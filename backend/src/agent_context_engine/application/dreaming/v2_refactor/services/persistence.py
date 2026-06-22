"""Persistence services extracted from `v2.py`.

These helpers isolate SQL mutation/persistence behavior and Neo4j sync orchestration
from stage orchestration, preserving existing v2 behavioral contracts.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import json
from typing import Any

import sqlite3

from ....graph import graph_extract_path_for_dream, graph_structure_for_dream_with_reopened_db, sync_graph_patch


def _decode_json(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _snapshot_from_entity(row: sqlite3.Row | None, overrides: dict[str, Any] | None = None, *, decode_json_fn) -> dict[str, Any] | None:
    if row is None and not overrides:
        return None
    snapshot = {
        "semantic_entity_id": row["semantic_entity_id"] if row else None,
        "entity_key": row["entity_key"] if row else None,
        "entity_type": row["entity_type"] if row else None,
        "name": row["name"] if row else None,
        "aliases": decode_json_fn(row["aliases_json"] if row else None) or [],
        "summary": row["summary"] if row else None,
        "properties": decode_json_fn(row["properties_json"] if row else None) or {},
        "confidence": row["confidence"] if row else None,
        "source_session_id": row["source_session_id"] if row else None,
        "source_dream_run_id": row["source_dream_run_id"] if row else None,
        "evidence": decode_json_fn(row["evidence_json"] if row else None) or [],
        "status": row["status"] if row else None,
        "created_at": row["created_at"] if row else None,
        "updated_at": row["updated_at"] if row else None,
    }
    if overrides:
        snapshot.update(overrides)
    return snapshot


def _snapshot_from_relation(row: sqlite3.Row | None, overrides: dict[str, Any] | None = None, *, decode_json_fn) -> dict[str, Any] | None:
    if row is None and not overrides:
        return None
    snapshot = {
        "semantic_relation_id": row["semantic_relation_id"] if row else None,
        "relation_key": row["relation_key"] if row else None,
        "relation_type": row["relation_type"] if row else None,
        "source_entity_key": row["source_entity_key"] if row else None,
        "target_entity_key": row["target_entity_key"] if row else None,
        "summary": row["summary"] if row else None,
        "properties": decode_json_fn(row["properties_json"] if row else None) or {},
        "confidence": row["confidence"] if row else None,
        "source_session_id": row["source_session_id"] if row else None,
        "source_dream_run_id": row["source_dream_run_id"] if row else None,
        "evidence": decode_json_fn(row["evidence_json"] if row else None) or [],
        "status": row["status"] if row else None,
        "created_at": row["created_at"] if row else None,
        "updated_at": row["updated_at"] if row else None,
    }
    if overrides:
        snapshot.update(overrides)
    return snapshot


def _record_mutation(
    conn: sqlite3.Connection,
    *,
    dream_run_id: str,
    decision_id: str,
    target_kind: str,
    target_id: str,
    target_key: str,
    mutation_kind: str,
    mutation_summary: str,
    before_snapshot_json: str | None,
    after_snapshot_json: str | None,
    source_session_id: str,
    now_fn,
    safe_slug_fn,
    json_dumps_fn=None,
) -> None:
    try:
        conn.execute(
            """
            insert into semantic_projection_mutations (
              mutation_id, dream_run_id, reconciliation_decision_id,
              target_kind, target_id, target_key,
              mutation_kind, mutation_summary, before_snapshot_json,
              after_snapshot_json, created_at, source_dream_run_id, source_session_id
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"mutation_{safe_slug_fn(dream_run_id)}_{safe_slug_fn(decision_id)}",
                dream_run_id,
                decision_id,
                target_kind,
                target_id,
                target_key,
                mutation_kind,
                mutation_summary,
                before_snapshot_json,
                after_snapshot_json,
                now_fn(),
                dream_run_id,
                source_session_id,
            ),
        )
    except sqlite3.OperationalError as exc:
        if "no such table: semantic_projection_mutations" not in str(exc):
            raise


def apply_persistence(
    conn: sqlite3.Connection,
    dream_run_id: str,
    *,
    now_fn,
    safe_slug_fn,
    json_dumps_fn,
    decode_json_fn=_decode_json,
    record_mutation_fn=_record_mutation,
) -> dict[str, Any]:
    """Apply pending reconciliation decisions and persist semantic entities/relations."""

    now = now_fn()
    created_entities = 0
    created_relations = 0

    proposal_keys = {
        row["semantic_proposal_id"]: row["proposed_key"]
        for row in conn.execute(
            "select semantic_proposal_id, proposed_key from semantic_proposals where dream_run_id = ?",
            (dream_run_id,),
        )
    }
    decisions = list(
        conn.execute(
            """
            select rd.*, sp.session_id as proposal_session_id,
                   sp.proposal_kind, sp.proposed_type, sp.proposed_key, sp.proposed_name,
                   sp.aliases_json, sp.summary, sp.properties_json, sp.evidence_json,
                   sp.review_required as proposal_review_required,
                   sp.review_reason as proposal_review_reason
            from reconciliation_decisions rd
            join semantic_proposals sp on sp.semantic_proposal_id = rd.semantic_proposal_id
            where rd.dream_run_id = ? and rd.status = 'pending'
            order by rd.created_at
            """,
            (dream_run_id,),
        )
    )

    for row in decisions:
        if row["review_required"] or row["proposal_review_required"]:
            reason = row["review_reason"] or row["proposal_review_reason"] or "semantic proposal requires review"
            conn.execute(
                "update reconciliation_decisions set status='deferred_review', review_required=1, review_reason=?, updated_at=? where reconciliation_decision_id=?",
                (reason, now, row["reconciliation_decision_id"]),
            )
            continue

        if row["decision"] in {"reject", "defer_for_review", "propose_schema"}:
            status = "rejected" if row["decision"] == "reject" else "deferred_review"
            conn.execute(
                "update reconciliation_decisions set status=?, updated_at=? where reconciliation_decision_id=?",
                (status, now, row["reconciliation_decision_id"]),
            )
            continue

        if row["proposal_kind"] == "entity" and row["decision"] in {"create_entity", "update_entity", "merge_entity"}:
            entity_id = f"sem_ent_{safe_slug_fn(row['proposed_key'])}"
            before_row = conn.execute(
                "select * from semantic_entities where entity_type = ? and entity_key = ?",
                (row["proposed_type"], row["proposed_key"]),
            ).fetchone()
            mutation_kind = "updated" if before_row is not None else "created"
            conn.execute(
                """
                insert into semantic_entities (
                  semantic_entity_id, entity_key, entity_type, name, aliases_json,
                  summary, properties_json, confidence, source_session_id,
                  source_dream_run_id, evidence_json, status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                on conflict(entity_type, entity_key) do update set
                  name=excluded.name,
                  aliases_json=excluded.aliases_json,
                  summary=coalesce(excluded.summary, semantic_entities.summary),
                  properties_json=excluded.properties_json,
                  confidence=excluded.confidence,
                  source_session_id=excluded.source_session_id,
                  source_dream_run_id=excluded.source_dream_run_id,
                  evidence_json=excluded.evidence_json,
                  updated_at=excluded.updated_at
                """,
                (
                    entity_id,
                    row["proposed_key"],
                    row["proposed_type"],
                    row["proposed_name"],
                    row["aliases_json"],
                    row["summary"],
                    row["properties_json"],
                    row["confidence"],
                    row["proposal_session_id"],
                    dream_run_id,
                    row["evidence_json"],
                    now,
                    now,
                ),
            )
            after_row = conn.execute("select * from semantic_entities where semantic_entity_id = ?", (entity_id,)).fetchone()
            record_mutation_fn(
                conn,
                dream_run_id=dream_run_id,
                decision_id=row["reconciliation_decision_id"],
                target_kind="semantic_entity",
                target_id=entity_id,
                target_key=row["proposed_key"],
                mutation_kind=mutation_kind,
                mutation_summary=f"semantic entity {mutation_kind}: {row['proposed_key']}",
                before_snapshot_json=json_dumps_fn(_snapshot_from_entity(before_row, decode_json_fn=decode_json_fn) or {}),
                after_snapshot_json=json_dumps_fn(_snapshot_from_entity(after_row, decode_json_fn=decode_json_fn) or {}),
                source_session_id=row["proposal_session_id"],
                now_fn=now_fn,
                safe_slug_fn=safe_slug_fn,
                json_dumps_fn=json_dumps_fn,
            )
            created_entities += 1
            conn.execute(
                "update reconciliation_decisions set status='applied', applied_at=?, updated_at=? where reconciliation_decision_id=?",
                (now, now, row["reconciliation_decision_id"]),
            )
            continue

        if row["proposal_kind"] == "relation" and row["decision"] in {"create_relation", "update_relation"}:
            try:
                properties = json.loads(row["properties_json"] or "{}")
            except json.JSONDecodeError:
                properties = {}
            source_ref = str(properties.get("source_ref") or "")
            target_ref = str(properties.get("target_ref") or "")
            source_key = proposal_keys.get(source_ref, source_ref)
            target_key = proposal_keys.get(target_ref, target_ref)
            if not source_key or not target_key:
                conn.execute(
                    "update reconciliation_decisions set status='deferred_review', review_required=1, review_reason='relation endpoint missing', updated_at=? where reconciliation_decision_id=?",
                    (now, row["reconciliation_decision_id"]),
                )
                continue
            relation_key = safe_slug_fn(f"{row['proposed_type']}:{source_key}->{target_key}")[:220]
            relation_id = f"sem_rel_{safe_slug_fn(relation_key)}"
            before_row = conn.execute("select * from semantic_relations where relation_key = ?", (relation_key,)).fetchone()
            mutation_kind = "updated" if before_row is not None else "created"
            conn.execute(
                """
                insert into semantic_relations (
                  semantic_relation_id, relation_key, relation_type, source_entity_key,
                  target_entity_key, summary, properties_json, confidence,
                  source_session_id, source_dream_run_id, evidence_json, status,
                  created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                on conflict(relation_key) do update set
                  summary=coalesce(excluded.summary, semantic_relations.summary),
                  properties_json=excluded.properties_json,
                  confidence=excluded.confidence,
                  source_session_id=excluded.source_session_id,
                  source_dream_run_id=excluded.source_dream_run_id,
                  evidence_json=excluded.evidence_json,
                  updated_at=excluded.updated_at
                """,
                (
                    relation_id,
                    relation_key,
                    row["proposed_type"],
                    source_key,
                    target_key,
                    row["summary"],
                    row["properties_json"],
                    row["confidence"],
                    row["proposal_session_id"],
                    dream_run_id,
                    row["evidence_json"],
                    now,
                    now,
                ),
            )
            after_row = conn.execute(
                "select * from semantic_relations where semantic_relation_id = ?",
                (relation_id,),
            ).fetchone()
            record_mutation_fn(
                conn,
                dream_run_id=dream_run_id,
                decision_id=row["reconciliation_decision_id"],
                target_kind="semantic_relation",
                target_id=relation_id,
                target_key=relation_key,
                mutation_kind=mutation_kind,
                mutation_summary=f"semantic relation {mutation_kind}: {relation_key}",
                before_snapshot_json=json_dumps_fn(_snapshot_from_relation(before_row, decode_json_fn=decode_json_fn) or {}),
                after_snapshot_json=json_dumps_fn(_snapshot_from_relation(after_row, decode_json_fn=decode_json_fn) or {}),
                source_session_id=row["proposal_session_id"],
                now_fn=now_fn,
                safe_slug_fn=safe_slug_fn,
                json_dumps_fn=json_dumps_fn,
            )
            created_relations += 1
            conn.execute(
                "update reconciliation_decisions set status='applied', applied_at=?, updated_at=? where reconciliation_decision_id=?",
                (now, now, row["reconciliation_decision_id"]),
            )

    return {
        "semantic_entities_written": created_entities,
        "semantic_relations_written": created_relations,
        "decisions_seen": len(decisions),
    }


def build_graph_dream_artifacts(
    conn: sqlite3.Connection,
    session: sqlite3.Row,
    dream_row: sqlite3.Row | None,
    *,
    runner: str,
    runner_model: str | None,
    timeout: int,
    args,
    graph_extract_path_fn=graph_extract_path_for_dream,
    graph_structure_fn=graph_structure_for_dream_with_reopened_db,
) -> tuple[Path | None, Path | None, sqlite3.Connection]:
    if dream_row is None:
        return None, None, conn
    graph_facts_path = graph_extract_path_fn(conn, session, dream_row)
    graph_patch_path, conn = graph_structure_fn(
        conn,
        session,
        dream_row,
        runner=runner,
        runner_model=runner_model,
        timeout=timeout,
        facts_path=graph_facts_path,
        args=args,
    )
    return Path(graph_facts_path) if graph_facts_path else None, Path(graph_patch_path) if graph_patch_path else None, conn


def _semantic_projection_patch(
    conn: sqlite3.Connection,
    dream_run_id: str,
    *,
    now_fn,
    schema_version: str,
    decode_json_fn=_decode_json,
    entity_type_to_graph_fn,
    relation_type_to_graph_fn,
) -> dict[str, Any]:
    entities: list[dict[str, Any]] = []
    try:
        entity_rows = conn.execute(
            "select * from semantic_entities where source_dream_run_id = ? and status = 'active' order by entity_type, entity_key",
            (dream_run_id,),
        )
    except sqlite3.OperationalError as exc:
        if "no such table: semantic_entities" not in str(exc):
            raise
        entity_rows = ()
    for row in entity_rows:
        evidence = [item for item in (decode_json_fn(row["evidence_json"] or "[]") or []) if isinstance(item, dict)]
        graph_entity_type = entity_type_to_graph_fn(row["entity_type"])
        entities.append(
            {
                "type": graph_entity_type,
                "key": row["entity_key"],
                "name": row["name"],
                "aliases": decode_json_fn(row["aliases_json"] or "[]"),
                "properties": {
                    "summary": row["summary"],
                    "semantic_type": row["entity_type"],
                    "pipeline": "dream_pipeline_v2",
                    **decode_json_fn(row["properties_json"] or "{}"),
                },
                "confidence": row["confidence"] or 0.8,
                "memory_kind": "semantic",
                "source_kind": "dream_run",
                "risk_level": "low",
                "sensitivity": "normal",
                "injection_policy": "on_demand",
                "evidence": [
                    {
                        "source_type": item.get("source") or "dream_pipeline_v2",
                        "session_id": row["source_session_id"],
                        "event_seq": item.get("event_seq"),
                        "field": "semantic_entity",
                        "path": None,
                        "quote": item.get("quote") or row["summary"] or row["name"],
                    }
                    for item in evidence
                ],
            }
        )

    entity_type_by_key = {entity["key"]: entity["type"] for entity in entities}
    relations: list[dict[str, Any]] = []
    try:
        relation_rows = conn.execute(
            "select * from semantic_relations where source_dream_run_id = ? and status = 'active' order by relation_type, relation_key",
            (dream_run_id,),
        )
    except sqlite3.OperationalError as exc:
        if "no such table: semantic_relations" not in str(exc):
            raise
        relation_rows = ()
    for row in relation_rows:
        evidence = [item for item in (decode_json_fn(row["evidence_json"] or "[]") or []) if isinstance(item, dict)]
        graph_relation_type = relation_type_to_graph_fn(row["relation_type"])
        relations.append(
            {
                "from": {"type": entity_type_by_key.get(row["source_entity_key"], "Concept"), "key": row["source_entity_key"]},
                "type": graph_relation_type,
                "to": {"type": entity_type_by_key.get(row["target_entity_key"], "Concept"), "key": row["target_entity_key"]},
                "properties": {
                    "summary": row["summary"],
                    "semantic_type": row["relation_type"],
                    "pipeline": "dream_pipeline_v2",
                    **decode_json_fn(row["properties_json"] or "{}"),
                },
                "confidence": row["confidence"] or 0.8,
                "memory_kind": "semantic",
                "source_kind": "dream_run",
                "risk_level": "low",
                "sensitivity": "normal",
                "injection_policy": "on_demand",
                "evidence": [
                    {
                        "source_type": item.get("source") or "dream_pipeline_v2",
                        "session_id": row["source_session_id"],
                        "event_seq": item.get("event_seq"),
                        "field": "semantic_relation",
                        "path": None,
                        "quote": item.get("quote") or row["summary"] or row["relation_type"],
                    }
                    for item in evidence
                ],
            }
        )

    return {
        "schema_version": schema_version,
        "source": {"kind": "semantic_projection_v2", "dream_run_id": dream_run_id, "created_at": now_fn()},
        "entities": entities,
        "relations": relations,
    }


def _neo4j_sync_args(args) -> Any:
    return argparse.Namespace(
        sync_neo4j=getattr(args, "sync_neo4j", True),
        neo4j_batch_size=int(getattr(args, "neo4j_batch_size", getattr(args, "batch_size", 500)),
        ),
        neo4j_timeout=int(getattr(args, "neo4j_timeout", getattr(args, "timeout", 60))),
        uri=getattr(args, "uri", None),
        database=getattr(args, "database", None),
        user=getattr(args, "user", None),
        password_env=getattr(args, "password_env", "AGENT_MEMORY_NEO4J_PASSWORD"),
    )


def sync_semantic_projection(
    conn: sqlite3.Connection,
    *,
    args: Any,
    dream_run_id: str,
    run_dir: Path,
    dry_run: bool,
    now_fn,
    safe_slug_fn,
    rel_fn,
    write_json_fn,
    projection_schema_version: str,
    entity_type_to_graph_fn,
    relation_type_to_graph_fn,
    sync_graph_patch_fn=sync_graph_patch,
) -> tuple[dict[str, Any], Path]:
    """Build semantic projection patch and optionally project into Neo4j."""
    patch = _semantic_projection_patch(
        conn,
        dream_run_id,
        now_fn=now_fn,
        schema_version=projection_schema_version,
        entity_type_to_graph_fn=entity_type_to_graph_fn,
        relation_type_to_graph_fn=relation_type_to_graph_fn,
    )
    patch_path = write_json_fn(run_dir / "07-persistence" / "final-semantic-patch.json", patch)
    started = now_fn()
    result: dict[str, Any] = {
        "status": "dry_run" if dry_run else "skipped_unconfigured",
        "dry_run": dry_run,
        "patch": rel_fn(patch_path),
        "entities": len(patch["entities"]),
        "relations": len(patch["relations"]),
        "database": getattr(args, "database", None),
    }
    error = None
    if dry_run:
        result["message"] = "Dry run: Neo4j projection was not updated."
    elif not bool(getattr(args, "sync_neo4j", True)):
        result["status"] = "disabled"
        result["message"] = "Neo4j sync disabled by --no-sync-neo4j."
    else:
        sync_args = _neo4j_sync_args(args)
        code, message = sync_graph_patch_fn(
            conn,
            args=sync_args,
            patch_path=patch_path,
        )
        if code == 0 and str(message).startswith("neo4j sync skipped:"):
            result["status"] = "skipped_unconfigured"
        else:
            result["status"] = "succeeded" if code == 0 else "failed"
        result["message"] = message
        error = None if code == 0 else message
    finished = now_fn()
    try:
        with conn:
            conn.execute(
                """
                insert or replace into projection_sync_runs (
                  projection_sync_run_id, projection, started_at, finished_at, status,
                  source_state_json, result_json, error_message
                ) values (?, 'neo4j_semantic_v2', ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"projection_{safe_slug_fn(dream_run_id)}",
                    started,
                    finished,
                    result["status"],
                    json.dumps({
                        "dream_run_id": dream_run_id,
                        "semantic_entities": len(patch["entities"]),
                        "semantic_relations": len(patch["relations"]),
                    }),
                    json.dumps(result),
                    error,
                ),
            )
    except sqlite3.OperationalError as exc:
        if "no such table: projection_sync_runs" not in str(exc):
            raise
    return result, patch_path
