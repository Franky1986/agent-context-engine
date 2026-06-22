"""Context and contract objects for the Dreaming v2 refactor path."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlite3

from ....ports.clock import Clock
from ....ports.filesystem import FileSystem
from ....ports.repositories.sqlite import SQLiteConnectionProvider


@dataclass(frozen=True)
class DreamV2RunArtifacts:
    """Artifacts produced during a v2 dream run."""

    project_dream_path: Path | None = None
    run_dir: Path | None = None
    summary_path: Path | None = None
    audit_paths: dict[str, Path] = field(default_factory=dict)


@dataclass(frozen=True)
class DreamV2StageContext:
    """Shared context for one stage during a run."""

    stage_name: str
    stage_order: int
    stage_run_id: str
    raw_output_path: Path | None = None
    parsed_output_path: Path | None = None
    artifact_path: Path | None = None
    output_started_at: str | None = None
    output_finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DreamV2Context:
    """Dependency bundle for one dream run.

    This is intentionally additive. It is not yet wired end-to-end into `v2.py`.
    """

    conn: sqlite3.Connection
    dream_run_id: str
    session_id: str
    event_from: int
    event_to: int
    run_dir: Path
    dry_run: bool
    clock: Clock
    file_system: FileSystem
    db_provider: SQLiteConnectionProvider
    run_artifacts: DreamV2RunArtifacts = field(default_factory=DreamV2RunArtifacts)


@dataclass(frozen=True)
class DreamV2RunSummary:
    """Execution summary object for future orchestration handoff."""

    conn: sqlite3.Connection
    args: Any
    context: DreamV2Context
