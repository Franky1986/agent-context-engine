"""Shared runtime helpers for Dreaming v2 refactor stages.

This keeps the stage layer off the legacy `v2.py` module while preserving the
existing stage lifecycle and artifact contracts.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from time import monotonic
from typing import Any

import sqlite3

from ...graph import GRAPH_SCHEMA_VERSION
from ..v2_infrastructure import (
    default_clock,
    default_command_runner,
    default_file_system,
    default_text_tools,
    json_dumps as infrastructure_json_dumps,
    memory_dir as infrastructure_memory_dir,
    root_path,
    safe_slug as infrastructure_safe_slug,
)
from .repositories import DreamV2Repository
from .services.prompting import plain_event_window as plain_event_window_service
from .services.semantic_payloads import RECONCILIATION_SCHEMA_VERSION, SEMANTIC_SCHEMA_VERSION

MAX_STAGE_OUTPUT_BYTES = 1024 * 1024

SEMANTIC_TO_GRAPH_ENTITY_TYPES = {
    "project": "Project",
    "person": "Person",
    "organization": "Organization",
    "product": "Product",
    "feature": "Feature",
    "decision": "Decision",
    "issue": "Issue",
    "risk": "Risk",
    "preference": "Preference",
    "concept": "Concept",
    "task": "OpenTask",
    "policy": "Policy",
    "schema_proposal": "SchemaProposal",
}

SEMANTIC_TO_GRAPH_RELATION_TYPES = {
    "discusses": "DISCUSSES",
    "depends_on": "DEPENDS_ON",
    "decides": "DECIDES",
    "blocks": "BLOCKS",
    "affects": "AFFECTS",
    "belongs_to_project": "BELONGS_TO_PROJECT",
    "supersedes": "SUPERSEDES",
    "requests": "REQUESTS",
    "resolves": "RESOLVES",
    "mentions_external_project": "MENTIONS_EXTERNAL_PROJECT",
    "schema_proposal": "PROPOSES_TYPE",
}


def default_runner():
    return default_command_runner()


def now() -> str:
    return default_clock().utc_now()


def monotonic_now() -> float:
    return monotonic()


def json_dumps(value: Any) -> str:
    return infrastructure_json_dumps(value)


def safe_slug(value: str) -> str:
    return infrastructure_safe_slug(value)


def root() -> Path:
    return root_path()


def memory_dir() -> Path:
    return infrastructure_memory_dir()


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(root()))
    except ValueError:
        return str(path)


def base_env() -> dict[str, str]:
    return dict(os.environ)


def mock_enabled() -> bool:
    return os.environ.get("AGENT_MEMORY_DREAM_V2_MOCK") == "1"


def read_text(path: Path) -> str:
    return default_file_system().read_text(path)


def read_text_limited(path: Path, limit: int) -> str:
    return default_text_tools().read_text_limited(path, limit)


def redact_embedded_context_artifacts(value: str) -> str:
    return default_text_tools().redact_embedded_context_artifacts(value)


def write_text(path: Path, text: str) -> Path:
    fs = default_file_system()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fs.write_text(tmp, text)
    tmp.replace(path)
    return path


def write_json(path: Path, value: Any) -> Path:
    return write_text(path, json_dumps(value) + "\n")


def plain_event_window(events: list[sqlite3.Row] | list[dict[str, Any]] | list[Any]) -> str:
    return plain_event_window_service(
        events,
        redact_fn=redact_embedded_context_artifacts,
        user_max_chars=2400,
        assistant_max_chars=3200,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_artifact(
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
    text = read_text_limited(path, MAX_STAGE_OUTPUT_BYTES + 1)
    try:
        DreamV2Repository(conn).insert_artifact(
            dream_artifact_id=f"artifact_{safe_slug(dream_run_id)}_{safe_slug(artifact_role)}",
            dream_run_id=dream_run_id,
            stage_run_id=stage_run_id,
            session_id=session_id,
            artifact_kind=artifact_kind,
            artifact_role=artifact_role,
            path=rel(path),
            sha256=_sha256_text(text),
            byte_count=len(text.encode("utf-8")),
            char_count=len(text),
            created_at=now(),
            metadata_json=json_dumps(metadata or {}),
        )
    except sqlite3.OperationalError as exc:
        if "no such table: dream_artifacts" not in str(exc):
            raise
        return
    try:
        conn.commit()
    except sqlite3.OperationalError as exc:
        if "no such table: dream_artifacts" not in str(exc):
            raise
        return
    except sqlite3.ProgrammingError:
        return


def stage_start(
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
    stage_run_id = f"stage_{safe_slug(dream_run_id)}_{stage_order:02d}_{safe_slug(stage_name)}"
    started_at = now()
    DreamV2Repository(conn).insert_stage_start(
        stage_run_id=stage_run_id,
        dream_run_id=dream_run_id,
        session_id=session_id,
        stage_name=stage_name,
        stage_order=stage_order,
        runner=runner,
        model=model,
        event_from=event_from,
        event_to=event_to,
        started_at=started_at,
    )
    conn.commit()
    return stage_run_id, started_at, monotonic_now()


def stage_finish(
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
    error: str | None = None,
) -> None:
    duration_ms = int((monotonic_now() - started_mono) * 1000)
    token_usage = (metadata or {}).get("token_usage") if isinstance(metadata, dict) else None
    token_usage = token_usage if isinstance(token_usage, dict) else {}
    prompt_tokens = token_usage.get("input_tokens") or token_usage.get("prompt_tokens")
    cached_tokens = token_usage.get("cached_input_tokens") or token_usage.get("cached_prompt_tokens")
    completion_tokens = token_usage.get("output_tokens") or token_usage.get("completion_tokens")
    reasoning_tokens = token_usage.get("reasoning_output_tokens") or token_usage.get("reasoning_tokens")
    total_tokens = token_usage.get("total_tokens")
    DreamV2Repository(conn).update_stage_finish(
        stage_run_id=stage_run_id,
        status=status,
        finished_at=now(),
        duration_ms=duration_ms,
        prompt_path=rel(prompt_path) if prompt_path else None,
        raw_output_path=rel(raw_output_path) if raw_output_path else None,
        parsed_output_path=rel(parsed_output_path) if parsed_output_path else None,
        artifact_path=rel(artifact_path) if artifact_path else None,
        metadata_json=json_dumps(metadata or {}),
        validation_json=json_dumps(validation or {}),
        error_message=error,
        prompt_tokens=prompt_tokens,
        cached_prompt_tokens=cached_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        total_tokens=total_tokens,
    )
    conn.commit()


def insert_reconciliation(
    conn: sqlite3.Connection,
    dream_run_id: str,
    stage_run_id: str,
    payload: dict[str, Any],
) -> None:
    DreamV2Repository(conn).insert_reconciliation_decisions(
        dream_run_id=dream_run_id,
        stage_run_id=stage_run_id,
        payload=payload,
        schema_version=RECONCILIATION_SCHEMA_VERSION,
        created_at=now(),
    )
    conn.commit()


def semantic_entity_type_to_graph(entity_type: Any) -> str:
    value = str(entity_type or "").strip()
    return SEMANTIC_TO_GRAPH_ENTITY_TYPES.get(value, value)


def semantic_relation_type_to_graph(relation_type: Any) -> str:
    value = str(relation_type or "").strip()
    return SEMANTIC_TO_GRAPH_RELATION_TYPES.get(value, value)
