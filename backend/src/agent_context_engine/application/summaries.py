from __future__ import annotations

import argparse
import atexit
import os
import sqlite3
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from ..adapters.sqlite import summaries as summaries_repo
from ..adapters.sqlite import repositories as repositories_repo
from ..infrastructure.locks import acquire_lock, release_lock
from ..infrastructure.render import render_handover, render_window_summary
from ..ports.clock import Clock
from ..ports.repositories.sqlite import SQLiteConnectionProvider
from .retrieval import index_memory_document


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        from ..infrastructure.config import utc_now

        return utc_now()


def _default_clock() -> Clock:
    return _DefaultClock()


def _now() -> str:
    return _default_clock().utc_now()


def _memory_dir() -> Path:
    from ..infrastructure.config import MEMORY_DIR

    return MEMORY_DIR


def _root() -> Path:
    from ..infrastructure.config import ROOT

    return ROOT


def _safe_slug(value: str) -> str:
    from ..infrastructure.config import safe_slug

    return safe_slug(str(value))


class _SummariesDbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        from ..adapters.sqlite.request_db import connect as request_db_connect

        return request_db_connect(*args, **kwargs)


def _default_db_provider() -> SQLiteConnectionProvider:
    return _SummariesDbProvider()


def _connect(init: bool = True, db_provider: SQLiteConnectionProvider | None = None) -> sqlite3.Connection:
    provider = db_provider or _default_db_provider()
    return provider.connect(init=init)


def summary_path(session: sqlite3.Row) -> Path:
    date_part = (session["last_event_at"] or _now())[:10]
    return _memory_dir() / "sessions" / date_part / f"{_safe_slug(session['client_type'])}-{_safe_slug(session['session_id'])[:12]}.md"


def summarize_one(conn: sqlite3.Connection, session: sqlite3.Row) -> Path:
    events = repositories_repo.session_events(conn, session["session_id"])
    path = summary_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_handover(session, events), encoding="utf-8")
    index_memory_document(conn, path, kind="summary", session_id=session["session_id"], project_id=session["project_id"], title=session["thread_name"])
    now = _now()
    summaries_repo.upsert_session_summary(
        conn,
        session_id=session["session_id"],
        summary_path=str(path.relative_to(_root())),
        created_at=now,
        input_event_seq_to=session["last_event_seq"],
        input_event_count=len(events),
    )
    return path


def cmd_summarize(
    args: argparse.Namespace,
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> int:
    conn = _connect(db_provider=db_provider)
    sessions = repositories_repo.summarizable_sessions(conn, args.pending)
    if args.session:
        selected = repositories_repo.resolve_session(conn, args.session)
        if selected is None:
            print(f"No session found for selector: {args.session}", file=sys.stderr)
            return 1
        sessions = [s for s in sessions if s["session_id"] == selected["session_id"]]
    if not sessions:
        print("No sessions to summarize.")
        return 0
    for session in sessions:
        path = summarize_one(conn, session)
        print(f"summarized {session['client_type']} {session['session_id']} -> {path.relative_to(_root())}")
    return 0


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def hour_floor(value: datetime) -> datetime:
    return value.replace(minute=0, second=0, microsecond=0)


def format_dt(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def running_window_overlap(conn: sqlite3.Connection, start: datetime, end: datetime) -> sqlite3.Row | None:
    return summaries_repo.running_window_overlap(conn, start=format_dt(start), end=format_dt(end))


def window_id_for_start(start: datetime) -> str:
    return f"hour_{start.strftime('%Y%m%dT%H0000Z')}"


def events_for_window(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[sqlite3.Row]:
    return summaries_repo.events_for_window(conn, start=format_dt(start), end=format_dt(end))


def summarize_window(conn: sqlite3.Connection, start: datetime, grace: timedelta, force: bool = False, reason: str = "scheduled") -> bool:
    end = start + timedelta(hours=1)
    grace_until = end + grace
    window_id = window_id_for_start(start)
    existing = summaries_repo.summary_window_status(conn, window_id=window_id)
    events = events_for_window(conn, start, end)
    if not events:
        return False
    if existing and existing["status"] == "summarized" and not force and int(existing["input_event_count"]) == len(events):
        return False
    overlap = running_window_overlap(conn, start, end)
    if overlap and overlap["window_id"] != window_id:
        print(f"skipped window {window_id}: overlapping window already running {overlap['window_id']} {overlap['window_start']}..{overlap['window_end']}")
        return False
    window_lock = acquire_lock("summary-window", window_id)
    if window_lock is None:
        print(f"skipped window {window_id}: already running")
        return False
    atexit.register(release_lock, window_lock)
    try:
        summaries_repo.mark_summary_window_running(
            conn,
            window_id=window_id,
            window_start=format_dt(start),
            window_end=format_dt(end),
            grace_until=format_dt(grace_until),
            created_at=_now(),
            input_event_count=len(events),
            notes=f"pid={os.getpid()} reason={reason}",
        )
        path = _memory_dir() / "sessions" / "windows" / f"{window_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_window_summary(window_id, start, end, grace_until, events), encoding="utf-8")
        index_memory_document(conn, path, kind="window_summary", title=window_id)
        summaries_repo.mark_summary_window_summarized(
            conn,
            window_id=window_id,
            window_start=format_dt(start),
            window_end=format_dt(end),
            grace_until=format_dt(grace_until),
            created_at=_now(),
            input_event_count=len(events),
            output_path=str(path.relative_to(_root())),
            notes=f"reason={reason}",
        )
        print(f"summarized window {window_id} events={len(events)} reason={reason} -> {path.relative_to(_root())}")
        return True
    except Exception:
        summaries_repo.mark_summary_window_failed(conn, window_id=window_id, notes=f"failed_at={_now()} reason={reason}")
        raise
    finally:
        release_lock(window_lock)


def repair_summary_windows(conn: sqlite3.Connection, grace: timedelta) -> int:
    bounds = summaries_repo.summary_window_bounds(conn)
    if not bounds["first_start"] or not bounds["last_end"]:
        return 0
    start = hour_floor(parse_iso(bounds["first_start"]))
    end_limit = hour_floor(parse_iso(bounds["last_end"]) - timedelta(seconds=1))
    repaired = 0
    while start <= end_limit:
        end = start + timedelta(hours=1)
        window_id = window_id_for_start(start)
        current_count = len(events_for_window(conn, start, end))
        row = summaries_repo.summary_window_status(conn, window_id=window_id)
        if current_count:
            missing = row is None
            changed = row is not None and row["status"] == "summarized" and int(row["input_event_count"]) != current_count
            failed = row is not None and row["status"] == "failed"
            if missing or changed or failed:
                repaired += 1 if summarize_window(conn, start, grace, force=True, reason="gap-fixer") else 0
        start = end
    return repaired


def cmd_summarize_windows(
    args: argparse.Namespace,
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> int:
    conn = _connect(db_provider=db_provider)
    now = datetime.now(timezone.utc)
    grace = timedelta(minutes=args.grace_minutes)
    repaired = repair_summary_windows(conn, grace) if args.fix_gaps else 0
    cutoff = now - grace
    earliest = summaries_repo.earliest_event_at_before(conn, cutoff=format_dt(cutoff))
    if not earliest:
        print("No events eligible for window summaries.")
        return 0
    start = hour_floor(parse_iso(earliest))
    end_limit = hour_floor(cutoff)
    created = 0
    while start <= end_limit:
        if summarize_window(conn, start, grace, force=args.force, reason="scheduled"):
            created += 1
        start = start + timedelta(hours=1)
    if created == 0 and repaired == 0:
        print("No new windows to summarize.")
    return 0
