from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .artifacts import display_path, graph_artifact_path, write_graph_artifact
from .extract import deterministic_graph_patch
from .llm import llm_graph_run


def graph_source_paths(dream_run: sqlite3.Row | None, facts_path: Path | None = None) -> list[str]:
    source_paths: list[str] = []
    if facts_path is not None:
        source_paths.append(display_path(facts_path))
    if dream_run is not None and dream_run["output_memory_paths_json"]:
        try:
            source_paths.extend(json.loads(dream_run["output_memory_paths_json"]))
        except json.JSONDecodeError:
            pass
    if dream_run is not None and dream_run["output_summary_path"]:
        source_paths.append(dream_run["output_summary_path"])
    return source_paths


def latest_dream_run(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        select *
        from dream_runs
        where session_id = ?
        order by coalesce(finished_at, started_at) desc
        limit 1
        """,
        (session_id,),
    ).fetchone()


def graph_extract_for_session(conn: sqlite3.Connection, session: sqlite3.Row, *, dream_run: sqlite3.Row | None = None) -> Path:
    patch = deterministic_graph_patch(conn, session, dream_run=dream_run)
    suffix = dream_run["dream_run_id"] if dream_run is not None else session["session_id"]
    path = graph_artifact_path("facts", f"facts_{suffix}")
    write_graph_artifact(
        conn,
        patch=patch,
        artifact_type="facts",
        path=path,
        session_id=session["session_id"],
        dream_run_id=dream_run["dream_run_id"] if dream_run is not None else None,
        runner="deterministic",
    )
    return path


def graph_structure_for_session(
    conn: sqlite3.Connection,
    session: sqlite3.Row,
    *,
    dream_run: sqlite3.Row | None = None,
    runner: str = "deterministic",
    model: str | None = None,
    timeout: int = 1800,
    facts_path: Path | None = None,
) -> Path:
    patch = deterministic_graph_patch(conn, session, dream_run=dream_run)
    suffix = dream_run["dream_run_id"] if dream_run is not None else session["session_id"]
    path = graph_artifact_path("patches", f"graph_patch_{suffix}")
    source_paths = graph_source_paths(dream_run, facts_path)
    artifact_runner = runner
    if runner in {"codex", "claude", "cursor", "antigravity", "gemini", "opencode"} and dream_run is not None:
        try:
            patch, llm_source_paths = llm_graph_run(session, dream_run, patch, runner=runner, model=model, timeout=timeout)
            source_paths.extend(llm_source_paths)
            artifact_runner = f"{runner}:llm"
        except Exception as exc:  # noqa: BLE001
            patch["generated_by"] = f"{runner}:deterministic-graph-fallback"
            patch["llm_structuring_error"] = str(exc)
            source_paths.append(f"llm_graph_error:{str(exc)[:500]}")
            artifact_runner = f"{runner}:deterministic-fallback"
    else:
        patch["generated_by"] = f"{runner}:graph-structurer"
    write_graph_artifact(
        conn,
        patch=patch,
        artifact_type="patch",
        path=path,
        session_id=session["session_id"],
        dream_run_id=dream_run["dream_run_id"] if dream_run is not None else None,
        runner=artifact_runner,
        source_paths=source_paths,
    )
    return path
