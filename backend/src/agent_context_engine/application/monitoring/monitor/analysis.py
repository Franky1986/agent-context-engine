from __future__ import annotations

import json
from collections import Counter
from html import escape
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from ....infrastructure.config import MEMORY_DIR, json_dumps, safe_slug
from ....adapters.serialization import local_time_text
from ....adapters.sqlite.row import row_dict as _row_dict
from ....infrastructure.db import connect, resolve_session
from ....infrastructure.metrics import session_metrics

REPORT_HTML_DIR = MEMORY_DIR / "analysis_reports"


def _safe_json_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]
    try:
        parsed = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _duration_ms(raw_started: Any, raw_finished: Any) -> int:
    started = _parse_iso(raw_started)
    finished = _parse_iso(raw_finished)
    if not started:
        return 0
    if not finished:
        return 0
    delta = finished - started
    ms = int(delta.total_seconds() * 1000)
    return ms if ms >= 0 else 0


def _topic(session: dict[str, Any], conn: Any) -> dict[str, Any]:
    if session["thread_name"]:
        return {"value": session["thread_name"], "source": "thread_name"}
    if session["session_brief"]:
        return {"value": session["session_brief"], "source": "session_brief"}
    row = conn.execute(
        """
        select prompt
        from events
        where session_id = ?
          and event_name = 'UserPromptSubmit'
          and prompt is not null and trim(prompt) != ''
        order by seq
        limit 1
        """,
        (session["session_id"],),
    ).fetchone()
    if row and row["prompt"]:
        prompt = str(row["prompt"]).strip().replace("\n", " ")[:160]
        return {"value": prompt, "source": "first_user_prompt"}
    return {"value": "-", "source": "none"}


def _collect_events(conn: Any, session_id: str) -> dict[str, Any]:
    event_rows = list(conn.execute("select * from events where session_id = ? order by seq", (session_id,)))
    by_name = Counter(row["event_name"] for row in event_rows)
    tool_events = [row for row in event_rows if row["tool_name"]]
    first_event = event_rows[0] if event_rows else None
    last_event = event_rows[-1] if event_rows else None
    return {
        "total": len(event_rows),
        "first_seq": event_rows[0]["seq"] if event_rows else 0,
        "last_seq": event_rows[-1]["seq"] if event_rows else 0,
        "first_event_at": first_event["recorded_at"] if first_event else None,
        "last_event_at": last_event["recorded_at"] if last_event else None,
        "by_name": dict(by_name),
        "tool_events": len(tool_events),
    }


def _collect_tool_and_output(conn: Any, session_id: str) -> dict[str, Any]:
    tool_calls = list(conn.execute("select status, count(*) as count from tool_calls where session_id = ? group by status", (session_id,)))
    outputs = conn.execute("select count(*) as c from tool_outputs where session_id = ?", (session_id,)).fetchone()["c"]
    file_accesses = conn.execute("select count(*) as c from file_accesses where session_id = ?", (session_id,)).fetchone()["c"]
    return {
        "calls_by_status": {row["status"]: int(row["count"]) for row in tool_calls},
        "outputs": int(outputs),
        "file_accesses": int(file_accesses),
    }


def _collect_graph_entities(conn: Any, session_id: str, limit: int, offset: int, include_rows: bool) -> dict[str, Any]:
    type_rows = [
        {
            "type": row["type"],
            "count": int(row["item_count"]),
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
        }
        for row in conn.execute(
            """
            select type, count(*) as item_count,
                   min(first_seen_at) as first_seen_at, max(last_seen_at) as last_seen_at
            from graph_entities
            where session_id = ?
            group by type
            order by count(*) desc, type
            """,
            (session_id,),
        )
    ]
    entities = []
    if include_rows:
        if limit <= 0:
            rows = conn.execute(
                """
                select ge.*
                from graph_entities ge
                where ge.session_id = ?
                order by ge.last_seen_at desc, ge.first_seen_at desc
                """,
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select ge.*
                from graph_entities ge
                where ge.session_id = ?
                order by ge.last_seen_at desc, ge.first_seen_at desc
                limit ? offset ?
                """,
                (session_id, limit, offset),
            ).fetchall()
        for row in rows:
            entity = _row_dict(row)
            entity_id = entity["entity_id"]
            entity["evidence_count"] = int(
                conn.execute(
                    "select count(*) as c from graph_evidence where owner_type = 'entity' and owner_id = ?",
                    (entity_id,),
                ).fetchone()["c"]
            )
            entity["out_relation_count"] = int(
                conn.execute(
                    "select count(*) as c from graph_relations where from_entity_id = ?",
                    (entity_id,),
                ).fetchone()["c"]
            )
            entity["in_relation_count"] = int(
                conn.execute(
                    "select count(*) as c from graph_relations where to_entity_id = ?",
                    (entity_id,),
                ).fetchone()["c"]
            )
            entity["relation_count"] = entity["out_relation_count"] + entity["in_relation_count"]
            entity["aliases"] = _safe_json_list(entity.get("aliases_json"))
            entities.append(entity)
    total = int(conn.execute("select count(*) as c from graph_entities where session_id = ?", (session_id,)).fetchone()["c"])
    return {"total": total, "types": type_rows, "items": entities}


def _collect_graph_relations(conn: Any, session_id: str, limit: int, offset: int, include_rows: bool) -> dict[str, Any]:
    type_rows = [
        {
            "type": row["relation_type"],
            "count": int(row["item_count"]),
            "first_seen_at": row["first_seen_at"],
            "last_seen_at": row["last_seen_at"],
        }
        for row in conn.execute(
            """
            select relation_type, count(*) as item_count,
                   min(first_seen_at) as first_seen_at, max(last_seen_at) as last_seen_at
            from graph_relations gr
            where gr.session_id = ?
            group by relation_type
            order by count(*) desc, relation_type
            """,
            (session_id,),
        )
    ]
    relations = []
    if include_rows:
        if limit <= 0:
            rows = conn.execute(
                """
                select gr.*,
                       f.name as from_name, f.type as from_type, f.key as from_key,
                       t.name as to_name, t.type as to_type, t.key as to_key
                from graph_relations gr
                left join graph_entities f on f.entity_id = gr.from_entity_id
                left join graph_entities t on t.entity_id = gr.to_entity_id
                where gr.session_id = ?
                order by gr.last_seen_at desc, gr.first_seen_at desc
                """,
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                select gr.*,
                       f.name as from_name, f.type as from_type, f.key as from_key,
                       t.name as to_name, t.type as to_type, t.key as to_key
                from graph_relations gr
                left join graph_entities f on f.entity_id = gr.from_entity_id
                left join graph_entities t on t.entity_id = gr.to_entity_id
                where gr.session_id = ?
                order by gr.last_seen_at desc, gr.first_seen_at desc
                limit ? offset ?
                """,
                (session_id, limit, offset),
            ).fetchall()
        for row in rows:
            relation = _row_dict(row)
            relation_id = relation["relation_id"]
            relation["evidence_count"] = int(
                conn.execute(
                    "select count(*) as c from graph_evidence where owner_type = 'relation' and owner_id = ?",
                    (relation_id,),
                ).fetchone()["c"]
            )
            relations.append(relation)
    total = int(
        conn.execute("select count(*) as c from graph_relations where session_id = ?", (session_id,)).fetchone()["c"]
    )
    return {"total": total, "types": type_rows, "items": relations}


def build_session_analysis_report(
    conn: Any,
    session_id: str,
    *,
    include_entities: bool = True,
    include_relations: bool = True,
    include_risks: bool = True,
    entity_limit: int = 25,
    relation_limit: int = 25,
    relation_offset: int = 0,
    entity_offset: int = 0,
    dream_limit: int = 5,
    risk_limit: int = 10,
    firewall_limit: int = 20,
) -> dict[str, Any]:
    session = conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
    if session is None:
        raise ValueError(f"session not found: {session_id}")

    session_row = _row_dict(session)
    event_profile = _collect_events(conn, session_id)
    tool_profile = _collect_tool_and_output(conn, session_id)
    metrics = session_metrics(conn, session_id)
    graph_entities = _collect_graph_entities(
        conn,
        session_id,
        limit=entity_limit,
        offset=entity_offset,
        include_rows=include_entities,
    )
    graph_relations = _collect_graph_relations(
        conn,
        session_id,
        limit=relation_limit,
        offset=relation_offset,
        include_rows=include_relations,
    )
    dreams = _collect_dreams(conn, session_id, limit=dream_limit)
    risks = _collect_risks(
        conn,
        session_id,
        limit=risk_limit,
        include_rows=include_risks,
    )
    firewall = _collect_firewall(conn, session_id, limit=firewall_limit)
    topic = _topic(session_row, conn)
    graph = {"entities_total": graph_entities["total"], "relations_total": graph_relations["total"]}
    quality = _quality_indicator(session_row, event_profile, metrics, graph, dreams, risks)
    top_terms = _collect_dominant_topic_terms(conn, session_id)

    return {
        "session": {
            "id": session_id,
            "client": session_row["client_type"],
            "project": session_row["project_id"] or "-",
            "workdir": session_row["last_workdir"] or session_row["cwd"] or "-",
            "status": session_row["status"],
            "summary_status": session_row["summary_status"],
            "dream_status": session_row["dream_status"],
            "started_at": session_row["started_at"],
            "ended_at": session_row["ended_at"],
            "last_event_at": session_row["last_event_at"],
            "last_event_seq": int(session_row["last_event_seq"] or 0),
            "new_events_since_summary": int(session_row["last_event_seq"]) - int(session_row["last_summary_event_seq"]),
            "new_events_since_dream": int(session_row["last_event_seq"]) - int(session_row["last_dream_event_seq"]),
            "thread_name": session_row["thread_name"] or "",
            "session_brief": session_row["session_brief"] or "",
            "native_resume_command": session_row["native_resume_command"] or "",
        },
        "topic": topic,
        "events": {
            "total": event_profile["total"],
            "first_seq": event_profile["first_seq"],
            "last_seq": event_profile["last_seq"],
            "first_event_at": local_time_text(event_profile["first_event_at"]),
            "last_event_at": local_time_text(event_profile["last_event_at"]),
            "event_counts": event_profile["by_name"],
            "tool_events": event_profile["tool_events"],
            "tool": tool_profile,
        },
        "metrics": metrics,
        "topics_preview": top_terms,
        "entities": graph_entities,
        "relations": graph_relations,
        "dreams": dreams,
        "risks": risks,
        "firewall": firewall,
        "quality": quality,
    }


def _collect_dreams(conn: Any, session_id: str, limit: int = 5) -> dict[str, Any]:
    rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            select *
            from dream_runs
            where session_id = ?
            order by coalesce(finished_at, started_at) desc
            limit ?
            """,
            (session_id, limit),
        )
    ]
    for row in rows:
        row["duration_ms"] = int(_duration_ms(row.get("started_at"), row.get("finished_at")))
        row["input_event_count"] = int(row["input_event_count"] or 0)
        row["helpful_score"] = row["helpful_score"]
    return {
        "count": len(rows),
        "items": rows,
    }


def _collect_risks(conn: Any, session_id: str, limit: int, include_rows: bool) -> dict[str, Any]:
    rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            select *
            from risk_events
            where session_id = ?
            order by created_at desc
            """,
            (session_id,),
        )
    ]
    status = Counter(row["status"] for row in rows)
    decision = Counter(row["decision"] for row in rows)
    by_level = Counter(row["risk_level"] or "-" for row in rows)
    return {
        "total": len(rows),
        "statuses": dict(status),
        "decisions": dict(decision),
        "levels": dict(by_level),
        "items": rows[:limit] if include_rows else [],
    }


def _collect_firewall(conn: Any, session_id: str, limit: int) -> dict[str, Any]:
    rules = [_row_dict(row) for row in conn.execute(
        """
        select rule_id, family_id, version, name, status, scope_type, rule_kind, workdir_prefix, session_id,
               created_at, updated_at, expires_at, reason, source_line
        from firewall_rules
        where created_from_session_id = ?
        order by updated_at desc
        limit ?
        """,
        (session_id, limit),
    )]
    overrides = [_row_dict(row) for row in conn.execute(
        """
        select *
        from firewall_overrides
        where session_id = ?
        order by created_at desc
        limit ?
        """,
        (session_id, limit),
    )]
    taint_resets = int(conn.execute("select count(*) as c from session_taint_resets where session_id = ?", (session_id,)).fetchone()["c"])
    intent_count = int(conn.execute("select count(*) as c from firewall_intent_approvals where session_id = ?", (session_id,)).fetchone()["c"])
    return {
        "rules_from_session": rules,
        "overrides": overrides,
        "session_taint_resets": taint_resets,
        "intent_approvals": intent_count,
    }


def _collect_dominant_topic_terms(conn: Any, session_id: str) -> list[str]:
    rows = conn.execute(
        """
        select event_name, prompt
        from events
        where session_id = ? and event_name = 'UserPromptSubmit' and prompt is not null and trim(prompt) != ''
        order by seq desc
        limit 4
        """,
        (session_id,),
    ).fetchall()
    terms = []
    for row in rows:
        text = str(row["prompt"]).strip()
        if text:
            terms.append(text[:80])
    return terms


def _to_local_or_dash(value: Any) -> str:
    return value if value not in (None, "") else "-"


def _format_html_rows(rows: list[dict[str, Any]], columns: list[str], default: str = "-") -> str:
    header = "".join(f"<th>{escape(col.replace('_', ' ').title())}</th>" for col in columns)
    body_lines = []
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col)
            if isinstance(value, (list, tuple)):
                text = ", ".join(str(item) for item in value) if value else default
            else:
                text = "-" if value is None or value == "" else str(value)
            cells.append(f"<td>{escape(text)}</td>")
        body_lines.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<table><thead><tr>"
        f"{header}"
        "</tr></thead><tbody>"
        + ("".join(body_lines) if body_lines else f"<tr><td colspan=\"{len(columns)}\">No data</td></tr>")
        + "</tbody></table>"
    )


def _build_analyze_report_html(report: dict[str, Any]) -> str:
    entities = report["entities"]
    relations = report["relations"]
    dreams = report["dreams"]["items"]
    risks = report["risks"]["items"]
    firewall = report["firewall"]

    entity_types = entities["types"]
    relation_types = relations["types"]
    entity_rows = [
        {
            "type": row["type"],
            "name": row["name"],
            "key": row["key"],
            "confidence": row.get("confidence"),
            "first_seen_at": _to_local_or_dash(row.get("first_seen_at")),
            "last_seen_at": _to_local_or_dash(row.get("last_seen_at")),
            "evidence_count": row.get("evidence_count"),
            "relation_count": row.get("relation_count"),
            "risk_level": row.get("risk_level"),
            "sensitivity": row.get("sensitivity"),
            "injection_policy": row.get("injection_policy"),
            "session_id": row.get("session_id"),
        }
        for row in entities["items"]
    ]

    relation_rows = [
        {
            "relation_type": row["relation_type"],
            "from": f"{row.get('from_name') or row.get('from_entity_id')} ({row.get('from_type', '-')})",
            "to": f"{row.get('to_name') or row.get('to_entity_id')} ({row.get('to_type', '-')})",
            "confidence": row.get("confidence"),
            "first_seen_at": _to_local_or_dash(row.get("first_seen_at")),
            "last_seen_at": _to_local_or_dash(row.get("last_seen_at")),
            "evidence_count": row.get("evidence_count"),
            "session_id": row.get("session_id"),
            "artifact_id": row.get("artifact_id"),
        }
        for row in relations["items"]
    ]

    firewall_rules = firewall["rules_from_session"]
    firewall_overrides = firewall["overrides"]

    section_entities = _format_html_rows(
        [
            {"type": row["type"], "count": row["count"], "first_seen_at": row["first_seen_at"], "last_seen_at": row["last_seen_at"]}
            for row in entity_types
        ],
        ["type", "count", "first_seen_at", "last_seen_at"],
    )
    section_relations = _format_html_rows(
        [
            {"type": row["type"], "count": row["count"], "first_seen_at": row["first_seen_at"], "last_seen_at": row["last_seen_at"]}
            for row in relation_types
        ],
        ["type", "count", "first_seen_at", "last_seen_at"],
    )

    section_entities_items = _format_html_rows(
        entity_rows,
        ["type", "name", "key", "first_seen_at", "last_seen_at", "confidence", "evidence_count", "relation_count", "risk_level", "sensitivity"],
    )
    section_relation_items = _format_html_rows(
        relation_rows,
        ["relation_type", "from", "to", "confidence", "first_seen_at", "last_seen_at", "evidence_count", "session_id", "artifact_id"],
    )

    section_dreams = "".join(
        f"<div>{escape(row['dream_run_id'])}: {escape(row['status'])} · {escape(str(row['input_event_count']))} events · "
        f"duration {escape(str(row['duration_ms']))} ms · started {escape(str(row['started_at']))}</div>"
        for row in dreams
    ) or "<em>No dream runs</em>"

    section_risks = "".join(
        f"<div>{escape(row['risk_event_id'])}: {escape(row['status'])} · {escape(str(row['decision']))} · "
        f"event {escape(str(row['event_seq']))} · {escape(row['created_at'])}</div>"
        for row in risks
    ) or "<em>No risk events</em>"

    section_firewall = _format_html_rows(
        [
            {
                "rule_id": row["rule_id"],
                "name": row["name"],
                "status": row["status"],
                "scope_type": row["scope_type"],
                "rule_kind": row["rule_kind"],
                "expires_at": row["expires_at"],
                "reason": row["reason"],
                "source_line": row["source_line"],
            }
            for row in firewall_rules
        ],
        ["rule_id", "name", "status", "scope_type", "rule_kind", "expires_at", "reason", "source_line"],
    )
    section_overrides = _format_html_rows(
        [
            {
                "override_id": row["override_id"],
                "scope_type": row["scope_type"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "enabled": row["enabled"],
                "reason": row["reason"],
                "source": row["source"],
            }
            for row in firewall_overrides
        ],
        ["override_id", "scope_type", "created_at", "expires_at", "enabled", "reason", "source"],
        default="-",
    )

    session = report["session"]
    topic = report["topic"]
    quality = report["quality"]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Session Analysis {escape(session['id'])}</title>
  <style>
    :root {{
      font-family: Arial, Helvetica, sans-serif;
      background: #0f1114;
      color: #ebedf0;
    }}
    body {{ margin: 24px; max-width: 1200px; color: #ebedf0; }}
    h1, h2 {{ margin: 0 0 10px; }}
    section {{ margin: 24px 0; padding: 16px; border: 1px solid #2a2f37; border-radius: 8px; background: #171a20; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; }}
    th, td {{ border: 1px solid #2a2f37; padding: 8px; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #1f232b; position: sticky; top: 0; }}
    .meta {{ color: #b5bfd0; font-size: 13px; line-height: 1.4; }}
    .pill {{ display: inline-block; background: #233046; padding: 2px 8px; border-radius: 999px; margin-right: 6px; font-size: 12px; }}
    details pre {{ max-height: 240px; overflow: auto; background: #0b0d10; padding: 8px; border-radius: 6px; }}
  </style>
</head>
<body>
  <h1>Session Analysis Report</h1>
  <div class="meta">Session: {escape(session['id'])} · Client: {escape(session['client'])} · Project: {escape(session['project'])}</div>
  <div class="meta">Start: {escape(str(session['started_at']))} · End: {escape(str(session['ended_at']))}</div>
  <div class="meta">Topic [{escape(topic['source'])}]: {escape(topic['value'])}</div>
  <div class="meta">
    <span class="pill">Entities total: {escape(str(entities['total']))}</span>
    <span class="pill">Relations total: {escape(str(relations['total']))}</span>
    <span class="pill">Risks: {escape(str(report['risks']['total']))}</span>
    <span class="pill">Dreams: {escape(str(report['dreams']['count']))}</span>
  </div>
  <div class="meta">
    <span class="pill">Quality score: {escape(str(quality['score']))}</span>
    <span class="pill">Blocked: {escape(str(quality['blocked_tool_events']))}</span>
    <span class="pill">Warned: {escape(str(quality['warned_tool_events']))}</span>
  </div>
  <section>
    <h2>Graph: Entity Types</h2>
    {section_entities}
  </section>
  <section>
    <h2>Graph: Relation Types</h2>
    {section_relations}
  </section>
  <section>
    <h2>Created Entities</h2>
    {section_entities_items}
    <div class="meta">Showing {escape(str(len(entities['items'])))} of {escape(str(entities['total']))} entities.</div>
  </section>
  <section>
    <h2>Created Relations</h2>
    {section_relation_items}
    <div class="meta">Showing {escape(str(len(relations['items'])))} of {escape(str(relations['total']))} relations.</div>
  </section>
  <section>
    <h2>Dream Runs</h2>
    {section_dreams}
  </section>
  <section>
    <h2>Risk Events</h2>
    {section_risks}
  </section>
  <section>
    <h2>Firewall: Session Rules</h2>
    {section_firewall}
    <h3>Scoped Overrides</h3>
    {section_overrides}
    <div class="meta">Taint Resets: {escape(str(firewall['session_taint_resets']))}, Intent Approvals: {escape(str(firewall['intent_approvals']))}</div>
  </section>
  <section>
    <h2>Quality Notes</h2>
    {''.join(f'<div>• {escape(item)}</div>' for item in quality['issues']) or '<em>No quality issues</em>'}
  </section>
  <section>
    <h2>Technical Details (JSON)</h2>
    <details>
      <summary>Show complete analysis report</summary>
      <pre>{escape(json_dumps(report))}</pre>
    </details>
  </section>
</body>
</html>"""


def write_session_analysis_report_html(report: dict[str, Any], session_id: str) -> Path:
    REPORT_HTML_DIR.mkdir(parents=True, exist_ok=True)
    safe_session = safe_slug(session_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = REPORT_HTML_DIR / f"analysis_{safe_session}_{timestamp}.html"
    content = _build_analyze_report_html(report)
    path.write_text(content, encoding="utf-8")
    return path


def _quality_indicator(session: dict[str, Any], events: dict[str, Any], metrics: dict[str, Any], graph: dict[str, Any], dreams: dict[str, Any], risks: dict[str, Any]) -> dict[str, Any]:
    score = 100
    issues: list[str] = []
    if events["total"] == 0:
        score -= 60
        issues.append("No events recorded")
    if metrics["turns"] == 0 and events["total"] > 0:
        score -= 20
        issues.append("No parsed turn metrics available")
    if session["dream_status"] != "dreamed":
        score -= 20
        issues.append("Dream not completed for latest window")
    if dreams["count"] == 0 and events["total"] > 0:
        issues.append("No dream runs for this session")
    blocked = risks["statuses"].get("blocked", 0)
    required = risks["statuses"].get("required", 0)
    if blocked:
        deduction = min(25, blocked * 7)
        score -= deduction
        issues.append(f"{blocked} blocked risk events")
    if required:
        score -= min(10, required * 3)
        issues.append(f"{required} required approvals")
    if graph["entities_total"] == 0 and graph["relations_total"] == 0 and events["tool_events"] > 0:
        score -= 10
        issues.append("No graph artifacts for tool activity")
    if session["summary_status"] != "summarized":
        score -= 10
        issues.append("Summary not up-to-date")
    return {
        "score": max(0, min(100, score)),
        "issues": issues,
        "blocked_tool_events": risks["statuses"].get("blocked", 0),
        "warned_tool_events": risks["statuses"].get("warned", 0),
        "required_tool_events": risks["statuses"].get("required", 0),
    }


def build_session_analysis_report_for_selector(
    selector: str,
    *,
    include_entities: bool = True,
    include_relations: bool = True,
    include_risks: bool = True,
    entity_limit: int = 25,
    relation_limit: int = 25,
    relation_offset: int = 0,
    entity_offset: int = 0,
    dream_limit: int = 5,
    risk_limit: int = 10,
    firewall_limit: int = 20,
) -> tuple[dict[str, Any], str]:
    """Return an analysis report for a session selector and the resolved session id."""
    conn = connect()
    try:
        session = resolve_session(conn, selector)
        if session is None:
            raise ValueError(f"session not found: {selector}")
        report = build_session_analysis_report(
            conn,
            session["session_id"],
            include_entities=include_entities,
            include_relations=include_relations,
            include_risks=include_risks,
            entity_limit=entity_limit,
            relation_limit=relation_limit,
            relation_offset=relation_offset,
            entity_offset=entity_offset,
            dream_limit=dream_limit,
            risk_limit=risk_limit,
            firewall_limit=firewall_limit,
        )
        return report, session["session_id"]
    finally:
        conn.close()


__all__ = [
    "build_session_analysis_report",
    "build_session_analysis_report_for_selector",
    "write_session_analysis_report_html",
]
