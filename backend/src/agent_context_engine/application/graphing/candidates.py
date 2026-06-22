from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from ...infrastructure.config import ROOT, json_dumps, safe_slug, utc_now
from ...infrastructure.db import connect
from ...infrastructure.text import read_text_limited
from .schema import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_RELATION_TYPES,
    GRAPH_CANDIDATE_SCHEMA_VERSION,
    GRAPH_DIR,
    GRAPH_MATCH_SCHEMA_VERSION,
    GRAPH_SCHEMA_VERSION,
    apply_metadata,
    clamp_confidence,
    ensure_patch_metadata,
    graph_schema_context,
    is_allowed_entity_type,
    is_allowed_relation_type,
    normalized_metadata,
    validate_graph_patch,
)


def candidate_artifact_path(kind: str, source_stem: str) -> Path:
    path = GRAPH_DIR / kind / f"{kind}_{safe_slug(source_stem)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def read_graph_json(path_arg: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_arg)
    if not path.is_absolute():
        path = ROOT / path
    return path, json.loads(path.read_text(encoding="utf-8"))


def validate_candidates(candidates: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidates.get("schema_version") != GRAPH_CANDIDATE_SCHEMA_VERSION:
        errors.append("invalid candidate schema_version")
    entity_keys: set[tuple[str, str]] = set()
    for idx, entity in enumerate(candidates.get("entities", [])):
        etype = entity.get("type")
        key = entity.get("proposed_key") or entity.get("key")
        if not is_allowed_entity_type(etype):
            errors.append(f"candidate entity[{idx}] unsupported type: {etype}")
        if not key:
            errors.append(f"candidate entity[{idx}] missing proposed_key")
        if not entity.get("evidence"):
            errors.append(f"candidate entity[{idx}] missing evidence")
        entity_keys.add((str(etype), str(key)))
    for idx, relation in enumerate(candidates.get("relations", [])):
        rtype = relation.get("type")
        if not is_allowed_relation_type(rtype):
            errors.append(f"candidate relation[{idx}] unsupported type: {rtype}")
        from_ref = relation.get("from", {})
        to_ref = relation.get("to", {})
        from_key = from_ref.get("proposed_key") or from_ref.get("key")
        to_key = to_ref.get("proposed_key") or to_ref.get("key")
        if (str(from_ref.get("type")), str(from_key)) not in entity_keys:
            errors.append(f"candidate relation[{idx}] from entity missing")
        if (str(to_ref.get("type")), str(to_key)) not in entity_keys:
            errors.append(f"candidate relation[{idx}] to entity missing")
        if not relation.get("evidence"):
            errors.append(f"candidate relation[{idx}] missing evidence")
    return errors


def patch_to_candidates(patch: dict[str, Any]) -> dict[str, Any]:
    patch = ensure_patch_metadata(patch)
    errors = validate_graph_patch(patch)
    if errors:
        raise RuntimeError("invalid graph patch:\n" + "\n".join(errors))
    return {
        "schema_version": GRAPH_CANDIDATE_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "generated_by": "deterministic:candidate-extractor",
        "source": patch.get("source") or {},
        "schema_context": graph_schema_context(),
        "entities": [
            {
                "candidate_id": f"{entity['type']}:{entity['key']}",
                "type": entity["type"],
                "name": entity.get("name") or entity["key"],
                "proposed_key": entity["key"],
                "aliases": entity.get("aliases") or [],
                "properties": entity.get("properties") or {},
                "evidence": entity.get("evidence") or [],
                "confidence": entity.get("confidence", 1.0),
                "memory_kind": entity.get("memory_kind"),
                "source_kind": entity.get("source_kind"),
                "risk_level": entity.get("risk_level"),
                "sensitivity": entity.get("sensitivity"),
                "injection_policy": entity.get("injection_policy"),
                "valid_from": entity.get("valid_from"),
                "valid_to": entity.get("valid_to"),
                "staleness": entity.get("staleness"),
                "poisoning_flags": entity.get("poisoning_flags") or [],
            }
            for entity in patch.get("entities", [])
        ],
        "relations": [
            {
                "candidate_id": f"{relation['from']['type']}:{relation['from']['key']}->{relation['type']}->{relation['to']['type']}:{relation['to']['key']}",
                "from": {"type": relation["from"]["type"], "proposed_key": relation["from"]["key"]},
                "type": relation["type"],
                "to": {"type": relation["to"]["type"], "proposed_key": relation["to"]["key"]},
                "properties": relation.get("properties") or {},
                "evidence": relation.get("evidence") or [],
                "confidence": relation.get("confidence", 1.0),
                "memory_kind": relation.get("memory_kind"),
                "source_kind": relation.get("source_kind"),
                "risk_level": relation.get("risk_level"),
                "sensitivity": relation.get("sensitivity"),
                "injection_policy": relation.get("injection_policy"),
                "valid_from": relation.get("valid_from"),
                "valid_to": relation.get("valid_to"),
                "staleness": relation.get("staleness"),
                "poisoning_flags": relation.get("poisoning_flags") or [],
            }
            for relation in patch.get("relations", [])
        ],
    }


def cmd_graph_candidates(args: argparse.Namespace) -> int:
    path, patch = read_graph_json(args.patch)
    candidates = patch_to_candidates(patch)
    errors = validate_candidates(candidates)
    if errors:
        for error in errors:
            print(error)
        return 1
    out = candidate_artifact_path("candidates", path.stem)
    out.write_text(json_dumps(candidates) + "\n", encoding="utf-8")
    print(f"wrote {display_path(out)} entities={len(candidates['entities'])} relations={len(candidates['relations'])}")
    return 0


def normalize_match_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def entity_match_texts(entity: dict[str, Any], *, candidate: bool = False) -> list[str]:
    key_name = "proposed_key" if candidate else "key"
    props = entity.get("properties") or {}
    texts = [
        entity.get(key_name) or "",
        entity.get("key") or "",
        entity.get("name") or "",
        props.get("path") or "",
        props.get("url") or "",
        props.get("command") or "",
    ]
    texts.extend(entity.get("aliases") or [])
    return [normalize_match_text(text) for text in texts if normalize_match_text(text)]


def best_text_similarity(left: list[str], right: list[str]) -> float:
    best = 0.0
    for a in left:
        for b in right:
            if not a or not b:
                continue
            if a == b:
                return 1.0
            if a in b or b in a:
                best = max(best, 0.92)
            best = max(best, SequenceMatcher(None, a, b).ratio())
    return best


def load_latest_patches(limit: int | None = None) -> list[tuple[Path, dict[str, Any]]]:
    conn = connect()
    rows = list(
        conn.execute(
            """
            select path
            from graph_artifacts
            where artifact_type = 'patch'
              and status = 'valid'
            order by created_at desc
            """
            + (" limit ?" if limit else ""),
            (limit,) if limit else (),
        )
    )
    patches: list[tuple[Path, dict[str, Any]]] = []
    for row in rows:
        path = Path(row["path"])
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            continue
        try:
            patches.append((path, json.loads(read_text_limited(path, 5_000_000))))
        except json.JSONDecodeError:
            continue
    return patches


def existing_entity_index(patch_limit: int) -> list[dict[str, Any]]:
    existing: dict[str, dict[str, Any]] = {}
    for _, patch in load_latest_patches(patch_limit):
        for entity in patch.get("entities", []):
            entity_id = f"{entity.get('type')}:{entity.get('key')}"
            existing.setdefault(entity_id, entity)
    return list(existing.values())


def local_entity_matches(candidate: dict[str, Any], existing_entities: list[dict[str, Any]], threshold: float, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidate_texts = entity_match_texts(candidate, candidate=True)
    for entity in existing_entities:
        if entity.get("type") != candidate.get("type"):
            continue
        score = best_text_similarity(candidate_texts, entity_match_texts(entity))
        if entity.get("key") == candidate.get("proposed_key"):
            score = 1.0
        if score >= threshold:
            rows.append(
                {
                    "source": "local_patch",
                    "score": round(score, 4),
                    "type": entity.get("type"),
                    "key": entity.get("key"),
                    "name": entity.get("name"),
                    "properties": entity.get("properties") or {},
                }
            )
    rows.sort(key=lambda item: (-float(item["score"]), str(item["type"]), str(item["key"])))
    return rows[:limit]


def cmd_graph_match_candidates(args: argparse.Namespace) -> int:
    from ..graph import cmd_graph_match_candidates as _cmd_graph_match_candidates

    return _cmd_graph_match_candidates(args)


def load_match_map(matches: dict[str, Any]) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    for row in matches.get("entity_matches", []):
        best = row.get("matches", [None])[0] if row.get("matches") else None
        mapping[row["candidate_id"]] = {
            "action": row.get("recommended_action") or "create",
            "match": best,
        }
    return mapping


def cmd_graph_reconcile(args: argparse.Namespace) -> int:
    candidates_path, candidates = read_graph_json(args.candidates)
    matches_path, matches = read_graph_json(args.matches)
    errors = validate_candidates(candidates)
    if errors:
        for error in errors:
            print(error)
        return 1
    match_map = load_match_map(matches)
    key_map: dict[str, str] = {}
    reconciled_entities: list[dict[str, Any]] = []
    for candidate in candidates.get("entities", []):
        decision = match_map.get(candidate["candidate_id"], {"action": "create", "match": None})
        match = decision.get("match")
        key = candidate["proposed_key"]
        action = "create"
        if decision.get("action") == "reuse" and match:
            key = match["key"]
            action = "reuse"
        key_map[candidate["candidate_id"]] = key
        props = dict(candidate.get("properties") or {})
        props["reconcile_action"] = action
        if match:
            props["matched_source"] = match.get("source")
            props["matched_score"] = match.get("score")
            props["original_proposed_key"] = candidate["proposed_key"]
        reconciled_entities.append(
            apply_metadata({
                "type": candidate["type"],
                "key": key,
                "name": match.get("name") if action == "reuse" and match and match.get("name") else candidate["name"],
                "aliases": candidate.get("aliases") or [],
                "properties": props,
                "evidence": candidate.get("evidence") or [],
            }, normalized_metadata(candidate, default_memory_kind="semantic", default_source_kind="graph_structuring", default_confidence=clamp_confidence(candidate.get("confidence"), 1.0)))
        )
    reconciled_relations: list[dict[str, Any]] = []
    entity_refs = {(entity["type"], entity["key"]) for entity in reconciled_entities}
    for relation in candidates.get("relations", []):
        from_candidate_id = f"{relation['from']['type']}:{relation['from']['proposed_key']}"
        to_candidate_id = f"{relation['to']['type']}:{relation['to']['proposed_key']}"
        from_ref = {"type": relation["from"]["type"], "key": key_map.get(from_candidate_id, relation["from"]["proposed_key"])}
        to_ref = {"type": relation["to"]["type"], "key": key_map.get(to_candidate_id, relation["to"]["proposed_key"])}
        if (from_ref["type"], from_ref["key"]) not in entity_refs or (to_ref["type"], to_ref["key"]) not in entity_refs:
            continue
        reconciled_relations.append(
            apply_metadata({
                "from": from_ref,
                "type": relation["type"],
                "to": to_ref,
                "properties": relation.get("properties") or {},
                "evidence": relation.get("evidence") or [],
            }, normalized_metadata(relation, default_memory_kind="graph_fact", default_source_kind="graph_structuring", default_confidence=clamp_confidence(relation.get("confidence"), 1.0)))
        )
    patch = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "generated_by": "deterministic:reconciler",
        "source": candidates.get("source") or {},
        "reconciliation": {
            "source_candidates": display_path(candidates_path),
            "source_matches": display_path(matches_path),
            "reuse_count": sum(1 for entity in reconciled_entities if entity.get("properties", {}).get("reconcile_action") == "reuse"),
            "create_count": sum(1 for entity in reconciled_entities if entity.get("properties", {}).get("reconcile_action") == "create"),
        },
        "entities": sorted(reconciled_entities, key=lambda e: (e["type"], e["key"])),
        "relations": sorted(reconciled_relations, key=lambda r: (r["from"]["type"], r["from"]["key"], r["type"], r["to"]["type"], r["to"]["key"])),
    }
    patch = ensure_patch_metadata(patch)
    patch_errors = validate_graph_patch(patch)
    if patch_errors:
        for error in patch_errors:
            print(error)
        return 1
    out = candidate_artifact_path("reconciled", candidates_path.stem)
    out.write_text(json_dumps(patch) + "\n", encoding="utf-8")
    print(
        f"wrote {display_path(out)} entities={len(patch['entities'])} relations={len(patch['relations'])} "
        f"reuse={patch['reconciliation']['reuse_count']} create={patch['reconciliation']['create_count']}"
    )
    return 0
