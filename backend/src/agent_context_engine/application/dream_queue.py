from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..adapters.sqlite import dream_queue as dream_queue_repo
from ..adapters.sqlite import repositories
from ..infrastructure.locks import is_stale_lock, lock_path, release_lock
from ..ports.clock import Clock
from ..ports.repositories.sqlite import SQLiteConnectionProvider
from .dreaming.v2 import cmd_dream_v2


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        from ..infrastructure.config import utc_now

        return utc_now()


def _default_clock() -> Clock:
    return _DefaultClock()


def _json_dumps(value: Any) -> str:
    from ..infrastructure.config import json_dumps

    return json_dumps(value)


def _safe_slug(value: str) -> str:
    from ..infrastructure.config import safe_slug

    return safe_slug(value)


def _now() -> str:
    return _default_clock().utc_now()


class _DreamQueueDbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        from ..adapters.sqlite.request_db import connect as request_db_connect

        return request_db_connect(*args, **kwargs)


def _default_db_provider() -> SQLiteConnectionProvider:
    return _DreamQueueDbProvider()


def _connect(db_provider: SQLiteConnectionProvider | None = None, *, init: bool = False) -> sqlite3.Connection:
    provider = db_provider or _default_db_provider()
    return provider.connect(init=init)


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def latest_dream_attempt_at(conn: sqlite3.Connection, session_id: str) -> datetime | None:
    return _parse_time(dream_queue_repo.latest_dream_attempt_at(conn, session_id))


def recover_stale_dream_queue_jobs(conn: sqlite3.Connection) -> int:
    now = _now()
    recovered = dream_queue_repo.requeue_expired_dream_jobs(
        conn,
        now=now,
        last_error="lease expired before dream queue completion",
    )
    if recovered:
        print(f"recovered stale dream queue jobs: {recovered}", file=sys.stderr)
    return recovered


def dream_interval_seconds() -> int:
    try:
        return max(0, int(os.environ.get("AGENT_MEMORY_DREAM_INTERVAL_SECONDS", "900")))
    except ValueError:
        return 900


def stale_dream_run_seconds() -> int:
    try:
        return max(900, int(os.environ.get("AGENT_MEMORY_STALE_DREAM_RUN_SECONDS", "7200")))
    except ValueError:
        return 7200


def _lock_missing_or_stale(path: Path, *, kind: str, key: str) -> bool:
    if not path.exists():
        return True
    return is_stale_lock(path, kind, key)


def recover_stale_running_dreams(conn: sqlite3.Connection) -> int:
    now_text = _now()
    now_dt = _parse_time(now_text) or datetime.now(timezone.utc)
    stale_after_seconds = stale_dream_run_seconds()
    rows = list(
        conn.execute(
            """
            select dr.dream_run_id, dr.session_id, dr.started_at,
                   s.last_event_seq, s.last_dream_event_seq
            from dream_runs dr
            join sessions s on s.session_id = dr.session_id
            where dr.status = 'running'
            order by dr.started_at asc
            """
        )
    )
    stale_rows: list[tuple[str, str, str, str]] = []
    for row in rows:
        session_id = str(row["session_id"])
        started_at = _parse_time(row["started_at"])
        age_seconds = (now_dt - started_at).total_seconds() if started_at is not None else float("inf")
        session_lock = lock_path("dream-session", session_id)
        if not _lock_missing_or_stale(session_lock, kind="dream-session", key=session_id):
            continue
        if age_seconds < stale_after_seconds:
            continue
        if session_lock.exists():
            release_lock(session_lock)
        reason = (
            "Recovered stale running dream without an active session lock. "
            f"started_at={row['started_at']} age_seconds={int(age_seconds)}"
        )
        dream_status = "dream_pending" if int(row["last_event_seq"] or 0) > int(row["last_dream_event_seq"] or 0) else "dreamed"
        stale_rows.append((str(row["dream_run_id"]), session_id, reason, dream_status))
    if stale_rows:
        with conn:
            for dream_run_id, session_id, reason, dream_status in stale_rows:
                conn.execute(
                    """
                    update dream_runs
                    set finished_at = ?,
                        status = 'failed',
                        pipeline_status = 'failed',
                        failed_stage = (
                          select stage_name
                          from dream_stage_runs
                          where dream_run_id = ?
                            and status = 'running'
                          order by stage_order desc
                          limit 1
                        ),
                        error_message = ?
                    where dream_run_id = ?
                      and status = 'running'
                    """,
                    (now_text, dream_run_id, reason, dream_run_id),
                )
                conn.execute(
                    """
                    update dream_stage_runs
                    set status = 'failed',
                        finished_at = ?,
                        error_message = ?
                    where dream_run_id = ?
                      and status = 'running'
                    """,
                    (now_text, reason, dream_run_id),
                )
                conn.execute(
                    """
                    update sessions
                    set dream_status = ?,
                        dream_runner_status = ?
                    where session_id = ?
                    """,
                    (dream_status, "stale_recovered", session_id),
                )
    recovered = len(stale_rows)
    if recovered:
        print(f"recovered stale running dreams: {recovered}", file=sys.stderr)
    return recovered


def stop_dream_due(conn: sqlite3.Connection, session_id: str, *, now: datetime | None = None) -> bool:
    latest = latest_dream_attempt_at(conn, session_id)
    if latest is None:
        return True
    now = now or datetime.now(timezone.utc)
    return (now - latest).total_seconds() >= dream_interval_seconds()


def enqueue_dream_job(
    conn: sqlite3.Connection,
    session_id: str,
    *,
    reason: str,
    runner: str,
    runner_model: str | None,
    runner_timeout: int,
    created_by: str,
    priority: int = 100,
) -> str:
    now = _now()
    recover_stale_running_dreams(conn)
    recover_stale_dream_queue_jobs(conn)
    existing = dream_queue_repo.find_active_dream_queue_id(conn, session_id)
    if existing is not None:
        dream_queue_repo.update_existing_dream_job(
            conn,
            existing,
            reason=reason,
            runner=runner,
            runner_model=runner_model,
            runner_timeout=runner_timeout,
            priority=priority,
            updated_at=now,
        )
        return existing

    queue_id = f"dreamq_{now.replace(':', '-').replace('+', 'Z')}_{_safe_slug(session_id)}_{os.getpid()}"
    dream_queue_repo.insert_dream_job(
        conn,
        dream_queue_id=queue_id,
        session_id=session_id,
        reason=reason,
        runner=runner,
        runner_model=runner_model,
        runner_timeout=runner_timeout,
        priority=priority,
        created_at=now,
        created_by=created_by,
        pipeline_version=int(os.environ.get("AGENT_MEMORY_PIPELINE_VERSION", "2") or "2"),
    )
    return queue_id


def enqueue_pending_dream_jobs(
    conn: sqlite3.Connection,
    *,
    runner: str,
    runner_model: str | None,
    runner_timeout: int,
    created_by: str,
    limit: int | None = None,
) -> int:
    recover_stale_running_dreams(conn)
    recover_stale_dream_queue_jobs(conn)
    sessions = repositories.dreamable_sessions(conn, True)
    if limit is not None:
        sessions = sessions[: max(0, int(limit))]
    count = 0
    for session in sessions:
        if not stop_dream_due(conn, session["session_id"]):
            continue
        enqueue_dream_job(
            conn,
            session["session_id"],
            reason="pending_sweep",
            runner=runner,
            runner_model=runner_model,
            runner_timeout=runner_timeout,
            created_by=created_by,
            priority=200,
        )
        count += 1
    return count


def _next_queued_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return dream_queue_repo.next_queued_dream_job(conn)


def _claim_next_queued_job(conn: sqlite3.Connection, *, lease_seconds: int = 1800) -> sqlite3.Row | None:
    job = _next_queued_job(conn)
    if job is None:
        return None
    now = _now()
    lease_until = (datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
    locked_by = f"pid:{os.getpid()}"
    claimed = dream_queue_repo.mark_dream_job_running(
        conn,
        job["dream_queue_id"],
        started_at=now,
        worker_pid=os.getpid(),
        locked_by=locked_by,
        lease_until=lease_until,
    )
    if not claimed:
        return None
    return dream_queue_repo.get_dream_queue_job(conn, job["dream_queue_id"])


def process_dream_queue(args: argparse.Namespace) -> int:
    limit = max(0, int(getattr(args, "dream_queue_limit", 5)))
    processed = 0
    exit_code = 0
    conn = _connect(init=False)
    try:
        recover_stale_running_dreams(conn)
        recover_stale_dream_queue_jobs(conn)
    finally:
        conn.close()
    while processed < limit:
        conn = _connect(init=False)
        job = _claim_next_queued_job(conn, lease_seconds=int(getattr(args, "runner_timeout", 1800)))
        if job is None:
            conn.close()
            break
        conn.close()

        runner = str(job["runner"] or "")
        requested_runner = str(getattr(args, "runner", "") or "")
        if runner == "same-as-session" and requested_runner and requested_runner != "same-as-session":
            runner = requested_runner
        dream_args = argparse.Namespace(
            pending=False,
            session=job["session_id"],
            runner=runner,
            runner_model=getattr(args, "runner_model", None) or job["runner_model"],
            runner_timeout=int(job["runner_timeout"]),
            pipeline_version=2,
            graph_runner=getattr(args, "graph_runner", None),
            fix_windows=True,
            window_grace_minutes=getattr(args, "grace_minutes", 5),
            repair_missing_graph_patches_limit=getattr(args, "repair_missing_graph_patches_limit", 0),
            created_by=job["created_by"] or "dream_queue",
            sync_neo4j=False,
            uri=getattr(args, "uri", None),
            database=getattr(args, "database", None),
            user=getattr(args, "user", None),
            password_env=getattr(args, "password_env", None),
        )
        result = cmd_dream_v2(dream_args)

        conn = _connect(init=False)
        finished = _now()
        session = repositories.fetch_session(conn, job["session_id"])
        succeeded = (
            result == 0
            and session is not None
            and (
                str(session["dream_runner_status"] or "") == "succeeded"
                or int(session["last_event_seq"]) <= int(session["last_dream_event_seq"])
            )
        )
        status = "succeeded" if succeeded else "failed"
        error = None if succeeded else f"dream command exited {result}"
        dream_queue_repo.mark_dream_job_finished(
            conn,
            job["dream_queue_id"],
            status=status,
            finished_at=finished,
            last_error=error,
        )
        conn.close()
        if result:
            exit_code = result
        processed += 1
    print(f"processed dream queue: {processed}")
    return exit_code


def queue_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    status = str(row["status"] or "")
    attempts = int(row["attempts"] or 0)
    max_attempts = int(row["max_attempts"] or 0)
    terminal = status == "failed" and max_attempts > 0 and attempts >= max_attempts
    return {
        "dream_queue_id": row["dream_queue_id"],
        "session_id": row["session_id"],
        "status": status,
        "terminal": terminal,
        "reason": row["reason"],
        "runner": row["runner"],
        "runner_model": row["runner_model"],
        "runner_timeout": int(row["runner_timeout"] or 0),
        "priority": int(row["priority"] or 0),
        "attempts": attempts,
        "max_attempts": max_attempts,
        "pipeline_version": int(row["pipeline_version"] or 2),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "lease_until": row["lease_until"],
        "locked_by": row["locked_by"],
        "worker_pid": row["worker_pid"],
        "retry_of_dream_run_id": row["retry_of_dream_run_id"],
        "created_by": row["created_by"],
        "last_error": row["last_error"],
    }


def dream_queue_status(conn: sqlite3.Connection, *, status: str, session_id: str | None, limit: int) -> dict[str, Any]:
    rows = dream_queue_repo.dream_queue_rows(conn, status=status, session_id=session_id, limit=limit)
    counts = dream_queue_repo.dream_queue_counts(conn)
    return {"counts": counts, "jobs": [queue_row_to_dict(row) for row in rows]}


def cmd_dream_queue_status(args: argparse.Namespace) -> int:
    conn = _connect(init=False)
    try:
        payload = dream_queue_status(
            conn,
            status=args.status,
            session_id=args.session,
            limit=args.limit,
        )
    finally:
        conn.close()
    if args.json:
        print(_json_dumps(payload))
        return 0
    counts = payload["counts"]
    print(
        "dream queue: "
        f"queued={counts.get('queued', 0)} "
        f"running={counts.get('running', 0)} "
        f"failed={counts.get('failed', 0)} "
        f"terminal_failed={counts.get('terminal_failed', 0)} "
        f"succeeded={counts.get('succeeded', 0)}"
    )
    jobs = payload["jobs"]
    if not jobs:
        print("No matching dream queue jobs.")
        return 0
    for job in jobs:
        terminal = " terminal" if job["terminal"] else ""
        model = job["runner_model"] or "-"
        print(
            f"{job['updated_at']} {job['dream_queue_id']} status={job['status']}{terminal} "
            f"session={job['session_id']} pipeline=v{job['pipeline_version']} "
            f"runner={job['runner']} model={model} attempts={job['attempts']}/{job['max_attempts']}"
        )
        print(
            f"  reason={job['reason']} priority={job['priority']} "
            f"created_by={job['created_by'] or '-'} lease_until={job['lease_until'] or '-'} locked_by={job['locked_by'] or '-'}"
        )
        if job["last_error"]:
            print(f"  error={job['last_error']}")
    return 0


def queue_dream_without_process(
    session_id: str,
    *,
    reason: str,
    runner: str,
    runner_timeout: int,
    created_by: str,
    runner_model: str | None = None,
    priority: int = 100,
) -> str:
    conn = _connect()
    try:
        return enqueue_dream_job(
            conn,
            session_id,
            reason=reason,
            runner=runner,
            runner_model=runner_model,
            runner_timeout=runner_timeout,
            created_by=created_by,
            priority=priority,
        )
    finally:
        conn.close()
