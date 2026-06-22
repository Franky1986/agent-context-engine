from __future__ import annotations

import json
from typing import Any

from ...domain.semantic_normalization import normalize_entity_proposal, normalize_relation_proposal
from ...infrastructure.config import json_dumps
from .normalization_learning import active_normalization_rules


def normalize_semantic_payload(
    payload: dict[str, Any],
    *,
    learned_rules: list[Any] | None = None,
) -> dict[str, Any]:
    normalized = json_dumps(payload)
    data = json.loads(normalized)
    entities = data.get("entities") if isinstance(data.get("entities"), list) else []
    relations = data.get("relations") if isinstance(data.get("relations"), list) else []
    entity_key_by_proposal_id: dict[str, str] = {}

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        result = normalize_entity_proposal(
            str(entity.get("type") or ""),
            entity.get("name"),
            entity.get("aliases") if isinstance(entity.get("aliases"), list) else [],
            learned_rules=learned_rules,
        )
        properties = entity.get("properties") if isinstance(entity.get("properties"), dict) else {}
        properties = {
            **properties,
            "normalization": result.to_dict(),
            "source_name": result.source_name,
            "identity_confidence": result.identity_confidence,
        }
        entity["properties"] = properties
        entity["name"] = result.canonical_name
        entity["aliases"] = list(result.aliases)
        entity["language"] = result.language
        entity["canonical_key_candidate"] = result.canonical_key
        entity["identity_confidence"] = result.identity_confidence
        entity_key_by_proposal_id[str(entity.get("proposal_id") or "")] = result.canonical_key

    for relation in relations:
        if not isinstance(relation, dict):
            continue
        source_ref = str(relation.get("source_ref") or "")
        target_ref = str(relation.get("target_ref") or "")
        result = normalize_relation_proposal(
            str(relation.get("type") or ""),
            relation.get("summary"),
            source_key=entity_key_by_proposal_id.get(source_ref, source_ref),
            target_key=entity_key_by_proposal_id.get(target_ref, target_ref),
        )
        properties = relation.get("properties") if isinstance(relation.get("properties"), dict) else {}
        relation["properties"] = {
            **properties,
            "normalization": result.to_dict(),
        }
        relation["summary"] = result.canonical_summary
        relation["language"] = result.language
        relation["canonical_relation_key_candidate"] = result.canonical_relation_key
        relation["identity_confidence"] = result.identity_confidence
    return data


def normalize_semantic_payload_from_db(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_semantic_payload(payload, learned_rules=active_normalization_rules(conn))
