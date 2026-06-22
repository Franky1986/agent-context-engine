from __future__ import annotations

import sqlite3
from typing import Any


def latest_dream_attempt_at(conn: sqlite3.Connection, session_id: str) -> str | None:
    row = conn.execute(
        """
        select coalesce(finished_at, started_at) as attempted_at
        from dream_runs
        where session_id = ?
        order by started_at desc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    return row["attempted_at"] if row else None


def find_active_dream_queue_id(conn: sqlite3.Connection, session_id: str) -> str | None:
    row = conn.execute(
        """
        select dream_queue_id
        from dream_queue
        where session_id = ?
          and status in ('queued', 'running')
        order by priority asc, created_at asc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    return str(row["dream_queue_id"]) if row is not None else None


def update_existing_dream_job(
    conn: sqlite3.Connection,
    dream_queue_id: str,
    *,
    reason: str,
    runner: str,
    runner_model: str | None,
    runner_timeout: int,
    priority: int,
    updated_at: str,
) -> None:
    with conn:
        conn.execute(
            """
            update dream_queue
            set reason = ?,
                runner = ?,
                runner_model = coalesce(?, runner_model),
                runner_timeout = ?,
                priority = min(priority, ?),
                updated_at = ?
            where dream_queue_id = ?
            """,
            (reason, runner, runner_model, int(runner_timeout), int(priority), updated_at, dream_queue_id),
        )


def insert_dream_job(
    conn: sqlite3.Connection,
    *,
    dream_queue_id: str,
    session_id: str,
    reason: str,
    runner: str,
    runner_model: str | None,
    runner_timeout: int,
    priority: int,
    created_at: str,
    created_by: str,
    pipeline_version: int,
) -> None:
    with conn:
        conn.execute(
            """
            insert into dream_queue (
              dream_queue_id, session_id, reason, runner, runner_model,
              runner_timeout, status, priority, attempts, max_attempts,
              created_at, updated_at, created_by, pipeline_version
            ) values (?, ?, ?, ?, ?, ?, 'queued', ?, 0, 1, ?, ?, ?, ?)
            """,
            (
                dream_queue_id,
                session_id,
                reason,
                runner,
                runner_model,
                int(runner_timeout),
                int(priority),
                created_at,
                created_at,
                created_by,
                int(pipeline_version),
            ),
        )


def next_queued_dream_job(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        """
        select dq.*
        from dream_queue dq
        left join sessions s on s.session_id = dq.session_id
        where dq.status = 'queued'
        order by dq.priority asc,
                 coalesce(s.last_event_at, s.started_at, dq.created_at) desc,
                 dq.created_at asc
        limit 1
        """
    ).fetchone()


def mark_dream_job_running(
    conn: sqlite3.Connection,
    dream_queue_id: str,
    *,
    started_at: str,
    worker_pid: int,
    locked_by: str,
    lease_until: str,
) -> bool:
    with conn:
        cursor = conn.execute(
            """
            update dream_queue
            set status = 'running',
                attempts = attempts + 1,
                started_at = coalesce(started_at, ?),
                updated_at = ?,
                worker_pid = ?,
                locked_by = ?,
                lease_until = ?
            where dream_queue_id = ?
              and status = 'queued'
            """,
            (started_at, started_at, int(worker_pid), locked_by, lease_until, dream_queue_id),
        )
    return cursor.rowcount == 1


def get_dream_queue_job(conn: sqlite3.Connection, dream_queue_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from dream_queue where dream_queue_id = ?", (dream_queue_id,)).fetchone()


def requeue_expired_dream_jobs(
    conn: sqlite3.Connection,
    *,
    now: str,
    last_error: str,
) -> int:
    with conn:
        cursor = conn.execute(
            """
            update dream_queue
            set status = 'queued',
                updated_at = ?,
                started_at = null,
                finished_at = null,
                lease_until = null,
                locked_by = null,
                worker_pid = null,
                last_error = ?
            where status = 'running'
              and lease_until is not null
              and lease_until <= ?
            """,
            (now, last_error, now),
        )
    return int(cursor.rowcount or 0)


def mark_dream_job_finished(
    conn: sqlite3.Connection,
    dream_queue_id: str,
    *,
    status: str,
    finished_at: str,
    last_error: str | None,
) -> None:
    with conn:
        conn.execute(
            """
            update dream_queue
            set status = ?,
                finished_at = ?,
                updated_at = ?,
                last_error = ?,
                lease_until = null,
                locked_by = null
            where dream_queue_id = ?
            """,
            (status, finished_at, finished_at, last_error, dream_queue_id),
        )


def dream_queue_rows(conn: sqlite3.Connection, *, status: str, session_id: str | None, limit: int) -> list[sqlite3.Row]:
    where = []
    params: list[Any] = []
    if status != "all":
        if status == "terminal_failed":
            where.append("status = 'failed' and attempts >= max_attempts")
        else:
            where.append("status = ?")
            params.append(status)
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    where_sql = "where " + " and ".join(where) if where else ""
    return list(
        conn.execute(
            f"""
            select *
            from dream_queue
            {where_sql}
            order by
              case status
                when 'running' then 0
                when 'queued' then 1
                when 'failed' then 2
                when 'succeeded' then 3
                else 4
              end,
              priority asc,
              updated_at desc
            limit ?
            """,
            (*params, max(0, int(limit))),
        )
    )


def dream_queue_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = list(
        conn.execute(
            """
            select status, count(*) as c
            from dream_queue
            group by status
            order by status
            """
        )
    )
    counts = {str(row["status"]): int(row["c"] or 0) for row in rows}
    terminal_row = conn.execute(
        """
        select count(*) as c
        from dream_queue
        where status = 'failed' and attempts >= max_attempts
        """
    ).fetchone()
    counts["terminal_failed"] = int(terminal_row["c"] or 0)
    return counts


def delete_dream_queue_for_session(conn: sqlite3.Connection, session_id: str) -> None:
    conn.execute("delete from dream_queue where session_id = ?", (session_id,))
