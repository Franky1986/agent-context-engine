from __future__ import annotations

import sqlite3


def fetch_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()


def session_events(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return list(conn.execute("select * from events where session_id = ? order by recorded_at, seq", (session_id,)))


def summarizable_sessions(conn: sqlite3.Connection, pending_only: bool) -> list[sqlite3.Row]:
    sql = "select * from sessions"
    if pending_only:
        sql += " where last_event_seq > last_summary_event_seq or summary_status = 'summary_pending'"
    sql += " order by last_event_at desc"
    return list(conn.execute(sql))


def dreamable_sessions(conn: sqlite3.Connection, pending_only: bool) -> list[sqlite3.Row]:
    sql = "select * from sessions"
    if pending_only:
        sql += """
        where coalesce(dream_status, 'dream_pending') <> 'failed'
          and (
            last_event_seq > last_dream_event_seq
            or exists (
                select 1
                from events e
                where e.session_id = sessions.session_id
                  and not exists (
                    select 1
                    from dream_runs dr
                    where dr.session_id = sessions.session_id
                      and dr.status = 'succeeded'
                      and e.seq between dr.input_event_seq_from and dr.input_event_seq_to
                  )
           )
            or exists (
                select 1
                from dream_runs dr
                where dr.session_id = sessions.session_id
                  and dr.status = 'succeeded'
                  and coalesce(dr.pipeline_version, 1) = 1
                  and not exists (
                    select 1
                    from graph_artifacts ga
                    where ga.dream_run_id = dr.dream_run_id
                      and ga.artifact_type = 'patch'
                      and ga.status = 'valid'
                  )
            )
          )
        """
    sql += " order by last_event_at desc"
    return list(conn.execute(sql))


def resolve_session(conn: sqlite3.Connection, selector: str) -> sqlite3.Row | None:
    rows = list(
        conn.execute(
            """
            select * from sessions
            where session_id like ?
               or coalesce(thread_name, '') like ?
            order by coalesce(last_event_at, started_at) desc
            limit 2
            """,
            (f"{selector}%", f"%{selector}%"),
        )
    )
    if rows:
        return rows[0]
    like = f"%{selector}%"
    return conn.execute(
        """
        select s.*
        from sessions s
        where exists (
          select 1 from events e
          where e.session_id = s.session_id
            and (
              coalesce(e.prompt, '') like ?
              or coalesce(e.last_assistant_message, '') like ?
              or coalesce(e.tool_response_text, '') like ?
            )
        )
        order by coalesce(s.last_event_at, s.started_at) desc
        limit 1
        """,
        (like, like, like),
    ).fetchone()
