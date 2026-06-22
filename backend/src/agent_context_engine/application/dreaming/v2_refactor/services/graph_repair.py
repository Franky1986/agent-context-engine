"""Graph repair helpers for Dreaming v2 refactor path."""

from __future__ import annotations

import argparse
import sqlite3
from typing import TYPE_CHECKING

from ....graph.repair import ensure_graph_patch_for_dream

if TYPE_CHECKING:
    from ..repositories import DreamV2Repository


def repair_missing_graph_patches(
    conn: sqlite3.Connection,
    repo: "DreamV2Repository",
    session: sqlite3.Row,
    *,
    repair_limit: int,
    runner: str,
    runner_model: str | None,
    timeout: int,
    args: argparse.Namespace | None,
) -> tuple[int, list[str], sqlite3.Connection]:
    """Run graph-patch regeneration for missing valid patches in a bounded window.

    Returns:
      - number of repaired dream runs
      - collected produced relative paths
      - potentially updated DB connection
    """
    if repair_limit <= 0:
        return 0, [], conn
    repaired = 0
    repaired_paths: list[str] = []
    for dream_row in repo.list_missing_patch_dream_runs(session["session_id"]):
        if repaired >= repair_limit:
            break
        paths, conn = ensure_graph_patch_for_dream(
            conn,
            session,
            dream_row,
            runner=runner,
            runner_model=runner_model,
            timeout=timeout,
            args=args,
        )
        repaired += 1
        repaired_paths.extend(paths)
    return repaired, repaired_paths, conn


__all__ = ["repair_missing_graph_patches"]
