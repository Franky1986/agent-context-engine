#!/usr/bin/env bash
set -euo pipefail

if [ "${AGENT_MEMORY_DREAM:-0}" = "1" ] || [ "${AGENT_MEMORY_INTERNAL_RUN:-0}" = "1" ]; then
  printf '{}\n'
  exit 0
fi

EVENT="${1:-}"
ROOT="__AGENT_CONTEXT_ENGINE_ROOT__"
SCRIPT="__AGENT_MEMORY_SCRIPT__"
HOOKS_STATE="$ROOT/memory/local/hooks-state.json"
LOG="$ROOT/memory/logs/gemini-hook.err.log"
mkdir -p "$(dirname "$LOG")"
TMPIN="$(mktemp)"
TMPPAYLOAD="$(mktemp)"
TMPOUT="$(mktemp)"
TMPERR="$(mktemp)"
trap 'rm -f "$TMPIN" "$TMPPAYLOAD" "$TMPOUT" "$TMPERR"' EXIT

if ! python3 - "$HOOKS_STATE" gemini <<'PY'
import json
import sys
from pathlib import Path


path = Path(sys.argv[1])
runner = sys.argv[2]
if not path.exists():
    raise SystemExit(0)
try:
    state = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
if state.get("enabled") is False:
    raise SystemExit(1)
runner_state = state.get("runners", {}).get(runner)
if isinstance(runner_state, dict) and runner_state.get("enabled") is False:
    raise SystemExit(1)
if runner_state is False:
    raise SystemExit(1)
raise SystemExit(0)
PY
then
  printf '{}\n'
  exit 0
fi

cat > "$TMPIN"

python3 - "$EVENT" "$TMPIN" > "$TMPPAYLOAD" <<'PY'
import json
import sys


EVENT = sys.argv[1] if len(sys.argv) > 1 else ""
PAYLOAD_PATH = sys.argv[2]


def read_payload(path: str) -> dict:
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:8000], "invalid_json": True}
    return loaded if isinstance(loaded, dict) else {"payload": loaded}


def canonical_event_name(original: str) -> str:
    mapping = {
        "SessionStart": "SessionStart",
        "BeforeAgent": "UserPromptSubmit",
        "BeforeTool": "PreToolUse",
        "AfterTool": "PostToolUse",
        "Notification": "Notification",
        "AfterAgent": "Stop",
    }
    return mapping.get(original, original or "unknown")


def first_text(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return "\n".join(chunks).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message"):
            text = first_text(value.get(key))
            if text:
                return text
    return ""


def last_user_prompt(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "text", "message"):
        text = first_text(payload.get(key))
        if text:
            return text
    llm_request = payload.get("llm_request")
    if not isinstance(llm_request, dict):
        return ""
    messages = llm_request.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "").lower() != "user":
            continue
        text = first_text(message.get("content"))
        if text:
            return text
    return ""


payload = read_payload(PAYLOAD_PATH)
original_event = EVENT or str(payload.get("hook_event_name") or payload.get("event_name") or "")
canonical = canonical_event_name(original_event)
transformed = dict(payload)
transformed["hook_event_name"] = canonical
transformed["event_name"] = canonical
transformed["gemini_hook_event_name"] = original_event

for source_key in ("session_id", "sessionId", "conversation_id", "conversationId"):
    value = payload.get(source_key)
    if value:
        transformed["session_id"] = str(value)
        break

for source_key in ("cwd", "workdir", "workspace_root", "workspaceRoot"):
    value = payload.get(source_key)
    if isinstance(value, str) and value.strip():
        transformed["cwd"] = value
        break

tool_name = payload.get("tool_name") or payload.get("toolName") or payload.get("tool")
if tool_name:
    transformed["tool_name"] = tool_name
tool_input = payload.get("tool_input")
if tool_input is None:
    tool_input = payload.get("toolInput")
if tool_input is None:
    tool_input = payload.get("tool_args")
if tool_input is None:
    tool_input = payload.get("toolArgs")
if tool_input is not None:
    transformed["tool_input"] = tool_input
tool_response = payload.get("tool_response")
if tool_response is None:
    tool_response = payload.get("toolResponse")
if tool_response is None:
    tool_response = payload.get("tool_output")
if tool_response is None:
    tool_response = payload.get("toolOutput")
if tool_response is not None:
    transformed["tool_response"] = tool_response

if canonical == "UserPromptSubmit" and not transformed.get("prompt"):
    prompt = last_user_prompt(payload)
    if prompt:
        transformed["prompt"] = prompt

print(json.dumps(transformed, ensure_ascii=False))
PY

set +e
env AGENT_CONTEXT_ENGINE_ROOT="$ROOT" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}" python3 "$SCRIPT" log-hook --client gemini \
  < "$TMPPAYLOAD" \
  > "$TMPOUT" \
  2> "$TMPERR"
CODE=$?
set -e
cat "$TMPERR" >> "$LOG"

python3 - "$EVENT" "$TMPOUT" "$TMPERR" "$CODE" <<'PY'
import json
import sys


event = sys.argv[1] if len(sys.argv) > 1 else ""
stdout_path, stderr_path, code_text = sys.argv[2:5]
code = int(code_text or "0")
stdout = open(stdout_path, "r", encoding="utf-8", errors="replace").read().strip()
stderr = open(stderr_path, "r", encoding="utf-8", errors="replace").read().strip()


def block_message() -> str:
    return stderr or "Agent Context Engine blocked this tool use by policy."


def print_passthrough_json(raw: str) -> bool:
    if not raw:
        return False
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    hook_specific = payload.get("hookSpecificOutput")
    if isinstance(hook_specific, dict) and hook_specific.get("hookEventName"):
        hook_specific["hookEventName"] = event or str(hook_specific.get("hookEventName"))
        payload["hookSpecificOutput"] = hook_specific
    print(json.dumps(payload, ensure_ascii=False))
    return True


if code == 2:
    message = block_message()
    if event == "BeforeTool":
        print(
            json.dumps(
                {
                    "decision": "deny",
                    "reason": message,
                    "systemMessage": "Agent Context Engine blocked this tool use by policy.",
                },
                ensure_ascii=False,
            )
        )
        sys.exit(0)
    if message:
        print(message, file=sys.stderr)
    sys.exit(2)

if code == 0 and print_passthrough_json(stdout):
    sys.exit(0)

print("{}")
PY
