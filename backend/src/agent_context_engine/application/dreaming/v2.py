from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from ..dream import contiguous_dreamed_event_seq, next_undreamed_range, resolve_dream_runner
from ..graph import GRAPH_SCHEMA_VERSION
from ...adapters.runners.codex import detect_client_version, transcript_mtime
from ...ports.clock import Clock
from ...ports.filesystem import FileSystem
from ...ports.repositories.sqlite import SQLiteConnectionProvider
from .memory import append_project_memory_ref
from .v2_infrastructure import (
    default_clock,
    default_db_provider,
    default_file_system,
    default_lock_provider,
    default_text_tools,
    dream_dir,
    json_dumps,
    memory_dir,
    root_path,
    safe_slug,
    utc_now,
)
from .v2_ports import LockProvider, TextTools
from .v2_refactor import runtime as refactor_runtime
from .v2_refactor.compat import (
    DREAM_DIR,
    MEMORY_DIR,
    RECONCILIATION_SCHEMA_VERSION,
    ROOT,
    SEMANTIC_SCHEMA_VERSION,
    _apply_persistence,
    _apply_semantic_guardrails,
    _candidate_search,
    _deterministic_reconciliation_payload,
    _deterministic_semantic_payload,
    _extract_json,
    _extract_operational,
    _insert_reconciliation,
    _insert_semantic_proposals,
    _plain_event_window,
    _sync_semantic_projection,
    _validate_reconciliation_payload_with_context,
    _validate_semantic_payload,
    build_dream_prompt,
    extract_session_brief,
    neo4j_query_candidate_rows,
    sync_graph_patch,
)
from .v2_refactor.context import DreamV2Context, DreamV2RunArtifacts, DreamV2StageContext
from .v2_refactor.orchestrator import (
    CommandRunnerDependencies,
    SessionRunnerDependencies,
    cmd_dream_v2 as cmd_dream_v2_refactored,
    run_v2_for_session as run_v2_for_session_refactored,
)
from .v2_refactor.repositories import DreamV2Repository
from .v2_refactor.services import (
    budget as prompting_budget,
    build_dream_prompt as build_dream_prompt_service,
    repair_missing_graph_patches,
)
from .v2_refactor.stages import (
    run_audit_stage,
    run_candidate_search_stage,
    run_narrative_stage,
    run_normalization_stage,
    run_operational_extraction_stage,
    run_persistence_stage,
    run_reconciliation_stage,
    run_semantic_stage,
    run_window_stage,
)

MAX_STAGE_OUTPUT_BYTES = refactor_runtime.MAX_STAGE_OUTPUT_BYTES


def _default_clock() -> Clock:
    return default_clock()


def _default_file_system() -> FileSystem:
    return default_file_system()


def _default_text_tools() -> TextTools:
    return default_text_tools()


def _default_lock_provider() -> LockProvider:
    return default_lock_provider()


def _default_db_provider() -> SQLiteConnectionProvider:
    return default_db_provider()


def _utc_now() -> str:
    return utc_now()


def _now() -> str:
    return _default_clock().utc_now()


def _json_dumps(value: Any) -> str:
    return json_dumps(value)


def _safe_slug(value: str) -> str:
    return safe_slug(value)


def _root() -> Path:
    return root_path()


def _dream_dir() -> Path:
    return dream_dir()


def _memory_dir() -> Path:
    return memory_dir()


def _connect(init: bool = False, db_provider: SQLiteConnectionProvider | None = None) -> sqlite3.Connection:
    provider = db_provider or _default_db_provider()
    return provider.connect(init=init)


def _read_text_limited(path: Path, limit: int) -> str:
    return _default_text_tools().read_text_limited(path, limit)


def _acquire_lock(name: str, *args: str):
    return _default_lock_provider().acquire(name, *args)


def _release_lock(token: Any) -> None:
    _default_lock_provider().release(token)


def _record_artifact(
    conn: sqlite3.Connection,
    *,
    dream_run_id: str,
    stage_run_id: str | None,
    session_id: str,
    artifact_kind: str,
    artifact_role: str,
    path: Path,
    metadata: dict[str, Any] | None = None,
) -> None:
    refactor_runtime.record_artifact(
        conn,
        dream_run_id=dream_run_id,
        stage_run_id=stage_run_id,
        session_id=session_id,
        artifact_kind=artifact_kind,
        artifact_role=artifact_role,
        path=path,
        metadata=metadata,
    )


def _stage_start(
    conn: sqlite3.Connection,
    *,
    dream_run_id: str,
    session_id: str,
    stage_name: str,
    stage_order: int,
    runner: str | None = None,
    model: str | None = None,
    event_from: int | None = None,
    event_to: int | None = None,
) -> tuple[str, str, float]:
    return refactor_runtime.stage_start(
        conn,
        dream_run_id=dream_run_id,
        session_id=session_id,
        stage_name=stage_name,
        stage_order=stage_order,
        runner=runner,
        model=model,
        event_from=event_from,
        event_to=event_to,
    )


def _stage_finish(
    conn: sqlite3.Connection,
    *,
    stage_run_id: str,
    started_mono: float,
    status: str = "succeeded",
    prompt_path: Path | None = None,
    raw_output_path: Path | None = None,
    parsed_output_path: Path | None = None,
    artifact_path: Path | None = None,
    metadata: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    refactor_runtime.stage_finish(
        conn,
        stage_run_id=stage_run_id,
        started_mono=started_mono,
        status=status,
        prompt_path=prompt_path,
        raw_output_path=raw_output_path,
        parsed_output_path=parsed_output_path,
        artifact_path=artifact_path,
        metadata=metadata,
        validation=validation,
        error=error_message,
    )


def _aggregate_stage_metrics(conn: sqlite3.Connection, dream_run_id: str, duration_ms: int | None = None) -> dict[str, int | None]:
    metrics_row = DreamV2Repository(conn).aggregate_stage_metrics(dream_run_id)
    metrics = {
        "duration_ms": duration_ms,
        "prompt_tokens": metrics_row["prompt_tokens"],
        "cached_prompt_tokens": metrics_row["cached_prompt_tokens"],
        "completion_tokens": metrics_row["completion_tokens"],
        "reasoning_tokens": metrics_row["reasoning_tokens"],
        "total_tokens": metrics_row["total_tokens"],
    }
    DreamV2Repository(conn).update_dream_run_metrics(
        dream_run_id=dream_run_id,
        duration_ms=metrics["duration_ms"],
        prompt_tokens=metrics["prompt_tokens"],
        cached_prompt_tokens=metrics["cached_prompt_tokens"],
        completion_tokens=metrics["completion_tokens"],
        reasoning_tokens=metrics["reasoning_tokens"],
        total_tokens=metrics["total_tokens"],
    )
    return metrics


def _last_dream_summary(conn: sqlite3.Connection, session_id: str) -> str:
    paths = DreamV2Repository(conn).fetch_latest_succeeded_dream_output_memory_paths(session_id)
    if not paths:
        return "_No previous dream summary._"
    for item in paths:
        path = _root() / item
        if path.suffix == ".md" and path.exists():
            return _read_text_limited(path, 12000)
    return "_No previous dream summary._"


def _current_session_handover(conn: sqlite3.Connection, session_id: str) -> str:
    path = DreamV2Repository(conn).fetch_latest_session_handover_path(session_id)
    if not path:
        return "_No current handover available._"
    candidate = _root() / path
    if not candidate.exists() or not candidate.is_file():
        return "_No current handover available._"
    text = _read_text_limited(candidate, 12000).strip()
    return text or "_No current handover available._"


def _same_session_semantic_context(conn: sqlite3.Connection, session_id: str) -> dict[str, Any]:
    repo = DreamV2Repository(conn)
    return {
        "entities": repo.list_session_semantic_entities(session_id),
        "relations": repo.list_session_semantic_relations(session_id),
    }


def _budget(name: str, prompt: str, target: int, hard: int) -> dict[str, Any]:
    return prompting_budget(name, prompt, target, hard)


def _session_runner_dependencies() -> SessionRunnerDependencies:
    return SessionRunnerDependencies(
        acquire_lock=_acquire_lock,
        release_lock=_release_lock,
        connect=_connect,
        repo_cls=DreamV2Repository,
        resolve_dream_runner=resolve_dream_runner,
        next_undreamed_range=next_undreamed_range,
        now=_now,
        safe_slug=_safe_slug,
        dream_dir=_dream_dir,
        detect_client_version=detect_client_version,
        transcript_mtime=transcript_mtime,
        last_dream_summary=_last_dream_summary,
        current_session_handover=_current_session_handover,
        same_session_semantic_context=_same_session_semantic_context,
        default_clock=_default_clock,
        default_file_system=_default_file_system,
        default_db_provider=_default_db_provider,
        run_artifacts_cls=DreamV2RunArtifacts,
        context_cls=DreamV2Context,
        stage_context_cls=DreamV2StageContext,
        build_dream_prompt=build_dream_prompt_service,
        json_dumps=_json_dumps,
        plain_event_window=_plain_event_window,
        budget=_budget,
        run_window_stage=run_window_stage,
        run_narrative_stage=run_narrative_stage,
        run_semantic_stage=run_semantic_stage,
        run_normalization_stage=run_normalization_stage,
        run_operational_extraction_stage=run_operational_extraction_stage,
        run_candidate_search_stage=run_candidate_search_stage,
        run_reconciliation_stage=run_reconciliation_stage,
        run_persistence_stage=run_persistence_stage,
        run_audit_stage=run_audit_stage,
        root=_root,
        append_project_memory_ref=append_project_memory_ref,
        extract_session_brief=extract_session_brief,
        record_artifact=_record_artifact,
        aggregate_stage_metrics=_aggregate_stage_metrics,
        contiguous_dreamed_event_seq=contiguous_dreamed_event_seq,
    )


def _command_runner_dependencies() -> CommandRunnerDependencies:
    return CommandRunnerDependencies(
        acquire_lock=_acquire_lock,
        release_lock=_release_lock,
        connect=_connect,
        repo_cls=DreamV2Repository,
        repair_missing_graph_patches=repair_missing_graph_patches,
        run_v2_for_session=run_v2_for_session,
    )


def run_v2_for_session(args: argparse.Namespace, session_id: str) -> int:
    return run_v2_for_session_refactored(args, session_id, deps=_session_runner_dependencies())


def cmd_dream_v2(args: argparse.Namespace) -> int:
    return cmd_dream_v2_refactored(args, deps=_command_runner_dependencies())


__all__ = [
    "DREAM_DIR",
    "GRAPH_SCHEMA_VERSION",
    "MAX_STAGE_OUTPUT_BYTES",
    "MEMORY_DIR",
    "RECONCILIATION_SCHEMA_VERSION",
    "ROOT",
    "SEMANTIC_SCHEMA_VERSION",
    "_apply_persistence",
    "_apply_semantic_guardrails",
    "_budget",
    "_candidate_search",
    "_command_runner_dependencies",
    "_current_session_handover",
    "_deterministic_reconciliation_payload",
    "_deterministic_semantic_payload",
    "_dream_dir",
    "_extract_json",
    "_extract_operational",
    "_insert_reconciliation",
    "_insert_semantic_proposals",
    "_json_dumps",
    "_last_dream_summary",
    "_memory_dir",
    "_plain_event_window",
    "_record_artifact",
    "_root",
    "_same_session_semantic_context",
    "_session_runner_dependencies",
    "_stage_finish",
    "_stage_start",
    "_sync_semantic_projection",
    "_validate_reconciliation_payload_with_context",
    "_validate_semantic_payload",
    "build_dream_prompt",
    "cmd_dream_v2",
    "extract_session_brief",
    "neo4j_query_candidate_rows",
    "run_v2_for_session",
    "sync_graph_patch",
]
