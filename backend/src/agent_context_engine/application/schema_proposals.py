from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from difflib import SequenceMatcher
from typing import Any

from ..infrastructure.config import json_dumps, utc_now
from ..infrastructure.db import connect


OPEN_STATUSES = {"pending", "reviewed"}
FINAL_STATUSES = {"approved", "rejected", "merged", "promoted"}
VALID_KINDS = {"entity_type", "relation_type", "alias", "merge"}


def _stable_hash(value: Any, length: int = 24) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()[:length]


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    for key in ("examples_json", "evidence_json"):
        data[key.removesuffix("_json")] = _json_list(data.pop(key, "[]"))
    data["review"] = _json_dict(data.pop("review_json", "{}"))
    return data


def _proposal_before(conn: sqlite3.Connection, proposal_id: str) -> dict[str, Any] | None:
    return _row_dict(conn.execute("select * from schema_proposals where proposal_id = ?", (proposal_id,)).fetchone())


def _audit(
    conn: sqlite3.Connection,
    *,
    proposal_id: str,
    action: str,
    actor: str | None,
    reason: str | None,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    conn.execute(
        """
        insert into schema_proposal_audit (
          audit_id, proposal_id, action, actor, reason, before_json, after_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"audit_{_stable_hash({'proposal_id': proposal_id, 'action': action, 'at': utc_now(), 'after': after})}",
            proposal_id,
            action,
            actor,
            reason,
            json_dumps(before or {}),
            json_dumps(after or {}),
            utc_now(),
        ),
    )


def create_schema_proposal(
    conn: sqlite3.Connection,
    *,
    kind: str,
    proposed_name: str,
    canonical_name: str | None = None,
    confidence: float | None = None,
    reason: str | None = None,
    examples: list[Any] | None = None,
    evidence: list[Any] | None = None,
    proposed_by: str | None = None,
    source_session_id: str | None = None,
    source_dream_run_id: str | None = None,
    source_graph_artifact_id: str | None = None,
) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        raise ValueError(f"unsupported schema proposal kind: {kind}")
    name = proposed_name.strip()
    if not name:
        raise ValueError("proposed_name must not be empty")
    existing = conn.execute(
        """
        select * from schema_proposals
        where kind = ?
          and lower(proposed_name) = lower(?)
          and status in ('pending', 'reviewed', 'approved', 'promoted')
        order by created_at desc
        limit 1
        """,
        (kind, name),
    ).fetchone()
    if existing:
        return _row_dict(existing) or {}

    now = utc_now()
    proposal_id = f"schema_prop_{_stable_hash({'kind': kind, 'name': name, 'created_at': now})}"
    with conn:
        conn.execute(
            """
            insert into schema_proposals (
              proposal_id, kind, proposed_name, canonical_name, status, confidence,
              reason, examples_json, evidence_json, review_json, proposed_by,
              source_session_id, source_dream_run_id, source_graph_artifact_id,
              created_at, updated_at
            ) values (?, ?, ?, ?, 'pending', ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal_id,
                kind,
                name,
                canonical_name,
                confidence,
                reason,
                json_dumps(examples or []),
                json_dumps(evidence or []),
                proposed_by,
                source_session_id,
                source_dream_run_id,
                source_graph_artifact_id,
                now,
                now,
            ),
        )
        after = _proposal_before(conn, proposal_id)
        _audit(conn, proposal_id=proposal_id, action="created", actor=proposed_by, reason=reason, before=None, after=after)
    return after or {}


def list_schema_proposals(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    sql = "select * from schema_proposals"
    if clauses:
        sql += " where " + " and ".join(clauses)
    sql += " order by updated_at desc limit ?"
    params.append(limit)
    return [_row_dict(row) or {} for row in conn.execute(sql, params)]


def list_schema_registry(conn: sqlite3.Connection, *, kind: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    params: list[Any] = []
    sql = "select * from graph_schema_registry"
    if kind:
        sql += " where kind = ?"
        params.append(kind)
    sql += " order by kind, name limit ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]


def _existing_type_counts(conn: sqlite3.Connection, kind: str) -> list[dict[str, Any]]:
    if kind == "relation_type":
        rows = conn.execute("select relation_type as name, count(*) as count from graph_relations group by relation_type").fetchall()
    else:
        rows = conn.execute("select type as name, count(*) as count from graph_entities group by type").fetchall()
    return [dict(row) for row in rows]


def review_schema_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    *,
    actor: str = "deterministic:schema-review",
) -> dict[str, Any]:
    before = _proposal_before(conn, proposal_id)
    if not before:
        raise ValueError(f"schema proposal not found: {proposal_id}")

    from .graphing.schema import ALLOWED_ENTITY_TYPES, ALLOWED_RELATION_TYPES

    kind = before["kind"]
    proposed = before["proposed_name"]
    allowed = ALLOWED_RELATION_TYPES if kind == "relation_type" else ALLOWED_ENTITY_TYPES
    existing_counts = _existing_type_counts(conn, kind)
    existing_names = [row["name"] for row in existing_counts]
    count_by_name = {row["name"].lower(): row["count"] for row in existing_counts}
    proposed_lower = proposed.lower()
    registry = conn.execute(
        "select * from graph_schema_registry where kind = ? and lower(name) = lower(?)",
        (kind, proposed),
    ).fetchone()
    similar = sorted(
        (
            {
                "name": name,
                "score": round(SequenceMatcher(None, proposed_lower, name.lower()).ratio(), 3),
                "count": count_by_name.get(name.lower(), 0),
            }
            for name in set(existing_names) | set(allowed)
            if name.lower() != proposed_lower
        ),
        key=lambda item: item["score"],
        reverse=True,
    )[:8]
    close_matches = [item for item in similar if item["score"] >= 0.82]
    historical_mentions = conn.execute(
        """
        select count(*) as count
        from graph_entities
        where lower(name) like ? or lower(key) like ? or lower(coalesce(properties_json, '')) like ?
        """,
        (f"%{proposed_lower}%", f"%{proposed_lower}%", f"%{proposed_lower}%"),
    ).fetchone()["count"]
    already_allowed = proposed in allowed
    already_materialized = proposed_lower in count_by_name
    if already_allowed or already_materialized or registry:
        recommendation = "merge"
        recommendation_reason = "type already exists in allowed schema, materialized graph, or dynamic registry"
    elif close_matches:
        recommendation = "merge"
        recommendation_reason = "similar historical schema names found"
    elif historical_mentions > 0 or before["examples"] or before["evidence"]:
        recommendation = "approve"
        recommendation_reason = "new type has examples, evidence, or historical mentions"
    else:
        recommendation = "needs_evidence"
        recommendation_reason = "no historical evidence found yet"
    review = {
        "kind": kind,
        "proposed_name": proposed,
        "already_allowed": already_allowed,
        "already_materialized": already_materialized,
        "existing_registry": dict(registry) if registry else None,
        "historical_mentions": historical_mentions,
        "similar": similar,
        "recommendation": recommendation,
        "recommendation_reason": recommendation_reason,
        "reviewed_at": utc_now(),
    }
    now = utc_now()
    with conn:
        conn.execute(
            """
            update schema_proposals
            set status = case when status = 'pending' then 'reviewed' else status end,
                review_json = ?,
                reviewed_at = ?,
                reviewer = ?,
                updated_at = ?
            where proposal_id = ?
            """,
            (json_dumps(review), now, actor, now, proposal_id),
        )
        after = _proposal_before(conn, proposal_id)
        _audit(conn, proposal_id=proposal_id, action="reviewed", actor=actor, reason=recommendation_reason, before=before, after=after)
    return after or {}


def decide_schema_proposal(
    conn: sqlite3.Connection,
    proposal_id: str,
    *,
    action: str,
    actor: str = "manual",
    reason: str | None = None,
    canonical_name: str | None = None,
) -> dict[str, Any]:
    if action not in FINAL_STATUSES:
        raise ValueError(f"unsupported schema proposal decision: {action}")
    before = _proposal_before(conn, proposal_id)
    if not before:
        raise ValueError(f"schema proposal not found: {proposal_id}")
    if before["status"] in FINAL_STATUSES and before["status"] != action:
        raise ValueError(f"proposal is already final: {before['status']}")
    now = utc_now()
    registry_name = canonical_name or before["canonical_name"] or before["proposed_name"]
    with conn:
        if action in {"approved", "promoted"}:
            schema_item_id = f"schema_{_stable_hash({'kind': before['kind'], 'name': registry_name.lower()})}"
            conn.execute(
                """
                insert into graph_schema_registry (
                  schema_item_id, kind, name, status, canonical_name,
                  created_from_proposal_id, reason, created_at, updated_at
                ) values (?, ?, ?, 'active', ?, ?, ?, ?, ?)
                on conflict(kind, name) do update set
                  status = 'active',
                  canonical_name = excluded.canonical_name,
                  reason = excluded.reason,
                  updated_at = excluded.updated_at
                """,
                (
                    schema_item_id,
                    before["kind"],
                    registry_name,
                    canonical_name,
                    proposal_id,
                    reason,
                    now,
                    now,
                ),
            )
        conn.execute(
            """
            update schema_proposals
            set status = ?,
                canonical_name = coalesce(?, canonical_name),
                decision_reason = ?,
                reviewed_at = coalesce(reviewed_at, ?),
                reviewer = ?,
                updated_at = ?
            where proposal_id = ?
            """,
            (action, canonical_name, reason, now, actor, now, proposal_id),
        )
        after = _proposal_before(conn, proposal_id)
        _audit(conn, proposal_id=proposal_id, action=action, actor=actor, reason=reason, before=before, after=after)
    return after or {}


def ingest_graph_schema_proposals(
    conn: sqlite3.Connection,
    patch: dict[str, Any],
    *,
    artifact_id: str,
    session_id: str | None,
    dream_run_id: str | None,
) -> list[dict[str, Any]]:
    created: list[dict[str, Any]] = []
    for entity in patch.get("entities", []):
        if entity.get("type") != "SchemaProposal":
            continue
        props = entity.get("properties") or {}
        proposed_name = str(props.get("proposed_name") or props.get("name") or entity.get("name") or entity.get("key") or "").strip()
        if not proposed_name:
            continue
        proposal = create_schema_proposal(
            conn,
            kind=str(props.get("kind") or "entity_type"),
            proposed_name=proposed_name,
            canonical_name=props.get("canonical_name"),
            confidence=entity.get("confidence"),
            reason=props.get("reason"),
            examples=_json_list(props.get("examples")),
            evidence=entity.get("evidence") or [],
            proposed_by=str(props.get("proposed_by") or "dream"),
            source_session_id=session_id,
            source_dream_run_id=dream_run_id,
            source_graph_artifact_id=artifact_id,
        )
        created.append(proposal)
    return created


def cmd_schema_proposals(args: argparse.Namespace) -> int:
    conn = connect()
    if args.schema_command == "list":
        rows = list_schema_proposals(conn, status=args.status, kind=args.kind, limit=args.limit)
        if args.json:
            print(json_dumps(rows))
        elif not rows:
            print("No schema proposals found.")
        else:
            for row in rows:
                print(f"{row['updated_at']} {row['status']} {row['kind']} {row['proposed_name']} id={row['proposal_id']}")
                if row.get("reason"):
                    print(f"  reason={row['reason']}")
                recommendation = (row.get("review") or {}).get("recommendation")
                if recommendation:
                    print(f"  recommendation={recommendation}")
        return 0
    if args.schema_command == "create":
        proposal = create_schema_proposal(
            conn,
            kind=args.kind,
            proposed_name=args.proposed_name,
            canonical_name=args.canonical_name,
            confidence=args.confidence,
            reason=args.reason,
            examples=args.example or [],
            proposed_by=args.actor,
        )
        print(json_dumps(proposal) if args.json else f"{proposal['proposal_id']} {proposal['status']} {proposal['kind']} {proposal['proposed_name']}")
        return 0
    if args.schema_command == "review":
        proposal = review_schema_proposal(conn, args.proposal_id, actor=args.actor)
        print(json_dumps(proposal) if args.json else f"{proposal['proposal_id']} {proposal['status']} recommendation={(proposal.get('review') or {}).get('recommendation')}")
        return 0
    if args.schema_command == "decide":
        proposal = decide_schema_proposal(conn, args.proposal_id, action=args.action, actor=args.actor, reason=args.reason, canonical_name=args.canonical_name)
        print(json_dumps(proposal) if args.json else f"{proposal['proposal_id']} {proposal['status']} {proposal['kind']} {proposal['proposed_name']}")
        return 0
    if args.schema_command == "registry":
        rows = list_schema_registry(conn, kind=args.kind, limit=args.limit)
        if args.json:
            print(json_dumps(rows))
        elif not rows:
            print("No dynamic schema registry entries found.")
        else:
            for row in rows:
                print(f"{row['kind']} {row['name']} status={row['status']} proposal={row['created_from_proposal_id'] or '-'}")
        return 0
    raise ValueError(f"unknown schema command: {args.schema_command}")
