from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ...infrastructure.config import ROOT, json_dumps, safe_slug, utc_now
from ...infrastructure.text import read_text_limited
from .materialize import materialize_graph_patch
from .schema import GRAPH_DIR, ensure_patch_metadata, validate_graph_patch


def graph_artifact_path(kind: str, name: str) -> Path:
    path = GRAPH_DIR / kind / f"{safe_slug(name)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def read_graph_json(path_arg: str) -> tuple[Path, dict[str, Any]]:
    path = Path(path_arg)
    if not path.is_absolute():
        path = ROOT / path
    return path, json.loads(read_text_limited(path, 10_000_000))


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def normalize_helpful_score(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score > 1.0 and score <= 10.0:
        score = score / 10.0
    if score < 0.0:
        return 0.0
    if score > 1.0:
        return 1.0
    return round(score, 4)


def normalize_insights(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    intent = str(value.get("intent") or "").strip().lower()
    intent = safe_slug(intent) if intent else ""
    tags = []
    raw_tags = value.get("tags") or value.get("labels") or []
    if isinstance(raw_tags, str):
        raw_tags = [raw_tags]
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            tag_text = safe_slug(str(tag).strip().lower())
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
            if len(tags) >= 12:
                break
    result: dict[str, Any] = {}
    if intent:
        result["intent"] = intent
    score = normalize_helpful_score(value.get("helpful_score", value.get("helpfulScore")))
    if score is not None:
        result["helpful_score"] = score
    result["tags"] = tags
    if value.get("rationale"):
        result["rationale"] = str(value.get("rationale"))[:500]
    return result


def patch_insights(patch: dict[str, Any]) -> dict[str, Any]:
    return normalize_insights(patch.get("insights") or patch.get("metadata") or {})


def write_graph_artifact(
    conn: sqlite3.Connection,
    *,
    patch: dict[str, Any],
    artifact_type: str,
    path: Path,
    session_id: str,
    dream_run_id: str | None,
    runner: str,
    source_paths: list[str] | None = None,
) -> None:
    patch = ensure_patch_metadata(patch)
    errors = validate_graph_patch(patch)
    path.write_text(json_dumps(patch) + "\n", encoding="utf-8")
    evidence_count = sum(len(entity.get("evidence", [])) for entity in patch.get("entities", [])) + sum(len(relation.get("evidence", [])) for relation in patch.get("relations", []))
    artifact_id = f"{artifact_type}_{safe_slug(path.stem)}"
    insights = patch_insights(patch)
    with conn:
        conn.execute(
            """
            insert or replace into graph_artifacts (
              graph_artifact_id, session_id, dream_run_id, artifact_type, path,
              created_at, status, entity_count, relation_count, evidence_count,
              runner, source_paths_json, intent, helpful_score, tags_json, error_message
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact_id,
                session_id,
                dream_run_id,
                artifact_type,
                display_path(path),
                utc_now(),
                "valid" if not errors else "invalid",
                len(patch.get("entities", [])),
                len(patch.get("relations", [])),
                evidence_count,
                runner,
                json_dumps(source_paths or []),
                insights.get("intent"),
                insights.get("helpful_score"),
                json_dumps(insights.get("tags") or []),
                "\n".join(errors) if errors else None,
            ),
        )
        if dream_run_id and artifact_type == "patch" and insights:
            conn.execute(
                """
                update dream_runs
                set intent = coalesce(?, intent),
                    helpful_score = coalesce(?, helpful_score),
                    tags_json = coalesce(?, tags_json)
                where dream_run_id = ?
                """,
                (insights.get("intent"), insights.get("helpful_score"), json_dumps(insights.get("tags") or []), dream_run_id),
            )
        if not errors:
            materialize_graph_patch(conn, patch, artifact_id, session_id=session_id, dream_run_id=dream_run_id, intent=insights.get("intent"), helpful_score=insights.get("helpful_score"), tags=insights.get("tags") or [])
