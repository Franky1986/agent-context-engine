#!/usr/bin/env bash
set -euo pipefail

if [ "${AGENT_MEMORY_DREAM:-0}" = "1" ]; then
  printf '{}\n'
  exit 0
fi

EVENT="${1:-}"
WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MEMORY_ROOT="${AGENT_CONTEXT_ENGINE_ROOT:-__AGENT_CONTEXT_ENGINE_ROOT__}"
HOOKS_STATE="$MEMORY_ROOT/memory/local/hooks-state.json"
LOG="$MEMORY_ROOT/memory/logs/antigravity-hook.err.log"
STATE_DIR="$WORKSPACE_ROOT/.agents/hooks/.agent-memory-state"
mkdir -p "$(dirname "$LOG")" "$STATE_DIR"
TMPIN="$(mktemp)"
TMPPAYLOAD="$(mktemp)"
TMPOUT="$(mktemp)"
TMPERR="$(mktemp)"
trap 'rm -f "$TMPIN" "$TMPPAYLOAD" "$TMPOUT" "$TMPERR"' EXIT

if ! python3 - "$HOOKS_STATE" antigravity <<'PY'
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

python3 - "$EVENT" "$TMPIN" "$WORKSPACE_ROOT" > "$TMPPAYLOAD" <<'PY'
import json
import os
import sys


EVENT = sys.argv[1] if len(sys.argv) > 1 else ""
PAYLOAD_PATH = sys.argv[2]
WORKSPACE_ROOT = sys.argv[3] if len(sys.argv) > 3 else ""


def read_payload(path: str) -> dict:
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    if not raw.strip():
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw[:8000], "invalid_json": True}
    return loaded if isinstance(loaded, dict) else {"payload": loaded}


def first_text(value: object) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = first_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in (
            "text",
            "message",
            "userMessage",
            "ephemeralMessage",
            "content",
            "prompt",
            "value",
        ):
            text = first_text(value.get(key))
            if text:
                return text
    return ""


def workspace_cwd(payload: dict) -> str:
    paths = payload.get("workspacePaths")
    if isinstance(paths, list):
        for item in paths:
            if isinstance(item, str) and item.strip():
                return item
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        for key in ("current_dir", "project_dir", "cwd"):
            value = workspace.get(key)
            if isinstance(value, str) and value.strip():
                return value
    for key in ("cwd", "workdir", "workingDirectory"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return WORKSPACE_ROOT


def conversation_id(payload: dict) -> str:
    for key in ("conversationId", "conversation_id", "session_id", "sessionId"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def canonical_tool_name(raw: object) -> str:
    value = str(raw or "").strip()
    mapping = {
        "run_command": "exec_command",
        "command": "exec_command",
    }
    return mapping.get(value, value)


def tool_payload(payload: dict) -> tuple[str, object, object]:
    tool_call = payload.get("toolCall")
    if isinstance(tool_call, dict):
        return (
            canonical_tool_name(tool_call.get("name")),
            tool_call.get("args"),
            payload.get("result"),
        )
    return (
        canonical_tool_name(payload.get("tool_name") or payload.get("toolName") or payload.get("tool")),
        payload.get("tool_input") if "tool_input" in payload else payload.get("toolInput"),
        payload.get("tool_response") if "tool_response" in payload else payload.get("toolResponse"),
    )


def invocation_prompt(payload: dict) -> str:
    for key in ("prompt", "userPrompt", "user_prompt", "message", "input"):
        text = first_text(payload.get(key))
        if text:
            return text
    request = payload.get("request")
    if isinstance(request, dict):
        for key in ("prompt", "message", "input"):
            text = first_text(request.get(key))
            if text:
                return text
    invocation = payload.get("invocation")
    if isinstance(invocation, dict):
        for key in ("prompt", "message", "input"):
            text = first_text(invocation.get(key))
            if text:
                return text
    return ""


payload = read_payload(PAYLOAD_PATH)
session_id = conversation_id(payload)
cwd = workspace_cwd(payload)
tool_name, tool_input, tool_response = tool_payload(payload)
prompt = invocation_prompt(payload)
transformed = dict(payload)
transformed["session_id"] = session_id
transformed["cwd"] = cwd
transformed["transcript_path"] = str(payload.get("transcriptPath") or payload.get("transcript_path") or "")
transformed["tool_name"] = tool_name
if tool_input is not None:
    transformed["tool_input"] = tool_input
if tool_response is not None:
    transformed["tool_response"] = tool_response
if prompt:
    transformed["prompt"] = prompt

mapping = {
    "PreInvocation": "UserPromptSubmit",
    "PreToolUse": "PreToolUse",
    "PostToolUse": "PostToolUse",
    "PostInvocation": "Notification",
    "Stop": "Stop",
}
canonical = mapping.get(EVENT, EVENT or "unknown")
transformed["hook_event_name"] = canonical
transformed["event_name"] = canonical
transformed["antigravity_hook_event_name"] = EVENT
print(json.dumps(transformed, ensure_ascii=False))
PY

run_hook() {
  local client_event="$1"
  local output_target="$2"
  set +e
  env AGENT_CONTEXT_ENGINE_ROOT="$MEMORY_ROOT" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}" python3 "$MEMORY_ROOT/__AGENT_MEMORY_SCRIPT__" log-hook --client antigravity \
    < "$TMPPAYLOAD" \
    > "$output_target" \
    2> "$TMPERR"
  local code=$?
  set -e
  cat "$TMPERR" >> "$LOG"
  printf '%s' "$code"
}

python3 - "$TMPPAYLOAD" "$STATE_DIR" > /dev/null <<'PY'
import hashlib
import json
import sys
from pathlib import Path


payload_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace") or "{}")
conversation_id = str(payload.get("session_id") or "")
if conversation_id:
    marker = state_dir / (hashlib.sha256(conversation_id.encode("utf-8")).hexdigest() + ".started")
    if str(payload.get("hook_event_name") or "") == "Stop":
        marker.unlink(missing_ok=True)
PY

START_CODE=0
START_OUT=""
if [ "$EVENT" = "PreInvocation" ]; then
  FIRST_PROMPT="$(python3 - "$TMPPAYLOAD" "$STATE_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path


payload_path = Path(sys.argv[1])
state_dir = Path(sys.argv[2])
payload = json.loads(payload_path.read_text(encoding="utf-8", errors="replace") or "{}")
conversation_id = str(payload.get("session_id") or "")
if not conversation_id:
    print("0")
    raise SystemExit
marker = state_dir / (hashlib.sha256(conversation_id.encode("utf-8")).hexdigest() + ".started")
if marker.exists():
    print("0")
else:
    marker.write_text(conversation_id + "\n", encoding="utf-8")
    print("1")
PY
)"
  if [ "$FIRST_PROMPT" = "1" ]; then
    python3 - "$TMPPAYLOAD" > "$TMPIN" <<'PY'
import json
import sys

payload = json.loads(open(sys.argv[1], "r", encoding="utf-8", errors="replace").read() or "{}")
payload["hook_event_name"] = "SessionStart"
payload["event_name"] = "SessionStart"
print(json.dumps(payload, ensure_ascii=False))
PY
    mv "$TMPIN" "$TMPPAYLOAD"
    START_CODE="$(run_hook SessionStart "$TMPOUT")"
    START_OUT="$(cat "$TMPOUT")"
    python3 - "$TMPPAYLOAD" "$EVENT" "$WORKSPACE_ROOT" > "$TMPIN" <<'PY'
import json
import os
import sys

payload = json.loads(open(sys.argv[1], "r", encoding="utf-8", errors="replace").read() or "{}")
event = sys.argv[2]
workspace_root = sys.argv[3]
payload["hook_event_name"] = "UserPromptSubmit"
payload["event_name"] = "UserPromptSubmit"
payload["antigravity_hook_event_name"] = event
payload["cwd"] = payload.get("cwd") or workspace_root
print(json.dumps(payload, ensure_ascii=False))
PY
    mv "$TMPIN" "$TMPPAYLOAD"
  fi
fi

CODE="$(run_hook "$EVENT" "$TMPOUT")"
OUT="$(cat "$TMPOUT")"

python3 - "$EVENT" "$START_CODE" "$START_OUT" "$CODE" "$OUT" "$TMPERR" <<'PY'
import json
import sys


event = sys.argv[1]
start_code = int(sys.argv[2] or "0")
start_out = sys.argv[3]
code = int(sys.argv[4] or "0")
stdout = sys.argv[5]
stderr_path = sys.argv[6]
stderr = open(stderr_path, "r", encoding="utf-8", errors="replace").read().strip()


def extract_context(raw: str) -> str:
    if not raw.strip():
        return ""
    for line in raw.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        context = (
            payload.get("hookSpecificOutput", {})
            .get("additionalContext", "")
        )
        if isinstance(context, str) and context.strip():
            return context.strip()
    return ""


def block_message() -> str:
    return stderr or "Agent Context Engine blocked this tool use by policy."


if event == "PreToolUse":
    if code == 2:
        print(json.dumps({"decision": "deny", "reason": block_message()}, ensure_ascii=False))
    else:
        context = extract_context(stdout)
        payload = {"decision": "allow"}
        if context:
            payload["reason"] = context
        print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

if event == "PreInvocation":
    parts = []
    if start_code == 0:
        context = extract_context(start_out)
        if context:
            parts.append({"ephemeralMessage": context})
    elif start_code == 2:
        parts.append({"ephemeralMessage": block_message()})
    context = extract_context(stdout)
    if context:
        parts.append({"ephemeralMessage": context})
    print(json.dumps({"injectSteps": parts}, ensure_ascii=False))
    raise SystemExit(0)

if event == "PostInvocation":
    context = extract_context(stdout)
    payload = {"injectSteps": []}
    if context:
        payload["injectSteps"].append({"ephemeralMessage": context})
        payload["terminationBehavior"] = ""
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0)

print("{}")
PY
