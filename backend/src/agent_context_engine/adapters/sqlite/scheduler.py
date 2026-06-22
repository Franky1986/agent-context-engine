from __future__ import annotations

import sqlite3
from typing import Any


SCHEDULER_COUNT_TABLES = [
    "sessions",
    "events",
    "summaries",
    "summary_windows",
    "dream_runs",
    "graph_artifacts",
    "neo4j_imports",
    "token_usage",
    "turn_metrics",
]


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in SCHEDULER_COUNT_TABLES:
        row = conn.execute(f"select count(*) as c from {table}").fetchone()
        counts[table] = int(row["c"])
    return counts


def pending_summary_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "select count(*) as c from sessions where last_event_seq > last_summary_event_seq or summary_status = 'summary_pending'"
    ).fetchone()
    return int(row["c"])


def running_summary_window_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("select count(*) as c from summary_windows where status = 'running'").fetchone()
    return int(row["c"])


def running_dream_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("select count(*) as c from dream_runs where status = 'running'").fetchone()
    return int(row["c"])


def insert_scheduler_run(
    conn: sqlite3.Connection,
    *,
    scheduler_run_id: str,
    label: str,
    started_at: str,
    grace_minutes: int,
    runner: str,
    runner_timeout: int,
    cwd: str,
    pid: int,
    before_counts_json: str,
) -> None:
    with conn:
        conn.execute(
            """
            insert into scheduler_runs (
              scheduler_run_id, label, started_at, status, grace_minutes,
              runner, runner_timeout, cwd, pid, before_counts_json
            ) values (?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
            """,
            (
                scheduler_run_id,
                label,
                started_at,
                int(grace_minutes),
                runner,
                int(runner_timeout),
                cwd,
                int(pid),
                before_counts_json,
            ),
        )


def insert_scheduler_step(
    conn: sqlite3.Connection,
    *,
    scheduler_run_id: str,
    step_name: str,
    started_at: str,
    before_counts_json: str,
) -> int:
    with conn:
        conn.execute(
            """
            insert into scheduler_steps (
              scheduler_run_id, step_name, started_at, status, before_counts_json
            ) values (?, ?, ?, 'running', ?)
            """,
            (scheduler_run_id, step_name, started_at, before_counts_json),
        )
        row = conn.execute("select last_insert_rowid() as id").fetchone()
    return int(row["id"])


def mark_scheduler_step_finished(
    conn: sqlite3.Connection,
    *,
    step_id: int,
    finished_at: str,
    status: str,
    exit_code: int,
    after_counts_json: str,
    error_message: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """
            update scheduler_steps
            set finished_at = ?, status = ?, exit_code = ?,
                after_counts_json = ?, error_message = ?
            where id = ?
            """,
            (finished_at, status, int(exit_code), after_counts_json, error_message, int(step_id)),
        )


def mark_scheduler_run_finished(
    conn: sqlite3.Connection,
    *,
    scheduler_run_id: str,
    finished_at: str,
    status: str,
    exit_code: int,
    after_counts_json: str,
) -> None:
    with conn:
        conn.execute(
            """
            update scheduler_runs
            set finished_at = ?, status = ?, exit_code = ?, after_counts_json = ?
            where scheduler_run_id = ?
            """,
            (finished_at, status, int(exit_code), after_counts_json, scheduler_run_id),
        )


def repair_abandoned_scheduler_runs(
    conn: sqlite3.Connection,
    *,
    finished_at: str,
    notes: str,
    error_message: str,
) -> dict[str, int]:
    run_rows = list(
        conn.execute(
            """
            select scheduler_run_id
            from scheduler_runs
            where status = 'running'
            """
        )
    )
    if not run_rows:
        return {"runs": 0, "steps": 0}

    run_ids = [str(row["scheduler_run_id"]) for row in run_rows]
    step_count = 0
    with conn:
        for scheduler_run_id in run_ids:
            step_cursor = conn.execute(
                """
                update scheduler_steps
                set finished_at = ?,
                    status = 'failed',
                    exit_code = 1,
                    after_counts_json = coalesce(after_counts_json, before_counts_json),
                    error_message = coalesce(error_message, ?)
                where scheduler_run_id = ?
                  and finished_at is null
                """,
                (finished_at, error_message, scheduler_run_id),
            )
            step_count += int(step_cursor.rowcount or 0)
            conn.execute(
                """
                update scheduler_runs
                set finished_at = ?,
                    status = 'failed',
                    exit_code = 1,
                    after_counts_json = coalesce(after_counts_json, before_counts_json),
                    notes = coalesce(notes, ?)
                where scheduler_run_id = ?
                """,
                (finished_at, notes, scheduler_run_id),
            )
    return {"runs": len(run_ids), "steps": step_count}


def scheduler_run_rows(conn: sqlite3.Connection, *, limit: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            select *
            from scheduler_runs
            order by started_at desc
            limit ?
            """,
            (int(limit),),
        )
    )


def scheduler_step_rows(conn: sqlite3.Connection, *, scheduler_run_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            select *
            from scheduler_steps
            where scheduler_run_id = ?
            order by id
            """,
            (scheduler_run_id,),
        )
    )
