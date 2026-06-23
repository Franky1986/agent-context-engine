from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from time import monotonic
from typing import Any

from ...adapters.runners.codex import codex_subprocess_env
from ...infrastructure.config import ROOT, json_dumps, safe_slug, utc_now
from ...infrastructure.db import connect as db_connect
from ...infrastructure.text import read_text_limited
from ..dreaming.runners import cursor_stdout_text, extract_runner_token_usage, opencode_stdout_text, runner_token_usage_available
from .artifacts import display_path, patch_insights, normalize_insights
from .candidates import best_text_similarity, entity_match_texts, existing_entity_index, normalize_match_text
from .extract import TECH_TERMS, evidence, extract_paths, extract_tickets, extract_urls
from .runners import (
    antigravity_graph_command,
    claude_graph_command,
    codex_graph_command,
    codex_stdout_has_tool_events,
    cursor_graph_command,
    gemini_graph_command,
    graph_runner_model,
    opencode_graph_command,
)
from .schema import (
    GRAPH_SCHEMA_VERSION,
    LLM_GRAPH_DIR,
    LLM_GRAPH_TEXT_LIMIT,
    MAX_EVIDENCE_PER_ITEM,
    apply_metadata,
    clamp_confidence,
    graph_schema_context,
    is_allowed_entity_type,
    is_allowed_relation_type,
    normalized_metadata,
    normalize_entity_language,
    validate_graph_patch,
)


OPERATIONAL_ENTITY_TYPES = {
    "APIEndpoint",
    "CLICommand",
    "CommandFamily",
    "ConfigFile",
    "Directory",
    "Document",
    "DreamRun",
    "EnvironmentVariable",
    "File",
    "FileAccess",
    "Service",
    "Skill",
    "Summary",
    "Tool",
}

OPERATIONAL_RELATION_TYPES = {
    "CALLED_TOOL",
    "CONTAINS",
    "HAS_FILE_ACCESS",
    "INSTANCE_OF",
    "MODIFIED_FILE",
    "ON_FILE",
    "PERFORMED",
    "READ_FILE",
    "RAN_COMMAND",
    "USED_TOOL",
    "WROTE_FILE",
}


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.S)
    if fence_match:
        stripped = fence_match.group(1).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise RuntimeError("LLM graph output did not contain a JSON object")
        stripped = stripped[start : end + 1]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"LLM graph output is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM graph output must be a JSON object")
    return parsed


def entity_query_terms(facts_patch: dict[str, Any], dream_text: str, limit: int = 80) -> list[str]:
    terms: list[str] = []
    for entity in facts_patch.get("entities", []):
        for value in [
            entity.get("key"),
            entity.get("name"),
            *((entity.get("aliases") or [])[:3]),
            (entity.get("properties") or {}).get("path"),
            (entity.get("properties") or {}).get("url"),
            (entity.get("properties") or {}).get("command"),
        ]:
            text = normalize_match_text(value)
            if text and text not in terms:
                terms.append(text)
            if len(terms) >= limit:
                return terms
    for raw in [*extract_paths(dream_text), *extract_urls(dream_text), *extract_tickets(dream_text)]:
        text = normalize_match_text(raw)
        if text and text not in terms:
            terms.append(text)
        if len(terms) >= limit:
            return terms
    for raw, label in TECH_TERMS.items():
        if raw in dream_text.lower():
            text = normalize_match_text(label)
            if text and text not in terms:
                terms.append(text)
    return terms[:limit]


def compact_existing_entities(facts_patch: dict[str, Any], dream_text: str, limit: int = 120) -> list[dict[str, Any]]:
    query_terms = entity_query_terms(facts_patch, dream_text)
    existing = existing_entity_index(120)
    scored: list[tuple[float, dict[str, Any]]] = []
    for entity in existing:
        score = best_text_similarity(query_terms, entity_match_texts(entity))
        if score >= 0.55:
            scored.append((score, entity))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("type")), str(item[1].get("key"))))
    rows: list[dict[str, Any]] = []
    for score, entity in scored[:limit]:
        rows.append(
            {
                "match_score": round(score, 4),
                "type": entity.get("type"),
                "key": entity.get("key"),
                "name": entity.get("name"),
                "aliases": (entity.get("aliases") or [])[:5],
                "properties": {
                    key: value
                    for key, value in (entity.get("properties") or {}).items()
                    if key in {"path", "path_key", "url", "command", "family", "client_type", "runner"}
                },
            }
        )
    return rows


def build_llm_graph_prompt(
    session: sqlite3.Row,
    dream_run: sqlite3.Row,
    facts_patch: dict[str, Any],
    dream_text: str,
    existing_entities: list[dict[str, Any]] | None = None,
    *,
    runner: str,
    model: str | None,
) -> str:
    semantic_context = session_semantic_graph_context(session["session_id"], exclude_dream_run_id=dream_run["dream_run_id"])
    return "\n".join(
        [
            "You are the offline graph structurer for Agent Memory.",
            "Return exactly one RFC-8259 JSON object. No Markdown. No code fences.",
            "Do not call tools. Do not inspect files. Do not browse. Use only the supplied context.",
            "",
            "Task:",
            "- Convert deterministic facts and the dream memory into one valid graph patch.",
            "- The deterministic operational graph is intentionally not included in this prompt.",
            "- Focus only on semantic entities and relations inferred from the dream memory.",
            "- Do not add files, directories, commands, tool calls, file accesses, environment variables, or other operational entities unless they are semantically central concepts rather than operational traces.",
            "- The full deterministic operational graph is merged outside this LLM step after validation.",
            "- You may add semantic entities and relations inferred from the dream memory.",
            "- Prefer core entity and relation types from schema_context when they fit.",
            "- Add specific dynamic entity types in PascalCase or relation types in UPPER_SNAKE_CASE whenever they add useful retrievable detail, even if core types are also present.",
            "- Capture concrete names, places, organizations, examples, domain objects, and project-specific concepts when they matter for future retrieval.",
            "- Connect those concrete dynamic entities to core entities such as Session, Project, Decision, OpenTask, Document, File, or Technology.",
            "- Dynamic types must be domain-specific, not generic placeholders.",
            "- For semantic entity names, use canonical English display names.",
            "- Put original German or other source-language names in aliases and properties.original_name.",
            "- Do not translate paths, commands, URLs, environment variables, ticket IDs, branch names, model names, or project names.",
            "- Reuse existing entity type/key pairs when they are exact or obvious semantic matches.",
            "- Every entity and relation must include evidence with source_type, session_id, field, and a short quote.",
            "- Include insights.intent as a short machine-readable slug, insights.helpful_score as 0.0-1.0, and insights.tags as short slugs.",
            "- helpful_score means how useful this session/dream is likely to be for future retrieval or continuation, not whether the assistant was polite.",
            "- Prefer source_type='dream_run' for inferences from the dream memory and source_type='event' for direct conversation facts.",
            "- Keep evidence quotes short. Do not copy large text blocks.",
            "- Do not include explanations outside JSON.",
            "",
            "Required JSON shape:",
            json_dumps(
                {
                    "schema_version": GRAPH_SCHEMA_VERSION,
                    "generated_at": "<iso timestamp>",
                    "generated_by": f"{runner}:llm-graph-structurer",
                    "source": {"kind": "dream_run", "id": dream_run["dream_run_id"], "session_id": session["session_id"]},
                    "insights": {
                        "intent": "implementation",
                        "helpful_score": 0.8,
                        "tags": ["agent-memory", "graph"],
                        "rationale": "short reason for score and intent",
                    },
                    "entities": [
                        {
                            "type": "Project",
                            "key": "example",
                            "name": "Example",
                            "aliases": [],
                            "properties": {},
                            "evidence": [{"source_type": "dream_run", "session_id": session["session_id"], "field": "dream_memory", "quote": "short supporting quote"}],
                            "confidence": 0.9,
                            "memory_kind": "semantic",
                            "source_kind": "dream",
                            "risk_level": "low",
                            "sensitivity": "normal",
                            "injection_policy": "on_demand",
                            "valid_from": None,
                            "valid_to": None,
                            "staleness": None,
                            "poisoning_flags": [],
                        }
                    ],
                    "relations": [
                        {
                            "from": {"type": "Session", "key": session["session_id"]},
                            "type": "MENTIONED",
                            "to": {"type": "Project", "key": "example"},
                            "properties": {},
                            "evidence": [{"source_type": "dream_run", "session_id": session["session_id"], "field": "dream_memory", "quote": "short supporting quote"}],
                            "confidence": 0.9,
                            "memory_kind": "graph_fact",
                            "source_kind": "dream",
                            "risk_level": "low",
                            "sensitivity": "normal",
                            "injection_policy": "on_demand",
                            "valid_from": None,
                            "valid_to": None,
                            "staleness": None,
                            "poisoning_flags": [],
                        }
                    ],
                }
            ),
            "",
            "schema_context:",
            json_dumps(semantic_graph_schema_context()),
            "",
            "session:",
            json_dumps(
                {
                    "session_id": session["session_id"],
                    "thread_name": session["thread_name"] or "",
                    "client_type": session["client_type"],
                    "project_id": session["project_id"] or "unknown",
                    "cwd": session["cwd"] or "",
                    "last_workdir": session["last_workdir"] or "",
                    "dream_run_id": dream_run["dream_run_id"],
                    "dream_runner": dream_run["runner"],
                    "dream_runner_model": dream_run["runner_model"] or model or "",
                }
            ),
            "",
            "semantic_context_from_this_session:",
            json_dumps(semantic_context),
            "",
            "deterministic_graph_available_outside_llm:",
            json_dumps(
                {
                    "entity_count": len(facts_patch.get("entities") or []),
                    "relation_count": len(facts_patch.get("relations") or []),
                    "note": "Operational deterministic facts are not shown to the LLM. They are merged after LLM semantic structuring.",
                }
            ),
            "",
            "dream_memory_markdown:",
            compact_dream_memory_for_semantic_graph(dream_text) if dream_text else "_No dream memory available._",
        ]
    )


def semantic_graph_schema_context() -> dict[str, Any]:
    context = dict(graph_schema_context())
    context["entity_types"] = [item for item in context.get("entity_types", []) if item not in OPERATIONAL_ENTITY_TYPES]
    context["relation_types"] = [item for item in context.get("relation_types", []) if item not in OPERATIONAL_RELATION_TYPES]
    context["entity_key_rules"] = {
        key: value
        for key, value in (context.get("entity_key_rules") or {}).items()
        if not any(part in OPERATIONAL_ENTITY_TYPES for part in str(key).split("/"))
    }
    context["omitted_operational_types"] = {
        "entity_type_count": len(OPERATIONAL_ENTITY_TYPES),
        "relation_type_count": len(OPERATIONAL_RELATION_TYPES),
        "note": "Operational graph types are handled deterministically outside the LLM semantic structuring step.",
    }
    return context


def _json_loads(value: Any, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return fallback


def _compact_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items[:2]:
        copied = dict(item)
        if copied.get("quote"):
            copied["quote"] = str(copied["quote"])[:240]
        out.append(copied)
    return out


def session_semantic_graph_context(session_id: str, *, exclude_dream_run_id: str | None = None, entity_limit: int = 80, relation_limit: int = 120) -> dict[str, Any]:
    conn = db_connect()
    try:
        entity_rows = list(
            conn.execute(
                """
                select entity_id, type, key, name, aliases_json, properties_json, confidence,
                       dream_run_id, intent, helpful_score, tags_json, evidence_json
                from graph_entities
                where session_id = ?
                  and type not in ({})
                  and (? is null or dream_run_id is null or dream_run_id != ?)
                order by last_seen_at desc, entity_id asc
                limit ?
                """.format(",".join("?" for _ in OPERATIONAL_ENTITY_TYPES)),
                (session_id, *sorted(OPERATIONAL_ENTITY_TYPES), exclude_dream_run_id, exclude_dream_run_id, entity_limit),
            )
        )
        entity_ids = [row["entity_id"] for row in entity_rows]
        relation_rows: list[Any] = []
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            relation_rows = list(
                conn.execute(
                    f"""
                    select r.relation_id, r.from_entity_id, r.relation_type, r.to_entity_id,
                           r.properties_json, r.confidence, r.dream_run_id, r.intent,
                           r.helpful_score, r.tags_json, r.evidence_json,
                           fe.type as from_type, fe.key as from_key, fe.name as from_name,
                           te.type as to_type, te.key as to_key, te.name as to_name
                    from graph_relations r
                    join graph_entities fe on fe.entity_id = r.from_entity_id
                    join graph_entities te on te.entity_id = r.to_entity_id
                    where r.session_id = ?
                      and r.from_entity_id in ({placeholders})
                      and r.to_entity_id in ({placeholders})
                      and r.relation_type not in ({",".join("?" for _ in OPERATIONAL_RELATION_TYPES)})
                      and (? is null or r.dream_run_id is null or r.dream_run_id != ?)
                    order by r.last_seen_at desc, r.relation_id asc
                    limit ?
                    """,
                    (
                        session_id,
                        *entity_ids,
                        *entity_ids,
                        *sorted(OPERATIONAL_RELATION_TYPES),
                        exclude_dream_run_id,
                        exclude_dream_run_id,
                        relation_limit,
                    ),
                )
            )
    finally:
        conn.close()

    entities = [
        {
            "type": row["type"],
            "key": row["key"],
            "name": row["name"],
            "aliases": _json_loads(row["aliases_json"], [])[:5],
            "properties": {
                key: value
                for key, value in (_json_loads(row["properties_json"], {}) or {}).items()
                if key not in {"path", "path_key", "command"}
            },
            "confidence": row["confidence"],
            "dream_run_id": row["dream_run_id"],
            "intent": row["intent"],
            "helpful_score": row["helpful_score"],
            "tags": _json_loads(row["tags_json"], []),
            "evidence": _compact_evidence(_json_loads(row["evidence_json"], [])),
        }
        for row in entity_rows
    ]
    relations = [
        {
            "from": {"type": row["from_type"], "key": row["from_key"], "name": row["from_name"]},
            "type": row["relation_type"],
            "to": {"type": row["to_type"], "key": row["to_key"], "name": row["to_name"]},
            "properties": _json_loads(row["properties_json"], {}),
            "confidence": row["confidence"],
            "dream_run_id": row["dream_run_id"],
            "intent": row["intent"],
            "helpful_score": row["helpful_score"],
            "tags": _json_loads(row["tags_json"], []),
            "evidence": _compact_evidence(_json_loads(row["evidence_json"], [])),
        }
        for row in relation_rows
    ]
    return {
        "scope": "same_session_previous_semantic_graph",
        "session_id": session_id,
        "excluded_current_dream_run_id": exclude_dream_run_id,
        "entity_count": len(entities),
        "relation_count": len(relations),
        "entities": entities,
        "relations": relations,
    }


def compact_dream_memory_for_semantic_graph(markdown: str) -> str:
    if not markdown:
        return ""
    omitted = {
        "Files And Commands",
        "Retrieval Notes",
    }
    lines: list[str] = []
    skip = False
    for line in markdown.splitlines():
        if line.startswith("## "):
            title = line.removeprefix("## ").strip()
            skip = title in omitted
        if not skip:
            lines.append(line)
    compact = "\n".join(lines).strip()
    return compact[:LLM_GRAPH_TEXT_LIMIT] + ("\n...[truncated]" if len(compact) > LLM_GRAPH_TEXT_LIMIT else "")


def normalize_llm_graph_patch(patch: dict[str, Any], session: sqlite3.Row, dream_run: sqlite3.Row, generated_by: str) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "generated_at": str(patch.get("generated_at") or utc_now()),
        "generated_by": generated_by,
        "source": {"kind": "dream_run", "id": dream_run["dream_run_id"], "session_id": session["session_id"]},
        "insights": normalize_insights(patch.get("insights")),
        "entities": [],
        "relations": [],
    }
    for entity in patch.get("entities", []):
        if not isinstance(entity, dict):
            continue
        entity_type = entity.get("type")
        key = str(entity.get("key") or "").strip()
        if not is_allowed_entity_type(entity_type) or not key or str(entity_type) in OPERATIONAL_ENTITY_TYPES:
            continue
        meta = normalized_metadata(
            entity,
            default_memory_kind="semantic",
            default_source_kind="dream",
            default_confidence=clamp_confidence(entity.get("confidence"), 0.8),
        )
        out = {
            "type": entity_type,
            "key": key,
            "name": str(entity.get("name") or key),
            "aliases": [str(alias) for alias in (entity.get("aliases") or [])[:10]],
            "properties": entity.get("properties") if isinstance(entity.get("properties"), dict) else {},
            "evidence": (entity.get("evidence") or [])[:MAX_EVIDENCE_PER_ITEM],
        }
        normalize_entity_language(out)
        apply_metadata(out, meta)
        normalized["entities"].append(out)
    entity_refs = {(entity["type"], entity["key"]) for entity in normalized["entities"]}
    for relation in patch.get("relations", []):
        if not isinstance(relation, dict):
            continue
        relation_type = relation.get("type")
        from_ref = relation.get("from") if isinstance(relation.get("from"), dict) else {}
        to_ref = relation.get("to") if isinstance(relation.get("to"), dict) else {}
        from_key = str(from_ref.get("key") or "").strip()
        to_key = str(to_ref.get("key") or "").strip()
        from_type = from_ref.get("type")
        to_type = to_ref.get("type")
        if (
            not is_allowed_relation_type(relation_type)
            or str(relation_type) in OPERATIONAL_RELATION_TYPES
            or str(from_type or "") in OPERATIONAL_ENTITY_TYPES
            or str(to_type or "") in OPERATIONAL_ENTITY_TYPES
        ):
            continue
        if (from_type, from_key) not in entity_refs or (to_type, to_key) not in entity_refs:
            continue
        meta = normalized_metadata(
            relation,
            default_memory_kind="graph_fact",
            default_source_kind="dream",
            default_confidence=clamp_confidence(relation.get("confidence"), 0.8),
        )
        out = {
            "from": {"type": from_type, "key": from_key},
            "type": relation_type,
            "to": {"type": to_type, "key": to_key},
            "properties": relation.get("properties") if isinstance(relation.get("properties"), dict) else {},
            "evidence": (relation.get("evidence") or [])[:MAX_EVIDENCE_PER_ITEM],
        }
        apply_metadata(out, meta)
        normalized["relations"].append(out)
    return normalized


def add_insight_entities(patch: dict[str, Any], session: sqlite3.Row, dream_run: sqlite3.Row) -> dict[str, Any]:
    insights = patch_insights(patch)
    if not insights.get("intent"):
        return patch
    ev = evidence("dream_run", session["session_id"], "insights", insights["intent"], path=dream_run["output_summary_path"])
    entities = list(patch.get("entities", []))
    relations = list(patch.get("relations", []))
    existing_refs = {(entity.get("type"), entity.get("key")) for entity in entities}
    dream_ref = ("DreamRun", dream_run["dream_run_id"])
    intent_key = f"intent:{insights['intent']}"
    if ("Concept", intent_key) not in existing_refs:
        entities.append(
            apply_metadata(
                {
                    "type": "Concept",
                    "key": intent_key,
                    "name": f"Intent: {insights['intent']}",
                    "aliases": [insights["intent"]],
                    "properties": {
                        "intent": insights["intent"],
                        "helpful_score": insights.get("helpful_score"),
                        "tags": insights.get("tags") or [],
                        "rationale": insights.get("rationale") or "",
                    },
                    "evidence": [ev],
                },
                normalized_metadata({"confidence": 0.9}, default_memory_kind="semantic", default_source_kind="dream"),
            )
        )
    if dream_ref in existing_refs:
        relations.append(
            apply_metadata(
                {
                    "from": {"type": "DreamRun", "key": dream_run["dream_run_id"]},
                    "type": "TRACKS",
                    "to": {"type": "Concept", "key": intent_key},
                    "properties": {
                        "intent": insights["intent"],
                        "helpful_score": insights.get("helpful_score"),
                        "tags": insights.get("tags") or [],
                    },
                    "evidence": [ev],
                },
                normalized_metadata({"confidence": 0.9}, default_memory_kind="graph_fact", default_source_kind="dream"),
            )
        )
    patch = dict(patch)
    patch["insights"] = insights
    patch["entities"] = entities
    patch["relations"] = relations
    return patch


def merge_graph_patches(base: dict[str, Any], overlay: dict[str, Any], *, generated_by: str) -> dict[str, Any]:
    entities: dict[tuple[str, str], dict[str, Any]] = {}
    relations: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for source in (base, overlay):
        for entity in source.get("entities", []):
            key = (entity.get("type"), entity.get("key"))
            if not key[0] or not key[1]:
                continue
            existing = entities.get(key)
            if existing is None:
                copied = dict(entity)
                copied["aliases"] = list(copied.get("aliases") or [])
                copied["properties"] = dict(copied.get("properties") or {})
                copied["evidence"] = list(copied.get("evidence") or [])[:MAX_EVIDENCE_PER_ITEM]
                apply_metadata(copied, normalized_metadata(copied, default_memory_kind="semantic", default_source_kind="graph_structuring", default_confidence=clamp_confidence(copied.get("confidence"), 0.8)))
                entities[key] = copied
                continue
            if entity.get("name") and existing.get("name") == existing.get("key"):
                existing["name"] = entity["name"]
            existing_aliases = list(existing.get("aliases") or [])
            for alias in entity.get("aliases") or []:
                if alias not in existing_aliases:
                    existing_aliases.append(alias)
            existing["aliases"] = existing_aliases[:10]
            existing["properties"].update({k: v for k, v in (entity.get("properties") or {}).items() if v is not None})
            for ev in entity.get("evidence") or []:
                if len(existing["evidence"]) >= MAX_EVIDENCE_PER_ITEM:
                    break
                if ev not in existing["evidence"]:
                    existing["evidence"].append(ev)
            existing["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), float(entity.get("confidence", 0.0) or 0.0))
            for flag in entity.get("poisoning_flags") or []:
                flags = list(existing.get("poisoning_flags") or [])
                if flag not in flags:
                    flags.append(flag)
                existing["poisoning_flags"] = flags
        for relation in source.get("relations", []):
            from_ref = relation.get("from") or {}
            to_ref = relation.get("to") or {}
            key = (from_ref.get("type"), from_ref.get("key"), relation.get("type"), f"{to_ref.get('type')}:{to_ref.get('key')}")
            if not all(key):
                continue
            existing = relations.get(key)
            if existing is None:
                copied = dict(relation)
                copied["from"] = dict(from_ref)
                copied["to"] = dict(to_ref)
                copied["properties"] = dict(copied.get("properties") or {})
                copied["evidence"] = list(copied.get("evidence") or [])[:MAX_EVIDENCE_PER_ITEM]
                apply_metadata(copied, normalized_metadata(copied, default_memory_kind="graph_fact", default_source_kind="graph_structuring", default_confidence=clamp_confidence(copied.get("confidence"), 0.8)))
                relations[key] = copied
                continue
            existing["properties"].update({k: v for k, v in (relation.get("properties") or {}).items() if v is not None})
            for ev in relation.get("evidence") or []:
                if len(existing["evidence"]) >= MAX_EVIDENCE_PER_ITEM:
                    break
                if ev not in existing["evidence"]:
                    existing["evidence"].append(ev)
            existing["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), float(relation.get("confidence", 0.0) or 0.0))
            for flag in relation.get("poisoning_flags") or []:
                flags = list(existing.get("poisoning_flags") or [])
                if flag not in flags:
                    flags.append(flag)
                existing["poisoning_flags"] = flags
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "generated_by": generated_by,
        "source": overlay.get("source") or base.get("source") or {},
        "insights": patch_insights(overlay) or patch_insights(base),
        "entities": sorted(entities.values(), key=lambda entity: (entity["type"], entity["key"])),
        "relations": sorted(relations.values(), key=lambda relation: (relation["from"]["type"], relation["from"]["key"], relation["type"], relation["to"]["type"], relation["to"]["key"])),
    }


def llm_graph_run(
    session: sqlite3.Row,
    dream_run: sqlite3.Row,
    facts_patch: dict[str, Any],
    *,
    runner: str,
    model: str | None,
    timeout: int,
) -> tuple[dict[str, Any], list[str]]:
    resolved_model = graph_runner_model(runner, model)
    dream_paths: list[str] = []
    if dream_run["output_memory_paths_json"]:
        try:
            dream_paths = [str(item) for item in json.loads(dream_run["output_memory_paths_json"])]
        except json.JSONDecodeError:
            dream_paths = []
    dream_text_parts: list[str] = []
    for rel in dream_paths:
        path = ROOT / rel
        if "/memories/dreams/" in rel and path.suffix == ".md" and path.exists():
            dream_text_parts.append(read_text_limited(path, LLM_GRAPH_TEXT_LIMIT))
    dream_text = compact_dream_memory_for_semantic_graph("\n\n".join(dream_text_parts))
    run_dir = LLM_GRAPH_DIR / safe_slug(dream_run["dream_run_id"])
    run_dir.mkdir(parents=True, exist_ok=True)
    prompt = build_llm_graph_prompt(
        session,
        dream_run,
        facts_patch,
        dream_text,
        None,
        runner=runner,
        model=resolved_model,
    )
    prompt_path = run_dir / "prompt.md"
    raw_path = run_dir / f"{runner}-raw-output.json"
    response_path = run_dir / f"{runner}-output.json"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    started_at = utc_now()
    started_mono = monotonic()
    if runner == "codex":
        command = codex_graph_command(response_path, resolved_model)
        proc = subprocess.run(
            command,
            input=prompt,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=str(ROOT),
            env=codex_subprocess_env(extra={"AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)}),
        )
        tool_event_detected = codex_stdout_has_tool_events(proc.stdout)
        raw_text = read_text_limited(response_path, 5_000_000) if response_path.exists() else proc.stdout
        if not response_path.exists():
            response_path.write_text(raw_text, encoding="utf-8")
    elif runner == "claude":
        command = claude_graph_command(resolved_model)
        proc = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)})
        tool_event_detected = False
        raw_text = proc.stdout
        response_path.write_text(raw_text, encoding="utf-8")
    elif runner == "cursor":
        command = cursor_graph_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)})
        tool_event_detected = False
        raw_text = cursor_stdout_text(proc.stdout)
        response_path.write_text(raw_text, encoding="utf-8")
    elif runner == "antigravity":
        command = antigravity_graph_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)})
        tool_event_detected = False
        raw_text = proc.stdout
        response_path.write_text(raw_text, encoding="utf-8")
    elif runner == "gemini":
        command = gemini_graph_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)})
        tool_event_detected = False
        raw_text = proc.stdout
        response_path.write_text(raw_text, encoding="utf-8")
    elif runner == "opencode":
        command = opencode_graph_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)})
        tool_event_detected = False
        raw_text = opencode_stdout_text(proc.stdout)
        response_path.write_text(raw_text, encoding="utf-8")
    else:
        raise RuntimeError(f"unsupported LLM graph runner: {runner}")
    duration_ms = int((monotonic() - started_mono) * 1000)
    raw_path.write_text(raw_text, encoding="utf-8")
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "runner": runner,
                "model": resolved_model,
                "started_for": dream_run["dream_run_id"],
                "started_at": started_at,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr, raw_text),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr, raw_text),
                "returncode": proc.returncode,
                "tool_event_detected": tool_event_detected,
                "prompt_chars": len(prompt),
                "response_chars": len(response_path.read_text(encoding="utf-8", errors="replace")) if response_path.exists() else 0,
                "raw_chars": len(raw_text),
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": display_path(prompt_path),
                "response_path": display_path(response_path),
                "raw_path": display_path(raw_path),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{runner} graph structurer failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    if tool_event_detected:
        raise RuntimeError("codex graph structurer used or attempted to use a tool; refusing graph output")
    llm_patch = normalize_llm_graph_patch(extract_json_object(raw_text), session, dream_run, f"{runner}:llm-graph-structurer")
    patch = merge_graph_patches(facts_patch, llm_patch, generated_by=f"{runner}:llm-graph-structurer")
    patch = add_insight_entities(patch, session, dream_run)
    errors = validate_graph_patch(patch)
    if errors:
        raise RuntimeError("LLM graph structurer produced an invalid patch:\n" + "\n".join(errors))
    return patch, [display_path(prompt_path), display_path(response_path), display_path(raw_path), display_path(meta_path)]
