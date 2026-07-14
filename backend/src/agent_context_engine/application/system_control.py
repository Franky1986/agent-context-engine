from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import sqlite3
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..adapters.system_scheduler import PlatformSystemScheduler
from ..infrastructure.config import ROOT, json_dumps, memory_root, utc_now
from ..ports.system_scheduler import SystemSchedulerPort
from .hooks_state import hooks_state_path, load_hooks_state
from .instance_profile import load_installation_profile, resolve_monitor_profile


SYSTEM_CONTROL_SCHEMA_VERSION = 1
SYSTEM_CONTROL_MODES = {"enabled", "disabling", "disabled", "enabling", "partial"}
SYSTEM_CONTROL_RELATIVE_PATH = Path("local") / "system-control.json"
SYSTEM_CONTROL_ANCHOR_RELATIVE_PATH = Path("local") / "system-control.anchor.json"
SYSTEM_CONTROL_LOCK_RELATIVE_PATH = Path("status") / "locks" / "system-control.lock"
SYSTEM_CONTROL_AUDIT_RELATIVE_PATH = Path("logs") / "system-control-audit.jsonl"
_USER_PROMPT_EVENTS = {"UserPromptSubmit", "userPromptSubmit", "beforeSubmitPrompt"}
SYSTEM_CONTROL_PROVENANCE_ASSURANCE = "instrumented_runner_event_unverified"


@dataclass(frozen=True)
class SystemCommand:
    name: str
    scope: str = "all"
    reason: str = ""
    confirmation: str = ""


def _build_hook_entry_boundary():
    marker = object()

    class InstrumentedHookEntry:
        __slots__ = ("_token",)

        def __init__(self) -> None:
            self._token = marker

    def mint() -> object | None:
        """Mark the normal adapter path; this is not same-user authentication."""
        if not _instrumented_hook_descriptor_open():
            return None
        return InstrumentedHookEntry()

    def require(entry: object) -> None:
        if not isinstance(entry, InstrumentedHookEntry) or entry._token is not marker:
            raise PermissionError("instrumented runner hook entry required")

    return mint, require


_instrumented_hook_entry, _require_hook_entry = _build_hook_entry_boundary()


def _instrumented_hook_descriptor_open() -> bool:
    try:
        os.fstat(3)
    except OSError:
        return False
    return True


def system_control_path(*, installation_root: Path = ROOT) -> Path:
    return memory_root(installation_root) / SYSTEM_CONTROL_RELATIVE_PATH


def system_control_anchor_path(*, installation_root: Path = ROOT) -> Path:
    return memory_root(installation_root) / SYSTEM_CONTROL_ANCHOR_RELATIVE_PATH


def system_control_lock_path(*, installation_root: Path = ROOT) -> Path:
    return memory_root(installation_root) / SYSTEM_CONTROL_LOCK_RELATIVE_PATH


def system_control_audit_path(*, installation_root: Path = ROOT) -> Path:
    return memory_root(installation_root) / SYSTEM_CONTROL_AUDIT_RELATIVE_PATH


def _enabled_state() -> dict[str, Any]:
    return {
        "schema_version": SYSTEM_CONTROL_SCHEMA_VERSION,
        "mode": "enabled",
        "scope": "all",
        "reason": "",
        "operation_id": "",
        "actor": "instrumented_user_prompt",
        "disabled_at": "",
        "updated_at": "",
        "previous": {},
        "background_drain": {},
        "steps": [],
        "last_error": "",
        "state_valid": True,
        "state_present": False,
        "integrity": "virgin_uninitialized",
        "provenance_assurance": SYSTEM_CONTROL_PROVENANCE_ASSURANCE,
    }


def _validate_state(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("system-control state must be a JSON object")
    if int(payload.get("schema_version") or 0) != SYSTEM_CONTROL_SCHEMA_VERSION:
        raise ValueError("unsupported system-control schema version")
    mode = str(payload.get("mode") or "")
    if mode not in SYSTEM_CONTROL_MODES:
        raise ValueError("invalid system-control mode")
    if str(payload.get("scope") or "all") != "all":
        raise ValueError("unsupported system-control scope")
    normalized = _enabled_state()
    normalized.update(payload)
    normalized["state_valid"] = True
    normalized["state_present"] = True
    normalized["steps"] = list(payload.get("steps") or [])
    normalized["previous"] = dict(payload.get("previous") or {})
    normalized["background_drain"] = dict(payload.get("background_drain") or {})
    return normalized


def _invalid_state(path: Path, error: str) -> dict[str, Any]:
    state = _enabled_state()
    state.update(
        {
            "mode": "partial",
            "state_valid": False,
            "state_present": path.exists(),
            "last_error": error,
            "integrity": "invalid",
        }
    )
    return state


def system_control_status(*, installation_root: Path = ROOT) -> dict[str, Any]:
    root = installation_root.expanduser().resolve()
    path = system_control_path(installation_root=installation_root)
    anchor_path = system_control_anchor_path(installation_root=root)
    if not path.exists():
        if anchor_path.exists():
            state = _invalid_state(path, "system-control state is missing after initialization")
        else:
            state = _enabled_state()
    else:
        try:
            raw = path.read_bytes()
            state = _validate_state(json.loads(raw.decode("utf-8")))
            if anchor_path.exists():
                anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
                expected_hash = str(anchor.get("state_sha256") or "") if isinstance(anchor, dict) else ""
                actual_hash = hashlib.sha256(raw).hexdigest()
                if not expected_hash or expected_hash != actual_hash:
                    raise ValueError("system-control state integrity anchor does not match")
                state["integrity"] = "anchored"
            else:
                state["integrity"] = "legacy_unanchored"
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            state = _invalid_state(path, f"invalid system-control state: {exc}")
    state["admission_open"] = state["mode"] == "enabled" and bool(state["state_valid"])
    state["state_path"] = str(path)
    state["anchor_path"] = str(anchor_path)
    state["memory_root"] = str(memory_root(installation_root))
    if not state["admission_open"]:
        drain = dict(state.get("background_drain") or {})
        drain.update(_background_observation(installation_root))
        state["background_drain"] = drain
    if not state["admission_open"]:
        state["recovery_command"] = (
            'system-recover --scope all --reason "State file recovery" --confirm "rebuild-disabled-state"'
            if not state["state_valid"]
            else 'system-enable --scope all --reason "Maintenance complete"'
        )
    else:
        state["recovery_command"] = ""
    return state


def system_admission_open(*, installation_root: Path = ROOT) -> bool:
    return bool(system_control_status(installation_root=installation_root)["admission_open"])


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json_dumps(payload) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _state_bytes(payload: dict[str, Any]) -> bytes:
    return (json_dumps(payload) + "\n").encode("utf-8")


def _write_control_state(root: Path, payload: dict[str, Any]) -> None:
    path = system_control_path(installation_root=root)
    anchor_path = system_control_anchor_path(installation_root=root)
    if not anchor_path.exists():
        _atomic_write(
            anchor_path,
            {
                "schema_version": 1,
                "initialized_at": utc_now(),
                "updated_at": utc_now(),
                "state_sha256": "initializing",
            },
        )
    _atomic_write(path, payload)
    raw = path.read_bytes()
    try:
        existing_anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        existing_anchor = {}
    _atomic_write(
        anchor_path,
        {
            "schema_version": 1,
            "initialized_at": str(existing_anchor.get("initialized_at") or utc_now()),
            "updated_at": utc_now(),
            "state_sha256": hashlib.sha256(raw).hexdigest(),
        },
    )


def _acquire_lock(root: Path, *, timeout_seconds: float = 5.0) -> Path:
    path = system_control_lock_path(installation_root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            path.mkdir()
            (path / "owner.json").write_text(
                json_dumps({"pid": os.getpid(), "created_at": utc_now()}) + "\n",
                encoding="utf-8",
            )
            return path
        except FileExistsError:
            owner_path = path / "owner.json"
            try:
                owner = json.loads(owner_path.read_text(encoding="utf-8"))
                owner_pid = int(owner.get("pid") or 0)
                os.kill(owner_pid, 0)
            except ProcessLookupError:
                shutil.rmtree(path, ignore_errors=True)
                continue
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                try:
                    stale = time.time() - path.stat().st_mtime > 900
                except OSError:
                    stale = False
                if stale:
                    shutil.rmtree(path, ignore_errors=True)
                    continue
            if time.monotonic() >= deadline:
                raise TimeoutError("system-control operation is already in progress")
            time.sleep(0.05)


def _release_lock(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def _audit(root: Path, payload: dict[str, Any]) -> None:
    path = system_control_audit_path(installation_root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = load_installation_profile(root)
    record = {
        "recorded_at": utc_now(),
        "instance_id": str(profile.get("instance_id") or root.name),
        "installation_root": str(root.resolve()),
        "memory_root": str(memory_root(root)),
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json_dumps(record) + "\n")


def audit_system_control_rejection(
    *,
    installation_root: Path = ROOT,
    raw_message: str | None,
    event_name: str,
    reason: str,
) -> None:
    """Record a rejected mutation attempt without retaining the user prompt."""
    command_name = str(raw_message or "").strip().split(maxsplit=1)[0]
    if command_name not in {"system-disable", "system-enable", "system-recover"}:
        return
    _audit(
        installation_root.expanduser().resolve(),
        {
            "command": command_name,
            "event_name": event_name,
            "provenance": SYSTEM_CONTROL_PROVENANCE_ASSURANCE,
            "result": "rejected",
            "error": reason,
        },
    )


def _hooks_snapshot(root: Path) -> dict[str, Any]:
    path = hooks_state_path(root=root)
    raw = path.read_bytes() if path.exists() else b""
    state = load_hooks_state(root=root)
    return {
        "state_sha256": hashlib.sha256(raw).hexdigest(),
        "state_present": path.exists(),
        "global_enabled": bool(state.get("enabled", True)),
        "disabled_runners": sorted(
            runner
            for runner, item in dict(state.get("runners") or {}).items()
            if isinstance(item, dict) and item.get("enabled") is False
        ),
    }


def _monitor_snapshot(root: Path) -> dict[str, Any]:
    profile = resolve_monitor_profile(root)
    return {
        "managed": True,
        "host": str(profile.get("host") or "127.0.0.1"),
        "port": int(profile.get("port") or 8787),
        "pid": int(profile.get("last_known_pid") or 0),
        "running": bool(profile.get("last_known_pid")),
        "suspended_behavior": "read_only",
    }


def _background_observation(root: Path) -> dict[str, Any]:
    db = memory_root(root) / "status" / "agent-memory.sqlite3"
    observation = {
        "currently_running": 0,
        "queued_not_started": 0,
        "last_checked_at": utc_now(),
    }
    if not db.exists():
        return observation
    try:
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type = 'table'")}
        if "dream_queue" in tables:
            observation["currently_running"] += int(conn.execute("select count(*) from dream_queue where status = 'running'").fetchone()[0])
            observation["queued_not_started"] += int(conn.execute("select count(*) from dream_queue where status = 'queued'").fetchone()[0])
        if "summary_windows" in tables:
            observation["currently_running"] += int(conn.execute("select count(*) from summary_windows where status = 'running'").fetchone()[0])
        if "hook_queue_audit" in tables:
            observation["queued_not_started"] += int(conn.execute("select count(*) from hook_queue_audit where status = 'queued'").fetchone()[0])
        conn.close()
    except (OSError, sqlite3.Error):
        observation["observation_error"] = "background state unavailable"
    return observation


def _step(name: str, *, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "status": "completed" if ok else "failed", "detail": detail, "updated_at": utc_now()}


def _disable_system(
    *,
    installation_root: Path = ROOT,
    reason: str,
    hook_entry: object,
    operation_id: str | None = None,
    scheduler: SystemSchedulerPort | None = None,
) -> dict[str, Any]:
    _require_hook_entry(hook_entry)
    root = installation_root.expanduser().resolve()
    scheduler = scheduler or PlatformSystemScheduler()
    operation_id = operation_id or str(uuid.uuid4())
    lock = _acquire_lock(root)
    try:
        current = system_control_status(installation_root=root)
        if current["mode"] == "disabled" and current["state_valid"]:
            _audit(root, {"operation_id": operation_id, "command": "system-disable", "reason": reason, "result": "already_disabled"})
            return current
        previous = current.get("previous") if current["mode"] in {"disabling", "partial"} and current["state_valid"] else None
        if not isinstance(previous, dict) or not previous:
            previous = {
                "hooks": _hooks_snapshot(root),
                "scheduler": scheduler.status(root),
                "monitor": _monitor_snapshot(root),
            }
        now = utc_now()
        drain = _background_observation(root)
        drain.update({"cutoff_at": str(current.get("disabled_at") or now), "running_at_cutoff": drain["currently_running"]})
        state = {
            "schema_version": SYSTEM_CONTROL_SCHEMA_VERSION,
            "mode": "disabling",
            "operation_id": operation_id,
            "scope": "all",
            "reason": reason,
            "actor": "instrumented_user_prompt",
            "disabled_at": str(current.get("disabled_at") or now),
            "updated_at": now,
            "previous": previous,
            "background_drain": drain,
            "steps": [_step("close_admission_gate", ok=True, detail="normal hook and background admission closed")],
            "last_error": "",
        }
        _write_control_state(root, state)
        scheduler_result = scheduler.disable(root, dict(previous.get("scheduler") or {}))
        state["steps"].append(_step("disable_scheduler", ok=bool(scheduler_result.get("ok")), detail=str(scheduler_result.get("detail") or scheduler_result.get("action") or "")))
        state["updated_at"] = utc_now()
        if scheduler_result.get("ok"):
            state["mode"] = "disabled"
        else:
            state["mode"] = "partial"
            state["last_error"] = str(scheduler_result.get("detail") or "scheduler disable failed")
        _write_control_state(root, state)
        _audit(root, {"operation_id": operation_id, "command": "system-disable", "scope": "all", "reason": reason, "previous_mode": current["mode"], "steps": state["steps"], "final_mode": state["mode"], "error": state["last_error"]})
        return system_control_status(installation_root=root)
    finally:
        _release_lock(lock)


def _enable_system(
    *,
    installation_root: Path = ROOT,
    reason: str,
    hook_entry: object,
    operation_id: str | None = None,
    scheduler: SystemSchedulerPort | None = None,
) -> dict[str, Any]:
    _require_hook_entry(hook_entry)
    root = installation_root.expanduser().resolve()
    scheduler = scheduler or PlatformSystemScheduler()
    operation_id = operation_id or str(uuid.uuid4())
    lock = _acquire_lock(root)
    try:
        current = system_control_status(installation_root=root)
        if current["mode"] == "enabled" and current["state_valid"]:
            _audit(root, {"operation_id": operation_id, "command": "system-enable", "reason": reason, "result": "already_enabled"})
            return current
        previous = current.get("previous")
        if not current["state_valid"] or not isinstance(previous, dict) or not isinstance(previous.get("scheduler"), dict):
            raise ValueError("safe restoration snapshot is unavailable; use the exact system-recover direct user command")
        derived_fields = {
            "admission_open",
            "anchor_path",
            "integrity",
            "memory_root",
            "provenance_assurance",
            "recovery_command",
            "state_path",
            "state_present",
            "state_valid",
        }
        state = {key: value for key, value in current.items() if key not in derived_fields}
        state.update({"mode": "enabling", "operation_id": operation_id, "reason": reason, "updated_at": utc_now(), "last_error": ""})
        state["steps"] = [_step("keep_admission_closed", ok=True)]
        _write_control_state(root, state)
        restore = scheduler.restore(root, dict(previous["scheduler"]))
        state["steps"].append(_step("restore_scheduler", ok=bool(restore.get("ok")), detail=str(restore.get("detail") or restore.get("action") or "")))
        hooks_now = _hooks_snapshot(root)
        hooks_before = dict(previous.get("hooks") or {})
        hooks_ok = hooks_now.get("state_sha256") == hooks_before.get("state_sha256")
        state["steps"].append(_step("verify_preserved_hooks", ok=hooks_ok, detail="hook state unchanged" if hooks_ok else "hook state drift detected"))
        if restore.get("ok") and hooks_ok:
            state["mode"] = "enabled"
            state["last_error"] = ""
            state["steps"].append(_step("open_admission_gate", ok=True))
        else:
            state["mode"] = "partial"
            state["last_error"] = str(restore.get("detail") or "hook-state drift prevents safe enable")
            scheduler.disable(root, dict(previous["scheduler"]))
        state["updated_at"] = utc_now()
        _write_control_state(root, state)
        _audit(root, {"operation_id": operation_id, "command": "system-enable", "scope": "all", "reason": reason, "previous_mode": current["mode"], "steps": state["steps"], "final_mode": state["mode"], "error": state["last_error"]})
        return system_control_status(installation_root=root)
    finally:
        _release_lock(lock)


def _recover_system(
    *,
    installation_root: Path = ROOT,
    reason: str,
    confirmation: str,
    hook_entry: object,
    scheduler: SystemSchedulerPort | None = None,
) -> dict[str, Any]:
    _require_hook_entry(hook_entry)
    if confirmation != "rebuild-disabled-state":
        raise ValueError("invalid recovery confirmation")
    root = installation_root.expanduser().resolve()
    scheduler = scheduler or PlatformSystemScheduler()
    operation_id = str(uuid.uuid4())
    lock = _acquire_lock(root)
    try:
        current = system_control_status(installation_root=root)
        if current["state_valid"]:
            raise ValueError("system-recover is only available for invalid system-control state")
        path = system_control_path(installation_root=root)
        backup = path.with_name(f"system-control.invalid-{int(time.time())}.json")
        if path.exists():
            shutil.copy2(path, backup)
        scheduler_before = scheduler.status(root)
        scheduler_result = scheduler.disable(root, scheduler_before)
        conservative_scheduler = dict(scheduler_before)
        conservative_scheduler["loaded"] = False
        conservative_scheduler["recovered_without_safe_snapshot"] = True
        now = utc_now()
        drain = _background_observation(root)
        drain.update({"cutoff_at": now, "running_at_cutoff": drain["currently_running"]})
        state = {
            "schema_version": SYSTEM_CONTROL_SCHEMA_VERSION,
            "mode": "disabled" if scheduler_result.get("ok") else "partial",
            "operation_id": operation_id,
            "scope": "all",
            "reason": reason,
            "actor": "instrumented_user_prompt",
            "disabled_at": now,
            "updated_at": utc_now(),
            "previous": {
                "hooks": _hooks_snapshot(root),
                "scheduler": conservative_scheduler,
                "monitor": _monitor_snapshot(root),
            },
            "background_drain": drain,
            "steps": [
                _step("close_admission_gate", ok=True),
                _step("preserve_invalid_state", ok=True, detail=str(backup)),
                _step("disable_scheduler", ok=bool(scheduler_result.get("ok")), detail=str(scheduler_result.get("detail") or "")),
            ],
            "last_error": "" if scheduler_result.get("ok") else str(scheduler_result.get("detail") or "scheduler disable failed"),
        }
        _write_control_state(root, state)
        _audit(root, {"operation_id": operation_id, "command": "system-recover", "reason": reason, "invalid_state_backup": str(backup), "final_mode": state["mode"], "steps": state["steps"]})
        return system_control_status(installation_root=root)
    finally:
        _release_lock(lock)


def parse_direct_user_system_command(raw_message: str | None) -> SystemCommand | None:
    raw = str(raw_message or "")
    stripped = raw.strip()
    if "```" in stripped and "system-" in stripped:
        raise ValueError("system control is not accepted from a Markdown code fence")
    if not stripped.startswith("system-"):
        return None
    if len([line for line in stripped.splitlines() if line.strip()]) != 1:
        raise ValueError("system control must be exactly one direct user line")
    if any(token in stripped for token in (";", "|", "&&", "||", "`", "$(`", ">", "<")):
        raise ValueError("shell operators and substitutions are not allowed")
    try:
        parts = shlex.split(stripped, posix=True)
    except ValueError as exc:
        raise ValueError(f"invalid system-control quoting: {exc}") from exc
    if not parts or parts[0] not in {"system-disable", "system-enable", "system-status", "system-recover"}:
        raise ValueError("unknown system-control command")
    if parts[0] == "system-status":
        if len(parts) != 1:
            raise ValueError("system-status accepts no arguments")
        return SystemCommand("system-status")
    values: dict[str, str] = {}
    index = 1
    allowed = {"--scope", "--reason"} | ({"--confirm"} if parts[0] == "system-recover" else set())
    while index < len(parts):
        flag = parts[index]
        if flag not in allowed or flag in values or index + 1 >= len(parts):
            raise ValueError(f"invalid or repeated system-control option: {flag}")
        values[flag] = parts[index + 1]
        index += 2
    if values.get("--scope") != "all" or not values.get("--reason", "").strip():
        raise ValueError("mutating system controls require --scope all and a non-empty --reason")
    if parts[0] == "system-recover" and values.get("--confirm") != "rebuild-disabled-state":
        raise ValueError('system-recover requires --confirm "rebuild-disabled-state"')
    return SystemCommand(parts[0], reason=values["--reason"].strip(), confirmation=values.get("--confirm", ""))


def render_system_control_result(state: dict[str, Any]) -> str:
    lines = [
        f"Agent Context Engine system mode: {state['mode']}",
        f"Normal hook/background admission: {'open' if state['admission_open'] else 'closed'}",
    ]
    if state.get("reason"):
        lines.append(f"Reason: {state['reason']}")
    failed = [str(step.get("name") or "unknown") for step in state.get("steps") or [] if step.get("status") == "failed"]
    if failed:
        lines.append("Failed steps: " + ", ".join(failed))
    if state.get("recovery_command"):
        lines.append("Direct user recovery line: " + str(state["recovery_command"]))
    return "\n".join(lines)


def apply_direct_user_system_command(
    raw_message: str | None,
    *,
    event_name: str,
    installation_root: Path = ROOT,
    session_id: str = "",
    event_seq: int | None = None,
    scheduler: SystemSchedulerPort | None = None,
) -> str | None:
    command = parse_direct_user_system_command(raw_message)
    if command is None:
        return None
    if event_name not in _USER_PROMPT_EVENTS:
        raise PermissionError("system controls require the current direct user prompt event")
    hook_entry = _instrumented_hook_entry()
    _require_hook_entry(hook_entry)
    if command.name == "system-status":
        state = system_control_status(installation_root=installation_root)
    elif command.name == "system-disable":
        state = _disable_system(installation_root=installation_root, reason=command.reason, hook_entry=hook_entry, scheduler=scheduler)
    elif command.name == "system-enable":
        state = _enable_system(installation_root=installation_root, reason=command.reason, hook_entry=hook_entry, scheduler=scheduler)
    else:
        state = _recover_system(installation_root=installation_root, reason=command.reason, confirmation=command.confirmation, hook_entry=hook_entry, scheduler=scheduler)
    if command.name != "system-status":
        _audit(
            installation_root,
            {
                "command": command.name,
                "session_id": session_id,
                "event_seq": int(event_seq or 0),
                "provenance": SYSTEM_CONTROL_PROVENANCE_ASSURANCE,
                "final_mode": state["mode"],
            },
        )
    return render_system_control_result(state)


_SUSPENDED_SAFE_COMMANDS = {
    "log-hook",
    "system-status",
    "status",
    "last",
    "folder",
    "context",
    "tool-calls",
    "tool-output",
    "file-accesses",
    "operational-facts",
    "handover",
    "use",
    "personal-context",
    "repo-context",
    "integrations-status",
    "hooks-status",
    "gemini-status",
    "antigravity-status",
    "opencode-status",
    "global-wrapper-status",
    "dream-v2-inspect",
    "dream-v2-audit",
    "dream-v2-readiness",
    "retrieval-runs",
    "retrieval-run",
    "quarantine",
    "metrics",
    "dream-insights",
    "dream-queue-status",
    "doctor",
    "check-installation",
    "install-discovery",
    "cursor-status",
    "launchagent-status",
    "scheduler-status",
    "graph-quality",
    "graph-status",
    "graph-validate",
    "graph-schema-context",
    "graph-query",
    "neo4j-status",
    "neo4j-import-status",
}
_SUSPENDED_SAFE_SUBCOMMANDS = {
    "personal": {"list", "show", "proposals", "audit"},
    "risk": {"list", "explain", "show"},
    "quarantine": {"list", "show"},
    "firewall": {"list", "show"},
    "schema-proposals": {"list", "registry"},
}
_SUSPENDED_SUBCOMMAND_ATTRS = {
    "personal": "personal_command",
    "risk": "risk_command",
    "quarantine": "quarantine_command",
    "firewall": "firewall_command",
    "schema-proposals": "schema_command",
}


def command_allowed_while_suspended(args: argparse.Namespace) -> bool:
    command = str(getattr(args, "command", "") or "")
    if command == "install-discovery" and getattr(args, "plan_json", None):
        return False
    allowed_subcommands = _SUSPENDED_SAFE_SUBCOMMANDS.get(command)
    if allowed_subcommands is not None:
        attr = _SUSPENDED_SUBCOMMAND_ATTRS[command]
        return str(getattr(args, attr, "") or "") in allowed_subcommands
    return command in _SUSPENDED_SAFE_COMMANDS


def cmd_system_status(args: argparse.Namespace) -> int:
    state = system_control_status(installation_root=ROOT)
    if bool(getattr(args, "json", False)):
        print(json_dumps(state))
    else:
        print(render_system_control_result(state))
        print(f"State: {state['state_path']}")
    return 0
