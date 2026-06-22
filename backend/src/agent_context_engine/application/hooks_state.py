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


def hook_runner_status(client: str, *, root: Path = ROOT) -> dict[str, Any]:
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


def hooks_enabled_for(client: str, *, root: Path = ROOT) -> bool:
    return bool(hook_runner_status(client, root=root)["enabled"])


def hooks_control_status(*, root: Path = ROOT) -> dict[str, Any]:
    state = load_hooks_state(root=root)
    runners = [hook_runner_status(runner, root=root) for runner in HOOK_RUNNERS]
    disabled = [item for item in runners if not item["enabled"]]
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
    }


def set_hooks_enabled(
    *,
    enabled: bool,
    runner: str = "all",
    actor: str,
    reason: str = "",
    root: Path = ROOT,
) -> dict[str, Any]:
    target = _normalize_runner_name(runner)
    state = load_hooks_state(root=root)
    now = utc_now()
    if target == "all":
        state["enabled"] = bool(enabled)
        state["updated_at"] = now
        state["updated_by"] = actor
        state["reason"] = str(reason or "")
        if enabled:
            state["disabled_at"] = None
            state["disabled_by"] = None
        else:
            state["disabled_at"] = now
            state["disabled_by"] = actor
    else:
        entry = dict(state["runners"][target])
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
        state["runners"][target] = entry
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


def _parse_hooks_command(line: str, expected_action: str) -> tuple[str, str]:
    try:
        parts = shlex.split(str(line or ""))
    except ValueError as exc:
        raise ValueError(f"invalid hooks command quoting: {exc}") from exc
    if not parts or parts[0].lower() != expected_action:
        raise ValueError(f"expected: {expected_action} [--runner <runner>] [--reason <reason>]")
    runner = "all"
    reason = ""
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
        raise ValueError(f"unexpected hooks command token: {token}")
    return runner, reason


def apply_direct_user_hook_state_commands(prompt: str | None, *, root: Path = ROOT) -> list[str]:
    messages: list[str] = []
    for line in direct_user_hooks_disable_lines(prompt):
        runner, reason = _parse_hooks_command(line, "hooks-disable")
        status = set_hooks_enabled(enabled=False, runner=runner, actor="user-chat", reason=reason, root=root)
        if runner == "all":
            messages.append(f"Hooks disabled globally at {status['disabled_at']} by {status['disabled_by']}.")
        else:
            runner_status = next(item for item in status["runners"] if item["client"] == runner)
            messages.append(f"Hooks disabled for {runner} at {runner_status['disabled_at']} by {runner_status['disabled_by']}.")
    for line in direct_user_hooks_enable_lines(prompt):
        runner, reason = _parse_hooks_command(line, "hooks-enable")
        set_hooks_enabled(enabled=True, runner=runner, actor="user-chat", reason=reason, root=root)
        if runner == "all":
            messages.append("Hooks enabled globally.")
        else:
            messages.append(f"Hooks enabled for {runner}.")
    for line in direct_user_hooks_status_lines(prompt):
        _runner, _reason = _parse_hooks_command(line, "hooks-status")
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
    return messages
