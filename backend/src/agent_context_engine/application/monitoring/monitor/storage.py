from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from ....adapters.sqlite.request_db import connect
from ....infrastructure.config import DB_PATH, MEMORY_DIR, ROOT
from ...instance_profile import (
    instance_metadata_path_for_root,
    load_installation_profile,
    load_storage_profile,
    resolve_storage_profile,
    storage_profile_path,
    sync_instance_metadata,
    user_config_path,
    user_state_root,
)
from ...graph import neo4j_config_for_args, neo4j_query_rows


def _safe_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except (OSError, ValueError):
        return str(path)


def _stat_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _is_excluded(path: Path, excluded: tuple[Path, ...]) -> bool:
    for root in excluded:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _path_stats(path: Path, *, exclude: tuple[Path, ...] = ()) -> dict[str, Any]:
    total = 0
    file_count = 0
    dir_count = 0
    newest_mtime = 0.0
    largest: list[tuple[int, str]] = []
    errors: list[str] = []
    if not path.exists():
        return {
            "path": _safe_rel(path),
            "absolute_path": str(path),
            "exists": False,
            "file_count": 0,
            "dir_count": 0,
            "size_bytes": 0,
            "newest_mtime": None,
            "largest_files": [],
            "errors": [],
        }
    if path.is_file():
        size = _stat_size(path)
        return {
            "path": _safe_rel(path),
            "absolute_path": str(path),
            "exists": True,
            "file_count": 1,
            "dir_count": 0,
            "size_bytes": size,
            "newest_mtime": path.stat().st_mtime,
            "largest_files": [{"path": _safe_rel(path), "size_bytes": size}],
            "errors": [],
        }
    for dirpath, dirnames, filenames in os.walk(path, followlinks=False):
        current = Path(dirpath)
        if _is_excluded(current, exclude):
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if not _is_excluded(current / name, exclude)]
        dir_count += len(dirnames)
        for filename in filenames:
            file_path = current / filename
            if _is_excluded(file_path, exclude):
                continue
            try:
                stat = file_path.stat()
            except OSError as exc:
                errors.append(f"{_safe_rel(file_path)}: {exc}")
                continue
            size = int(stat.st_size)
            total += size
            file_count += 1
            newest_mtime = max(newest_mtime, float(stat.st_mtime))
            largest.append((size, _safe_rel(file_path)))
    largest.sort(reverse=True)
    return {
        "path": _safe_rel(path),
        "absolute_path": str(path),
        "exists": True,
        "file_count": file_count,
        "dir_count": dir_count,
        "size_bytes": total,
        "newest_mtime": newest_mtime or None,
        "largest_files": [{"path": rel, "size_bytes": size} for size, rel in largest[:5]],
        "errors": errors[:10],
    }


def _sqlite_files() -> list[dict[str, Any]]:
    files = [DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm")]
    return [
        {
            "name": path.name,
            "path": _safe_rel(path),
            "absolute_path": str(path),
            "exists": path.exists(),
            "size_bytes": _stat_size(path),
        }
        for path in files
    ]


def _sqlite_count(conn: Any, table: str, where: str = "") -> int | None:
    exists = conn.execute("select 1 from sqlite_master where type='table' and name=?", (table,)).fetchone()
    if not exists:
        return None
    query = f"select count(*) as c from {table} {where}"
    return int(conn.execute(query).fetchone()["c"])


def _sqlite_row_counts(conn: Any) -> list[dict[str, Any]]:
    tables = [
        ("sessions", "Sessions"),
        ("events", "Events"),
        ("dream_runs", "Dream runs"),
        ("memory_documents", "Memory documents"),
        ("memory_chunks", "Memory chunks"),
        ("retrieval_runs", "Retrieval runs"),
        ("graph_entities", "Graph entities"),
        ("graph_relations", "Graph relations"),
        ("tool_outputs", "Tool output metadata"),
        ("risk_events", "Risk events"),
        ("classifier_runs", "Classifier runs"),
        ("scheduler_runs", "Scheduler runs"),
        ("neo4j_imports", "Neo4j imports"),
    ]
    rows: list[dict[str, Any]] = []
    for table, label in tables:
        count = _sqlite_count(conn, table)
        if count is not None:
            rows.append({"table": table, "label": label, "rows": count})
    return rows


def _tool_output_raw_count(conn: Any) -> int:
    count = _sqlite_count(conn, "tool_outputs", "where content_text is not null or path is not null")
    return int(count or 0)


def _file_category(label: str, key: str, path: Path, description: str, *, exclude: tuple[Path, ...] = ()) -> dict[str, Any]:
    stats = _path_stats(path, exclude=exclude)
    return {"key": key, "label": label, "description": description, **stats}


def monitor_storage_inspect() -> dict[str, Any]:
    conn = connect()
    install_profile = load_installation_profile(ROOT)
    storage = resolve_storage_profile(ROOT)
    runtime_storage_profile = load_storage_profile(MEMORY_DIR)
    instance_metadata = sync_instance_metadata(ROOT)
    db_related = tuple(path for path in [DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm")] if path.exists())
    categories = [
        _file_category("SQLite database files", "sqlite", DB_PATH.parent, "Main SQLite database plus WAL/SHM files."),
        _file_category("Status and locks", "status", MEMORY_DIR / "status", "Runtime status files and lock metadata.", exclude=db_related),
        _file_category("Logs", "logs", MEMORY_DIR / "logs", "Hook, scheduler, monitor, and runtime logs."),
        _file_category("Hook event logs", "event_logs", MEMORY_DIR / "events", "Legacy raw JSONL hook event logs.", exclude=(MEMORY_DIR / "events" / "queue",)),
        _file_category("Hook queue", "queue", MEMORY_DIR / "events" / "queue", "Deferred hook events waiting for processing."),
        _file_category("Tool output files", "tool_outputs", MEMORY_DIR / "tool-outputs", "Legacy raw tool-output files; current builds keep only metadata."),
        _file_category("Session files", "sessions", MEMORY_DIR / "sessions", "Per-session summary and handover artifacts."),
        _file_category("Dream artifacts", "dream", MEMORY_DIR / "dream", "Dream run outputs, graph patches, and extraction artifacts."),
        _file_category("Memory documents", "memories", MEMORY_DIR / "memories", "Materialized memory documents indexed for retrieval."),
        _file_category("Graph artifacts", "graph", MEMORY_DIR / "graph", "Graph import/export artifacts outside SQLite and Neo4j."),
        _file_category("Personal memory", "personal", MEMORY_DIR / "personal", "User-curated personal memory markdown files."),
        _file_category("Personal proposals", "personal_proposals", MEMORY_DIR / "personal-proposals", "Pending personal-memory proposals."),
        _file_category("Analysis reports", "analysis_reports", MEMORY_DIR / "analysis_reports", "Generated session analysis reports."),
        _file_category("Local config", "local", MEMORY_DIR / "local", "Local-only config such as Neo4j env files."),
    ]
    sqlite_files = _sqlite_files()
    memory_total = _path_stats(MEMORY_DIR)
    raw_tool_outputs = _tool_output_raw_count(conn)
    event_jsonl_files = int(sum(1 for _ in (MEMORY_DIR / "events").glob("*.jsonl"))) if (MEMORY_DIR / "events").exists() else 0
    queued_files = int(sum(1 for _ in (MEMORY_DIR / "events" / "queue").glob("*/*.json"))) if (MEMORY_DIR / "events" / "queue").exists() else 0
    warnings: list[dict[str, str]] = []
    if raw_tool_outputs:
        warnings.append({"level": "warn", "message": f"{raw_tool_outputs} tool output row(s) still reference raw content."})
    if event_jsonl_files:
        warnings.append({"level": "warn", "message": f"{event_jsonl_files} raw event log file(s) are present."})
    if queued_files:
        warnings.append({"level": "info", "message": f"{queued_files} queued hook event file(s) are waiting for processing."})
    return {
        "root": str(ROOT),
        "install_root": str(ROOT),
        "memory_dir": str(MEMORY_DIR),
        "memory_root": str(MEMORY_DIR),
        "storage_schema_version": int(storage.get("schema_version") or 1),
        "storage_attached_at": str(storage.get("attached_at") or ""),
        "storage_profile_path": str(storage_profile_path(MEMORY_DIR)),
        "storage_instance_id": str(runtime_storage_profile.get("storage_instance_id") or ""),
        "user_state_root": str(user_state_root()),
        "user_config_path": str(user_config_path()),
        "instance_metadata_path": str(instance_metadata_path_for_root(ROOT)),
        "instance_metadata": instance_metadata,
        "total": memory_total,
        "categories": categories,
        "sqlite": {
            "path": str(DB_PATH),
            "files": sqlite_files,
            "total_size_bytes": sum(int(item["size_bytes"]) for item in sqlite_files),
            "row_counts": _sqlite_row_counts(conn),
            "raw_tool_output_rows": raw_tool_outputs,
        },
        "warnings": warnings,
        "cleanup_commands": [
            "./scripts/agent-context-engine prune-logs --dry-run",
            "./scripts/agent-context-engine prune-event-logs --dry-run",
            "./scripts/agent-context-engine purge-tool-outputs --dry-run",
            "./scripts/agent-context-engine graph-prune",
        ],
    }


def _neo4j_size(args: argparse.Namespace) -> dict[str, Any]:
    config = neo4j_config_for_args(args)
    statements = [
        (
            "show databases yield name, currentStatus, databaseSize "
            "where name = $database return currentStatus, databaseSize"
        ),
        (
            "call dbms.queryJmx('org.neo4j:instance=kernel#0,name=Store file sizes') "
            "yield attributes return attributes.TotalStoreSize.value"
        ),
    ]
    errors: list[str] = []
    for statement in statements:
        try:
            _, rows = neo4j_query_rows(args, statement, {"database": config["database"]})
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
            continue
        if not rows:
            continue
        value = rows[0][-1]
        return {"available": True, "size_bytes": int(value or 0), "source": statement.split()[0].lower(), "errors": errors}
    return {"available": False, "size_bytes": None, "source": None, "errors": errors[:2]}


def monitor_neo4j_inspect(args: argparse.Namespace) -> dict[str, Any]:
    config = neo4j_config_for_args(args)
    public_config = {"uri": config["uri"], "database": config["database"], "user": config["user"], "configured": bool(config["password"])}
    if not config["password"]:
        return {"configured": False, "config": public_config, "error": "Neo4j password not configured"}
    try:
        counts = neo4j_query_rows(
            args,
            """
            match (e:AgentMemoryEntity)
            with count(e) as entities
            match (r:AgentMemoryRelation)
            with entities, count(r) as relations
            optional match (v:AgentMemoryEvidence)
            return entities, relations, count(v) as evidence
            """,
        )[1][0]
        labels = neo4j_query_rows(
            args,
            """
            match (n)
            unwind labels(n) as label
            return label, count(*) as count
            order by count desc, label
            limit 25
            """,
        )[1]
        rel_types = neo4j_query_rows(
            args,
            """
            match ()-[r]->()
            return type(r) as type, count(*) as count
            order by count desc, type
            limit 25
            """,
        )[1]
        size = _neo4j_size(args)
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "config": public_config, "error": str(exc)}
    return {
        "configured": True,
        "config": public_config,
        "counts": {"entities": int(counts[0] or 0), "relations": int(counts[1] or 0), "evidence": int(counts[2] or 0)},
        "labels": [{"label": row[0], "count": int(row[1] or 0)} for row in labels],
        "relationship_types": [{"type": row[0], "count": int(row[1] or 0)} for row in rel_types],
        "size": size,
    }
