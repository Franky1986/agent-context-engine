"""Audit stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..services import write_audit_manifest
from ..context import DreamV2Context, DreamV2StageContext


def run_audit_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    session: dict[str, Any] | Any,
    semantic_payload: dict[str, Any],
    reconciliation_payload: dict[str, Any],
    operational: dict[str, Any],
    candidates: dict[str, Any],
    persistence_result: dict[str, Any] | None,
    validation: dict[str, Any],
    event_count: int,
    dry_run: bool,
) -> dict[str, Any]:
    """Execute audit stage via context contract.

    Produces markdown audit summary, memory changes and review files and returns paths.
    """

    audit_paths = write_audit_manifest(
        context.run_dir,
        session=session,
        dream_run_id=context.dream_run_id,
        event_from=context.event_from,
        event_to=context.event_to,
        event_count=event_count,
        semantic_payload=semantic_payload,
        reconciliation_payload=reconciliation_payload,
        operational=operational,
        candidates=candidates,
        persistence=persistence_result or {},
        validation=validation,
        dry_run=dry_run,
        write_text_fn=stage_runtime.write_text,
    )
    summary_path = audit_paths["summary"]

    return {
        "status": "migrated",
        "stage_name": stage_context.stage_name,
        "stage_order": stage_context.stage_order,
        "stage_run_id": stage_context.stage_run_id,
        "session_id": context.session_id,
        "dream_run_id": context.dream_run_id,
        "event_from": context.event_from,
        "event_to": context.event_to,
        "audit_paths": audit_paths,
        "summary_path": str(summary_path),
        "memory_changes_path": str(audit_paths["memory_changes"]),
        "review_needed_path": str(audit_paths["review_needed"]),
        "summary_length": len(audit_paths["summary"].read_text(encoding="utf-8")),
        "artifact_path": str(summary_path),
    }
