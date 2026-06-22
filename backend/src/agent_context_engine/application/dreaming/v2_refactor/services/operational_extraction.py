"""Operational extraction service extracted from `v2.py`.

This module isolates SQL-side extraction of operational evidence from the v2
orchestration flow while preserving existing payload and behavior contracts.
"""

from __future__ import annotations

from typing import Any


def extract_operational_facts(
    conn,
    dream_run_id: str,
    session_id: str,
    event_from: int,
    event_to: int,
    *,
    safe_slug_fn,
    now_fn,
    json_dumps_fn,
) -> dict[str, Any]:
    """Extract file-write and pre-tool operational facts and persist them."""

    now = now_fn()
    facts: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        select *
        from file_accesses
        where session_id = ? and seq between ? and ?
          and operation in ('write', 'delete', 'patch', 'mkdir')
        order by seq
        """,
        (session_id, event_from, event_to),
    ):
        fact_id = f"opfact_{safe_slug_fn(dream_run_id)}_{row['seq']}_{safe_slug_fn(row['operation'])}_{safe_slug_fn(row['path_key'])}"
        fact = {
            "event_seq": row["seq"],
            "fact_kind": "file_change",
            "fact_key": row["path_key"],
            "operation": row["operation"],
            "subject": row["path_raw"],
            "status": row["status"],
        }
        facts.append(fact)
        conn.execute(
            """
            insert or replace into operational_facts (
              operational_fact_id, session_id, dream_run_id, event_seq, fact_kind,
              fact_key, operation, subject, status, properties_json, evidence_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fact_id,
                session_id,
                dream_run_id,
                row["seq"],
                "file_change",
                row["path_key"],
                row["operation"],
                row["path_raw"],
                row["status"],
                json_dumps_fn({"tool_name": row["tool_name"], "tool_use_id": row["tool_use_id"]}),
                json_dumps_fn([{"event_seq": row["seq"], "quote": row["evidence_quote"]}]),
                now,
            ),
        )

    pretools: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        select e.session_id, e.seq, e.tool_name, e.tool_use_id, tc.tool_call_id,
               re.risk_event_id, re.status, re.decision, re.approval_state,
               re.command_hash, re.preview
        from events e
        left join tool_calls tc on tc.session_id = e.session_id and tc.seq = e.seq
        left join risk_events re on re.session_id = e.session_id and re.event_seq = e.seq
        where e.session_id = ? and e.seq between ? and ? and e.event_name = 'PreToolUse'
        order by e.seq
        """,
        (session_id, event_from, event_to),
    ):
        ref_id = f"pretool_{safe_slug_fn(session_id)}_{row['seq']}_{safe_slug_fn(row['tool_use_id'] or '')}"
        pretool = dict(row)
        pretools.append(pretool)
        conn.execute(
            """
            insert or replace into pretool_audit_refs (
              pretool_audit_ref_id, session_id, dream_run_id, event_seq,
              tool_call_id, tool_name, tool_use_id, risk_event_id, status,
              decision, approval_state, command_hash, redacted_preview, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ref_id,
                session_id,
                dream_run_id,
                row["seq"],
                row["tool_call_id"],
                row["tool_name"],
                row["tool_use_id"],
                row["risk_event_id"],
                row["status"] or "observed",
                row["decision"],
                row["approval_state"],
                row["command_hash"],
                row["preview"],
                now,
            ),
        )

    return {"operational_facts": facts, "pretool_audit_refs": pretools}
