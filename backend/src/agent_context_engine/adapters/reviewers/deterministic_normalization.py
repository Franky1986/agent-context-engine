from __future__ import annotations

from ...domain.normalization_learning import (
    NormalizationRuleEvaluation,
    NormalizationRuleProposal,
    NormalizationRuleReview,
    deterministic_rule_review,
)


class DeterministicNormalizationRuleReviewer:
    def review(
        self,
        proposal: NormalizationRuleProposal,
        evaluation: NormalizationRuleEvaluation,
    ) -> NormalizationRuleReview:
        return deterministic_rule_review(proposal, evaluation)
