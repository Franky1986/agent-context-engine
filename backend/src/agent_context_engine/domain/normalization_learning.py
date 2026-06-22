from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any

TITLE_FAMILY_ENTITY_TYPES = {"task", "decision", "issue", "risk", "feature", "policy"}


def _clean_text(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return text.strip(" -:\t\r\n")


def _ascii_fold(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    return "".join(char for char in folded if not unicodedata.combining(char))


def _slug(value: str) -> str:
    text = _ascii_fold(value).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "unknown"


def _lookup_forms(*values: Any) -> tuple[str, ...]:
    forms: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        candidates = (text, _ascii_fold(text), _ascii_fold(text).lower(), _slug(text).replace("-", " "))
        for candidate in candidates:
            key = candidate.casefold()
            if candidate and key not in seen:
                seen.add(key)
                forms.append(candidate)
    return tuple(forms)


@dataclass(frozen=True)
class LearnedNormalizationRule:
    rule_id: str
    rule_kind: str
    target_kind: str
    target_type: str
    canonical_value: str
    aliases: tuple[str, ...]
    confidence: float
    rollout_state: str

    def matches(self, target_type: str, values: list[str]) -> bool:
        if self.target_kind != "entity" or self.target_type != target_type:
            return False
        rule_forms = {
            form.casefold()
            for form in _lookup_forms(self.canonical_value, *self.aliases)
            if str(form).strip()
        }
        value_forms = {
            form.casefold()
            for form in _lookup_forms(*values)
            if str(form).strip()
        }
        return bool(rule_forms & value_forms)


@dataclass(frozen=True)
class NormalizationObservation:
    entity_type: str
    source_name: str
    canonical_name: str
    aliases: tuple[str, ...]
    language: str
    source_session_id: str | None
    source_dream_run_id: str | None
    trace: tuple[str, ...]


@dataclass(frozen=True)
class NormalizationRuleProposal:
    rule_kind: str
    target_kind: str
    target_type: str
    canonical_value: str
    aliases: tuple[str, ...]
    rationale: str
    evidence: tuple[dict[str, Any], ...]
    positive_examples: tuple[dict[str, Any], ...]
    pattern: dict[str, Any]


@dataclass(frozen=True)
class NormalizationRuleEvaluation:
    corpus_size: int
    support_count: int
    conflict_count: int
    consistency_ratio: float
    cross_language_support: int
    estimated_duplicate_reduction: float
    recommended_state: str

    def to_metrics(self) -> dict[str, Any]:
        return {
            "corpus_size": self.corpus_size,
            "support_count": self.support_count,
            "conflict_count": self.conflict_count,
            "consistency_ratio": self.consistency_ratio,
            "cross_language_support": self.cross_language_support,
            "estimated_duplicate_reduction": self.estimated_duplicate_reduction,
            "recommended_state": self.recommended_state,
        }


@dataclass(frozen=True)
class NormalizationRuleReview:
    decision: str
    rationale: str
    rollout_state: str


def rule_from_record(record: dict[str, Any]) -> LearnedNormalizationRule:
    return LearnedNormalizationRule(
        rule_id=str(record.get("rule_id") or ""),
        rule_kind=str(record.get("rule_kind") or ""),
        target_kind=str(record.get("target_kind") or "entity"),
        target_type=str(record.get("target_type") or ""),
        canonical_value=str(record.get("canonical_value") or ""),
        aliases=tuple(str(item) for item in (record.get("aliases") or []) if str(item).strip()),
        confidence=float(record.get("confidence") or 0.0),
        rollout_state=str(record.get("current_rollout_state") or record.get("status") or ""),
    )


def propose_alias_family_rules(observations: list[NormalizationObservation]) -> list[NormalizationRuleProposal]:
    grouped: dict[tuple[str, str, tuple[str, ...]], dict[str, Any]] = {}
    for observation in observations:
        aliases = tuple(
            alias
            for alias in observation.aliases
            if alias and alias.casefold() != observation.canonical_name.casefold()
        )
        if not aliases:
            continue
        if len(aliases) == 1 and aliases[0].casefold() == observation.source_name.casefold():
            continue
        key = (
            observation.entity_type,
            observation.canonical_name.casefold(),
            tuple(sorted(form.casefold() for form in _lookup_forms(*aliases))),
        )
        entry = grouped.setdefault(
            key,
            {
                "aliases": [],
                "evidence": [],
                "examples": [],
                "canonical_value": observation.canonical_name,
                "entity_type": observation.entity_type,
            },
        )
        for alias in aliases:
            if alias not in entry["aliases"]:
                entry["aliases"].append(alias)
        entry["evidence"].append(
            {
                "source_name": observation.source_name,
                "language": observation.language,
                "trace": list(observation.trace),
                "source_session_id": observation.source_session_id,
                "source_dream_run_id": observation.source_dream_run_id,
            }
        )
        entry["examples"].append(
            {
                "source_name": observation.source_name,
                "aliases": list(observation.aliases),
                "canonical_value": observation.canonical_name,
                "source_session_id": observation.source_session_id,
                "source_dream_run_id": observation.source_dream_run_id,
                "metadata": {"language": observation.language, "trace": list(observation.trace)},
            }
        )
    proposals: list[NormalizationRuleProposal] = []
    for _, entry in grouped.items():
        rationale = (
            f"Observed reusable alias family for {entry['entity_type']} "
            f"canonicalized as {entry['canonical_value']!r}."
        )
        proposals.append(
            NormalizationRuleProposal(
                rule_kind="alias_family",
                target_kind="entity",
                target_type=entry["entity_type"],
                canonical_value=entry["canonical_value"],
                aliases=tuple(entry["aliases"]),
                rationale=rationale,
                evidence=tuple(entry["evidence"]),
                positive_examples=tuple(entry["examples"]),
                pattern={"match_aliases": list(entry["aliases"]), "canonical_value": entry["canonical_value"]},
            )
        )
    return proposals


def propose_title_family_rules(observations: list[NormalizationObservation]) -> list[NormalizationRuleProposal]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for observation in observations:
        if observation.entity_type not in TITLE_FAMILY_ENTITY_TYPES:
            continue
        if observation.source_name.casefold() == observation.canonical_name.casefold():
            continue
        if "type_prefix_stripped" not in observation.trace and "canonical_name_changed" not in observation.trace:
            continue
        key = (observation.entity_type, observation.canonical_name.casefold())
        entry = grouped.setdefault(
            key,
            {
                "source_titles": [],
                "evidence": [],
                "examples": [],
                "canonical_value": observation.canonical_name,
                "entity_type": observation.entity_type,
            },
        )
        if observation.source_name not in entry["source_titles"]:
            entry["source_titles"].append(observation.source_name)
        entry["evidence"].append(
            {
                "source_name": observation.source_name,
                "canonical_name": observation.canonical_name,
                "language": observation.language,
                "trace": list(observation.trace),
                "source_session_id": observation.source_session_id,
                "source_dream_run_id": observation.source_dream_run_id,
            }
        )
        entry["examples"].append(
            {
                "source_name": observation.source_name,
                "aliases": [observation.source_name],
                "canonical_value": observation.canonical_name,
                "source_session_id": observation.source_session_id,
                "source_dream_run_id": observation.source_dream_run_id,
                "metadata": {"language": observation.language, "trace": list(observation.trace)},
            }
        )
    proposals: list[NormalizationRuleProposal] = []
    for _, entry in grouped.items():
        if not entry["source_titles"]:
            continue
        rationale = (
            f"Observed reusable title-family normalization for {entry['entity_type']} "
            f"canonicalized as {entry['canonical_value']!r}."
        )
        proposals.append(
            NormalizationRuleProposal(
                rule_kind="title_family",
                target_kind="entity",
                target_type=entry["entity_type"],
                canonical_value=entry["canonical_value"],
                aliases=tuple(entry["source_titles"]),
                rationale=rationale,
                evidence=tuple(entry["evidence"]),
                positive_examples=tuple(entry["examples"]),
                pattern={"match_titles": list(entry["source_titles"]), "canonical_value": entry["canonical_value"]},
            )
        )
    return proposals


def evaluate_alias_family_rule(
    proposal: NormalizationRuleProposal,
    corpus: list[NormalizationObservation],
) -> NormalizationRuleEvaluation:
    support_count = 0
    conflict_count = 0
    cross_language_support = 0
    matched_languages: set[str] = set()
    rule_forms = {
        form.casefold()
        for form in _lookup_forms(proposal.canonical_value, *proposal.aliases)
        if str(form).strip()
    }
    for observation in corpus:
        if observation.entity_type != proposal.target_type:
            continue
        observation_forms = {
            form.casefold()
            for form in _lookup_forms(observation.source_name, observation.canonical_name, *observation.aliases)
            if str(form).strip()
        }
        if not (rule_forms & observation_forms):
            continue
        support_count += 1
        matched_languages.add(observation.language or "unknown")
        if observation.canonical_name.casefold() != proposal.canonical_value.casefold():
            conflict_count += 1
        if observation.language:
            cross_language_support = max(cross_language_support, len(matched_languages))
    consistency_ratio = 1.0 if support_count == 0 else max(0.0, (support_count - conflict_count) / support_count)
    estimated_duplicate_reduction = max(0.0, float(support_count - 1 - conflict_count))
    if support_count >= 2 and conflict_count == 0 and consistency_ratio >= 0.95:
        recommended_state = "active"
    elif support_count >= 1 and conflict_count == 0 and consistency_ratio >= 0.75:
        recommended_state = "shadow"
    else:
        recommended_state = "rejected"
    return NormalizationRuleEvaluation(
        corpus_size=len(corpus),
        support_count=support_count,
        conflict_count=conflict_count,
        consistency_ratio=consistency_ratio,
        cross_language_support=cross_language_support,
        estimated_duplicate_reduction=estimated_duplicate_reduction,
        recommended_state=recommended_state,
    )


def evaluate_title_family_rule(
    proposal: NormalizationRuleProposal,
    corpus: list[NormalizationObservation],
) -> NormalizationRuleEvaluation:
    support_count = 0
    conflict_count = 0
    matched_languages: set[str] = set()
    rule_forms = {form.casefold() for form in _lookup_forms(*proposal.aliases) if str(form).strip()}
    for observation in corpus:
        if observation.entity_type != proposal.target_type:
            continue
        source_forms = {form.casefold() for form in _lookup_forms(observation.source_name) if str(form).strip()}
        if not (rule_forms & source_forms):
            continue
        support_count += 1
        matched_languages.add(observation.language or "unknown")
        if observation.canonical_name.casefold() != proposal.canonical_value.casefold():
            conflict_count += 1
    consistency_ratio = 1.0 if support_count == 0 else max(0.0, (support_count - conflict_count) / support_count)
    estimated_duplicate_reduction = max(0.0, float(support_count - 1 - conflict_count))
    if support_count >= 2 and conflict_count == 0 and consistency_ratio >= 0.95:
        recommended_state = "active"
    elif support_count >= 1 and conflict_count == 0 and consistency_ratio >= 0.75:
        recommended_state = "shadow"
    else:
        recommended_state = "rejected"
    return NormalizationRuleEvaluation(
        corpus_size=len(corpus),
        support_count=support_count,
        conflict_count=conflict_count,
        consistency_ratio=consistency_ratio,
        cross_language_support=len(matched_languages),
        estimated_duplicate_reduction=estimated_duplicate_reduction,
        recommended_state=recommended_state,
    )


def deterministic_rule_review(proposal: NormalizationRuleProposal, evaluation: NormalizationRuleEvaluation) -> NormalizationRuleReview:
    if evaluation.recommended_state == "active":
        return NormalizationRuleReview(
            decision="approve",
            rationale=(
                f"Consistent alias-family evidence with support={evaluation.support_count} "
                f"and no conflicts."
            ),
            rollout_state="active",
        )
    if evaluation.recommended_state == "shadow":
        return NormalizationRuleReview(
            decision="shadow_only",
            rationale=(
                f"Useful signal exists, but support={evaluation.support_count} is still "
                f"too weak for global activation."
            ),
            rollout_state="shadow",
        )
    return NormalizationRuleReview(
        decision="reject",
        rationale=(
            f"Conflicting or weak alias-family evidence: support={evaluation.support_count}, "
            f"conflicts={evaluation.conflict_count}."
        ),
        rollout_state="rolled_back",
    )
