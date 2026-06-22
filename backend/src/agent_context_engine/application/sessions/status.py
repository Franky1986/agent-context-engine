from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any

from ...infrastructure.db import connect
from ...infrastructure.config import session_short
from ...infrastructure.metrics import session_metrics


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


def cmd_status(args: argparse.Namespace) -> int:
    conn = connect()
    rows = list(conn.execute("select * from sessions order by coalesce(last_event_at, started_at) desc limit ?", (args.limit,)))
    if not rows:
        print("No sessions recorded.")
        return 0
    for row in rows:
        new_summary = int(row["last_event_seq"]) - int(row["last_summary_event_seq"])
        new_dream = int(row["last_event_seq"]) - int(row["last_dream_event_seq"])
        print(f"{row['client_type']} {session_short(row['session_id'])} {row['project_id'] or 'unknown'} {row['status']} summary={row['summary_status']} dream={row['dream_status']}")
        if row["thread_name"]:
            print(f"  title: {row['thread_name']}")
        print(f"  events: {row['last_event_seq']} last={local_time(row['last_event_at'])}")
        if row["last_workdir"] and row["last_workdir"] != row["cwd"]:
            print(f"  workdir: {row['last_workdir']}")
        print(f"  last summary: {local_time(row['last_summary_at']) or '-'} new_events={max(new_summary, 0)}")
        print(f"  last dream: {local_time(row['last_dream_at']) or '-'} new_events={max(new_dream, 0)} run={row['last_dream_run_id'] or '-'}")
        if row["last_dream_run_id"]:
            dream = conn.execute(
                "select runner, runner_model from dream_runs where dream_run_id = ?", (row["last_dream_run_id"],)
            ).fetchone()
            if dream:
                print(f"  dream runner: {dream['runner']} model={dream['runner_model'] or '-'}")
        if row["native_resume_command"]:
            print(f"  resume: {row['native_resume_command']}")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    conn = connect()
    rows = list(conn.execute("select * from sessions order by coalesce(last_event_at, started_at) desc limit ?", (args.limit,)))
    if not rows:
        print("No sessions recorded.")
        return 0
    for row in rows:
        metrics = session_metrics(conn, row["session_id"])
        title = f" title={row['thread_name']}" if row["thread_name"] else ""
        print(f"{row['client_type']} {session_short(row['session_id'])} {row['project_id']}{title}")
        print(
            "  "
            f"turns={metrics['turns']} duration_ms={metrics['duration_ms']} ttft_ms={metrics['ttft_ms']} "
            f"tokens total={metrics['total_tokens']} input={metrics['input_tokens']} "
            f"cached={metrics['cached_input_tokens']} output={metrics['output_tokens']} "
            f"reasoning={metrics['reasoning_output_tokens']}"
        )
    return 0


def cmd_dream_insights(args: argparse.Namespace) -> int:
    conn = connect()
    where = []
    params: list[Any] = []
    if args.intent:
        where.append("intent = ?")
        params.append(args.intent)
    if args.min_helpful_score is not None:
        where.append("coalesce(helpful_score, 0) >= ?")
        params.append(args.min_helpful_score)
    if args.tag:
        where.append("coalesce(tags_json, '') like ?")
        params.append(f"%{args.tag}%")
    where_sql = "where " + " and ".join(where) if where else ""
    if args.aggregate:
        rows = list(
            conn.execute(
                f"""
                select coalesce(intent, 'unknown') as intent,
                       count(*) as runs,
                       round(avg(helpful_score), 4) as avg_helpful_score,
                       max(finished_at) as last_finished_at
                from dream_runs
                {where_sql}
                group by coalesce(intent, 'unknown')
                order by runs desc, intent
                limit ?
                """,
                (*params, args.limit),
            )
        )
        for row in rows:
            print(
                f"{row['intent']} runs={row['runs']} avg_helpful_score={row['avg_helpful_score'] if row['avg_helpful_score'] is not None else '-'} "
                f"last={local_time(row['last_finished_at']) or '-'}"
            )
        return 0
    rows = list(
        conn.execute(
            f"""
            select dr.*, s.thread_name, s.project_id
            from dream_runs dr
            left join sessions s on s.session_id = dr.session_id
            {where_sql}
            order by coalesce(dr.finished_at, dr.started_at) desc
            limit ?
            """,
            (*params, args.limit),
        )
    )
    for row in rows:
        tags = []
        if row["tags_json"]:
            try:
                tags = json.loads(row["tags_json"])
            except json.JSONDecodeError:
                tags = []
        print(
            f"{local_time(row['finished_at'] or row['started_at'])} {row['client_type']} {session_short(row['session_id'])} "
            f"intent={row['intent'] or '-'} helpful_score={row['helpful_score'] if row['helpful_score'] is not None else '-'}"
        )
        print(f"  project={row['project_id'] or '-'} title={row['thread_name'] or '-'} runner={row['runner']} model={row['runner_model'] or '-'}")
        print(f"  dream_run={row['dream_run_id']} tags={','.join(tags) if tags else '-'}")
    return 0


__all__ = [
    "cmd_dream_insights",
    "cmd_metrics",
    "cmd_status",
    "local_time",
]
