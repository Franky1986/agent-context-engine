from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ...infrastructure.config import json_dumps, session_short
from ...infrastructure.db import connect, resolve_session
from ...infrastructure.text import markdown_escape
from ..file_access import rebuild_file_accesses
from ..toolrefs import read_tool_output_text


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


def cmd_tool_calls(args: argparse.Namespace) -> int:
    conn = connect()
    params: list[object] = []
    where = "where 1=1"
    if args.session:
        session = resolve_session(conn, args.session)
        if session is None:
            print(f"No session found for selector: {args.session}", file=sys.stderr)
            return 1
        where += " and tc.session_id = ?"
        params.append(session["session_id"])
    rows = list(
        conn.execute(
            f"""
            select tc.*, out.tool_output_id, out.byte_count, out.line_count, out.sha256
            from tool_calls tc
            left join tool_outputs out on out.tool_output_id = tc.output_id
            {where}
            order by tc.recorded_at desc, tc.seq desc
            limit ?
            """,
            (*params, args.limit),
        )
    )
    for row in rows:
        print(
            f"{local_time(row['recorded_at'])} session={row['session_id']} seq={row['seq']} "
            f"tool={row['tool_name'] or '-'} status={row['status']} "
            f"output={row['tool_output_id'] or '-'} bytes={row['byte_count'] or 0} lines={row['line_count'] or 0}"
        )
    if not rows:
        print("No tool calls found.")
    return 0


def cmd_tool_output(args: argparse.Namespace) -> int:
    conn = connect()
    row = None
    if args.output_id:
        row = conn.execute("select * from tool_outputs where tool_output_id = ?", (args.output_id,)).fetchone()
    elif args.session and args.seq is not None:
        session = resolve_session(conn, args.session)
        if session is None:
            print(f"No session found for selector: {args.session}", file=sys.stderr)
            return 1
        row = conn.execute(
            "select * from tool_outputs where session_id = ? and seq = ?", (session["session_id"], args.seq)
        ).fetchone()
    else:
        print("Provide output_id or --session plus --seq", file=sys.stderr)
        return 1
    if row is None:
        print("No tool output found.", file=sys.stderr)
        return 1
    if args.metadata:
        print(f"tool_output_id: {row['tool_output_id']}")
        print(f"session_id: {row['session_id']}")
        print(f"seq: {row['seq']}")
        print(f"status: {row['status']}")
        print(f"bytes: {row['byte_count']}")
        print(f"chars: {row['char_count']}")
        print(f"lines: {row['line_count']}")
        print(f"sha256: {row['sha256']}")
        print(f"storage_kind: {row['storage_kind']}")
        print(f"path: {row['path'] or ''}")
        print("")
    text = read_tool_output_text(row)
    if args.chars and len(text) > args.chars:
        text = text[: args.chars] + "\n...[truncated]"
    if text:
        print(text)
    else:
        print("Raw tool output is not persisted. Only summary metadata is kept in events/tool_outputs.")
    return 0


def cmd_file_accesses(args: argparse.Namespace) -> int:
    conn = connect()
    params: list[object] = []
    where = "where 1=1"
    if args.session:
        session = resolve_session(conn, args.session)
        if session is None:
            print(f"No session found for selector: {args.session}", file=sys.stderr)
            return 1
        where += " and fa.session_id = ?"
        params.append(session["session_id"])
    if args.path:
        needle = normalize_path_text(args.path)
        where += " and (fa.path_abs = ? or fa.path_key = ? or fa.path_abs like ? or fa.path_key like ?)"
        params.extend([needle, args.path, f"%{args.path}%", f"%{args.path}%"])
    if args.operation:
        where += " and fa.operation = ?"
        params.append(args.operation)
    rows = list(
        conn.execute(
            f"""
            select fa.*, s.thread_name, s.session_brief
            from file_accesses fa
            left join sessions s on s.session_id = fa.session_id
            {where}
            order by fa.recorded_at desc, fa.seq desc, fa.path_key
            limit ?
            """,
            (*params, args.limit),
        )
    )
    if args.json:
        print(json_dumps({"file_accesses": [dict(row) for row in rows]}))
        return 0
    if not rows:
        print("No file accesses found.")
        return 0
    for row in rows:
        print(
            f"{local_time(row['recorded_at'])} {row['operation']} status={row['status']} "
            f"session={session_short(row['session_id'])} seq={row['seq']} tool={row['tool_name'] or '-'}"
        )
        print(f"  path: {row['path_key']}")
        if row["path_abs"]:
            print(f"  abs: {row['path_abs']}")
        if row["session_brief"]:
            print(f"  session: {row['session_brief']}")
        if args.evidence:
            print(markdown_escape(row["evidence_quote"] or "", args.chars).replace("\n", "\n  "))
    return 0


def cmd_rebuild_file_accesses(args: argparse.Namespace) -> int:
    conn = connect()
    session_id = None
    if args.session:
        session = resolve_session(conn, args.session)
        if session is None:
            print(f"No session found for selector: {args.session}", file=sys.stderr)
            return 1
        session_id = session["session_id"]
    count = rebuild_file_accesses(conn, session_id)
    print(f"rebuilt file_accesses={count}" + (f" session={session_id}" if session_id else ""))
    return 0


def cmd_operational_facts(args: argparse.Namespace) -> int:
    conn = connect()
    params: list[object] = []
    where = "where 1=1"
    session_id = None
    if args.session:
        session = resolve_session(conn, args.session)
        if session is None:
            print(f"No session found for selector: {args.session}", file=sys.stderr)
            return 1
        session_id = session["session_id"]
        where += " and of.session_id = ?"
        params.append(session_id)
    if args.dream_run_id:
        where += " and of.dream_run_id = ?"
        params.append(args.dream_run_id)
    if args.kind:
        where += " and of.fact_kind = ?"
        params.append(args.kind)
    facts = [
        dict(row)
        for row in conn.execute(
            f"""
            select of.*, s.thread_name, s.project_id
            from operational_facts of
            left join sessions s on s.session_id = of.session_id
            {where}
            order by of.created_at desc, of.session_id, of.event_seq, of.fact_kind, of.fact_key
            limit ?
            """,
            (*params, args.limit),
        )
    ]
    pretool_params: list[object] = []
    pretool_where = "where 1=1"
    if session_id:
        pretool_where += " and p.session_id = ?"
        pretool_params.append(session_id)
    if args.dream_run_id:
        pretool_where += " and p.dream_run_id = ?"
        pretool_params.append(args.dream_run_id)
    pretools = []
    if args.include_pretool:
        pretools = [
            dict(row)
            for row in conn.execute(
                f"""
                select p.*, s.thread_name, s.project_id
                from pretool_audit_refs p
                left join sessions s on s.session_id = p.session_id
                {pretool_where}
                order by p.created_at desc, p.session_id, p.event_seq
                limit ?
                """,
                (*pretool_params, args.limit),
            )
        ]
    if args.json:
        print(json_dumps({"operational_facts": facts, "pretool_audit_refs": pretools}))
        return 0
    if not facts and not pretools:
        print("No operational facts found.")
        return 0
    for row in facts:
        print(
            f"{row['created_at']} {row['fact_kind']} operation={row['operation'] or '-'} "
            f"status={row['status']} session={session_short(row['session_id'])} seq={row['event_seq'] or '-'}"
        )
        print(f"  subject: {row['subject'] or row['fact_key']}")
        print(f"  dream: {row['dream_run_id'] or '-'}")
    for row in pretools:
        print(
            f"{row['created_at']} pretool_audit status={row['status']} decision={row['decision'] or '-'} "
            f"approval={row['approval_state'] or '-'} session={session_short(row['session_id'])} seq={row['event_seq']}"
        )
        print(f"  tool: {row['tool_name'] or '-'} use={row['tool_use_id'] or '-'} risk={row['risk_event_id'] or '-'}")
        if row["redacted_preview"]:
            print(f"  preview: {markdown_escape(row['redacted_preview'], args.chars).replace(chr(10), chr(10) + '  ')}")
    return 0


__all__ = [
    "cmd_tool_calls",
    "cmd_tool_output",
    "cmd_file_accesses",
    "cmd_rebuild_file_accesses",
    "cmd_operational_facts",
    "local_time",
]
