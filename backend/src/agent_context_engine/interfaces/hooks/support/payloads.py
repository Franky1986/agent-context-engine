from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from ....infrastructure.config import MEMORY_DIR, json_dumps, safe_slug


def load_payload() -> dict[str, Any]:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # Claude Code embeds literal control characters (e.g. 0x0A newlines) in hook
        # payloads without escaping them, which violates RFC 8259. Repair by replacing
        # all control characters with their \uXXXX equivalents before re-parsing.
        try:
            cleaned = re.sub(r"[\x00-\x1f]", lambda m: f"\\u{ord(m.group(0)):04x}", raw)
            payload = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return {"hook_event_name": "invalid-json", "raw": raw[:8000], "error": str(exc)}
    return payload if isinstance(payload, dict) else {"payload": payload}


def event_name(payload: dict[str, Any]) -> str:
    return str(
        payload.get("hook_event_name")
        or payload.get("event_name")
        or payload.get("hookName")
        or payload.get("hook_name")
        or payload.get("event")
        or payload.get("type")
        or "unknown"
    )


def is_stop_event(name: str) -> bool:
    return name.lower() == "stop"


def is_session_start_event(name: str) -> bool:
    return name in {"SessionStart", "sessionStart"} or name.lower() == "sessionstart"


def should_sync_transcript(client: str, name: str) -> bool:
    if is_stop_event(name):
        return True
    if client == "codex" and name in {"SessionStart", "sessionStart", "UserPromptSubmit", "userPromptSubmit"}:
        return True
    return False


def write_event_jsonl(client: str, session_id: str, event: dict[str, Any]) -> Path:
    out = MEMORY_DIR / "events" / safe_slug(client) / f"{safe_slug(session_id)}.jsonl"
    if os.environ.get("AGENT_MEMORY_WRITE_EVENT_JSONL", "0") not in {"1", "true", "True", "yes"}:
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as handle:
        handle.write(json_dumps(event) + "\n")
    return out


def one_line(value: str | None, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def normalized_path(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return str(Path(value).expanduser())


def effective_start_cwd(payload_cwd: str) -> str:
    launch_cwd = normalized_path(os.environ.get("AGENT_MEMORY_LAUNCH_CWD"))
    root_cwd = normalized_path(os.environ.get("AGENT_CONTEXT_ENGINE_ROOT"))
    # Root-managed wrappers `cd` into the Agent Memory installation before
    # launching the runner. Preserve the original shell folder as the initial
    # project/workdir context whenever it differs from the memory root, no
    # matter whether that launch folder lives inside or outside the root tree.
    if launch_cwd and launch_cwd != root_cwd:
        return launch_cwd
    return normalized_path(payload_cwd)
