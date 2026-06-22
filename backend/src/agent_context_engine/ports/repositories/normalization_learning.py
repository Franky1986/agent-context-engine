from __future__ import annotations

from typing import Any, Protocol


class NormalizationLearningRepository(Protocol):
    def list_active_rules(self, *, rule_kind: str | None = None, target_type: str | None = None) -> list[dict[str, Any]]:
        """Return currently active learned normalization rules."""

    def semantic_entity_corpus(self, *, target_type: str | None = None) -> list[dict[str, Any]]:
        """Return normalized semantic entities as learning/evaluation corpus rows."""

    def upsert_rule(self, record: dict[str, Any]) -> str:
        """Create or update a learned normalization rule and return its id."""

    def add_rule_version(self, record: dict[str, Any]) -> str:
        """Persist a versioned snapshot of a learned normalization rule."""

    def upsert_rule_proposal(self, record: dict[str, Any]) -> str:
        """Create or update a learned rule proposal and return its id."""

    def replace_rule_examples(self, proposal_id: str, examples: list[dict[str, Any]]) -> None:
        """Replace proposal examples with the provided set."""

    def add_rule_evaluation(self, record: dict[str, Any]) -> str:
        """Persist an evaluation run for a learned rule proposal."""

    def add_rule_review(self, record: dict[str, Any]) -> str:
        """Persist a machine review outcome for a learned rule proposal."""

    def add_rule_rollout(self, record: dict[str, Any]) -> str:
        """Persist a rollout state transition for a learned normalization rule."""
