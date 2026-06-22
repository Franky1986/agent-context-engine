"""Narrative stage extraction for Dreaming v2 refactor."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext
from ..services import (
    budget,
    build_dream_prompt,
    invoke_runner,
    load_reused_stage_text,
    plain_event_window,
    project_slug,
    source_manifest_item,
    write_prompt_manifest,
)


def run_narrative_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    event_rows: list[dict[str, Any]] | list[Any],
    session: dict[str, Any] | Any,
    prompt_text: str,
    prior_dream_summary: str,
    current_handover: str,
    semantic_context: dict[str, Any],
    runner: str,
    runner_model: str | None,
    reuse_from_dream_run_id: str | None,
    runner_timeout: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute narrative stage via staged context.

    Current return shape mirrors the stage contract while using the refactor
    runtime facade for shared IO and stage lifecycle behavior.
    """

    stage_dir = f"{stage_context.stage_order:02d}-{stage_context.stage_name.replace('_', '-')}"
    run_dir = Path(context.run_dir)

    stage_id, _, started_mono = stage_runtime.stage_start(
        conn,
        dream_run_id=context.dream_run_id,
        session_id=context.session_id,
        stage_name=stage_context.stage_name,
        stage_order=stage_context.stage_order,
        runner=runner,
        model=runner_model,
        event_from=context.event_from,
        event_to=context.event_to,
    )

    if isinstance(prompt_text, str) and prompt_text:
        prompt = prompt_text
    else:
        prompt = build_dream_prompt(
            session,
            event_rows,
            prior_dream_summary,
            semantic_context,
            current_handover,
            json_dumps_fn=stage_runtime.json_dumps,
            plain_event_window_fn=lambda ev: plain_event_window(
                ev,
                redact_fn=stage_runtime.redact_embedded_context_artifacts,
            ),
            budget_fn=budget,
        )
    prompt_path = stage_runtime.write_text(run_dir / stage_dir / "prompt.md", prompt + "\n")
    conversation = plain_event_window(
        event_rows,
        redact_fn=stage_runtime.redact_embedded_context_artifacts,
    )
    dream_manifest_path = write_prompt_manifest(
        run_dir,
        stage_name=stage_context.stage_name,
        stage_dir=stage_dir,
        prompt_path=prompt_path,
        prompt=prompt,
        budget=budget("dream_narrative", prompt, 60000, 120000),
        included_sources=[
            source_manifest_item("session_metadata", dict(session), json_dumps_fn=stage_runtime.json_dumps),
            source_manifest_item(
                "last_dream_summary",
                prior_dream_summary,
                json_dumps_fn=stage_runtime.json_dumps,
                included_chars=12000,
                limit=12000,
            ),
            source_manifest_item(
                "current_session_handover",
                current_handover,
                json_dumps_fn=stage_runtime.json_dumps,
                included_chars=12000,
                limit=12000,
            ),
            source_manifest_item(
                "same_session_semantic_context",
                semantic_context,
                json_dumps_fn=stage_runtime.json_dumps,
                included_chars=12000,
                limit=12000,
            ),
            source_manifest_item("chronological_conversation_window", conversation, json_dumps_fn=stage_runtime.json_dumps),
        ],
        excluded_sources=[
            {"name": "raw_tool_inputs", "reason": "operational audit data, not LLM dream context"},
            {"name": "raw_tool_outputs", "reason": "operational audit data, not LLM dream context"},
            {"name": "deterministic_file_command_facts", "reason": "extracted separately into SQLite"},
            {"name": "project_memory_full_text", "reason": "not part of timeslice dream context"},
        ],
        write_json_fn=stage_runtime.write_json,
        rel_fn=stage_runtime.rel,
    )
    with conn:
        stage_runtime.record_artifact(
            conn,
            dream_run_id=context.dream_run_id,
            stage_run_id=stage_id,
            session_id=context.session_id,
            artifact_kind="prompt_manifest",
            artifact_role="dream_narrative_prompt_manifest",
            path=dream_manifest_path,
        )

    raw_path = run_dir / stage_dir / "raw-output.md"
    reused_response = load_reused_stage_text(
        conn,
        reuse_from_dream_run_id,
        stage_context.stage_name,
        root_fn=stage_runtime.root,
        read_text_fn=stage_runtime.read_text,
    )
    if reused_response is not None:
        response = reused_response
        stage_runtime.write_text(raw_path, response.strip() + "\n")
        metadata: dict[str, Any] = {
            "reused_from_dream_run_id": reuse_from_dream_run_id,
            "reused_stage": stage_context.stage_name,
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }
    else:
        response, metadata = invoke_runner(
            runner,
            runner_model,
            prompt,
            raw_path,
            int(runner_timeout),
            command_runner=stage_runtime.default_runner(),
            root_path=str(stage_runtime.root()),
            now_fn=stage_runtime.now,
            monotonic_fn=stage_runtime.monotonic_now,
            read_text_limited_fn=stage_runtime.read_text_limited,
            write_text_fn=stage_runtime.write_text,
            base_env=stage_runtime.base_env(),
            max_output_bytes=stage_runtime.MAX_STAGE_OUTPUT_BYTES,
            mock_enabled=stage_runtime.mock_enabled(),
            semantic_schema_version=stage_runtime.SEMANTIC_SCHEMA_VERSION,
            reconciliation_schema_version=stage_runtime.RECONCILIATION_SCHEMA_VERSION,
            json_dumps_fn=stage_runtime.json_dumps,
        )
    dream_path = stage_runtime.write_text(run_dir / stage_dir / "dream.md", response.strip() + "\n")
    validation = {"ok": bool(response.strip()), "bytes": len(response.encode("utf-8"))}
    if reused_response is not None:
        validation["reused_from_dream_run_id"] = reuse_from_dream_run_id
    if not validation["ok"]:
        raise RuntimeError("dream narrative validation failed")
    if metadata is None:
        metadata = {
            "token_usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
            },
        }
    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        prompt_path=prompt_path,
        raw_output_path=raw_path,
        parsed_output_path=dream_path,
        metadata=metadata,
        validation=validation,
    )

    project_dream_path: Path | None = None
    if not dry_run:
        project_dream_path = (
            stage_runtime.memory_dir()
            / "memories"
            / "dreams"
            / project_slug(session, safe_slug_fn=stage_runtime.safe_slug)
            / f"{stage_runtime.safe_slug(context.dream_run_id)}.md"
        )
        stage_runtime.write_text(project_dream_path, response.strip() + "\n")

    return {
        "status": "migrated",
        "stage_run_id": stage_id,
        "stage_name": stage_context.stage_name,
        "stage_order": stage_context.stage_order,
        "session_id": context.session_id,
        "dream_run_id": context.dream_run_id,
        "event_from": context.event_from,
        "event_to": context.event_to,
        "prompt_path": str(prompt_path),
        "raw_output_path": str(raw_path),
        "parsed_output_path": str(dream_path),
        "artifact_path": str(dream_manifest_path),
        "project_dream_path": str(project_dream_path) if project_dream_path is not None else None,
        "response": response,
        "validation": validation,
        "metadata": metadata,
    }
