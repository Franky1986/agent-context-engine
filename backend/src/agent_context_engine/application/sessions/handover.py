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
from ..dreaming.memory import extract_session_brief
from ...infrastructure.config import MEMORY_DIR, ROOT
from ...infrastructure.db import connect, resolve_session, session_events
from ...infrastructure.metrics import session_metrics
from ...infrastructure.render import conversation_timeline
from ...adapters.runners.session_metadata import refresh_session_row_metadata
from ..retrieval import search_memory_chunks
from ...infrastructure.text import markdown_escape, tagged_block


def _quote_platform_value(value: str | Path) -> str:
    from ..platform import current_platform_profile
    from ..platform.runtime_selection import select_path_quoting_adapter

    return select_path_quoting_adapter(current_platform_profile()).quote(str(value))


def resume_command(session: sqlite3.Row) -> str:
    if session["client_type"] == "codex":
        wrapper_name = resolve_runner_wrapper_name("codex", root=ROOT)
        return f"{wrapper_name} resume {_quote_platform_value(session['session_id'])}"
    if session["client_type"] == "antigravity":
        workdir = session["last_workdir"] or session["cwd"] or str(ROOT)
        return f"cd {_quote_platform_value(workdir)} && agy --conversation {_quote_platform_value(session['session_id'])}"
    return session["native_resume_command"] or f"# unsupported client: {session['client_type']} {session['session_id']}"


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


def cmd_resume(args: argparse.Namespace) -> int:
    conn = connect()
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}", file=sys.stderr)
        return 1
    refresh_session_row_metadata(conn, session)
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}", file=sys.stderr)
        return 1
    command = resume_command(session)
    if args.print_only:
        print(command)
        return 0
    if session["client_type"] == "codex":
        wrapper_name = resolve_runner_wrapper_name("codex", root=ROOT)
        os.chdir(str(ROOT))
        os.execvp(wrapper_name, [wrapper_name, "resume", session["session_id"]])
    if session["client_type"] == "antigravity":
        workdir = session["last_workdir"] or session["cwd"] or str(ROOT)
        os.chdir(str(workdir))
        os.execvp("agy", ["agy", "--conversation", session["session_id"]])
    if session["client_type"] == "claude":
        wrapper_name = resolve_runner_wrapper_name("claude", root=ROOT)
        os.chdir(str(ROOT))
        os.execvp(wrapper_name, [wrapper_name, "--resume", session["session_id"]])
    if session["client_type"] == "cursor":
        workdir = session["last_workdir"] or session["cwd"] or str(ROOT)
        os.chdir(str(workdir))
        os.execvp("cursor-agent", ["cursor-agent", "--resume", session["session_id"]])
    if session["client_type"] == "opencode":
        workdir = session["last_workdir"] or session["cwd"] or str(ROOT)
        os.chdir(str(workdir))
        os.execvp("opencode", ["opencode", "--session", session["session_id"]])
    print(f"Cannot auto-resume unsupported client: {session['client_type']}", file=sys.stderr)
    print(command)
    return 1


def cmd_context(args: argparse.Namespace) -> int:
    conn = connect()
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}", file=sys.stderr)
        return 1
    refresh_session_row_metadata(conn, session)
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}", file=sys.stderr)
        return 1
    dream = latest_dream_for_session(conn, session["session_id"])
    summary = _resolve_active_summary(conn, session["session_id"], dream)
    events = session_events(conn, session["session_id"])
    tools = [event for event in events if event["tool_name"]]
    print(f"Session: {session['session_id']}")
    print(f"Title: {session['thread_name'] or '-'}")
    print(f"Client: {session['client_type']}")
    print(f"Project: {session['project_id'] or '-'}")
    print(f"Workdir: {session['last_workdir'] or session['cwd'] or '-'}")
    print(f"Status: {session['status']} summary={session['summary_status']} dream={session['dream_status']}")
    print(f"Events: {session['last_event_seq']}")
    print(f"Last event: {local_time(session['last_event_at']) or '-'}")
    print(f"Last summary: {local_time(session['last_summary_at']) or '-'}")
    print(f"Last dream: {local_time(session['last_dream_at']) or '-'}")
    print(f"Summary: {summary.get('summary_path') if summary else '-'}")
    print(f"Transcript: {session['transcript_path'] or '-'}")
    print(f"Exact resume: {resume_command(session)}")
    print("")
    print("Conversation timeline:")
    items = conversation_timeline(events)
    for item in items[-args.timeline :]:
        print(item)
    if not items:
        print("- None")
    print("")
    print("Recent tools:")
    for event in tools[-args.tools :]:
        print(f"- #{event['seq']} {event['tool_name']} {markdown_escape(event['tool_use_id'], 120)}")
        if args.show_tools:
            if event["tool_input_json"]:
                print(
                    tagged_block(
                        "tool_input",
                        {"seq": event["seq"], "tool": event["tool_name"]},
                        event["tool_input_json"],
                        1500,
                    )
                )
            if event["tool_response_text"]:
                print(
                    tagged_block(
                        "tool_response",
                        {"seq": event["seq"], "tool": event["tool_name"]},
                        event["tool_response_text"],
                        2000,
                    )
                )
    if not tools:
        print("- None")
    if summary and args.show_handover:
        content = read_existing_rel(str(summary.get("summary_path") or ""), 200_000)
        if content:
            print("")
            print("Handover:")
            print(content)
    return 0


def latest_dream_for_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select *
        from dream_runs
        where session_id = ?
        order by coalesce(finished_at, started_at) desc
        limit 1
        """,
        (session_id,),
    ).fetchone()


def _runtime_allowed_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in (ROOT, MEMORY_DIR):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _resolve_runtime_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    for allowed_root in _runtime_allowed_roots():
        if resolved == allowed_root or allowed_root in resolved.parents:
            return resolved
    return None


def _display_path(path_value: str | Path | None) -> str:
    if not path_value:
        return ""
    candidate = Path(path_value)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(ROOT))
        except ValueError:
            return str(candidate)
    return str(candidate)


def read_existing_rel(path_value: str | None, limit: int) -> str:
    path = _resolve_runtime_path(path_value)
    if path is None:
        return ""
    if not path.exists() or not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:limit]


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()} if row is not None else {}


def _parse_json_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, (str, Path))]
    if not isinstance(value, str):
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if isinstance(item, (str, Path))]


def _resolve_summary_from_latest_dream(dream: sqlite3.Row | None) -> dict[str, Any]:
    if dream is None:
        return {}
    output_summary_path = str(dream["output_summary_path"] or "").strip()
    if output_summary_path:
        return {
            "summary_path": output_summary_path,
            "summary_kind": "dream_pipeline_v2",
            "created_at": dream["finished_at"] or dream["started_at"],
            "input_event_count": int(dream["input_event_count"] or 0),
        }
    for path in _parse_json_list(dream["output_memory_paths_json"]):
        normalized = str(path).strip()
        if normalized.endswith("/summary.md") and "/audit/" in normalized:
            return {
                "summary_path": normalized,
                "summary_kind": "dream_pipeline_v2",
                "created_at": dream["finished_at"] or dream["started_at"],
                "input_event_count": int(dream["input_event_count"] or 0),
            }
    return {}


def _resolve_active_summary(conn: sqlite3.Connection, session_id: str, dream: sqlite3.Row | None) -> dict[str, Any]:
    summary = _row_dict(conn.execute("select * from summaries where session_id = ?", (session_id,)).fetchone())
    if summary.get("summary_path") and read_existing_rel(str(summary["summary_path"]), 1):
        return summary
    fallback = _resolve_summary_from_latest_dream(dream)
    if fallback.get("summary_path") and read_existing_rel(str(fallback["summary_path"]), 1):
        return fallback
    return summary or fallback


def _latest_dream_memory_path(dream: sqlite3.Row | None) -> str:
    if dream is None:
        return ""
    preferred = ""
    for path in _parse_json_list(dream["output_memory_paths_json"]):
        normalized = str(path).strip()
        if not normalized.endswith(".md"):
            continue
        if "/memories/dreams/" in normalized:
            return normalized
        if "/audit/" in normalized:
            continue
        if not preferred:
            preferred = normalized
    return preferred


def _summary_brief(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("-").strip()
        if line:
            return line[:240]
    return ""


def project_memory_path(project_id: str | None) -> Path:
    from ...infrastructure.config import safe_slug

    return MEMORY_DIR / "memories" / "projects" / f"{safe_slug(project_id or 'unknown')}.md"


def cmd_handover(args: argparse.Namespace) -> int:
    conn = connect()
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}", file=sys.stderr)
        return 1
    refresh_session_row_metadata(conn, session)
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}", file=sys.stderr)
        return 1
    dream = latest_dream_for_session(conn, session["session_id"])
    summary = _resolve_active_summary(conn, session["session_id"], dream)
    summary_text = read_existing_rel(str(summary.get("summary_path") or ""), args.summary_chars).strip()
    dream_memory_path = _latest_dream_memory_path(dream)
    dream_memory_text = read_existing_rel(dream_memory_path, args.dream_chars).strip()
    session_brief = (
        extract_session_brief(dream_memory_text)
        or str(session["session_brief"] or "").strip()
        or _summary_brief(summary_text)
    )
    metrics = session_metrics(conn, session["session_id"])
    workdir = session["last_workdir"] or session["cwd"] or str(ROOT)
    events = session_events(conn, session["session_id"])
    tools = [event for event in events if event["tool_name"]]

    print("# Agent Context Engine Handover")
    print("")
    print("## Routing")
    print("")
    print(f"- session_id: `{session['session_id']}`")
    print(f"- thread_name: `{session['thread_name'] or ''}`")
    print(f"- client_type: `{session['client_type']}`")
    print(f"- project_id: `{session['project_id'] or 'unknown'}`")
    print(f"- workdir: `{workdir}`")
    print(f"- use_workdir_for_tools: `{workdir}`")
    print(f"- exact_resume: `{resume_command(session)}`")
    print(f"- transcript: `{session['transcript_path'] or ''}`")
    print("")
    print("## Freshness")
    print("")
    print(f"- status: `{session['status']}`")
    print(f"- events: `{session['last_event_seq']}`")
    print(f"- last_event_at: `{local_time(session['last_event_at'])}`")
    print(f"- summary_status: `{session['summary_status']}`")
    print(f"- active_summary_kind: `{summary.get('summary_kind') or ''}`")
    print(f"- last_summary_at: `{local_time(session['last_summary_at'])}`")
    print(f"- new_events_since_summary: `{max(int(session['last_event_seq']) - int(session['last_summary_event_seq']), 0)}`")
    print(f"- dream_status: `{session['dream_status']}`")
    print(f"- last_dream_at: `{local_time(session['last_dream_at'])}`")
    print(f"- last_dream_run_id: `{session['last_dream_run_id'] or ''}`")
    print(f"- new_events_since_dream: `{max(int(session['last_event_seq']) - int(session['last_dream_event_seq']), 0)}`")
    if dream:
        print(f"- dream_runner: `{dream['runner']}`")
        print(f"- dream_runner_model: `{dream['runner_model'] or ''}`")
        print(f"- dream_run_status: `{dream['status']}`")
    print("")
    print("## Metrics")
    print("")
    print(
        f"- turns: `{metrics['turns']}` duration_ms: `{metrics['duration_ms']}` "
        f"ttft_ms: `{metrics['ttft_ms']}` total_tokens: `{metrics['total_tokens']}` "
        f"input_tokens: `{metrics['input_tokens']}` output_tokens: `{metrics['output_tokens']}` "
        f"reasoning_tokens: `{metrics['reasoning_output_tokens']}`"
    )
    print("")
    print("## Artifacts")
    print("")
    print(f"- summary: `{summary.get('summary_path') or ''}` kind=`{summary.get('summary_kind') or ''}`")
    if dream:
        print(f"- dream_memory: `{dream['output_memory_paths_json'] or ''}`")
    project_memory = project_memory_path(session["project_id"])
    print(f"- project_memory: `{_display_path(project_memory) if project_memory.exists() else ''}`")
    graph_rows = list(
        conn.execute(
            """
            select *
            from graph_artifacts
            where session_id = ?
            order by created_at desc
            limit ?
            """,
            (session["session_id"], args.graph_limit),
        )
    )
    for row in graph_rows:
        print(
            f"- graph_{row['artifact_type']}: `{row['path']}` status=`{row['status']}` "
            f"entities=`{row['entity_count']}` relations=`{row['relation_count']}`"
        )
    print("")
    agents_path = Path(workdir) / "AGENTS.md"
    if not agents_path.exists():
        agents_path = ROOT / "AGENTS.md"
    print("## Agent Instructions")
    print("")
    if agents_path.exists():
        try:
            text = agents_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        print((text[: args.project_chars]).strip() or "_AGENTS.md is empty._")
    else:
        print("_No AGENTS.md found for this workdir._")
    print("")

    if session_brief:
        print("## Session Brief")
        print("")
        print(session_brief)
        print("")
    if summary.get("summary_path"):
        print("## Current Session Summary")
        print("")
        print(summary_text or "_Summary file missing or empty._")
        print("")
    if dream_memory_path and dream_memory_text and dream_memory_path != str(summary.get("summary_path") or ""):
        print("## Latest Dream Memory")
        print("")
        print(dream_memory_text or "_Dream file missing or empty._")
        print("")
    if args.include_project_memory and project_memory.exists():
        print("## Project Memory")
        print("")
        print(read_existing_rel(str(project_memory), args.project_chars).strip())
        print("")
    query_terms = " ".join(
        item
        for item in [args.selector, session["thread_name"] or "", session["project_id"] or "", workdir]
        if item
    )
    retrieved = search_memory_chunks(conn, query_terms, project_id=session["project_id"], limit=args.retrieval_limit)
    if retrieved:
        print("## Retrieved Memory")
        print("")
        for row in retrieved:
            print(f"- `{row['path']}#{row['chunk_index']}` kind=`{row['kind']}` intent=`{row['intent'] or ''}` helpful_score=`{row['helpful_score'] if row['helpful_score'] is not None else ''}`")
            if row["heading"]:
                print(f"  heading: {markdown_escape(row['heading'], 160)}")
            print(tagged_block("memory_chunk", {"path": row["path"], "chunk": row["chunk_index"]}, row["text"], args.retrieval_chars))
        print("")

    print("## Recent Timeline")
    print("")
    items = conversation_timeline(events)
    for item in items[-args.timeline :]:
        print(item)
    if not items:
        print("- None")
    return 0


__all__ = ["cmd_resume", "cmd_context", "cmd_handover", "resume_command", "local_time"]
