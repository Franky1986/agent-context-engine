"""Compatibility helpers for tests and transitional callers.

This module preserves the old helper-shaped API surface outside `v2.py` so
callers can migrate off the monolithic module before the final cutover.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from ..memory import extract_session_brief
from ..v2_infrastructure import dream_dir, json_dumps, memory_dir, root_path, safe_slug, utc_now
from ...graph import GRAPH_SCHEMA_VERSION, neo4j_query_candidate_rows, sync_graph_patch
import agent_context_engine.application.dreaming.v2_refactor.services.candidate_search as candidate_search_module
from . import runtime as refactor_runtime
from .services import (
    RECONCILIATION_SCHEMA_VERSION,
    SEMANTIC_SCHEMA_VERSION,
    apply_persistence,
    apply_semantic_guardrails,
    build_dream_prompt,
    deterministic_reconciliation_payload,
    deterministic_semantic_payload,
    extract_json,
    extract_operational_facts,
    insert_semantic_proposals,
    search_candidates,
    sync_semantic_projection,
    validate_reconciliation_payload_with_context,
    validate_semantic_payload,
)

ROOT = root_path()
DREAM_DIR = dream_dir()
MEMORY_DIR = memory_dir()


def _now() -> str:
    return utc_now()


def _json_dumps(value: Any) -> str:
    return json_dumps(value)


def _safe_slug(value: str) -> str:
    return safe_slug(value)


def _plain_event_window(events: list[sqlite3.Row]) -> str:
    return refactor_runtime.plain_event_window(events)


def _extract_json(text: str) -> Any:
    return extract_json(text)


def _validate_semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return validate_semantic_payload(payload, semantic_schema_version=SEMANTIC_SCHEMA_VERSION)


def _validate_reconciliation_payload_with_context(payload: dict[str, Any], *, semantic_payload: dict[str, Any]) -> dict[str, Any]:
    return validate_reconciliation_payload_with_context(payload, semantic_payload=semantic_payload)


def _apply_semantic_guardrails(payload: dict[str, Any]) -> dict[str, Any]:
    return apply_semantic_guardrails(payload)


def _deterministic_semantic_payload(
    session: sqlite3.Row,
    events: list[sqlite3.Row],
    dream_markdown: str,
    *,
    dream_run_id: str,
    event_from: int,
    event_to: int,
) -> dict[str, Any]:
    return deterministic_semantic_payload(
        session,
        events,
        dream_markdown,
        dream_run_id=dream_run_id,
        event_from=event_from,
        event_to=event_to,
        safe_slug_fn=_safe_slug,
        semantic_schema_version=SEMANTIC_SCHEMA_VERSION,
    )


def _deterministic_reconciliation_payload(
    semantic_payload: dict[str, Any],
    candidates: dict[str, Any],
    *,
    dream_run_id: str,
    session_id: str,
) -> dict[str, Any]:
    return deterministic_reconciliation_payload(
        semantic_payload,
        candidates,
        dream_run_id=dream_run_id,
        session_id=session_id,
        safe_slug_fn=_safe_slug,
    )


def _extract_operational(conn: sqlite3.Connection, dream_run_id: str, session_id: str, event_from: int, event_to: int) -> dict[str, Any]:
    return extract_operational_facts(
        conn=conn,
        dream_run_id=dream_run_id,
        session_id=session_id,
        event_from=event_from,
        event_to=event_to,
        safe_slug_fn=_safe_slug,
        now_fn=_now,
        json_dumps_fn=_json_dumps,
    )


def _candidate_search(conn: sqlite3.Connection, payload: dict[str, Any], args: argparse.Namespace | None = None, limit_per: int = 8) -> dict[str, Any]:
    candidate_search_module.neo4j_query_candidate_rows = neo4j_query_candidate_rows
    return search_candidates(
        conn=conn,
        payload=payload,
        args=args,
        limit_per=limit_per,
        now_fn=_now,
        safe_slug_fn=_safe_slug,
        json_dumps_fn=_json_dumps,
    )


def _insert_semantic_proposals(
    conn: sqlite3.Connection,
    dream_run_id: str,
    stage_run_id: str,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    insert_semantic_proposals(
        conn,
        dream_run_id=dream_run_id,
        stage_run_id=stage_run_id,
        session_id=session_id,
        payload=payload,
        now_fn=_now,
        safe_slug_fn=_safe_slug,
        json_dumps_fn=_json_dumps,
    )


def _insert_reconciliation(
    conn: sqlite3.Connection,
    dream_run_id: str,
    stage_run_id: str,
    _session_id: str,
    payload: dict[str, Any],
) -> None:
    refactor_runtime.insert_reconciliation(conn, dream_run_id, stage_run_id, payload)


def _apply_persistence(conn: sqlite3.Connection, dream_run_id: str) -> dict[str, Any]:
    return apply_persistence(
        conn,
        dream_run_id,
        now_fn=_now,
        safe_slug_fn=_safe_slug,
        json_dumps_fn=_json_dumps,
    )


def _sync_semantic_projection(
    conn: sqlite3.Connection,
    *,
    args: argparse.Namespace,
    dream_run_id: str,
    run_dir: Path,
    dry_run: bool,
) -> tuple[dict[str, Any], Path]:
    return sync_semantic_projection(
        conn,
        args=args,
        dream_run_id=dream_run_id,
        run_dir=run_dir,
        dry_run=dry_run,
        now_fn=_now,
        safe_slug_fn=_safe_slug,
        rel_fn=refactor_runtime.rel,
        write_json_fn=refactor_runtime.write_json,
        sync_graph_patch_fn=sync_graph_patch,
        projection_schema_version=GRAPH_SCHEMA_VERSION,
        entity_type_to_graph_fn=refactor_runtime.semantic_entity_type_to_graph,
        relation_type_to_graph_fn=refactor_runtime.semantic_relation_type_to_graph,
    )


__all__ = [
    "DREAM_DIR",
    "GRAPH_SCHEMA_VERSION",
    "MEMORY_DIR",
    "RECONCILIATION_SCHEMA_VERSION",
    "ROOT",
    "SEMANTIC_SCHEMA_VERSION",
    "_apply_persistence",
    "_apply_semantic_guardrails",
    "_candidate_search",
    "_deterministic_reconciliation_payload",
    "_deterministic_semantic_payload",
    "_extract_json",
    "_extract_operational",
    "_insert_reconciliation",
    "_insert_semantic_proposals",
    "_plain_event_window",
    "_sync_semantic_projection",
    "_validate_reconciliation_payload_with_context",
    "_validate_semantic_payload",
    "build_dream_prompt",
    "extract_session_brief",
    "neo4j_query_candidate_rows",
    "sync_graph_patch",
]
