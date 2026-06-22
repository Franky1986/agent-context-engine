"""Repository contract surface for Dreaming v2 migration."""

from __future__ import annotations

import json
from typing import Any
from dataclasses import dataclass

import sqlite3


@dataclass(frozen=True)
class DreamV2SessionRow:
    session_id: str
    project_id: str | None = None
    last_event_seq: int | None = None


@dataclass(frozen=True)
class DreamV2RunRow:
    dream_run_id: str
    session_id: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class DreamV2StageRunRow:
    stage_run_id: str
    stage_name: str
    stage_order: int | None = None
    status: str | None = None


@dataclass(frozen=True)
class DreamV2ReconciliationDecisionRow:
    reconciliation_decision_id: str
    dream_run_id: str
    semantic_proposal_id: str | None = None
    decision: str | None = None
    status: str | None = None


class DreamV2Repository:
    """Compatibility shell for future repository extraction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert_dream_run(
        self,
        *,
        dream_run_id: str,
        session_id: str,
        client_type: str,
        runner: str,
        runner_version: str,
        runner_model: str | None,
        started_at: str,
        event_from: int,
        event_to: int,
        event_count: int,
        transcript_path: str | None,
        transcript_mtime: str | None,
        created_by: str,
        pipeline_version: int = 2,
        auto_retry_allowed: int = 0,
    ) -> None:
        self.conn.execute(
            """
            insert into dream_runs (
              dream_run_id, session_id, client_type, runner, runner_version,
              runner_model, started_at, status, input_event_seq_from,
              input_event_seq_to, input_event_count, input_transcript_path,
              input_transcript_mtime, pipeline_version, pipeline_status,
              auto_retry_allowed, created_by
            ) values (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, 'running', ?, ?)
            """,
            (
                dream_run_id,
                session_id,
                client_type,
                runner,
                runner_version,
                runner_model,
                started_at,
                event_from,
                event_to,
                event_count,
                transcript_path,
                transcript_mtime,
                pipeline_version,
                auto_retry_allowed,
                created_by,
            ),
        )

    def update_dream_run_status(
        self,
        dream_run_id: str,
        *,
        finished_at: str,
        status: str,
        pipeline_status: str,
        output_summary_path: str | None = None,
        output_memory_paths_json: str | None = None,
        failed_stage: str | None = None,
        error_message: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            update dream_runs
            set finished_at=?, status=?, pipeline_status=?,
                output_summary_path=?, output_memory_paths_json=?, failed_stage=?, error_message=?
            where dream_run_id= ?
            """,
            (
                finished_at,
                status,
                pipeline_status,
                output_summary_path,
                output_memory_paths_json,
                failed_stage,
                error_message,
                dream_run_id,
            ),
        )

    def insert_stage_start(
        self,
        *,
        stage_run_id: str,
        dream_run_id: str,
        session_id: str,
        stage_name: str,
        stage_order: int,
        runner: str | None,
        model: str | None,
        event_from: int | None,
        event_to: int | None,
        created_by: str = "pipeline_v2",
        started_at: str,
    ) -> None:
        self.conn.execute(
            """
            insert or replace into dream_stage_runs (
              stage_run_id, dream_run_id, session_id, stage_name, stage_order,
              runner, model, status, started_at, input_event_seq_from,
              input_event_seq_to, created_by
            ) values (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?)
            """,
            (
                stage_run_id,
                dream_run_id,
                session_id,
                stage_name,
                stage_order,
                runner,
                model,
                started_at,
                event_from,
                event_to,
                created_by,
            ),
        )

    def update_stage_finish(
        self,
        *,
        stage_run_id: str,
        status: str,
        finished_at: str,
        duration_ms: int,
        prompt_path: str | None,
        raw_output_path: str | None,
        parsed_output_path: str | None,
        artifact_path: str | None,
        metadata_json: str,
        validation_json: str,
        error_message: str | None,
        prompt_tokens: int | None = None,
        cached_prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        reasoning_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        self.conn.execute(
            """
            update dream_stage_runs
            set status=?, finished_at=?, duration_ms=?,
                prompt_path=?, raw_output_path=?, parsed_output_path=?, artifact_path=?,
                metadata_json=?, validation_json=?, error_message=?,
                prompt_tokens=?, cached_prompt_tokens=?, completion_tokens=?,
                reasoning_tokens=?, total_tokens=?
            where stage_run_id=?
            """,
            (
                status,
                finished_at,
                duration_ms,
                prompt_path,
                raw_output_path,
                parsed_output_path,
                artifact_path,
                metadata_json,
                validation_json,
                error_message,
                prompt_tokens,
                cached_prompt_tokens,
                completion_tokens,
                reasoning_tokens,
                total_tokens,
                stage_run_id,
            ),
        )

    def insert_artifact(
        self,
        *,
        dream_artifact_id: str,
        dream_run_id: str,
        stage_run_id: str | None,
        session_id: str,
        artifact_kind: str,
        artifact_role: str,
        path: str,
        sha256: str,
        byte_count: int,
        char_count: int,
        created_at: str,
        metadata_json: str,
    ) -> None:
        self.conn.execute(
            """
            insert or replace into dream_artifacts (
              dream_artifact_id, dream_run_id, stage_run_id, session_id,
              artifact_kind, artifact_role, path, sha256, byte_count, char_count,
              created_at, metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dream_artifact_id,
                dream_run_id,
                stage_run_id,
                session_id,
                artifact_kind,
                artifact_role,
                path,
                sha256,
                byte_count,
                char_count,
                created_at,
                metadata_json,
            ),
        )

    def insert_reconciliation_decisions(
        self,
        *,
        dream_run_id: str,
        stage_run_id: str | None,
        payload: dict[str, Any],
        schema_version: str,
        created_at: str,
        updated_at: str | None = None,
        status: str = "pending",
    ) -> int:
        inserted = 0
        updated_at = updated_at or created_at
        for decision in payload.get("decisions", []):
            if not isinstance(decision, dict):
                continue
            semantic_proposal_id = decision.get("proposal_id")
            if semantic_proposal_id is not None:
                try:
                    row = self.conn.execute(
                        "select 1 from semantic_proposals where semantic_proposal_id = ?",
                        (semantic_proposal_id,),
                    ).fetchone()
                except sqlite3.OperationalError as exc:
                    if "no such table: semantic_proposals" not in str(exc):
                        raise
                    row = True
                if row is None:
                    semantic_proposal_id = None
            self.conn.execute(
                """
                insert or replace into reconciliation_decisions (
                  reconciliation_decision_id, dream_run_id, stage_run_id,
                  semantic_proposal_id, decision, target_key, confidence,
                  reason, human_summary, evidence_json, status, schema_version,
                  write_patch_json, review_required, review_reason, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.get("decision_id"),
                    dream_run_id,
                    stage_run_id,
                    semantic_proposal_id,
                    decision.get("action"),
                    decision.get("target_key"),
                    decision.get("confidence"),
                    decision.get("reason"),
                    decision.get("human_summary"),
                    json.dumps(decision.get("evidence") or []),
                    status,
                    schema_version,
                    json.dumps(decision.get("write_patch") or {}),
                    1 if decision.get("review_required") else 0,
                    decision.get("review_reason"),
                    created_at,
                    updated_at,
                ),
            )
            inserted += 1
        return inserted

    def update_session_dream_state(
        self,
        session_id: str,
        *,
        dream_status: str | None = None,
        dream_runner_used: str | None = None,
        dream_runner_status: str | None = None,
        last_dream_event_seq: int | None = None,
        last_dream_at: str | None = None,
        last_dream_run_id: str | None = None,
        session_brief: str | None = None,
        keep_existing_session_brief: bool = False,
        summary_status: str | None = None,
        last_summary_event_seq: int | None = None,
        last_summary_at: str | None = None,
    ) -> None:
        updates: list[str] = []
        params: list[Any] = []
        if dream_status is not None:
            updates.append("dream_status=?")
            params.append(dream_status)
        if dream_runner_used is not None:
            updates.append("dream_runner_used=?")
            params.append(dream_runner_used)
        if dream_runner_status is not None:
            updates.append("dream_runner_status=?")
            params.append(dream_runner_status)
        if last_dream_event_seq is not None:
            updates.append("last_dream_event_seq=?")
            params.append(last_dream_event_seq)
        if last_dream_at is not None:
            updates.append("last_dream_at=?")
            params.append(last_dream_at)
        if last_dream_run_id is not None:
            updates.append("last_dream_run_id=?")
            params.append(last_dream_run_id)
        if session_brief is not None:
            if keep_existing_session_brief:
                updates.append("session_brief = coalesce(session_brief, ?)")
            else:
                updates.append("session_brief=?")
            params.append(session_brief)
        if summary_status is not None:
            updates.append("summary_status=?")
            params.append(summary_status)
        if last_summary_event_seq is not None:
            updates.append("last_summary_event_seq=?")
            params.append(last_summary_event_seq)
        if last_summary_at is not None:
            updates.append("last_summary_at=?")
            params.append(last_summary_at)
        if not updates:
            return
        self.conn.execute(
            f"update sessions set {', '.join(updates)} where session_id=?",
            (*params, session_id),
        )

    def update_dream_run_metrics(
        self,
        dream_run_id: str,
        *,
        duration_ms: int | None,
        prompt_tokens: int,
        cached_prompt_tokens: int,
        completion_tokens: int,
        reasoning_tokens: int,
        total_tokens: int,
    ) -> None:
        try:
            self.conn.execute(
                """
                update dream_runs
                set duration_ms = coalesce(?, duration_ms),
                    prompt_tokens = ?,
                    cached_prompt_tokens = ?,
                    completion_tokens = ?,
                    reasoning_tokens = ?,
                    total_tokens = ?
                where dream_run_id = ?
                """,
                (
                    duration_ms,
                    prompt_tokens,
                    cached_prompt_tokens,
                    completion_tokens,
                    reasoning_tokens,
                    total_tokens,
                    dream_run_id,
                ),
            )
        except sqlite3.OperationalError as exc:
            if "no such column" not in str(exc):
                raise

    def mark_running_stages_failed(self, dream_run_id: str, finished_at: str, error_message: str) -> int:
        cursor = self.conn.execute(
            "update dream_stage_runs set status='failed', finished_at=?, error_message=? where dream_run_id=? and status='running'",
            (finished_at, error_message, dream_run_id),
        )
        return cursor.rowcount

    def current_running_stage_name(self, dream_run_id: str) -> str | None:
        row = self.conn.execute(
            "select stage_name from dream_stage_runs where dream_run_id=? and status='running' order by stage_order desc limit 1",
            (dream_run_id,),
        ).fetchone()
        return row["stage_name"] if row is not None else None

    def upsert_session_dream_summary(
        self,
        session_id: str,
        *,
        summary_path: str,
        created_at: str,
        input_event_seq_to: int,
        input_event_count: int,
    ) -> None:
        self.conn.execute(
            """
            insert into summaries (
              session_id, summary_path, created_at, input_event_seq_to,
              input_event_count, summary_kind
            ) values (?, ?, ?, ?, ?, 'dream_pipeline_v2')
            on conflict(session_id) do update set
              summary_path = excluded.summary_path,
              created_at = excluded.created_at,
              input_event_seq_to = excluded.input_event_seq_to,
              input_event_count = excluded.input_event_count,
              summary_kind = excluded.summary_kind
            """,
            (session_id, summary_path, created_at, input_event_seq_to, input_event_count),
        )

    def fetch_session(self, session_id: str) -> Any:
        return self.conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()

    def resolve_session_selector(self, selector: str) -> Any:
        prefix = f"{selector}%"
        rows = list(
            self.conn.execute(
                """
                select * from sessions
                where session_id like ?
                   or coalesce(thread_name, '') like ?
                order by coalesce(last_event_at, started_at) desc
                limit 2
                """,
                (prefix, f"%{selector}%"),
            ).fetchall()
        )
        if rows:
            return rows[0]
        like = f"%{selector}%"
        return self.conn.execute(
            """
            select s.*
            from sessions s
            where exists (
              select 1 from events e
              where e.session_id = s.session_id
                and (
                  coalesce(e.prompt, '') like ?
                  or coalesce(e.last_assistant_message, '') like ?
                  or coalesce(e.tool_response_text, '') like ?
                )
            )
            order by coalesce(s.last_event_at, s.started_at) desc
            limit 1
            """,
            (like, like, like),
        ).fetchone()

    def fetch_session_by_selector(self, selector: str) -> Any:
        return self.conn.execute("select * from sessions where session_id = ?", (selector,)).fetchone()

    def fetch_dream_run(self, dream_run_id: str) -> Any:
        return self.conn.execute("select * from dream_runs where dream_run_id = ?", (dream_run_id,)).fetchone()

    def latest_dream_run_for_session(self, session_id: str) -> Any:
        return self.conn.execute(
            """
            select * from dream_runs
            where session_id = ?
            order by started_at desc, dream_run_id desc
            limit 1
            """,
            (session_id,),
        ).fetchone()

    def list_dream_runs_for_session(self, session_id: str, limit: int | None = None) -> list[Any]:
        query = """select * from dream_runs where session_id = ? order by started_at desc, dream_run_id desc"""
        if limit is not None:
            return list(self.conn.execute(query + " limit ?", (session_id, int(limit))).fetchall())
        return list(self.conn.execute(query, (session_id,)).fetchall())

    def list_events_for_session_range(self, session_id: str, event_from: int, event_to: int) -> list[Any]:
        return list(
            self.conn.execute(
                "select * from events where session_id=? and seq between ? and ? order by seq",
                (session_id, int(event_from), int(event_to)),
            ).fetchall()
        )

    def fetch_stage_run(self, stage_run_id: str) -> Any:
        return self.conn.execute(
            "select * from dream_stage_runs where stage_run_id = ?",
            (stage_run_id,),
        ).fetchone()

    def fetch_succeeded_stage_run(self, dream_run_id: str, stage_name: str) -> Any:
        return self.conn.execute(
            """
            select *
            from dream_stage_runs
            where dream_run_id = ? and stage_name = ? and status = 'succeeded'
            order by started_at desc, stage_run_id desc
            limit 1
            """,
            (dream_run_id, stage_name),
        ).fetchone()

    def list_stage_runs_for_dream(self, dream_run_id: str) -> list[Any]:
        return list(self.conn.execute(
            "select * from dream_stage_runs where dream_run_id = ? order by stage_order asc",
            (dream_run_id,),
        ).fetchall())

    def list_reconciliation_decisions(self, dream_run_id: str) -> list[Any]:
        return list(
            self.conn.execute(
                "select * from reconciliation_decisions where dream_run_id = ? order by reconciliation_decision_id",
                (dream_run_id,),
            ).fetchall(),
        )

    def list_session_artifacts(self, session_id: str) -> list[Any]:
        return list(self.conn.execute("select * from dream_artifacts where session_id = ?", (session_id,)).fetchall())

    def fetch_latest_succeeded_dream_output_memory_paths(self, session_id: str) -> list[str]:
        row = self.conn.execute(
            """
            select output_memory_paths_json
            from dream_runs
            where session_id = ? and status = 'succeeded'
            order by finished_at desc, started_at desc
            limit 1
            """,
            (session_id,),
        ).fetchone()
        if not row or not row["output_memory_paths_json"]:
            return []
        try:
            paths = json.loads(row["output_memory_paths_json"])
        except json.JSONDecodeError:
            return []
        if not isinstance(paths, list):
            return []
        return [str(item) for item in paths if isinstance(item, str)]

    def fetch_latest_session_handover_path(self, session_id: str) -> str | None:
        row = self.conn.execute(
            """
            select summary_path
            from summaries
            where session_id = ?
            """,
            (session_id,),
        ).fetchone()
        return str(row["summary_path"]) if row is not None and row["summary_path"] else None

    def list_session_semantic_entities(self, session_id: str, limit: int = 40) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.conn.execute(
                """
                select entity_key, entity_type, name, summary, confidence
                from semantic_entities
                where source_session_id = ?
                order by updated_at desc
                limit ?
                """,
                (session_id, int(limit)),
            )
        ]

    def list_session_semantic_relations(self, session_id: str, limit: int = 40) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.conn.execute(
                """
                select relation_key, relation_type, source_entity_key, target_entity_key, summary, confidence
                from semantic_relations
                where source_session_id = ?
                order by updated_at desc
                limit ?
                """,
                (session_id, int(limit)),
            )
        ]

    def aggregate_stage_metrics(self, dream_run_id: str) -> dict[str, int | None]:
        row = self.conn.execute(
            """
            select
              coalesce(sum(prompt_tokens), 0) as prompt_tokens,
              coalesce(sum(cached_prompt_tokens), 0) as cached_prompt_tokens,
              coalesce(sum(completion_tokens), 0) as completion_tokens,
              coalesce(sum(reasoning_tokens), 0) as reasoning_tokens,
              coalesce(sum(total_tokens), 0) as total_tokens
            from dream_stage_runs
            where dream_run_id = ?
            """,
            (dream_run_id,),
        ).fetchone()
        return {
            "prompt_tokens": int(row["prompt_tokens"] or 0) if row else 0,
            "cached_prompt_tokens": int(row["cached_prompt_tokens"] or 0) if row else 0,
            "completion_tokens": int(row["completion_tokens"] or 0) if row else 0,
            "reasoning_tokens": int(row["reasoning_tokens"] or 0) if row else 0,
            "total_tokens": int(row["total_tokens"] or 0) if row else 0,
        }

    def list_sessions_pending_dream(self) -> list[Any]:
        return list(
            self.conn.execute(
                """
                select *
                from sessions
                where last_event_seq > last_dream_event_seq
                  and dream_status in ('dream_pending', 'dream_pending_runner_missing', 'dreaming')
                order by last_event_at desc
                """
            ).fetchall()
        )

    def list_sessions_missing_graph_artifacts(self) -> list[Any]:
        return list(
            self.conn.execute(
                """
                select *
                from sessions
                where exists (
                  select 1
                  from dream_runs dr
                  where dr.session_id = sessions.session_id
                    and dr.status = 'succeeded'
                    and not exists (
                      select 1
                      from graph_artifacts ga
                      where ga.dream_run_id = dr.dream_run_id
                        and ga.artifact_type = 'patch'
                        and ga.status = 'valid'
                    )
                )
                order by last_event_at desc
                """
            ).fetchall()
        )

    def list_missing_patch_dream_runs(self, session_id: str) -> list[Any]:
        return list(
            self.conn.execute(
                """
                select *
                from dream_runs dr
                where dr.session_id = ?
                  and dr.status = 'succeeded'
                  and not exists (
                    select 1
                    from graph_artifacts ga
                    where ga.dream_run_id = dr.dream_run_id
                      and ga.artifact_type = 'patch'
                      and ga.status = 'valid'
                  )
                order by dr.input_event_seq_from, dr.input_event_seq_to, dr.started_at
                """,
                (session_id,),
            ).fetchall()
        )
