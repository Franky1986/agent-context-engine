from __future__ import annotations

import argparse
import os
from pathlib import Path
import sqlite3
from typing import Protocol

from ...infrastructure.db import connect
from .adapters import deterministic_graph_patch, graph_artifact_path, llm_graph_run, write_graph_artifact
from .operations import graph_extract_for_session, graph_source_paths, graph_structure_for_session


class GraphMaterializationPort(Protocol):
    def graph_extract_path_for_dream(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        dream_row: sqlite3.Row,
    ) -> Path:
        ...

    def graph_structure_for_dream_with_reopened_db(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        dream_row: sqlite3.Row,
        *,
        runner: str,
        runner_model: str | None,
        timeout: int,
        facts_path: Path | None,
        args: argparse.Namespace | None = None,
    ) -> tuple[Path, sqlite3.Connection]:
        ...


class DefaultGraphMaterializationPort(GraphMaterializationPort):
    def _resolve_graph_runner(
        self,
        *,
        args: argparse.Namespace | None,
        runner: str,
        runner_model: str | None,
    ) -> tuple[str, str | None]:
        if args is None:
            return runner, runner_model
        requested_graph_runner = (
            getattr(args, "graph_runner", None)
            or os.environ.get("AGENT_MEMORY_DREAM_GRAPH_RUNNER")
            or "same-as-session"
        )
        graph_runner = runner if requested_graph_runner == "same-as-session" else requested_graph_runner
        requested_graph_runner_model = getattr(args, "graph_runner_model", None)
        graph_runner_model = requested_graph_runner_model or (runner_model if graph_runner == runner else None)
        return graph_runner, graph_runner_model

    def graph_structure_for_dream_with_reopened_db(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        dream_row: sqlite3.Row,
        *,
        runner: str,
        runner_model: str | None,
        timeout: int,
        facts_path: Path | None,
        args: argparse.Namespace | None = None,
    ) -> tuple[Path, sqlite3.Connection]:
        graph_runner, graph_runner_model = self._resolve_graph_runner(
            args=args,
            runner=runner,
            runner_model=runner_model,
        )
        if graph_runner not in {"codex", "claude", "cursor", "antigravity", "gemini", "opencode"}:
            patch_path = graph_structure_for_session(
                conn,
                session,
                dream_run=dream_row,
                runner=graph_runner,
                model=graph_runner_model,
                timeout=timeout,
                facts_path=facts_path,
            )
            return patch_path, conn

        patch = deterministic_graph_patch(conn, session, dream_run=dream_row)
        path = graph_artifact_path("patches", f"graph_patch_{dream_row['dream_run_id']}")
        source_paths = graph_source_paths(dream_row, facts_path)
        artifact_runner = graph_runner
        conn.close()
        conn = None
        try:
            patch, llm_source_paths = llm_graph_run(
                session,
                dream_row,
                patch,
                runner=graph_runner,
                model=graph_runner_model,
                timeout=timeout,
            )
            source_paths.extend(llm_source_paths)
            artifact_runner = f"{graph_runner}:llm"
        except Exception as exc:  # noqa: BLE001
            patch["generated_by"] = f"{graph_runner}:deterministic-graph-fallback"
            patch["llm_structuring_error"] = str(exc)
            source_paths.append(f"llm_graph_error:{str(exc)[:500]}")
            artifact_runner = f"{graph_runner}:deterministic-fallback"
        conn = connect()
        write_graph_artifact(
            conn,
            patch=patch,
            artifact_type="patch",
            path=path,
            session_id=session["session_id"],
            dream_run_id=dream_row["dream_run_id"],
            runner=artifact_runner,
            source_paths=source_paths,
        )
        return path, conn

    def graph_extract_path_for_dream(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        dream_row: sqlite3.Row,
    ) -> Path:
        return graph_extract_for_session(conn, session, dream_run=dream_row)


def graph_materialization_port() -> GraphMaterializationPort:
    return DefaultGraphMaterializationPort()


def graph_structure_for_dream_with_reopened_db(
    conn: sqlite3.Connection,
    session: sqlite3.Row,
    dream_row: sqlite3.Row,
    *,
    runner: str,
    runner_model: str | None,
    timeout: int,
    facts_path: Path | None,
    args: argparse.Namespace | None = None,
) -> tuple[Path, sqlite3.Connection]:
    return graph_materialization_port().graph_structure_for_dream_with_reopened_db(
        conn,
        session,
        dream_row,
        runner=runner,
        runner_model=runner_model,
        timeout=timeout,
        facts_path=facts_path,
        args=args,
    )


def graph_extract_path_for_dream(conn: sqlite3.Connection, session: sqlite3.Row, dream_row: sqlite3.Row) -> Path:
    return graph_materialization_port().graph_extract_path_for_dream(conn, session, dream_row)
