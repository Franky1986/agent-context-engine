from __future__ import annotations

import json
import sqlite3
from typing import Any

from ...infrastructure.config import json_dumps, safe_slug, utc_now


def _safe_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


class SQLiteNormalizationLearningRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_active_rules(self, *, rule_kind: str | None = None, target_type: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = ["active"]
        where = ["coalesce(current_rollout_state, status) = ?"]
        if rule_kind:
            where.append("rule_kind = ?")
            params.append(rule_kind)
        if target_type:
            where.append("target_type = ?")
            params.append(target_type)
        rows = self._conn.execute(
            f"""
            select *
            from normalization_rules
            where {' and '.join(where)}
            order by updated_at desc, confidence desc
            """,
            params,
        ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    def semantic_entity_corpus(self, *, target_type: str | None = None) -> list[dict[str, Any]]:
        params: list[Any] = []
        where = ["status = 'active'"]
        if target_type:
            where.append("entity_type = ?")
            params.append(target_type)
        rows = self._conn.execute(
            f"""
            select semantic_entity_id, entity_key, entity_type, name, aliases_json,
                   properties_json, source_session_id, source_dream_run_id, confidence
            from semantic_entities
            where {' and '.join(where)}
            order by updated_at desc, created_at desc
            """,
            params,
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            properties = _safe_json(row["properties_json"], {})
            normalization = properties.get("normalization") if isinstance(properties, dict) and isinstance(properties.get("normalization"), dict) else {}
            aliases = _safe_json(row["aliases_json"], [])
            result.append(
                {
                    "semantic_entity_id": row["semantic_entity_id"],
                    "entity_key": row["entity_key"],
                    "entity_type": row["entity_type"],
                    "canonical_name": row["name"],
                    "aliases": aliases,
                    "normalized_name": normalization.get("normalized_name"),
                    "normalized_english_name": normalization.get("normalized_english_name"),
                    "language": normalization.get("language") or properties.get("language"),
                    "source_name": normalization.get("source_name") or properties.get("source_name") or row["name"],
                    "trace": normalization.get("trace") or [],
                    "source_session_id": row["source_session_id"],
                    "source_dream_run_id": row["source_dream_run_id"],
                    "confidence": row["confidence"],
                }
            )
        return result

    def upsert_rule(self, record: dict[str, Any]) -> str:
        rule_id = str(record.get("rule_id") or f"norm_rule_{safe_slug(record.get('rule_kind') or 'rule')}_{safe_slug(record.get('target_type') or 'generic')}_{safe_slug(record.get('canonical_value') or 'canonical')}")
        now = utc_now()
        self._conn.execute(
            """
            insert into normalization_rules (
              rule_id, rule_kind, target_kind, target_type, canonical_value,
              aliases_json, pattern_json, confidence, status, current_rollout_state,
              source_proposal_id, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(rule_id) do update set
              canonical_value=excluded.canonical_value,
              aliases_json=excluded.aliases_json,
              pattern_json=excluded.pattern_json,
              confidence=excluded.confidence,
              status=excluded.status,
              current_rollout_state=excluded.current_rollout_state,
              source_proposal_id=excluded.source_proposal_id,
              updated_at=excluded.updated_at
            """,
            (
                rule_id,
                record.get("rule_kind"),
                record.get("target_kind") or "entity",
                record.get("target_type"),
                record.get("canonical_value"),
                json_dumps(record.get("aliases") or []),
                json_dumps(record.get("pattern") or {}),
                record.get("confidence"),
                record.get("status") or "candidate",
                record.get("current_rollout_state") or record.get("status") or "candidate",
                record.get("source_proposal_id"),
                record.get("created_at") or now,
                now,
            ),
        )
        return rule_id

    def add_rule_version(self, record: dict[str, Any]) -> str:
        version_id = str(record.get("version_id") or f"norm_rule_ver_{safe_slug(record.get('rule_id') or 'rule')}_{safe_slug(record.get('source_proposal_id') or utc_now())}")
        self._conn.execute(
            """
            insert or replace into normalization_rule_versions (
              version_id, rule_id, source_proposal_id, rollout_state,
              version_number, definition_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                version_id,
                record.get("rule_id"),
                record.get("source_proposal_id"),
                record.get("rollout_state"),
                record.get("version_number") or 1,
                json_dumps(record.get("definition") or {}),
                record.get("created_at") or utc_now(),
            ),
        )
        return version_id

    def upsert_rule_proposal(self, record: dict[str, Any]) -> str:
        proposal_id = str(record.get("proposal_id") or f"norm_prop_{safe_slug(record.get('rule_kind') or 'rule')}_{safe_slug(record.get('target_type') or 'generic')}_{safe_slug(record.get('canonical_value') or 'canonical')}")
        now = utc_now()
        self._conn.execute(
            """
            insert into normalization_rule_proposals (
              proposal_id, dream_run_id, session_id, rule_kind, target_kind,
              target_type, canonical_value, aliases_json, rationale,
              evidence_json, status, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(proposal_id) do update set
              rationale=excluded.rationale,
              evidence_json=excluded.evidence_json,
              aliases_json=excluded.aliases_json,
              status=excluded.status,
              updated_at=excluded.updated_at
            """,
            (
                proposal_id,
                record.get("dream_run_id"),
                record.get("session_id"),
                record.get("rule_kind"),
                record.get("target_kind") or "entity",
                record.get("target_type"),
                record.get("canonical_value"),
                json_dumps(record.get("aliases") or []),
                record.get("rationale"),
                json_dumps(record.get("evidence") or []),
                record.get("status") or "proposed",
                record.get("created_at") or now,
                now,
            ),
        )
        return proposal_id

    def replace_rule_examples(self, proposal_id: str, examples: list[dict[str, Any]]) -> None:
        self._conn.execute("delete from normalization_rule_examples where proposal_id = ?", (proposal_id,))
        now = utc_now()
        for index, example in enumerate(examples, start=1):
            example_id = str(example.get("example_id") or f"norm_ex_{safe_slug(proposal_id)}_{index}")
            self._conn.execute(
                """
                insert into normalization_rule_examples (
                  example_id, proposal_id, example_kind, source_name, aliases_json,
                  canonical_value, source_session_id, source_dream_run_id,
                  metadata_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    example_id,
                    proposal_id,
                    example.get("example_kind") or "positive",
                    example.get("source_name"),
                    json_dumps(example.get("aliases") or []),
                    example.get("canonical_value"),
                    example.get("source_session_id"),
                    example.get("source_dream_run_id"),
                    json_dumps(example.get("metadata") or {}),
                    example.get("created_at") or now,
                ),
            )

    def add_rule_evaluation(self, record: dict[str, Any]) -> str:
        evaluation_id = str(record.get("evaluation_id") or f"norm_eval_{safe_slug(record.get('proposal_id') or 'proposal')}_{safe_slug(record.get('status') or 'status')}")
        self._conn.execute(
            """
            insert or replace into normalization_rule_evaluations (
              evaluation_id, proposal_id, evaluator, corpus_size,
              metrics_json, status, created_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluation_id,
                record.get("proposal_id"),
                record.get("evaluator") or "deterministic",
                record.get("corpus_size") or 0,
                json_dumps(record.get("metrics") or {}),
                record.get("status") or "evaluated",
                record.get("created_at") or utc_now(),
            ),
        )
        return evaluation_id

    def add_rule_review(self, record: dict[str, Any]) -> str:
        review_id = str(record.get("review_id") or f"norm_review_{safe_slug(record.get('proposal_id') or 'proposal')}_{safe_slug(record.get('decision') or 'decision')}")
        self._conn.execute(
            """
            insert or replace into normalization_rule_reviews (
              review_id, proposal_id, evaluation_id, reviewer,
              decision, rationale, details_json, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                record.get("proposal_id"),
                record.get("evaluation_id"),
                record.get("reviewer") or "deterministic-review",
                record.get("decision"),
                record.get("rationale"),
                json_dumps(record.get("details") or {}),
                record.get("created_at") or utc_now(),
            ),
        )
        return review_id

    def add_rule_rollout(self, record: dict[str, Any]) -> str:
        rollout_id = str(record.get("rollout_id") or f"norm_rollout_{safe_slug(record.get('rule_id') or 'rule')}_{safe_slug(record.get('state') or 'state')}")
        self._conn.execute(
            """
            insert or replace into normalization_rule_rollouts (
              rollout_id, rule_id, proposal_id, review_id,
              state, reason, created_at
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rollout_id,
                record.get("rule_id"),
                record.get("proposal_id"),
                record.get("review_id"),
                record.get("state"),
                record.get("reason"),
                record.get("created_at") or utc_now(),
            ),
        )
        return rollout_id

    def _row_to_rule(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "rule_id": row["rule_id"],
            "rule_kind": row["rule_kind"],
            "target_kind": row["target_kind"],
            "target_type": row["target_type"],
            "canonical_value": row["canonical_value"],
            "aliases": _safe_json(row["aliases_json"], []),
            "pattern": _safe_json(row["pattern_json"], {}),
            "confidence": row["confidence"],
            "status": row["status"],
            "current_rollout_state": row["current_rollout_state"],
            "source_proposal_id": row["source_proposal_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
