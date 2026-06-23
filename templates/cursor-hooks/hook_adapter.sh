#!/usr/bin/env bash
set -euo pipefail

# Cursor hooks must never break the editor workflow. This wrapper logs the
# payload to the Agent Context Engine root and then returns the allow/continue JSON
# expected by before-hooks.
if [ "${AGENT_MEMORY_DREAM:-0}" = "1" ]; then
  printf '{}\n'
  exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOG="$ROOT/memory/logs/cursor-hook.err.log"
SCRIPT="$ROOT/scripts/agent_context_engine.py"
HOOKS_STATE="$ROOT/memory/local/hooks-state.json"
if [ ! -f "$SCRIPT" ]; then
  SCRIPT="$ROOT/docs/skills/agent-context-engine/scripts/agent_context_engine.py"
fi
mkdir -p "$(dirname "$LOG")"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
cat > "$TMP"

set +e
env AGENT_CONTEXT_ENGINE_ROOT="$ROOT" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}" python3 "$SCRIPT" log-hook --client cursor \
  < "$TMP" \
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

if ! python3 - "$HOOKS_STATE" cursor <<'PY'
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
  case "$EVENT" in
    beforeSubmitPrompt)
      printf '{"continue":true}\n'
      ;;
    beforeShellExecution|beforeMCPExecution|beforeReadFile)
      printf '{"permission":"allow"}\n'
      ;;
    *)
      printf '{}\n'
      ;;
  esac
  exit 0
fi

case "$EVENT" in
  beforeSubmitPrompt)
    if [ "$CODE" = "2" ]; then
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
