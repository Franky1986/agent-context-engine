"""Candidate search stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext
from ..services import search_candidates


def run_candidate_search_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    semantic_payload: dict[str, Any],
    args: Any,
) -> dict[str, Any]:
    """Execute candidate search stage via context contract."""

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

    with conn:
        candidates = search_candidates(
            conn,
            semantic_payload,
            args=args,
            now_fn=stage_runtime.now,
            safe_slug_fn=stage_runtime.safe_slug,
            json_dumps_fn=stage_runtime.json_dumps,
        )
    candidates_path = stage_runtime.write_json(run_dir / stage_dir / "candidates.json", candidates)

    validation = {"ok": True, "neo4j_status": candidates.get("neo4j_status")}
    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        parsed_output_path=candidates_path,
        validation=validation,
        metadata=validation,
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
        "candidates": candidates,
        "candidates_path": str(candidates_path),
        "parsed_output_path": str(candidates_path),
        "artifact_path": str(candidates_path),
        "validation": validation,
    }
