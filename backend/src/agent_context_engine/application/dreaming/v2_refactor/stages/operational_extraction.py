"""Operational extraction stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext
from ..services import extract_operational_facts


def run_operational_extraction_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
) -> dict[str, Any]:
    """Execute operational extraction stage via context contract."""

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
        operational = extract_operational_facts(
            conn,
            context.dream_run_id,
            context.session_id,
            context.event_from,
            context.event_to,
            safe_slug_fn=stage_runtime.safe_slug,
            now_fn=stage_runtime.now,
            json_dumps_fn=stage_runtime.json_dumps,
        )
    operational_path = stage_runtime.write_json(run_dir / stage_dir / "operational-facts.json", operational)

    validation = {"ok": True, "sqlite_only": True}
    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        parsed_output_path=operational_path,
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
        "parsed_output_path": str(operational_path),
        "artifact_path": str(operational_path),
        "operational_payload": operational,
        "validation": validation,
    }
