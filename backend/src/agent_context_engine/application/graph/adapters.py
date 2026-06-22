from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
from typing import Any

from ...infrastructure.config import json_dumps, utc_now
from ..graphing.schema import ALLOWED_RELATION_TYPES
from ..graphing.artifacts import (
    display_path,
    graph_artifact_path,
    read_graph_json,
    write_graph_artifact,
)
from ..graphing.extract import (
    command_family,
    command_family_key,
    command_family_properties,
    deterministic_graph_patch,
)
from ..graphing.candidates import (
    best_text_similarity,
    candidate_artifact_path,
    cmd_graph_candidates as _cmd_graph_candidates,
    cmd_graph_reconcile as _cmd_graph_reconcile,
    entity_match_texts,
    existing_entity_index,
    local_entity_matches,
    validate_candidates,
)
from ..graphing.query import cmd_graph_query as _cmd_graph_query
from ..graphing.llm import llm_graph_run
from ..graphing.materialize import (
    backfill_command_families as _backfill_command_families,
    materialize_graph_patch,
    write_command_family_import_patch,
)
from ..graphing.schema import (
    GRAPH_MATCH_SCHEMA_VERSION,
    GRAPH_SCHEMA_VERSION,
    ensure_patch_metadata,
    graph_schema_context,
    is_allowed_relation_type,
    validate_graph_patch,
)
from ..graphing.operations import graph_source_paths
from .sync import neo4j_query_rows


def backfill_command_families(
    conn: sqlite3.Connection,
    *,
    command_family_func=command_family,
    command_family_key_func=command_family_key,
    command_family_properties_func=command_family_properties,
) -> dict[str, int]:
    return _backfill_command_families(
        conn,
        command_family_func=command_family_func,
        command_family_key_func=command_family_key_func,
        command_family_properties_func=command_family_properties_func,
    )


def write_command_family_import_patch(conn: sqlite3.Connection) -> tuple[Path, dict[str, int]]:
    return write_command_family_import_patch(conn)


def cmd_graph_query(args: Any) -> Any:
    return _cmd_graph_query(args)


def cmd_graph_candidates(args: Any) -> Any:
    return _cmd_graph_candidates(args)


def _neo4j_entity_matches(
    args: argparse.Namespace,
    candidate: dict[str, Any],
    threshold: float,
    limit: int,
) -> list[dict[str, Any]]:
    if not getattr(args, "include_neo4j", False):
        return []
    query_values = entity_match_texts(candidate, candidate=True)[:6]
    try:
        _, rows = neo4j_query_rows(
            args,
            """
            MATCH (n:AgentMemoryEntity {type: $type})
            WHERE any(q IN $queries WHERE
              toLower(coalesce(n.key, '')) CONTAINS q OR
              toLower(coalesce(n.name, '')) CONTAINS q OR
              any(alias IN coalesce(n.aliases, []) WHERE toLower(alias) CONTAINS q)
            )
            RETURN n.type, n.key, n.name, n.properties_json
            LIMIT $limit
            """,
            {"type": candidate.get("type"), "queries": query_values, "limit": limit * 3},
        )
    except Exception:
        return []

    matches: list[dict[str, Any]] = []
    candidate_texts = entity_match_texts(candidate, candidate=True)
    for row in rows:
        props = {}
        if len(row) > 3 and row[3]:
            try:
                props = json.loads(row[3])
            except json.JSONDecodeError:
                props = {}
        entity = {"type": row[0], "key": row[1], "name": row[2], "properties": props, "aliases": []}
        score = best_text_similarity(candidate_texts, entity_match_texts(entity))
        if score >= threshold:
            matches.append(
                {
                    "source": "neo4j",
                    "score": round(score, 4),
                    "type": row[0],
                    "key": row[1],
                    "name": row[2],
                    "properties": props,
                }
            )
    matches.sort(key=lambda item: (-float(item["score"]), str(item["type"]), str(item["key"])))
    return matches[:limit]


def _cmd_graph_match_candidates(args: Any) -> int:
    path, candidates = read_graph_json(args.candidates)
    errors = validate_candidates(candidates)
    if errors:
        for error in errors:
            print(error)
        return 1

    existing_entities = existing_entity_index(args.patch_limit)
    include_neo4j = bool(getattr(args, "include_neo4j", False))

    entity_matches: list[dict[str, Any]] = []
    for candidate in candidates.get("entities", []):
        matches = local_entity_matches(candidate, existing_entities, args.threshold, args.limit_per_entity)
        if include_neo4j:
            matches.extend(_neo4j_entity_matches(args, candidate, args.threshold, args.limit_per_entity))
            deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
            for match in matches:
                key = (match["source"], match["type"], match["key"])
                if key not in deduped or float(match["score"]) > float(deduped[key]["score"]):
                    deduped[key] = match
            matches = sorted(deduped.values(), key=lambda item: (-float(item["score"]), str(item["source"]), str(item["key"])))[: args.limit_per_entity]

        entity_matches.append(
            {
                "candidate_id": candidate["candidate_id"],
                "type": candidate["type"],
                "proposed_key": candidate["proposed_key"],
                "name": candidate["name"],
                "matches": matches,
                "recommended_action": "reuse" if matches and float(matches[0]["score"]) >= args.reuse_threshold else "create",
            }
        )

    result = {
        "schema_version": GRAPH_MATCH_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "generated_by": "deterministic:similarity-preflight",
        "source_candidates": display_path(path),
        "threshold": args.threshold,
        "reuse_threshold": args.reuse_threshold,
        "entity_matches": entity_matches,
        "relation_policy": {
            "allowed_relation_types": sorted(ALLOWED_RELATION_TYPES),
            "rule": "Relations may be imported only after endpoint entity keys are reconciled and relation type is in the allowlist.",
        },
    }

    out = candidate_artifact_path("matches", path.stem)
    out.write_text(json_dumps(result) + "\n", encoding="utf-8")
    print(f"wrote {display_path(out)} candidates={len(entity_matches)}")
    return 0


def cmd_graph_match_candidates(args: Any) -> Any:
    return _cmd_graph_match_candidates(args)


def cmd_graph_reconcile(args: Any) -> Any:
    return _cmd_graph_reconcile(args)


__all__ = [
    "display_path",
    "graph_artifact_path",
    "graph_schema_context",
    "graph_source_paths",
    "read_graph_json",
    "write_graph_artifact",
    "materialize_graph_patch",
    "deterministic_graph_patch",
    "llm_graph_run",
    "GRAPH_SCHEMA_VERSION",
    "ensure_patch_metadata",
    "is_allowed_relation_type",
    "validate_graph_patch",
    "backfill_command_families",
    "write_command_family_import_patch",
    "command_family",
    "command_family_key",
    "command_family_properties",
    "cmd_graph_query",
    "cmd_graph_candidates",
    "cmd_graph_match_candidates",
    "cmd_graph_reconcile",
]
