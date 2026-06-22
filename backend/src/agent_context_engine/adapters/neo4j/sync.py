from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ...infrastructure.config import ENV_FILE_PATH, MEMORY_DIR, ROOT, json_dumps, safe_slug, utc_now
from ...infrastructure.db import connect
from ...application.graph import GRAPH_SCHEMA_VERSION, ensure_patch_metadata, is_allowed_relation_type, validate_graph_patch


DEFAULT_URI = "http://localhost:7474"
DEFAULT_USER = "neo4j"
DEFAULT_DATABASE = "agenticMemory20"
DEFAULT_ENV_FILE = ENV_FILE_PATH
NEO4J_DATABASE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,62}$")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def neo4j_config(args: argparse.Namespace) -> dict[str, str]:
    env_file_values = load_env_file()
    password = os.environ.get(args.password_env) or env_file_values.get(args.password_env)
    return {
        "uri": (args.uri or env_file_values.get("AGENT_MEMORY_NEO4J_URI", DEFAULT_URI)).rstrip("/"),
        "user": args.user or env_file_values.get("AGENT_MEMORY_NEO4J_USER", DEFAULT_USER),
        "password": password or "",
        "database": args.database or env_file_values.get("AGENT_MEMORY_NEO4J_DATABASE", DEFAULT_DATABASE),
    }


def cypher_endpoint(config: dict[str, str]) -> str:
    return f"{config['uri']}/db/{config['database']}/tx/commit"


def run_cypher(config: dict[str, str], statements: list[dict[str, Any]], *, timeout: int = 30) -> dict[str, Any]:
    if not config["password"]:
        raise RuntimeError("missing Neo4j password; set AGENT_MEMORY_NEO4J_PASSWORD or use --password-env")
    body = json.dumps({"statements": statements}).encode("utf-8")
    token = base64.b64encode(f"{config['user']}:{config['password']}".encode("utf-8")).decode("ascii")
    request = urllib.request.Request(
        cypher_endpoint(config),
        data=body,
        headers={
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Neo4j HTTP {exc.code}: {detail}") from exc
    if data.get("errors"):
        raise RuntimeError(json_dumps(data["errors"]))
    return data


def cypher_rows(config: dict[str, str], statement: str, parameters: dict[str, Any] | None = None) -> list[list[Any]]:
    data = run_cypher(config, [{"statement": statement, "parameters": parameters or {}}])
    if not data.get("results"):
        return []
    return [item.get("row", []) for item in data["results"][0].get("data", [])]


def schema_statements() -> list[dict[str, Any]]:
    return [
        {
            "statement": (
                "CREATE CONSTRAINT agent_memory_entity_key IF NOT EXISTS "
                "FOR (n:AgentMemoryEntity) REQUIRE (n.type, n.key) IS UNIQUE"
            )
        },
        {
            "statement": (
                "CREATE CONSTRAINT agent_memory_relation_key IF NOT EXISTS "
                "FOR (n:AgentMemoryRelation) REQUIRE n.key IS UNIQUE"
            )
        },
        {
            "statement": (
                "CREATE CONSTRAINT agent_memory_evidence_key IF NOT EXISTS "
                "FOR (n:AgentMemoryEvidence) REQUIRE n.key IS UNIQUE"
            )
        },
        {
            "statement": (
                "CREATE FULLTEXT INDEX agent_memory_entity_fulltext IF NOT EXISTS "
                "FOR (n:AgentMemoryEntity) ON EACH [n.name, n.key, n.content, n.path]"
            )
        },
    ]


def evidence_key(evidence: dict[str, Any]) -> str:
    raw = json_dumps(
        {
            "source_type": evidence.get("source_type"),
            "session_id": evidence.get("session_id"),
            "event_seq": evidence.get("event_seq"),
            "field": evidence.get("field"),
            "path": evidence.get("path"),
            "quote": evidence.get("quote"),
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def relation_key(relation: dict[str, Any]) -> str:
    raw = json_dumps(
        {
            "from": relation["from"],
            "type": relation["type"],
            "to": relation["to"],
        }
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def prepare_patch_for_import(patch: dict[str, Any]) -> dict[str, Any]:
    patch = ensure_patch_metadata(patch)
    errors = validate_graph_patch(patch)
    if errors:
        raise RuntimeError("invalid graph patch:\n" + "\n".join(errors))
    entities: list[dict[str, Any]] = []
    evidence_nodes: dict[str, dict[str, Any]] = {}
    entity_evidence: list[dict[str, str]] = []
    for entity in patch["entities"]:
        entity_id = f"{entity['type']}:{entity['key']}"
        entity_copy = {
            "id": entity_id,
            "type": entity["type"],
            "key": entity["key"],
            "name": entity.get("name") or entity["key"],
            "aliases": entity.get("aliases") or [],
            "confidence": float(entity.get("confidence", 1.0)),
            "memory_kind": entity.get("memory_kind") or "semantic",
            "source_kind": entity.get("source_kind") or "graph_structuring",
            "risk_level": entity.get("risk_level") or "low",
            "sensitivity": entity.get("sensitivity") or "normal",
            "injection_policy": entity.get("injection_policy") or "on_demand",
            "valid_from": entity.get("valid_from"),
            "valid_to": entity.get("valid_to"),
            "staleness": entity.get("staleness"),
            "poisoning_flags": entity.get("poisoning_flags") or [],
            "properties_json": json_dumps(entity.get("properties") or {}),
            "evidence_json": json_dumps(entity.get("evidence") or []),
            "updated_at": utc_now(),
        }
        entities.append(entity_copy)
        for item in entity.get("evidence", []):
            ev_key = evidence_key(item)
            evidence_nodes[ev_key] = {"key": ev_key, **item}
            entity_evidence.append({"entity_id": entity_id, "evidence_key": ev_key})

    relations: list[dict[str, Any]] = []
    relation_evidence: list[dict[str, str]] = []
    for relation in patch["relations"]:
        rel_key = relation_key(relation)
        from_id = f"{relation['from']['type']}:{relation['from']['key']}"
        to_id = f"{relation['to']['type']}:{relation['to']['key']}"
        relations.append(
            {
                "key": rel_key,
                "type": relation["type"],
                "from_id": from_id,
                "to_id": to_id,
                "confidence": float(relation.get("confidence", 1.0)),
                "memory_kind": relation.get("memory_kind") or "graph_fact",
                "source_kind": relation.get("source_kind") or "graph_structuring",
                "risk_level": relation.get("risk_level") or "low",
                "sensitivity": relation.get("sensitivity") or "normal",
                "injection_policy": relation.get("injection_policy") or "on_demand",
                "valid_from": relation.get("valid_from"),
                "valid_to": relation.get("valid_to"),
                "staleness": relation.get("staleness"),
                "poisoning_flags": relation.get("poisoning_flags") or [],
                "properties_json": json_dumps(relation.get("properties") or {}),
                "evidence_json": json_dumps(relation.get("evidence") or []),
                "updated_at": utc_now(),
            }
        )
        for item in relation.get("evidence", []):
            ev_key = evidence_key(item)
            evidence_nodes[ev_key] = {"key": ev_key, **item}
            relation_evidence.append({"relation_key": rel_key, "evidence_key": ev_key})

    return {
        "schema_version": patch["schema_version"],
        "source": patch.get("source") or {},
        "entities": entities,
        "relations": relations,
        "evidence": list(evidence_nodes.values()),
        "entity_evidence": entity_evidence,
        "relation_evidence": relation_evidence,
    }


def import_statements(prepared: dict[str, Any]) -> list[dict[str, Any]]:
    statements: list[dict[str, Any]] = [
        {
            "statement": """
            UNWIND $entities AS row
            MERGE (n:AgentMemoryEntity {type: row.type, key: row.key})
            SET n.entity_id = row.id,
                n.name = row.name,
                n.aliases = row.aliases,
                n.confidence = row.confidence,
                n.memory_kind = row.memory_kind,
                n.source_kind = row.source_kind,
                n.risk_level = row.risk_level,
                n.sensitivity = row.sensitivity,
                n.injection_policy = row.injection_policy,
                n.valid_from = row.valid_from,
                n.valid_to = row.valid_to,
                n.staleness = row.staleness,
                n.poisoning_flags = row.poisoning_flags,
                n.properties_json = row.properties_json,
                n.evidence_json = row.evidence_json,
                n.updated_at = row.updated_at
            """,
            "parameters": {"entities": prepared["entities"]},
        },
        {
            "statement": """
            UNWIND $evidence AS row
            MERGE (e:AgentMemoryEvidence {key: row.key})
            SET e.source_type = row.source_type,
                e.session_id = row.session_id,
                e.event_seq = row.event_seq,
                e.field = row.field,
                e.path = row.path,
                e.quote = row.quote
            """,
            "parameters": {"evidence": prepared["evidence"]},
        },
        {
            "statement": """
            UNWIND $links AS row
            MATCH (n:AgentMemoryEntity {entity_id: row.entity_id})
            MATCH (e:AgentMemoryEvidence {key: row.evidence_key})
            MERGE (n)-[:HAS_EVIDENCE]->(e)
            """,
            "parameters": {"links": prepared["entity_evidence"]},
        },
        {
            "statement": """
            UNWIND $relations AS row
            MATCH (from:AgentMemoryEntity {entity_id: row.from_id})
            MATCH (to:AgentMemoryEntity {entity_id: row.to_id})
            MERGE (r:AgentMemoryRelation {key: row.key})
            SET r.type = row.type,
                r.confidence = row.confidence,
                r.memory_kind = row.memory_kind,
                r.source_kind = row.source_kind,
                r.risk_level = row.risk_level,
                r.sensitivity = row.sensitivity,
                r.injection_policy = row.injection_policy,
                r.valid_from = row.valid_from,
                r.valid_to = row.valid_to,
                r.staleness = row.staleness,
                r.poisoning_flags = row.poisoning_flags,
                r.properties_json = row.properties_json,
                r.evidence_json = row.evidence_json,
                r.updated_at = row.updated_at
            MERGE (from)-[:AM_RELATION_FROM]->(r)
            MERGE (r)-[:AM_RELATION_TO]->(to)
            """,
            "parameters": {"relations": prepared["relations"]},
        },
        {
            "statement": """
            UNWIND $links AS row
            MATCH (r:AgentMemoryRelation {key: row.relation_key})
            MATCH (e:AgentMemoryEvidence {key: row.evidence_key})
            MERGE (r)-[:HAS_EVIDENCE]->(e)
            """,
            "parameters": {"links": prepared["relation_evidence"]},
        },
    ]
    relation_types = sorted({row["type"] for row in prepared["relations"] if is_allowed_relation_type(row["type"])})
    for relation_type in relation_types:
        rows = [row for row in prepared["relations"] if row["type"] == relation_type]
        if not rows:
            continue
        statements.append(
            {
                "statement": f"""
                UNWIND $relations AS row
                MATCH (from:AgentMemoryEntity {{entity_id: row.from_id}})
                MATCH (to:AgentMemoryEntity {{entity_id: row.to_id}})
                MERGE (from)-[rel:{relation_type}]->(to)
                SET rel.relation_key = row.key,
                    rel.confidence = row.confidence,
                    rel.risk_level = row.risk_level,
                    rel.sensitivity = row.sensitivity,
                    rel.updated_at = row.updated_at
                """,
                "parameters": {"relations": rows},
            }
        )
    return statements


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    size = max(1, int(size))
    return [items[index : index + size] for index in range(0, len(items), size)]


def import_statement_batches(prepared: dict[str, Any], *, batch_size: int = 500) -> list[list[dict[str, Any]]]:
    batches: list[list[dict[str, Any]]] = []
    base_templates = import_statements(
        {
            **prepared,
            "entities": [],
            "evidence": [],
            "entity_evidence": [],
            "relations": [],
            "relation_evidence": [],
        }
    )[:5]
    base_keys = ["entities", "evidence", "links", "relations", "links"]
    prepared_keys = ["entities", "evidence", "entity_evidence", "relations", "relation_evidence"]
    for template, parameter_key, prepared_key in zip(base_templates, base_keys, prepared_keys, strict=True):
        rows = prepared[prepared_key]
        for part in chunked(rows, batch_size):
            batches.append(
                [
                    {
                        "statement": template["statement"],
                        "parameters": {parameter_key: part},
                    }
                ]
            )
    relation_types = sorted({row["type"] for row in prepared["relations"] if is_allowed_relation_type(row["type"])})
    for relation_type in relation_types:
        rows = [row for row in prepared["relations"] if row["type"] == relation_type]
        if not rows:
            continue
        statement = f"""
        UNWIND $relations AS row
        MATCH (from:AgentMemoryEntity {{entity_id: row.from_id}})
        MATCH (to:AgentMemoryEntity {{entity_id: row.to_id}})
        MERGE (from)-[rel:{relation_type}]->(to)
        SET rel.relation_key = row.key,
            rel.confidence = row.confidence,
            rel.risk_level = row.risk_level,
            rel.sensitivity = row.sensitivity,
            rel.updated_at = row.updated_at
        """
        for part in chunked(rows, batch_size):
            batches.append([{"statement": statement, "parameters": {"relations": part}}])
    return batches


def run_import_batches(config: dict[str, str], prepared: dict[str, Any], *, batch_size: int = 500, timeout: int = 60) -> int:
    batches = import_statement_batches(prepared, batch_size=batch_size)
    for batch in batches:
        run_cypher(config, batch, timeout=timeout)
    return len(batches)


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def write_import_audit(path: Path, prepared: dict[str, Any], status: str, error: str | None = None) -> Path:
    out_dir = MEMORY_DIR / "graph" / "imports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"import_{safe_slug(path.stem)}_{utc_now().replace(':', '-').replace('+', 'Z')}.json"
    out_path.write_text(
        json_dumps(
            {
                "source_patch": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                "created_at": utc_now(),
                "status": status,
                "entity_count": len(prepared["entities"]),
                "relation_count": len(prepared["relations"]),
                "evidence_count": len(prepared["evidence"]),
                "error": error,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return out_path


def source_patch_rel(path: Path) -> str:
    return display_path(path)


def graph_artifact_id_for_patch(conn, path: Path) -> str | None:
    row = conn.execute(
        """
        select graph_artifact_id
        from graph_artifacts
        where path = ?
           or path = ?
        order by created_at desc
        limit 1
        """,
        (source_patch_rel(path), str(path)),
    ).fetchone()
    return row["graph_artifact_id"] if row else None


def record_import(
    conn,
    *,
    path: Path,
    config: dict[str, str],
    prepared: dict[str, Any],
    started_at: str,
    finished_at: str,
    status: str,
    audit: Path,
    error: str | None = None,
) -> None:
    import_id = f"neo4j_{safe_slug(path.stem)}_{finished_at.replace(':', '-').replace('+', 'Z')}"
    with conn:
        conn.execute(
            """
            insert or replace into neo4j_imports (
              import_id, graph_artifact_id, source_patch, uri, database_name,
              user_name, started_at, finished_at, status, entity_count,
              relation_count, evidence_count, audit_path, error_message
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                import_id,
                graph_artifact_id_for_patch(conn, path),
                source_patch_rel(path),
                config["uri"],
                config["database"],
                config["user"],
                started_at,
                finished_at,
                status,
                len(prepared["entities"]),
                len(prepared["relations"]),
                len(prepared["evidence"]),
                display_path(audit),
                error,
            ),
        )


def load_patch(path_arg: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_arg)
    if not path.is_absolute():
        path = ROOT / path
    patch = json.loads(path.read_text(encoding="utf-8"))
    if patch.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported graph schema: {patch.get('schema_version')}")
    return path, patch


def cmd_neo4j_status(args: argparse.Namespace) -> int:
    config = neo4j_config(args)
    try:
        data = run_cypher(config, [{"statement": "RETURN 1 AS ok"}])
    except Exception as exc:  # noqa: BLE001
        print(f"failed neo4j status uri={config['uri']} database={config['database']}: {exc}")
        return 1
    value = data["results"][0]["data"][0]["row"][0]
    print(f"ok neo4j uri={config['uri']} database={config['database']} result={value}")
    return 0


def cmd_neo4j_install_schema(args: argparse.Namespace) -> int:
    config = neo4j_config(args)
    try:
        run_cypher(config, schema_statements())
    except Exception as exc:  # noqa: BLE001
        print(f"failed neo4j schema install uri={config['uri']} database={config['database']}: {exc}")
        return 1
    print(f"installed neo4j schema database={config['database']}")
    return 0


def cmd_neo4j_create_database(args: argparse.Namespace) -> int:
    config = neo4j_config(args)
    database = args.name
    if not NEO4J_DATABASE_RE.fullmatch(database):
        print("failed neo4j create database: database name must match [A-Za-z][A-Za-z0-9_]{0,62}")
        return 2
    system_config = {**config, "database": "system"}
    try:
        run_cypher(system_config, [{"statement": f"CREATE DATABASE {database} IF NOT EXISTS"}], timeout=args.timeout)
        rows = cypher_rows(
            system_config,
            "SHOW DATABASES YIELD name, currentStatus WHERE name = $name RETURN name, currentStatus",
            {"name": database.lower()},
        )
    except Exception as exc:  # noqa: BLE001
        print(f"failed neo4j create database uri={config['uri']} database={database}: {exc}")
        return 1
    status = rows[0][1] if rows else "unknown"
    print(f"created neo4j database={database} status={status}")
    return 0


def cmd_neo4j_import(args: argparse.Namespace) -> int:
    config = neo4j_config(args)
    path, patch = load_patch(args.patch)
    prepared = prepare_patch_for_import(patch)
    conn = connect()
    started_at = utc_now()
    if args.dry_run:
        audit = write_import_audit(path, prepared, "dry_run")
        record_import(conn, path=path, config=config, prepared=prepared, started_at=started_at, finished_at=utc_now(), status="dry_run", audit=audit)
        print(
            f"dry-run {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
            f"entities={len(prepared['entities'])} relations={len(prepared['relations'])} evidence={len(prepared['evidence'])}"
        )
        print(f"audit={audit.relative_to(ROOT) if audit.is_relative_to(ROOT) else audit}")
        return 0
    try:
        run_cypher(config, schema_statements(), timeout=args.timeout)
        batch_count = run_import_batches(config, prepared, batch_size=args.batch_size, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001
        audit = write_import_audit(path, prepared, "failed", str(exc))
        record_import(conn, path=path, config=config, prepared=prepared, started_at=started_at, finished_at=utc_now(), status="failed", audit=audit, error=str(exc))
        print(f"failed neo4j import: {exc}")
        print(f"audit={audit.relative_to(ROOT) if audit.is_relative_to(ROOT) else audit}")
        return 1
    audit = write_import_audit(path, prepared, "imported")
    record_import(conn, path=path, config=config, prepared=prepared, started_at=started_at, finished_at=utc_now(), status="imported", audit=audit)
    print(
        f"imported {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
        f"entities={len(prepared['entities'])} relations={len(prepared['relations'])} evidence={len(prepared['evidence'])} batches={batch_count}"
    )
    print(f"audit={audit.relative_to(ROOT) if audit.is_relative_to(ROOT) else audit}")
    return 0


def pending_patch_rows(conn, config: dict[str, str], limit: int | None = None) -> list:
    sql = """
        select ga.*
        from graph_artifacts ga
        where ga.artifact_type = 'patch'
          and ga.status = 'valid'
          and not exists (
            select 1
            from neo4j_imports ni
            where ni.source_patch = ga.path
              and ni.uri = ?
              and ni.database_name = ?
              and ni.user_name = ?
              and ni.status = 'imported'
          )
        order by ga.created_at asc
    """
    params: list[Any] = [config["uri"], config["database"], config["user"]]
    if limit:
        sql += " limit ?"
        params.append(int(limit))
    return list(conn.execute(sql, params))


def import_patch_path(conn, config: dict[str, str], path: Path, *, dry_run: bool = False, batch_size: int = 500, timeout: int = 60) -> tuple[int, str]:
    patch = json.loads(path.read_text(encoding="utf-8"))
    prepared = prepare_patch_for_import(patch)
    started_at = utc_now()
    if dry_run:
        audit = write_import_audit(path, prepared, "dry_run")
        record_import(conn, path=path, config=config, prepared=prepared, started_at=started_at, finished_at=utc_now(), status="dry_run", audit=audit)
        return 0, f"dry-run {display_path(path)} entities={len(prepared['entities'])} relations={len(prepared['relations'])} evidence={len(prepared['evidence'])}"
    try:
        run_cypher(config, schema_statements(), timeout=timeout)
        batch_count = run_import_batches(config, prepared, batch_size=batch_size, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        audit = write_import_audit(path, prepared, "failed", str(exc))
        record_import(conn, path=path, config=config, prepared=prepared, started_at=started_at, finished_at=utc_now(), status="failed", audit=audit, error=str(exc))
        return 1, f"failed {display_path(path)}: {exc}"
    audit = write_import_audit(path, prepared, "imported")
    record_import(conn, path=path, config=config, prepared=prepared, started_at=started_at, finished_at=utc_now(), status="imported", audit=audit)
    return 0, f"imported {display_path(path)} entities={len(prepared['entities'])} relations={len(prepared['relations'])} evidence={len(prepared['evidence'])} batches={batch_count}"


def cmd_neo4j_sync_pending(args: argparse.Namespace) -> int:
    config = neo4j_config(args)
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
            code, message = import_patch_path(conn, config, path, dry_run=args.dry_run, batch_size=args.batch_size, timeout=args.timeout)
            print(message)
            if code:
                exit_code = code
        return exit_code
    finally:
        conn.close()


def cmd_neo4j_import_status(args: argparse.Namespace) -> int:
    config = neo4j_config(args)
    conn = connect()
    pending = pending_patch_rows(conn, config, None)
    print(f"pending_patches={len(pending)} uri={config['uri']} database={config['database']} user={config['user']}")
    rows = list(
        conn.execute(
            """
            select *
            from neo4j_imports
            order by started_at desc
            limit ?
            """,
            (args.limit,),
        )
    )
    if not rows:
        print("No Neo4j imports recorded.")
        return 0
    for row in rows:
        print(
            f"{row['started_at']} status={row['status']} source={row['source_patch']} "
            f"entities={row['entity_count']} relations={row['relation_count']} evidence={row['evidence_count']}"
        )
        print(f"  uri={row['uri']} database={row['database_name']} user={row['user_name']} audit={row['audit_path'] or '-'}")
        if row["error_message"]:
            print(f"  error={row['error_message']}")
    return 0


def add_neo4j_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--uri", default=os.environ.get("AGENT_MEMORY_NEO4J_URI"))
    parser.add_argument("--database", default=os.environ.get("AGENT_MEMORY_NEO4J_DATABASE"))
    parser.add_argument("--user", default=os.environ.get("AGENT_MEMORY_NEO4J_USER"))
    parser.add_argument("--password-env", default="AGENT_MEMORY_NEO4J_PASSWORD")
