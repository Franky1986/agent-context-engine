"""Candidate search service extracted from `v2.py`.

This keeps query and scoring behavior while isolating it from orchestration.
"""

from __future__ import annotations

import json
from typing import Any

from agent_context_engine.domain.semantic_normalization import lookup_forms, slugify_normalized
from agent_context_engine.application.graph import neo4j_query_candidate_rows


def _decode_json(value: Any, default: Any = None) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _candidate_score(entity: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, str]:
    entity_properties = entity.get("properties") if isinstance(entity.get("properties"), dict) else {}
    entity_norm = entity_properties.get("normalization") if isinstance(entity_properties.get("normalization"), dict) else {}
    entity_canonical_key = str(entity.get("canonical_key_candidate") or entity_norm.get("canonical_key") or "")
    entity_aliases = entity.get("aliases") if isinstance(entity.get("aliases"), list) else []
    entity_forms = {value.casefold() for value in lookup_forms(entity.get("name"), *entity_aliases, entity_canonical_key, entity_norm.get("normalized_name"), entity_norm.get("normalized_english_name"))}

    candidate_properties = _decode_json(candidate.get("properties_json"), {}) if isinstance(candidate.get("properties_json"), str) else (candidate.get("properties") if isinstance(candidate.get("properties"), dict) else {})
    candidate_norm = candidate_properties.get("normalization") if isinstance(candidate_properties.get("normalization"), dict) else {}
    candidate_aliases = _decode_json(candidate.get("aliases_json"), []) if isinstance(candidate.get("aliases_json"), str) else (candidate.get("aliases") if isinstance(candidate.get("aliases"), list) else [])
    candidate_forms = {value.casefold() for value in lookup_forms(candidate.get("name"), *candidate_aliases, candidate.get("entity_key") or candidate.get("key"), candidate_norm.get("normalized_name"), candidate_norm.get("normalized_english_name"), candidate_norm.get("canonical_key"))}

    if entity_canonical_key and entity_canonical_key == str(candidate.get("entity_key") or ""):
        return 1.0, "canonical key match"
    if entity_forms & candidate_forms:
        overlap = entity_forms & candidate_forms
        if str(entity.get("name") or "").casefold() == str(candidate.get("name") or "").casefold():
            return 0.95, "exact canonical name match"
        if any(" " in form for form in overlap):
            return 0.88, "normalized alias overlap"
        return 0.8, "normalized form overlap"
    entity_slug = slugify_normalized(str(entity_canonical_key or entity.get("name") or ""))
    candidate_slug = slugify_normalized(str(candidate.get("entity_key") or candidate.get("name") or ""))
    if entity_slug and entity_slug == candidate_slug:
        return 0.82, "normalized slug match"
    return 0.35, "same type fallback"


def _insert_candidate_match(
    conn,
    *,
    proposal_id: str,
    source: str,
    idx: int,
    candidate: dict[str, Any],
    score: float,
    reason: str,
    now_fn,
    safe_slug_fn,
    json_dumps_fn,
) -> None:
    conn.execute(
        """
        insert or replace into semantic_candidate_matches (
          candidate_match_id, semantic_proposal_id, source, candidate_type,
          candidate_key, candidate_name, score, match_reason, properties_json,
          evidence_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"cand_{safe_slug_fn(proposal_id)}_{safe_slug_fn(source)}_{idx}",
            proposal_id,
            source,
            candidate.get("entity_type") or candidate.get("type") or "unknown",
            candidate.get("entity_key") or candidate.get("key") or "",
            candidate.get("name"),
            score,
            reason,
            json_dumps_fn(candidate.get("properties") or {}),
            json_dumps_fn(candidate.get("evidence") or []),
            now_fn(),
        ),
    )


def search_candidates(
    conn,
    payload: dict[str, Any],
    args,
    limit_per: int = 8,
    *,
    now_fn,
    safe_slug_fn,
    json_dumps_fn,
) -> dict[str, Any]:
    result: dict[str, Any] = {"candidates": {}, "neo4j_status": "skipped_optional"}
    neo4j_statuses: set[str] = set()
    neo4j_errors: list[str] = []

    for entity in payload.get("entities", []):
        proposal_id = entity["proposal_id"]
        rows = [
            dict(row)
            for row in conn.execute(
                """
                select entity_key, entity_type, name, aliases_json, summary, properties_json, confidence
                from semantic_entities
                where entity_type = ?
                order by updated_at desc
                limit ?
                """,
                (entity["type"], max(limit_per * 4, 24)),
            )
        ]
        scored_rows = []
        for row in rows:
            score, reason = _candidate_score(entity, row)
            if score < 0.45:
                continue
            scored_rows.append((score, reason, row))
        scored_rows.sort(key=lambda item: (item[0], float(item[2].get("confidence") or 0.0)), reverse=True)
        rows = [row for _, _, row in scored_rows[:limit_per]]

        for idx, candidate in enumerate(rows):
            score, reason = _candidate_score(entity, candidate)
            _insert_candidate_match(
                conn,
                proposal_id=proposal_id,
                source="sqlite",
                idx=idx,
                candidate=candidate,
                score=score,
                reason=reason,
                now_fn=now_fn,
                safe_slug_fn=safe_slug_fn,
                json_dumps_fn=json_dumps_fn,
            )

        try:
            neo4j_status, neo4j_rows, neo4j_error = neo4j_query_candidate_rows(args, entity, limit_per)
        except Exception as exc:  # pragma: no cover - defensive; mirrors v2 fallback behavior
            neo4j_status, neo4j_rows, neo4j_error = "skipped_error", [], str(exc)

        neo4j_statuses.add(neo4j_status)
        if neo4j_error:
            neo4j_errors.append(neo4j_error[:500])

        merged = list(rows)
        existing_keys = {row["entity_key"] for row in merged}
        for idx, candidate in enumerate(neo4j_rows):
            if candidate.get("entity_key") in existing_keys:
                continue
            score, reason = _candidate_score(entity, candidate)
            merged.append(candidate)
            _insert_candidate_match(
                conn,
                proposal_id=proposal_id,
                source="neo4j",
                idx=idx,
                candidate=candidate,
                score=score,
                reason=f"{reason}; optional neo4j semantic candidate search",
                now_fn=now_fn,
                safe_slug_fn=safe_slug_fn,
                json_dumps_fn=json_dumps_fn,
            )
        result["candidates"][proposal_id] = merged[:limit_per]

    if neo4j_statuses:
        if "queried" in neo4j_statuses:
            result["neo4j_status"] = "queried"
        elif "skipped_error" in neo4j_statuses:
            result["neo4j_status"] = "skipped_error"
        elif "skipped_unconfigured" in neo4j_statuses:
            result["neo4j_status"] = "skipped_unconfigured"
        elif "disabled" in neo4j_statuses:
            result["neo4j_status"] = "disabled"
    if neo4j_errors:
        result["neo4j_errors"] = neo4j_errors[:3]
    return result
