from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from typing import Any


@dataclass(frozen=True)
class QueryIntent:
    """Value object describing query intent extraction for retrieval."""

    intent: str
    operational_hits: tuple[str, ...]
    semantic_hits: tuple[str, ...]
    operational_context_budget: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "operational_hits": list(self.operational_hits),
            "semantic_hits": list(self.semantic_hits),
            "operational_context_budget": self.operational_context_budget,
        }


class QueryIntentPort(Protocol):
    """Port contract for query-intent classification in retrieval flow."""

    def classify(self, terms: list[str]) -> QueryIntent:
        """Classify terms into a normalized retrieval intent profile."""


class DefaultQueryIntentClassifier:
    """Default production classifier for query intent."""

    def classify(self, terms: list[str]) -> QueryIntent:
        lowered = {term.lower().strip() for term in terms if term.strip()}
        operational_hits = sorted(term for term in lowered if term in OPERATIONAL_QUERY_TERMS)
        semantic_hits = sorted(term for term in lowered if term in SEMANTIC_QUERY_TERMS)
        if operational_hits and not semantic_hits:
            intent = "operational"
        elif semantic_hits and not operational_hits:
            intent = "semantic"
        elif operational_hits and semantic_hits:
            intent = "mixed"
        else:
            intent = "balanced"
        if intent == "operational":
            operational_context_budget = 0.75
        elif intent == "mixed":
            operational_context_budget = 0.45
        elif intent == "semantic":
            operational_context_budget = 0.2
        else:
            operational_context_budget = 0.35
        return QueryIntent(
            intent=intent,
            operational_hits=tuple(operational_hits),
            semantic_hits=tuple(semantic_hits),
            operational_context_budget=operational_context_budget,
        )


def get_query_intent_classifier() -> QueryIntentPort:
    return DefaultQueryIntentClassifier()


HIGH_VALUE_ENTITY_TYPES = {
    "Project",
    "Session",
    "Decision",
    "OpenTask",
    "FailureMode",
    "Document",
    "Technology",
    "RiskEvent",
    "Concept",
    "Skill",
    "Service",
    "APIEndpoint",
    "Component",
    "Capability",
}
OPERATIONAL_ENTITY_TYPES = {"FileAccess", "CLICommand", "Tool", "Directory"}
SUPPORTING_ENTITY_TYPES = {"File", "ConfigFile", "CommandFamily", "EnvironmentVariable", "DreamRun", "Summary"}
OPERATIONAL_QUERY_TERMS = {
    "file",
    "files",
    "datei",
    "dateien",
    "path",
    "pfad",
    "command",
    "commands",
    "cli",
    "tool",
    "tools",
    "audit",
    "log",
    "logs",
    "changed",
    "modified",
    "geändert",
    "geaendert",
    "gelesen",
    "read",
    "write",
    "written",
}
SEMANTIC_QUERY_TERMS = {
    "decision",
    "entscheid",
    "entscheidung",
    "decisions",
    "open",
    "offen",
    "task",
    "tasks",
    "todo",
    "architecture",
    "architektur",
    "design",
    "why",
    "warum",
    "reason",
    "plan",
    "status",
    "risk",
    "risiko",
}
ENTITY_TYPES = sorted(HIGH_VALUE_ENTITY_TYPES | OPERATIONAL_ENTITY_TYPES | SUPPORTING_ENTITY_TYPES)
RESULT_KIND_WEIGHTS_BY_INTENT = {
    "operational": {
        "entity": 0.12,
        "graph_entity": 0.12,
        "summary": 0.02,
        "dream": 0.0,
        "project_memory": 0.0,
        "personal_memory": 0.0,
        "session": 0.0,
    },
    "semantic": {
        "entity": 0.08,
        "graph_entity": 0.08,
        "summary": 0.05,
        "dream": 0.04,
        "project_memory": 0.04,
        "personal_memory": 0.02,
        "session": 0.03,
    },
    "mixed": {
        "entity": 0.1,
        "graph_entity": 0.1,
        "summary": 0.03,
        "dream": 0.02,
        "project_memory": 0.02,
        "personal_memory": 0.0,
        "session": 0.02,
    },
    "balanced": {
        "entity": 0.06,
        "graph_entity": 0.06,
        "summary": 0.02,
        "dream": 0.02,
        "project_memory": 0.02,
        "personal_memory": 0.0,
        "session": 0.02,
    },
}


def classify_query_intent(terms: list[str], *, return_payload: bool = True) -> dict[str, Any] | QueryIntent:
    """Classify raw terms into intent profile.

    Default return is payload dict for existing call sites.
    Set return_payload=False to get the domain value object.
    """

    profile = get_query_intent_classifier().classify(terms)
    return profile.to_dict() if return_payload else profile


def entity_type_weight_for_query(entity_type: str, intent: str) -> float:
    if intent == "operational":
        if entity_type in OPERATIONAL_ENTITY_TYPES:
            return 1.0
        if entity_type in {"File", "ConfigFile", "CommandFamily"}:
            return 0.9
        if entity_type in {"Document", "EnvironmentVariable", "DreamRun", "Summary"}:
            return 0.65
        if entity_type in HIGH_VALUE_ENTITY_TYPES:
            return 0.35
        return 0.1
    if entity_type in HIGH_VALUE_ENTITY_TYPES:
        return 1.0
    if entity_type in SUPPORTING_ENTITY_TYPES:
        return 0.45
    if entity_type in OPERATIONAL_ENTITY_TYPES and intent == "operational":
        return 0.55
    if entity_type in OPERATIONAL_ENTITY_TYPES and intent == "mixed":
        return 0.15
    if entity_type in OPERATIONAL_ENTITY_TYPES and intent == "semantic":
        return -0.55
    if entity_type in OPERATIONAL_ENTITY_TYPES:
        return -0.35
    return 0.1


def retrieval_profile_from_terms(terms: list[str]) -> dict[str, Any]:
    intent_profile = classify_query_intent(terms)
    intent = str(intent_profile["intent"])
    return {
        "intent": intent_profile,
        "entity_type_weights": {entity_type: entity_type_weight_for_query(entity_type, intent) for entity_type in ENTITY_TYPES},
        "result_kind_weights": RESULT_KIND_WEIGHTS_BY_INTENT.get(intent, RESULT_KIND_WEIGHTS_BY_INTENT["balanced"]),
    }


def clamp_profile_weight(value: Any, *, default: float = 0.0) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    return max(-1.0, min(1.0, numeric))
