#!/usr/bin/env bash
set -euo pipefail

# Cursor hooks must never break the editor workflow. This wrapper logs the
# payload to the Agent Context Engine root and then returns the allow/continue JSON
# expected by before-hooks.
if [ "${AGENT_MEMORY_DREAM:-0}" = "1" ]; then
  printf '{}\n'
  exit 0
fi

ROOT='__ROOT__'
LOG="$ROOT/memory/logs/cursor-hook.err.log"
SCRIPT="$ROOT/scripts/agent_context_engine.py"
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="$ROOT/docs/skills/agent-context-engine/scripts/agent_context_engine.py"
fi
mkdir -p "$(dirname "$LOG")"
TMP="$(mktemp)"
TMPOUT="$(mktemp)"
trap 'rm -f "$TMP" "$TMPOUT"' EXIT
cat > "$TMP"

set +e
env AGENT_CONTEXT_ENGINE_ROOT="$ROOT" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}" python3 "$SCRIPT" log-hook --client cursor \
  < "$TMP" \
  3</dev/null \
  > "$TMPOUT" \
  2>>"$LOG"
CODE=$?
set -e

if [ "$CODE" != "0" ] && [ "$CODE" != "2" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cursor hook log failed code=$CODE" >> "$LOG"
fi

EVENT="$(python3 - "$TMP" <<'PY'
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as handle:
        data = json.load(handle)
except Exception:
    data = {}
for key in ("hook_event_name", "event_name", "hookName", "hook_name", "event", "type"):
    if data.get(key):
        print(data[key])
        break
PY
)"

case "$EVENT" in
  beforeSubmitPrompt)
    if [ -s "$TMPOUT" ]; then
      cat "$TMPOUT"
    elif [ "$CODE" = "2" ]; then
      printf '{"continue":false,"message":"Agent Context Engine blocked this prompt by policy."}\n'
    else
      printf '{"continue":true}\n'
    fi
    ;;
  beforeShellExecution|beforeMCPExecution|beforeReadFile)
    if [ "$CODE" = "2" ]; then
      printf '{"permission":"deny","message":"Agent Context Engine blocked this tool use by policy."}\n'
    else
      printf '{"permission":"allow"}\n'
    fi
    ;;
  *)
    printf '{}\n'
    ;;
esac
