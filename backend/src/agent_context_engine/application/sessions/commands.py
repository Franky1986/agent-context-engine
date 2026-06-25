from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..instance_profile import resolve_runner_wrapper_name
from ...infrastructure.config import ROOT, detect_project, json_dumps, session_short
from ...infrastructure.db import connect
from ...adapters.runners.claude import claude_session_title, sync_transcript_claude
from ...adapters.runners.codex import codex_thread_name, discover_codex_transcripts_for_folder, iter_codex_transcript_messages, sync_transcript_metrics
from ...adapters.runners.session_metadata import refresh_session_row_metadata


def _quote_platform_value(value: str | Path) -> str:
    from ..platform import current_platform_profile
    from ..platform.runtime_selection import select_path_quoting_adapter

    return select_path_quoting_adapter(current_platform_profile()).quote(str(value))


def resume_command(session: sqlite3.Row) -> str:
    if session["client_type"] == "codex":
        wrapper_name = resolve_runner_wrapper_name("codex", root=ROOT)
        return f"{wrapper_name} resume {_quote_platform_value(session['session_id'])}"
    return session["native_resume_command"] or f"# unsupported client: {session['client_type']} {session['session_id']}"


def normalize_path_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return str(Path(value).expanduser())


def local_time(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _one_line(text: str | None, limit: int = 100) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 1)].rstrip() + "…"


def session_folder_where(alias: str = "s") -> str:
    return f"""
    (
      coalesce({alias}.last_workdir, '') = ?
      or coalesce({alias}.cwd, '') = ?
      or coalesce({alias}.last_workdir, '') like ?
      or coalesce({alias}.cwd, '') like ?
      or (coalesce({alias}.last_workdir, '') != '' and ? like coalesce({alias}.last_workdir, '') || '/%')
      or (coalesce({alias}.cwd, '') != '' and ? like coalesce({alias}.cwd, '') || '/%')
    )
    """


def session_folder_params(folder: str) -> list[str]:
    folder = normalize_path_text(folder)
    return [folder, folder, f"{folder}/%", f"{folder}/%", folder, folder]


def session_mini_summary(conn: sqlite3.Connection, row: sqlite3.Row) -> str:
    if row["session_brief"]:
        return _one_line(row["session_brief"])
    if row["thread_name"]:
        return _one_line(row["thread_name"])
    first_prompt = conn.execute(
        """
        select prompt
        from events
        where session_id = ?
          and coalesce(prompt, '') != ''
        order by seq asc
        limit 1
        """,
        (row["session_id"],),
    ).fetchone()
    if first_prompt and first_prompt["prompt"]:
        return _one_line(first_prompt["prompt"])
    latest_assistant = conn.execute(
        """
        select last_assistant_message
        from events
        where session_id = ?
          and coalesce(last_assistant_message, '') != ''
        order by seq desc
        limit 1
        """,
        (row["session_id"],),
    ).fetchone()
    if latest_assistant and latest_assistant["last_assistant_message"]:
        return _one_line(latest_assistant["last_assistant_message"])
    return ""


def print_session_row(conn: sqlite3.Connection, row: sqlite3.Row) -> None:
    title = f" title={row['thread_name']}" if row["thread_name"] else ""
    print(f"{local_time(row['last_event_at'])} {row['client_type']} {row['project_id']} {session_short(row['session_id'])}{title}")
    print(f"  session: {row['session_id']}")
    print(f"  workdir: {row['last_workdir'] or row['cwd'] or '-'}")
    summary_hint = session_mini_summary(conn, row)
    if summary_hint:
        print(f"  hint: {summary_hint}")
    print(f"  resume: {resume_command(row)}")
    if "summary_path" in row.keys():
        print(f"  summary: {row['summary_path'] or '-'}")
    print(f"  transcript: {row['transcript_path'] or '-'}")


def cmd_sync_transcripts(args: argparse.Namespace) -> int:
    conn = connect()
    rows = list(conn.execute("select session_id, client_type, transcript_path from sessions where transcript_path is not null"))
    count = 0
    imported = 0
    for row in rows:
        if args.session and not row["session_id"].startswith(args.session):
            continue
        if row["client_type"] == "codex":
            thread_name = codex_thread_name(row["session_id"])
            if thread_name:
                with conn:
                    conn.execute("update sessions set thread_name = ? where session_id = ?", (thread_name, row["session_id"]))
            sync_transcript_metrics(conn, row["session_id"], row["transcript_path"])
        elif row["client_type"] == "claude":
            thread_name = claude_session_title(row["session_id"])
            if thread_name:
                with conn:
                    conn.execute("update sessions set thread_name = ? where session_id = ?", (thread_name, row["session_id"]))
            imported += sync_transcript_claude(conn, row["session_id"], row["transcript_path"])
        refresh_session_row_metadata(conn, row)
        count += 1
    print(f"synced transcripts: {count} imported_events={imported}")
    return 0


def cmd_last(args: argparse.Namespace) -> int:
    conn = connect()
    where = []
    params: list[Any] = []
    if getattr(args, "folder", None):
        where.append(session_folder_where("s"))
        params.extend(session_folder_params(args.folder))
    if args.query:
        like = f"%{args.query}%"
        where.append(
            """
            (
              s.session_id like ?
              or coalesce(s.thread_name, '') like ?
              or coalesce(s.project_id, '') like ?
              or coalesce(s.cwd, '') like ?
              or exists (
                select 1 from events e
                where e.session_id = s.session_id
                  and (
                    coalesce(e.prompt, '') like ?
                    or coalesce(e.last_assistant_message, '') like ?
                    or coalesce(e.tool_response_text, '') like ?
                  )
              )
            )
            """
        )
        params.extend([like, like, like, like, like, like, like])
    where_sql = " where " + " and ".join(where) if where else ""
    rows = list(
        conn.execute(
            f"""
            select s.*, m.summary_path
            from sessions s
            left join summaries m on m.session_id = s.session_id
            {where_sql}
            order by coalesce(s.last_event_at, s.started_at) desc
            limit ?
            """,
            (*params, args.limit),
        )
    )
    for row in rows:
        refresh_session_row_metadata(conn, row)
        print_session_row(conn, row)
    return 0


def cmd_folder(args: argparse.Namespace) -> int:
    conn = connect()
    folder = normalize_path_text(args.folder or os.environ.get("PWD") or ".")
    params = session_folder_params(folder)
    rows = list(
        conn.execute(
            f"""
            select s.*, m.summary_path
            from sessions s
            left join summaries m on m.session_id = s.session_id
            where {session_folder_where("s")}
            order by coalesce(s.last_event_at, s.started_at) desc
            limit ?
            """,
            (*params, args.limit),
        )
    )
    print(f"Folder: {folder}")
    print("")
    print("Indexed agent-memory sessions:")
    if rows:
        for row in rows:
            refresh_session_row_metadata(conn, row)
            print_session_row(conn, row)
    else:
        print("- None")
    if args.include_transcripts:
        known = {row["session_id"] for row in rows}
        missing = discover_codex_transcripts_for_folder(folder, known, args.transcript_limit)
        print("")
        print("Unindexed Codex transcripts in this folder:")
        if missing:
            for item in missing:
                print(f"{local_time(item['last_at'] or item['started_at'])} codex unindexed {session_short(item['session_id'])}")
                print(f"  session: {item['session_id']}")
                print(f"  workdir: {item['cwd'] or '-'}")
                print(f"  transcript: {item['path']}")
                print(f"  hint: {item['hint'] or '-'}")
                print(f"  import: agent-memory sync-codex-transcript {item['path']}")
        else:
            print("- None")
    return 0


def cmd_sync_codex_transcript(args: argparse.Namespace) -> int:
    conn = connect()
    path = Path(args.path).expanduser().resolve()
    info, messages = iter_codex_transcript_messages(path)
    session_id = str(args.session_id or info.get("session_id") or "")
    if not session_id:
        print(f"Cannot derive Codex session id from transcript path: {path}", file=sys.stderr)
        return 1
    cwd = normalize_path_text(args.cwd or info.get("cwd") or ROOT)
    project_id = detect_project(cwd)
    started_at = str(info.get("started_at") or "")
    last_at = str(info.get("last_at") or started_at)
    existing = conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
    with conn:
        if existing is None:
            conn.execute(
                """
                insert into sessions (
                  session_id, client_type, project_id, cwd, last_workdir,
                  transcript_path, started_at, last_event_at, ended_at, status,
                  summary_status, dream_status, last_event_seq,
                  preferred_dream_runner, native_resume_command
                ) values (?, 'codex', ?, ?, ?, ?, ?, ?, ?, 'stopped',
                          'summary_pending', 'dream_pending', 0, 'codex', ?)
                """,
                (session_id, project_id, cwd, cwd, str(path), started_at, last_at, last_at, f"codex resume {session_id}"),
            )
        else:
            conn.execute(
                """
                update sessions
                set project_id = coalesce(project_id, ?),
                    cwd = coalesce(cwd, ?),
                    last_workdir = coalesce(last_workdir, ?),
                    transcript_path = ?,
                    last_event_at = coalesce(?, last_event_at),
                    ended_at = coalesce(?, ended_at),
                    status = 'stopped',
                    summary_status = 'summary_pending',
                    dream_status = 'dream_pending'
                where session_id = ?
                """,
                (project_id, cwd, cwd, str(path), last_at, last_at, session_id),
            )
        seq_row = conn.execute("select coalesce(max(seq), 0) as seq from events where session_id = ?", (session_id,)).fetchone()
        seq = int(seq_row["seq"] or 0)
        imported = 0
        for message in messages:
            source_id = f"codex-transcript:{path}:{message['line_no']}"
            exists = conn.execute("select 1 from events where session_id = ? and source_id = ?", (session_id, source_id)).fetchone()
            if exists:
                continue
            seq += 1
            role = message["role"]
            conn.execute(
                """
                insert into events (
                  session_id, seq, event_name, recorded_at, client_type, cwd,
                  project_id, prompt, last_assistant_message, transcript_path,
                  source_id, payload_json
                ) values (?, ?, ?, ?, 'codex', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    seq,
                    "TranscriptUser" if role == "user" else "TranscriptAssistant",
                    message["timestamp"] or last_at or started_at,
                    cwd,
                    project_id,
                    message["text"] if role == "user" else None,
                    message["text"] if role == "assistant" else None,
                    str(path),
                    source_id,
                    json_dumps(message["raw"]),
                ),
            )
            imported += 1
        conn.execute(
            """
            update sessions
            set last_event_seq = (select coalesce(max(seq), 0) from events where session_id = ?),
                last_event_at = coalesce(?, last_event_at),
                summary_status = 'summary_pending',
                dream_status = 'dream_pending'
            where session_id = ?
            """,
            (session_id, last_at, session_id),
        )
    sync_transcript_metrics(conn, session_id, str(path))
    print(f"synced codex transcript: session={session_id} imported_events={imported} path={path}")
    return 0


__all__ = [
    "cmd_folder",
    "cmd_last",
    "cmd_sync_codex_transcript",
    "cmd_sync_transcripts",
    "print_session_row",
]
