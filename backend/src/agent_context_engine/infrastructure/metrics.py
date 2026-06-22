from __future__ import annotations

import sqlite3

from .db import connect


def session_metrics(conn: sqlite3.Connection, session_id: str) -> dict[str, int]:
    row = conn.execute(
        """
        select coalesce(tm.turns, 0) as turns,
               coalesce(tm.duration_ms, 0) as duration_ms,
               coalesce(tm.ttft_ms, 0) as ttft_ms,
               coalesce(tu.input_tokens, 0) as input_tokens,
               coalesce(tu.cached_input_tokens, 0) as cached_input_tokens,
               coalesce(tu.output_tokens, 0) as output_tokens,
               coalesce(tu.reasoning_output_tokens, 0) as reasoning_output_tokens,
               coalesce(tu.total_tokens, 0) as total_tokens
        from sessions s
        left join (
          select session_id,
                 count(*) as turns,
                 sum(coalesce(duration_ms, 0)) as duration_ms,
                 sum(coalesce(time_to_first_token_ms, 0)) as ttft_ms
          from turn_metrics
          where session_id = ?
          group by session_id
        ) tm on tm.session_id = s.session_id
        left join (
          select session_id,
                 sum(input_tokens) as input_tokens,
                 sum(cached_input_tokens) as cached_input_tokens,
                 sum(output_tokens) as output_tokens,
                 sum(reasoning_output_tokens) as reasoning_output_tokens,
                 sum(total_tokens) as total_tokens
          from (
            select session_id,
                   coalesce(turn_id, 'row:' || id) as turn_key,
                   max(coalesce(input_tokens, 0)) as input_tokens,
                   max(coalesce(cached_input_tokens, 0)) as cached_input_tokens,
                   max(coalesce(output_tokens, 0)) as output_tokens,
                   max(coalesce(reasoning_output_tokens, 0)) as reasoning_output_tokens,
                   max(coalesce(total_tokens, 0)) as total_tokens
            from token_usage
            where session_id = ?
            group by session_id, turn_key
          )
          group by session_id
        ) tu on tu.session_id = s.session_id
        where s.session_id = ?
        """,
        (session_id, session_id, session_id),
    ).fetchone()
    keys = [
        "turns",
        "duration_ms",
        "ttft_ms",
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    ]
    if row is None:
        return {key: 0 for key in keys}
    return {key: int(row[key] or 0) for key in keys}


def aggregate_metrics_for_events(events: list[sqlite3.Row]) -> dict[str, int]:
    session_ids = sorted({event["session_id"] for event in events})
    if not session_ids:
        return {
            "sessions": 0,
            "turns": 0,
            "duration_ms": 0,
            "ttft_ms": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "reasoning_output_tokens": 0,
            "total_tokens": 0,
        }
    conn = connect()
    placeholders = ",".join("?" for _ in session_ids)
    row = conn.execute(
        f"""
        select
          (select count(distinct session_id) from events where session_id in ({placeholders})) as sessions,
          (select count(*) from turn_metrics where session_id in ({placeholders})) as turns,
          (select coalesce(sum(duration_ms), 0) from turn_metrics where session_id in ({placeholders})) as duration_ms,
          (select coalesce(sum(time_to_first_token_ms), 0) from turn_metrics where session_id in ({placeholders})) as ttft_ms,
          (select coalesce(sum(input_tokens), 0) from (
             select session_id, coalesce(turn_id, 'row:' || id) as turn_key, max(coalesce(input_tokens, 0)) as input_tokens
             from token_usage where session_id in ({placeholders}) group by session_id, turn_key
           )) as input_tokens,
          (select coalesce(sum(cached_input_tokens), 0) from (
             select session_id, coalesce(turn_id, 'row:' || id) as turn_key, max(coalesce(cached_input_tokens, 0)) as cached_input_tokens
             from token_usage where session_id in ({placeholders}) group by session_id, turn_key
           )) as cached_input_tokens,
          (select coalesce(sum(output_tokens), 0) from (
             select session_id, coalesce(turn_id, 'row:' || id) as turn_key, max(coalesce(output_tokens, 0)) as output_tokens
             from token_usage where session_id in ({placeholders}) group by session_id, turn_key
           )) as output_tokens,
          (select coalesce(sum(reasoning_output_tokens), 0) from (
             select session_id, coalesce(turn_id, 'row:' || id) as turn_key, max(coalesce(reasoning_output_tokens, 0)) as reasoning_output_tokens
             from token_usage where session_id in ({placeholders}) group by session_id, turn_key
           )) as reasoning_output_tokens,
          (select coalesce(sum(total_tokens), 0) from (
             select session_id, coalesce(turn_id, 'row:' || id) as turn_key, max(coalesce(total_tokens, 0)) as total_tokens
             from token_usage where session_id in ({placeholders}) group by session_id, turn_key
           )) as total_tokens
        """,
        tuple(session_ids) * 9,
    ).fetchone()
    return {key: int(row[key] or 0) for key in row.keys()}
