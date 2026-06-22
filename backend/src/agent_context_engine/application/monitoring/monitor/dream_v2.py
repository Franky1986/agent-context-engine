from __future__ import annotations

from typing import Any

from ....infrastructure.config import MEMORY_DIR, ROOT, json_dumps, safe_slug, utc_now
from ....adapters.sqlite.request_db import connect
from ...dreaming.v2_cli import _semantic_patch, evaluate_v2_runs, run_fixture_evaluation
from ...dreaming.v2_refactor.compat import _apply_persistence


def monitor_dream_v2_review(payload: dict[str, Any]) -> dict[str, Any]:
    decision_id = str(payload.get("decision_id") or "")
    action = str(payload.get("action") or "")
    reason = str(payload.get("reason") or "")
    reviewer = str(payload.get("reviewer") or "monitor")
    if action not in {"approve", "reject", "defer"}:
        raise ValueError("action must be approve, reject, or defer")
    conn = connect()
    decision = conn.execute("select * from reconciliation_decisions where reconciliation_decision_id = ?", (decision_id,)).fetchone()
    if decision is None:
        raise ValueError(f"review item not found: {decision_id}")
    status = {"approve": "pending", "reject": "rejected", "defer": "deferred_review"}[action]
    now = utc_now()
    with conn:
        conn.execute(
            """
            update reconciliation_decisions
            set status = ?, review_required = case when ? = 'pending' then 0 else review_required end,
                review_reason = ?, updated_at = ?
            where reconciliation_decision_id = ?
            """,
            (status, status, reason, now, decision_id),
        )
        conn.execute(
            """
            insert into schema_reviews (
              schema_review_id, proposal_id, status, reviewer, reason, created_at,
              reviewed_at, metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"review_{safe_slug(decision_id)}_{now.replace(':', '-').replace('+', 'Z')}",
                decision["semantic_proposal_id"] or decision_id,
                status,
                reviewer,
                reason,
                now,
                now,
                json_dumps({"kind": "monitor_reconciliation_decision", "decision_id": decision_id, "action": action}),
            ),
        )
    return {"decision_id": decision_id, "status": status, "reviewer": reviewer}


def monitor_dream_v2_apply(payload: dict[str, Any]) -> dict[str, Any]:
    dream_run_id = str(payload.get("dream_run_id") or "")
    conn = connect()
    run = conn.execute("select * from dream_runs where dream_run_id = ?", (dream_run_id,)).fetchone()
    if run is None:
        raise ValueError(f"dream run not found: {dream_run_id}")
    persistence = _apply_persistence(conn, dream_run_id)
    path = MEMORY_DIR / "dream" / "v2" / "runs" / safe_slug(dream_run_id) / "07-persistence" / f"monitor-apply-{utc_now().replace(':', '-').replace('+', 'Z')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_dumps(persistence) + "\n", encoding="utf-8")
    now = utc_now()
    with conn:
        conn.execute(
            """
            insert or replace into dream_artifacts (
              dream_artifact_id, dream_run_id, session_id, artifact_kind,
              artifact_role, path, byte_count, char_count, created_at, metadata_json
            ) values (?, ?, ?, 'persistence', 'monitor_apply', ?, ?, ?, ?, ?)
            """,
            (
                f"artifact_{safe_slug(dream_run_id)}_monitor_apply_{now.replace(':', '-').replace('+', 'Z')}",
                dream_run_id,
                run["session_id"],
                str(path.relative_to(ROOT)),
                path.stat().st_size,
                len(path.read_text(encoding="utf-8")),
                now,
                json_dumps({"trigger": "monitor"}),
            ),
        )
    return {"dream_run_id": dream_run_id, "persistence": persistence, "path": str(path.relative_to(ROOT))}


def monitor_dream_v2_evaluate(limit: int = 20) -> dict[str, Any]:
    conn = connect()
    return evaluate_v2_runs(conn, limit)


def monitor_dream_v2_fixture_evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str(payload.get("kind") or "small")
    if kind not in {"small", "medium", "oversized", "injection"}:
        raise ValueError("kind must be small, medium, oversized, or injection")
    session_id = str(payload.get("session_id") or f"monitor-v2-fixture-{kind}")
    project = str(payload.get("project") or "agent-memory-monitor-fixtures")
    runner = str(payload.get("runner") or "codex")
    runner_model = payload.get("runner_model")
    if runner_model is not None:
        runner_model = str(runner_model)
    runner_timeout = int(payload.get("runner_timeout") or 60)
    return run_fixture_evaluation(
        kind=kind,
        session_id=session_id,
        project=project,
        runner=runner,
        runner_model=runner_model,
        runner_timeout=runner_timeout,
    )


def monitor_dream_v2_projection_dry_run() -> dict[str, Any]:
    conn = connect()
    patch = _semantic_patch(conn)
    out_dir = MEMORY_DIR / "graph" / "semantic" / "imports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"semantic_projection_monitor_{utc_now().replace(':', '-').replace('+', 'Z')}.json"
    path.write_text(json_dumps(patch) + "\n", encoding="utf-8")
    now = utc_now()
    result = {
        "patch": str(path.relative_to(ROOT)),
        "entities": len(patch["entities"]),
        "relations": len(patch["relations"]),
        "neo4j_status": "dry_run",
    }
    with conn:
        conn.execute(
            """
            insert or replace into projection_sync_runs (
              projection_sync_run_id, projection, started_at, finished_at, status,
              source_state_json, result_json, error_message
            ) values (?, 'neo4j_semantic_v2', ?, ?, 'dry_run', ?, ?, null)
            """,
            (
                f"projection_monitor_{now.replace(':', '-').replace('+', 'Z')}",
                now,
                now,
                json_dumps({"semantic_entities": len(patch["entities"]), "semantic_relations": len(patch["relations"])}),
                json_dumps(result),
            ),
        )
    return result
