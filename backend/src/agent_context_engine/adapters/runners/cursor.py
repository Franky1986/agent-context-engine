from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from ...infrastructure.config import ROOT, json_dumps, safe_slug, utc_now


CURSOR_EVENTS = [
    "beforeSubmitPrompt",
    "afterAgentResponse",
    "beforeShellExecution",
    "afterShellExecution",
    "beforeMCPExecution",
    "afterMCPExecution",
    "afterFileEdit",
    "beforeReadFile",
    "stop",
]
CURSOR_COMMAND = "./.cursor/hooks/hook_adapter.sh"


def normalize_cursor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    event = (
        payload.get("hook_event_name")
        or payload.get("event_name")
        or payload.get("hookName")
        or payload.get("hook_name")
        or payload.get("event")
        or payload.get("type")
    )
    if event:
        normalized["hook_event_name"] = str(event)
    event_lower = str(event or "").lower()
    session_id = (
        payload.get("session_id")
        or payload.get("conversation_id")
        or payload.get("conversationId")
        or payload.get("chat_id")
        or payload.get("chatId")
        or payload.get("thread_id")
    )
    if session_id:
        normalized["session_id"] = str(session_id)
    cwd = (
        payload.get("cwd")
        or payload.get("workspace_path")
        or payload.get("workspacePath")
        or payload.get("workspace_root")
        or payload.get("workspaceRoot")
        or payload.get("project_path")
    )
    if cwd:
        normalized["cwd"] = str(cwd)
    prompt = payload.get("prompt") or payload.get("user_prompt") or payload.get("userPrompt") or payload.get("message")
    if prompt and "prompt" not in normalized:
        normalized["prompt"] = str(prompt)
    assistant = payload.get("last_assistant_message") or payload.get("assistant_message") or payload.get("response") or payload.get("text")
    if assistant and "last_assistant_message" not in normalized:
        normalized["last_assistant_message"] = str(assistant)
    tool_name = payload.get("tool_name") or payload.get("toolName")
    if not tool_name and event_lower in {"beforeshellexecution", "aftershellexecution"}:
        tool_name = "Bash"
    if not tool_name:
        tool_name = payload.get("command") or payload.get("shell_command")
    if tool_name and "tool_name" not in normalized:
        normalized["tool_name"] = str(tool_name)
    if "tool_input" not in normalized:
        for key in ("toolInput", "input", "args", "command"):
            if key in payload:
                normalized["tool_input"] = payload[key]
                break
    if "tool_response" not in normalized:
        for key in ("toolResponse", "output", "result", "stdout"):
            if key in payload:
                value = payload[key]
                normalized["tool_response"] = value if isinstance(value, str) else json_dumps(value)
                break
    return normalized


def cursor_paths(root: Path = ROOT) -> tuple[Path, Path]:
    return root / ".cursor" / "hooks.json", root / ".cursor" / "hooks" / "hook_adapter.sh"


def cursor_hook_entry() -> dict[str, str]:
    return {"command": CURSOR_COMMAND}


def is_agent_memory_cursor_hook(entry: Any) -> bool:
    return isinstance(entry, dict) and str(entry.get("command") or "") == CURSOR_COMMAND


def load_cursor_hooks(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "hooks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Cursor hooks JSON: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid Cursor hooks JSON object: {path}")
    data.setdefault("version", 1)
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise ValueError(f"invalid Cursor hooks map: {path}")
    return data


def write_cursor_hooks(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def enable_cursor_hooks(root: Path = ROOT) -> tuple[Path, Path, Path | None]:
    hooks_path, script_path = cursor_paths(root)
    backup_path = None
    if hooks_path.exists():
        backup_path = hooks_path.with_suffix(f".json.bak-{safe_slug(utc_now())}")
        shutil.copy2(hooks_path, backup_path)
    data = load_cursor_hooks(hooks_path)
    hooks = data["hooks"]
    for event in CURSOR_EVENTS:
        entries = hooks.setdefault(event, [])
        if not isinstance(entries, list):
            entries = []
            hooks[event] = entries
        if not any(is_agent_memory_cursor_hook(entry) for entry in entries):
            entries.append(cursor_hook_entry())
    write_cursor_hooks(hooks_path, data)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    return hooks_path, script_path, backup_path


def disable_cursor_hooks(root: Path = ROOT) -> tuple[Path, int, Path | None]:
    hooks_path, _script_path = cursor_paths(root)
    if not hooks_path.exists():
        return hooks_path, 0, None
    backup_path = hooks_path.with_suffix(f".json.bak-{safe_slug(utc_now())}")
    shutil.copy2(hooks_path, backup_path)
    data = load_cursor_hooks(hooks_path)
    removed = 0
    hooks = data["hooks"]
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept = []
        for entry in entries:
            if is_agent_memory_cursor_hook(entry):
                removed += 1
            else:
                kept.append(entry)
        if kept:
            hooks[event] = kept
        else:
            hooks.pop(event, None)
    write_cursor_hooks(hooks_path, data)
    return hooks_path, removed, backup_path


def cursor_status(root: Path = ROOT) -> dict[str, Any]:
    hooks_path, script_path = cursor_paths(root)
    active_events: list[str] = []
    if hooks_path.exists():
        data = load_cursor_hooks(hooks_path)
        for event, entries in data.get("hooks", {}).items():
            if isinstance(entries, list) and any(is_agent_memory_cursor_hook(entry) for entry in entries):
                active_events.append(str(event))
    return {
        "hooks_path": hooks_path,
        "script_path": script_path,
        "hooks_exists": hooks_path.exists(),
        "script_exists": script_path.exists(),
        "active_events": sorted(active_events),
    }


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sync_cursor_payload_metrics(conn: sqlite3.Connection, session_id: str, seq: int, payload: dict[str, Any], recorded_at: str) -> None:
    input_tokens = _int_or_none(payload.get("input_tokens"))
    output_tokens = _int_or_none(payload.get("output_tokens"))
    cache_read_tokens = _int_or_none(payload.get("cache_read_tokens"))
    cache_write_tokens = _int_or_none(payload.get("cache_write_tokens"))
    reasoning_tokens = _int_or_none(payload.get("reasoning_output_tokens") or payload.get("reasoning_tokens"))
    total_tokens = _int_or_none(payload.get("total_tokens"))
    if total_tokens is None and (input_tokens is not None or output_tokens is not None or reasoning_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0) + (reasoning_tokens or 0)
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return
    turn_id = str(payload.get("generation_id") or payload.get("turn_id") or seq)
    with conn:
        conn.execute(
            """
            insert or ignore into token_usage (
              session_id, turn_id, recorded_at, input_tokens,
              cached_input_tokens, output_tokens, reasoning_output_tokens,
              total_tokens, model_context_window, raw_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                turn_id,
                recorded_at,
                input_tokens,
                cache_read_tokens,
                output_tokens,
                reasoning_tokens,
                total_tokens,
                _int_or_none(payload.get("model_context_window")),
                json_dumps(
                    {
                        "source": "cursor-hook-payload",
                        "model": payload.get("model"),
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_read_tokens": cache_read_tokens,
                        "cache_write_tokens": cache_write_tokens,
                        "reasoning_output_tokens": reasoning_tokens,
                        "total_tokens": total_tokens,
                        "payload": payload,
                    }
                ),
            ),
        )
        conn.execute(
            """
            insert into turn_metrics (
              session_id, turn_id, completed_at, last_agent_message, raw_complete_json
            ) values (?, ?, ?, ?, ?)
            on conflict(session_id, turn_id) do update set
              completed_at = coalesce(excluded.completed_at, turn_metrics.completed_at),
              last_agent_message = coalesce(excluded.last_agent_message, turn_metrics.last_agent_message),
              raw_complete_json = excluded.raw_complete_json
            """,
            (
                session_id,
                turn_id,
                recorded_at,
                payload.get("last_assistant_message") or payload.get("text"),
                json_dumps(payload),
            ),
        )
