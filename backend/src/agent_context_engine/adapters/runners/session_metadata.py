from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ...application.instance_profile import resolve_runner_wrapper_name
from ...infrastructure.config import ROOT, sh_quote

PROMPT_EVENT_NAMES = ("UserPromptSubmit", "userPromptSubmit", "beforeSubmitPrompt")
GEMINI_HOME_ENV = "AGENT_MEMORY_GEMINI_HOME"
OPENCODE_HOME_ENV = "AGENT_MEMORY_OPENCODE_HOME"


@dataclass
class NativeSessionMetadata:
    thread_name: str | None = None
    transcript_path: str | None = None
    native_resume_command: str | None = None
    session_brief: str | None = None
    latest_user_prompt: str | None = None
    latest_assistant_message: str | None = None
    user_prompts: list[str] | None = None


def _compact_text(value: str | None, limit: int = 220) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _first_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _first_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value"):
            text = _first_text(value.get(key))
            if text:
                return text
    return ""


def _tag_body(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _gemini_home() -> Path:
    override = os.environ.get(GEMINI_HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".gemini").resolve()


def _opencode_home() -> Path:
    override = os.environ.get(OPENCODE_HOME_ENV)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "opencode").resolve()


def _antigravity_roots() -> list[Path]:
    base = _gemini_home()
    return [base / "antigravity-cli", base / "antigravity"]


def antigravity_transcript_path(session_id: str) -> Path | None:
    for base in _antigravity_roots():
        candidate = base / "brain" / session_id / ".system_generated" / "logs" / "transcript.jsonl"
        if candidate.exists():
            return candidate
    return None


def antigravity_annotation_title(session_id: str) -> str | None:
    for base in _antigravity_roots():
        path = base / "annotations" / f"{session_id}.pbtxt"
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        match = re.search(r'title:"((?:[^"\\]|\\.)*)"', text)
        if match:
            try:
                return bytes(match.group(1), "utf-8").decode("unicode_escape")
            except UnicodeDecodeError:
                return match.group(1)
    return None


def gemini_transcript_path(session_id: str) -> Path | None:
    prefix = session_id[:8]
    candidates = sorted(
        _gemini_home().glob(f"tmp/**/chats/session-*-{prefix}.jsonl"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        try:
            first_line = candidate.read_text(encoding="utf-8", errors="replace").splitlines()[0]
        except (OSError, IndexError):
            continue
        try:
            header = json.loads(first_line)
        except json.JSONDecodeError:
            continue
        if str(header.get("sessionId") or "") == session_id:
            return candidate
    return None


def _parse_antigravity_transcript(path: Path) -> NativeSessionMetadata:
    prompts: list[str] = []
    assistants: list[str] = []
    if not path.exists():
        return NativeSessionMetadata(user_prompts=prompts)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row_type = str(row.get("type") or "")
                source = str(row.get("source") or "")
                content = str(row.get("content") or "")
                if row_type == "USER_INPUT" and source.startswith("USER"):
                    text = _tag_body(content, "USER_REQUEST")
                    compact = _compact_text(text, limit=500)
                    if compact:
                        prompts.append(compact)
                elif source == "MODEL":
                    compact = _compact_text(content, limit=1200)
                    if compact:
                        assistants.append(compact)
    except OSError:
        return NativeSessionMetadata(user_prompts=prompts)
    first_prompt = prompts[0] if prompts else None
    return NativeSessionMetadata(
        transcript_path=str(path),
        session_brief=_compact_text(first_prompt),
        latest_user_prompt=prompts[-1] if prompts else None,
        latest_assistant_message=assistants[-1] if assistants else None,
        user_prompts=prompts,
    )


def _rough_token_estimate(text: str) -> int:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if not compact:
        return 0
    return max(1, (len(compact) + 3) // 4)


def _iso_from_epoch_millis(value: object) -> str | None:
    try:
        millis = int(value or 0)
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_opencode_token_rows(session_id: str) -> list[dict[str, Any]]:
    message_dir = _opencode_home() / "storage" / "message" / session_id
    if not message_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(message_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(payload.get("role") or "") != "assistant":
            continue
        tokens = payload.get("tokens")
        if not isinstance(tokens, dict):
            continue
        input_tokens = int(tokens.get("input") or 0)
        output_tokens = int(tokens.get("output") or 0)
        reasoning_tokens = int(tokens.get("reasoning") or 0)
        cache = tokens.get("cache") if isinstance(tokens.get("cache"), dict) else {}
        cached_input_tokens = int(cache.get("read") or 0)
        total_tokens = input_tokens + output_tokens + reasoning_tokens
        if total_tokens <= 0:
            continue
        recorded_at = (
            _iso_from_epoch_millis((payload.get("time") or {}).get("completed"))
            or _iso_from_epoch_millis((payload.get("time") or {}).get("created"))
        )
        if not recorded_at:
            continue
        rows.append(
            {
                "turn_id": str(payload.get("id") or path.stem),
                "recorded_at": recorded_at,
                "input_tokens": input_tokens,
                "cached_input_tokens": cached_input_tokens,
                "output_tokens": output_tokens,
                "reasoning_output_tokens": reasoning_tokens,
                "total_tokens": total_tokens,
                "raw_json": json.dumps(
                    {
                        "usage_source": "opencode_message_store",
                        "provider_id": payload.get("providerID"),
                        "model_id": payload.get("modelID"),
                        "tokens": tokens,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
    return rows


def _sync_opencode_token_usage(conn: sqlite3.Connection, session_id: str) -> None:
    for row in _parse_opencode_token_rows(session_id):
        conn.execute(
            """
            insert or ignore into token_usage (
              session_id, turn_id, recorded_at, input_tokens,
              cached_input_tokens, output_tokens, reasoning_output_tokens,
              total_tokens, raw_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                row["turn_id"],
                row["recorded_at"],
                row["input_tokens"],
                row["cached_input_tokens"],
                row["output_tokens"],
                row["reasoning_output_tokens"],
                row["total_tokens"],
                row["raw_json"],
            ),
        )


def _estimate_antigravity_token_usage(path: Path) -> dict[str, Any] | None:
    prompt_total = 0
    output_total = 0
    latest_timestamp = ""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                created_at = str(row.get("created_at") or "")
                if created_at:
                    latest_timestamp = created_at
                row_type = str(row.get("type") or "")
                source = str(row.get("source") or "")
                content = str(row.get("content") or "")
                if row_type == "USER_INPUT" and source.startswith("USER"):
                    prompt_total += _rough_token_estimate(_tag_body(content, "USER_REQUEST"))
                elif source == "MODEL" and content.strip():
                    output_total += _rough_token_estimate(content)
    except OSError:
        return None
    total_tokens = prompt_total + output_total
    if total_tokens <= 0:
        return None
    return {
        "turn_id": "antigravity-transcript-estimate",
        "recorded_at": latest_timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "input_tokens": prompt_total,
        "cached_input_tokens": 0,
        "output_tokens": output_total,
        "reasoning_output_tokens": 0,
        "total_tokens": total_tokens,
        "raw_json": json.dumps(
            {
                "usage_source": "antigravity_transcript_estimate",
                "transcript_path": str(path),
                "approximate": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
    }


def _sync_antigravity_token_usage(conn: sqlite3.Connection, session_id: str, transcript_path: str | None) -> None:
    if not transcript_path:
        return
    estimate = _estimate_antigravity_token_usage(Path(transcript_path))
    if not estimate:
        return
    conn.execute(
        "delete from token_usage where session_id = ? and turn_id = 'antigravity-transcript-estimate'",
        (session_id,),
    )
    conn.execute(
        """
        insert into token_usage (
          session_id, turn_id, recorded_at, input_tokens,
          cached_input_tokens, output_tokens, reasoning_output_tokens,
          total_tokens, raw_json
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            estimate["turn_id"],
            estimate["recorded_at"],
            estimate["input_tokens"],
            estimate["cached_input_tokens"],
            estimate["output_tokens"],
            estimate["reasoning_output_tokens"],
            estimate["total_tokens"],
            estimate["raw_json"],
        ),
    )


def _parse_gemini_transcript(path: Path) -> NativeSessionMetadata:
    prompts: list[str] = []
    assistants: list[str] = []
    if not path.exists():
        return NativeSessionMetadata(user_prompts=prompts)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row_type = str(row.get("type") or "")
                if row_type == "user":
                    text = _first_text(row.get("content"))
                    if not text or "<session_context>" in text:
                        continue
                    compact = _compact_text(text, limit=500)
                    if compact:
                        prompts.append(compact)
                elif row_type == "gemini":
                    compact = _compact_text(str(row.get("content") or ""), limit=1200)
                    if compact:
                        assistants.append(compact)
    except OSError:
        return NativeSessionMetadata(user_prompts=prompts)
    first_prompt = prompts[0] if prompts else None
    return NativeSessionMetadata(
        transcript_path=str(path),
        session_brief=_compact_text(first_prompt),
        latest_user_prompt=prompts[-1] if prompts else None,
        latest_assistant_message=assistants[-1] if assistants else None,
        user_prompts=prompts,
    )


def native_resume_command(client: str, session_id: str, workdir: str | None, *, root: Path = ROOT) -> str | None:
    resolved_workdir = workdir or str(ROOT)
    if client == "codex":
        return f"{resolve_runner_wrapper_name('codex', root=root)} resume {session_id}"
    if client == "claude":
        return f"{resolve_runner_wrapper_name('claude', root=root)} --resume {session_id}"
    if client == "cursor":
        return f"cd {sh_quote(resolved_workdir)} && cursor-agent --resume {sh_quote(session_id)}"
    if client == "antigravity":
        return f"cd {sh_quote(resolved_workdir)} && agy --conversation {sh_quote(session_id)}"
    if client == "opencode":
        return f"cd {sh_quote(resolved_workdir)} && opencode --session {sh_quote(session_id)}"
    return None


def _payload_thread_name(payload: Mapping[str, Any], client: str) -> str | None:
    if client in {"cursor", "opencode"}:
        return _compact_text(str(payload.get("thread_name") or payload.get("conversation_title") or payload.get("title") or ""))
    if client == "antigravity":
        return _compact_text(
            str(payload.get("thread_name") or payload.get("conversation_title") or payload.get("title") or payload.get("session_title") or "")
        )
    return _compact_text(str(payload.get("thread_name") or payload.get("conversation_title") or payload.get("title") or ""))


def resolve_native_session_metadata(
    client: str,
    session_id: str,
    *,
    cwd: str | None,
    workdir: str | None,
    payload: Mapping[str, Any] | None = None,
) -> NativeSessionMetadata:
    payload = payload or {}
    metadata = NativeSessionMetadata(
        thread_name=_payload_thread_name(payload, client),
        transcript_path=_compact_text(str(payload.get("transcript_path") or ""), limit=2000),
        native_resume_command=native_resume_command(client, session_id, workdir or cwd, root=ROOT),
        latest_user_prompt=_compact_text(str(payload.get("prompt") or ""), limit=500),
        latest_assistant_message=_compact_text(str(payload.get("last_assistant_message") or ""), limit=1200),
        user_prompts=[],
    )
    if metadata.latest_user_prompt:
        metadata.session_brief = _compact_text(metadata.latest_user_prompt)
        metadata.user_prompts = [metadata.latest_user_prompt]
    transcript_path = Path(metadata.transcript_path) if metadata.transcript_path else None
    if client == "antigravity":
        metadata.thread_name = antigravity_annotation_title(session_id) or metadata.thread_name
        transcript_path = transcript_path or antigravity_transcript_path(session_id)
        if transcript_path:
            parsed = _parse_antigravity_transcript(transcript_path)
            metadata.transcript_path = parsed.transcript_path or metadata.transcript_path
            metadata.session_brief = metadata.session_brief or parsed.session_brief
            metadata.latest_user_prompt = metadata.latest_user_prompt or parsed.latest_user_prompt
            metadata.latest_assistant_message = metadata.latest_assistant_message or parsed.latest_assistant_message
            metadata.user_prompts = parsed.user_prompts or metadata.user_prompts
    elif client == "gemini":
        transcript_path = transcript_path or gemini_transcript_path(session_id)
        if transcript_path:
            parsed = _parse_gemini_transcript(transcript_path)
            metadata.transcript_path = parsed.transcript_path or metadata.transcript_path
            metadata.session_brief = metadata.session_brief or parsed.session_brief
            metadata.latest_user_prompt = metadata.latest_user_prompt or parsed.latest_user_prompt
            metadata.latest_assistant_message = metadata.latest_assistant_message or parsed.latest_assistant_message
            metadata.user_prompts = parsed.user_prompts or metadata.user_prompts
    return metadata


def _update_first_missing_prompts(conn: sqlite3.Connection, session_id: str, prompts: list[str]) -> None:
    if not prompts:
        return
    rows = conn.execute(
        f"""
        select seq
        from events
        where session_id = ?
          and event_name in ({",".join("?" for _ in PROMPT_EVENT_NAMES)})
          and coalesce(trim(prompt), '') = ''
        order by seq asc
        """,
        (session_id, *PROMPT_EVENT_NAMES),
    ).fetchall()
    for row, prompt in zip(rows, prompts):
        conn.execute(
            """
            update events
            set prompt = ?
            where session_id = ?
              and seq = ?
              and coalesce(trim(prompt), '') = ''
            """,
            (prompt, session_id, int(row["seq"])),
        )


def _update_latest_assistant_message(conn: sqlite3.Connection, session_id: str, message: str | None) -> None:
    if not message:
        return
    conn.execute(
        """
        update events
        set last_assistant_message = ?
        where session_id = ?
          and seq = (
            select seq
            from events
            where session_id = ?
              and event_name = 'Stop'
            order by seq desc
            limit 1
          )
          and coalesce(trim(last_assistant_message), '') = ''
        """,
        (message, session_id, session_id),
    )


def refresh_session_row_metadata(
    conn: sqlite3.Connection,
    row: sqlite3.Row | Mapping[str, Any],
    *,
    persist: bool = True,
) -> dict[str, Any]:
    row_map = dict(row)
    session_id = str(row["session_id"])
    client = str(row["client_type"])
    cwd = str(row_map.get("cwd") or "")
    workdir = str(row_map.get("last_workdir") or cwd)
    current_thread_name = _compact_text(str(row_map.get("thread_name") or ""))
    current_transcript = _compact_text(str(row_map.get("transcript_path") or ""), limit=2000)
    current_resume = _compact_text(str(row_map.get("native_resume_command") or ""), limit=2000)
    current_brief = _compact_text(str(row_map.get("session_brief") or ""))
    metadata = resolve_native_session_metadata(client, session_id, cwd=cwd, workdir=workdir, payload={})
    updates: dict[str, Any] = {}
    if metadata.thread_name and metadata.thread_name != current_thread_name:
        updates["thread_name"] = metadata.thread_name
    if metadata.transcript_path and metadata.transcript_path != current_transcript:
        updates["transcript_path"] = metadata.transcript_path
    if metadata.native_resume_command and metadata.native_resume_command != current_resume:
        updates["native_resume_command"] = metadata.native_resume_command
    if metadata.session_brief and not current_brief:
        updates["session_brief"] = metadata.session_brief
    if persist:
        with conn:
            if updates:
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(
                    f"update sessions set {assignments} where session_id = ?",
                    (*updates.values(), session_id),
                )
            _update_first_missing_prompts(conn, session_id, metadata.user_prompts or [])
            _update_latest_assistant_message(conn, session_id, metadata.latest_assistant_message)
            if client == "opencode":
                _sync_opencode_token_usage(conn, session_id)
            elif client == "antigravity":
                _sync_antigravity_token_usage(conn, session_id, metadata.transcript_path)
    return {
        "thread_name": updates.get("thread_name", current_thread_name),
        "transcript_path": updates.get("transcript_path", current_transcript),
        "native_resume_command": updates.get("native_resume_command", current_resume),
        "session_brief": updates.get("session_brief", current_brief),
        "latest_user_prompt": metadata.latest_user_prompt,
        "latest_assistant_message": metadata.latest_assistant_message,
    }
