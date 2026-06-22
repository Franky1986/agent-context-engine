from __future__ import annotations

import re
from typing import Any

from ...infrastructure.config import MEMORY_DIR, safe_slug


GRAPH_SCHEMA_VERSION = "agent-memory-graph-v1"
GRAPH_CANDIDATE_SCHEMA_VERSION = "agent-memory-graph-candidates-v1"
GRAPH_MATCH_SCHEMA_VERSION = "agent-memory-graph-matches-v1"
GRAPH_DIR = MEMORY_DIR / "graph"
LLM_GRAPH_DIR = GRAPH_DIR / "llm-runs"
MAX_EVIDENCE_PER_ITEM = 8
LLM_GRAPH_TEXT_LIMIT = 40_000
ALLOWED_MEMORY_KINDS = {"raw", "episodic", "semantic", "procedural", "policy", "handover", "graph_fact"}
ALLOWED_SOURCE_KINDS = {"user", "assistant", "tool_call", "tool_output_ref", "dream", "dream_run", "graph_structuring", "manual", "session", "event"}
ALLOWED_RISK_LEVELS = {"low", "medium", "high", "unknown"}
ALLOWED_SENSITIVITY = {"normal", "private", "secret"}
ALLOWED_INJECTION_POLICIES = {"startup_safe", "on_demand", "never_auto"}
ALLOWED_POISONING_FLAGS = {
    "unverified_user_claim",
    "inferred_without_tool",
    "tool_output_omitted",
    "contradicted",
    "stale",
    "low_confidence",
    "scope_mismatch",
    "side_effect_related",
}

ALLOWED_ENTITY_TYPES = {
    "Session",
    "Project",
    "Directory",
    "File",
    "FileAccess",
    "FileChange",
    "FileDelete",
    "DreamRun",
    "Summary",
    "Memory",
    "Tool",
    "CLICommand",
    "CommandFamily",
    "ShellCommand",
    "Skill",
    "Technology",
    "Concept",
    "Decision",
    "OpenTask",
    "Ticket",
    "Issue",
    "PR",
    "Commit",
    "Branch",
    "EnvironmentVariable",
    "ConfigFile",
    "Service",
    "MCPServer",
    "Hook",
    "Scheduler",
    "LaunchAgent",
    "Error",
    "FailureMode",
    "Test",
    "TestRun",
    "Dependency",
    "Package",
    "APIEndpoint",
    "Database",
    "Table",
    "ExternalURL",
    "Document",
    "ReferenceAsset",
    "GeneratedAsset",
    "CredentialPlaceholder",
    "ClientHarness",
    "LLMModel",
    "RiskEvent",
    "RiskPolicyOverride",
    "TaintReset",
    "FirewallIntent",
    "FirewallRule",
    "FirewallRuleAudit",
    "SchemaProposal",
}

ALLOWED_RELATION_TYPES = {
    "IN_PROJECT",
    "HAS_PATH",
    "TOUCHED_FILE",
    "READ_FILE",
    "LISTED_FILE",
    "CREATED_FILE",
    "MODIFIED_FILE",
    "DELETED_FILE",
    "RENAMED_FILE",
    "WROTE_FILE",
    "PERFORMED",
    "ON_FILE",
    "USED_TOOL",
    "RAN_COMMAND",
    "INSTANCE_OF",
    "USED_SKILL",
    "USED_MODEL",
    "MENTIONED",
    "PRODUCED",
    "SUMMARIZED",
    "WROTE",
    "DERIVED_FROM",
    "USES_TECH",
    "DECLARES_DEPENDENCY",
    "OCCURRED_IN",
    "CAUSED_BY",
    "VALIDATED",
    "TRACKS",
    "AFFECTS",
    "TRIGGERS",
    "RUNS",
    "HAS_DOCUMENT",
    "PROPOSES_TYPE",
    "ALIASES_TYPE",
    "SPECIALIZES_TYPE",
}
DYNAMIC_ENTITY_TYPE_RE = re.compile(r"^[A-Z][A-Za-z0-9]{2,63}$")
DYNAMIC_RELATION_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,95}$")
BLOCKED_DYNAMIC_ENTITY_TYPES = {"Entity", "Node", "Object", "Thing", "Item", "Data", "Value", "Category"}
BLOCKED_DYNAMIC_RELATION_TYPES = {"RELATED", "LINKED", "HAS", "IS", "DOES", "USES"}
CANONICAL_ENGLISH_ENTITY_TYPES = {
    "APIEndpoint",
    "Capability",
    "Component",
    "Concept",
    "Decision",
    "Dependency",
    "Error",
    "FailureMode",
    "FirewallIntent",
    "Issue",
    "Memory",
    "OpenTask",
    "Package",
    "RiskEvent",
    "RiskPolicyOverride",
    "Scheduler",
    "SchemaProposal",
    "Service",
    "Summary",
    "Technology",
    "Test",
}
LANGUAGE_PRESERVING_ENTITY_TYPES = {
    "Branch",
    "CLICommand",
    "ClientHarness",
    "CommandFamily",
    "Commit",
    "ConfigFile",
    "CredentialPlaceholder",
    "Database",
    "Directory",
    "Document",
    "DreamRun",
    "EnvironmentVariable",
    "ExternalURL",
    "File",
    "FileAccess",
    "GeneratedAsset",
    "Hook",
    "LLMModel",
    "LaunchAgent",
    "MCPServer",
    "PR",
    "Project",
    "ReferenceAsset",
    "RiskPolicyOverride",
    "Session",
    "ShellCommand",
    "Skill",
    "Table",
    "TaintReset",
    "Ticket",
    "Tool",
}
GERMAN_NAME_RE = re.compile(r"[äöüß]|\b(entscheidung|entscheidungen|beschlossen|gilt|offen|offene|nächste|naechste|aufgabe|aufgaben|fehler|ursache|risiko|risiken)\b", re.I)
GENERIC_ENGLISH_NAMES_BY_TYPE = {
    ("Decision", "entscheidung"): "Decision",
    ("Decision", "entscheidungen"): "Decision",
    ("Decision", "beschlossen"): "Decision",
    ("Decision", "gilt"): "Decision",
    ("Decision", "default"): "Decision",
    ("OpenTask", "offen"): "Open task",
    ("OpenTask", "offene"): "Open task",
    ("OpenTask", "nächste"): "Next task",
    ("OpenTask", "naechste"): "Next task",
    ("OpenTask", "todo"): "To do",
    ("OpenTask", "follow-up"): "Follow-up",
    ("FailureMode", "fehler"): "Failure mode",
    ("FailureMode", "ursache"): "Root cause",
}
GERMAN_TOKEN_TRANSLATIONS = {
    "entscheidung": "decision",
    "entscheidungen": "decisions",
    "offen": "open",
    "offene": "open",
    "aufgabe": "task",
    "aufgaben": "tasks",
    "nächste": "next",
    "naechste": "next",
    "fehler": "error",
    "ursache": "root cause",
    "ursachenanalyse": "root cause analysis",
    "risiko": "risk",
    "risiken": "risks",
}


def clamp_confidence(value: Any, default: float = 1.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = default
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(score, 4)


def normalized_metadata(
    value: dict[str, Any] | None = None,
    *,
    default_memory_kind: str = "graph_fact",
    default_source_kind: str = "event",
    default_confidence: float = 1.0,
) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    confidence = clamp_confidence(raw.get("confidence"), default_confidence)
    flags = raw.get("poisoning_flags") or raw.get("poisoningFlags") or []
    if isinstance(flags, str):
        flags = [flags]
    flags = [safe_slug(str(flag).strip().lower()) for flag in flags if str(flag).strip()]
    flags = [flag for flag in flags if flag in ALLOWED_POISONING_FLAGS]
    if confidence < 0.5 and "low_confidence" not in flags:
        flags.append("low_confidence")
    return {
        "memory_kind": raw.get("memory_kind") if raw.get("memory_kind") in ALLOWED_MEMORY_KINDS else default_memory_kind,
        "source_kind": raw.get("source_kind") if raw.get("source_kind") in ALLOWED_SOURCE_KINDS else default_source_kind,
        "confidence": confidence,
        "risk_level": raw.get("risk_level") if raw.get("risk_level") in ALLOWED_RISK_LEVELS else "low",
        "sensitivity": raw.get("sensitivity") if raw.get("sensitivity") in ALLOWED_SENSITIVITY else "normal",
        "injection_policy": raw.get("injection_policy") if raw.get("injection_policy") in ALLOWED_INJECTION_POLICIES else "on_demand",
        "valid_from": raw.get("valid_from") or None,
        "valid_to": raw.get("valid_to") or None,
        "staleness": raw.get("staleness") or None,
        "poisoning_flags": flags,
    }


def apply_metadata(target: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    target["memory_kind"] = metadata["memory_kind"]
    target["source_kind"] = metadata["source_kind"]
    target["confidence"] = metadata["confidence"]
    target["risk_level"] = metadata["risk_level"]
    target["sensitivity"] = metadata["sensitivity"]
    target["injection_policy"] = metadata["injection_policy"]
    target["valid_from"] = metadata["valid_from"]
    target["valid_to"] = metadata["valid_to"]
    target["staleness"] = metadata["staleness"]
    target["poisoning_flags"] = list(metadata["poisoning_flags"])
    return target


def _looks_like_identifier(value: str) -> bool:
    lowered = value.lower()
    return (
        "/" in value
        or "\\" in value
        or "://" in value
        or lowered.startswith(("$", "env:"))
        or bool(re.search(r"\.[a-z0-9]{1,8}($|[#?])", lowered))
    )


def _source_language(value: str) -> str:
    if GERMAN_NAME_RE.search(value):
        return "de"
    return "unknown"


def _canonical_english_name(entity_type: str, name: str) -> str:
    stripped = " ".join(name.split())
    lowered = stripped.lower()
    mapped = GENERIC_ENGLISH_NAMES_BY_TYPE.get((entity_type, lowered))
    if mapped:
        return mapped
    if not GERMAN_NAME_RE.search(stripped):
        return stripped
    words = re.split(r"(\W+)", stripped)
    translated = "".join(GERMAN_TOKEN_TRANSLATIONS.get(word.lower(), word) for word in words)
    return translated[:1].upper() + translated[1:] if translated else stripped


def normalize_entity_language(entity: dict[str, Any]) -> dict[str, Any]:
    entity_type = str(entity.get("type") or "")
    dynamic_semantic_type = bool(DYNAMIC_ENTITY_TYPE_RE.fullmatch(entity_type)) and entity_type not in BLOCKED_DYNAMIC_ENTITY_TYPES
    if entity_type not in CANONICAL_ENGLISH_ENTITY_TYPES and not dynamic_semantic_type:
        return entity
    name = str(entity.get("name") or entity.get("key") or "").strip()
    if not name or _looks_like_identifier(name):
        return entity
    canonical = _canonical_english_name(entity_type, name)
    aliases = [str(alias) for alias in (entity.get("aliases") or []) if str(alias).strip()]
    if canonical != name and name not in aliases:
        aliases.insert(0, name)
    properties = dict(entity.get("properties") or {})
    language = _source_language(name)
    if canonical != name:
        properties.setdefault("original_name", name)
        if language != "unknown":
            properties.setdefault("source_language", language)
        entity["name"] = canonical
    entity["aliases"] = aliases[:10]
    entity["properties"] = properties
    return entity


def is_allowed_entity_type(entity_type: Any) -> bool:
    value = str(entity_type or "")
    return value in ALLOWED_ENTITY_TYPES or (
        bool(DYNAMIC_ENTITY_TYPE_RE.fullmatch(value)) and value not in BLOCKED_DYNAMIC_ENTITY_TYPES
    )


def is_allowed_relation_type(relation_type: Any) -> bool:
    value = str(relation_type or "")
    return value in ALLOWED_RELATION_TYPES or (
        bool(DYNAMIC_RELATION_TYPE_RE.fullmatch(value)) and value not in BLOCKED_DYNAMIC_RELATION_TYPES
    )


def is_dynamic_entity_type(entity_type: Any) -> bool:
    value = str(entity_type or "")
    return is_allowed_entity_type(value) and value not in ALLOWED_ENTITY_TYPES


def is_dynamic_relation_type(relation_type: Any) -> bool:
    value = str(relation_type or "")
    return is_allowed_relation_type(value) and value not in ALLOWED_RELATION_TYPES


def validate_graph_patch(patch: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if patch.get("schema_version") != GRAPH_SCHEMA_VERSION:
        errors.append("invalid schema_version")
    entity_keys: set[tuple[str, str]] = set()
    for idx, entity in enumerate(patch.get("entities", [])):
        etype = entity.get("type")
        key = entity.get("key")
        if not is_allowed_entity_type(etype):
            errors.append(f"entity[{idx}] unsupported type: {etype}")
        if not key:
            errors.append(f"entity[{idx}] missing key")
        if not entity.get("evidence"):
            errors.append(f"entity[{idx}] missing evidence")
        if entity.get("memory_kind") not in ALLOWED_MEMORY_KINDS:
            errors.append(f"entity[{idx}] invalid memory_kind: {entity.get('memory_kind')}")
        if entity.get("source_kind") not in ALLOWED_SOURCE_KINDS:
            errors.append(f"entity[{idx}] invalid source_kind: {entity.get('source_kind')}")
        if entity.get("risk_level") not in ALLOWED_RISK_LEVELS:
            errors.append(f"entity[{idx}] invalid risk_level: {entity.get('risk_level')}")
        if entity.get("sensitivity") not in ALLOWED_SENSITIVITY:
            errors.append(f"entity[{idx}] invalid sensitivity: {entity.get('sensitivity')}")
        if entity.get("injection_policy") not in ALLOWED_INJECTION_POLICIES:
            errors.append(f"entity[{idx}] invalid injection_policy: {entity.get('injection_policy')}")
        for flag in entity.get("poisoning_flags") or []:
            if flag not in ALLOWED_POISONING_FLAGS:
                errors.append(f"entity[{idx}] invalid poisoning_flag: {flag}")
        entity_keys.add((str(etype), str(key)))
    for idx, relation in enumerate(patch.get("relations", [])):
        rtype = relation.get("type")
        from_ref = relation.get("from", {})
        to_ref = relation.get("to", {})
        if not is_allowed_relation_type(rtype):
            errors.append(f"relation[{idx}] unsupported type: {rtype}")
        if (str(from_ref.get("type")), str(from_ref.get("key"))) not in entity_keys:
            errors.append(f"relation[{idx}] from entity missing")
        if (str(to_ref.get("type")), str(to_ref.get("key"))) not in entity_keys:
            errors.append(f"relation[{idx}] to entity missing")
        if not relation.get("evidence"):
            errors.append(f"relation[{idx}] missing evidence")
        if relation.get("memory_kind") not in ALLOWED_MEMORY_KINDS:
            errors.append(f"relation[{idx}] invalid memory_kind: {relation.get('memory_kind')}")
        if relation.get("source_kind") not in ALLOWED_SOURCE_KINDS:
            errors.append(f"relation[{idx}] invalid source_kind: {relation.get('source_kind')}")
        if relation.get("risk_level") not in ALLOWED_RISK_LEVELS:
            errors.append(f"relation[{idx}] invalid risk_level: {relation.get('risk_level')}")
        if relation.get("sensitivity") not in ALLOWED_SENSITIVITY:
            errors.append(f"relation[{idx}] invalid sensitivity: {relation.get('sensitivity')}")
        if relation.get("injection_policy") not in ALLOWED_INJECTION_POLICIES:
            errors.append(f"relation[{idx}] invalid injection_policy: {relation.get('injection_policy')}")
        for flag in relation.get("poisoning_flags") or []:
            if flag not in ALLOWED_POISONING_FLAGS:
                errors.append(f"relation[{idx}] invalid poisoning_flag: {flag}")
    return errors


def ensure_patch_metadata(patch: dict[str, Any]) -> dict[str, Any]:
    patch = dict(patch)
    entities: list[dict[str, Any]] = []
    for entity in patch.get("entities", []):
        if not isinstance(entity, dict):
            continue
        copied = dict(entity)
        copied["properties"] = dict(copied.get("properties") or {})
        copied["aliases"] = list(copied.get("aliases") or [])
        normalize_entity_language(copied)
        apply_metadata(
            copied,
            normalized_metadata(
                copied,
                default_memory_kind="semantic",
                default_source_kind="graph_structuring",
                default_confidence=clamp_confidence(copied.get("confidence"), 0.8),
            ),
        )
        entities.append(copied)
    relations: list[dict[str, Any]] = []
    for relation in patch.get("relations", []):
        if not isinstance(relation, dict):
            continue
        copied = dict(relation)
        apply_metadata(
            copied,
            normalized_metadata(
                copied,
                default_memory_kind="graph_fact",
                default_source_kind="graph_structuring",
                default_confidence=clamp_confidence(copied.get("confidence"), 0.8),
            ),
        )
        relations.append(copied)
    patch["entities"] = entities
    patch["relations"] = relations
    return patch


def graph_schema_context() -> dict[str, Any]:
    return {
        "schema_version": GRAPH_SCHEMA_VERSION,
        "candidate_schema_version": GRAPH_CANDIDATE_SCHEMA_VERSION,
        "match_schema_version": GRAPH_MATCH_SCHEMA_VERSION,
        "entity_types": sorted(ALLOWED_ENTITY_TYPES),
        "relation_types": sorted(ALLOWED_RELATION_TYPES),
        "dynamic_schema_rules": {
            "entity_type_pattern": "PascalCase, 3-64 alphanumeric characters, domain-specific",
            "relation_type_pattern": "UPPER_SNAKE_CASE, 3-96 alphanumeric/underscore characters, domain-specific",
            "blocked_entity_type_examples": sorted(BLOCKED_DYNAMIC_ENTITY_TYPES),
            "blocked_relation_type_examples": sorted(BLOCKED_DYNAMIC_RELATION_TYPES),
        },
        "neo4j_internal_relation_types": ["AM_RELATION_FROM", "AM_RELATION_TO", "HAS_EVIDENCE"],
        "rules": [
            "Prefer core entity_types and relation_types when they fit.",
            "You may introduce specific dynamic entity types in PascalCase and relation types in UPPER_SNAKE_CASE whenever they add useful retrievable detail, even if core types are also present.",
            "Capture concrete names, places, organizations, examples, domain objects, and project-specific concepts as dynamic entities when they are meaningful for later retrieval.",
            "Use dynamic relations to connect those concrete entities to core entities such as Session, Project, Decision, OpenTask, Document, File, or Technology.",
            "Avoid generic dynamic names such as Entity, Thing, Item, RELATED, LINKED, HAS, IS, DOES, or USES.",
            "Every entity and relation must carry evidence with source_type, session_id, field, and a short quote when available.",
            "Every entity and relation must carry memory_kind, source_kind, confidence, risk_level, sensitivity, injection_policy, and poisoning_flags.",
            "Use sensitivity='private' or 'secret' and injection_policy='never_auto' for sensitive facts.",
            "Use risk_level='medium' or 'high' for unverified claims, side-effect-related facts, or contradictions.",
            "For semantic entity types, prefer canonical English names and keep original-language names as aliases.",
            "Do not translate paths, commands, URLs, environment variables, ticket IDs, branch names, model names, or project names.",
            "Prefer reusing existing entities when type and key match exactly.",
            "Prefer reusing existing entities when name, alias, path, URL, or command are near matches.",
            "Create a new entity only when no exact, alias, path, URL, command, or high-similarity match exists.",
            "Keep Neo4j an index derived from JSON patches; deterministic code performs writes.",
        ],
        "metadata_rules": {
            "memory_kind": sorted(ALLOWED_MEMORY_KINDS),
            "source_kind": sorted(ALLOWED_SOURCE_KINDS),
            "risk_level": sorted(ALLOWED_RISK_LEVELS),
            "sensitivity": sorted(ALLOWED_SENSITIVITY),
            "injection_policy": sorted(ALLOWED_INJECTION_POLICIES),
            "poisoning_flags": sorted(ALLOWED_POISONING_FLAGS),
        },
        "entity_key_rules": {
            "File/Directory/Document/ReferenceAsset/GeneratedAsset/ConfigFile": "absolute path resolved from the session/root working directory",
            "CLICommand/ShellCommand": "normalized executable plus relevant leading arguments with paths/timestamps/uuids collapsed",
            "CommandFamily": "normalized command family such as executable or executable plus stable subcommand",
            "ExternalURL": "full URL",
            "EnvironmentVariable": "variable name",
            "default": "safe lowercase slug",
        },
    }
