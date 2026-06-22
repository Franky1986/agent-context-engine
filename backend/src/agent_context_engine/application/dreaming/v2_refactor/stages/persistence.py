"""Persistence stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from ...normalization_learning import run_normalization_learning
from .. import runtime as stage_runtime
from ..repositories import DreamV2Repository
from ..services import apply_persistence, build_graph_dream_artifacts, sync_semantic_projection
from ..context import DreamV2Context, DreamV2StageContext


def run_persistence_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    session: dict[str, Any] | Any,
    reconciliation_payload: dict[str, Any],
    semantic_payload: dict[str, Any],
    dry_run: bool,
    runner: str,
    runner_model: str | None,
    args: Any | None = None,
) -> dict[str, Any]:
    """Execute persistence stage via context contract.

    This includes dry-run mode, SQLite persistence, optional Neo4j sync, and
    graph artifact handling consistent with the existing pipeline contract.
    """

    stage_dir = f"{stage_context.stage_order:02d}-{stage_context.stage_name.replace('_', '-') }"
    run_dir = context.run_dir
    stage_id, _, started_mono = stage_runtime.stage_start(
        conn,
        dream_run_id=context.dream_run_id,
        session_id=context.session_id,
        stage_name=stage_context.stage_name,
        stage_order=stage_context.stage_order,
        event_from=context.event_from,
        event_to=context.event_to,
    )

    if dry_run:
        persistence: dict[str, Any] = {
            "dry_run": True,
            "semantic_entities_written": 0,
            "semantic_relations_written": 0,
            "decisions_seen": len(reconciliation_payload.get("decisions") or []),
            "normalization_learning": {
                "proposals_created": 0,
                "rules_activated": 0,
                "shadow_rules": 0,
                "rejected_rules": 0,
            },
            "note": "Durable semantic memory, project memory, session dream window, and Neo4j projection were not updated.",
        }
    else:
        with conn:
            persistence = apply_persistence(
                conn,
                context.dream_run_id,
                now_fn=stage_runtime.now,
                safe_slug_fn=stage_runtime.safe_slug,
                json_dumps_fn=stage_runtime.json_dumps,
            )
            persistence["normalization_learning"] = run_normalization_learning(
                conn,
                dream_run_id=context.dream_run_id,
                session_id=context.session_id,
                normalized_payload=semantic_payload,
            )

    repo = DreamV2Repository(conn)
    if args is None:
        args = type(
            "Args",
            (),
            {
                "sync_neo4j": True,
                "runner_timeout": 1800,
                "neo4j_batch_size": getattr(conn, "neo4j_batch_size", 500),
                "neo4j_timeout": getattr(conn, "neo4j_timeout", 60),
                "uri": None,
                "database": None,
                "user": None,
                "password_env": "AGENT_MEMORY_NEO4J_PASSWORD",
            },
        )()

    sqlite_writes_path = stage_runtime.write_json(run_dir / stage_dir / "sqlite-writes.json", persistence)
    neo4j_sync, semantic_patch_path = sync_semantic_projection(
        conn,
        args=args,
        dream_run_id=context.dream_run_id,
        run_dir=run_dir,
        dry_run=dry_run,
        now_fn=stage_runtime.now,
        safe_slug_fn=stage_runtime.safe_slug,
        rel_fn=stage_runtime.rel,
        write_json_fn=stage_runtime.write_json,
        projection_schema_version=stage_runtime.GRAPH_SCHEMA_VERSION,
        entity_type_to_graph_fn=stage_runtime.semantic_entity_type_to_graph,
        relation_type_to_graph_fn=stage_runtime.semantic_relation_type_to_graph,
    )
    neo4j_sync_path = stage_runtime.write_json(run_dir / stage_dir / "neo4j-sync.json", neo4j_sync)

    graph_facts_path = None
    graph_patch_path = None
    if not dry_run:
        dream_row = repo.fetch_dream_run(context.dream_run_id)
        if dream_row is not None:
            graph_facts_path, graph_patch_path, conn = build_graph_dream_artifacts(
                conn,
                session,
                dream_row,
                runner=runner,
                runner_model=runner_model,
                timeout=int(getattr(args, "runner_timeout", 1800)),
                args=args,
            )

    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        parsed_output_path=sqlite_writes_path,
        artifact_path=semantic_patch_path,
        validation={"ok": neo4j_sync.get("status") != "failed", "neo4j_status": neo4j_sync.get("status"), "dry_run": dry_run},
    )
    if neo4j_sync.get("status") == "failed":
        raise RuntimeError(f"semantic Neo4j projection failed: {neo4j_sync.get('message')}")

    return {
        "status": "migrated",
        "stage_name": stage_context.stage_name,
        "stage_order": stage_context.stage_order,
        "stage_run_id": stage_id,
        "session_id": context.session_id,
        "dream_run_id": context.dream_run_id,
        "event_from": context.event_from,
        "event_to": context.event_to,
        "dry_run": dry_run,
        "decisions_seen": len(reconciliation_payload.get("decisions", [])),
        "entities_written": int(persistence.get("semantic_entities_written", 0)),
        "relations_written": int(persistence.get("semantic_relations_written", 0)),
        "persistence": persistence,
        "sqlite_writes_path": str(sqlite_writes_path),
        "neo4j_sync_path": str(neo4j_sync_path),
        "artifact_path": str(semantic_patch_path if semantic_patch_path is not None else sqlite_writes_path),
        "graph_patch_path": str(graph_patch_path) if graph_patch_path is not None else None,
        "graph_facts_path": str(graph_facts_path) if graph_facts_path is not None else None,
        "conn": conn,
    }
