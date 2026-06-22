"""Normalization stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext
from ..services import insert_semantic_proposals


def run_normalization_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    semantic_payload: dict[str, Any],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute normalization stage via context contract.

    Keeps the existing write contract while moving shared runtime access to the
    refactor layer.
    """
    from ...normalization import normalize_semantic_payload_from_db

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

    normalized = normalize_semantic_payload_from_db(conn, semantic_payload)
    normalization_path = stage_runtime.write_json(run_dir / stage_dir / "normalized-semantic-proposals.json", normalized)
    normalization_validation = {
        "ok": True,
        "entities": len(normalized.get("entities") or []),
        "relations": len(normalized.get("relations") or []),
        "entities_changed": sum(
            1
            for entity in normalized.get("entities") or []
            if (entity.get("properties") or {}).get("normalization", {}).get("canonical_name")
            != (entity.get("properties") or {}).get("normalization", {}).get("source_name")
        ),
    }
    if not dry_run:
        with conn:
            insert_semantic_proposals(
                conn,
                dream_run_id=context.dream_run_id,
                stage_run_id=stage_id,
                session_id=context.session_id,
                payload=normalized,
                now_fn=stage_runtime.now,
                safe_slug_fn=stage_runtime.safe_slug,
                json_dumps_fn=stage_runtime.json_dumps,
            )

    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        parsed_output_path=normalization_path,
        validation=normalization_validation,
        metadata=normalization_validation,
    )

    return {
        "status": "migrated",
        "stage_name": stage_context.stage_name,
        "stage_order": stage_context.stage_order,
        "stage_run_id": stage_id,
        "session_id": context.session_id,
        "dream_run_id": context.dream_run_id,
        "event_from": context.event_from,
        "event_to": context.event_to,
        "semantic_payload": normalized,
        "normalization_validation": normalization_validation,
        "parsed_output_path": str(normalization_path),
        "artifact_path": str(normalization_path),
        "dry_run": dry_run,
    }
