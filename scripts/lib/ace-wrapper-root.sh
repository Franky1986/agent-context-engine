#!/usr/bin/env bash

ace_wrapper_local_root() {
  local script_dir="$1"
  if [[ -f "$script_dir/../SKILL.md" && "$(basename "$(dirname "$script_dir")")" = "agent-context-engine" && "$(basename "$(dirname "$(dirname "$script_dir")")")" = "skills" ]]; then
    (cd "$script_dir/../../../.." && pwd)
  else
    (cd "$script_dir/.." && pwd)
  fi
}

ace_resolve_wrapper_root() {
  local script_dir="$1"
  local invocation_path="$2"
  shift 2
  local invocation_name
  local resolved_invocation_path="$invocation_path"
  local local_root
  local canonical_name
  local canonical_invocation=0

  local_root="$(ace_wrapper_local_root "$script_dir")"
  if [[ -n "${AGENT_CONTEXT_ENGINE_ROOT:-}" ]]; then
    printf '%s\n' "$AGENT_CONTEXT_ENGINE_ROOT"
    return
  fi

  invocation_name="$(basename "$invocation_path")"
  if [[ "$resolved_invocation_path" != */* ]]; then
    resolved_invocation_path="$(command -v "$resolved_invocation_path" 2>/dev/null || printf '%s' "$resolved_invocation_path")"
  fi
  for canonical_name in "$@"; do
    if [[ "$invocation_name" = "$canonical_name" ]]; then
      canonical_invocation=1
      break
    fi
  done

  # Direct repo-local calls and instance-specific command names are pinned to
  # the installation that owns the wrapper script. Shared canonical symlinks
  # continue to follow the user-global active-root takeover contract.
  if [[ ! -L "$resolved_invocation_path" || "$canonical_invocation" -eq 0 ]]; then
    printf '%s\n' "$local_root"
    return
  fi

  local storage_root
  if [[ -n "${AGENT_CONTEXT_ENGINE_STORAGE_ROOT:-}" ]]; then
    storage_root="$AGENT_CONTEXT_ENGINE_STORAGE_ROOT"
  elif [[ -n "${AGENT_MEMORY_STORAGE_ROOT:-}" ]]; then
    storage_root="$AGENT_MEMORY_STORAGE_ROOT"
  else
    storage_root="$HOME"
  fi
  local active_root_file="$storage_root/.agent-context-engine/active-root"
  if [[ -f "$active_root_file" ]]; then
    cat "$active_root_file"
    return
  fi
  printf '%s\n' "$local_root"
}

ace_system_mode() {
  local root="$1"
  local cli="$2"
  local payload=""
  payload="$(env AGENT_CONTEXT_ENGINE_ROOT="$root" "$cli" system-status --json 2>/dev/null || true)"
  if [[ -z "$payload" ]] || ! command -v python3 >/dev/null 2>&1; then
    printf 'partial\n'
    return
  fi
  python3 -c 'import json, sys
try:
    payload = json.loads(sys.argv[1])
except Exception:
    print("partial")
else:
    print(str(payload.get("mode") or "partial"))' "$payload"
}

ace_print_suspended_warning() {
  local root="$1"
  local mode="$2"
  local language="${AGENT_CONTEXT_ENGINE_LANGUAGE:-}"
  if [[ -z "$language" && -f "$root/memory/local/installation-profile.json" ]] && command -v python3 >/dev/null 2>&1; then
    language="$(python3 -c 'import json, pathlib, sys
try:
    payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    raise SystemExit(0)
print(str((payload.get("monitor") or {}).get("language") or ""))' "$root/memory/local/installation-profile.json" 2>/dev/null || true)"
  fi
  case "$language" in
    de*)
      printf 'Agent Context Engine ist angehalten (Modus: %s). Normale Hooks und Hintergrundarbeit sind deaktiviert.\n' "$mode" >&2
      printf 'Es erfolgen keine Aktivierungs- oder Reparaturänderungen. Status: agent-context-engine system-status\n' >&2
      ;;
    *)
      printf 'Agent Context Engine is suspended (mode: %s). Normal hooks and background work are disabled.\n' "$mode" >&2
      printf 'No activation or repair changes will be made. Status: agent-context-engine system-status\n' >&2
      ;;
  esac
}
