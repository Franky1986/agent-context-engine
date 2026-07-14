from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from ..infrastructure.config import ROOT, json_dumps, utc_now


HOOK_STATE_REL_PATH = Path("memory") / "local" / "hooks-state.json"
HOOK_RUNNERS = ("codex", "claude", "cursor", "antigravity", "gemini", "opencode")


def _empty_runner_state() -> dict[str, Any]:
    return {
        "enabled": None,
        "updated_at": None,
        "updated_by": None,
        "disabled_at": None,
        "disabled_by": None,
        "reason": "",
    }


def _default_state() -> dict[str, Any]:
    return {
        "enabled": True,
        "updated_at": None,
        "updated_by": None,
        "disabled_at": None,
        "disabled_by": None,
        "reason": "",
        "runners": {runner: _empty_runner_state() for runner in HOOK_RUNNERS},
        "projects": {},
    }


def _normalize_runner_name(value: str | None) -> str:
    runner = str(value or "all").strip().lower()
    if runner in {"*", "global", "all"}:
        return "all"
    if runner not in HOOK_RUNNERS:
        raise ValueError(f"unsupported runner: {value!r}")
    return runner


def _normalize_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    state = _default_state()
    payload = payload if isinstance(payload, dict) else {}
    state["enabled"] = bool(payload.get("enabled", True))
    state["updated_at"] = payload.get("updated_at")
    state["updated_by"] = payload.get("updated_by")
    state["disabled_at"] = payload.get("disabled_at")
    state["disabled_by"] = payload.get("disabled_by")
    state["reason"] = str(payload.get("reason") or "")
    runners_payload = payload.get("runners")
    if not isinstance(runners_payload, dict):
        runners_payload = {}
    for runner in HOOK_RUNNERS:
        entry = runners_payload.get(runner)
        if not isinstance(entry, dict):
            continue
        normalized = _empty_runner_state()
        raw_enabled = entry.get("enabled")
        if isinstance(raw_enabled, bool):
            normalized["enabled"] = raw_enabled
        normalized["updated_at"] = entry.get("updated_at")
        normalized["updated_by"] = entry.get("updated_by")
        normalized["disabled_at"] = entry.get("disabled_at")
        normalized["disabled_by"] = entry.get("disabled_by")
        normalized["reason"] = str(entry.get("reason") or "")
        state["runners"][runner] = normalized
    projects_payload = payload.get("projects")
    if isinstance(projects_payload, dict):
        for project_path, project_payload in projects_payload.items():
            if not isinstance(project_payload, dict) or not str(project_path).strip():
                continue
            project_state = _default_state()
            project_state.pop("projects", None)
            project_state["enabled"] = bool(project_payload.get("enabled", True))
            project_state["updated_at"] = project_payload.get("updated_at")
            project_state["updated_by"] = project_payload.get("updated_by")
            project_state["disabled_at"] = project_payload.get("disabled_at")
            project_state["disabled_by"] = project_payload.get("disabled_by")
            project_state["reason"] = str(project_payload.get("reason") or "")
            runner_payload = project_payload.get("runners")
            runner_payload = runner_payload if isinstance(runner_payload, dict) else {}
            for runner in HOOK_RUNNERS:
                entry = runner_payload.get(runner)
                if not isinstance(entry, dict):
                    continue
                normalized = _empty_runner_state()
                if isinstance(entry.get("enabled"), bool):
                    normalized["enabled"] = entry["enabled"]
                for key in ("updated_at", "updated_by", "disabled_at", "disabled_by"):
                    normalized[key] = entry.get(key)
                normalized["reason"] = str(entry.get("reason") or "")
                project_state["runners"][runner] = normalized
            state["projects"][str(Path(str(project_path)).expanduser().resolve())] = project_state
    return state


def hooks_state_path(*, root: Path = ROOT) -> Path:
    return root / HOOK_STATE_REL_PATH


def load_hooks_state(*, root: Path = ROOT) -> dict[str, Any]:
    path = hooks_state_path(root=root)
    if not path.exists():
        return _default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _default_state()
    return _normalize_state(payload if isinstance(payload, dict) else None)


def save_hooks_state(state: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    normalized = _normalize_state(state)
    path = hooks_state_path(root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(normalized) + "\n", encoding="utf-8")
    return normalized


def hook_runner_status(client: str, *, root: Path = ROOT, project_root: Path | None = None) -> dict[str, Any]:
    runner = _normalize_runner_name(client)
    if runner == "all":
        raise ValueError("runner-specific status requires a concrete client")
    state = load_hooks_state(root=root)
    runner_entry = dict(state["runners"][runner])
    global_enabled = bool(state["enabled"])
    runner_override = runner_entry.get("enabled")
    if global_enabled is False:
        return {
            "client": runner,
            "enabled": False,
            "source": "global_disabled",
            "global_enabled": False,
            "runner_override": runner_override,
            "disabled_at": state.get("disabled_at"),
            "disabled_by": state.get("disabled_by"),
            "reason": state.get("reason") or "",
        }
    if runner_override is False:
        return {
            "client": runner,
            "enabled": False,
            "source": "runner_disabled",
            "global_enabled": True,
            "runner_override": False,
            "disabled_at": runner_entry.get("disabled_at"),
            "disabled_by": runner_entry.get("disabled_by"),
            "reason": runner_entry.get("reason") or "",
        }
    project_path = str(project_root.expanduser().resolve()) if project_root is not None else ""
    project_state = state["projects"].get(project_path) if project_path else None
    if isinstance(project_state, dict) and project_state.get("enabled") is False:
        return {
            "client": runner,
            "enabled": False,
            "source": "project_disabled",
            "global_enabled": True,
            "runner_override": runner_override,
            "project": project_path,
            "disabled_at": project_state.get("disabled_at"),
            "disabled_by": project_state.get("disabled_by"),
            "reason": project_state.get("reason") or "",
        }
    project_runner = (
        dict(project_state.get("runners") or {}).get(runner)
        if isinstance(project_state, dict)
        else None
    )
    if isinstance(project_runner, dict) and project_runner.get("enabled") is False:
        return {
            "client": runner,
            "enabled": False,
            "source": "project_runner_disabled",
            "global_enabled": True,
            "runner_override": runner_override,
            "project": project_path,
            "disabled_at": project_runner.get("disabled_at"),
            "disabled_by": project_runner.get("disabled_by"),
            "reason": project_runner.get("reason") or "",
        }
    if runner_override is True:
        return {
            "client": runner,
            "enabled": True,
            "source": "runner_enabled",
            "global_enabled": True,
            "runner_override": True,
            "disabled_at": None,
            "disabled_by": None,
            "reason": runner_entry.get("reason") or "",
        }
    return {
        "client": runner,
        "enabled": True,
        "source": "default_enabled",
        "global_enabled": True,
        "runner_override": None,
        "disabled_at": None,
        "disabled_by": None,
        "reason": "",
    }


def hooks_enabled_for(client: str, *, root: Path = ROOT, project_root: Path | None = None) -> bool:
    return bool(hook_runner_status(client, root=root, project_root=project_root)["enabled"])


def hooks_control_status(*, root: Path = ROOT) -> dict[str, Any]:
    state = load_hooks_state(root=root)
    runners = [hook_runner_status(runner, root=root) for runner in HOOK_RUNNERS]
    disabled = [item for item in runners if not item["enabled"]]
    projects = []
    for project_path, project_state in sorted(state["projects"].items()):
        project_runners = [
            hook_runner_status(runner, root=root, project_root=Path(project_path))
            for runner in HOOK_RUNNERS
        ]
        projects.append(
            {
                "path": project_path,
                "enabled": bool(project_state.get("enabled", True)),
                "disabled_at": project_state.get("disabled_at"),
                "disabled_by": project_state.get("disabled_by"),
                "reason": project_state.get("reason") or "",
                "runners": project_runners,
                "disabled_runners": [item["client"] for item in project_runners if not item["enabled"]],
            }
        )
    return {
        "enabled": bool(state["enabled"]),
        "updated_at": state.get("updated_at"),
        "updated_by": state.get("updated_by"),
        "disabled_at": state.get("disabled_at"),
        "disabled_by": state.get("disabled_by"),
        "reason": state.get("reason") or "",
        "runners": runners,
        "disabled_runner_count": len(disabled),
        "disabled_runners": [item["client"] for item in disabled],
        "projects": projects,
        "disabled_project_count": sum(1 for item in projects if not item["enabled"]),
    }


def set_hooks_enabled(
    *,
    enabled: bool,
    runner: str = "all",
    actor: str,
    reason: str = "",
    root: Path = ROOT,
    project_root: Path | None = None,
) -> dict[str, Any]:
    target = _normalize_runner_name(runner)
    state = load_hooks_state(root=root)
    now = utc_now()
    selected_state = state
    if project_root is not None:
        project_path = str(project_root.expanduser().resolve())
        selected_state = dict(state["projects"].get(project_path) or _default_state())
        selected_state.pop("projects", None)
        state["projects"][project_path] = selected_state
    if target == "all":
        selected_state["enabled"] = bool(enabled)
        selected_state["updated_at"] = now
        selected_state["updated_by"] = actor
        selected_state["reason"] = str(reason or "")
        if enabled:
            selected_state["disabled_at"] = None
            selected_state["disabled_by"] = None
        else:
            selected_state["disabled_at"] = now
            selected_state["disabled_by"] = actor
    else:
        entry = dict(selected_state["runners"][target])
        entry["enabled"] = bool(enabled)
        entry["updated_at"] = now
        entry["updated_by"] = actor
        entry["reason"] = str(reason or "")
        if enabled:
            entry["disabled_at"] = None
            entry["disabled_by"] = None
        else:
            entry["disabled_at"] = now
            entry["disabled_by"] = actor
        selected_state["runners"][target] = entry
    save_hooks_state(state, root=root)
    return hooks_control_status(root=root)


def _direct_user_control_blocks(prompt: str | None, start_patterns: tuple[str, ...]) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    patterns = tuple(pattern.lower() for pattern in start_patterns)
    for raw in (prompt or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lowered = stripped.lower()
        starts_control = lowered.startswith(
            (
                "hooks-disable",
                "hooks-enable",
                "hooks-status",
                "firewall add",
                "firewall disable",
                "firewall enable",
                "approve explain",
            )
        )
        if lowered.startswith(patterns):
            if current:
                blocks.append(current)
            current = [stripped]
            continue
        if current and starts_control:
            blocks.append(current)
            current = []
            continue
        if current:
            current.append(stripped)
    if current:
        blocks.append(current)
    return [" ".join(block).strip() for block in blocks]


def direct_user_hooks_disable_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, ("hooks-disable",))


def direct_user_hooks_enable_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, ("hooks-enable",))


def direct_user_hooks_status_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, ("hooks-status",))


def prompt_contains_only_hook_control(prompt: str | None) -> bool:
    lines = [line.strip() for line in (prompt or "").splitlines() if line.strip()]
    if not lines:
        return False
    return all(
        line.lower().startswith(("hooks-disable", "hooks-enable", "hooks-status"))
        for line in lines
    )


def _parse_hooks_command(line: str, expected_action: str) -> tuple[str, str, bool]:
    try:
        parts = shlex.split(str(line or ""))
    except ValueError as exc:
        raise ValueError(f"invalid hooks command quoting: {exc}") from exc
    if not parts or parts[0].lower() != expected_action:
        raise ValueError(f"expected: {expected_action} [--project] [--runner <runner>] [--reason <reason>]")
    runner = "all"
    reason = ""
    project = False
    idx = 1
    while idx < len(parts):
        token = parts[idx]
        if token == "--runner":
            if idx + 1 >= len(parts):
                raise ValueError("--runner requires a value")
            runner = _normalize_runner_name(parts[idx + 1])
            idx += 2
            continue
        if token == "--reason":
            if idx + 1 >= len(parts):
                raise ValueError("--reason requires a value")
            reason = parts[idx + 1]
            idx += 2
            continue
        if token == "--project":
            project = True
            idx += 1
            continue
        raise ValueError(f"unexpected hooks command token: {token}")
    return runner, reason, project


def apply_direct_user_hook_state_commands(
    prompt: str | None,
    *,
    root: Path = ROOT,
    project_root: Path | None = None,
) -> list[str]:
    if not prompt_contains_only_hook_control(prompt):
        return []
    messages: list[str] = []
    for line in direct_user_hooks_disable_lines(prompt):
        runner, reason, project = _parse_hooks_command(line, "hooks-disable")
        selected_project = project_root if project else None
        if project and selected_project is None:
            raise ValueError("--project requires a resolved current project directory")
        set_hooks_enabled(
            enabled=False,
            runner=runner,
            actor="user-chat",
            reason=reason,
            root=root,
            project_root=selected_project,
        )
        selected_status = hook_runner_status(
            runner if runner != "all" else HOOK_RUNNERS[0],
            root=root,
            project_root=selected_project,
        )
        scope = f" in project {selected_project.resolve()}" if selected_project else " globally"
        if runner == "all":
            messages.append(
                f"Hooks disabled{scope} at {selected_status['disabled_at']} by {selected_status['disabled_by']}."
            )
        else:
            messages.append(
                f"Hooks disabled for {runner}{scope} at {selected_status['disabled_at']} "
                f"by {selected_status['disabled_by']}."
            )
    for line in direct_user_hooks_enable_lines(prompt):
        runner, reason, project = _parse_hooks_command(line, "hooks-enable")
        selected_project = project_root if project else None
        if project and selected_project is None:
            raise ValueError("--project requires a resolved current project directory")
        set_hooks_enabled(enabled=True, runner=runner, actor="user-chat", reason=reason, root=root, project_root=selected_project)
        scope = f" in project {selected_project.resolve()}" if selected_project else " globally"
        effective_runners = (runner,) if runner != "all" else HOOK_RUNNERS
        effective_statuses = [
            hook_runner_status(
                effective_runner,
                root=root,
                project_root=selected_project,
            )
            for effective_runner in effective_runners
        ]
        disabled_statuses = [item for item in effective_statuses if not item["enabled"]]
        if not disabled_statuses:
            if runner == "all":
                messages.append(f"Hooks enabled{scope}.")
            else:
                messages.append(f"Hooks enabled for {runner}{scope}.")
        else:
            disabled_detail = ", ".join(
                f"{item['client']}:{item.get('source') or 'disabled'}"
                for item in disabled_statuses
            )
            if runner == "all":
                messages.append(
                    f"Hooks overrides cleared{scope}; hooks remain disabled ({disabled_detail})."
                )
            else:
                messages.append(
                    f"Hooks override cleared for {runner}{scope}; hooks remain disabled ({disabled_detail})."
                )
    for line in direct_user_hooks_status_lines(prompt):
        runner, _reason, project = _parse_hooks_command(line, "hooks-status")
        selected_project = project_root if project else None
        if project and selected_project is None:
            raise ValueError("--project requires a resolved current project directory")
        status = hooks_control_status(root=root)
        global_state = "enabled" if status["enabled"] else "disabled"
        summary = f"Hooks status: global={global_state}"
        if status["disabled_runner_count"]:
            summary += " disabled_runners=" + ",".join(status["disabled_runners"])
        messages.append(summary)
        for runner_state in status["runners"]:
            state_text = "enabled" if runner_state["enabled"] else "disabled"
            detail = f"- {runner_state['client']}: {state_text} ({runner_state['source']})"
            if runner_state.get("disabled_by"):
                detail += f" by={runner_state['disabled_by']}"
            if runner_state.get("disabled_at"):
                detail += f" at={runner_state['disabled_at']}"
            messages.append(detail)
        if selected_project:
            selected_runners = HOOK_RUNNERS if runner == "all" else (runner,)
            messages.append(f"Project: {selected_project.resolve()}")
            for selected_runner in selected_runners:
                project_status = hook_runner_status(selected_runner, root=root, project_root=selected_project)
                state_text = "enabled" if project_status["enabled"] else "disabled"
                messages.append(f"- {selected_runner}: {state_text} ({project_status['source']})")
    return messages
