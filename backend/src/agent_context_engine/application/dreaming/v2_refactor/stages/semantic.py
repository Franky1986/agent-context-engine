"""Semantic extraction stage migration adapter for Dreaming v2."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext
from ..services import (
    KNOWN_ENTITY_TYPES,
    KNOWN_RELATION_TYPES,
    RECONCILIATION_SCHEMA_VERSION,
    SEMANTIC_SCHEMA_VERSION,
    budget,
    apply_semantic_guardrails,
    build_semantic_prompt,
    deterministic_semantic_payload,
    extract_json_with_diagnostics,
    invoke_runner,
    load_reused_stage_json,
    plain_event_window,
    remap_semantic_payload_for_rerun,
    source_manifest_item,
    validate_semantic_payload,
    write_prompt_manifest,
)


def run_semantic_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    current: dict[str, Any] | Any,
    events: list[dict[str, Any]] | list[Any],
    narrative_response: str,
    semantic_context: dict[str, Any],
    runner: str,
    runner_model: str | None,
    reuse_from_dream_run_id: str | None,
    runner_timeout: int,
    args: Any | None = None,
) -> dict[str, Any]:
    """Execute semantic stage via context contract.

    This module keeps deterministic behavior while routing shared IO and stage
    lifecycle through the refactor runtime facade.
    """

    stage_dir = f"{stage_context.stage_order:02d}-{stage_context.stage_name.replace('_', '-') }"
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

    semantic_prompt = build_semantic_prompt(
        current,
        events,
        narrative_response,
        semantic_context,
        json_dumps_fn=stage_runtime.json_dumps,
        plain_event_window_fn=stage_runtime.plain_event_window,
        budget_fn=budget,
        known_entity_types=KNOWN_ENTITY_TYPES,
        known_relation_types=KNOWN_RELATION_TYPES,
        schema_version=SEMANTIC_SCHEMA_VERSION,
    )
    run_dir = context.run_dir
    semantic_prompt_path = run_dir / stage_dir / "prompt.md"
    stage_runtime.write_text(semantic_prompt_path, semantic_prompt + "\n")
    semantic_manifest_path = write_prompt_manifest(
        run_dir,
        stage_name=stage_context.stage_name,
        stage_dir=stage_dir,
        prompt_path=semantic_prompt_path,
        prompt=semantic_prompt,
        budget=budget("semantic_extraction", semantic_prompt, 40000, 80000),
        included_sources=[
            source_manifest_item("json_schema_contract", "semantic_proposals.v2", json_dumps_fn=stage_runtime.json_dumps),
            source_manifest_item(
                "session_metadata",
                {"session_id": current["session_id"], "project_id": current["project_id"], "client_type": current["client_type"]},
                json_dumps_fn=stage_runtime.json_dumps,
            ),
            source_manifest_item(
                "same_session_semantic_context",
                semantic_context,
                json_dumps_fn=stage_runtime.json_dumps,
                included_chars=12000,
                limit=12000,
            ),
            source_manifest_item(
                "dream_markdown",
                narrative_response,
                json_dumps_fn=stage_runtime.json_dumps,
                included_chars=30000,
                limit=30000,
            ),
            source_manifest_item(
                "compact_conversation",
                plain_event_window(
                    events,
                    redact_fn=stage_runtime.redact_embedded_context_artifacts,
                ),
                json_dumps_fn=stage_runtime.json_dumps,
                included_chars=20000,
                limit=20000,
            ),
        ],
        excluded_sources=[
            {"name": "file_entities", "reason": "operational entities are rejected by semantic schema"},
            {"name": "directory_entities", "reason": "operational entities are rejected by semantic schema"},
            {"name": "command_entities", "reason": "operational entities are rejected by semantic schema"},
            {"name": "raw_tool_inputs", "reason": "raw tool data remains SQLite audit only"},
            {"name": "raw_tool_outputs", "reason": "raw tool data remains SQLite audit only"},
            {"name": "tool_payloads", "reason": "raw tool data remains SQLite audit only"},
            {"name": "existing_global_semantic_memory", "reason": "looked up only after semantic generation"},
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
            artifact_role="semantic_extraction_prompt_manifest",
            path=semantic_manifest_path,
        )

    semantic_raw_path = run_dir / stage_dir / "raw-output.json"
    semantic_id_map: dict[str, str] = {}
    semantic_meta: dict[str, Any] = {}
    reused_semantic_payload = load_reused_stage_json(
        conn,
        reuse_from_dream_run_id,
        stage_context.stage_name,
        root_fn=stage_runtime.root,
        read_text_fn=stage_runtime.read_text,
    )
    if reused_semantic_payload is not None:
        semantic_payload = remap_semantic_payload_for_rerun(
            reused_semantic_payload,
            dream_run_id=context.dream_run_id,
            session_id=context.session_id,
            event_from=context.event_from,
            event_to=context.event_to,
            safe_slug_fn=stage_runtime.safe_slug,
            json_dumps_fn=stage_runtime.json_dumps,
        )
        semantic_text = stage_runtime.json_dumps(semantic_payload)
        stage_runtime.write_text(semantic_raw_path, semantic_text + "\n")
        semantic_meta = {"reused_from_dream_run_id": reuse_from_dream_run_id, "reused_stage": stage_context.stage_name, "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
    else:
        semantic_text, semantic_meta = invoke_runner(
            runner,
            runner_model,
            semantic_prompt,
            semantic_raw_path,
            int(getattr(args, "runner_timeout", runner_timeout) if args is not None else runner_timeout),
            command_runner=stage_runtime.default_runner(),
            root_path=str(stage_runtime.root()),
            now_fn=stage_runtime.now,
            monotonic_fn=stage_runtime.monotonic_now,
            read_text_limited_fn=stage_runtime.read_text_limited,
            write_text_fn=stage_runtime.write_text,
            base_env=stage_runtime.base_env(),
            max_output_bytes=stage_runtime.MAX_STAGE_OUTPUT_BYTES,
            mock_enabled=stage_runtime.mock_enabled(),
            semantic_schema_version=SEMANTIC_SCHEMA_VERSION,
            reconciliation_schema_version=RECONCILIATION_SCHEMA_VERSION,
            json_dumps_fn=stage_runtime.json_dumps,
            allow_empty_output=True,
        )
        semantic_fallback_reason: str | None = None
        try:
            semantic_payload, json_diagnostics = extract_json_with_diagnostics(semantic_text)
            semantic_payload["dream_run_id"] = context.dream_run_id
            semantic_payload["session_id"] = context.session_id
            semantic_payload["source_event_range"] = {"start_seq": context.event_from, "end_seq": context.event_to}
            semantic_meta = {
                **semantic_meta,
                "json_parse": json_diagnostics,
            }
        except Exception as exc:  # noqa: BLE001
            semantic_fallback_reason = str(exc)
            semantic_payload = deterministic_semantic_payload(
                current,
                events,
                narrative_response,
                dream_run_id=context.dream_run_id,
                event_from=context.event_from,
                event_to=context.event_to,
                safe_slug_fn=stage_runtime.safe_slug,
                semantic_schema_version=SEMANTIC_SCHEMA_VERSION,
            )
            semantic_meta = {
                **semantic_meta,
                "fallback_to_deterministic_semantic": True,
                "fallback_reason": semantic_fallback_reason,
                "json_parse_error_code": getattr(exc, "code", None),
                "json_parse": getattr(exc, "diagnostics", {"strategy": "failed"}),
            }
    semantic_payload = apply_semantic_guardrails(semantic_payload, events=events)
    low_signal_window = bool(semantic_payload.pop("_low_signal_window", False))
    signal_strength = str(semantic_payload.pop("_signal_strength", "medium"))
    semantic_id_map = semantic_payload.pop("_rerun_id_map", {})
    semantic_validation = validate_semantic_payload(semantic_payload, semantic_schema_version=SEMANTIC_SCHEMA_VERSION)
    if not semantic_validation["ok"] and not semantic_meta.get("fallback_to_deterministic_semantic"):
        semantic_payload = deterministic_semantic_payload(
            current,
            events,
            narrative_response,
            dream_run_id=context.dream_run_id,
            event_from=context.event_from,
            event_to=context.event_to,
            safe_slug_fn=stage_runtime.safe_slug,
            semantic_schema_version=SEMANTIC_SCHEMA_VERSION,
        )
        semantic_payload = apply_semantic_guardrails(semantic_payload, events=events)
        low_signal_window = bool(semantic_payload.pop("_low_signal_window", False))
        signal_strength = str(semantic_payload.pop("_signal_strength", "medium"))
        semantic_id_map = semantic_payload.pop("_rerun_id_map", {})
        semantic_validation = validate_semantic_payload(semantic_payload, semantic_schema_version=SEMANTIC_SCHEMA_VERSION)
        semantic_meta = {
            **semantic_meta,
            "fallback_to_deterministic_semantic": True,
            "fallback_reason": semantic_validation["errors"],
        }

    if reused_semantic_payload is not None:
        semantic_validation["reused_from_dream_run_id"] = reuse_from_dream_run_id
    if semantic_meta.get("fallback_to_deterministic_semantic"):
        semantic_validation["fallback_to_deterministic_semantic"] = True
        semantic_validation["fallback_reason"] = semantic_meta.get("fallback_reason")
    if low_signal_window:
        semantic_meta = {
            **semantic_meta,
            "low_signal_window": True,
        }
        semantic_validation["low_signal_window"] = True
    semantic_meta = {
        **semantic_meta,
        "signal_strength": signal_strength,
    }
    semantic_validation["signal_strength"] = signal_strength

    semantic_path = run_dir / stage_dir / "semantic-proposals.json"
    stage_runtime.write_json(semantic_path, semantic_payload)
    stage_runtime.write_json(run_dir / stage_dir / "validation.json", semantic_validation)
    if not semantic_validation["ok"]:
        raise RuntimeError(f"semantic extraction validation failed: {semantic_validation['errors']}")

    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        prompt_path=semantic_prompt_path,
        raw_output_path=semantic_raw_path,
        parsed_output_path=semantic_path,
        metadata=semantic_meta,
        validation=semantic_validation,
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
        "event_count": len(events),
        "prompt_path": str(semantic_prompt_path),
        "raw_output_path": str(semantic_raw_path),
        "parsed_output_path": str(semantic_path),
        "artifact_path": str(semantic_manifest_path),
        "semantic_payload": semantic_payload,
        "semantic_validation": semantic_validation,
        "semantic_id_map": semantic_id_map,
        "semantic_meta": semantic_meta,
        "signal_strength": signal_strength,
        "proposal_count": len(semantic_payload.get("entities", [])),
        "relation_count": len(semantic_payload.get("relations", [])),
        "schema_proposal_count": len(semantic_payload.get("schema_proposals", [])),
    }
