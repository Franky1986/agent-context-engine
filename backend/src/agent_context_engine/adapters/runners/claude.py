from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ...infrastructure.config import json_dumps

CLAUDE_PROJECTS = Path.home() / ".claude" / "projects"


def _cwd_to_project_dir(cwd: str) -> Path:
    """Map /Users/foo/bar → ~/.claude/projects/-Users-foo-bar (Claude's encoding)."""
    encoded = cwd.lstrip("/").replace("/", "-")
    return CLAUDE_PROJECTS / encoded


def claude_transcript_path(session_id: str, cwd: str | None) -> Path | None:
    """Locate the Claude session JSONL on disk."""
    if cwd:
        candidate = _cwd_to_project_dir(cwd) / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    if not CLAUDE_PROJECTS.exists():
        return None
    for proj_dir in CLAUDE_PROJECTS.iterdir():
        if not proj_dir.is_dir():
            continue
        candidate = proj_dir / f"{session_id}.jsonl"
        if candidate.exists():
            return candidate
    return None


def claude_session_title(session_id: str, cwd: str | None = None) -> str | None:
    """Read the display title from the first summary entry in the session JSONL."""
    path = claude_transcript_path(session_id, cwd)
    if not path:
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("type") == "summary" and row.get("summary"):
                    return str(row["summary"])
    except OSError:
        return None
    return None


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif item_type == "tool_result" and isinstance(item.get("content"), str):
            parts.append(f"[tool_result] {item['content']}")
    return "\n\n".join(part.strip() for part in parts if part and part.strip()).strip()


def _next_seq(conn: sqlite3.Connection, session_id: str) -> int:
    row = conn.execute(
        """
        select max(
          coalesce((select max(seq) from events where session_id = ?), 0),
          coalesce((select last_reserved_event_seq from sessions where session_id = ?), 0)
        ) as seq
        """,
        (session_id, session_id),
    ).fetchone()
    return int(row["seq"]) + 1


def sync_transcript_events_claude(conn: sqlite3.Connection, session_id: str, transcript_path: str) -> int:
    """Import Claude transcript user/assistant turns as deduplicated synthetic events."""
    path = Path(transcript_path)
    if not path.exists():
        return 0
    inserted = 0
    max_recorded_at: str | None = None
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            row_type = row.get("type")
            if row_type not in {"user", "assistant"}:
                continue
            message = row.get("message")
            if not isinstance(message, dict):
                continue
            text = _content_text(message.get("content"))
            if not text:
                continue
            uuid = str(row.get("uuid") or "")
            source_id = f"claude:{row_type}:{uuid or row.get('timestamp') or inserted}"
            if conn.execute("select 1 from events where session_id = ? and source_id = ?", (session_id, source_id)).fetchone():
                continue
            timestamp = row.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")
            cwd = str(row.get("cwd") or "")
            with conn:
                seq = _next_seq(conn, session_id)
                conn.execute(
                    """
                    insert into events (
                      session_id, seq, event_name, recorded_at, client_type, cwd,
                      project_id, turn_id, tool_name, tool_use_id, prompt,
                      tool_input_json, tool_response_text, last_assistant_message,
                      transcript_path, source_id, payload_json
                    ) values (?, ?, ?, ?, 'claude', ?, null, ?, null, null, ?, null, null, ?, ?, ?, ?)
                    """,
                    (
                        session_id,
                        seq,
                        "TranscriptUser" if row_type == "user" else "TranscriptAssistant",
                        timestamp,
                        cwd,
                        uuid or None,
                        text if row_type == "user" else None,
                        text if row_type == "assistant" else None,
                        str(path),
                        source_id,
                        json_dumps(row),
                    ),
                )
                conn.execute(
                    """
                    update sessions
                    set last_event_seq = case when last_event_seq < ? then ? else last_event_seq end,
                        last_reserved_event_seq = case
                          when last_reserved_event_seq < ? then ?
                          else last_reserved_event_seq
                        end,
                        last_event_at = case
                          when last_event_at is null or last_event_at < ? then ?
                          else last_event_at
                        end,
                        transcript_path = coalesce(transcript_path, ?),
                        summary_status = 'summary_pending',
                        dream_status = 'dream_pending'
                    where session_id = ?
                    """,
                    (seq, seq, seq, seq, timestamp, timestamp, str(path), session_id),
                )
            max_recorded_at = timestamp if max_recorded_at is None or timestamp > max_recorded_at else max_recorded_at
            inserted += 1
    return inserted


def sync_transcript_metrics_claude(conn: sqlite3.Connection, session_id: str, transcript_path: str) -> None:
    """Parse Claude JSONL and upsert one token_usage row per assistant turn."""
    path = Path(transcript_path)
    if not path.exists():
        return
    turn_counter = 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("type") != "assistant":
                continue
            message = row.get("message")
            if not isinstance(message, dict):
                continue
            usage = message.get("usage")
            if not isinstance(usage, dict):
                continue
            turn_counter += 1
            # Use message uuid as synthetic turn_id; fall back to counter-based id.
            turn_id = str(row.get("uuid") or f"{session_id}-t{turn_counter}")
            timestamp = row.get("timestamp") or datetime.now(timezone.utc).isoformat(timespec="seconds")
            cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
            cache_read = int(usage.get("cache_read_input_tokens") or 0)
            input_tokens = int(usage.get("input_tokens") or 0)
            output_tokens = int(usage.get("output_tokens") or 0)
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
                        timestamp,
                        input_tokens,
                        cache_creation + cache_read,
                        output_tokens,
                        None,
                        input_tokens + output_tokens,
                        None,
                        json_dumps(usage),
                    ),
                )


def sync_transcript_claude(conn: sqlite3.Connection, session_id: str, transcript_path: str) -> int:
    inserted = sync_transcript_events_claude(conn, session_id, transcript_path)
    sync_transcript_metrics_claude(conn, session_id, transcript_path)
    return inserted
