from __future__ import annotations

import json
from typing import Any

from ....adapters.sqlite.row import row_dict as _row_dict
from ....adapters.sqlite.request_db import connect


def monitor_graph_artifact_detail(graph_artifact_id: str) -> dict[str, Any]:
    conn = connect()
    artifact = conn.execute("select * from graph_artifacts where graph_artifact_id = ?", (graph_artifact_id,)).fetchone()
    if artifact is None:
        raise ValueError(f"graph artifact not found: {graph_artifact_id}")
    artifact_item = _row_dict(artifact)
    dream_run_id = artifact_item.get("dream_run_id")
    entities = [
        _row_dict(row)
        for row in conn.execute(
            """
            select ge.*,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id) as evidence_count
            from graph_entities ge
            where ge.artifact_id = ? or (? is not null and ge.dream_run_id = ?)
            order by coalesce(ge.confidence, 0) desc, ge.type, ge.name
            limit 400
            """,
            (graph_artifact_id, dream_run_id, dream_run_id),
        )
    ]
    relations = [
        _row_dict(row)
        for row in conn.execute(
            """
            select gr.*, f.name as from_name, f.type as from_type, t.name as to_name, t.type as to_type,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
            from graph_relations gr
            left join graph_entities f on f.entity_id = gr.from_entity_id
            left join graph_entities t on t.entity_id = gr.to_entity_id
            where gr.artifact_id = ? or (? is not null and gr.dream_run_id = ?)
            order by coalesce(gr.confidence, 0) desc, gr.relation_type
            limit 800
            """,
            (graph_artifact_id, dream_run_id, dream_run_id),
        )
    ]
    owner_ids = [row["entity_id"] for row in entities] + [row["relation_id"] for row in relations]
    evidence: list[dict[str, Any]] = []
    if owner_ids:
        placeholders = ",".join("?" for _ in owner_ids[:1000])
        evidence = [
            _row_dict(row)
            for row in conn.execute(
                f"""
                select *
                from graph_evidence
                where owner_id in ({placeholders})
                order by owner_type, event_seq
                limit 1000
                """,
                owner_ids[:1000],
            )
        ]
    node_map: dict[str, dict[str, Any]] = {}
    for row in entities:
        node_map[row["entity_id"]] = {
            "id": row["entity_id"],
            "name": row["name"],
            "type": row["type"],
            "key": row["key"],
            "size": 10 + min(10, int(row.get("evidence_count") or 0)),
        }
    for row in relations:
        if row.get("from_entity_id") not in node_map:
            node_map[row["from_entity_id"]] = {"id": row["from_entity_id"], "name": row.get("from_name") or row["from_entity_id"], "type": row.get("from_type") or "Entity", "size": 8}
        if row.get("to_entity_id") not in node_map:
            node_map[row["to_entity_id"]] = {"id": row["to_entity_id"], "name": row.get("to_name") or row["to_entity_id"], "type": row.get("to_type") or "Entity", "size": 8}
    links = [
        {
            "source": row["from_entity_id"],
            "target": row["to_entity_id"],
            "type": row["relation_type"],
            "weight": max(1, float(row["confidence"] or 1)),
        }
        for row in relations
    ]
    return {
        "artifact": artifact_item,
        "entities": entities,
        "relations": relations,
        "evidence": evidence,
        "graph": {"nodes": list(node_map.values()), "links": links, "source": "sqlite-artifact"},
    }


def monitor_dream_graph(dream_run_id: str) -> dict[str, Any]:
    conn = connect()
    dream = conn.execute("select dream_run_id, session_id, status from dream_runs where dream_run_id = ?", (dream_run_id,)).fetchone()
    if dream is None:
        raise ValueError(f"dream run not found: {dream_run_id}")
    entities = [
        _row_dict(row)
        for row in conn.execute(
            """
            select semantic_entity_id, entity_key, entity_type, name, aliases_json,
                   summary, properties_json, confidence, evidence_json, status,
                   created_at, updated_at
            from semantic_entities
            where source_dream_run_id = ?
            order by confidence desc, entity_type, entity_key
            """,
            (dream_run_id,),
        )
    ]
    relations = [
        _row_dict(row)
        for row in conn.execute(
            """
            select semantic_relation_id, relation_key, relation_type,
                   source_entity_key, target_entity_key, summary,
                   properties_json, confidence, evidence_json, status,
                   created_at, updated_at
            from semantic_relations
            where source_dream_run_id = ?
            order by confidence desc, relation_type, relation_key
            """,
            (dream_run_id,),
        )
    ]
    for row in entities:
        try:
            row["aliases"] = json.loads(row.get("aliases_json") or "[]")
        except json.JSONDecodeError:
            row["aliases"] = []
        try:
            row["properties"] = json.loads(row.get("properties_json") or "{}")
        except json.JSONDecodeError:
            row["properties"] = {}
        try:
            row["evidence"] = json.loads(row.get("evidence_json") or "[]")
        except json.JSONDecodeError:
            row["evidence"] = []
        del row["aliases_json"]
        del row["properties_json"]
        del row["evidence_json"]

    for row in relations:
        try:
            row["properties"] = json.loads(row.get("properties_json") or "{}")
        except json.JSONDecodeError:
            row["properties"] = {}
        try:
            row["evidence"] = json.loads(row.get("evidence_json") or "[]")
        except json.JSONDecodeError:
            row["evidence"] = []
        del row["properties_json"]
        del row["evidence_json"]

    entity_id_by_key = {row["entity_key"]: row["semantic_entity_id"] for row in entities}
    node_map: dict[str, dict[str, Any]] = {}
    for row in entities:
        node_map[row["semantic_entity_id"]] = {
            "id": row["semantic_entity_id"],
            "name": row["name"],
            "type": row["entity_type"],
            "key": row["entity_key"],
            "size": 10 + min(10, len(row.get("evidence") or [])),
        }

    def _ensure_external_node(entity_key: str) -> str:
        external_id = f"external::{entity_key}"
        if external_id not in node_map:
            node_map[external_id] = {
                "id": external_id,
                "name": entity_key,
                "type": "Referenced Entity",
                "key": entity_key,
                "size": 7,
            }
        return external_id

    links: list[dict[str, Any]] = []
    for row in relations:
        source_key = str(row.get("source_entity_key") or "")
        target_key = str(row.get("target_entity_key") or "")
        source_node = entity_id_by_key.get(source_key) if source_key else None
        target_node = entity_id_by_key.get(target_key) if target_key else None
        if not source_node:
            source_node = _ensure_external_node(source_key)
        if not target_node:
            target_node = _ensure_external_node(target_key)
        if source_node and target_node:
            links.append(
                {
                    "source": source_node,
                    "target": target_node,
                    "type": row.get("relation_type") or "RELATED",
                    "weight": max(1, float(row.get("confidence") or 1)),
                }
            )

    return {
        "run": _row_dict(dream),
        "entities": entities,
        "relations": relations,
        "graph": {
            "nodes": list(node_map.values()),
            "links": links,
            "source": "sqlite-semantic",
        },
    }
