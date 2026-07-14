#!/usr/bin/env bash
set -euo pipefail

# Central hook adapter hub for gemini.
# This script is intentionally stable and lives in the central storage directory.
# It resolves the active Agent Context Engine installation at runtime and
# delegates to the installation-specific template.
# spec_version=__HUB_SPEC_VERSION__

RUNNER="gemini"

# Resolve symlinks so direct runner and IDE hooks remain pinned to the hub they
# were activated against, including isolated installations.
SOURCE="${BASH_SOURCE[0]}"
while [[ -L "$SOURCE" ]]; do
  DIR="$(cd "$(dirname "$SOURCE")" && pwd)"
  SOURCE="$(readlink "$SOURCE")"
  [[ "$SOURCE" != /* ]] && SOURCE="$DIR/$SOURCE"
done
HUB_DIR="$(cd "$(dirname "$SOURCE")" && pwd)"

if [ -n "${AGENT_CONTEXT_ENGINE_STORAGE_ROOT:-}" ]; then
  STORAGE_ROOT="${AGENT_CONTEXT_ENGINE_STORAGE_ROOT}"
elif [ -n "${AGENT_MEMORY_STORAGE_ROOT:-}" ]; then
  STORAGE_ROOT="${AGENT_MEMORY_STORAGE_ROOT}"
elif [ "$(basename "$(dirname "$(dirname "$HUB_DIR")")")" = ".agent-context-engine" ]; then
  STORAGE_ROOT="$(cd "$HUB_DIR/../../.." && pwd)"
else
  STORAGE_ROOT="$HOME"
fi

ACTIVE_ROOT_FILE="$STORAGE_ROOT/.agent-context-engine/active-root"

if [ -n "${AGENT_CONTEXT_ENGINE_ROOT:-}" ]; then
  ROOT="${AGENT_CONTEXT_ENGINE_ROOT}"
elif [ -f "$ACTIVE_ROOT_FILE" ]; then
  ROOT="$(cat "$ACTIVE_ROOT_FILE")"
else
  echo "${RUNNER}-hub: cannot find active Agent Context Engine root. Set AGENT_CONTEXT_ENGINE_ROOT or run install/repair." >&2
  exit 0
fi

if [ ! -d "$ROOT" ]; then
  echo "${RUNNER}-hub: active root does not exist: $ROOT" >&2
  exit 0
fi

export AGENT_CONTEXT_ENGINE_ROOT="$ROOT"
export AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT="${AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT:-$RUNNER}"
export AGENT_MEMORY_LAUNCH_CWD="${AGENT_MEMORY_LAUNCH_CWD:-${PWD}}"

if [ -z "${AGENT_CONTEXT_ENGINE_SCRIPT:-}" ]; then
  if [ -f "$ROOT/scripts/agent_context_engine.py" ]; then
    export AGENT_CONTEXT_ENGINE_SCRIPT="$ROOT/scripts/agent_context_engine.py"
  elif [ -f "$ROOT/docs/skills/agent-context-engine/scripts/agent_context_engine.py" ]; then
    export AGENT_CONTEXT_ENGINE_SCRIPT="$ROOT/docs/skills/agent-context-engine/scripts/agent_context_engine.py"
  fi
fi

TEMPLATE="$ROOT/templates/__RUNNER__-hooks/hook_adapter.sh"
if [ ! -f "$TEMPLATE" ]; then
  echo "${RUNNER}-hub: missing template $TEMPLATE" >&2
  exit 0
fi

exec /usr/bin/env bash "$TEMPLATE" "$@"
