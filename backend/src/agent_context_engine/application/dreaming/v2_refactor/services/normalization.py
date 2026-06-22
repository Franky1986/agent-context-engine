"""Normalization service helpers extracted from the Dreaming v2 monolith."""

from __future__ import annotations

from typing import Any

import sqlite3

KNOWN_ENTITY_TYPES = {
    "project",
    "person",
    "organization",
    "product",
    "feature",
    "decision",
    "issue",
    "risk",
    "preference",
    "concept",
    "task",
    "policy",
    "schema_proposal",
}

KNOWN_RELATION_TYPES = {
    "discusses",
    "depends_on",
    "decides",
    "blocks",
    "affects",
    "belongs_to_project",
    "supersedes",
    "requests",
    "resolves",
    "mentions_external_project",
    "schema_proposal",
}

SEMANTIC_SCHEMA_VERSION = "semantic_proposals.v2"


def _schema_growth_index(payload: dict[str, Any]) -> dict[str, set[str]]:
    index = {"entity_type": set(), "relation_type": set()}
    proposals = payload.get("schema_proposals") if isinstance(payload.get("schema_proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        kind = str(proposal.get("kind") or "")
        proposed_name = str(proposal.get("proposed_name") or "")
        if kind in index and proposed_name:
            index[kind].add(proposed_name)
    return index


def _requires_schema_review(kind: str, typ: Any, schema_growth: dict[str, set[str]]) -> bool:
    value = str(typ or "")
    if not value:
        return False
    if kind == "entity_type":
        return value not in KNOWN_ENTITY_TYPES and value in schema_growth["entity_type"]
    if kind == "relation_type":
        return value not in KNOWN_RELATION_TYPES and value in schema_growth["relation_type"]
    return False


def _entity_key(entity_type: str, name: str, *, safe_slug_fn) -> str:
    return safe_slug_fn(f"{entity_type}:{name.lower()}")[:180]


def _proposal_key(kind: str, typ: str, name: str, *, safe_slug_fn) -> str:
    return safe_slug_fn(f"{kind}:{typ}:{name.lower()}")[:180]


def insert_semantic_proposals(
    conn: sqlite3.Connection,
    *,
    dream_run_id: str,
    stage_run_id: str,
    session_id: str,
    payload: dict[str, Any],
    now_fn,
    safe_slug_fn,
    json_dumps_fn,
) -> None:
    """Persist semantic/schema proposals for the normalization stage.

    Extracted from legacy v2 orchestration logic; behavior is intentionally preserved.
    """

    now = now_fn()
    schema_growth = _schema_growth_index(payload)

    for proposal in payload.get("schema_proposals", []):
        proposal_id = str(proposal["proposal_id"])
        kind = str(proposal["kind"])
        proposed_name = str(proposal["proposed_name"])
        conn.execute(
            """
            insert or replace into schema_proposals (
              proposal_id, kind, proposed_name, canonical_name, status, confidence,
              reason, examples_json, evidence_json, review_json, proposed_by,
              source_session_id, source_dream_run_id, created_at, updated_at
            ) values (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, 'dream_pipeline_v2', ?, ?, ?, ?)
            """,
            (
                proposal_id,
                kind,
                proposed_name,
                proposal.get("canonical_name") or proposed_name,
                proposal.get("confidence"),
                proposal.get("reason"),
                json_dumps_fn(proposal.get("examples") or []),
                json_dumps_fn(proposal.get("evidence") or []),
                json_dumps_fn(
                    {
                        "review_required": True,
                        "review_reason": proposal.get("review_reason") or "New semantic schema category requires human review.",
                    }
                ),
                session_id,
                dream_run_id,
                now,
                now,
            ),
        )
        conn.execute(
            """
            insert into schema_proposal_audit (
              audit_id, proposal_id, action, actor, reason, after_json, created_at
            ) values (?, ?, 'created', 'dream_pipeline_v2', ?, ?, ?)
            on conflict(audit_id) do nothing
            """,
            (
                f"audit_{safe_slug_fn(proposal_id)}_{safe_slug_fn(dream_run_id)}",
                proposal_id,
                proposal.get("reason") or "",
                json_dumps_fn(proposal),
                now,
            ),
        )

    for entity in payload.get("entities", []):
        proposal_id = str(entity["proposal_id"])
        entity_requires_schema_review = _requires_schema_review("entity_type", entity.get("type"), schema_growth)
        conn.execute(
            """
            insert or replace into semantic_proposals (
              semantic_proposal_id, dream_run_id, stage_run_id, session_id,
              proposal_kind, proposed_type, proposed_key, proposed_name,
              aliases_json, summary, properties_json, evidence_json, confidence,
              schema_version, review_required, review_reason, validation_json,
              created_at, updated_at
            ) values (?, ?, ?, ?, 'entity', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                proposal_id,
                dream_run_id,
                stage_run_id,
                session_id,
                entity["type"],
                entity.get("canonical_key_candidate") or _entity_key(entity["type"], entity["name"], safe_slug_fn=safe_slug_fn),
                entity["name"],
                json_dumps_fn(entity.get("aliases") or []),
                entity.get("summary"),
                json_dumps_fn(entity.get("properties") or {}),
                json_dumps_fn(entity.get("evidence") or []),
                entity.get("confidence"),
                SEMANTIC_SCHEMA_VERSION,
                1 if entity.get("review_required") or entity_requires_schema_review else 0,
                entity.get("review_reason")
                or ("New semantic entity type requires schema review." if entity_requires_schema_review else None),
                now,
                now,
            ),
        )

    for relation in payload.get("relations", []):
        proposal_id = str(relation["proposal_id"])
        relation_requires_schema_review = _requires_schema_review("relation_type", relation.get("type"), schema_growth)
        conn.execute(
            """
            insert or replace into semantic_proposals (
              semantic_proposal_id, dream_run_id, stage_run_id, session_id,
              proposal_kind, proposed_type, proposed_key, proposed_name,
              properties_json, evidence_json, confidence, schema_version,
              review_required, review_reason, validation_json, created_at, updated_at
            ) values (?, ?, ?, ?, 'relation', ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
            """,
            (
                proposal_id,
                dream_run_id,
                stage_run_id,
                session_id,
                relation["type"],
                relation.get("canonical_relation_key_candidate")
                or _proposal_key("relation", relation["type"], proposal_id, safe_slug_fn=safe_slug_fn),
                relation.get("summary") or relation["type"],
                json_dumps_fn(
                    {
                        **(relation.get("properties") or {}),
                        "source_ref": relation.get("source_ref"),
                        "target_ref": relation.get("target_ref"),
                    }
                ),
                json_dumps_fn(relation.get("evidence") or []),
                relation.get("confidence"),
                SEMANTIC_SCHEMA_VERSION,
                1 if relation.get("review_required") or relation_requires_schema_review else 0,
                relation.get("review_reason")
                or ("New semantic relation type requires schema review." if relation_requires_schema_review else None),
                now,
                now,
            ),
        )
