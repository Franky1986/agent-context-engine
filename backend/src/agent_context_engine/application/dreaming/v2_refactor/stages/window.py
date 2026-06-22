"""Window/capture stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext


def run_window_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    event_rows: list[dict[str, Any]] | list[Any],
    current: dict[str, Any] | Any,
    previous_summary: str,
    semantic_context: dict[str, Any],
    _output_paths_only: bool = False,
) -> dict[str, Any]:
    """Execute window stage via context contract.

    Keeps existing behavior from the monolith inline implementation while isolating
    orchestration for refactoring.
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

    window_dir = run_dir / stage_dir
    stage_runtime.write_json(window_dir / "events.json", [dict(event) for event in event_rows])
    conversation_path = stage_runtime.write_text(window_dir / "conversation.md", stage_runtime.plain_event_window(event_rows) + "\n")
    stage_runtime.write_json(window_dir / "session-metadata.json", dict(current))
    stage_runtime.write_text(window_dir / "last-dream-summary.md", previous_summary + "\n")
    stage_runtime.write_json(window_dir / "same-session-semantic-context.json", semantic_context)

    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        artifact_path=conversation_path,
        validation={"ok": True},
    )

    payload: dict[str, Any] = {
        "status": "migrated",
        "stage_name": stage_context.stage_name,
        "stage_order": stage_context.stage_order,
        "stage_run_id": stage_id,
        "session_id": context.session_id,
        "dream_run_id": context.dream_run_id,
        "event_from": context.event_from,
        "event_to": context.event_to,
        "artifact_path": str(conversation_path),
        "validation": {"ok": True},
    }

    if _output_paths_only:
        return payload

    return {
        **payload,
        "output_paths": {
            "events": str(window_dir / "events.json"),
            "conversation": str(window_dir / "conversation.md"),
            "session_metadata": str(window_dir / "session-metadata.json"),
            "last_dream_summary": str(window_dir / "last-dream-summary.md"),
            "semantic_context": str(window_dir / "same-session-semantic-context.json"),
        },
    }
