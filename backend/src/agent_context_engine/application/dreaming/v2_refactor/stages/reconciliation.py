"""Reconciliation stage contract for Dreaming v2 refactor."""

from __future__ import annotations

from typing import Any

from .. import runtime as stage_runtime
from ..context import DreamV2Context, DreamV2StageContext
from ..services import (
    RECONCILIATION_SCHEMA_VERSION,
    apply_reconciliation_guardrails,
    budget,
    build_reconciliation_prompt,
    deterministic_reconciliation_payload,
    extract_json_with_diagnostics,
    invoke_runner,
    load_reused_stage_json,
    remap_reconciliation_payload_for_rerun,
    source_manifest_item,
    validate_reconciliation_payload_with_context,
    write_prompt_manifest,
)


def run_reconciliation_stage(
    *,
    conn: Any,
    context: DreamV2Context,
    stage_context: DreamV2StageContext,
    semantic_payload: dict[str, Any],
    candidates: dict[str, Any],
    runner: str,
    runner_model: str | None,
    semantic_id_map: dict[str, str] | None = None,
    reuse_from_dream_run_id: str | None = None,
    runner_timeout: int | None = None,
    args: Any | None = None,
) -> dict[str, Any]:
    """Execute reconciliation stage via context contract.

    Mirrors the previous monolith stage behavior, including reuse + deterministic
    fallback, while routing shared runtime concerns through the refactor facade.
    """

    stage_dir = f"{stage_context.stage_order:02d}-{stage_context.stage_name.replace('_', '-') }"
    run_dir = context.run_dir
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

    session = conn.execute(
        "select * from sessions where session_id = ?",
        (context.session_id,),
    ).fetchone()
    if session is None:
        raise RuntimeError(f"cannot run reconciliation stage: session not found {context.session_id}")

    reconciliation_prompt = build_reconciliation_prompt(
        session,
        semantic_payload,
        candidates,
        json_dumps_fn=stage_runtime.json_dumps,
        budget_fn=budget,
        schema_version=RECONCILIATION_SCHEMA_VERSION,
    )
    reconciliation_prompt_path = stage_runtime.write_text(run_dir / stage_dir / "prompt.md", reconciliation_prompt + "\n")
    reconciliation_manifest_path = write_prompt_manifest(
        run_dir,
        stage_name=stage_context.stage_name,
        stage_dir=stage_dir,
        prompt_path=reconciliation_prompt_path,
        prompt=reconciliation_prompt,
        budget=budget("reconciliation", reconciliation_prompt, 30000, 60000),
        included_sources=[
            source_manifest_item("json_schema_contract", "reconciliation_decisions.v2", json_dumps_fn=stage_runtime.json_dumps),
            source_manifest_item(
                "session_metadata",
                {
                    "session_id": session["session_id"],
                    "project_id": session["project_id"],
                    "client_type": session["client_type"],
                },
                json_dumps_fn=stage_runtime.json_dumps,
            ),
            source_manifest_item("semantic_proposals", semantic_payload, json_dumps_fn=stage_runtime.json_dumps, included_chars=30000, limit=30000),
            source_manifest_item("candidate_matches", candidates, json_dumps_fn=stage_runtime.json_dumps, included_chars=18000, limit=18000),
        ],
        excluded_sources=[
            {"name": "raw_conversation_window", "reason": "reconciliation uses validated proposals and bounded candidates only"},
            {"name": "raw_tool_inputs", "reason": "not part of semantic reconciliation"},
            {"name": "raw_tool_outputs", "reason": "not part of semantic reconciliation"},
            {"name": "operational_facts", "reason": "kept SQLite-only and not semantic candidates"},
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
            artifact_role="reconciliation_prompt_manifest",
            path=reconciliation_manifest_path,
        )

    reconciliation_raw_path = run_dir / stage_dir / "raw-output.json"
    reused_reconciliation_payload = (
        load_reused_stage_json(
            conn,
            reuse_from_dream_run_id,
            stage_context.stage_name,
            root_fn=stage_runtime.root,
            read_text_fn=stage_runtime.read_text,
        )
        if semantic_id_map is not None
        else None
    )
    if reused_reconciliation_payload is not None:
        reconciliation_payload = remap_reconciliation_payload_for_rerun(
            reused_reconciliation_payload,
            dream_run_id=context.dream_run_id,
            session_id=context.session_id,
            proposal_id_map=semantic_id_map,
            safe_slug_fn=stage_runtime.safe_slug,
            json_dumps_fn=stage_runtime.json_dumps,
        )
        reconciliation_text = stage_runtime.json_dumps(reconciliation_payload)
        stage_runtime.write_text(reconciliation_raw_path, reconciliation_text + "\n")
        reconciliation_meta: dict[str, Any] = {
            "reused_from_dream_run_id": reuse_from_dream_run_id,
            "reused_stage": stage_context.stage_name,
            "token_usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        }
    else:
        reconciliation_text, reconciliation_meta = invoke_runner(
            runner,
            runner_model,
            reconciliation_prompt,
            reconciliation_raw_path,
            int(runner_timeout or 1800),
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
            reconciliation_schema_version=RECONCILIATION_SCHEMA_VERSION,
            json_dumps_fn=stage_runtime.json_dumps,
            allow_empty_output=True,
        )
        reconciliation_fallback_reason: str | None = None
        try:
            reconciliation_payload, json_diagnostics = extract_json_with_diagnostics(reconciliation_text)
            reconciliation_payload["dream_run_id"] = context.dream_run_id
            reconciliation_payload["session_id"] = context.session_id
            reconciliation_meta = {
                **(reconciliation_meta if isinstance(reconciliation_meta, dict) else {}),
                "json_parse": json_diagnostics,
            }
        except Exception as exc:  # noqa: BLE001
            reconciliation_fallback_reason = str(exc)
            reconciliation_payload = deterministic_reconciliation_payload(
                semantic_payload,
                candidates,
                dream_run_id=context.dream_run_id,
                session_id=context.session_id,
                safe_slug_fn=stage_runtime.safe_slug,
            )
            reconciliation_meta = {
                **(reconciliation_meta if isinstance(reconciliation_meta, dict) else {}),
                "fallback_to_deterministic_reconciliation": True,
                "fallback_reason": reconciliation_fallback_reason,
                "json_parse_error_code": getattr(exc, "code", None),
                "json_parse": getattr(exc, "diagnostics", {"strategy": "failed"}),
            }

    reconciliation_payload = apply_reconciliation_guardrails(
        reconciliation_payload,
        semantic_payload=semantic_payload,
    )

    reconciliation_validation = validate_reconciliation_payload_with_context(
        reconciliation_payload,
        semantic_payload=semantic_payload,
    )
    if reused_reconciliation_payload is not None:
        reconciliation_validation["reused_from_dream_run_id"] = reuse_from_dream_run_id
    elif not reconciliation_validation["ok"]:
        reconciliation_payload = deterministic_reconciliation_payload(
            semantic_payload,
            candidates,
            dream_run_id=context.dream_run_id,
            session_id=context.session_id,
            safe_slug_fn=stage_runtime.safe_slug,
        )
        reconciliation_meta = {
            **(reconciliation_meta if isinstance(reconciliation_meta, dict) else {}),
            "fallback_to_deterministic_reconciliation": True,
            "fallback_reason": reconciliation_validation["errors"],
        }
        reconciliation_payload = apply_reconciliation_guardrails(
            reconciliation_payload,
            semantic_payload=semantic_payload,
        )
        reconciliation_validation = validate_reconciliation_payload_with_context(
            reconciliation_payload,
            semantic_payload=semantic_payload,
        )
        reconciliation_validation["fallback_to_deterministic_reconciliation"] = True
    if reconciliation_meta.get("fallback_to_deterministic_reconciliation"):
        reconciliation_validation["fallback_to_deterministic_reconciliation"] = True
        reconciliation_validation["fallback_reason"] = reconciliation_meta.get("fallback_reason")

    decisions_path = stage_runtime.write_json(run_dir / stage_dir / "decisions.json", reconciliation_payload)
    stage_runtime.write_json(run_dir / stage_dir / "validation.json", reconciliation_validation)
    if not reconciliation_validation["ok"]:
        raise RuntimeError(f"reconciliation validation failed: {reconciliation_validation['errors']}")

    with conn:
        stage_runtime.insert_reconciliation(
            conn,
            context.dream_run_id,
            stage_id,
            reconciliation_payload,
        )
    stage_runtime.stage_finish(
        conn,
        stage_run_id=stage_id,
        started_mono=started_mono,
        prompt_path=reconciliation_prompt_path,
        raw_output_path=reconciliation_raw_path,
        parsed_output_path=decisions_path,
        metadata=reconciliation_meta,
        validation=reconciliation_validation,
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
        "reconciliation_payload": reconciliation_payload,
        "reconciliation_validation": reconciliation_validation,
        "reconciliation_meta": reconciliation_meta,
        "prompt_path": str(reconciliation_prompt_path),
        "raw_output_path": str(reconciliation_raw_path),
        "parsed_output_path": str(decisions_path),
        "artifact_path": str(reconciliation_manifest_path),
        "proposal_count": len(semantic_payload.get("entities", [])),
        "relation_count": len(semantic_payload.get("relations", [])),
        "decision_count": len(reconciliation_payload.get("decisions", [])),
    }
