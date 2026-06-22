"""Dream runner policy and output-contract helpers for Application layer."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence, Tuple

from ..infrastructure.config import ROOT, json_dumps, safe_slug, utc_now
from .dreaming.runners import cursor_agent_auth_status, model_for_runner, runner_available, runner_for_session


def _runner_requested_implicitly(requested_runner: str | None, *, map_deterministic_to_session: bool) -> bool:
    runner = (requested_runner or "").strip()
    if not runner or runner == "same-as-session":
        return True
    return map_deterministic_to_session and runner in {"deterministic", "none"}


def _runner_auth_ready(conn: sqlite3.Connection | None, runner: str) -> bool:
    if runner != "cursor":
        return True
    auth_ready, _detail = cursor_agent_auth_status()
    if auth_ready:
        return True
    return False


def _runner_readiness_error(runner: str) -> str:
    if runner != "cursor":
        return f"{runner} dream runner is not ready"
    _ready, detail = cursor_agent_auth_status()
    lowered = str(detail or "").lower()
    if "executable is missing" in lowered or "not found" in lowered:
        return "cursor dream runner is not ready; install `cursor-agent` first, then run `cursor-agent login`"
    return "cursor dream runner is not ready; run `cursor-agent login` or set `CURSOR_API_KEY`"


def next_undreamed_range(conn: sqlite3.Connection, session_id: str, last_event_seq: int) -> tuple[int, int] | None:
    if last_event_seq <= 0:
        return None
    covered = [
        (int(row["input_event_seq_from"]), int(row["input_event_seq_to"]))
        for row in conn.execute(
            """
            select input_event_seq_from, input_event_seq_to
            from dream_runs
            where session_id = ? and status = 'succeeded'
            order by input_event_seq_from, input_event_seq_to
            """,
            (session_id,),
        )
    ]
    seq = 1
    for start, end in covered:
        if end < seq:
            continue
        if start > seq:
            return seq, min(start - 1, last_event_seq)
        seq = max(seq, end + 1)
        if seq > last_event_seq:
            return None
    if seq <= last_event_seq:
        return seq, last_event_seq
    return None


def contiguous_dreamed_event_seq(conn: sqlite3.Connection, session_id: str, last_event_seq: int) -> int:
    seq = 1
    for row in conn.execute(
        """
        select input_event_seq_from, input_event_seq_to
        from dream_runs
        where session_id = ? and status = 'succeeded'
        order by input_event_seq_from, input_event_seq_to
        """,
        (session_id,),
    ):
        start = int(row["input_event_seq_from"])
        end = int(row["input_event_seq_to"])
        if end < seq:
            continue
        if start > seq:
            break
        seq = max(seq, end + 1)
        if seq > last_event_seq:
            return last_event_seq
    return min(seq - 1, last_event_seq)


def resolve_dream_runner(
    session: sqlite3.Row,
    requested_runner: str | None,
    requested_model: str | None = None,
    *,
    conn: sqlite3.Connection | None = None,
    map_deterministic_to_session: bool = False,
    allow_standalone_deterministic: bool = True,
) -> Tuple[str, str | None]:
    implicit_request = _runner_requested_implicitly(requested_runner, map_deterministic_to_session=map_deterministic_to_session)
    runner = requested_runner or "same-as-session"
    if map_deterministic_to_session and runner in {"deterministic", "none", ""}:
        runner = "same-as-session"
    runner = runner_for_session(session, runner)
    model_request = requested_model

    if implicit_request and not _runner_auth_ready(conn, runner):
        raise RuntimeError(_runner_readiness_error(runner))

    if not allow_standalone_deterministic and runner in {"deterministic", "none"}:
        raise RuntimeError("Dream Pipeline 2.0 requires an LLM runner; deterministic dream runner is not allowed")

    if not runner_available(runner):
        raise RuntimeError(f"missing runner: {runner}")

    return runner, model_for_runner(runner, model_request)


def _to_relative_path(path: str | Path) -> str:
    candidate = Path(path)
    if candidate.is_absolute():
        try:
            return str(candidate.relative_to(ROOT))
        except ValueError:
            return str(candidate)
    return str(candidate)


def _artifact_stats(path: str | Path) -> tuple[int, int]:
    resolved = ROOT / _to_relative_path(path)
    if not resolved.exists() or not resolved.is_file():
        return 0, 0
    try:
        byte_count = resolved.stat().st_size
    except OSError:
        byte_count = 0
    try:
        char_count = len(resolved.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        char_count = 0
    return byte_count, char_count


def register_dream_stage_run(
    conn: sqlite3.Connection,
    dream_run_id: str,
    session_id: str,
    stage_name: str,
    stage_order: int,
    *,
    runner: str | None = None,
    model: str | None = None,
    event_from: int | None = None,
    event_to: int | None = None,
    created_by: str = "dream-v2",
) -> str:
    stage_run_id = f"stage_{safe_slug(dream_run_id)}_{safe_slug(stage_name)}_{stage_order}_{safe_slug(utc_now())}"
    started_at = utc_now()
    with conn:
        conn.execute(
            """
            insert into dream_stage_runs (
              stage_run_id, dream_run_id, session_id, stage_name, stage_order, runner, model,
              status, started_at, input_event_seq_from, input_event_seq_to, created_by
            ) values (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (
                stage_run_id,
                dream_run_id,
                session_id,
                stage_name,
                stage_order,
                runner,
                model,
                started_at,
                event_from,
                event_to,
                created_by,
            ),
        )
    return stage_run_id


def finalize_dream_stage_run(
    conn: sqlite3.Connection,
    stage_run_id: str,
    *,
    status: str,
    finished_at: str,
    duration_ms: int | None = None,
    prompt_path: str | Path | None = None,
    raw_output_path: str | Path | None = None,
    parsed_output_path: str | Path | None = None,
    artifact_path: str | Path | None = None,
    metadata: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """
            update dream_stage_runs
            set status = ?,
                finished_at = ?,
                duration_ms = ?,
                prompt_path = coalesce(?, prompt_path),
                raw_output_path = coalesce(?, raw_output_path),
                parsed_output_path = coalesce(?, parsed_output_path),
                artifact_path = coalesce(?, artifact_path),
                metadata_json = coalesce(?, metadata_json),
                validation_json = coalesce(?, validation_json),
                error_message = ?
            where stage_run_id = ?
            """,
            (
                status,
                finished_at,
                duration_ms,
                _to_relative_path(prompt_path) if prompt_path else None,
                _to_relative_path(raw_output_path) if raw_output_path else None,
                _to_relative_path(parsed_output_path) if parsed_output_path else None,
                _to_relative_path(artifact_path) if artifact_path else None,
                json_dumps(metadata or {}),
                json_dumps(validation or {}),
                error_message,
                stage_run_id,
            ),
        )


def register_dream_artifact(
    conn: sqlite3.Connection,
    *,
    dream_run_id: str,
    stage_run_id: str | None,
    session_id: str,
    artifact_kind: str,
    artifact_role: str,
    path: str | Path,
    metadata: dict[str, Any] | None = None,
    created_by: str = "dream-v2",
) -> None:
    rel_path = _to_relative_path(path)
    byte_count, char_count = _artifact_stats(path)
    artifact_id = f"artifact_{safe_slug(dream_run_id)}_{safe_slug(artifact_role)}_{safe_slug(utc_now())}"
    with conn:
        conn.execute(
            """
            insert into dream_artifacts (
              dream_artifact_id, dream_run_id, stage_run_id, session_id,
              artifact_kind, artifact_role, path, sha256, byte_count, char_count,
              created_at, metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                dream_run_id,
                stage_run_id,
                session_id,
                artifact_kind,
                artifact_role,
                rel_path,
                None,
                byte_count,
                char_count,
                utc_now(),
                json_dumps(metadata or {}),
            ),
        )


def _as_json_text(value: Sequence[str] | None) -> str | None:
    if value is None:
        return None
    return json_dumps(list(value))


def mark_dream_run_terminal(
    conn: sqlite3.Connection,
    *,
    dream_run_id: str,
    finished_at: str,
    status: str,
    pipeline_status: str,
    output_summary_path: str | None = None,
    output_memory_paths: Sequence[str] | None = None,
    error_message: str | None = None,
    failed_stage: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """
            update dream_runs
            set finished_at = ?,
                status = ?,
                pipeline_status = ?,
                output_summary_path = coalesce(?, output_summary_path),
                output_memory_paths_json = coalesce(?, output_memory_paths_json),
                failed_stage = ?,
                error_message = ?
            where dream_run_id = ?
            """,
            (
                finished_at,
                status,
                pipeline_status,
                output_summary_path,
                _as_json_text(output_memory_paths),
                failed_stage,
                error_message,
                dream_run_id,
            ),
        )


__all__ = [
    "contiguous_dreamed_event_seq",
    "next_undreamed_range",
    "register_dream_artifact",
    "register_dream_stage_run",
    "finalize_dream_stage_run",
    "mark_dream_run_terminal",
    "resolve_dream_runner",
]
