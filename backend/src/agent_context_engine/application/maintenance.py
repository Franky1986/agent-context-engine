from __future__ import annotations

import tarfile
import time
import sqlite3
from pathlib import Path
from typing import Any

from ..ports.clock import Clock
from ..ports.repositories.sqlite import SQLiteConnectionProvider


GRAPH_PRUNE_KINDS = ("llm-runs", "facts", "patches")


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        from ..infrastructure.config import utc_now

        return utc_now()


def _default_clock() -> Clock:
    return _DefaultClock()


def _now() -> str:
    return _default_clock().utc_now()


def _memory_dir() -> Path:
    from ..infrastructure.config import MEMORY_DIR

    return MEMORY_DIR


def _root() -> Path:
    from ..infrastructure.config import ROOT

    return ROOT


class _MaintenanceDbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        from ..adapters.sqlite.request_db import connect as request_db_connect

        return request_db_connect(*args, **kwargs)


def _default_db_provider() -> SQLiteConnectionProvider:
    return _MaintenanceDbProvider()


def _connect(init: bool = True, db_provider: SQLiteConnectionProvider | None = None) -> sqlite3.Connection:
    provider = db_provider or _default_db_provider()
    return provider.connect(init=init)


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(_root().resolve()))
    except ValueError:
        return str(path)


def _path_size(path: Path) -> int:
    try:
        if path.is_file():
            return path.stat().st_size
        if path.is_dir():
            return sum(child.stat().st_size for child in path.rglob("*") if child.is_file())
    except OSError:
        return 0
    return 0


def _remove_empty_parents(path: Path, stop: Path) -> None:
    current = path.parent
    stop = stop.resolve()
    while True:
        try:
            resolved = current.resolve()
        except OSError:
            break
        if resolved == stop or stop not in resolved.parents:
            break
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _delete_path(path: Path, *, stop: Path) -> None:
    if path.is_dir():
        for child in sorted(path.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink(missing_ok=True)
            elif child.is_dir():
                try:
                    child.rmdir()
                except OSError:
                    pass
        try:
            path.rmdir()
        except OSError:
            pass
        _remove_empty_parents(path, stop)
        return
    path.unlink(missing_ok=True)
    _remove_empty_parents(path, stop)


def _graph_artifact_file(root: Path, value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = _root() / path
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"refusing graph artifact outside graph root: {path}") from None
    return path


def _pending_neo4j_patch_paths(conn) -> set[str]:
    rows = conn.execute(
        """
        select ga.path
        from graph_artifacts ga
        where ga.artifact_type = 'patch'
          and ga.status = 'valid'
          and not exists (
            select 1
            from neo4j_imports ni
            where ni.source_patch = ga.path
              and ni.status = 'imported'
          )
        """
    )
    return {str(row["path"]) for row in rows}


def _processed_graph_targets(conn, *, kinds: set[str], include_pending_neo4j: bool) -> list[dict[str, object]]:
    graph_root = _memory_dir() / "graph"
    targets: list[dict[str, object]] = []
    pending_patch_paths = set() if include_pending_neo4j else _pending_neo4j_patch_paths(conn)

    artifact_kind_map = {"facts": "facts", "patches": "patch"}
    for kind, artifact_type in artifact_kind_map.items():
        if kind not in kinds:
            continue
        rows = conn.execute(
            """
            select graph_artifact_id, dream_run_id, path, artifact_type, status
            from graph_artifacts
            where artifact_type = ?
              and status = 'valid'
            order by created_at asc
            """,
            (artifact_type,),
        )
        for row in rows:
            if kind == "patches" and row["path"] in pending_patch_paths:
                continue
            try:
                path = _graph_artifact_file(graph_root, row["path"])
            except ValueError:
                continue
            if not path.exists():
                continue
            targets.append(
                {
                    "kind": kind,
                    "path": path,
                    "size": _path_size(path),
                    "graph_artifact_id": row["graph_artifact_id"],
                    "dream_run_id": row["dream_run_id"],
                }
            )

    if "llm-runs" in kinds:
        processed_dream_ids = {
            str(row["dream_run_id"])
            for row in conn.execute(
                """
                select distinct dream_run_id
                from graph_artifacts
                where dream_run_id is not null
                  and dream_run_id <> ''
                  and status = 'valid'
                """
            )
        }
        llm_root = graph_root / "llm-runs"
        if llm_root.exists():
            for path in sorted(llm_root.iterdir()):
                if not path.is_dir() or path.name not in processed_dream_ids:
                    continue
                targets.append(
                    {
                        "kind": "llm-runs",
                        "path": path,
                        "size": _path_size(path),
                        "graph_artifact_id": None,
                        "dream_run_id": path.name,
                    }
                )
    return targets


def run_graph_prune(
    *,
    kinds: list[str] | tuple[str, ...] | None = None,
    include_pending_neo4j: bool = False,
    archive: str | None = None,
    delete: bool = False,
    show_limit: int = 20,
    db_provider: SQLiteConnectionProvider | None = None,
) -> tuple[list[str], int]:
    kinds_set = set(kinds or GRAPH_PRUNE_KINDS)
    conn = _connect(db_provider=db_provider)
    targets = _processed_graph_targets(conn, kinds=kinds_set, include_pending_neo4j=include_pending_neo4j)
    total_size = sum(int(item["size"] or 0) for item in targets)
    counts: dict[str, int] = {kind: 0 for kind in GRAPH_PRUNE_KINDS}
    sizes: dict[str, int] = {kind: 0 for kind in GRAPH_PRUNE_KINDS}
    for item in targets:
        kind = str(item["kind"])
        counts[kind] = counts.get(kind, 0) + 1
        sizes[kind] = sizes.get(kind, 0) + int(item["size"] or 0)

    lines: list[str] = []
    action = "dry-run"
    if archive:
        action = "archive"
    if delete:
        action = "delete" if not archive else "archive+delete"
    lines.append(f"graph prune {action}: files={len(targets)} bytes={total_size}")
    for kind in GRAPH_PRUNE_KINDS:
        if counts.get(kind):
            lines.append(f"  {kind}: files={counts[kind]} bytes={sizes[kind]}")
    if not include_pending_neo4j:
        pending_count = len(_pending_neo4j_patch_paths(conn))
        if pending_count:
            lines.append(f"  protected pending neo4j patches={pending_count}")

    limit = max(0, int(show_limit))
    for item in targets[:limit]:
        path = item["path"]
        lines.append(f"  {_display_path(path)} bytes={item['size']} kind={item['kind']}")
    if len(targets) > limit:
        lines.append(f"  ... {len(targets) - limit} more")

    if not archive and not delete:
        return lines, 0

    if archive:
        archive_path = Path(archive)
        if not archive_path.is_absolute():
            archive_path = _root() / archive_path
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive_path, "w:gz") as tar:
            for item in targets:
                path = item["path"]
                if isinstance(path, Path) and path.exists():
                    tar.add(path, arcname=_display_path(path))
        lines.append(f"archived graph artifacts: {_display_path(archive_path)}")

    if delete:
        graph_root = _memory_dir() / "graph"
        pruned_at = _now()
        deleted = 0
        deleted_bytes = 0
        artifact_ids = [str(item["graph_artifact_id"]) for item in targets if item.get("graph_artifact_id")]
        for item in targets:
            path = item["path"]
            if not isinstance(path, Path) or not path.exists():
                continue
            deleted_bytes += int(item["size"] or 0)
            _delete_path(path, stop=graph_root)
            deleted += 1
        if artifact_ids:
            with conn:
                conn.executemany(
                    """
                    update graph_artifacts
                    set status = 'pruned',
                        error_message = coalesce(error_message || '\n', '') || ?
                    where graph_artifact_id = ?
                    """,
                    [
                        (f"Pruned from filesystem at {pruned_at}; graph rows remain materialized in SQLite.", artifact_id)
                        for artifact_id in artifact_ids
                    ],
                )
        lines.append(f"deleted graph artifacts: files={deleted} bytes={deleted_bytes}")
    return lines, 0


def run_prune_logs(*, days: int, all: bool, dry_run: bool) -> tuple[list[str], int]:
    root = _memory_dir() / "logs"
    if not root.exists():
        return ["pruned logs: files=0 bytes=0"], 0
    cutoff = time.time() - max(0, int(days)) * 86400
    files = [path for path in root.iterdir() if path.is_file()]
    removed = 0
    removed_bytes = 0
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        if not all and stat.st_mtime > cutoff:
            continue
        if dry_run:
            removed += 1
            removed_bytes += stat.st_size
            continue
        try:
            removed_bytes += stat.st_size
            path.unlink()
            removed += 1
        except OSError:
            continue
    return [f"pruned logs: files={removed} bytes={removed_bytes}"], 0


def run_purge_tool_outputs(*, dry_run: bool) -> tuple[list[str], int]:
    conn = _connect()
    row = conn.execute(
        """
        select count(*) as rows, coalesce(sum(byte_count), 0) as bytes
        from tool_outputs
        where coalesce(content_text, '') <> '' or coalesce(path, '') <> ''
        """
    ).fetchone()
    rows = int(row["rows"] or 0)
    bytes_count = int(row["bytes"] or 0)
    file_root = MEMORY_DIR / "tool-outputs"
    file_count = 0
    file_bytes = 0
    if file_root.exists():
        for path in file_root.rglob("*"):
            if not path.is_file():
                continue
            file_count += 1
            try:
                file_bytes += path.stat().st_size
            except OSError:
                pass
    if not dry_run:
        with conn:
            conn.execute(
                "update tool_outputs set storage_kind = 'omitted', content_text = null, path = null "
                "where coalesce(content_text, '') <> '' or coalesce(path, '') <> ''"
            )
        if file_root.exists():
            for path in sorted(file_root.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    try:
                        path.rmdir()
                    except OSError:
                        pass
    return [f"purged tool outputs: rows={rows} bytes={bytes_count} files={file_count} file_bytes={file_bytes}"], 0


def run_prune_event_logs(*, dry_run: bool) -> tuple[list[str], int]:
    root = MEMORY_DIR / "events"
    if not root.exists():
        return ["pruned event logs: files=0 bytes=0"], 0
    files = [path for path in root.rglob("*.jsonl") if path.is_file()]
    removed = 0
    removed_bytes = 0
    for path in files:
        try:
            removed_bytes += path.stat().st_size
        except OSError:
            pass
        if not dry_run:
            path.unlink(missing_ok=True)
        removed += 1
    return [f"pruned event logs: files={removed} bytes={removed_bytes}"], 0
