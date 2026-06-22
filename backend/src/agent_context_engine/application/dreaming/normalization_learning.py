from __future__ import annotations

from typing import Any

from ...adapters.reviewers.deterministic_normalization import DeterministicNormalizationRuleReviewer
from ...adapters.sqlite.normalization_learning import SQLiteNormalizationLearningRepository
from ...domain.normalization_learning import (
    NormalizationObservation,
    evaluate_alias_family_rule,
    evaluate_title_family_rule,
    propose_alias_family_rules,
    propose_title_family_rules,
    rule_from_record,
)
from ...infrastructure.config import safe_slug, utc_now
from ...ports.reviewers.normalization_learning import NormalizationRuleReviewer


def active_normalization_rules(conn: Any) -> list[Any]:
    repository = SQLiteNormalizationLearningRepository(conn)
    return [rule_from_record(record) for record in repository.list_active_rules(target_type=None)]


def _observations_from_payload(payload: dict[str, Any], *, session_id: str | None, dream_run_id: str | None) -> list[NormalizationObservation]:
    observations: list[NormalizationObservation] = []
    for entity in payload.get("entities", []):
        if not isinstance(entity, dict):
            continue
        properties = entity.get("properties") if isinstance(entity.get("properties"), dict) else {}
        normalization = properties.get("normalization") if isinstance(properties.get("normalization"), dict) else {}
        canonical_name = str(normalization.get("canonical_name") or entity.get("name") or "").strip()
        aliases = tuple(str(item) for item in (entity.get("aliases") or []) if str(item).strip())
        if not canonical_name:
            continue
        observations.append(
            NormalizationObservation(
                entity_type=str(entity.get("type") or ""),
                source_name=str(normalization.get("source_name") or entity.get("name") or canonical_name),
                canonical_name=canonical_name,
                aliases=aliases,
                language=str(normalization.get("language") or entity.get("language") or ""),
                source_session_id=session_id,
                source_dream_run_id=dream_run_id,
                trace=tuple(str(item) for item in (normalization.get("trace") or []) if str(item).strip()),
            )
        )
    return observations


def run_normalization_learning(
    conn: Any,
    *,
    dream_run_id: str,
    session_id: str,
    normalized_payload: dict[str, Any],
    reviewer: NormalizationRuleReviewer | None = None,
) -> dict[str, Any]:
    repository = SQLiteNormalizationLearningRepository(conn)
    reviewer = reviewer or DeterministicNormalizationRuleReviewer()
    observed = _observations_from_payload(
        normalized_payload,
        session_id=session_id,
        dream_run_id=dream_run_id,
    )
    if not observed:
        return {"proposals_created": 0, "rules_activated": 0, "shadow_rules": 0, "rejected_rules": 0}

    corpus = observed + [
        NormalizationObservation(
            entity_type=str(item.get("entity_type") or ""),
            source_name=str(item.get("source_name") or item.get("canonical_name") or ""),
            canonical_name=str(item.get("canonical_name") or ""),
            aliases=tuple(str(alias) for alias in (item.get("aliases") or []) if str(alias).strip()),
            language=str(item.get("language") or ""),
            source_session_id=item.get("source_session_id"),
            source_dream_run_id=item.get("source_dream_run_id"),
            trace=tuple(str(value) for value in (item.get("trace") or []) if str(value).strip()),
        )
        for item in repository.semantic_entity_corpus()
    ]
    proposals = [
        *propose_alias_family_rules(observed),
        *propose_title_family_rules(observed),
    ]
    summary = {"proposals_created": 0, "rules_activated": 0, "shadow_rules": 0, "rejected_rules": 0}
    now = utc_now()
    for proposal in proposals:
        proposal_aliases = list(dict.fromkeys([*proposal.aliases, proposal.canonical_value]))
        proposal_id = repository.upsert_rule_proposal(
            {
                "proposal_id": f"norm_prop_{safe_slug(proposal.rule_kind)}_{safe_slug(proposal.target_type)}_{safe_slug(proposal.canonical_value)}",
                "dream_run_id": dream_run_id,
                "session_id": session_id,
                "rule_kind": proposal.rule_kind,
                "target_kind": proposal.target_kind,
                "target_type": proposal.target_type,
                "canonical_value": proposal.canonical_value,
                "aliases": proposal_aliases,
                "rationale": proposal.rationale,
                "evidence": list(proposal.evidence),
                "status": "proposed",
                "created_at": now,
            }
        )
        repository.replace_rule_examples(proposal_id, list(proposal.positive_examples))
        if proposal.rule_kind == "title_family":
            evaluation = evaluate_title_family_rule(proposal, corpus)
        else:
            evaluation = evaluate_alias_family_rule(proposal, corpus)
        evaluation_id = repository.add_rule_evaluation(
            {
                "evaluation_id": f"norm_eval_{safe_slug(proposal_id)}_{safe_slug(evaluation.recommended_state)}",
                "proposal_id": proposal_id,
                "evaluator": "deterministic-corpus",
                "corpus_size": evaluation.corpus_size,
                "metrics": evaluation.to_metrics(),
                "status": "evaluated",
                "created_at": now,
            }
        )
        review = reviewer.review(proposal, evaluation)
        review_id = repository.add_rule_review(
            {
                "review_id": f"norm_review_{safe_slug(proposal_id)}_{safe_slug(review.decision)}",
                "proposal_id": proposal_id,
                "evaluation_id": evaluation_id,
                "reviewer": "deterministic-review",
                "decision": review.decision,
                "rationale": review.rationale,
                "details": evaluation.to_metrics(),
                "created_at": now,
            }
        )
        if review.rollout_state != "rolled_back":
            rule_id = repository.upsert_rule(
                {
                    "rule_id": f"norm_rule_{safe_slug(proposal.rule_kind)}_{safe_slug(proposal.target_type)}_{safe_slug(proposal.canonical_value)}",
                    "rule_kind": proposal.rule_kind,
                    "target_kind": proposal.target_kind,
                    "target_type": proposal.target_type,
                    "canonical_value": proposal.canonical_value,
                    "aliases": proposal_aliases,
                    "pattern": proposal.pattern,
                    "confidence": evaluation.consistency_ratio,
                    "status": review.rollout_state,
                    "current_rollout_state": review.rollout_state,
                    "source_proposal_id": proposal_id,
                    "created_at": now,
                }
            )
            repository.add_rule_version(
                {
                    "version_id": f"norm_rule_ver_{safe_slug(rule_id)}_{safe_slug(proposal_id)}",
                    "rule_id": rule_id,
                    "source_proposal_id": proposal_id,
                    "rollout_state": review.rollout_state,
                    "version_number": 1,
                    "definition": {
                        "rule_kind": proposal.rule_kind,
                        "target_kind": proposal.target_kind,
                        "target_type": proposal.target_type,
                        "canonical_value": proposal.canonical_value,
                        "aliases": proposal_aliases,
                        "pattern": proposal.pattern,
                        "review": review.decision,
                        "metrics": evaluation.to_metrics(),
                    },
                    "created_at": now,
                }
            )
            repository.add_rule_rollout(
                {
                    "rollout_id": f"norm_rollout_{safe_slug(rule_id)}_{safe_slug(review.rollout_state)}",
                    "rule_id": rule_id,
                    "proposal_id": proposal_id,
                    "review_id": review_id,
                    "state": review.rollout_state,
                    "reason": review.rationale,
                    "created_at": now,
                }
            )
        else:
            rule_id = repository.upsert_rule(
                {
                    "rule_id": f"norm_rule_{safe_slug(proposal.rule_kind)}_{safe_slug(proposal.target_type)}_{safe_slug(proposal.canonical_value)}",
                    "rule_kind": proposal.rule_kind,
                    "target_kind": proposal.target_kind,
                    "target_type": proposal.target_type,
                    "canonical_value": proposal.canonical_value,
                    "aliases": proposal_aliases,
                    "pattern": proposal.pattern,
                    "confidence": evaluation.consistency_ratio,
                    "status": "rejected",
                    "current_rollout_state": "rolled_back",
                    "source_proposal_id": proposal_id,
                    "created_at": now,
                }
            )
            repository.add_rule_rollout(
                {
                    "rollout_id": f"norm_rollout_{safe_slug(rule_id)}_rolled_back",
                    "rule_id": rule_id,
                    "proposal_id": proposal_id,
                    "review_id": review_id,
                    "state": "rolled_back",
                    "reason": review.rationale,
                    "created_at": now,
                }
            )
        summary["proposals_created"] += 1
        if review.rollout_state == "active":
            summary["rules_activated"] += 1
        elif review.rollout_state == "shadow":
            summary["shadow_rules"] += 1
        else:
            summary["rejected_rules"] += 1
    return summary
