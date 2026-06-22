from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from ...infrastructure.config import ROOT, json_dumps, safe_slug, utc_now
from .schema import (
    GRAPH_SCHEMA_VERSION,
    ensure_patch_metadata,
    is_allowed_relation_type,
    is_dynamic_entity_type,
    is_dynamic_relation_type,
    validate_graph_patch,
)


def stable_hash(value: Any, length: int = 24) -> str:
    return hashlib.sha256(json_dumps(value).encode("utf-8")).hexdigest()[:length]


def _json_loads_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _record_dynamic_schema_item(
    conn: sqlite3.Connection,
    *,
    kind: str,
    name: str,
    reason: str,
    artifact_id: str,
    now: str,
) -> None:
    schema_item_id = f"schema_{stable_hash({'kind': kind, 'name': name.lower()})}"
    conn.execute(
        """
        insert into graph_schema_registry (
          schema_item_id, kind, name, status, canonical_name,
          created_from_proposal_id, reason, created_at, updated_at
        ) values (?, ?, ?, 'active', ?, null, ?, ?, ?)
        on conflict(kind, name) do update set
          status = 'active',
          canonical_name = coalesce(graph_schema_registry.canonical_name, excluded.canonical_name),
          reason = excluded.reason,
          updated_at = excluded.updated_at
        """,
        (schema_item_id, kind, name, name, f"{reason}; artifact={artifact_id}", now, now),
    )


def _json_loads_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _graph_artifact_path(kind: str, name: str) -> Path:
    from .schema import GRAPH_DIR

    path = GRAPH_DIR / kind / f"{safe_slug(name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def backfill_command_families(
    conn: sqlite3.Connection,
    *,
    command_family_func,
    command_family_key_func,
    command_family_properties_func,
) -> dict[str, int]:
    now = utc_now()
    family_rows: dict[str, dict[str, Any]] = {}
    relation_count = 0
    evidence_count = 0
    commands = list(conn.execute("select * from graph_entities where type = 'CLICommand' order by first_seen_at, entity_id"))
    with conn:
        conn.execute(
            """
            delete from graph_evidence
            where owner_type = 'relation'
              and owner_id in (select relation_id from graph_relations where artifact_id = 'command_family_backfill')
            """
        )
        conn.execute("delete from graph_relations where artifact_id = 'command_family_backfill'")
        conn.execute(
            """
            delete from graph_evidence
            where owner_type = 'entity'
              and owner_id in (select entity_id from graph_entities where type = 'CommandFamily' and artifact_id = 'command_family_backfill')
            """
        )
        conn.execute("delete from graph_entities where type = 'CommandFamily' and artifact_id = 'command_family_backfill'")
        for row in commands:
            props = _json_loads_dict(row["properties_json"])
            command = str(props.get("command") or row["key"] or row["name"] or "")
            family = command_family_func(command)
            family_key = command_family_key_func(family)
            family_id = f"CommandFamily:{family_key}"
            existing_family = conn.execute("select first_seen_at, properties_json, evidence_json from graph_entities where entity_id = ?", (family_id,)).fetchone()
            family_props = command_family_properties_func(family)
            family_props["example_command"] = command[:500]
            if family_id in family_rows:
                existing_props = dict(family_rows[family_id]["properties"])
                family_props = {**existing_props, **family_props}
            elif existing_family:
                existing_props = _json_loads_dict(existing_family["properties_json"])
                family_props = {**existing_props, **family_props}
            variant_ids = set(family_rows.get(family_id, {}).get("variant_ids") or [])
            variant_ids.add(row["entity_id"])
            family_props["variant_count"] = len(variant_ids)
            family_evidence = _json_loads_list(row["evidence_json"])[:1]
            if not family_evidence:
                family_evidence = [
                    {
                        "source_type": "derived_graph",
                        "session_id": row["session_id"],
                        "field": "command_family",
                        "quote": command[:500],
                    }
                ]
            family_rows[family_id] = {
                "entity_id": family_id,
                "type": "CommandFamily",
                "key": family_key,
                "name": family,
                "properties": family_props,
                "variant_ids": sorted(variant_ids),
                "evidence": family_evidence,
                "first_seen_at": existing_family["first_seen_at"] if existing_family else row["first_seen_at"],
                "last_seen_at": now,
                "artifact_id": "command_family_backfill",
                "session_id": row["session_id"],
                "dream_run_id": row["dream_run_id"],
            }
            relation_id = stable_hash({"from": row["entity_id"], "type": "INSTANCE_OF", "to": family_id})
            existing_rel = conn.execute("select first_seen_at from graph_relations where relation_id = ?", (relation_id,)).fetchone()
            relation_evidence = [
                {
                    "source_type": "derived_graph",
                    "session_id": row["session_id"],
                    "field": "command_family",
                    "quote": command[:500],
                }
            ]
            conn.execute(
                """
                insert or replace into graph_relations (
                  relation_id, from_entity_id, relation_type, to_entity_id, properties_json,
                  confidence, first_seen_at, last_seen_at, artifact_id, session_id,
                  dream_run_id, intent, helpful_score, tags_json, memory_kind, source_kind,
                  risk_level, sensitivity, injection_policy, valid_from, valid_to, staleness,
                  poisoning_flags_json, evidence_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    row["entity_id"],
                    "INSTANCE_OF",
                    family_id,
                    json_dumps({"derived_from": "CLICommand.properties.family"}),
                    float(row["confidence"] or 1.0),
                    existing_rel["first_seen_at"] if existing_rel else row["first_seen_at"],
                    now,
                    "command_family_backfill",
                    row["session_id"],
                    row["dream_run_id"],
                    row["intent"],
                    row["helpful_score"],
                    row["tags_json"],
                    "graph_fact",
                    "graph_structuring",
                    row["risk_level"] or "low",
                    row["sensitivity"] or "normal",
                    row["injection_policy"] or "on_demand",
                    row["valid_from"],
                    row["valid_to"],
                    row["staleness"],
                    row["poisoning_flags_json"] or "[]",
                    json_dumps(relation_evidence),
                ),
            )
            relation_count += 1
            for item in relation_evidence:
                evidence_id = stable_hash({"owner": relation_id, **item})
                conn.execute(
                    """
                    insert or replace into graph_evidence (
                      evidence_id, owner_type, owner_id, source_type, session_id,
                      event_seq, field, path, quote
                    ) values (?, 'relation', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (evidence_id, relation_id, item.get("source_type"), item.get("session_id"), item.get("event_seq"), item.get("field"), item.get("path"), item.get("quote")),
                )
                evidence_count += 1
        for row in family_rows.values():
            conn.execute(
                """
                insert or replace into graph_entities (
                  entity_id, type, key, name, aliases_json, properties_json, confidence,
                  first_seen_at, last_seen_at, artifact_id, session_id, dream_run_id,
                  intent, helpful_score, tags_json, memory_kind, source_kind, risk_level,
                  sensitivity, injection_policy, valid_from, valid_to, staleness,
                  poisoning_flags_json, evidence_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["entity_id"],
                    row["type"],
                    row["key"],
                    row["name"],
                    "[]",
                    json_dumps(row["properties"]),
                    1.0,
                    row["first_seen_at"],
                    row["last_seen_at"],
                    row["artifact_id"],
                    row["session_id"],
                    row["dream_run_id"],
                    None,
                    None,
                    "[]",
                    "procedural",
                    "graph_structuring",
                    "low",
                    "normal",
                    "on_demand",
                    None,
                    None,
                    None,
                    "[]",
                    json_dumps(row["evidence"]),
                ),
            )
            for item in row["evidence"]:
                evidence_id = stable_hash({"owner": row["entity_id"], **item})
                conn.execute(
                    """
                    insert or replace into graph_evidence (
                      evidence_id, owner_type, owner_id, source_type, session_id,
                      event_seq, field, path, quote
                    ) values (?, 'entity', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (evidence_id, row["entity_id"], item.get("source_type"), item.get("session_id"), item.get("event_seq"), item.get("field"), item.get("path"), item.get("quote")),
                )
                evidence_count += 1
    return {"commands": len(commands), "families": len(family_rows), "relations": relation_count, "evidence": evidence_count}


def _patch_entity_from_row(row: sqlite3.Row) -> dict[str, Any]:
    entity = {
        "type": row["type"],
        "key": row["key"],
        "name": row["name"],
        "aliases": _json_loads_list(row["aliases_json"]),
        "properties": _json_loads_dict(row["properties_json"]),
        "evidence": _json_loads_list(row["evidence_json"]),
        "confidence": float(row["confidence"] or 1.0),
        "memory_kind": row["memory_kind"] or "semantic",
        "source_kind": row["source_kind"] or "graph_structuring",
        "risk_level": row["risk_level"] or "low",
        "sensitivity": row["sensitivity"] or "normal",
        "injection_policy": row["injection_policy"] or "on_demand",
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "staleness": row["staleness"],
        "poisoning_flags": _json_loads_list(row["poisoning_flags_json"]),
    }
    if not entity["evidence"]:
        entity["evidence"] = [
            {
                "source_type": "derived_graph",
                "session_id": row["session_id"],
                "field": "command_family",
                "quote": f"{row['type']}:{row['key']}"[:500],
            }
        ]
    return entity


def _patch_relation_from_row(row: sqlite3.Row, entities_by_id: dict[str, sqlite3.Row]) -> dict[str, Any] | None:
    from_entity = entities_by_id.get(row["from_entity_id"])
    to_entity = entities_by_id.get(row["to_entity_id"])
    if from_entity is None or to_entity is None:
        return None
    evidence_items = _json_loads_list(row["evidence_json"])
    if not evidence_items:
        evidence_items = [
            {
                "source_type": "derived_graph",
                "session_id": row["session_id"],
                "field": "command_family",
                "quote": f"{row['from_entity_id']} {row['relation_type']} {row['to_entity_id']}"[:500],
            }
        ]
    return {
        "from": {"type": from_entity["type"], "key": from_entity["key"]},
        "type": row["relation_type"],
        "to": {"type": to_entity["type"], "key": to_entity["key"]},
        "properties": _json_loads_dict(row["properties_json"]),
        "evidence": evidence_items,
        "confidence": float(row["confidence"] or 1.0),
        "memory_kind": row["memory_kind"] or "graph_fact",
        "source_kind": row["source_kind"] or "graph_structuring",
        "risk_level": row["risk_level"] or "low",
        "sensitivity": row["sensitivity"] or "normal",
        "injection_policy": row["injection_policy"] or "on_demand",
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "staleness": row["staleness"],
        "poisoning_flags": _json_loads_list(row["poisoning_flags_json"]),
    }


def write_command_family_import_patch(conn: sqlite3.Connection) -> tuple[Path, dict[str, int]]:
    relations = list(conn.execute("select * from graph_relations where relation_type = 'INSTANCE_OF' order by first_seen_at, relation_id"))
    entity_ids = sorted({row["from_entity_id"] for row in relations} | {row["to_entity_id"] for row in relations})
    if not entity_ids:
        raise RuntimeError("no command family relations found; run graph-backfill-command-families first")
    placeholders = ",".join("?" for _ in entity_ids)
    entities_by_id = {
        row["entity_id"]: row
        for row in conn.execute(f"select * from graph_entities where entity_id in ({placeholders}) order by type, key", entity_ids)
    }
    patch_relations = [relation for row in relations if (relation := _patch_relation_from_row(row, entities_by_id)) is not None]
    patch = ensure_patch_metadata(
        {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "generated_by": "deterministic:command-family-backfill",
            "source": {"kind": "manual", "id": "command_family_backfill"},
            "entities": [_patch_entity_from_row(entities_by_id[entity_id]) for entity_id in entity_ids if entity_id in entities_by_id],
            "relations": patch_relations,
        }
    )
    errors = validate_graph_patch(patch)
    path = _graph_artifact_path("patches", f"command_family_backfill_{utc_now()}")
    path.write_text(json_dumps(patch) + "\n", encoding="utf-8")
    evidence_count = sum(len(entity.get("evidence", [])) for entity in patch["entities"]) + sum(len(relation.get("evidence", [])) for relation in patch["relations"])
    artifact_id = f"patch_{safe_slug(path.stem)}"
    with conn:
        conn.execute(
            """
            insert or replace into graph_artifacts (
              graph_artifact_id, session_id, dream_run_id, artifact_type, path,
              created_at, status, entity_count, relation_count, evidence_count,
              runner, source_paths_json, intent, helpful_score, tags_json, error_message
            ) values (?, ?, ?, 'patch', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                None,
                None,
                _display_path(path),
                utc_now(),
                "valid" if not errors else "invalid",
                len(patch["entities"]),
                len(patch["relations"]),
                evidence_count,
                "deterministic:command-family-backfill",
                json_dumps(["sqlite:graph_entities", "sqlite:graph_relations"]),
                None,
                None,
                "[]",
                "\n".join(errors) if errors else None,
            ),
        )
    return path, {"entities": len(patch["entities"]), "relations": len(patch["relations"]), "evidence": evidence_count, "errors": len(errors)}


def materialize_graph_patch(
    conn: sqlite3.Connection,
    patch: dict[str, Any],
    artifact_id: str,
    *,
    session_id: str,
    dream_run_id: str | None,
    intent: str | None,
    helpful_score: float | None,
    tags: list[str],
) -> None:
    now = utc_now()
    tags_json = json_dumps(tags)
    for entity in patch.get("entities", []):
        entity_id = f"{entity.get('type')}:{entity.get('key')}"
        if not entity.get("type") or not entity.get("key"):
            continue
        if is_dynamic_entity_type(entity.get("type")):
            _record_dynamic_schema_item(
                conn,
                kind="entity_type",
                name=str(entity["type"]),
                reason="auto-discovered dynamic graph entity type",
                artifact_id=artifact_id,
                now=now,
            )
        existing = conn.execute("select first_seen_at from graph_entities where entity_id = ?", (entity_id,)).fetchone()
        conn.execute(
            """
            insert or replace into graph_entities (
              entity_id, type, key, name, aliases_json, properties_json, confidence,
              first_seen_at, last_seen_at, artifact_id, session_id, dream_run_id,
              intent, helpful_score, tags_json, memory_kind, source_kind, risk_level,
              sensitivity, injection_policy, valid_from, valid_to, staleness,
              poisoning_flags_json, evidence_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entity_id,
                entity["type"],
                entity["key"],
                entity.get("name") or entity["key"],
                json_dumps(entity.get("aliases") or []),
                json_dumps(entity.get("properties") or {}),
                float(entity.get("confidence", 1.0) or 1.0),
                existing["first_seen_at"] if existing else now,
                now,
                artifact_id,
                session_id,
                dream_run_id,
                intent,
                helpful_score,
                tags_json,
                entity.get("memory_kind") or "semantic",
                entity.get("source_kind") or "graph_structuring",
                entity.get("risk_level") or "low",
                entity.get("sensitivity") or "normal",
                entity.get("injection_policy") or "on_demand",
                entity.get("valid_from"),
                entity.get("valid_to"),
                entity.get("staleness"),
                json_dumps(entity.get("poisoning_flags") or []),
                json_dumps(entity.get("evidence") or []),
            ),
        )
        for item in entity.get("evidence") or []:
            evidence_id = stable_hash({"owner": entity_id, **item})
            conn.execute(
                """
                insert or replace into graph_evidence (
                  evidence_id, owner_type, owner_id, source_type, session_id,
                  event_seq, field, path, quote
                ) values (?, 'entity', ?, ?, ?, ?, ?, ?, ?)
                """,
                (evidence_id, entity_id, item.get("source_type"), item.get("session_id"), item.get("event_seq"), item.get("field"), item.get("path"), item.get("quote")),
            )
    entity_ids = {f"{entity.get('type')}:{entity.get('key')}" for entity in patch.get("entities", [])}
    for relation in patch.get("relations", []):
        from_ref = relation.get("from") or {}
        to_ref = relation.get("to") or {}
        from_id = f"{from_ref.get('type')}:{from_ref.get('key')}"
        to_id = f"{to_ref.get('type')}:{to_ref.get('key')}"
        if from_id not in entity_ids or to_id not in entity_ids or not is_allowed_relation_type(relation.get("type")):
            continue
        if is_dynamic_relation_type(relation.get("type")):
            _record_dynamic_schema_item(
                conn,
                kind="relation_type",
                name=str(relation["type"]),
                reason="auto-discovered dynamic graph relation type",
                artifact_id=artifact_id,
                now=now,
            )
        relation_id = stable_hash({"from": from_id, "type": relation["type"], "to": to_id})
        existing = conn.execute("select first_seen_at from graph_relations where relation_id = ?", (relation_id,)).fetchone()
        conn.execute(
            """
            insert or replace into graph_relations (
              relation_id, from_entity_id, relation_type, to_entity_id, properties_json,
              confidence, first_seen_at, last_seen_at, artifact_id, session_id,
              dream_run_id, intent, helpful_score, tags_json, memory_kind, source_kind,
              risk_level, sensitivity, injection_policy, valid_from, valid_to, staleness,
              poisoning_flags_json, evidence_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                relation_id,
                from_id,
                relation["type"],
                to_id,
                json_dumps(relation.get("properties") or {}),
                float(relation.get("confidence", 1.0) or 1.0),
                existing["first_seen_at"] if existing else now,
                now,
                artifact_id,
                session_id,
                dream_run_id,
                intent,
                helpful_score,
                tags_json,
                relation.get("memory_kind") or "graph_fact",
                relation.get("source_kind") or "graph_structuring",
                relation.get("risk_level") or "low",
                relation.get("sensitivity") or "normal",
                relation.get("injection_policy") or "on_demand",
                relation.get("valid_from"),
                relation.get("valid_to"),
                relation.get("staleness"),
                json_dumps(relation.get("poisoning_flags") or []),
                json_dumps(relation.get("evidence") or []),
            ),
        )
        for item in relation.get("evidence") or []:
            evidence_id = stable_hash({"owner": relation_id, **item})
            conn.execute(
                """
                insert or replace into graph_evidence (
                  evidence_id, owner_type, owner_id, source_type, session_id,
                  event_seq, field, path, quote
                ) values (?, 'relation', ?, ?, ?, ?, ?, ?, ?)
                """,
                (evidence_id, relation_id, item.get("source_type"), item.get("session_id"), item.get("event_seq"), item.get("field"), item.get("path"), item.get("quote")),
            )
    from ..schema_proposals import ingest_graph_schema_proposals

    ingest_graph_schema_proposals(conn, patch, artifact_id=artifact_id, session_id=session_id, dream_run_id=dream_run_id)
