#!/usr/bin/env bash
set -euo pipefail

# Skip hook when running inside an internal Agent Context Engine subprocess to
# avoid recursive logging and fake user-visible sessions.
if [ "${AGENT_MEMORY_DREAM:-0}" = "1" ] || [ "${AGENT_MEMORY_INTERNAL_RUN:-0}" = "1" ]; then
  exit 0
fi

ROOT="${AGENT_CONTEXT_ENGINE_ROOT:-}"
if [ -z "$ROOT" ]; then
  echo "claude hook adapter: AGENT_CONTEXT_ENGINE_ROOT is not set" >&2
  exit 0
fi

CLIENT="${AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT:-claude}"

SCRIPT="${AGENT_CONTEXT_ENGINE_SCRIPT:-}"
if [ -z "$SCRIPT" ]; then
  if [ -f "$ROOT/scripts/agent_context_engine.py" ]; then
    SCRIPT="$ROOT/scripts/agent_context_engine.py"
  elif [ -f "$ROOT/docs/skills/agent-context-engine/scripts/agent_context_engine.py" ]; then
    SCRIPT="$ROOT/docs/skills/agent-context-engine/scripts/agent_context_engine.py"
  else
    echo "claude hook adapter: cannot find agent_context_engine.py under $ROOT" >&2
    exit 0
  fi
fi

LOG="$ROOT/memory/logs/${CLIENT}-hook.err.log"
mkdir -p "$(dirname "$LOG")"
PAYLOAD_TMP="$(mktemp)"
TMPERR="$(mktemp)"
trap 'rm -f "$TMPERR" "$PAYLOAD_TMP"' EXIT
cat > "$PAYLOAD_TMP"

# Claude merges user-level and project-level hooks. During migrations both
# scopes can temporarily point at Agent Context Engine and deliver the exact
# same native payload. Keep that overlap idempotent at the adapter boundary.
DEDUP_ROOT="$ROOT/memory/runtime/hook-dedupe/${CLIENT}"
mkdir -p "$DEDUP_ROOT"

if command -v shasum >/dev/null 2>&1; then
  PAYLOAD_HASH="$(shasum -a 256 "$PAYLOAD_TMP" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  PAYLOAD_HASH="$(sha256sum "$PAYLOAD_TMP" | awk '{print $1}')"
else
  PAYLOAD_HASH=""
fi
if [ -n "$PAYLOAD_HASH" ]; then
  DEDUP_LOCK="$DEDUP_ROOT/$PAYLOAD_HASH.lock"
  if ! mkdir "$DEDUP_LOCK" 2>/dev/null; then
    if python3 - "$DEDUP_LOCK" <<'PY'
import sys
import time
from pathlib import Path

path = Path(sys.argv[1])
try:
    age = time.time() - path.stat().st_mtime
except OSError:
    raise SystemExit(0)
raise SystemExit(0 if age > 10 else 1)
PY
    then
      rm -rf "$DEDUP_LOCK"
      mkdir "$DEDUP_LOCK" 2>/dev/null || exit 0
    else
      exit 0
    fi
  fi
  touch "$DEDUP_LOCK"
fi

set +e
env AGENT_CONTEXT_ENGINE_ROOT="$ROOT" AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT="$CLIENT" AGENT_MEMORY_LAUNCH_CWD="${AGENT_MEMORY_LAUNCH_CWD:-${PWD}}" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}" python3 "$SCRIPT" log-hook --client "$CLIENT" \
  <"$PAYLOAD_TMP" \
  3</dev/null \
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

# Hook errors are non-blocking. Keep Claude Code usable and record diagnostics.
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] ${CLIENT} hook exit $CODE (see above)" >> "$LOG"
exit 0
