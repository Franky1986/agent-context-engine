from __future__ import annotations

import sqlite3


def upsert_session_summary(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    summary_path: str,
    created_at: str,
    input_event_seq_to: int,
    input_event_count: int,
) -> None:
    with conn:
        conn.execute(
            """
            insert into summaries (
              session_id, summary_path, created_at, input_event_seq_to,
              input_event_count, summary_kind
            ) values (?, ?, ?, ?, ?, 'deterministic_handover')
            on conflict(session_id) do update set
              summary_path = excluded.summary_path,
              created_at = excluded.created_at,
              input_event_seq_to = excluded.input_event_seq_to,
              input_event_count = excluded.input_event_count,
              summary_kind = excluded.summary_kind
            """,
            (session_id, summary_path, created_at, int(input_event_seq_to), int(input_event_count)),
        )
        conn.execute(
            "update sessions set summary_status = 'summarized', last_summary_event_seq = last_event_seq, last_summary_at = ? where session_id = ?",
            (created_at, session_id),
        )


def running_window_overlap(conn: sqlite3.Connection, *, start: str, end: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select window_id, window_start, window_end
        from summary_windows
        where status = 'running' and window_start < ? and window_end > ?
        order by created_at desc
        limit 1
        """,
        (end, start),
    ).fetchone()


def events_for_window(conn: sqlite3.Connection, *, start: str, end: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            select e.*, s.thread_name
            from events e
            left join sessions s on s.session_id = e.session_id
            where e.recorded_at >= ? and e.recorded_at < ?
            order by e.recorded_at, e.session_id, e.seq
            """,
            (start, end),
        )
    )


def summary_window_status(conn: sqlite3.Connection, *, window_id: str) -> sqlite3.Row | None:
    return conn.execute("select status, input_event_count from summary_windows where window_id = ?", (window_id,)).fetchone()


def mark_summary_window_running(
    conn: sqlite3.Connection,
    *,
    window_id: str,
    window_start: str,
    window_end: str,
    grace_until: str,
    created_at: str,
    input_event_count: int,
    notes: str,
) -> None:
    with conn:
        conn.execute(
            """
            insert into summary_windows (
              window_id, window_start, window_end, grace_until, status,
              created_at, input_event_count, notes
            ) values (?, ?, ?, ?, 'running', ?, ?, ?)
            on conflict(window_id) do update set
              window_start = excluded.window_start,
              window_end = excluded.window_end,
              grace_until = excluded.grace_until,
              status = excluded.status,
              created_at = excluded.created_at,
              input_event_count = excluded.input_event_count,
              notes = excluded.notes
            """,
            (window_id, window_start, window_end, grace_until, created_at, int(input_event_count), notes),
        )


def mark_summary_window_summarized(
    conn: sqlite3.Connection,
    *,
    window_id: str,
    window_start: str,
    window_end: str,
    grace_until: str,
    created_at: str,
    input_event_count: int,
    output_path: str,
    notes: str,
) -> None:
    with conn:
        conn.execute(
            """
            insert into summary_windows (
              window_id, window_start, window_end, grace_until, status,
              created_at, input_event_count, output_path, notes
            ) values (?, ?, ?, ?, 'summarized', ?, ?, ?, ?)
            on conflict(window_id) do update set
              status = excluded.status,
              created_at = excluded.created_at,
              input_event_count = excluded.input_event_count,
              output_path = excluded.output_path,
              grace_until = excluded.grace_until,
              notes = excluded.notes
            """,
            (window_id, window_start, window_end, grace_until, created_at, int(input_event_count), output_path, notes),
        )


def mark_summary_window_failed(conn: sqlite3.Connection, *, window_id: str, notes: str) -> None:
    with conn:
        conn.execute("update summary_windows set status = 'failed', notes = ? where window_id = ?", (notes, window_id))


def summary_window_bounds(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "select min(window_start) as first_start, max(window_end) as last_end from summary_windows where status in ('summarized', 'running', 'failed')"
    ).fetchone()


def earliest_event_at_before(conn: sqlite3.Connection, *, cutoff: str) -> str | None:
    row = conn.execute("select min(recorded_at) as first_at from events where recorded_at <= ?", (cutoff,)).fetchone()
    return row["first_at"] if row else None
