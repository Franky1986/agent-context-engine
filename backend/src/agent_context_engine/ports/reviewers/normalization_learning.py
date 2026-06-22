from __future__ import annotations

from typing import Protocol

from ...domain.normalization_learning import (
    NormalizationRuleEvaluation,
    NormalizationRuleProposal,
    NormalizationRuleReview,
)


class NormalizationRuleReviewer(Protocol):
    def review(
        self,
        proposal: NormalizationRuleProposal,
        evaluation: NormalizationRuleEvaluation,
    ) -> NormalizationRuleReview:
        """Review an evaluated learned normalization rule proposal."""
