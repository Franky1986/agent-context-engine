from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..infrastructure.config import safe_slug, utc_now
from .classifier import deterministic_classifier
from .file_access import upsert_file_accesses_for_event
from .risk import record_risk_event, scan_tool_output
from ..infrastructure.text import tool_response_summary


TOOL_RESPONSE_EVENT_SUMMARY_LIMIT = 700


def _normalize_tool_output_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def read_tool_output_text(row: sqlite3.Row | dict[str, Any]) -> str:
    content = row["content_text"] if row["content_text"] is not None else ""
    if content:
        return str(content)
    return ""


def tool_output_event_summary(value: Any) -> str | None:
    text = _normalize_tool_output_text(value)
    if text is None:
        return None
    return tool_response_summary(text, TOOL_RESPONSE_EVENT_SUMMARY_LIMIT)


def tool_output_status(value: Any) -> str:
    summary = tool_response_summary(_normalize_tool_output_text(value))
    if "tool_status=failed" in summary:
        return "failed"
    if "tool_status=empty" in summary:
        return "empty"
    return "successful"


def upsert_tool_call_and_output(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    seq: int,
    recorded_at: str,
    client_type: str,
    project_id: str | None,
    cwd: str | None = None,
    tool_name: str | None,
    tool_use_id: str | None,
    input_json: str | None,
    response_text: Any,
) -> str | None:
    if not tool_name and response_text is None and input_json is None:
        return None
    created_at = utc_now()
    tool_call_id = f"toolcall_{safe_slug(session_id)}_{seq}"
    normalized_response_text = _normalize_tool_output_text(response_text)
    status = "planned" if normalized_response_text is None else tool_output_status(normalized_response_text)
    output_id = f"toolout_{safe_slug(session_id)}_{seq}" if normalized_response_text is not None else None
    conn.execute(
        """
        insert or replace into tool_calls (
          tool_call_id, session_id, seq, recorded_at, client_type, project_id,
          tool_name, tool_use_id, status, input_json, output_id, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tool_call_id, session_id, seq, recorded_at, client_type, project_id, tool_name, tool_use_id, status, input_json, output_id, created_at),
    )
    if normalized_response_text is not None:
        encoded = normalized_response_text.encode("utf-8", errors="replace")
        output_risk = scan_tool_output(normalized_response_text)
        classified_output = deterministic_classifier(
            conn,
            stage="tool_output",
            source_kind="tool_output_text",
            payload=normalized_response_text,
            deterministic=output_risk,
            client_type=client_type,
            session_id=session_id,
            event_seq=seq,
            tool_call_id=tool_call_id,
            source_ref=output_id,
            runner="auto",
        )
        output_risk = classified_output.decision
        conn.execute(
            """
            insert or replace into tool_outputs (
              tool_output_id, tool_call_id, session_id, seq, tool_use_id,
              storage_kind, content_text, path, sha256, byte_count, char_count,
              line_count, status, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                output_id,
                tool_call_id,
                session_id,
                seq,
                tool_use_id,
                "omitted",
                None,
                None,
                hashlib.sha256(encoded).hexdigest(),
                len(encoded),
                len(normalized_response_text),
                len(normalized_response_text.splitlines()),
                status,
                created_at,
            ),
        )
        if output_risk.is_risky:
            record_risk_event(
                conn,
                output_risk,
                client_type=client_type,
                session_id=session_id,
                event_seq=seq,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                source_kind="tool_output_text",
                source_ref=output_id,
                status="quarantined" if output_risk.decision == "quarantine" else "warned",
                classifier_run_id=classified_output.run_id,
                evidence=[{"source_kind": "tool_output_text", "source_ref": output_id, "field": "tool_response", "quote": output_risk.preview}],
            )
    upsert_file_accesses_for_event(
        conn,
        session_id=session_id,
        seq=seq,
        recorded_at=recorded_at,
        client_type=client_type,
        project_id=project_id,
        cwd=cwd,
        tool_name=tool_name,
        tool_use_id=tool_use_id,
        input_json=input_json,
        status=status,
    )
    return output_id


def tool_response_ref(conn: sqlite3.Connection, session_id: str, seq: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select tc.tool_call_id, tc.tool_name, tc.tool_use_id, tc.status as call_status,
               out.tool_output_id, out.storage_kind, out.path, out.sha256,
               out.byte_count, out.char_count, out.line_count, out.status as output_status
        from tool_calls tc
        left join tool_outputs out on out.tool_output_id = tc.output_id
        where tc.session_id = ? and tc.seq = ?
        """,
        (session_id, seq),
    ).fetchone()
    return {key: row[key] for key in row.keys()} if row else None
