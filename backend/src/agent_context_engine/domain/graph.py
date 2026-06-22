"""Graph domain value objects.

These classes provide stable, side-effect-free representations for the
Graph bounded context and are intentionally free of persistence logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping
import json


def _as_row_dict(row: Any) -> Mapping[str, Any]:
    if isinstance(row, Mapping):
        return row
    if row is None:
        return {}
    try:
        return {str(key): row[key] for key in row.keys()}
    except Exception:
        return {}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return [value]


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_float(value: Any, default: float | None = 0.0) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


SCHEMA_PROPOSAL_STATUSES = {"pending", "reviewed", "approved", "rejected", "promoted", "archived"}
SCHEMA_PROPOSAL_FINAL_STATUSES = {"approved", "rejected", "promoted"}


@dataclass(frozen=True)
class GraphArtifact:
    artifact_id: str
    artifact_type: str
    status: str
    created_at: str
    path: str | None = None
    session_id: str | None = None
    dream_run_id: str | None = None
    runner: str | None = None
    entity_count: int = 0
    relation_count: int = 0
    evidence_count: int = 0
    intent: str | None = None
    helpful_score: float | None = None
    tags: list[str] = field(default_factory=list)
    error_message: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "GraphArtifact":
        row = _as_row_dict(row)
        return cls(
            artifact_id=str(row.get("artifact_id") or row.get("graph_artifact_id") or ""),
            artifact_type=str(row.get("artifact_type") or ""),
            status=str(row.get("status") or ""),
            created_at=str(row["created_at"]),
            path=row.get("path"),
            session_id=row.get("session_id"),
            dream_run_id=row.get("dream_run_id"),
            runner=row.get("runner"),
            entity_count=_as_int(row.get("entity_count")) or 0,
            relation_count=_as_int(row.get("relation_count")) or 0,
            evidence_count=_as_int(row.get("evidence_count")) or 0,
            intent=row.get("intent"),
            helpful_score=_as_float(row.get("helpful_score"), None),
            tags=_as_list(row.get("tags") or row.get("tags_json")),
            error_message=row.get("error_message"),
        )

    def short_path(self) -> str:
        return self.path or "-"

    @property
    def has_signal(self) -> bool:
        return self.helpful_score is not None or bool(self.tags) or bool(self.intent)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "status": self.status,
            "created_at": self.created_at,
            "path": self.path,
            "session_id": self.session_id,
            "dream_run_id": self.dream_run_id,
            "runner": self.runner,
            "entity_count": self.entity_count,
            "relation_count": self.relation_count,
            "evidence_count": self.evidence_count,
            "intent": self.intent,
            "helpful_score": self.helpful_score,
            "tags": self.tags,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class GraphCountSummary:
    name: str
    count: int

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "GraphCountSummary":
        row = _as_row_dict(row)
        return cls(
            name=str(row.get("type") or row.get("relation_type") or row.get("normalized_name") or ""),
            count=_as_int(row.get("count")) or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "count": self.count}


@dataclass(frozen=True)
class GraphResolutionCandidate:
    surface: str
    count: int
    types: list[str] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "GraphResolutionCandidate":
        row = _as_row_dict(row)
        return cls(
            surface=str(row.get("surface") or ""),
            count=_as_int(row.get("count")) or 0,
            types=list(row.get("types") or []),
            examples=list(row.get("examples") or []),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "count": self.count,
            "types": self.types,
            "examples": self.examples,
        }


@dataclass(frozen=True)
class GraphCuratedEntity:
    entity_id: str
    type: str
    name: str
    key: str
    score: float
    evidence_count: int
    relation_count: int

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "GraphCuratedEntity":
        row = _as_row_dict(row)
        return cls(
            entity_id=str(row.get("entity_id") or ""),
            type=str(row.get("type") or ""),
            name=str(row.get("name") or ""),
            key=str(row.get("key") or ""),
            score=float(row.get("score") or 0.0),
            evidence_count=_as_int(row.get("evidence_count")) or 0,
            relation_count=_as_int(row.get("relation_count")) or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "type": self.type,
            "name": self.name,
            "key": self.key,
            "score": self.score,
            "evidence_count": self.evidence_count,
            "relation_count": self.relation_count,
        }


@dataclass(frozen=True)
class GraphCuratedRelation:
    type: str
    from_entity: dict[str, Any]
    to_entity: dict[str, Any]
    confidence: float | None
    evidence_count: int

    @classmethod
    def from_mapping(cls, row: Mapping[str, Any]) -> "GraphCuratedRelation":
        row = _as_row_dict(row)
        return cls(
            type=str(row.get("type") or ""),
            from_entity={
                "id": str(row.get("from_id") or ""),
                "type": str(row.get("from_type") or ""),
                "name": str(row.get("from_name") or ""),
            },
            to_entity={
                "id": str(row.get("to_id") or ""),
                "type": str(row.get("to_type") or ""),
                "name": str(row.get("to_name") or ""),
            },
            confidence=_as_float(row.get("confidence"), None),
            evidence_count=_as_int(row.get("evidence_count")) or 0,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "from": self.from_entity,
            "to": self.to_entity,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
        }


@dataclass(frozen=True)
class GraphCuratedContext:
    query: str
    terms: list[str]
    intent_profile: dict[str, Any]
    entities: list[GraphCuratedEntity]
    relations: list[GraphCuratedRelation]
    quality_notes: list[str]
    max_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "terms": self.terms,
            "intent_profile": self.intent_profile,
            "entities": [item.to_dict() for item in self.entities],
            "relations": [item.to_dict() for item in self.relations],
            "quality_notes": self.quality_notes,
            "max_score": self.max_score,
        }

    @property
    def has_data(self) -> bool:
        return bool(self.entities or self.relations)


@dataclass(frozen=True)
class GraphExpectedPresence:
    expected_entity_types: list[str]
    expected_relation_types: list[str]
    seen_entity_types: list[str]
    seen_relation_types: list[str]
    missing_entity_types: list[str]
    missing_relation_types: list[str]

    @property
    def passed(self) -> bool:
        return not self.missing_entity_types and not self.missing_relation_types

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected_entity_types": self.expected_entity_types,
            "expected_relation_types": self.expected_relation_types,
            "seen_entity_types": self.seen_entity_types,
            "seen_relation_types": self.seen_relation_types,
            "missing_entity_types": self.missing_entity_types,
            "missing_relation_types": self.missing_relation_types,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class GraphQueryAssessment:
    text_result_count: int
    graph_entity_count: int
    graph_relation_count: int
    likely_graph_lift: bool
    graph_max_score: float
    expected_presence: GraphExpectedPresence | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "text_result_count": self.text_result_count,
            "graph_entity_count": self.graph_entity_count,
            "graph_relation_count": self.graph_relation_count,
            "likely_graph_lift": self.likely_graph_lift,
            "graph_max_score": self.graph_max_score,
        }
        if self.expected_presence is not None:
            payload["expected_presence"] = self.expected_presence.to_dict()
        return payload


@dataclass(frozen=True)
class GraphQualityEvaluation:
    id: str | None
    query: str
    text_results: list[dict[str, Any]]
    curated_graph: GraphCuratedContext
    assessment: GraphQueryAssessment

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "query": self.query,
            "text_results": self.text_results,
            "curated_graph": self.curated_graph.to_dict(),
            "assessment": self.assessment.to_dict(),
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


@dataclass(frozen=True)
class GraphQualityOverview:
    entity_total: int
    relation_total: int
    evidence_total: int
    entity_evidence_total: int
    relation_evidence_total: int
    orphan_entity_total: int
    source_anchored_entity_total: int
    operational_entity_total: int
    high_value_entity_total: int
    generic_semantic_entity_total: int
    top_entity_types: list[GraphCountSummary]
    top_relation_types: list[GraphCountSummary]
    duplicate_name_groups: list[GraphCountSummary]
    entity_resolution_candidates: list[GraphResolutionCandidate]

    @property
    def entity_evidence_ratio(self) -> float:
        return round(self.entity_evidence_total / self.entity_total, 4) if self.entity_total else 0.0

    @property
    def relation_evidence_ratio(self) -> float:
        return round(self.relation_evidence_total / self.relation_total, 4) if self.relation_total else 0.0

    @property
    def orphan_entity_ratio(self) -> float:
        return round(self.orphan_entity_total / self.entity_total, 4) if self.entity_total else 0.0

    @property
    def source_anchored_entity_ratio(self) -> float:
        return round(self.source_anchored_entity_total / self.entity_total, 4) if self.entity_total else 0.0

    @property
    def operational_entity_ratio(self) -> float:
        return round(self.operational_entity_total / self.entity_total, 4) if self.entity_total else 0.0

    @property
    def high_value_entity_ratio(self) -> float:
        return round(self.high_value_entity_total / self.entity_total, 4) if self.entity_total else 0.0

    @property
    def noise_entity_total(self) -> int:
        return self.operational_entity_total

    @property
    def noise_entity_ratio(self) -> float:
        return self.operational_entity_ratio

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
        *,
        top_entity_types: list[GraphCountSummary] | None = None,
        top_relation_types: list[GraphCountSummary] | None = None,
        duplicate_name_groups: list[GraphCountSummary] | None = None,
        entity_resolution_candidates: list[GraphResolutionCandidate] | None = None,
    ) -> "GraphQualityOverview":
        return cls(
            entity_total=_as_int(payload.get("entity_total")) or 0,
            relation_total=_as_int(payload.get("relation_total")) or 0,
            evidence_total=_as_int(payload.get("evidence_total")) or 0,
            entity_evidence_total=_as_int(payload.get("entity_evidence_total")) or 0,
            relation_evidence_total=_as_int(payload.get("relation_evidence_total")) or 0,
            orphan_entity_total=_as_int(payload.get("orphan_entity_total")) or 0,
            source_anchored_entity_total=_as_int(payload.get("source_anchored_entity_total")) or 0,
            operational_entity_total=_as_int(payload.get("operational_entity_total")) or 0,
            high_value_entity_total=_as_int(payload.get("high_value_entity_total")) or 0,
            generic_semantic_entity_total=_as_int(payload.get("generic_semantic_entity_total")) or 0,
            top_entity_types=top_entity_types or [GraphCountSummary(str(row.get("type") or ""), int(row.get("count") or 0)) for row in payload.get("top_entity_types", [])],
            top_relation_types=top_relation_types or [GraphCountSummary(str(row.get("relation_type") or row.get("type") or ""), int(row.get("count") or 0)) for row in payload.get("top_relation_types", [])],
            duplicate_name_groups=duplicate_name_groups or [GraphCountSummary(str(row.get("normalized_name") or row.get("type") or ""), int(row.get("count") or 0)) for row in payload.get("duplicate_name_groups", [])],
            entity_resolution_candidates=entity_resolution_candidates or [GraphResolutionCandidate.from_mapping(row) for row in payload.get("entity_resolution_candidates", [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_total": self.entity_total,
            "relation_total": self.relation_total,
            "evidence_total": self.evidence_total,
            "entity_evidence_total": self.entity_evidence_total,
            "relation_evidence_total": self.relation_evidence_total,
            "orphan_entity_total": self.orphan_entity_total,
            "source_anchored_entity_total": self.source_anchored_entity_total,
            "operational_entity_total": self.operational_entity_total,
            "high_value_entity_total": self.high_value_entity_total,
            "generic_semantic_entity_total": self.generic_semantic_entity_total,
            "entity_evidence_ratio": self.entity_evidence_ratio,
            "relation_evidence_ratio": self.relation_evidence_ratio,
            "orphan_entity_ratio": self.orphan_entity_ratio,
            "source_anchored_entity_ratio": self.source_anchored_entity_ratio,
            "operational_entity_ratio": self.operational_entity_ratio,
            "high_value_entity_ratio": self.high_value_entity_ratio,
            "noise_entity_total": self.noise_entity_total,
            "noise_entity_ratio": self.noise_entity_ratio,
            "top_entity_types": [item.to_dict() for item in self.top_entity_types],
            "top_relation_types": [item.to_dict() for item in self.top_relation_types],
            "duplicate_name_groups": [item.to_dict() for item in self.duplicate_name_groups],
            "entity_resolution_candidates": [item.to_dict() for item in self.entity_resolution_candidates],
        }


@dataclass(frozen=True)
class EvidenceLink:
    owner_type: str
    owner_id: str
    source_type: str
    session_id: str | None = None
    event_seq: int | None = None
    field: str | None = None
    path: str | None = None
    quote: str | None = None

    @property
    def key(self) -> str:
        return json.dumps(
            {
                "owner_type": self.owner_type,
                "owner_id": self.owner_id,
                "source_type": self.source_type,
                "session_id": self.session_id or "",
                "event_seq": self.event_seq,
                "field": self.field,
                "path": self.path,
                "quote": self.quote,
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "EvidenceLink":
        row = _as_row_dict(row)
        return cls(
            owner_type=str(row.get("owner_type") or ""),
            owner_id=str(row.get("owner_id") or ""),
            source_type=str(row.get("source_type") or ""),
            session_id=row.get("session_id"),
            event_seq=_as_int(row.get("event_seq")),
            field=row.get("field"),
            path=row.get("path"),
            quote=row.get("quote"),
        )

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> "EvidenceLink":
        return cls(
            owner_type=str(row.get("owner_type") or ""),
            owner_id=str(row.get("owner_id") or ""),
            source_type=str(row.get("source_type") or ""),
            session_id=row.get("session_id"),
            event_seq=_as_int(row.get("event_seq")),
            field=row.get("field"),
            path=row.get("path"),
            quote=row.get("quote"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_type": self.owner_type,
            "owner_id": self.owner_id,
            "source_type": self.source_type,
            "session_id": self.session_id,
            "event_seq": self.event_seq,
            "field": self.field,
            "path": self.path,
            "quote": self.quote,
        }

    @property
    def is_queryable(self) -> bool:
        return bool(self.quote and self.quote.strip())


@dataclass(frozen=True)
class GraphEntity:
    entity_id: str
    type: str
    key: str
    name: str
    aliases: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    first_seen_at: str = ""
    last_seen_at: str = ""
    artifact_id: str | None = None
    session_id: str | None = None
    dream_run_id: str | None = None
    intent: str | None = None
    helpful_score: float | None = None
    tags: list[str] = field(default_factory=list)
    memory_kind: str = "graph_fact"
    source_kind: str = "graph_structuring"
    risk_level: str = "low"
    sensitivity: str = "normal"
    injection_policy: str = "on_demand"
    valid_from: str | None = None
    valid_to: str | None = None
    staleness: str | None = None
    poisoning_flags: list[str] = field(default_factory=list)
    evidence: list[EvidenceLink] = field(default_factory=list)

    @property
    def is_stale(self) -> bool:
        return self.staleness == "stale" or (self.helpful_score is not None and self.helpful_score < 0)

    @property
    def confidence_bucket(self) -> str:
        if self.confidence >= 0.9:
            return "high"
        if self.confidence >= 0.65:
            return "medium"
        return "low"

    def with_evidence(self, evidence: list[EvidenceLink]) -> "GraphEntity":
        return replace(self, evidence=list(evidence))

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "GraphEntity":
        row = _as_row_dict(row)
        evidence = [
            _decode_evidence_link(
                item,
                owner_type="entity",
                owner_id=str(row.get("entity_id") or ""),
            )
            for item in _as_list(row.get("evidence") or row.get("evidence_json"))
        ]
        return cls(
            entity_id=str(row["entity_id"]),
            type=str(row["type"]),
            key=str(row.get("key") or ""),
            name=str(row.get("name") or ""),
            aliases=_as_list(row.get("aliases") or row.get("aliases_json")),
            properties=_as_dict(row.get("properties") or row.get("properties_json")),
            confidence=_as_float(row.get("confidence"), 1.0),
            first_seen_at=str(row.get("first_seen_at") or ""),
            last_seen_at=str(row.get("last_seen_at") or ""),
            artifact_id=row.get("artifact_id"),
            session_id=row.get("session_id"),
            dream_run_id=row.get("dream_run_id"),
            intent=row.get("intent"),
            helpful_score=_as_float(row.get("helpful_score"), None),
            tags=_as_list(row.get("tags") or row.get("tags_json")),
            memory_kind=str(row.get("memory_kind") or "graph_fact"),
            source_kind=str(row.get("source_kind") or "graph_structuring"),
            risk_level=str(row.get("risk_level") or "low"),
            sensitivity=str(row.get("sensitivity") or "normal"),
            injection_policy=str(row.get("injection_policy") or "on_demand"),
            valid_from=row.get("valid_from"),
            valid_to=row.get("valid_to"),
            staleness=row.get("staleness"),
            poisoning_flags=_as_list(row.get("poisoning_flags") or row.get("poisoning_flags_json")),
            evidence=evidence,
        )

    @classmethod
    def from_patch_item(cls, item: Mapping[str, Any]) -> "GraphEntity":
        return cls(
            entity_id=str(item.get("id") or item.get("entity_id") or ""),
            type=str(item.get("type") or ""),
            key=str(item.get("key") or ""),
            name=str(item.get("name") or ""),
            aliases=_as_list(item.get("aliases")),
            properties=_as_dict(item.get("properties")),
            confidence=_as_float(item.get("confidence"), 1.0),
            first_seen_at=str(item.get("first_seen_at") or ""),
            last_seen_at=str(item.get("last_seen_at") or ""),
            artifact_id=item.get("artifact_id"),
            session_id=item.get("session_id"),
            dream_run_id=item.get("dream_run_id"),
            intent=item.get("intent"),
            helpful_score=_as_float(item.get("helpful_score"), None),
            tags=_as_list(item.get("tags")),
            memory_kind=str(item.get("memory_kind") or "graph_fact"),
            source_kind=str(item.get("source_kind") or "graph_structuring"),
            risk_level=str(item.get("risk_level") or "low"),
            sensitivity=str(item.get("sensitivity") or "normal"),
            injection_policy=str(item.get("injection_policy") or "on_demand"),
            valid_from=item.get("valid_from"),
            valid_to=item.get("valid_to"),
            staleness=item.get("staleness"),
            poisoning_flags=_as_list(item.get("poisoning_flags")),
            evidence=[EvidenceLink.from_dict(e) for e in _as_list(item.get("evidence"))],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "type": self.type,
            "key": self.key,
            "name": self.name,
            "aliases": self.aliases,
            "properties": self.properties,
            "confidence": self.confidence,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "artifact_id": self.artifact_id,
            "session_id": self.session_id,
            "dream_run_id": self.dream_run_id,
            "intent": self.intent,
            "helpful_score": self.helpful_score,
            "tags": self.tags,
            "memory_kind": self.memory_kind,
            "source_kind": self.source_kind,
            "risk_level": self.risk_level,
            "sensitivity": self.sensitivity,
            "injection_policy": self.injection_policy,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "staleness": self.staleness,
            "poisoning_flags": self.poisoning_flags,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class GraphRelation:
    relation_id: str
    from_entity_id: str
    relation_type: str
    to_entity_id: str
    properties: dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    first_seen_at: str = ""
    last_seen_at: str = ""
    artifact_id: str | None = None
    session_id: str | None = None
    dream_run_id: str | None = None
    intent: str | None = None
    helpful_score: float | None = None
    tags: list[str] = field(default_factory=list)
    memory_kind: str = "graph_fact"
    source_kind: str = "graph_structuring"
    risk_level: str = "low"
    sensitivity: str = "normal"
    injection_policy: str = "on_demand"
    valid_from: str | None = None
    valid_to: str | None = None
    staleness: str | None = None
    poisoning_flags: list[str] = field(default_factory=list)
    evidence: list[EvidenceLink] = field(default_factory=list)

    @property
    def is_valid_type(self) -> bool:
        return bool(self.relation_type and self.relation_type.strip())

    @property
    def endpoint_pair(self) -> tuple[str, str]:
        return (self.from_entity_id, self.to_entity_id)

    def with_evidence(self, evidence: list[EvidenceLink]) -> "GraphRelation":
        return replace(self, evidence=list(evidence))

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "GraphRelation":
        row = _as_row_dict(row)
        evidence = [
            _decode_evidence_link(
                item,
                owner_type="relation",
                owner_id=str(row.get("relation_id") or ""),
            )
            for item in _as_list(row.get("evidence") or row.get("evidence_json"))
        ]
        return cls(
            relation_id=str(row["relation_id"]),
            from_entity_id=str(row["from_entity_id"]),
            relation_type=str(row["relation_type"]),
            to_entity_id=str(row["to_entity_id"]),
            properties=_as_dict(row.get("properties") or row.get("properties_json")),
            confidence=_as_float(row.get("confidence"), 1.0),
            first_seen_at=str(row.get("first_seen_at") or ""),
            last_seen_at=str(row.get("last_seen_at") or ""),
            artifact_id=row.get("artifact_id"),
            session_id=row.get("session_id"),
            dream_run_id=row.get("dream_run_id"),
            intent=row.get("intent"),
            helpful_score=_as_float(row.get("helpful_score"), None),
            tags=_as_list(row.get("tags") or row.get("tags_json")),
            memory_kind=str(row.get("memory_kind") or "graph_fact"),
            source_kind=str(row.get("source_kind") or "graph_structuring"),
            risk_level=str(row.get("risk_level") or "low"),
            sensitivity=str(row.get("sensitivity") or "normal"),
            injection_policy=str(row.get("injection_policy") or "on_demand"),
            valid_from=row.get("valid_from"),
            valid_to=row.get("valid_to"),
            staleness=row.get("staleness"),
            poisoning_flags=_as_list(row.get("poisoning_flags") or row.get("poisoning_flags_json")),
            evidence=evidence,
        )

    @classmethod
    def from_patch_item(cls, item: Mapping[str, Any]) -> "GraphRelation":
        return cls(
            relation_id=str(item.get("id") or item.get("relation_id") or ""),
            from_entity_id=str(item.get("fromEntity") or item.get("from_entity_id") or ""),
            relation_type=str(item.get("type") or ""),
            to_entity_id=str(item.get("toEntity") or item.get("to_entity_id") or ""),
            properties=_as_dict(item.get("properties")),
            confidence=_as_float(item.get("confidence"), 1.0),
            first_seen_at=str(item.get("first_seen_at") or ""),
            last_seen_at=str(item.get("last_seen_at") or ""),
            artifact_id=item.get("artifact_id"),
            session_id=item.get("session_id"),
            dream_run_id=item.get("dream_run_id"),
            intent=item.get("intent"),
            helpful_score=_as_float(item.get("helpful_score"), None),
            tags=_as_list(item.get("tags")),
            memory_kind=str(item.get("memory_kind") or "graph_fact"),
            source_kind=str(item.get("source_kind") or "graph_structuring"),
            risk_level=str(item.get("risk_level") or "low"),
            sensitivity=str(item.get("sensitivity") or "normal"),
            injection_policy=str(item.get("injection_policy") or "on_demand"),
            valid_from=item.get("valid_from"),
            valid_to=item.get("valid_to"),
            staleness=item.get("staleness"),
            poisoning_flags=_as_list(item.get("poisoning_flags")),
            evidence=[EvidenceLink.from_dict(e) for e in _as_list(item.get("evidence"))],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "from_entity_id": self.from_entity_id,
            "relation_type": self.relation_type,
            "to_entity_id": self.to_entity_id,
            "properties": self.properties,
            "confidence": self.confidence,
            "first_seen_at": self.first_seen_at,
            "last_seen_at": self.last_seen_at,
            "artifact_id": self.artifact_id,
            "session_id": self.session_id,
            "dream_run_id": self.dream_run_id,
            "intent": self.intent,
            "helpful_score": self.helpful_score,
            "tags": self.tags,
            "memory_kind": self.memory_kind,
            "source_kind": self.source_kind,
            "risk_level": self.risk_level,
            "sensitivity": self.sensitivity,
            "injection_policy": self.injection_policy,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "staleness": self.staleness,
            "poisoning_flags": self.poisoning_flags,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class SchemaProposal:
    proposal_id: str
    kind: str
    proposed_name: str
    status: str = "pending"
    canonical_name: str | None = None
    confidence: float | None = None
    reason: str | None = None
    examples: list[Any] = field(default_factory=list)
    evidence: list[Any] = field(default_factory=list)
    review: dict[str, Any] | None = None
    created_at: str | None = None
    updated_at: str | None = None
    decision_reason: str | None = None

    @property
    def is_final(self) -> bool:
        return self.status in SCHEMA_PROPOSAL_FINAL_STATUSES

    @property
    def is_reviewed(self) -> bool:
        return self.status in {"reviewed", "approved", "rejected", "merged", "promoted"}

    @property
    def recommendation(self) -> str | None:
        return (self.review or {}).get("recommendation")

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SchemaProposal":
        row = _as_row_dict(row)
        return cls(
            proposal_id=str(row.get("proposal_id") or ""),
            kind=str(row.get("kind") or ""),
            proposed_name=str(row.get("proposed_name") or row.get("name") or ""),
            status=str(row.get("status") or "pending"),
            canonical_name=row.get("canonical_name"),
            confidence=_as_float(row.get("confidence"), 0.0),
            reason=row.get("reason"),
            examples=_as_list(row.get("examples") or row.get("examples_json")),
            evidence=_as_list(row.get("evidence") or row.get("evidence_json")),
            review=_as_dict(row.get("review") or row.get("review_json")),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            decision_reason=row.get("decision_reason"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "kind": self.kind,
            "proposed_name": self.proposed_name,
            "status": self.status,
            "canonical_name": self.canonical_name,
            "confidence": self.confidence,
            "reason": self.reason,
            "examples": self.examples,
            "evidence": self.evidence,
            "review": self.review,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "decision_reason": self.decision_reason,
        }


def _decode_evidence_link(item: Any, *, owner_type: str, owner_id: str) -> EvidenceLink:
    if isinstance(item, EvidenceLink):
        return item
    if isinstance(item, Mapping):
        data = dict(item)
        if "owner_type" not in data:
            data["owner_type"] = owner_type
        if "owner_id" not in data:
            data["owner_id"] = owner_id
        if "source_type" not in data:
            data["source_type"] = "graph"
        return EvidenceLink.from_dict(data)
    if isinstance(item, str):
        return EvidenceLink(
            owner_type=owner_type,
            owner_id=owner_id,
            source_type="graph",
            quote=item,
        )
    return EvidenceLink(owner_type=owner_type, owner_id=owner_id, source_type="graph")


__all__ = [
    "EvidenceLink",
    "GraphArtifact",
    "GraphCountSummary",
    "GraphCuratedContext",
    "GraphCuratedEntity",
    "GraphCuratedRelation",
    "GraphExpectedPresence",
    "GraphQueryAssessment",
    "GraphQualityEvaluation",
    "GraphQualityOverview",
    "GraphEntity",
    "GraphRelation",
    "GraphResolutionCandidate",
    "SchemaProposal",
    "SCHEMA_PROPOSAL_FINAL_STATUSES",
    "SCHEMA_PROPOSAL_STATUSES",
]
