"""Audit output helpers for Dreaming v2 refactor."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


__all__ = ["write_audit_manifest", "count_decision_actions"]


def _count_decisions(decisions: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in decisions:
        action = str(decision.get("action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts


def count_decision_actions(decisions: list[dict[str, Any]]) -> dict[str, int]:
    """Public (service) facade for decision counting used by legacy callers."""

    return _count_decisions(decisions)


def write_audit_manifest(
    run_dir: Path,
    *,
    session: Any,
    dream_run_id: str,
    event_from: int,
    event_to: int,
    event_count: int,
    semantic_payload: dict[str, Any],
    reconciliation_payload: dict[str, Any],
    operational: dict[str, Any],
    candidates: dict[str, Any],
    persistence: dict[str, Any],
    validation: dict[str, Any],
    dry_run: bool,
    write_text_fn: Callable[[Path, str], Path],
) -> dict[str, Path]:
    audit_dir = run_dir / "audit"
    entities = semantic_payload.get("entities") if isinstance(semantic_payload.get("entities"), list) else []
    relations = semantic_payload.get("relations") if isinstance(semantic_payload.get("relations"), list) else []
    schema_proposals = semantic_payload.get("schema_proposals") if isinstance(semantic_payload.get("schema_proposals"), list) else []
    decisions = reconciliation_payload.get("decisions") if isinstance(reconciliation_payload.get("decisions"), list) else []

    review_items = [
        decision
        for decision in decisions
        if decision.get("review_required") or decision.get("action") in {"defer_for_review", "propose_schema"}
    ]
    decision_counts = _count_decisions(decisions)
    operational_counts = {
        "file_changes": len(operational.get("file_changes") or []),
        "pretool_audit_refs": len(operational.get("pretool_audit_refs") or []),
    }
    candidate_counts = {
        "proposals_seen": len(semantic_payload.get("entities", []) or []) + len(semantic_payload.get("relations", []) or []),
        "candidates_found": sum(len(v) for v in (candidates.get("candidates", {}).values() if isinstance(candidates.get("candidates", {}), dict) else [])),
    }
    summary = "\n".join(
        [
            "# Dream Pipeline 2.0 Audit",
            "",
            f"session_id: {session['session_id']}",
            f"dream_run_id: {dream_run_id}",
            f"event_range: {event_from}-{event_to} ({event_count} events)",
            "",
            "Raw tool inputs and outputs are not included.",
            "",
            "## Event window:",
            f"- start_seq: {event_from}",
            f"- end_seq: {event_to}",
            f"- event_count: {event_count}",
            "",
            "## Semantic proposals:",
            f"semantic_entities: {len(entities)}",
            f"semantic_relations: {len(relations)}",
            f"schema_proposals: {len(schema_proposals)}",
            f"decisions_seen: {len(decisions)}",
            "",
            "## Decision counts:",
            *(f"- {name}: {count}" for name, count in sorted(decision_counts.items())),
            "",
            "## Operational facts:",
            f"- file_changes={operational_counts['file_changes']}",
            f"- pretool_audit_refs={operational_counts['pretool_audit_refs']}",
            "",
            "## Candidate Search",
            f"- proposals_seen={candidate_counts['proposals_seen']}",
            f"- candidate_rows={candidate_counts['candidates_found']}",
            "",
            "## Validation",
            f"- status={validation.get('status')}",
            f"- dry_run={bool(dry_run)}",
            "",
            "# Memory Changes",
            "",
            f"- Semantic entities written: `{persistence.get('semantic_entities_written', 0)}`",
            f"- Semantic relations written: `{persistence.get('semantic_relations_written', 0)}`",
            f"- Decisions seen: `{persistence.get('decisions_seen', len(decisions))}`",
            f"- Dry run: `{bool(dry_run)}`",
            "",
            "# Proposed Entities",
            *(f"- `{entity.get('proposal_id')}` `{entity.get('type')}` {entity.get('name')}" for entity in entities),
            "",
            "# Proposed Relations",
            *(f"- `{relation.get('proposal_id')}` `{relation.get('type')}` {relation.get('source_ref')} -> {relation.get('target_ref')}" for relation in relations),
            "",
            "# Schema Proposals",
            *(f"- `{proposal.get('proposal_id')}` `{proposal.get('kind')}` {proposal.get('proposed_name')} - {proposal.get('reason') or ''}" for proposal in schema_proposals),
            "",
            "# Decisions",
            *(f"- `{decision.get('decision_id')}` `{decision.get('action')}` proposal=`{decision.get('proposal_id')}` review=`{bool(decision.get('review_required'))}` - {decision.get('human_summary') or decision.get('reason') or ''}" for decision in decisions),
        ]
    )

    if review_items:
        review = "\n".join(
            [
                "# Review Needed",
                "",
                *(
                    f"- `{decision.get('decision_id')}` action=`{decision.get('action')}` proposal=`{decision.get('proposal_id')}` reason={decision.get('review_reason') or decision.get('reason') or '-'}"
                    for decision in review_items
                ),
                "",
            ]
        )
    else:
        review = "# Review Needed\n\nNo review-needed items were generated by this run.\n"

    return {
        "summary": write_text_fn(audit_dir / "summary.md", summary + "\n"),
        "memory_changes": write_text_fn(audit_dir / "memory-changes.md", "\n".join([
            "# Memory Changes",
            "",
            "## Proposed Entities",
            *(f"- `{entity.get('proposal_id')}` `{entity.get('type')}` {entity.get('name')}" for entity in entities),
            "",
            "## Proposed Relations",
            *(f"- `{relation.get('proposal_id')}` `{relation.get('type')}` {relation.get('source_ref')} -> {relation.get('target_ref')}" for relation in relations),
            "",
            "## Decisions",
            *(f"- `{decision.get('decision_id')}` `{decision.get('action')}` proposal=`{decision.get('proposal_id')}`" for decision in decisions),
            "",
            f"- entities={len(entities)}",
            f"- relations={len(relations)}",
            f"- schema_proposals={len(schema_proposals)}",
            f"- decisions={len(decisions)}",
            "",
        ]) + "\n"),
        "review_needed": write_text_fn(audit_dir / "review-needed.md", review),
    }
