from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Protocol

from ..graphing.operations import (
    graph_extract_for_session as _graph_extract_for_session,
    graph_source_paths as _graph_source_paths,
    graph_structure_for_session as _graph_structure_for_session,
    latest_dream_run as _latest_dream_run,
)


class GraphOperationsPort(Protocol):
    """Domain-facing port for graphing operation use-cases."""

    def graph_extract_for_session(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        *,
        dream_run: sqlite3.Row | None = None,
    ) -> Path:
        ...

    def graph_structure_for_session(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        *,
        dream_run: sqlite3.Row | None = None,
        runner: str = "deterministic",
        model: str | None = None,
        timeout: int = 1800,
        facts_path: Path | None = None,
    ) -> Path:
        ...

    def graph_source_paths(
        self,
        dream_run: sqlite3.Row | None,
        facts_path: Path | None = None,
    ) -> list[str]:
        ...

    def latest_dream_run(self, conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
        ...


class DefaultGraphOperationsPort(GraphOperationsPort):
    def graph_extract_for_session(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        *,
        dream_run: sqlite3.Row | None = None,
    ) -> Path:
        return _graph_extract_for_session(
            conn,
            session,
            dream_run=dream_run,
        )

    def graph_structure_for_session(
        self,
        conn: sqlite3.Connection,
        session: sqlite3.Row,
        *,
        dream_run: sqlite3.Row | None = None,
        runner: str = "deterministic",
        model: str | None = None,
        timeout: int = 1800,
        facts_path: Path | None = None,
    ) -> Path:
        return _graph_structure_for_session(
            conn,
            session,
            dream_run=dream_run,
            runner=runner,
            model=model,
            timeout=timeout,
            facts_path=facts_path,
        )

    def graph_source_paths(
        self,
        dream_run: sqlite3.Row | None,
        facts_path: Path | None = None,
    ) -> list[str]:
        return _graph_source_paths(dream_run, facts_path=facts_path)

    def latest_dream_run(self, conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
        return _latest_dream_run(conn, session_id)


def graph_operations_port() -> GraphOperationsPort:
    return DefaultGraphOperationsPort()


def graph_extract_for_session(
    conn: sqlite3.Connection,
    session: sqlite3.Row,
    *,
    dream_run: sqlite3.Row | None = None,
) -> Path:
    return graph_operations_port().graph_extract_for_session(conn, session, dream_run=dream_run)


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
    return graph_operations_port().graph_structure_for_session(
        conn,
        session,
        dream_run=dream_run,
        runner=runner,
        model=model,
        timeout=timeout,
        facts_path=facts_path,
    )


def graph_source_paths(
    dream_run: sqlite3.Row | None,
    facts_path: Path | None = None,
) -> list[str]:
    return graph_operations_port().graph_source_paths(dream_run, facts_path=facts_path)


def latest_dream_run(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return graph_operations_port().latest_dream_run(conn, session_id)
