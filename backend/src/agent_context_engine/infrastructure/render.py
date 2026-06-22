from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

from ..adapters.sqlite.toolrefs import tool_response_ref
from .config import session_short
from .metrics import aggregate_metrics_for_events, session_metrics
from .text import markdown_escape, redact_embedded_context_artifacts, tagged_block, tool_response_summary, xml_text


def _format_dt(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def render_handover(session: sqlite3.Row, events: list[sqlite3.Row]) -> str:
    tool_events = [event for event in events if event["tool_name"]]
    last_assistant = next((event["last_assistant_message"] for event in reversed(events) if event["last_assistant_message"]), "")
    changed_files: set[str] = set()
    commands: list[str] = []
    from .db import connect

    conn = connect()
    metrics = session_metrics(conn, session["session_id"])
    for event in events:
        tool_input = event["tool_input_json"]
        if tool_input:
            try:
                parsed = json.loads(tool_input)
            except json.JSONDecodeError:
                parsed = {}
            command = parsed.get("command") if isinstance(parsed, dict) else None
            if command:
                commands.append(str(command))
            for key in ("cmd", "command", "file_path", "path"):
                value = parsed.get(key) if isinstance(parsed, dict) else None
                if isinstance(value, str):
                    for match in re.findall(r"[\w./-]+\.(?:py|js|ts|tsx|md|json|toml|sh|yml|yaml)", value):
                        changed_files.add(match)

    lines = [
        f"# Session Handover {session_short(session['session_id'])}",
        "",
        f"- Session: `{session['session_id']}`",
        f"- Client: `{session['client_type']}`",
        f"- Project: `{session['project_id'] or 'unknown'}`",
        f"- CWD: `{session['cwd'] or ''}`",
        f"- Last workdir: `{session['last_workdir'] or session['cwd'] or ''}`",
        f"- Started: `{session['started_at'] or ''}`",
        f"- Last event: `{session['last_event_at'] or ''}`",
        f"- Ended: `{session['ended_at'] or ''}`",
        f"- Events summarized: `1-{session['last_event_seq']}`",
        f"- Transcript: `{session['transcript_path'] or ''}`",
        f"- Resume: `{session['native_resume_command'] or ''}`",
        "",
        "## Metrics",
        "",
        f"- Turns: `{metrics['turns']}`",
        f"- Duration ms: `{metrics['duration_ms']}`",
        f"- Time to first token ms: `{metrics['ttft_ms']}`",
        f"- Prompt/Input tokens: `{metrics['input_tokens']}`",
        f"- Cached input tokens: `{metrics['cached_input_tokens']}`",
        f"- Completion/Output tokens: `{metrics['output_tokens']}`",
        f"- Reasoning tokens: `{metrics['reasoning_output_tokens']}`",
        f"- Total tokens: `{metrics['total_tokens']}`",
        "",
        "## Conversation Timeline",
        "",
    ]
    lines.extend(conversation_timeline(events, include_tools=False, limit=30) or ["- No user/assistant turns recorded."])

    lines += ["", "## Tool Activity", ""]
    if tool_events:
        for event in tool_events[-20:]:
            lines.append(f"- #{event['seq']} `{event['tool_name']}` `{markdown_escape(event['tool_use_id'], 120)}`")
            if event["tool_input_json"]:
                lines.append(tagged_block("tool_input", {"seq": event["seq"], "tool": event["tool_name"]}, event["tool_input_json"], 1500))
            if event["tool_response_text"]:
                ref = tool_response_ref(conn, event["session_id"], event["seq"])
                attrs = {"seq": event["seq"], "tool": event["tool_name"], "raw_output_omitted": "true"}
                if ref:
                    attrs.update({"output_id": ref.get("tool_output_id"), "status": ref.get("output_status"), "bytes": ref.get("byte_count"), "lines": ref.get("line_count")})
                lines.append(tagged_block("tool_response_ref", attrs, tool_response_summary(event["tool_response_text"]), 900))
    else:
        lines.append("- No tool activity recorded.")

    lines += ["", "## Commands", ""]
    lines.extend([f"- `{markdown_escape(command, 240)}`" for command in commands[-20:]] or ["- No shell commands recorded."])
    lines += ["", "## Files Mentioned", ""]
    lines.extend([f"- `{path}`" for path in sorted(changed_files)] or ["- No file paths detected automatically."])
    lines += ["", "## Last Assistant Message", ""]
    lines.append(tagged_block("last_assistant_message", None, last_assistant, 2500) if last_assistant else "_None recorded._")
    lines.append("")
    return "\n".join(lines)


def render_window_summary(window_id: str, start: datetime, end: datetime, grace_until: datetime, events: list[sqlite3.Row]) -> str:
    metrics = aggregate_metrics_for_events(events)
    from .db import connect
    conn = connect()
    lines = [
        f"# Summary Window {window_id}",
        "",
        f"- Window start: `{_format_dt(start)}`",
        f"- Window end: `{_format_dt(end)}`",
        f"- Grace until: `{_format_dt(grace_until)}`",
        f"- Events: `{len(events)}`",
        "",
        "## Metrics",
        "",
        f"- Sessions: `{metrics['sessions']}`",
        f"- Turns: `{metrics['turns']}`",
        f"- Duration ms: `{metrics['duration_ms']}`",
        f"- Time to first token ms: `{metrics['ttft_ms']}`",
        f"- Prompt/Input tokens: `{metrics['input_tokens']}`",
        f"- Cached input tokens: `{metrics['cached_input_tokens']}`",
        f"- Completion/Output tokens: `{metrics['output_tokens']}`",
        f"- Reasoning tokens: `{metrics['reasoning_output_tokens']}`",
        f"- Total tokens: `{metrics['total_tokens']}`",
        "",
        "## Events",
        "",
    ]
    for event in events:
        attrs = {"recorded_at": event["recorded_at"], "session_id": event["session_id"], "thread_name": event["thread_name"], "seq": event["seq"], "event": event["event_name"]}
        if event["prompt"]:
            lines.append(tagged_block("user_turn", attrs, redact_embedded_context_artifacts(event["prompt"]), 1500))
        elif event["last_assistant_message"]:
            lines.append(tagged_block("assistant_turn", attrs, redact_embedded_context_artifacts(event["last_assistant_message"]), 1800))
        elif event["tool_name"]:
            lines.append(f"<tool_turn recorded_at=\"{xml_text(event['recorded_at'])}\" session_id=\"{xml_text(event['session_id'])}\" seq=\"{event['seq']}\" tool=\"{xml_text(event['tool_name'])}\" tool_use_id=\"{xml_text(event['tool_use_id'])}\">")
            if event["tool_input_json"]:
                lines.append(tagged_block("tool_input", None, event["tool_input_json"], 1200))
            if event["tool_response_text"]:
                ref = tool_response_ref(conn, event["session_id"], event["seq"])
                attrs = {"raw_output_omitted": "true"}
                if ref:
                    attrs.update({"output_id": ref.get("tool_output_id"), "status": ref.get("output_status"), "bytes": ref.get("byte_count"), "lines": ref.get("line_count")})
                lines.append(tagged_block("tool_response_ref", attrs, tool_response_summary(event["tool_response_text"]), 800))
            lines.append("</tool_turn>")
        else:
            lines.append(tagged_block("event", attrs, event["payload_json"], 1200))
    return "\n".join(lines) + "\n"


def conversation_timeline(events: list[sqlite3.Row], *, include_tools: bool = True, limit: int | None = None) -> list[str]:
    items: list[str] = []
    from .db import connect
    conn = connect()
    for event in events:
        if event["prompt"]:
            items.append(tagged_block("user_turn", {"seq": event["seq"]}, redact_embedded_context_artifacts(event["prompt"]), 1200))
        if include_tools and event["tool_name"]:
            body_parts = []
            if event["tool_input_json"]:
                body_parts.append(tagged_block("tool_input", None, event["tool_input_json"], 1200))
            if event["tool_response_text"]:
                ref = tool_response_ref(conn, event["session_id"], event["seq"])
                attrs = {"raw_output_omitted": "true"}
                if ref:
                    attrs.update({"output_id": ref.get("tool_output_id"), "status": ref.get("output_status"), "bytes": ref.get("byte_count"), "lines": ref.get("line_count")})
                body_parts.append(tagged_block("tool_response_ref", attrs, tool_response_summary(event["tool_response_text"]), 800))
            body = "\n".join(body_parts) if body_parts else ""
            items.append(f"<tool_turn seq=\"{event['seq']}\" tool=\"{xml_text(event['tool_name'], 200)}\" tool_use_id=\"{xml_text(event['tool_use_id'], 200)}\">\n{body}\n</tool_turn>")
        if event["last_assistant_message"]:
            items.append(tagged_block("assistant_turn", {"seq": event["seq"]}, redact_embedded_context_artifacts(event["last_assistant_message"]), 1800))
    return items[-limit:] if limit is not None and limit > 0 else items
