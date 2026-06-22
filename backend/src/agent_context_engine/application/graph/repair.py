from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from ...infrastructure.config import ROOT
from .materialization import (
    graph_extract_path_for_dream,
    graph_structure_for_dream_with_reopened_db,
)


def _as_relative_path(path: Path | str) -> str:
    if not path:
        return ""
    if not isinstance(path, Path):
        return str(path)
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def missing_patch_dream_runs(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            select *
            from dream_runs dr
            where dr.session_id = ?
              and dr.status = 'succeeded'
              and not exists (
                select 1
                from graph_artifacts ga
                where ga.dream_run_id = dr.dream_run_id
                  and ga.artifact_type = 'patch'
                  and ga.status = 'valid'
              )
            order by dr.input_event_seq_from, dr.input_event_seq_to, dr.started_at
            """,
            (session_id,),
        )
    )


def ensure_graph_patch_for_dream(
    conn: sqlite3.Connection,
    session: sqlite3.Row,
    dream_row: sqlite3.Row,
    *,
    runner: str,
    runner_model: str | None,
    timeout: int,
    args: argparse.Namespace | None = None,
) -> tuple[list[str], sqlite3.Connection]:
    facts_path = graph_extract_path_for_dream(conn, session, dream_row)
    patch_path, conn = graph_structure_for_dream_with_reopened_db(
        conn,
        session,
        dream_row,
        runner=runner,
        runner_model=runner_model,
        timeout=timeout,
        facts_path=facts_path,
        args=args,
    )
    return [_as_relative_path(facts_path), _as_relative_path(patch_path)], conn


__all__ = ["ensure_graph_patch_for_dream", "missing_patch_dream_runs"]
