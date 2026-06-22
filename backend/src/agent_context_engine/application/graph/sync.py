from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3
from typing import Any, Protocol

from ...infrastructure.config import ROOT


class GraphSyncPort(Protocol):
    def sync_graph_patch(
        self,
        conn: sqlite3.Connection,
        args: argparse.Namespace,
        patch_path: str | Path,
    ) -> tuple[int, str]:
        ...


def neo4j_config_for_args(args: argparse.Namespace | None) -> dict[str, str]:
    if args is None:
        args = argparse.Namespace()
    from ...adapters.neo4j.sync import neo4j_config as _neo4j_config

    return _neo4j_config(args)


def neo4j_query_rows(
    args: argparse.Namespace | None,
    statement: str,
    params: dict[str, Any] | None = None,
) -> tuple[dict[str, str], list[Any]]:
    config = neo4j_config_for_args(args)
    if not config.get("password"):
        return config, []

    from ...adapters.neo4j.sync import cypher_rows as _cypher_rows

    return config, list(_cypher_rows(config, statement, params or {}))


class DefaultGraphSyncPort(GraphSyncPort):
    def sync_graph_patch(
        self,
        conn: sqlite3.Connection,
        args: argparse.Namespace,
        patch_path: str | Path,
    ) -> tuple[int, str]:
        if not bool(getattr(args, "sync_neo4j", True)):
            return 0, "neo4j sync skipped: sync_neo4j is disabled"

        from ...adapters.neo4j.sync import neo4j_config as _neo4j_config
        from ...adapters.neo4j.sync import import_patch_path as _import_patch_path

        config = _neo4j_config(args)
        if not config["password"]:
            return 0, "neo4j sync skipped: AGENT_MEMORY_NEO4J_PASSWORD is not set"

        path = Path(patch_path)
        if not patch_path:
            return 0, "neo4j sync skipped: patch path is empty"
        if not path.is_absolute():
            path = ROOT / path

        try:
            return _import_patch_path(
                conn,
                config,
                path,
                dry_run=False,
                batch_size=int(getattr(args, "neo4j_batch_size", 500)),
                timeout=int(getattr(args, "neo4j_timeout", 60)),
            )
        except Exception as exc:  # noqa: BLE001
            return 1, f"failed {path}: {exc}"


def graph_sync_port() -> GraphSyncPort:
    return DefaultGraphSyncPort()


def sync_graph_patch(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    patch_path: str | Path,
) -> tuple[int, str]:
    return graph_sync_port().sync_graph_patch(
        conn,
        args=args,
        patch_path=patch_path,
    )


def sync_graph_patch_for_dream_paths(
    conn: sqlite3.Connection,
    args: argparse.Namespace,
    graph_paths: list[str | Path] | None,
) -> tuple[int, str]:
    if not graph_paths or len(graph_paths) < 2:
        return 0, "neo4j sync skipped: expected patch path for this graph run is missing"
    return sync_graph_patch(conn, args=args, patch_path=graph_paths[1])


def cmd_neo4j_sync_pending(args: argparse.Namespace) -> int:
    from ...infrastructure.db import connect
    from ...adapters.neo4j.sync import run_cypher, schema_statements
    from ...adapters.neo4j.sync import import_patch_path as _import_patch_path, neo4j_config as _neo4j_config, pending_patch_rows

    config = _neo4j_config(args)
    conn = connect()
    try:
        rows = pending_patch_rows(conn, config, args.limit)
        if not rows:
            print("No pending Neo4j graph patches.")
            return 0

        if not args.dry_run and not config["password"]:
            print("neo4j sync skipped: AGENT_MEMORY_NEO4J_PASSWORD is not set")
            return 0

        exit_code = 0
        if not args.dry_run:
            try:
                run_cypher(config, schema_statements(), timeout=args.timeout)
            except Exception as exc:  # noqa: BLE001
                print(f"failed neo4j schema install uri={config['uri']} database={config['database']}: {exc}")
                return 1

        for row in rows:
            path = Path(row["path"])
            if not path.is_absolute():
                path = ROOT / path
            if not path.exists():
                print(f"missing patch {row['path']}")
                exit_code = 1
                continue
            code, message = _import_patch_path(
                conn,
                config,
                path,
                dry_run=bool(args.dry_run),
                batch_size=int(getattr(args, "batch_size", 500)),
                timeout=int(getattr(args, "timeout", 60)),
            )
            print(message)
            if code:
                exit_code = code

        return exit_code
    finally:
        conn.close()


def add_neo4j_args(parser: argparse.ArgumentParser) -> None:
    from ...adapters.neo4j.sync import add_neo4j_args as _add_neo4j_args

    _add_neo4j_args(parser)


def cmd_neo4j_status(args: argparse.Namespace) -> int:
    from ...adapters.neo4j.sync import cmd_neo4j_status as _cmd_neo4j_status

    return _cmd_neo4j_status(args)


def cmd_neo4j_install_schema(args: argparse.Namespace) -> int:
    from ...adapters.neo4j.sync import cmd_neo4j_install_schema as _cmd_neo4j_install_schema

    return _cmd_neo4j_install_schema(args)


def cmd_neo4j_create_database(args: argparse.Namespace) -> int:
    from ...adapters.neo4j.sync import cmd_neo4j_create_database as _cmd_neo4j_create_database

    return _cmd_neo4j_create_database(args)


def cmd_neo4j_import(args: argparse.Namespace) -> int:
    from ...adapters.neo4j.sync import cmd_neo4j_import as _cmd_neo4j_import

    return _cmd_neo4j_import(args)


def cmd_neo4j_import_status(args: argparse.Namespace) -> int:
    from ...adapters.neo4j.sync import cmd_neo4j_import_status as _cmd_neo4j_import_status

    return _cmd_neo4j_import_status(args)


def neo4j_query_candidate_rows(
    args: argparse.Namespace | None,
    entity: dict[str, Any],
    limit_per: int,
) -> tuple[str, list[dict[str, Any]], str | None]:
    if args is None or not bool(getattr(args, "sync_neo4j", True)):
        return "disabled", [], None

    from ...adapters.neo4j.sync import neo4j_config as _neo4j_config
    from ...adapters.neo4j.sync import cypher_rows as _cypher_rows

    config = _neo4j_config(args)
    if not config.get("password"):
        return "skipped_unconfigured", [], None

    statement = """
    MATCH (n:AgentMemoryEntity)
    WHERE n.memory_kind = 'semantic'
      AND n.type = $type
      AND (
        toLower(coalesce(n.name, '')) CONTAINS toLower($name)
        OR toLower($name) CONTAINS toLower(coalesce(n.name, ''))
        OR toLower(coalesce(n.key, '')) CONTAINS toLower($name)
      )
    RETURN n.key, n.type, n.name, coalesce(n.content, n.summary, ''), coalesce(n.confidence, 0.65)
    LIMIT $limit
    """
    try:
        rows = _cypher_rows(config, statement, {"type": entity.get("type"), "name": entity.get("name") or "", "limit": limit_per})
    except Exception as exc:  # noqa: BLE001
        return "skipped_error", [], str(exc)

    candidates = [
        {
            "entity_key": row[0],
            "entity_type": row[1],
            "name": row[2],
            "summary": row[3],
            "confidence": row[4],
            "source": "neo4j",
        }
        for row in rows
    ]
    return "queried", candidates, None
