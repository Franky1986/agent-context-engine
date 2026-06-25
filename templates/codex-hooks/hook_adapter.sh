#!/usr/bin/env bash
set -euo pipefail

# Skip hook when running inside an internal Agent Context Engine subprocess to
# avoid recursive logging and fake user-visible sessions.
if [ "${AGENT_MEMORY_DREAM:-0}" = "1" ] || [ "${AGENT_MEMORY_INTERNAL_RUN:-0}" = "1" ]; then
  exit 0
fi

ROOT="__AGENT_CONTEXT_ENGINE_ROOT__"
SCRIPT="__AGENT_MEMORY_SCRIPT__"
HOOKS_STATE="$ROOT/memory/local/hooks-state.json"
LOG="$ROOT/memory/logs/codex-hook.err.log"
mkdir -p "$(dirname "$LOG")"
TMPERR="$(mktemp)"
trap 'rm -f "$TMPERR"' EXIT

if ! python3 - "$HOOKS_STATE" codex <<'PY'
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
  exit 0
fi

set +e
env AGENT_CONTEXT_ENGINE_ROOT="$ROOT" AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT="${AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT:-}" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}" python3 "$SCRIPT" log-hook --client codex \
  2>"$TMPERR"
CODE=$?
set -e
cat "$TMPERR" >> "$LOG"

if [ "$CODE" = "2" ]; then
  if [ -s "$TMPERR" ]; then
    cat "$TMPERR" >&2
  else
    echo "Agent Context Engine blocked this tool use by policy." >&2
  fi
  exit 2
fi

if [ "$CODE" = "0" ]; then
  exit 0
fi

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] codex hook log failed" >> "$LOG"
exit 0
