from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess
from typing import Any

from ..adapters.runners.cursor import CURSOR_EVENTS, cursor_hook_entry, cursor_paths, enable_cursor_hooks, is_agent_memory_cursor_hook, load_cursor_hooks, write_cursor_hooks
from .hooks_state import hook_runner_status
from ..infrastructure.config import ANTIGRAVITY_DREAM_MODEL, OPENCODE_DREAM_MODEL, ROOT, SCRIPT_PATH, SKILL_ROOT, sh_quote
from .instance_profile import agent_memory_cli_for_root, load_installation_profile, preferred_agent_memory_cli_for_root, resolve_runner_wrapper_name, resolve_wrapper_command_name


GEMINI_MINI_PREFERENCE = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"]
OPENCODE_DEFAULT_PROVIDER = "ollama"
OPENCODE_DEFAULT_MODEL = os.environ.get("AGENT_MEMORY_OPENCODE_DEFAULT_MODEL", "")
OPENCODE_DEFAULT_SMALL_MODEL = os.environ.get("AGENT_MEMORY_OPENCODE_SMALL_MODEL", "")
INTEGRATION_PROJECTS_REGISTRY = Path("memory") / "status" / "integration-projects.json"
INTEGRATION_HISTORY_PATH = Path("memory") / "status" / "integration-history.jsonl"


def _root_prefixed(command: str, *, root: Path = ROOT) -> str:
    return f"cd {sh_quote(str(root.resolve()))} && {command}"


def _agent_memory_cli_display(root: Path = ROOT) -> str:
    return preferred_agent_memory_cli_for_root(root)


def workspace_binding_path(client: str, *, root: Path = ROOT) -> Path | None:
    client = str(client or "").strip().lower()
    if client == "codex":
        return root / ".codex" / "agent-memory-binding.json"
    if client == "claude":
        return root / ".claude" / "agent-memory-binding.json"
    if client == "cursor":
        return root / ".cursor" / "agent-memory-binding.json"
    return None


def write_workspace_binding(client: str, *, root: Path = ROOT, memory_root: Path = ROOT, written_by: str = "install") -> Path | None:
    binding_path = workspace_binding_path(client, root=root)
    if binding_path is None:
        return None
    profile = load_installation_profile(memory_root)
    payload = {
        "version": 1,
        "client": client,
        "instance_id": str(profile.get("instance_id") or memory_root.name),
        "memory_root": str(memory_root.resolve()),
        "agent_memory_cli": str((memory_root / agent_memory_cli_for_root(memory_root).replace("./", "")).resolve()),
        "written_at": _utc_timestamp(),
        "written_by": written_by,
    }
    binding_path.parent.mkdir(parents=True, exist_ok=True)
    binding_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return binding_path


def workspace_binding_status(client: str, *, root: Path = ROOT, expected_memory_root: Path | None = None) -> dict[str, Any]:
    binding_path = workspace_binding_path(client, root=root)
    if binding_path is None:
        return {
            "hook_binding_path": "",
            "hook_binding_state": "not_applicable",
            "hook_binding_target_root": "",
            "hook_binding_target_instance": "",
            "hook_binding_target_exists": False,
            "hook_binding_target_cli_exists": False,
            "hook_binding_last_error": "",
        }
    payload: dict[str, Any] = {}
    if not binding_path.exists():
        return {
            "hook_binding_path": str(binding_path),
            "hook_binding_state": "missing",
            "hook_binding_target_root": "",
            "hook_binding_target_instance": "",
            "hook_binding_target_exists": False,
            "hook_binding_target_cli_exists": False,
            "hook_binding_last_error": "",
        }
    try:
        payload = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "hook_binding_path": str(binding_path),
            "hook_binding_state": "invalid_json",
            "hook_binding_target_root": "",
            "hook_binding_target_instance": "",
            "hook_binding_target_exists": False,
            "hook_binding_target_cli_exists": False,
            "hook_binding_last_error": str(exc),
        }
    target_root_text = str(payload.get("memory_root") or "").strip()
    instance_id = str(payload.get("instance_id") or "").strip()
    cli_text = str(payload.get("agent_memory_cli") or "").strip()
    try:
        target_root = Path(target_root_text).expanduser().resolve() if target_root_text else None
    except OSError as exc:
        return {
            "hook_binding_path": str(binding_path),
            "hook_binding_state": "invalid_json",
            "hook_binding_target_root": target_root_text,
            "hook_binding_target_instance": instance_id,
            "hook_binding_target_exists": False,
            "hook_binding_target_cli_exists": False,
            "hook_binding_last_error": str(exc),
        }
    target_exists = bool(target_root and target_root.exists())
    target_cli_exists = bool(cli_text and Path(cli_text).expanduser().exists())
    state = "bound"
    if target_root is None:
        state = "invalid_json"
    elif expected_memory_root is not None and target_root.resolve() != expected_memory_root.resolve():
        state = "root_mismatch"
    elif not target_exists:
        state = "missing_target_root"
    elif not target_cli_exists:
        state = "missing_target_cli"
    return {
        "hook_binding_path": str(binding_path),
        "hook_binding_state": state,
        "hook_binding_target_root": str(target_root) if target_root else target_root_text,
        "hook_binding_target_instance": instance_id,
        "hook_binding_target_exists": target_exists,
        "hook_binding_target_cli_exists": target_cli_exists,
        "hook_binding_last_error": "",
    }


def _effective_binding_hooks_state(local_state: str, binding_state: str) -> tuple[str, bool]:
    if local_state in {"disabled", "not_prepared", "configured_without_agent_memory"}:
        return local_state, local_state == "enabled"
    if binding_state in {"not_applicable", "bound"}:
        return local_state, local_state == "enabled"
    if binding_state == "missing":
        return "inactive_missing_binding", False
    if binding_state == "invalid_json":
        return "inactive_invalid_binding", False
    if binding_state == "missing_target_cli":
        return "inactive_missing_cli", False
    if binding_state in {"missing_target_root", "root_mismatch"}:
        return "inactive_missing_target", False
    return local_state, local_state == "enabled"


def integration_hook_command(*, client: str, action: str, target_root: Path | None = None, root: Path = ROOT) -> str:
    command = f"{_agent_memory_cli_display(root)} integration-hooks --client {client} --action {action}"
    if target_root is not None:
        command += f" --target {sh_quote(str(target_root.resolve()))}"
    return _root_prefixed(command, root=root)


def _cursor_hook_wrapper(memory_root: Path) -> str:
    return f"""#!/usr/bin/env bash
set -euo pipefail
ROOT={sh_quote(str(memory_root.resolve()))}
SCRIPT={sh_quote(str(Path(SCRIPT_PATH).resolve()))}
HOOKS_STATE="$ROOT/memory/local/hooks-state.json"
AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${{AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}}"
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
runner_state = state.get("runners", {{}}).get(runner)
if isinstance(runner_state, dict) and runner_state.get("enabled") is False:
    raise SystemExit(1)
if runner_state is False:
    raise SystemExit(1)
raise SystemExit(0)
PY
then
  exit 0
fi
cd "$ROOT"
exec env AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="$AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC" python3 "$SCRIPT" log-hook --client cursor --detect-version
"""


def _global_wrapper_status(command_name: str) -> dict[str, Any]:
    resolved = shutil.which(command_name)
    return {
        "global_command_name": command_name,
        "global_command_available": resolved is not None,
        "global_command_path": resolved or "",
    }


def _global_wrapper_activation(command_name: str, *, root: Path = ROOT) -> dict[str, Any]:
    return {
        "global_activation_command": _root_prefixed(f"{_agent_memory_cli_display(root)} global-wrapper-enable {command_name}", root=root),
        "global_deactivation_command": _root_prefixed(f"{_agent_memory_cli_display(root)} global-wrapper-disable {command_name}", root=root),
        "global_status_command": _root_prefixed(f"{_agent_memory_cli_display(root)} global-wrapper-status", root=root),
    }


def _wrapper_paths(wrapper_command: str, *, root: Path = ROOT) -> dict[str, Any]:
    command = wrapper_command.strip()
    script_path = root / command[2:] if command.startswith("./") else root / command
    return {
        "wrapper_command": command,
        "wrapper_path": str(script_path),
        "wrapper_path_exists": script_path.exists(),
    }


def _resolved_global_wrapper_name(client: str, *, root: Path = ROOT) -> str:
    return resolve_runner_wrapper_name(client, root=root)


def _shell_wrapper_state(
    *,
    executable_name: str,
    wrapper_command: str,
    hooks_state: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    executable = shutil.which(executable_name)
    global_command_name = resolve_wrapper_command_name(wrapper_command.replace("./scripts/", ""), root=root)
    global_status = _global_wrapper_status(global_command_name)
    wrapper_paths = _wrapper_paths(wrapper_command, root=root)
    if not wrapper_paths["wrapper_path_exists"]:
        wrapper_state = "not_prepared"
    elif executable is None:
        wrapper_state = "runner_missing"
    elif hooks_state in {"disabled", "configured_without_agent_memory", "not_prepared"}:
        wrapper_state = "blocked_by_hooks"
    elif global_status["global_command_available"]:
        wrapper_state = "global_active"
    else:
        wrapper_state = "root_active"
    return {
        **global_status,
        **_global_wrapper_activation(global_command_name, root=root),
        **wrapper_paths,
        "wrapper_state": wrapper_state,
        "wrapper_ready": wrapper_state in {"global_active", "root_active"},
    }


def _simple_wrapper_state(
    *,
    executable_name: str,
    wrapper_command: str,
    root: Path = ROOT,
) -> dict[str, Any]:
    executable = shutil.which(executable_name)
    global_command_name = resolve_wrapper_command_name(wrapper_command.replace("./scripts/", ""), root=root)
    global_status = _global_wrapper_status(global_command_name)
    wrapper_paths = _wrapper_paths(wrapper_command, root=root)
    if not wrapper_paths["wrapper_path_exists"]:
        wrapper_state = "not_prepared"
    elif executable is None:
        wrapper_state = "runner_missing"
    elif global_status["global_command_available"]:
        wrapper_state = "global_active"
    else:
        wrapper_state = "root_active"
    return {
        **global_status,
        **_global_wrapper_activation(global_command_name, root=root),
        **wrapper_paths,
        "wrapper_state": wrapper_state,
        "wrapper_ready": wrapper_state in {"global_active", "root_active"},
    }


def _apply_hook_control_status(item: dict[str, Any], *, client: str, root: Path = ROOT) -> dict[str, Any]:
    control = hook_runner_status(client, root=root)
    local_hooks_state = str(item.get("hook_local_state") or item.get("hooks_state") or "not_prepared")
    effective_hooks_state = str(item.get("hook_effective_state") or item.get("hooks_state") or local_hooks_state)
    if not control["enabled"] and effective_hooks_state == "enabled":
        effective_hooks_state = "disabled_by_control_plane"
    item["hook_config_state"] = local_hooks_state
    item["hooks_state"] = effective_hooks_state
    item["hooks_control_state"] = "enabled" if control["enabled"] else "disabled"
    item["hooks_control_source"] = control["source"]
    item["hooks_control_disabled_at"] = control.get("disabled_at")
    item["hooks_control_disabled_by"] = control.get("disabled_by")
    item["hooks_control_reason"] = control.get("reason") or ""
    item["hooks_enabled"] = effective_hooks_state == "enabled" and bool(control["enabled"])
    if not item["hooks_enabled"] and str(item.get("wrapper_state") or "") in {"global_active", "root_active"}:
        item["wrapper_state"] = "blocked_by_hooks"
        item["wrapper_ready"] = False
    return item


def _agent_memory_script_for_root(memory_root: Path) -> str:
    if (memory_root / "scripts" / "agent_context_engine.py").exists():
        return "scripts/agent_context_engine.py"
    return "docs/skills/agent-context-engine/scripts/agent_context_engine.py"


def _agent_memory_script_absolute_path(memory_root: Path) -> Path:
    return (memory_root / _agent_memory_script_for_root(memory_root)).resolve()


def _render_shell_hook_script(client: str, *, memory_root: Path) -> str:
    spec = _hook_spec(client)
    return (
        spec["template_script"].read_text(encoding="utf-8")
        .replace("__AGENT_CONTEXT_ENGINE_ROOT__", str(memory_root.resolve()))
        .replace("__AGENT_MEMORY_SCRIPT__", str(_agent_memory_script_absolute_path(memory_root)))
    )


def shell_hook_adapter_status(client: str, *, root: Path = ROOT, memory_root: Path | None = None) -> dict[str, Any]:
    spec = _hook_spec(client, root=root)
    script_path: Path = spec["script_path"]
    expected_memory_root = (memory_root or root).resolve()
    expected_script = _agent_memory_script_absolute_path(expected_memory_root)
    if not script_path.exists():
        return {
            "exists": False,
            "managed": False,
            "status": "missing",
            "expected_root": str(expected_memory_root),
            "expected_script": str(expected_script),
            "detected_root": "",
            "detected_script": "",
        }
    text = script_path.read_text(encoding="utf-8", errors="replace")
    managed = f"log-hook --client {client}" in text
    detected_root = ""
    detected_script = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ROOT="):
            detected_root = stripped.split("=", 1)[1].strip().strip('"').strip("'")
        if stripped.startswith("SCRIPT="):
            detected_script = stripped.split("=", 1)[1].strip().strip('"').strip("'")
    status = "ok"
    if not managed:
        status = "unmanaged"
    elif detected_root != str(expected_memory_root):
        status = "root_mismatch"
    elif detected_script != str(expected_script):
        status = "script_mismatch"
    return {
        "exists": True,
        "managed": managed,
        "status": status,
        "expected_root": str(expected_memory_root),
        "expected_script": str(expected_script),
        "detected_root": detected_root,
        "detected_script": detected_script,
    }


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _integration_projects_registry_path(root: Path = ROOT) -> Path:
    return root / INTEGRATION_PROJECTS_REGISTRY


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_integration_projects_registry(root: Path = ROOT) -> dict[str, Any]:
    path = _integration_projects_registry_path(root)
    if not path.exists():
        return {"version": 1, "clients": {}}
    try:
        payload = _read_json(path)
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "clients": {}}
    if not isinstance(payload, dict):
        return {"version": 1, "clients": {}}
    clients = payload.get("clients")
    if not isinstance(clients, dict):
        payload["clients"] = {}
    payload.setdefault("version", 1)
    return payload


def _save_integration_projects_registry(payload: dict[str, Any], root: Path = ROOT) -> None:
    _write_json(_integration_projects_registry_path(root), payload)


def _integration_history_path(root: Path = ROOT) -> Path:
    return root / INTEGRATION_HISTORY_PATH


def append_integration_history(
    *,
    client: str,
    action: str,
    root: Path = ROOT,
    target: Path | None = None,
    source: str = "system",
    actor: str = "agent-memory",
    details: dict[str, Any] | None = None,
) -> None:
    payload = {
        "timestamp": _utc_timestamp(),
        "client": str(client or "").strip().lower(),
        "action": str(action or "").strip().lower(),
        "source": str(source or "system"),
        "actor": str(actor or "agent-memory"),
        "root": str(root.resolve()),
        "target_path": str(target.expanduser().resolve()) if target is not None else "",
        "details": details or {},
    }
    path = _integration_history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def integration_history(*, root: Path = ROOT, client: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    path = _integration_history_path(root)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        if client and str(item.get("client") or "").strip().lower() != client.strip().lower():
            continue
        rows.append(item)
    rows.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return rows[: max(1, min(limit, 100))]


def register_integration_project(client: str, target: Path, *, memory_root: Path = ROOT) -> None:
    client = str(client or "").strip().lower()
    target = target.expanduser().resolve()
    payload = _load_integration_projects_registry(memory_root)
    clients = payload.setdefault("clients", {})
    entries = clients.setdefault(client, [])
    if not isinstance(entries, list):
        entries = []
        clients[client] = entries
    target_path = str(target)
    updated = False
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("path") or "") == target_path:
            entry = {
                **entry,
                "path": target_path,
                "name": target.name or target_path,
                "updated_at": _utc_timestamp(),
            }
            updated = True
        normalized.append(entry)
    if not updated:
        normalized.append(
            {
                "path": target_path,
                "name": target.name or target_path,
                "updated_at": _utc_timestamp(),
            }
        )
    clients[client] = normalized
    _save_integration_projects_registry(payload, memory_root)


def unregister_integration_project(client: str, target: Path, *, memory_root: Path = ROOT) -> None:
    # Keep known projects in the registry even after hooks are disabled so the
    # monitor can show stable x-of-y counts and let operators re-enable hooks
    # without the project disappearing from the UI.
    register_integration_project(client, target, memory_root=memory_root)


def _project_activation_entry(client: str, target_path: str) -> dict[str, Any]:
    target = Path(target_path).expanduser()
    resolved = target.resolve()
    item: dict[str, Any] = {
        "path": str(resolved),
        "name": resolved.name or str(resolved),
        "exists": resolved.exists(),
    }
    if not resolved.exists():
        item["hooks_state"] = "project_missing"
        return item
    if client == "cursor":
        status = _cursor_status_with_hooks(root=resolved)
    elif client == "antigravity":
        status = _antigravity_hook_status(root=resolved)
    elif client == "opencode":
        status = _opencode_hook_status(root=resolved)
    else:
        status = {"hooks_state": "not_supported", "prepared": False, "hook_config_path": "", "hook_disabled_path": "", "active_hook_events": []}
    item.update(
        {
            "hooks_state": status.get("hooks_state", "unknown"),
            "prepared": bool(status.get("prepared")),
            "hooks_enabled": bool(status.get("hooks_enabled")),
            "hook_config_path": str(status.get("hook_config_path") or ""),
            "hook_disabled_path": str(status.get("hook_disabled_path") or ""),
            "active_hook_events": list(status.get("active_hook_events") or []),
        }
    )
    return item


def integration_projects_status(client: str, *, memory_root: Path = ROOT, current_root: Path | None = None) -> dict[str, Any]:
    client = str(client or "").strip().lower()
    payload = _load_integration_projects_registry(memory_root)
    raw_entries = payload.get("clients", {}).get(client, [])
    paths: list[str] = []
    if isinstance(raw_entries, list):
        for entry in raw_entries:
            if isinstance(entry, dict):
                path = str(entry.get("path") or "").strip()
                if path:
                    paths.append(path)
    if current_root is not None and client in {"cursor"}:
        current_path = str(current_root.expanduser().resolve())
        if client == "cursor":
            current_status = _cursor_status_with_hooks(root=current_root)
        if bool(current_status.get("prepared")) and current_path not in paths:
            paths.insert(0, current_path)
    ordered_paths: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        ordered_paths.append(path)
    entries = [_project_activation_entry(client, path) for path in ordered_paths]
    return {"activated_projects": entries, "activated_project_count": len(entries)}


def _hook_spec(client: str, *, root: Path = ROOT) -> dict[str, Any]:
    if client == "codex":
        return {
            "config_path": root / ".codex" / "hooks.json",
            "disabled_paths": [
                root / ".codex" / "hooks_deactivated.json",
                root / ".codex" / "hooks_disabled.json",
                root / ".codex" / "hooks_not_use_at_the_moment.json",
            ],
            "script_path": root / ".codex" / "hooks" / "hook_adapter.sh",
            "template_config": SKILL_ROOT / "templates" / "codex-hooks" / "hooks.json",
            "template_script": SKILL_ROOT / "templates" / "codex-hooks" / "hook_adapter.sh",
            "command": "./.codex/hooks/hook_adapter.sh",
        }
    if client == "claude":
        return {
            "config_path": root / ".claude" / "settings.json",
            "disabled_paths": [root / ".claude" / "settings_deactivated.json"],
            "script_path": root / ".claude" / "hooks" / "hook_adapter.sh",
            "template_config": SKILL_ROOT / "templates" / "claude-hooks" / "settings.json",
            "template_script": SKILL_ROOT / "templates" / "claude-hooks" / "hook_adapter.sh",
            "command": "./.claude/hooks/hook_adapter.sh",
        }
    if client == "gemini":
        return {
            "config_path": root / ".gemini" / "settings.json",
            "disabled_paths": [root / ".gemini" / "settings_deactivated.json"],
            "script_path": root / ".gemini" / "hooks" / "hook_adapter.sh",
            "template_config": SKILL_ROOT / "templates" / "gemini-hooks" / "settings.json",
            "template_script": SKILL_ROOT / "templates" / "gemini-hooks" / "hook_adapter.sh",
            "command": "./.gemini/hooks/hook_adapter.sh",
        }
    raise ValueError(f"unsupported shell-hook client: {client}")


def antigravity_project_paths(root: Path = ROOT) -> dict[str, Path]:
    return {
        "config_path": root / ".agents" / "hooks.json",
        "disabled_path": root / ".agents" / "hooks_deactivated.json",
        "script_path": root / ".agents" / "hooks" / "hook_adapter.sh",
        "state_dir": root / ".agents" / "hooks" / ".agent-memory-state",
    }


def _disabled_hook_path(spec: dict[str, Any]) -> Path:
    return spec["disabled_paths"][0]


def _find_existing_disabled_path(spec: dict[str, Any]) -> Path | None:
    for path in spec["disabled_paths"]:
        if path.exists():
            return path
    return None


def _expected_hook_events(client: str) -> list[str]:
    if client == "cursor":
        return list(CURSOR_EVENTS)
    template = _read_json(_hook_spec(client)["template_config"])
    hooks = template.get("hooks", {})
    return list(hooks.keys()) if isinstance(hooks, dict) else []


def _template_hook_commands(client: str, *, root: Path = ROOT) -> dict[str, set[str]]:
    template = _read_json(_hook_spec(client, root=root)["template_config"])
    hooks = template.get("hooks", {})
    if not isinstance(hooks, dict):
        return {}
    commands: dict[str, set[str]] = {}
    for event, groups in hooks.items():
        event_commands: set[str] = set()
        if isinstance(groups, list):
            for group in groups:
                if not isinstance(group, dict):
                    continue
                raw_hooks = group.get("hooks")
                if not isinstance(raw_hooks, list):
                    continue
                for hook in raw_hooks:
                    if not isinstance(hook, dict):
                        continue
                    command = str(hook.get("command") or "").strip()
                    if command:
                        event_commands.add(command)
        if event_commands:
            commands[str(event)] = event_commands
    return commands


def _group_contains_command(group: Any, command: str) -> bool:
    if not isinstance(group, dict):
        return False
    hooks = group.get("hooks")
    if not isinstance(hooks, list):
        return False
    for hook in hooks:
        if isinstance(hook, dict) and str(hook.get("command") or "") == command:
            return True
    return False


def _group_contains_any_command(group: Any, commands: set[str]) -> bool:
    return any(_group_contains_command(group, command) for command in commands)


def _active_events_for_shell_hook(data: dict[str, Any], *, expected_commands: dict[str, set[str]]) -> list[str]:
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return []
    active: list[str] = []
    for event, commands in expected_commands.items():
        groups = hooks.get(event)
        if isinstance(groups, list) and any(_group_contains_any_command(group, commands) for group in groups):
            active.append(event)
    return active


def _prepare_shell_hook_client(client: str, *, root: Path = ROOT, memory_root: Path | None = None) -> None:
    spec = _hook_spec(client, root=root)
    config_path: Path = spec["config_path"]
    disabled_path = _find_existing_disabled_path(spec)
    if not config_path.exists() and disabled_path:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        disabled_path.replace(config_path)
    if not config_path.exists():
        _write_json(config_path, _read_json(spec["template_config"]))
    script_memory_root = memory_root or root
    script_text = _render_shell_hook_script(client, memory_root=script_memory_root)
    script_path: Path = spec["script_path"]
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_text, encoding="utf-8")
    script_path.chmod(0o755)
    write_workspace_binding(client, root=root, memory_root=script_memory_root, written_by="hook-prepare")


def _merge_shell_hook_client(client: str, *, root: Path = ROOT, memory_root: Path | None = None) -> None:
    spec = _hook_spec(client, root=root)
    _prepare_shell_hook_client(client, root=root, memory_root=memory_root)
    current = _read_json(spec["config_path"])
    template = _read_json(spec["template_config"])
    hooks = current.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        hooks = {}
        current["hooks"] = hooks
    template_hooks = template.get("hooks", {})
    if not isinstance(template_hooks, dict):
        template_hooks = {}
    expected_commands = _template_hook_commands(client, root=root)
    for event, template_groups in template_hooks.items():
        groups = hooks.setdefault(event, [])
        if not isinstance(groups, list):
            groups = []
            hooks[event] = groups
        if any(_group_contains_any_command(group, expected_commands.get(str(event), set())) for group in groups):
            continue
        if isinstance(template_groups, list):
            groups.extend(template_groups)
    _write_json(spec["config_path"], current)


def _disable_shell_hook_client(client: str, *, root: Path = ROOT) -> None:
    spec = _hook_spec(client, root=root)
    config_path: Path = spec["config_path"]
    if not config_path.exists():
        return
    disabled_path = _disabled_hook_path(spec)
    disabled_path.parent.mkdir(parents=True, exist_ok=True)
    if disabled_path.exists():
        disabled_path.unlink()
    config_path.replace(disabled_path)


def _shell_hook_status(client: str, *, root: Path = ROOT, memory_root: Path | None = None) -> dict[str, Any]:
    spec = _hook_spec(client, root=root)
    config_path: Path = spec["config_path"]
    script_path: Path = spec["script_path"]
    disabled_path = _find_existing_disabled_path(spec)
    expected_events = _expected_hook_events(client)
    expected_commands = _template_hook_commands(client, root=root)
    active_events: list[str] = []
    if config_path.exists():
        try:
            active_events = _active_events_for_shell_hook(_read_json(config_path), expected_commands=expected_commands)
        except json.JSONDecodeError:
            active_events = []
    script_status = shell_hook_adapter_status(client, root=root, memory_root=memory_root)
    local_hooks_state = "not_prepared"
    if config_path.exists() and len(active_events) == len(expected_events) and expected_events:
        local_hooks_state = "enabled"
    elif config_path.exists() and active_events:
        local_hooks_state = "partial"
    elif disabled_path is not None:
        local_hooks_state = "disabled"
    elif config_path.exists():
        local_hooks_state = "configured_without_agent_memory"
    binding_status = workspace_binding_status(client, root=root, expected_memory_root=memory_root or root)
    hooks_state, hooks_enabled = _effective_binding_hooks_state(local_hooks_state, str(binding_status["hook_binding_state"]))
    prepared = script_path.exists() or config_path.exists() or disabled_path is not None
    return {
        "prepared": prepared,
        "hooks_manageable": True,
        "hooks_state": hooks_state,
        "hooks_enabled": hooks_enabled,
        "hook_local_state": local_hooks_state,
        "hook_effective_state": hooks_state,
        "hook_config_path": str(config_path),
        "hook_disabled_path": str(disabled_path) if disabled_path else "",
        "hook_script_path": str(script_path),
        "hook_script_status": script_status["status"],
        "hook_script_expected_root": script_status["expected_root"],
        "hook_script_detected_root": script_status["detected_root"],
        "hook_script_expected_script": script_status["expected_script"],
        "hook_script_detected_script": script_status["detected_script"],
        "expected_hook_events": expected_events,
        "active_hook_events": active_events,
        **binding_status,
    }


def _antigravity_template(*, root: Path = ROOT) -> dict[str, Any]:
    template_path = SKILL_ROOT / "templates" / "antigravity-hooks" / "hooks.json"
    template = json.loads(
        template_path.read_text(encoding="utf-8").replace(
            "__ANTIGRAVITY_HOOK_SCRIPT__",
            str((root / ".agents" / "hooks" / "hook_adapter.sh").resolve()),
        )
    )
    if not isinstance(template, dict):
        raise ValueError("invalid antigravity hook template")
    return template


def _antigravity_hook_events(*, root: Path = ROOT) -> list[str]:
    template = _antigravity_template(root=root).get("agent-memory", {})
    if not isinstance(template, dict):
        return []
    return [str(event) for event in template.keys()]


def _antigravity_hook_commands(*, root: Path = ROOT) -> dict[str, set[str]]:
    template = _antigravity_template(root=root).get("agent-memory", {})
    if not isinstance(template, dict):
        return {}
    commands: dict[str, set[str]] = {}
    for event, entries in template.items():
        if not isinstance(entries, list):
            continue
        event_commands: set[str] = set()
        for entry in entries:
            event_commands.update(_antigravity_entry_commands(str(event), entry))
        if event_commands:
            commands[str(event)] = event_commands
    return commands


def _antigravity_event_uses_direct_handlers(event: str) -> bool:
    return str(event) in {"PreInvocation", "PostInvocation", "Stop"}


def _antigravity_entry_commands(event: str, entry: Any) -> set[str]:
    if not isinstance(entry, dict):
        return set()
    if _antigravity_event_uses_direct_handlers(event):
        command = str(entry.get("command") or "").strip()
        return {command} if command else set()
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return set()
    commands: set[str] = set()
    for hook in hooks:
        if not isinstance(hook, dict):
            continue
        command = str(hook.get("command") or "").strip()
        if command:
            commands.add(command)
    return commands


def _antigravity_event_is_active(event: str, entries: Any, commands: set[str]) -> bool:
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if _antigravity_entry_commands(event, entry) & commands:
            return True
    return False


def _prepare_antigravity_hook_client(*, root: Path = ROOT, memory_root: Path | None = None) -> None:
    memory_root = memory_root or root
    paths = antigravity_project_paths(root)
    config_path = paths["config_path"]
    disabled_path = paths["disabled_path"]
    if not config_path.exists() and disabled_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        disabled_path.replace(config_path)
    if not config_path.exists():
        _write_json(config_path, {})
    script_text = (SKILL_ROOT / "templates" / "antigravity-hooks" / "hook_adapter.sh").read_text(encoding="utf-8")
    script_text = script_text.replace("__AGENT_MEMORY_SCRIPT__", _agent_memory_script_for_root(memory_root))
    script_text = script_text.replace("__AGENT_CONTEXT_ENGINE_ROOT__", str(memory_root.resolve()))
    script_path = paths["script_path"]
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(script_text, encoding="utf-8")
    script_path.chmod(0o755)


def _render_antigravity_template(*, root: Path = ROOT) -> dict[str, Any]:
    return _antigravity_template(root=root)


def _merge_antigravity_hook_client(*, root: Path = ROOT, memory_root: Path | None = None) -> None:
    _prepare_antigravity_hook_client(root=root, memory_root=memory_root)
    paths = antigravity_project_paths(root)
    current = _read_json(paths["config_path"])
    if not isinstance(current, dict):
        current = {}
    template = _render_antigravity_template(root=root)
    template_entry = template.get("agent-memory", {})
    if not isinstance(template_entry, dict):
        template_entry = {}
    hook_key = "agent-memory"
    existing_entry = current.get(hook_key)
    if not isinstance(existing_entry, dict):
        existing_entry = {}
    existing_entry["enabled"] = True
    expected_commands = _antigravity_hook_commands(root=root)
    for event, template_groups in template_entry.items():
        if event == "enabled":
            continue
        groups = existing_entry.get(event)
        if not isinstance(groups, list):
            groups = []
            existing_entry[event] = groups
        if _antigravity_event_is_active(str(event), groups, expected_commands.get(str(event), set())):
            continue
        if isinstance(template_groups, list):
            existing_entry[event] = list(template_groups)
    current[hook_key] = existing_entry
    _write_json(paths["config_path"], current)


def _disable_antigravity_hook_client(*, root: Path = ROOT) -> None:
    paths = antigravity_project_paths(root)
    if not paths["config_path"].exists():
        return
    if paths["disabled_path"].exists():
        paths["disabled_path"].unlink()
    paths["config_path"].replace(paths["disabled_path"])


def _antigravity_hook_status(*, root: Path = ROOT) -> dict[str, Any]:
    paths = antigravity_project_paths(root)
    config_path = paths["config_path"]
    disabled_path = paths["disabled_path"]
    script_path = paths["script_path"]
    active_events: list[str] = []
    expected_events = _antigravity_hook_events(root=root)
    if config_path.exists():
        try:
            current = _read_json(config_path)
        except json.JSONDecodeError:
            current = {}
        hook_entry = current.get("agent-memory", {})
        if isinstance(hook_entry, dict) and hook_entry.get("enabled", True) is not False:
            expected_commands = _antigravity_hook_commands(root=root)
            for event, commands in expected_commands.items():
                groups = hook_entry.get(event)
                if _antigravity_event_is_active(str(event), groups, commands):
                    active_events.append(event)
    if config_path.exists() and len(active_events) == len(expected_events) and expected_events:
        hooks_state = "enabled"
    elif config_path.exists() and active_events:
        hooks_state = "partial"
    elif disabled_path.exists():
        hooks_state = "disabled"
    elif config_path.exists():
        hooks_state = "configured_without_agent_memory"
    else:
        hooks_state = "not_prepared"
    prepared = config_path.exists() or disabled_path.exists() or script_path.exists()
    return {
        "prepared": prepared,
        "hooks_manageable": True,
        "hooks_state": hooks_state,
        "hooks_enabled": hooks_state == "enabled",
        "hook_config_path": str(config_path),
        "hook_disabled_path": str(disabled_path),
        "hook_script_path": str(script_path),
        "expected_hook_events": expected_events,
        "active_hook_events": sorted(active_events),
    }


def _cursor_status_with_hooks(*, root: Path = ROOT) -> dict[str, Any]:
    hooks_path, script_path = cursor_paths(root)
    disabled_path = root / ".cursor" / "hooks_deactivated.json"
    active_events: list[str] = []
    if hooks_path.exists():
        try:
            data = load_cursor_hooks(hooks_path)
            for event, entries in data.get("hooks", {}).items():
                if isinstance(entries, list) and any(is_agent_memory_cursor_hook(entry) for entry in entries):
                    active_events.append(str(event))
        except ValueError:
            active_events = []
    if hooks_path.exists() and len(active_events) == len(CURSOR_EVENTS):
        local_hooks_state = "enabled"
    elif hooks_path.exists() and active_events:
        local_hooks_state = "partial"
    elif disabled_path.exists():
        local_hooks_state = "disabled"
    elif hooks_path.exists():
        local_hooks_state = "configured_without_agent_memory"
    else:
        local_hooks_state = "not_prepared"
    binding_status = workspace_binding_status("cursor", root=root, expected_memory_root=root)
    hooks_state, hooks_enabled = _effective_binding_hooks_state(local_hooks_state, str(binding_status["hook_binding_state"]))
    return {
        "prepared": script_path.exists() or hooks_path.exists() or disabled_path.exists(),
        "hooks_manageable": True,
        "hooks_state": hooks_state,
        "hooks_enabled": hooks_enabled,
        "hook_local_state": local_hooks_state,
        "hook_effective_state": hooks_state,
        "hook_config_path": str(hooks_path),
        "hook_disabled_path": str(disabled_path) if disabled_path.exists() else str(disabled_path),
        "hook_script_path": str(script_path),
        "expected_hook_events": list(CURSOR_EVENTS),
        "active_hook_events": sorted(active_events),
        **binding_status,
    }


def _enable_cursor_project_hooks(*, root: Path = ROOT, memory_root: Path = ROOT) -> None:
    disabled_path = root / ".cursor" / "hooks_deactivated.json"
    active_path, script_path = cursor_paths(root)
    if not active_path.exists() and disabled_path.exists():
        active_path.parent.mkdir(parents=True, exist_ok=True)
        disabled_path.replace(active_path)
    enable_cursor_hooks(root)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(_cursor_hook_wrapper(memory_root), encoding="utf-8")
    script_path.chmod(0o755)
    write_workspace_binding("cursor", root=root, memory_root=memory_root, written_by="cursor-enable")


def _disable_cursor_project_hooks(*, root: Path = ROOT) -> None:
    hooks_path, _script_path = cursor_paths(root)
    disabled_path = root / ".cursor" / "hooks_deactivated.json"
    if not hooks_path.exists():
        return
    if disabled_path.exists():
        disabled_path.unlink()
    hooks_path.replace(disabled_path)


def _opencode_hook_status(*, root: Path = ROOT) -> dict[str, Any]:
    paths = opencode_project_paths(root)
    plugin_path = paths["plugin_file"]
    disabled_path = plugin_path.with_name("agent-memory_deactivated.js")
    active = plugin_path.exists() and "AgentMemoryPlugin" in plugin_path.read_text(encoding="utf-8", errors="replace")
    if active:
        hooks_state = "enabled"
    elif disabled_path.exists():
        hooks_state = "disabled"
    elif paths["config"].exists() or plugin_path.exists():
        hooks_state = "configured_without_agent_memory"
    else:
        hooks_state = "not_prepared"
    return {
        "prepared": paths["config"].exists() or plugin_path.exists() or disabled_path.exists(),
        "hooks_manageable": True,
        "hooks_state": hooks_state,
        "hooks_enabled": hooks_state == "enabled",
        "hook_config_path": str(plugin_path),
        "hook_disabled_path": str(disabled_path),
        "hook_script_path": str(plugin_path),
        "expected_hook_events": [
            "session.created",
            "message.updated",
            "tool.execute.before",
            "tool.execute.after",
            "permission.asked",
            "permission.replied",
            "session.idle",
            "command.executed",
        ],
        "active_hook_events": ["plugin"] if active else [],
    }


def _enable_opencode_project_hooks(*, root: Path = ROOT, memory_root: Path = ROOT) -> None:
    paths = opencode_project_paths(root)
    disabled_path = paths["plugin_file"].with_name("agent-memory_deactivated.js")
    if not paths["plugin_file"].exists() and disabled_path.exists():
        paths["plugin_file"].parent.mkdir(parents=True, exist_ok=True)
        disabled_path.replace(paths["plugin_file"])
    ensure_opencode_project(root, memory_root=memory_root)


def _disable_opencode_project_hooks(*, root: Path = ROOT) -> None:
    paths = opencode_project_paths(root)
    plugin_path = paths["plugin_file"]
    disabled_path = plugin_path.with_name("agent-memory_deactivated.js")
    if not plugin_path.exists():
        return
    if disabled_path.exists():
        disabled_path.unlink()
    plugin_path.replace(disabled_path)


def _run_command(command: list[str], *, cwd: Path | None = None, timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(cwd or ROOT),
        env=os.environ.copy(),
    )


def parse_ollama_models(text: str) -> list[dict[str, str]]:
    models: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("name"):
            continue
        parts = stripped.split()
        if not parts:
            continue
        name = parts[0]
        size = ""
        if len(parts) >= 4:
            size = f"{parts[2]} {parts[3]}".strip()
        models.append({"id": name, "provider": "ollama", "label": name, "size": size})
    return models


def discover_ollama_models(*, timeout: int = 10) -> dict[str, Any]:
    executable = shutil.which("ollama")
    if not executable:
        return {"ok": False, "provider": "ollama", "reason": "missing_executable", "models": []}
    try:
        proc = _run_command([executable, "list"], timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "provider": "ollama", "reason": f"command_failed:{exc}", "models": []}
    if proc.returncode != 0:
        return {
            "ok": False,
            "provider": "ollama",
            "reason": "command_error",
            "detail": (proc.stderr or proc.stdout).strip(),
            "models": [],
        }
    return {"ok": True, "provider": "ollama", "models": parse_ollama_models(proc.stdout)}


def parse_opencode_models(text: str) -> list[dict[str, str]]:
    models: list[dict[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("provider") or stripped.lower().startswith("model"):
            continue
        parts = stripped.split()
        if not parts:
            continue
        identifier = parts[0]
        if "/" not in identifier:
            continue
        provider, model_id = identifier.split("/", 1)
        models.append({"id": identifier, "provider": provider, "label": model_id})
    return models


def discover_opencode_models(provider: str | None = None, *, timeout: int = 15) -> dict[str, Any]:
    executable = shutil.which("opencode")
    if not executable:
        return {"ok": False, "client": "opencode", "reason": "missing_executable", "models": []}
    command = [executable, "models"]
    if provider:
        command.append(provider)
    try:
        proc = _run_command(command, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "client": "opencode", "reason": f"command_failed:{exc}", "models": []}
    if proc.returncode != 0:
        return {
            "ok": False,
            "client": "opencode",
            "reason": "command_error",
            "detail": (proc.stderr or proc.stdout).strip(),
            "models": [],
        }
    models = parse_opencode_models(proc.stdout)
    if provider:
        models = [item for item in models if item["provider"] == provider]
    return {"ok": True, "client": "opencode", "models": models}


def probe_gemini_models(candidates: list[str] | None = None, *, timeout: int = 20) -> dict[str, Any]:
    executable = shutil.which("gemini")
    if not executable:
        return {"ok": False, "client": "gemini", "reason": "missing_executable", "models": []}
    discovered: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    for model in (candidates or GEMINI_MINI_PREFERENCE):
        try:
            proc = _run_command(
                [executable, "-m", model, "-p", "Reply with OK only.", "--output-format", "json"],
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append({"id": model, "detail": str(exc)})
            continue
        if proc.returncode == 0:
            discovered.append({"id": model, "provider": "gemini", "label": model})
        else:
            errors.append({"id": model, "detail": (proc.stderr or proc.stdout).strip()})
    return {"ok": bool(discovered), "client": "gemini", "models": discovered, "errors": errors}


def pick_preferred_gemini_mini_model(models: list[dict[str, str]]) -> str | None:
    ids = {item.get("id") for item in models}
    for candidate in GEMINI_MINI_PREFERENCE:
        if candidate in ids:
            return candidate
    return next((item.get("id") for item in models if item.get("id")), None)


def opencode_project_paths(root: Path = ROOT) -> dict[str, Path]:
    return {
        "config": root / "opencode.json",
        "plugin_dir": root / ".opencode" / "plugins",
        "plugin_file": root / ".opencode" / "plugins" / "agent-memory.js",
    }


def _opencode_dream_provider_details() -> tuple[str, str]:
    provider_id, _, model_name = OPENCODE_DREAM_MODEL.partition("/")
    return provider_id or OPENCODE_DEFAULT_PROVIDER, model_name or OPENCODE_DREAM_MODEL


def render_opencode_config(
    *,
    existing_config: dict[str, Any] | None = None,
    model: str | None = None,
    small_model: str | None = None,
) -> str:
    config = dict(existing_config or {})
    config["$schema"] = "https://opencode.ai/config.json"
    provider_id, model_name = _opencode_dream_provider_details()
    providers = config.get("provider")
    if not isinstance(providers, dict):
        providers = {}
    provider_entry = providers.get(provider_id)
    if not isinstance(provider_entry, dict):
        provider_entry = {}
    models = provider_entry.get("models")
    if not isinstance(models, dict):
        models = {}
    models[model_name] = {"name": model_name}
    provider_entry["models"] = models
    provider_entry.setdefault("name", "Ollama (local)")
    provider_entry.setdefault("npm", "@ai-sdk/openai-compatible")
    options = provider_entry.get("options")
    if not isinstance(options, dict):
        options = {}
    options.setdefault("baseURL", "http://localhost:11434/v1")
    provider_entry["options"] = options
    providers[provider_id] = provider_entry
    config["provider"] = providers
    if model is not None:
        config["model"] = model
    if small_model is not None:
        config["small_model"] = small_model
    return json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def render_opencode_plugin(root: Path = ROOT, memory_root: Path | None = None) -> str:
    if memory_root is None:
        memory_root = root
    script = str(SCRIPT_PATH)
    install_root_text = str(root)
    memory_root_text = str(memory_root)
    hooks_state_rel = str(Path("memory") / "local" / "hooks-state.json")
    return f"""import {{ appendFileSync, mkdirSync, readFileSync }} from "node:fs"
import {{ join }} from "node:path"
import {{ spawn, spawnSync }} from "node:child_process"

export const AgentMemoryPlugin = async ({{ directory, worktree }}) => {{
  if (process.env.AGENT_MEMORY_DREAM === "1") {{
    return {{}}
  }}

  const python = "python3"
  const script = {json.dumps(script)}
  const installRoot = {json.dumps(install_root_text)}
  const memoryRoot = {json.dumps(memory_root_text)}
  const hooksStateRelativePath = {json.dumps(hooks_state_rel)}

  const launchCwd = process.env.AGENT_MEMORY_LAUNCH_CWD || ""
  const opencodeBridgeLog = join(memoryRoot, "logs", "opencode-hook.err.log")
  const currentCwd = (fallback = "") => launchCwd || worktree || directory || fallback || "."
  const sessionIdFrom = (...values) => {{
    for (const value of values) {{
      if (typeof value === "string" && value.trim()) return value.trim()
    }}
    return ""
  }}
  const cwdFromInfo = (info = {{}}, fallback = "") =>
    currentCwd(
      info?.directory ||
      info?.cwd ||
      info?.worktree ||
      info?.path?.cwd ||
      info?.path?.directory ||
      fallback
    )
  const titleFrom = (...values) => {{
    for (const value of values) {{
      if (typeof value === "string" && value.trim()) return value.trim()
    }}
    return ""
  }}
  const textFromParts = (parts) =>
    Array.isArray(parts)
      ? parts
          .filter((part) => part && part.type === "text" && typeof part.text === "string")
          .map((part) => part.text)
          .join("\\n")
          .trim()
      : ""

  const hooksEnabled = () => {{
    try {{
      const raw = readFileSync(join(installRoot, hooksStateRelativePath), "utf8")
      const state = JSON.parse(raw)
      if (state && state.enabled === false) return false
      const runnerState = state?.runners?.opencode
      if (runnerState && runnerState.enabled === false) return false
    }} catch (_error) {{
      return true
    }}
    return true
  }}

  const logAsyncBridgeError = (message, error) => {{
    try {{
      mkdirSync(join(memoryRoot, "logs"), {{ recursive: true }})
      const detail = error instanceof Error ? (error.stack || error.message) : String(error || "")
      appendFileSync(opencodeBridgeLog, `[${{new Date().toISOString()}}] ${{message}}${{detail ? ` :: ${{detail}}` : ""}}\\n`, "utf8")
    }} catch (_logError) {{
      // Drop logging failures; the bridge itself must stay non-fatal.
    }}
  }}

  const runHookSync = (payload, mode = "auto") => {{
    if (!hooksEnabled()) return
    const proc = spawnSync(python, [script, "log-hook", "--client", "opencode", "--mode", mode], {{
      cwd: currentCwd(payload?.cwd || ""),
      input: JSON.stringify(payload),
      encoding: "utf8",
      env: {{
        ...process.env,
        AGENT_CONTEXT_ENGINE_ROOT: installRoot,
        AGENT_CONTEXT_ENGINE_STORAGE_ROOT: memoryRoot,
      }},
    }})
    const stdout = (proc.stdout || "").trim()
    const stderr = (proc.stderr || "").trim()
    if (stdout) process.stdout.write(stdout + "\\n")
    if (proc.status === 2) throw new Error(stderr || "Agent Context Engine blocked this action")
    if ((proc.status || 0) !== 0 && stderr) process.stderr.write(stderr + "\\n")
  }}

  const runHookAsync = (payload, mode = "queue") => {{
    if (!hooksEnabled()) return
    const proc = spawn(python, [script, "log-hook", "--client", "opencode", "--mode", mode], {{
      cwd: currentCwd(payload?.cwd || ""),
      env: {{
        ...process.env,
        AGENT_CONTEXT_ENGINE_ROOT: installRoot,
        AGENT_CONTEXT_ENGINE_STORAGE_ROOT: memoryRoot,
      }},
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
    }})
    proc.on("error", (error) => logAsyncBridgeError("spawn failed", error))
    proc.stdin.on("error", (error) => logAsyncBridgeError("stdin failed", error))
    try {{
      proc.stdin.write(JSON.stringify(payload))
      proc.stdin.end()
    }} catch (error) {{
      logAsyncBridgeError("async hook handoff failed", error)
      try {{
        proc.kill()
      }} catch (_killError) {{
        // Ignore cleanup failure.
      }}
      return
    }}
    proc.unref()
  }}

  return {{
    event: async (input) => {{
      const event = input?.event
      if (!event || typeof event.type !== "string") return
      if (event.type === "session.created") {{
        const info = event.properties?.info || {{}}
        const sessionId = sessionIdFrom(
          event.properties?.sessionID,
          event.properties?.sessionId,
          event.sessionID,
          event.sessionId,
          input?.sessionID,
          input?.sessionId
        )
        runHookAsync({{
          hook_event_name: "SessionStart",
          session_id: sessionId,
          cwd: cwdFromInfo(info),
          thread_name: titleFrom(info?.title, event.properties?.title, event.title),
          payload: event,
        }})
        return
      }}
      if (event.type === "permission.asked") {{
        runHookAsync({{
          hook_event_name: "PermissionAsked",
          session_id: sessionIdFrom(event.properties?.sessionID, event.properties?.sessionId, event.sessionID, event.sessionId),
          cwd: currentCwd(),
          payload: event,
        }})
        return
      }}
      if (event.type === "permission.replied") {{
        runHookAsync({{
          hook_event_name: "PermissionReplied",
          session_id: sessionIdFrom(event.properties?.sessionID, event.properties?.sessionId, event.sessionID, event.sessionId),
          cwd: currentCwd(),
          payload: event,
        }})
        return
      }}
      if (event.type === "command.executed") {{
        runHookAsync({{
          hook_event_name: "CommandExecuted",
          session_id: sessionIdFrom(event.properties?.sessionID, event.properties?.sessionId, event.sessionID, event.sessionId),
          cwd: currentCwd(),
          payload: event,
        }})
        return
      }}
      if (event.type === "session.idle") {{
        runHookAsync({{
          hook_event_name: "Stop",
          session_id: sessionIdFrom(event.properties?.sessionID, event.properties?.sessionId, event.sessionID, event.sessionId),
          cwd: currentCwd(),
          payload: event,
        }})
      }}
    }},
    "chat.message": async (input, output) => {{
      const prompt = textFromParts(output?.parts)
      if (!prompt) return
      runHookSync({{
        hook_event_name: "UserPromptSubmit",
        session_id: sessionIdFrom(input?.sessionID, input?.sessionId, output?.sessionID, output?.sessionId),
        cwd: currentCwd(),
        prompt,
        payload: {{ input: input || null, output: output || null }},
      }}, "context")
    }},
    "tool.execute.before": async (input, output) => {{
      runHookSync({{
        hook_event_name: "PreToolUse",
        session_id: sessionIdFrom(input?.sessionID, input?.sessionId, output?.sessionID, output?.sessionId),
        cwd: currentCwd(),
        tool_name: input?.tool || "",
        tool_input: output?.args || null,
        tool_use_id: input?.callID || "",
        payload: {{ input: input || null, output: output || null }},
      }}, "auto")
    }},
    "tool.execute.after": async (input, output) => {{
      runHookAsync({{
        hook_event_name: "PostToolUse",
        session_id: input?.sessionID || "",
        cwd: currentCwd(),
        tool_name: input?.tool || "",
        tool_input: input?.args || null,
        tool_response: output?.output || "",
        tool_use_id: input?.callID || "",
        payload: {{ input: input || null, output: output || null }},
      }})
    }},
    "command.execute.before": async (input, output) => {{
      runHookSync({{
        hook_event_name: "PreToolUse",
        session_id: input?.sessionID || "",
        cwd: currentCwd(),
        tool_name: "command",
        tool_input: {{
          command: input?.command || "",
          arguments: input?.arguments || "",
          parts: output?.parts || [],
        }},
        tool_use_id: "",
        payload: {{ input: input || null, output: output || null }},
      }}, "auto")
    }},
  }}
}}

export const server = AgentMemoryPlugin

export default {{
  id: "agent-memory",
  server,
}}
"""


def ensure_opencode_project(
    root: Path = ROOT,
    *,
    memory_root: Path | None = None,
    model: str | None = None,
    small_model: str | None = None,
) -> dict[str, Path]:
    paths = opencode_project_paths(root)
    paths["plugin_dir"].mkdir(parents=True, exist_ok=True)
    existing_config: dict[str, Any] | None = None
    if paths["config"].exists():
        try:
            loaded = json.loads(paths["config"].read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing_config = loaded
        except json.JSONDecodeError:
            existing_config = None
    paths["config"].write_text(
        render_opencode_config(
            existing_config=existing_config,
            model=model,
            small_model=small_model,
        ),
        encoding="utf-8",
    )
    paths["plugin_file"].write_text(render_opencode_plugin(root=root, memory_root=memory_root), encoding="utf-8")
    return paths


def ensure_antigravity_project(root: Path = ROOT, *, memory_root: Path | None = None) -> dict[str, Path]:
    _merge_antigravity_hook_client(root=root, memory_root=memory_root or root)
    return antigravity_project_paths(root)


def ensure_gemini_project(root: Path = ROOT) -> dict[str, Path]:
    _merge_shell_hook_client("gemini", root=root)
    spec = _hook_spec("gemini", root=root)
    return {
        "config_path": spec["config_path"],
        "script_path": spec["script_path"],
        "disabled_path": _disabled_hook_path(spec),
    }


def opencode_status(root: Path = ROOT) -> dict[str, Any]:
    paths = opencode_project_paths(root)
    discovered = discover_opencode_models()
    ollama = discover_ollama_models()
    selected_model = OPENCODE_DEFAULT_MODEL
    selected_small_model = OPENCODE_DEFAULT_SMALL_MODEL
    if paths["config"].exists():
        try:
            config = json.loads(paths["config"].read_text(encoding="utf-8"))
            selected_model = str(config.get("model") or selected_model)
            selected_small_model = str(config.get("small_model") or selected_small_model)
        except json.JSONDecodeError:
            pass
    ollama_ids = {item["id"] for item in ollama.get("models", [])}
    dream_provider_id, dream_provider_model = _opencode_dream_provider_details()
    runtime_ready = shutil.which("opencode") is not None
    dream_ready = runtime_ready and shutil.which(dream_provider_id) is not None and dream_provider_model in ollama_ids
    hook_status = _opencode_hook_status(root=root)
    wrapper_status = _simple_wrapper_state(executable_name="opencode", wrapper_command="./scripts/opencode-ace", root=root)
    global_wrapper_name = _resolved_global_wrapper_name("opencode", root=root)
    usage_hint = (
        f"Run the global wrapper `{global_wrapper_name}` from any directory. It starts OpenCode from the Agent Context Engine root so the plugin bridge loads, while the original launch directory becomes the project context."
        if wrapper_status["global_command_available"]
        else f"Use the global wrapper `{global_wrapper_name}` after adding the PATH link. Without that link, use the root command below."
    )
    return _apply_hook_control_status({
        "client": "opencode",
        "label": "Opencode",
        "ingress_transport": "plugin_bridge",
        "runner": "opencode",
        "provider": selected_model.split("/", 1)[0] if "/" in selected_model else (OPENCODE_DEFAULT_PROVIDER if selected_model else ""),
        "ready": runtime_ready,
        "auth_status": "not_required_local",
        "readiness_status": "installed" if runtime_ready else "missing_executable",
        "selected_model": selected_model,
        "selected_small_model": selected_small_model,
        "dream_model": OPENCODE_DREAM_MODEL,
        "dream_model_ready": dream_ready,
        "dream_readiness_status": "ready" if dream_ready else "model_missing" if runtime_ready and shutil.which(dream_provider_id) else "missing_executable",
        "project_config_exists": paths["config"].exists(),
        "plugin_exists": paths["plugin_file"].exists(),
        "paths": {key: str(value) for key, value in paths.items()},
        "models": discovered.get("models", []),
        "provider_models": ollama.get("models", []),
        "recommended_model": selected_model or "",
        "recommended_small_model": selected_small_model or selected_model or "",
        "recommended_dream_model": OPENCODE_DREAM_MODEL,
        "wrapper_command": "./scripts/opencode-ace",
        "usage_mode": "wrapper",
        "usage_hint": usage_hint,
        "working_root": str(root.resolve()),
        "terminal_command": _root_prefixed("./scripts/opencode-ace", root=root),
        "activation_command": _root_prefixed(f"{_agent_memory_cli_display(root)} opencode-enable", root=root),
        **wrapper_status,
        **hook_status,
        "prepared": bool(wrapper_status["wrapper_path_exists"]) or bool(hook_status["prepared"]),
    }, client="opencode", root=root)


def antigravity_status(*, root: Path = ROOT) -> dict[str, Any]:
    executable = shutil.which("agy")
    hook_status = _antigravity_hook_status(root=root)
    wrapper_status = _shell_wrapper_state(
        executable_name="agy",
        wrapper_command="./scripts/agy-ace",
        hooks_state=str(hook_status["hooks_state"]),
        root=root,
    )
    legacy_global_command = shutil.which("antigravity-ace")
    if not wrapper_status.get("global_command_available") and legacy_global_command:
        wrapper_status["global_command_available"] = True
        wrapper_status["global_command_path"] = legacy_global_command
        if executable is not None and str(hook_status["hooks_state"]) not in {"disabled", "configured_without_agent_memory", "not_prepared"}:
            wrapper_status["wrapper_state"] = "global_active"
            wrapper_status["wrapper_ready"] = True
    global_wrapper_name = _resolved_global_wrapper_name("antigravity", root=root)
    usage_hint = (
        f"Run the global wrapper `{global_wrapper_name}` from any directory. It starts Antigravity from the Agent Context Engine root so the central hooks load, while the original launch directory is added as a workspace."
        if wrapper_status["global_command_available"]
        else f"Use the global wrapper `{global_wrapper_name}` after adding the PATH link. The legacy alias `antigravity-ace` remains available. Without the link, use the root command below."
    )
    return _apply_hook_control_status({
        "client": "antigravity",
        "label": "Antigravity CLI",
        "ingress_transport": "shell_hook",
        "runner": "antigravity",
        "provider": "google",
        "ready": executable is not None,
        "auth_status": "unknown",
        "readiness_status": "installed" if executable else "missing_executable",
        "selected_model": ANTIGRAVITY_DREAM_MODEL,
        "selected_small_model": ANTIGRAVITY_DREAM_MODEL,
        "models": [],
        "recommended_model": ANTIGRAVITY_DREAM_MODEL,
        "recommended_small_model": ANTIGRAVITY_DREAM_MODEL,
        "wrapper_command": "./scripts/agy-ace",
        "usage_mode": "wrapper",
        "usage_hint": usage_hint,
        "working_root": str(root.resolve()),
        "terminal_command": _root_prefixed("./scripts/agy-ace", root=root),
        "activation_command": _root_prefixed(f"{_agent_memory_cli_display(root)} antigravity-enable", root=root),
        "resume_command": "agy --conversation <conversation-id>",
        "conversation_resume_command": "agy --conversation <conversation-id>",
        "legacy_wrapper_command": "./scripts/antigravity-ace",
        "prepared": bool(wrapper_status["wrapper_path_exists"]) or bool(hook_status["prepared"]),
        **wrapper_status,
        **hook_status,
    }, client="antigravity", root=root)


def gemini_status(*, root: Path = ROOT, probe: bool = False) -> dict[str, Any]:
    executable = shutil.which("gemini")
    discovered = probe_gemini_models() if probe and executable else {"ok": False, "models": []}
    recommended = pick_preferred_gemini_mini_model(discovered.get("models", [])) if probe else None
    hook_status = _shell_hook_status("gemini", root=root)
    wrapper_status = _shell_wrapper_state(
        executable_name="gemini",
        wrapper_command="./scripts/gemini-ace",
        hooks_state=str(hook_status["hooks_state"]),
        root=root,
    )
    global_wrapper_name = _resolved_global_wrapper_name("gemini", root=root)
    usage_hint = (
        f"Run the global wrapper `{global_wrapper_name}` from any directory. It starts Gemini from the Agent Context Engine root so the central hooks load, while the original launch directory is included in the workspace."
        if wrapper_status["global_command_available"]
        else f"Use the global wrapper `{global_wrapper_name}` after adding the PATH link. Without that link, use the root command below."
    )
    return _apply_hook_control_status({
        "client": "gemini",
        "label": "Gemini CLI",
        "ingress_transport": "shell_hook",
        "runner": "gemini",
        "provider": "gemini",
        "ready": executable is not None,
        "auth_status": "unknown",
        "readiness_status": "installed" if executable else "missing_executable",
        "selected_model": recommended or "",
        "selected_small_model": recommended or "",
        "models": discovered.get("models", []),
        "recommended_model": recommended or GEMINI_MINI_PREFERENCE[0],
        "recommended_small_model": recommended or GEMINI_MINI_PREFERENCE[0],
        "errors": discovered.get("errors", []),
        "wrapper_command": "./scripts/gemini-ace",
        "usage_mode": "wrapper",
        "usage_hint": usage_hint,
        "working_root": str(root.resolve()),
        "terminal_command": _root_prefixed("./scripts/gemini-ace", root=root),
        "activation_command": _root_prefixed(f"{_agent_memory_cli_display(root)} gemini-enable", root=root),
        "prepared": bool(wrapper_status["wrapper_path_exists"]) or bool(hook_status["prepared"]),
        **wrapper_status,
        **hook_status,
    }, client="gemini", root=root)


def static_integration_statuses(*, root: Path = ROOT, probe_gemini: bool = False) -> list[dict[str, Any]]:
    codex_hooks = _shell_hook_status("codex", root=root)
    claude_hooks = _shell_hook_status("claude", root=root)
    cursor_hooks = _cursor_status_with_hooks(root=root)
    codex_wrapper = _shell_wrapper_state(
        executable_name="codex",
        wrapper_command="./scripts/codex-ace",
        hooks_state=str(codex_hooks["hooks_state"]),
        root=root,
    )
    claude_wrapper = _shell_wrapper_state(
        executable_name="claude",
        wrapper_command="./scripts/claude-ace",
        hooks_state=str(claude_hooks["hooks_state"]),
        root=root,
    )
    codex_global_name = _resolved_global_wrapper_name("codex", root=root)
    claude_global_name = _resolved_global_wrapper_name("claude", root=root)
    return [
        _apply_hook_control_status({
            "client": "codex",
            "label": "Codex",
            "ingress_transport": "shell_hook",
            "runner": "codex",
            "provider": "openai",
            "ready": shutil.which("codex") is not None,
            "auth_status": "unknown",
            "readiness_status": "installed" if shutil.which("codex") else "missing_executable",
            "selected_model": os.environ.get("AGENT_MEMORY_CODEX_DREAM_MODEL", "gpt-5.4-mini"),
            "selected_small_model": os.environ.get("AGENT_MEMORY_CODEX_DREAM_MODEL", "gpt-5.4-mini"),
            "models": [],
            "recommended_model": os.environ.get("AGENT_MEMORY_CODEX_DREAM_MODEL", "gpt-5.4-mini"),
            "recommended_small_model": os.environ.get("AGENT_MEMORY_CODEX_DREAM_MODEL", "gpt-5.4-mini"),
            "wrapper_command": "./scripts/codex-ace",
            "usage_mode": "wrapper",
            "usage_hint": (
                f"Run the global wrapper `{codex_global_name}` from any directory."
                if codex_wrapper["global_command_available"]
                else f"Use the global wrapper `{codex_global_name}` after adding the PATH link. Without that link, use the root command below."
            ),
            "working_root": str(root.resolve()),
            "terminal_command": _root_prefixed("./scripts/codex-ace", root=root),
            **codex_wrapper,
            **codex_hooks,
            "prepared": bool(codex_wrapper["wrapper_path_exists"]) or bool(codex_hooks["prepared"]),
        }, client="codex", root=root),
        _apply_hook_control_status({
            "client": "claude",
            "label": "Claude",
            "ingress_transport": "shell_hook",
            "runner": "claude",
            "provider": "anthropic",
            "ready": shutil.which("claude") is not None,
            "auth_status": "unknown",
            "readiness_status": "installed" if shutil.which("claude") else "missing_executable",
            "selected_model": os.environ.get("AGENT_MEMORY_CLAUDE_DREAM_MODEL", "claude-haiku-4-5-20251001"),
            "selected_small_model": os.environ.get("AGENT_MEMORY_CLAUDE_DREAM_MODEL", "claude-haiku-4-5-20251001"),
            "models": [],
            "recommended_model": os.environ.get("AGENT_MEMORY_CLAUDE_DREAM_MODEL", "claude-haiku-4-5-20251001"),
            "recommended_small_model": os.environ.get("AGENT_MEMORY_CLAUDE_DREAM_MODEL", "claude-haiku-4-5-20251001"),
            "wrapper_command": "./scripts/claude-ace",
            "usage_mode": "wrapper",
            "usage_hint": (
                f"Run the global wrapper `{claude_global_name}` from any directory."
                if claude_wrapper["global_command_available"]
                else f"Use the global wrapper `{claude_global_name}` after adding the PATH link. Without that link, use the root command below."
            ),
            "working_root": str(root.resolve()),
            "terminal_command": _root_prefixed("./scripts/claude-ace", root=root),
            **claude_wrapper,
            **claude_hooks,
            "prepared": bool(claude_wrapper["wrapper_path_exists"]) or bool(claude_hooks["prepared"]),
        }, client="claude", root=root),
        _apply_hook_control_status({
            "client": "cursor",
            "label": "Cursor",
            "ingress_transport": "shell_hook",
            "runner": "cursor",
            "provider": "cursor",
            "ready": shutil.which("cursor-agent") is not None,
            "auth_status": "runtime_managed",
            "readiness_status": "installed" if shutil.which("cursor-agent") else "missing_executable",
            "selected_model": os.environ.get("AGENT_MEMORY_CURSOR_DREAM_MODEL", "gpt-5.4-mini-medium"),
            "selected_small_model": os.environ.get("AGENT_MEMORY_CURSOR_DREAM_MODEL", "gpt-5.4-mini-medium"),
            "models": [],
            "recommended_model": os.environ.get("AGENT_MEMORY_CURSOR_DREAM_MODEL", "gpt-5.4-mini-medium"),
            "recommended_small_model": os.environ.get("AGENT_MEMORY_CURSOR_DREAM_MODEL", "gpt-5.4-mini-medium"),
            "usage_mode": "project_activation",
            "usage_hint": "Run the activation command once per project from the Agent Context Engine root. Afterwards open that project in Cursor and work there normally.",
            "working_root": str(root.resolve()),
            "activation_command": _root_prefixed(f"{_agent_memory_cli_display(root)} cursor-enable --target <project-path>", root=root),
            "global_command_name": "",
            "global_command_available": False,
            "global_command_path": "",
            "wrapper_command": "",
            "wrapper_path": "",
            "wrapper_path_exists": False,
            "wrapper_state": "project_activation",
            "wrapper_ready": True,
            **cursor_hooks,
            **integration_projects_status("cursor", memory_root=root, current_root=root),
        }, client="cursor", root=root),
        {
            **antigravity_status(root=root),
        },
        gemini_status(root=root, probe=probe_gemini),
        {
            **opencode_status(root),
        },
    ]


def integration_summary(*, root: Path = ROOT, probe_gemini: bool = False) -> dict[str, Any]:
    items = static_integration_statuses(root=root, probe_gemini=probe_gemini)
    for item in items:
        client = str(item.get("client") or "").strip().lower()
        history = integration_history(root=root, client=client, limit=10)
        item["history"] = history
        item["last_history_entry"] = history[0] if history else None
    return {
        "items": items,
        "total": len(items),
        "ready": sum(1 for item in items if item.get("ready")),
        "not_ready": sum(1 for item in items if not item.get("ready")),
    }


def manage_integration_hooks(*, client: str, action: str, root: Path = ROOT, target_root: Path | None = None) -> dict[str, Any]:
    client = str(client or "").strip().lower()
    action = str(action or "").strip().lower()
    selected_root = Path(target_root).expanduser().resolve() if target_root is not None else root
    if action not in {"enable", "disable"}:
        raise ValueError(f"unsupported integration hook action: {action}")
    try:
        if client in {"codex", "claude", "gemini"}:
            if action == "enable":
                _merge_shell_hook_client(client, root=selected_root, memory_root=root)
            else:
                _disable_shell_hook_client(client, root=selected_root)
        elif client == "antigravity":
            if action == "enable":
                _merge_antigravity_hook_client(root=selected_root, memory_root=root)
                register_integration_project(client, selected_root, memory_root=root)
            else:
                _disable_antigravity_hook_client(root=selected_root)
                unregister_integration_project(client, selected_root, memory_root=root)
        elif client == "cursor":
            if action == "enable":
                _enable_cursor_project_hooks(root=selected_root, memory_root=root)
                register_integration_project(client, selected_root, memory_root=root)
            else:
                _disable_cursor_project_hooks(root=selected_root)
                unregister_integration_project(client, selected_root, memory_root=root)
        elif client == "opencode":
            if action == "enable":
                _enable_opencode_project_hooks(root=selected_root, memory_root=root)
                register_integration_project(client, selected_root, memory_root=root)
            else:
                _disable_opencode_project_hooks(root=selected_root)
                unregister_integration_project(client, selected_root, memory_root=root)
        else:
            raise ValueError(f"unsupported integration client: {client}")
    except PermissionError as exc:
        target_label = str(selected_root)
        operation = "activate" if action == "enable" else "deactivate"
        fallback = integration_hook_command(client=client, action=action, target_root=selected_root, root=root)
        raise PermissionError(
            f"Cannot {operation} Agent Context Engine hooks for `{target_label}`. "
            "The running monitor process does not have filesystem permission to update that project. "
            f"Run this command from a local terminal instead: `{fallback}`"
        ) from exc
    append_integration_history(
        client=client,
        action=f"hooks_{action}",
        root=root,
        target=selected_root,
        source="monitor",
        actor="monitor-ui",
        details={"scope": "project" if client == "cursor" else "root"},
    )
    summary = integration_summary(root=root, probe_gemini=False)
    item = next((entry for entry in summary["items"] if entry.get("client") == client), None)
    return {
        "ok": True,
        "client": client,
        "action": action,
        "target_root": str(selected_root),
        "command": integration_hook_command(client=client, action=action, target_root=selected_root, root=root),
        "item": item,
        "integrations": summary,
    }
