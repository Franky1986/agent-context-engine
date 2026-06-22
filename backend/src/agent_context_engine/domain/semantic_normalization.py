from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .normalization_learning import LearnedNormalizationRule


GERMAN_PREFIXES_BY_TYPE = {
    "task": ("offene aufgabe", "aufgabe", "task", "open task", "todo"),
    "decision": ("entscheidung", "decision"),
    "issue": ("problem", "issue", "bug"),
    "risk": ("risiko", "risk"),
    "concept": ("konzept", "concept"),
    "feature": ("feature", "funktion"),
    "policy": ("richtlinie", "policy"),
}


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


def slugify_normalized(value: str) -> str:
    return _slug(value)


def _is_ascii_phrase(value: str) -> bool:
    if not value:
        return False
    return all(ord(char) < 128 for char in value)


def _detect_language(values: list[str]) -> str:
    combined = " ".join(values).lower()
    if re.search(r"[äöüß]", combined):
        return "de"
    german_hints = {"offen", "aufgabe", "entscheidung", "risiko", "konzept", "funktion", "und", "mit", "für"}
    if german_hints & set(re.findall(r"[a-zA-ZäöüÄÖÜß]+", combined)):
        return "de"
    return "en"


def _strip_type_prefix(entity_type: str, value: str) -> str:
    lowered = value.lower()
    for prefix in GERMAN_PREFIXES_BY_TYPE.get(entity_type, ()):
        if lowered == prefix:
            return value
        if lowered.startswith(prefix + ":"):
            return value[len(prefix) + 1 :].strip()
        if lowered.startswith(prefix + " "):
            return value[len(prefix) + 1 :].strip()
    return value


def _unique_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def lookup_forms(*values: Any) -> tuple[str, ...]:
    forms: list[str] = []
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        forms.append(text)
        forms.append(_ascii_fold(text))
        forms.append(_ascii_fold(text).lower())
        forms.append(_slug(text).replace("-", " "))
    return tuple(_unique_texts(forms))


def _score_canonical_candidate(entity_type: str, source_language: str, value: str) -> tuple[int, int, int, str]:
    cleaned = _clean_text(value)
    ascii_bonus = 1 if _is_ascii_phrase(cleaned) else 0
    language_bonus = 1 if source_language != "en" and ascii_bonus else 0
    stripped_bonus = 1 if _strip_type_prefix(entity_type, cleaned) != cleaned else 0
    return (language_bonus, ascii_bonus, stripped_bonus, cleaned.casefold())


@dataclass(frozen=True)
class NormalizedEntityProposal:
    canonical_name: str
    canonical_key: str
    aliases: tuple[str, ...]
    normalized_name: str
    normalized_english_name: str
    language: str
    source_name: str
    trace: tuple[str, ...]
    applied_rule_ids: tuple[str, ...]
    identity_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "canonical_key": self.canonical_key,
            "aliases": list(self.aliases),
            "normalized_name": self.normalized_name,
            "normalized_english_name": self.normalized_english_name,
            "language": self.language,
            "source_name": self.source_name,
            "trace": list(self.trace),
            "applied_rule_ids": list(self.applied_rule_ids),
            "identity_confidence": self.identity_confidence,
        }


@dataclass(frozen=True)
class NormalizedRelationProposal:
    canonical_summary: str
    canonical_relation_key: str
    normalized_relation_type: str
    language: str
    trace: tuple[str, ...]
    applied_rule_ids: tuple[str, ...]
    identity_confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_summary": self.canonical_summary,
            "canonical_relation_key": self.canonical_relation_key,
            "normalized_relation_type": self.normalized_relation_type,
            "language": self.language,
            "trace": list(self.trace),
            "applied_rule_ids": list(self.applied_rule_ids),
            "identity_confidence": self.identity_confidence,
        }


def normalize_entity_proposal(
    entity_type: str,
    name: Any,
    aliases: list[str] | tuple[str, ...] | None = None,
    *,
    learned_rules: list["LearnedNormalizationRule"] | tuple["LearnedNormalizationRule", ...] | None = None,
) -> NormalizedEntityProposal:
    source_name = _clean_text(name)
    alias_values = _unique_texts([source_name, *(aliases or [])]) or [source_name or entity_type]
    applied_rules = [
        rule
        for rule in (learned_rules or [])
        if rule.rule_kind in {"alias_family", "title_family"} and rule.matches(entity_type, alias_values)
    ]
    if applied_rules:
        enriched_alias_values: list[str] = list(alias_values)
        for rule in applied_rules:
            enriched_alias_values.extend([rule.canonical_value, *rule.aliases])
        alias_values = _unique_texts(enriched_alias_values)
    language = _detect_language(alias_values)
    preferred_canonical = None
    if applied_rules:
        preferred_canonical = max(
            applied_rules,
            key=lambda rule: (rule.confidence, len(rule.aliases), len(rule.canonical_value)),
        ).canonical_value
    ascii_aliases = [value for value in alias_values if _is_ascii_phrase(value) and value.casefold() != source_name.casefold()]
    if preferred_canonical:
        canonical_candidate = preferred_canonical
    elif language != "en" and ascii_aliases:
        canonical_candidate = max(ascii_aliases, key=lambda value: (len(value.split()), len(value), value.casefold()))
    else:
        canonical_candidate = max(alias_values, key=lambda value: _score_canonical_candidate(entity_type, language, value))
    stripped = _clean_text(_strip_type_prefix(entity_type, canonical_candidate))
    canonical_name = stripped or source_name
    normalized_name = _ascii_fold(canonical_name).lower()
    normalized_english_name = _ascii_fold(canonical_name).lower()
    merged_aliases = _unique_texts(
        [
            source_name,
            canonical_name,
            *alias_values,
            _ascii_fold(source_name),
            _ascii_fold(canonical_name),
        ]
    )
    trace: list[str] = []
    if canonical_name != source_name:
        trace.append("canonical_name_changed")
    if any(alias != _ascii_fold(alias) for alias in alias_values):
        trace.append("ascii_fold_alias_added")
    if canonical_name != canonical_candidate:
        trace.append("type_prefix_stripped")
    if applied_rules:
        trace.append("learned_rule_applied")
    identity_confidence = min(
        1.0,
        0.55
        + (0.12 if canonical_name != source_name else 0.0)
        + (0.08 if ascii_aliases else 0.0)
        + sum(min(0.1, max(0.0, rule.confidence)) for rule in applied_rules),
    )
    return NormalizedEntityProposal(
        canonical_name=canonical_name,
        canonical_key=f"{entity_type}-{_slug(normalized_english_name)}",
        aliases=tuple(merged_aliases),
        normalized_name=normalized_name,
        normalized_english_name=normalized_english_name,
        language=language,
        source_name=source_name,
        trace=tuple(_unique_texts(trace)),
        applied_rule_ids=tuple(rule.rule_id for rule in applied_rules),
        identity_confidence=identity_confidence,
    )


def normalize_relation_proposal(
    relation_type: str,
    summary: Any,
    *,
    source_key: str,
    target_key: str,
) -> NormalizedRelationProposal:
    source_summary = _clean_text(summary) or relation_type
    language = _detect_language([source_summary])
    canonical_summary = source_summary[0].upper() + source_summary[1:] if source_summary else relation_type
    canonical_relation_key = f"{_slug(relation_type)}-{_slug(source_key)}--{_slug(target_key)}"
    trace: list[str] = []
    if canonical_summary != source_summary:
        trace.append("summary_cased")
    return NormalizedRelationProposal(
        canonical_summary=canonical_summary,
        canonical_relation_key=canonical_relation_key,
        normalized_relation_type=relation_type.lower().strip(),
        language=language,
        trace=tuple(trace),
        applied_rule_ids=(),
        identity_confidence=0.6,
    )
