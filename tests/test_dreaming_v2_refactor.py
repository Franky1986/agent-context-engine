from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_context_engine.application.dreaming.v2 as dream_v2
from agent_context_engine.application.dreaming.v2_infrastructure import (
    default_command_runner,
    default_file_system,
    default_text_tools,
)
from agent_context_engine.application.dreaming.v2_refactor import runtime as stage_runtime
from agent_context_engine.application.dreaming.v2_refactor.context import (
    DreamV2Context,
    DreamV2RunArtifacts,
    DreamV2RunSummary,
    DreamV2StageContext,
)
from agent_context_engine.application.dreaming.v2_refactor.repositories import DreamV2Repository
from agent_context_engine.application.dreaming.v2_refactor.stages.narrative import run_narrative_stage
from agent_context_engine.application.dreaming.v2_refactor.services import repair_missing_graph_patches
from agent_context_engine.application.dreaming.v2_refactor.services.semantic_payloads import apply_reconciliation_guardrails, apply_semantic_guardrails
from agent_context_engine.application.dreaming.v2_refactor.stages import (
    run_audit_stage,
    run_candidate_search_stage,
    run_normalization_stage,
    run_reconciliation_stage,
    run_operational_extraction_stage,
    run_semantic_stage,
    run_window_stage,
)
from agent_context_engine.application.dreaming.v2_refactor.services import invoke_runner as run_v2_invoke_runner
from agent_context_engine.application.dreaming.v2_refactor.stages.persistence import run_persistence_stage


class _DummyClock:
    def utc_now(self) -> str:
        return "2026-06-10T10:00:00Z"


class _DummyDbProvider:
    def connect(self, init: bool = False) -> sqlite3.Connection:  # pragma: no cover - defensive stub
        raise AssertionError("connect should not be called in this test")


class TestV2RefactorSafety(unittest.TestCase):
    """Safety checks before active refactor migration."""

    def test_stage_context_dataclasses_are_frozen_and_composable(self) -> None:
        artifacts = DreamV2RunArtifacts()
        self.assertEqual(artifacts.audit_paths, {})

        stage_ctx = DreamV2StageContext(
            stage_name="dream_narrative",
            stage_order=1,
            stage_run_id="stage-1",
            raw_output_path=Path("/tmp/raw.md"),
            parsed_output_path=Path("/tmp/parsed.json"),
            metadata={"k": "v"},
        )
        self.assertEqual(stage_ctx.stage_name, "dream_narrative")

        conn = sqlite3.connect(":memory:")
        ctx = DreamV2Context(
            conn=conn,
            dream_run_id="dream-test",
            session_id="session-test",
            event_from=1,
            event_to=10,
            run_dir=Path("/tmp/run"),
            dry_run=True,
            clock=_DummyClock(),
            file_system=default_file_system(),
            db_provider=_DummyDbProvider(),
            run_artifacts=artifacts,
        )
        self.assertEqual(ctx.event_from, 1)
        self.assertTrue(ctx.dry_run)

        summary = DreamV2RunSummary(conn=conn, args=type("Args", (), {"runner": "codex"})(), context=ctx)
        self.assertEqual(summary.context.dream_run_id, "dream-test")

    def test_narrative_stage_contract_runs_without_pipeline_side_effects(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text not null,
                  session_id text not null,
                  stage_name text not null,
                  stage_order int not null,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )
        stage_ctx = DreamV2StageContext(stage_name="dream_narrative", stage_order=1, stage_run_id="stage-test")
        ctx = DreamV2Context(
            conn=conn,
            dream_run_id="dream-run",
            session_id="session-1",
            event_from=1,
            event_to=3,
            run_dir=Path("/tmp/run"),
            dry_run=False,
            clock=_DummyClock(),
            file_system=default_file_system(),
            db_provider=_DummyDbProvider(),
        )
        old_env = os.environ.get("AGENT_MEMORY_DREAM_V2_MOCK")
        os.environ["AGENT_MEMORY_DREAM_V2_MOCK"] = "1"
        try:
            result = run_narrative_stage(
                conn=conn,
                context=ctx,
                stage_context=stage_ctx,
                event_rows=[
                    {
                        "seq": 1,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "user",
                        "prompt": "Prompt 1",
                        "last_assistant_message": "Assistant 1",
                        "tool_name": None,
                    },
                    {
                        "seq": 2,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "assistant",
                        "prompt": "Prompt 2",
                        "last_assistant_message": "Assistant 2",
                        "tool_name": None,
                    },
                ],
                session={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                prompt_text="prompt body",
                prior_dream_summary="previous summary",
                current_handover="handover text",
                semantic_context={"entities": [], "relations": []},
                runner="codex",
                runner_model=None,
                reuse_from_dream_run_id=None,
                runner_timeout=120,
                dry_run=True,
            )
        finally:
            if old_env is None:
                del os.environ["AGENT_MEMORY_DREAM_V2_MOCK"]
            else:
                os.environ["AGENT_MEMORY_DREAM_V2_MOCK"] = old_env

        self.assertEqual(result["status"], "migrated")
        self.assertEqual(result["event_from"], 1)
        self.assertEqual(result["event_to"], 3)

    def _build_skeleton_context(self) -> DreamV2Context:
        return DreamV2Context(
            conn=sqlite3.connect(":memory:"),
            dream_run_id="dream-run",
            session_id="session-1",
            event_from=1,
            event_to=3,
            run_dir=Path("/tmp/run"),
            dry_run=True,
            clock=_DummyClock(),
            file_system=default_file_system(),
            db_provider=_DummyDbProvider(),
        )

    def _build_skeleton_stage_context(self, stage_name: str, stage_order: int, stage_run_id: str) -> DreamV2StageContext:
        return DreamV2StageContext(
            stage_name=stage_name,
            stage_order=stage_order,
            stage_run_id=stage_run_id,
            raw_output_path=Path("/tmp/raw.txt"),
            parsed_output_path=Path("/tmp/parsed.json"),
            artifact_path=Path("/tmp/artifacts.json"),
            metadata={"unit": "true"},
        )

    def _bootstrap_v2_orchestrator_db(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute(
                """
                create table sessions (
                  session_id text primary key,
                  project_id text,
                  client_type text,
                  last_event_seq int,
                  transcript_path text,
                  dream_status text,
                  dream_runner_used text,
                  dream_runner_status text,
                  last_dream_event_seq int,
                  last_dream_at text,
                  last_dream_run_id text,
                  session_brief text,
                  summary_status text,
                  last_summary_event_seq int,
                  last_summary_at text
                )
                """
            )
            conn.execute(
                """
                create table events (
                  session_id text,
                  seq int,
                  recorded_at text,
                  event_name text,
                  prompt text,
                  last_assistant_message text,
                  tool_name text
                )
                """
            )
            conn.execute(
                """
                create table dream_runs (
                  dream_run_id text primary key,
                  session_id text,
                  client_type text,
                  runner text,
                  runner_version text,
                  runner_model text,
                  started_at text,
                  status text,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  input_event_count int,
                  input_transcript_path text,
                  input_transcript_mtime text,
                  pipeline_version int,
                  pipeline_status text,
                  auto_retry_allowed int,
                  created_by text,
                  finished_at text,
                  output_summary_path text,
                  output_memory_paths_json text,
                  failed_stage text,
                  error_message text
                )
                """
            )
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text,
                  session_id text,
                  stage_name text,
                  stage_order int,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )
            conn.execute(
                """
                create table dream_artifacts (
                  dream_artifact_id text primary key,
                  dream_run_id text,
                  stage_run_id text,
                  session_id text,
                  artifact_kind text,
                  artifact_role text,
                  path text,
                  sha256 text,
                  byte_count int,
                  char_count int,
                  created_at text,
                  metadata_json text
                )
                """
            )
            conn.execute(
                """
                create table reconciliation_decisions (
                  reconciliation_decision_id text primary key,
                  dream_run_id text,
                  semantic_proposal_id text
                )
                """
            )
            conn.execute(
                """
                create table semantic_entities (
                  entity_key text,
                  entity_type text,
                  name text,
                  summary text,
                  confidence real,
                  source_session_id text,
                  updated_at text
                )
                """
            )
            conn.execute(
                """
                create table semantic_relations (
                  relation_key text,
                  relation_type text,
                  source_entity_key text,
                  target_entity_key text,
                  summary text,
                  confidence real,
                  source_session_id text,
                  updated_at text
                )
                """
            )
            conn.execute(
                """
                create table summaries (
                  session_id text primary key,
                  summary_path text,
                  created_at text,
                  summary_status text,
                  input_event_seq_to int,
                  input_event_count int,
                  summary_kind text
                )
                """
            )

    def _fake_run_audit_stage(self, audit_paths: dict[str, Path]) -> dict:
        return {
            "status": "migrated",
            "event_count": 2,
            "semantic_count": 0,
            "relation_count": 0,
            "decision_count": 0,
            "audit_paths": audit_paths,
            "summary_length": 1,
        }

    def test_run_v2_for_session_success_dry_run_marks_dream_as_dry_run_succeeded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "dream-v2.sqlite"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            self._bootstrap_v2_orchestrator_db(conn)
            with conn:
                conn.execute(
                    "insert into sessions(session_id, project_id, client_type, last_event_seq, transcript_path) values (?, ?, ?, ?, ?)",
                    ("session-1", "project-1", "codex", 2, "logs/transcript.jsonl"),
                )
                conn.executemany(
                    "insert into events(session_id, seq, recorded_at, event_name, prompt, last_assistant_message, tool_name) values (?, ?, ?, ?, ?, ?, ?)",
                    [
                        ("session-1", 1, "2026-06-10T10:00:00Z", "user", "Prompt 1", "Assistant 1", None),
                        ("session-1", 2, "2026-06-10T10:00:00Z", "assistant", "Prompt 2", "Assistant 2", None),
                    ],
                )
                conn.execute(
                    "insert into summaries(session_id, summary_path, summary_status, summary_kind) values (?, ?, ?, ?)",
                    ("session-1", "summaries/session-1.md", "summarized", "legacy"),
                )

            run_audit_files = {
                "summary": tmp_path / "audit-summary.md",
                "window": tmp_path / "window.json",
                "dream": tmp_path / "dream.md",
            }
            for path in run_audit_files.values():
                path.write_text(f"artifact: {path.name}")

            args = argparse.Namespace(
                runner="codex",
                runner_model=None,
                dry_run=True,
                force_event_seq_from=1,
                force_event_seq_to=2,
                reuse_validated_stages=False,
                reuse_from_dream_run_id=None,
                runner_timeout=1800,
                created_by="unit-test",
            )

            def _open_db_conn(*_args: object, **_kwargs: object) -> sqlite3.Connection:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                return conn

            deps = replace(
                dream_v2._session_runner_dependencies(),
                acquire_lock=lambda *_args, **_kwargs: "lock-token",
                release_lock=lambda *_args, **_kwargs: None,
                connect=_open_db_conn,
                resolve_dream_runner=lambda *_args, **_kwargs: ("codex", None),
                dream_dir=lambda: tmp_path,
                root=lambda: tmp_path,
                run_window_stage=lambda **_kwargs: {},
                run_narrative_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "response": "Dream output",
                    "project_dream_path": None,
                    "event_from": 1,
                    "event_to": 2,
                },
                run_semantic_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "semantic_payload": {"schema_version": "semantic_proposals.v2", "entities": [], "relations": []},
                    "semantic_id_map": {},
                },
                run_normalization_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "semantic_payload": {"schema_version": "semantic_proposals.v2", "entities": [], "relations": []},
                    "event_from": 1,
                    "event_to": 2,
                },
                run_operational_extraction_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "operational_payload": {},
                },
                run_candidate_search_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "candidates": {"entities": [], "relations": []},
                },
                run_reconciliation_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "reconciliation_payload": {"schema_version": "reconciliation_decisions.v2", "decisions": []},
                },
                run_persistence_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "persistence": {},
                },
                run_audit_stage=lambda **_kwargs: self._fake_run_audit_stage(run_audit_files),
            )
            with patch("agent_context_engine.application.dreaming.v2._session_runner_dependencies", return_value=deps):

                exit_code = dream_v2.run_v2_for_session(args, "session-1")

            self.assertEqual(exit_code, 0)

            verify_conn = sqlite3.connect(db_path)
            verify_conn.row_factory = sqlite3.Row
            dream_run = verify_conn.execute(
                "select * from dream_runs where session_id='session-1' and status='succeeded' order by started_at desc limit 1"
            ).fetchone()
            session = verify_conn.execute("select * from sessions where session_id='session-1'").fetchone()
            audit_artifacts = verify_conn.execute("select count(*) as c from dream_artifacts where session_id='session-1'").fetchone()[0]
            self.assertIsNotNone(dream_run)
            self.assertEqual(dream_run["pipeline_status"], "dry_run")
            self.assertTrue(dream_run["output_summary_path"])
            self.assertTrue(json.loads(dream_run["output_memory_paths_json"]))
            self.assertEqual(session["dream_status"], "dream_pending")
            self.assertEqual(session["dream_runner_status"], "dry_run_succeeded")
            self.assertGreaterEqual(audit_artifacts, len(run_audit_files))

    def test_run_v2_for_session_failure_updates_failed_state_and_marks_session_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "dream-v2.sqlite"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            self._bootstrap_v2_orchestrator_db(conn)
            with conn:
                conn.execute(
                    "insert into sessions(session_id, project_id, client_type, last_event_seq, transcript_path) values (?, ?, ?, ?, ?)",
                    ("session-1", "project-1", "codex", 1, "logs/transcript.jsonl"),
                )
                conn.execute(
                    "insert into events(session_id, seq, recorded_at, event_name, prompt, last_assistant_message, tool_name) values (?, ?, ?, ?, ?, ?, ?)",
                    ("session-1", 1, "2026-06-10T10:00:00Z", "user", "Prompt 1", "Assistant 1", None),
                )

            args = argparse.Namespace(
                runner="codex",
                runner_model=None,
                dry_run=True,
                force_event_seq_from=1,
                force_event_seq_to=1,
                reuse_validated_stages=False,
                reuse_from_dream_run_id=None,
                runner_timeout=1800,
                created_by="unit-test",
            )

            def _open_db_conn(*_args: object, **_kwargs: object) -> sqlite3.Connection:
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                return conn

            def _raise_reconciliation_failure(**_kwargs: object) -> dict[str, Any]:
                raise RuntimeError("integration stage failure")

            deps = replace(
                dream_v2._session_runner_dependencies(),
                acquire_lock=lambda *_args, **_kwargs: "lock-token",
                release_lock=lambda *_args, **_kwargs: None,
                connect=_open_db_conn,
                resolve_dream_runner=lambda *_args, **_kwargs: ("codex", None),
                dream_dir=lambda: tmp_path,
                root=lambda: tmp_path,
                run_window_stage=lambda **_kwargs: {},
                run_narrative_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "response": "Dream output",
                    "project_dream_path": None,
                    "event_from": 1,
                    "event_to": 1,
                },
                run_semantic_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "semantic_payload": {"schema_version": "semantic_proposals.v2", "entities": [], "relations": []},
                    "semantic_id_map": {},
                },
                run_normalization_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "semantic_payload": {"schema_version": "semantic_proposals.v2", "entities": [], "relations": []},
                    "event_from": 1,
                    "event_to": 1,
                },
                run_operational_extraction_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "operational_payload": {},
                },
                run_candidate_search_stage=lambda **_kwargs: {
                    "status": "migrated",
                    "candidates": {"entities": [], "relations": []},
                },
                run_reconciliation_stage=_raise_reconciliation_failure,
            )
            with patch("agent_context_engine.application.dreaming.v2._session_runner_dependencies", return_value=deps):

                exit_code = dream_v2.run_v2_for_session(args, "session-1")

            self.assertEqual(exit_code, 1)

            verify_conn = sqlite3.connect(db_path)
            verify_conn.row_factory = sqlite3.Row
            dream_run = verify_conn.execute(
                "select * from dream_runs where session_id='session-1' order by started_at desc limit 1"
            ).fetchone()
            session = verify_conn.execute("select * from sessions where session_id='session-1'").fetchone()
            self.assertEqual(dream_run["status"], "failed")
            self.assertEqual(dream_run["pipeline_status"], "failed")
            self.assertEqual(session["dream_status"], "failed")
            self.assertEqual(session["dream_runner_status"], "integration stage failure")

    def test_run_v2_for_session_reuse_preflight_failure_releases_lock_and_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            db_path = tmp_path / "dream-v2.sqlite"
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            self._bootstrap_v2_orchestrator_db(conn)
            with conn:
                conn.execute(
                    "insert into sessions(session_id, project_id, client_type, last_event_seq, transcript_path) values (?, ?, ?, ?, ?)",
                    ("session-1", "project-1", "codex", 2, "logs/transcript.jsonl"),
                )
                conn.execute(
                    "insert into events(session_id, seq, recorded_at, event_name, prompt, last_assistant_message, tool_name) values (?, ?, ?, ?, ?, ?, ?)",
                    ("session-1", 1, "2026-06-10T10:00:00Z", "user", "Prompt 1", "Assistant 1", None),
                )
                conn.execute(
                    "insert into events(session_id, seq, recorded_at, event_name, prompt, last_assistant_message, tool_name) values (?, ?, ?, ?, ?, ?, ?)",
                    ("session-1", 2, "2026-06-10T10:00:01Z", "assistant", "Prompt 2", "Assistant 2", None),
                )

            args = argparse.Namespace(
                runner="codex",
                runner_model=None,
                dry_run=True,
                force_event_seq_from=1,
                force_event_seq_to=2,
                reuse_validated_stages=True,
                reuse_from_dream_run_id="missing-run",
                runner_timeout=1800,
                created_by="unit-test",
            )

            class _TrackingConnection:
                def __init__(self, inner: sqlite3.Connection) -> None:
                    self._inner = inner
                    self.closed = False

                def __getattr__(self, name: str) -> Any:
                    return getattr(self._inner, name)

                def __enter__(self) -> sqlite3.Connection:
                    return self._inner.__enter__()

                def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None:
                    return self._inner.__exit__(exc_type, exc, tb)

                def close(self) -> None:
                    self.closed = True
                    self._inner.close()

            connections: list[_TrackingConnection] = []
            released: list[str] = []

            def _open_db_conn(*_args: object, **_kwargs: object) -> _TrackingConnection:
                inner = sqlite3.connect(db_path)
                inner.row_factory = sqlite3.Row
                wrapped = _TrackingConnection(inner)
                connections.append(wrapped)
                return wrapped

            deps = replace(
                dream_v2._session_runner_dependencies(),
                acquire_lock=lambda *_args, **_kwargs: "lock-token",
                release_lock=lambda token: released.append(str(token)),
                connect=_open_db_conn,
                resolve_dream_runner=lambda *_args, **_kwargs: ("codex", None),
                dream_dir=lambda: tmp_path,
                root=lambda: tmp_path,
            )
            with patch("agent_context_engine.application.dreaming.v2._session_runner_dependencies", return_value=deps):
                exit_code = dream_v2.run_v2_for_session(args, "session-1")

            self.assertEqual(exit_code, 1)
            self.assertEqual(released, ["lock-token"])
            self.assertEqual(len(connections), 1)
            self.assertTrue(connections[0].closed)

    def test_stage_contracts_roundtrip_for_refactor_stages(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text not null,
                  session_id text not null,
                  stage_name text not null,
                  stage_order int not null,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )
            conn.execute(
                """
                create table sessions (
                  session_id text primary key,
                  project_id text,
                  client_type text,
                  last_event_seq int
                )
                """
            )
            conn.execute(
                """
                create table reconciliation_decisions (
                  reconciliation_decision_id text primary key,
                  dream_run_id text not null,
                  stage_run_id text,
                  semantic_proposal_id text,
                  decision text,
                  target_key text,
                  confidence real,
                  reason text,
                  human_summary text,
                  evidence_json text,
                  status text,
                  schema_version text,
                  write_patch_json text,
                  review_required int,
                  review_reason text,
                  created_at text,
                  updated_at text
                )
                """
            )
            conn.execute(
                """
                create table file_accesses (
                  session_id text,
                  seq int,
                  path_key text,
                  path_raw text,
                  operation text,
                  status text,
                  tool_name text,
                  tool_use_id text,
                  evidence_quote text
                )
                """
            )
            conn.execute("create table events (session_id text, seq int, event_name text, tool_name text, tool_use_id text)")
            conn.execute("create table tool_calls (session_id text, seq int, tool_call_id text)")
            conn.execute(
                """
                create table risk_events (
                  session_id text,
                  event_seq int,
                  risk_event_id text,
                  status text,
                  decision text,
                  approval_state text,
                  command_hash text,
                  preview text
                )
                """
            )
            conn.execute(
                """
                create table dream_artifacts (
                  dream_artifact_id text primary key,
                  dream_run_id text,
                  stage_run_id text,
                  session_id text,
                  artifact_kind text,
                  artifact_role text,
                  path text,
                  sha256 text,
                  byte_count int,
                  char_count int,
                  created_at text,
                  metadata_json text
                )
                """
            )
            conn.execute(
                """
                insert into sessions(session_id, project_id, client_type, last_event_seq)
                values (?, ?, ?, ?)
                """,
                ("session-1", "demo", "codex", 3),
            )
        context = self._build_skeleton_context()
        context = DreamV2Context(
            conn=conn,
            dream_run_id="dream-run",
            session_id="session-1",
            event_from=1,
            event_to=3,
            run_dir=Path("/tmp/run"),
            dry_run=True,
            clock=_DummyClock(),
            file_system=default_file_system(),
            db_provider=_DummyDbProvider(),
        )
        base_stage = self._build_skeleton_stage_context("dream_narrative", 1, "stage-dream_narrative")

        old_env = os.environ.get("AGENT_MEMORY_DREAM_V2_MOCK")
        os.environ["AGENT_MEMORY_DREAM_V2_MOCK"] = "1"
        try:
            narrative = run_narrative_stage(
                conn=context.conn,
                context=context,
                stage_context=base_stage,
                event_rows=[
                    {
                        "seq": 1,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "user",
                        "prompt": "Prompt 1",
                        "last_assistant_message": "Assistant 1",
                        "tool_name": None,
                    },
                ],
                session={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                prompt_text="prompt",
                prior_dream_summary="summary",
                current_handover="handover",
                semantic_context={"entities": [], "relations": []},
                runner="codex",
                runner_model=None,
                reuse_from_dream_run_id=None,
                runner_timeout=120,
                dry_run=True,
            )
            semantic = run_semantic_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("semantic_extraction", 2, "stage-semantic"),
                current={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                events=[
                    {
                        "seq": 1,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "user",
                        "prompt": "Prompt 1",
                        "last_assistant_message": "Assistant 1",
                        "tool_name": None,
                    },
                    {
                        "seq": 2,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "assistant",
                        "prompt": "Prompt 2",
                        "last_assistant_message": "Assistant 2",
                        "tool_name": None,
                    },
                ],
                narrative_response="The session implemented Dream Pipeline 2.0 as the canonical memory pipeline.",
                semantic_context={"entities": [], "relations": []},
                runner="codex",
                runner_model=None,
                reuse_from_dream_run_id=None,
                runner_timeout=120,
                args=None,
            )
            window = run_window_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("window", 0, "stage-window"),
                event_rows=[
                    {
                        "seq": 1,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "user",
                        "prompt": "Prompt 1",
                        "last_assistant_message": "Assistant 1",
                        "tool_name": None,
                    },
                    {
                        "seq": 2,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "assistant",
                        "prompt": "Prompt 2",
                        "last_assistant_message": "Assistant 2",
                        "tool_name": None,
                    },
                ],
                current={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                previous_summary="summary",
                semantic_context={"entities": [], "relations": []},
            )
            operational = run_operational_extraction_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("operational_extraction", 4, "stage-operational"),
            )
            candidate = run_candidate_search_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("candidate_search", 5, "stage-candidate"),
                semantic_payload={"entities": []},
                args=type(
                    "Args",
                    (),
                    {
                        "sync_neo4j": False,
                        "neo4j_batch_size": 50,
                        "neo4j_timeout": 60,
                    },
                )(),
            )
            reconciliation = run_reconciliation_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("reconciliation", 6, "stage-reconciliation"),
                semantic_payload=semantic["semantic_payload"],
                candidates={
                    "candidates": {
                        "entity-main-task": [],
                    },
                },
                runner="codex",
                runner_model=None,
                semantic_id_map=semantic["semantic_id_map"],
                reuse_from_dream_run_id=None,
                runner_timeout=120,
                args=None,
            )
            persistence = run_persistence_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("persistence", 7, "stage-persistence"),
                session={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                reconciliation_payload=reconciliation["reconciliation_payload"],
                semantic_payload=semantic["semantic_payload"],
                dry_run=True,
                runner="codex",
                runner_model=None,
                args=type(
                    "Args",
                    (),
                    {
                        "sync_neo4j": False,
                        "runner_timeout": 120,
                        "database": None,
                        "neo4j_batch_size": 200,
                        "neo4j_timeout": 60,
                        "uri": None,
                        "user": None,
                        "password_env": "AGENT_MEMORY_NEO4J_PASSWORD",
                    },
                )(),
            )
            audit = run_audit_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("audit", 8, "stage-audit"),
                session={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                semantic_payload=semantic["semantic_payload"],
                reconciliation_payload=reconciliation["reconciliation_payload"],
                operational={"file_changes": [], "pretool_audit_refs": []},
                candidates={"candidates": {}},
                persistence_result=persistence["persistence"],
                validation={"status": "succeeded"},
                dry_run=True,
                event_count=2,
            )
        finally:
            if old_env is None:
                del os.environ["AGENT_MEMORY_DREAM_V2_MOCK"]
            else:
                os.environ["AGENT_MEMORY_DREAM_V2_MOCK"] = old_env

        for payload in [window, narrative, semantic, operational, candidate, reconciliation, persistence, audit]:
            self.assertIn(payload["status"], {"migrated"})
            self.assertIn("stage_run_id", payload)
            self.assertIn("dream_run_id", payload)
            self.assertIn("session_id", payload)
            self.assertIn("artifact_path", payload)
            self.assertIn("event_from", payload)
            self.assertIn("event_to", payload)
            self.assertIsInstance(payload["artifact_path"], str)

        self.assertEqual(narrative["event_from"], 1)
        self.assertGreater(semantic["proposal_count"], 0)
        self.assertGreaterEqual(semantic["relation_count"], 0)
        self.assertGreaterEqual(reconciliation["decision_count"], 1)
        self.assertEqual(persistence["status"], "migrated")
        self.assertTrue(persistence["dry_run"])
        self.assertEqual(persistence["decisions_seen"], 1)
        self.assertGreater(audit["summary_length"], 0)

    def test_infra_adapter_file_system_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fs = default_file_system()

            txt = base / "a" / "b" / "value.txt"
            fs.write_text(txt, "hello")
            self.assertEqual(fs.read_text(txt), "hello")

            blob = base / "data.bin"
            fs.write_bytes(blob, b"\x00\x01")
            self.assertEqual(fs.read_bytes(blob), b"\x00\x01")

            self.assertFalse(fs.exists(base / "missing.txt"))

    def test_infra_adapter_command_runner_executes_command(self) -> None:
        runner = default_command_runner()
        result = runner.run([sys.executable, "-c", "print('v2-adapter-ok')"])
        self.assertEqual(result.returncode, 0)
        self.assertIn("v2-adapter-ok", result.stdout)

    def test_infra_adapter_text_tools_limits_and_redacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            text = base / "long.txt"
            long_text = "x" * 500
            text.write_text(long_text, encoding="utf-8")

            text_tools = default_text_tools()
            limited = text_tools.read_text_limited(text, 120)
            self.assertTrue(limited.startswith("x" * 120))
            self.assertIn("...[truncated]", limited)

            with_marker = text_tools.redact_embedded_context_artifacts(
                "lead\nProject Memory Reference memory/memories/projects/demo\nafter"
            )
            self.assertIn("embedded memory/handover artifact omitted", with_marker)

            without_marker = text_tools.redact_embedded_context_artifacts("plain conversation text")
            self.assertEqual(without_marker, "plain conversation text")

    def test_semantic_stage_falls_back_when_runner_returns_invalid_json(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text not null,
                  session_id text not null,
                  stage_name text not null,
                  stage_order int not null,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )
            conn.execute(
                """
                create table dream_artifacts (
                  dream_artifact_id text primary key,
                  dream_run_id text,
                  stage_run_id text,
                  session_id text,
                  artifact_kind text,
                  artifact_role text,
                  path text,
                  sha256 text,
                  byte_count int,
                  char_count int,
                  created_at text,
                  metadata_json text
                )
                """
            )

        context = self._build_skeleton_context()
        context = DreamV2Context(
            conn=conn,
            dream_run_id="dream-run",
            session_id="session-1",
            event_from=1,
            event_to=2,
            run_dir=Path("/tmp/run"),
            dry_run=True,
            clock=_DummyClock(),
            file_system=default_file_system(),
            db_provider=_DummyDbProvider(),
        )

        with patch("agent_context_engine.application.dreaming.v2_refactor.stages.semantic.invoke_runner", return_value=("not-json", {})):
            semantic = run_semantic_stage(
                conn=conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("semantic_extraction", 2, "stage-semantic"),
                current={"session_id": "session-1", "project_id": "demo", "client_type": "codex"},
                events=[
                    {
                        "seq": 1,
                        "recorded_at": "2026-06-10T10:00:00Z",
                        "event_name": "user",
                        "prompt": "Prompt 1",
                        "last_assistant_message": "Assistant 1",
                        "tool_name": None,
                    },
                ],
                narrative_response="A fallback test should trigger deterministic semantic output.",
                semantic_context={"entities": [], "relations": []},
                runner="codex",
                runner_model=None,
                reuse_from_dream_run_id=None,
                runner_timeout=120,
                args=None,
            )
        self.assertEqual(semantic["status"], "migrated")
        self.assertTrue(semantic["semantic_meta"].get("fallback_to_deterministic_semantic"))
        self.assertTrue(semantic["semantic_validation"]["ok"])

    def test_invoke_runner_raises_for_nonzero_command_exit(self) -> None:
        class _FailedRunResult:
            returncode = 1
            stdout = ""
            stderr = "command failed"

        class _FailedRunner:
            def run(self, *_: object, **__: object) -> _FailedRunResult:
                return _FailedRunResult()

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.md"
            with self.assertRaises(RuntimeError) as ctx:
                run_v2_invoke_runner(
                    "codex",
                    None,
                    "ignore",
                    out,
                    60,
                    command_runner=_FailedRunner(),
                    root_path=tmp,
                    now_fn=_DummyClock().utc_now,
                    monotonic_fn=lambda: 1.23,
                    read_text_limited_fn=lambda *_args: "",
                    write_text_fn=lambda *_path: None,
                    base_env={},
                    max_output_bytes=dream_v2.MAX_STAGE_OUTPUT_BYTES,
                    mock_enabled=False,
                    semantic_schema_version=dream_v2.SEMANTIC_SCHEMA_VERSION,
                    reconciliation_schema_version=dream_v2.RECONCILIATION_SCHEMA_VERSION,
                    json_dumps_fn=dream_v2._json_dumps,
                )
            self.assertIn("v2 LLM stage failed", str(ctx.exception))

    def test_invoke_runner_parses_cursor_json_output_and_usage(self) -> None:
        class _CursorRunResult:
            returncode = 0
            stdout = json.dumps(
                {
                    "type": "result",
                    "result": "Cursor dream output",
                    "usage": {
                        "inputTokens": 123,
                        "outputTokens": 45,
                        "cacheReadTokens": 10,
                    },
                }
            )
            stderr = ""

        class _CursorRunner:
            def run(self, *_: object, **__: object) -> _CursorRunResult:
                return _CursorRunResult()

        writes: dict[str, str] = {}

        def _write_text(path: str | Path, content: str) -> None:
            writes[str(path)] = content

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out.md"
            text, metadata = run_v2_invoke_runner(
                "cursor",
                None,
                "ignore",
                out,
                60,
                command_runner=_CursorRunner(),
                root_path=tmp,
                now_fn=_DummyClock().utc_now,
                monotonic_fn=lambda: 1.23,
                read_text_limited_fn=lambda *_args: "",
                write_text_fn=_write_text,
                base_env={},
                max_output_bytes=dream_v2.MAX_STAGE_OUTPUT_BYTES,
                mock_enabled=False,
                semantic_schema_version=dream_v2.SEMANTIC_SCHEMA_VERSION,
                reconciliation_schema_version=dream_v2.RECONCILIATION_SCHEMA_VERSION,
                json_dumps_fn=dream_v2._json_dumps,
            )
        self.assertEqual(text, "Cursor dream output")
        self.assertEqual(metadata["token_usage"]["prompt_tokens"], 123)
        self.assertEqual(metadata["token_usage"]["cached_prompt_tokens"], 10)
        self.assertEqual(metadata["token_usage"]["completion_tokens"], 45)
        self.assertEqual(metadata["token_usage"]["total_tokens"], 168)
        self.assertTrue(metadata["token_usage_available"])
        self.assertEqual(writes[str(out)], "Cursor dream output\n")

    def test_apply_semantic_guardrails_drops_low_signal_overreach(self) -> None:
        payload = {
            "entities": [
                {
                    "proposal_id": "entity-trprcbt-mcp",
                    "type": "project",
                    "name": "trprcbt-mcp",
                    "aliases": ["trprcbt-mcp"],
                    "summary": "Project context",
                    "confidence": 0.93,
                    "evidence": [{"source": "conversation", "event_seq": 1, "quote": "support for the `trprcbt-mcp` project"}],
                    "review_required": False,
                    "review_reason": None,
                },
                {
                    "proposal_id": "entity-english-preference",
                    "type": "preference",
                    "name": "English for this project context",
                    "aliases": [],
                    "summary": "Language preference",
                    "confidence": 0.9,
                    "evidence": [{"source": "conversation", "event_seq": 2, "quote": "Keep the interaction in English for this project context."}],
                    "review_required": False,
                    "review_reason": None,
                },
                {
                    "proposal_id": "entity-await-task",
                    "type": "task",
                    "name": "Wait for the user to specify the actual task",
                    "aliases": [],
                    "summary": "Pending task",
                    "confidence": 0.97,
                    "evidence": [{"source": "conversation", "event_seq": 2, "quote": "Wait for the user to specify the actual task."}],
                    "review_required": False,
                    "review_reason": None,
                },
            ],
            "relations": [],
            "schema_proposals": [],
        }
        events = [
            {"seq": 1, "prompt": "hi"},
            {"seq": 2, "response": "Hallo! Wie kann ich dir heute helfen — am `trprcbt-mcp`-Projekt oder etwas anderem?"},
        ]

        guarded = apply_semantic_guardrails(payload, events=events)

        self.assertTrue(guarded["_low_signal_window"])
        self.assertEqual(guarded["_signal_strength"], "low")
        self.assertEqual(len(guarded["entities"]), 1)
        project = guarded["entities"][0]
        self.assertEqual(project["type"], "project")
        self.assertTrue(project["review_required"])
        self.assertEqual(project["evidence"][0]["quote"], "trprcbt-mcp")
        self.assertEqual(guarded["relations"], [])
        self.assertEqual(guarded["schema_proposals"], [])

    def test_apply_reconciliation_guardrails_defers_review_required_proposals(self) -> None:
        semantic_payload = {
            "entities": [
                {
                    "proposal_id": "entity-trprcbt-mcp",
                    "type": "project",
                    "name": "trprcbt-mcp",
                    "review_required": True,
                    "review_reason": "Signal strength `low` is below the minimum `medium` required for durable `project` persistence.",
                }
            ],
            "relations": [],
        }
        payload = {
            "schema_version": dream_v2.RECONCILIATION_SCHEMA_VERSION,
            "dream_run_id": "dream-1",
            "session_id": "session-1",
            "decisions": [
                {
                    "decision_id": "decision-trprcbt-mcp",
                    "proposal_id": "entity-trprcbt-mcp",
                    "action": "create_entity",
                    "reason": "create",
                    "human_summary": "Create entity",
                    "review_required": False,
                    "review_reason": None,
                }
            ],
        }

        guarded = apply_reconciliation_guardrails(payload, semantic_payload=semantic_payload)

        self.assertEqual(guarded["decisions"][0]["action"], "defer_for_review")
        self.assertTrue(guarded["decisions"][0]["review_required"])
        self.assertIn("Signal strength", guarded["decisions"][0]["review_reason"])

    def test_normalization_stage_contract_is_dry_run_safe(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text not null,
                  session_id text not null,
                  stage_name text not null,
                  stage_order int not null,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )
            conn.execute(
                """
                create table dream_artifacts (
                  dream_artifact_id text primary key,
                  dream_run_id text,
                  stage_run_id text,
                  session_id text,
                  artifact_kind text,
                  artifact_role text,
                  path text,
                  sha256 text,
                  byte_count int,
                  char_count int,
                  created_at text,
                  metadata_json text
                )
                """
            )

        context = DreamV2Context(
            conn=conn,
            dream_run_id="dream-run",
            session_id="session-1",
            event_from=1,
            event_to=3,
            run_dir=Path("/tmp/run"),
            dry_run=True,
            clock=_DummyClock(),
            file_system=default_file_system(),
            db_provider=_DummyDbProvider(),
        )

        with patch("agent_context_engine.application.dreaming.normalization.normalize_semantic_payload_from_db") as normalize_payload:
            normalize_payload.return_value = {
                "schema_version": "semantic_proposals.v2",
                "dream_run_id": "dream-run",
                "session_id": "session-1",
                "source_event_range": {"start_seq": 1, "end_seq": 3},
                "entities": [],
                "relations": [],
                "schema_proposals": [],
            }
            normalization = run_normalization_stage(
                conn=context.conn,
                context=context,
                stage_context=self._build_skeleton_stage_context("normalization", 3, "stage-normalization"),
                semantic_payload={"entities": [], "relations": []},
                dry_run=True,
            )

        self.assertEqual(normalization["status"], "migrated")
        self.assertEqual(normalization["event_from"], 1)
        self.assertEqual(normalization["event_to"], 3)
        self.assertIsInstance(normalization["artifact_path"], str)
        self.assertIn("entities", normalization["semantic_payload"])

    def test_repository_wrapper_returns_rows(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("create table dream_runs (dream_run_id text primary key, session_id text, status text, started_at text, finished_at text)")
            conn.execute("create table sessions (session_id text primary key, project_id text, last_event_seq int)")
            conn.execute(
                "create table dream_stage_runs (stage_run_id text primary key, dream_run_id text, stage_name text, stage_order int, status text)"
            )
            conn.execute(
                "create table reconciliation_decisions (reconciliation_decision_id text primary key, dream_run_id text, semantic_proposal_id text)"
            )
            conn.execute("create table dream_artifacts (dream_artifact_id text primary key, dream_run_id text, session_id text, artifact_kind text)")
            conn.execute("insert into dream_runs(dream_run_id, session_id, status, started_at) values (?, ?, ?, ?)", ("run-1", "s-1", "succeeded", "2026-06-10T10:00:00Z"))
            conn.execute("insert into sessions(session_id, project_id, last_event_seq) values (?, ?, ?)", ("s-1", "demo", 3))
            conn.execute("insert into dream_stage_runs(stage_run_id, dream_run_id, stage_name, stage_order, status) values (?, ?, ?, ?, ?)", ("stage-1", "run-1", "window", 0, "succeeded"))
            conn.execute("insert into reconciliation_decisions(reconciliation_decision_id, dream_run_id, semantic_proposal_id) values (?, ?, ?)", ("dec-1", "run-1", "ent-1"))
            conn.execute("insert into dream_artifacts(dream_artifact_id, dream_run_id, session_id, artifact_kind) values (?, ?, ?, ?)", ("art-1", "run-1", "s-1", "prompt_manifest"))

        repo = DreamV2Repository(conn)
        row = repo.fetch_session("s-1")
        by_selector = repo.fetch_session_by_selector("s-1")
        run = repo.fetch_dream_run("run-1")
        run_runs = repo.list_dream_runs_for_session("s-1")
        latest_run = repo.latest_dream_run_for_session("s-1")
        stage_row = repo.fetch_stage_run("stage-1")
        stage_rows = repo.list_stage_runs_for_dream("run-1")
        decision_rows = repo.list_reconciliation_decisions("run-1")
        artifact_rows = repo.list_session_artifacts("s-1")

        self.assertIsNotNone(row)
        self.assertIsNotNone(by_selector)
        self.assertIsNotNone(run)
        self.assertIsNotNone(latest_run)
        self.assertIsNotNone(stage_row)
        self.assertEqual(len(run_runs), 1)
        self.assertEqual(len(stage_rows), 1)
        self.assertEqual(len(decision_rows), 1)
        self.assertEqual(len(artifact_rows), 1)
        self.assertEqual(row[0], "s-1")
        self.assertEqual(by_selector[0], "s-1")

    def test_repository_read_helpers_for_context_and_reuse(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table sessions (
                  session_id text primary key,
                  dream_status text
                )
                """
            )
            conn.execute(
                """
                create table dream_runs (
                  dream_run_id text primary key,
                  session_id text,
                  status text,
                  started_at text,
                  finished_at text,
                  output_memory_paths_json text
                )
                """
            )
            conn.execute(
                """
                create table summaries (
                  session_id text primary key,
                  summary_path text
                )
                """
            )
            conn.execute(
                """
                create table semantic_entities (
                  entity_key text,
                  entity_type text,
                  name text,
                  summary text,
                  confidence real,
                  source_session_id text,
                  updated_at text
                )
                """
            )
            conn.execute(
                """
                create table semantic_relations (
                  relation_key text,
                  relation_type text,
                  source_entity_key text,
                  target_entity_key text,
                  summary text,
                  confidence real,
                  source_session_id text,
                  updated_at text
                )
                """
            )
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text,
                  stage_name text,
                  status text,
                  parsed_output_path text,
                  started_at text
                )
                """
            )
            conn.execute("insert into sessions(session_id) values ('session-1')")
            conn.execute(
                """
                insert into dream_runs(
                  dream_run_id, session_id, status, started_at, finished_at, output_memory_paths_json
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    "run-1",
                    "session-1",
                    "succeeded",
                    "2026-06-10T09:00:00Z",
                    "2026-06-10T09:00:05Z",
                    json.dumps(["artifacts/run-1-summary.md", "artifacts/run-1-notes.json"]),
                ),
            )
            conn.execute("insert into summaries(session_id, summary_path) values ('session-1', 'handover/session-1/summary.md')")
            conn.execute(
                """
                insert into semantic_entities(
                  entity_key, entity_type, name, summary, confidence, source_session_id, updated_at
                ) values
                ('ent:1', 'person', 'Alice', 'lead', 0.81, 'session-1', '2026-06-10T09:00:01Z'),
                ('ent:2', 'feature', 'Search', 'topic', 0.67, 'session-1', '2026-06-10T09:00:02Z')
                """
            )
            conn.execute(
                """
                insert into semantic_relations(
                  relation_key, relation_type, source_entity_key, target_entity_key, summary, confidence, source_session_id, updated_at
                ) values
                ('ent:1>ent:2', 'discusses', 'ent:1', 'ent:2', 'Alice discusses Search', 0.75, 'session-1', '2026-06-10T09:00:03Z')
                """
            )
            conn.execute(
                """
                insert into dream_stage_runs(
                  stage_run_id, dream_run_id, stage_name, status, parsed_output_path, started_at
                ) values (?, ?, ?, 'succeeded', ?, ?)
                """,
                ("stage-1", "run-1", "semantic_extraction", "artifacts/semantic.json", "2026-06-10T09:00:00Z"),
            )

        repo = DreamV2Repository(conn)
        self.assertEqual(
            repo.fetch_latest_succeeded_dream_output_memory_paths("session-1"),
            ["artifacts/run-1-summary.md", "artifacts/run-1-notes.json"],
        )
        self.assertEqual(repo.fetch_latest_session_handover_path("session-1"), "handover/session-1/summary.md")

        entities = repo.list_session_semantic_entities("session-1")
        self.assertEqual(len(entities), 2)
        self.assertEqual({row["entity_key"] for row in entities}, {"ent:1", "ent:2"})

        relations = repo.list_session_semantic_relations("session-1")
        self.assertEqual(len(relations), 1)
        self.assertEqual(relations[0]["relation_type"], "discusses")

        reused = repo.fetch_succeeded_stage_run("run-1", "semantic_extraction")
        self.assertIsNotNone(reused)
        self.assertEqual(reused["parsed_output_path"], "artifacts/semantic.json")

    def test_repository_resolves_session_selector(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table sessions (
                  session_id text primary key,
                  thread_name text,
                  last_event_at text,
                  started_at text
                )
                """
            )
            conn.execute(
                """
                create table events (
                  session_id text,
                  prompt text,
                  last_assistant_message text,
                  tool_response_text text
                )
                """
            )
            conn.execute(
                "insert into sessions(session_id, thread_name, last_event_at, started_at) values (?, ?, ?, ?)",
                ("s-abc", "alpha thread", "2026-06-10T10:05:00Z", "2026-06-10T10:00:00Z"),
            )
            conn.execute(
                "insert into sessions(session_id, thread_name, last_event_at, started_at) values (?, ?, ?, ?)",
                ("s-def", "beta thread", "2026-06-10T09:55:00Z", "2026-06-10T09:50:00Z"),
            )
            conn.execute("insert into events(session_id, prompt, last_assistant_message, tool_response_text) values (?, ?, ?, ?)", ("s-def", "hello from context", None, None))
            conn.execute("insert into events(session_id, prompt, last_assistant_message, tool_response_text) values (?, ?, ?, ?)", ("s-def", None, "assistant follows", None))
        repo = DreamV2Repository(conn)
        by_prefix = repo.resolve_session_selector("s-a")
        by_thread = repo.resolve_session_selector("alpha")
        by_event = repo.resolve_session_selector("hello")
        missing = repo.resolve_session_selector("zzz")

        self.assertIsNotNone(by_prefix)
        self.assertEqual(by_prefix["session_id"], "s-abc")
        self.assertIsNotNone(by_thread)
        self.assertEqual(by_thread["session_id"], "s-abc")
        self.assertIsNotNone(by_event)
        self.assertEqual(by_event["session_id"], "s-def")
        self.assertIsNone(missing)

    def test_repository_aggregates_stage_metrics(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text,
                  status text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int
                )
                """
            )
            conn.execute(
                """
                insert into dream_stage_runs(
                  stage_run_id, dream_run_id, status, prompt_tokens, cached_prompt_tokens,
                  completion_tokens, reasoning_tokens, total_tokens
                ) values
                ('s1', 'run-1', 'succeeded', 10, 2, 30, 4, 36),
                ('s2', 'run-1', 'failed', 20, 3, 40, 1, 64)
                """
            )
        repo = DreamV2Repository(conn)
        metrics = repo.aggregate_stage_metrics("run-1")
        self.assertEqual(
            metrics,
            {
                "prompt_tokens": 30,
                "cached_prompt_tokens": 5,
                "completion_tokens": 70,
                "reasoning_tokens": 5,
                "total_tokens": 100,
            },
        )

    def test_repository_queries_for_dream_selection_and_repair_candidates(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table sessions (
                  session_id text primary key,
                  last_event_seq int,
                  last_dream_event_seq int,
                  dream_status text,
                  last_event_at text
                )
                """
            )
            conn.execute(
                """
                create table dream_runs (
                  dream_run_id text primary key,
                  session_id text,
                  status text,
                  started_at text
                )
                """
            )
            conn.execute(
                """
                create table graph_artifacts (
                  dream_run_id text,
                  artifact_type text,
                  status text
                )
                """
            )
            conn.execute(
                "insert into sessions(session_id, last_event_seq, last_dream_event_seq, dream_status, last_event_at) values (?, ?, ?, ?, ?)",
                ("s-due", 10, 2, "dream_pending", "2026-06-10T10:00:00Z"),
            )
            conn.execute(
                "insert into sessions(session_id, last_event_seq, last_dream_event_seq, dream_status, last_event_at) values (?, ?, ?, ?, ?)",
                ("s-fresh", 9, 8, "dreamed", "2026-06-10T10:05:00Z"),
            )
            conn.execute(
                "insert into sessions(session_id, last_event_seq, last_dream_event_seq, dream_status, last_event_at) values (?, ?, ?, ?, ?)",
                ("s-repair", 20, 5, "failed", "2026-06-10T09:50:00Z"),
            )
            conn.execute(
                "insert into dream_runs(dream_run_id, session_id, status, started_at) values (?, ?, ?, ?)",
                ("run-ok", "s-due", "running", "2026-06-10T09:00:00Z"),
            )
            conn.execute(
                "insert into dream_runs(dream_run_id, session_id, status, started_at) values (?, ?, ?, ?)",
                ("run-repair", "s-repair", "succeeded", "2026-06-10T09:10:00Z"),
            )
            conn.execute(
                "insert into graph_artifacts(dream_run_id, artifact_type, status) values (?, ?, ?)",
                ("run-repair", "patch", "invalid"),
            )
        repo = DreamV2Repository(conn)
        pending = repo.list_sessions_pending_dream()
        repair = repo.list_sessions_missing_graph_artifacts()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["session_id"], "s-due")
        self.assertEqual(len(repair), 1)
        self.assertEqual(repair[0]["session_id"], "s-repair")

    def test_repository_lists_missing_patch_dream_runs(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_runs (
                  dream_run_id text primary key,
                  session_id text,
                  status text,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  started_at text
                )
                """
            )
            conn.execute("create table graph_artifacts (dream_run_id text, artifact_type text, status text)")
            conn.execute("insert into dream_runs(dream_run_id, session_id, status, input_event_seq_from, input_event_seq_to, started_at) values (?, ?, ?, ?, ?, ?)", ("run-valid", "session-a", "succeeded", 0, 2, "2026-06-10T10:00:00Z"))
            conn.execute("insert into dream_runs(dream_run_id, session_id, status, input_event_seq_from, input_event_seq_to, started_at) values (?, ?, ?, ?, ?, ?)", ("run-missing-1", "session-a", "succeeded", 3, 5, "2026-06-10T10:01:00Z"))
            conn.execute("insert into dream_runs(dream_run_id, session_id, status, input_event_seq_from, input_event_seq_to, started_at) values (?, ?, ?, ?, ?, ?)", ("run-missing-2", "session-a", "succeeded", 6, 8, "2026-06-10T10:02:00Z"))
            conn.execute("insert into dream_runs(dream_run_id, session_id, status, input_event_seq_from, input_event_seq_to, started_at) values (?, ?, ?, ?, ?, ?)", ("run-failed", "session-a", "failed", 9, 10, "2026-06-10T10:03:00Z"))
            conn.execute("insert into graph_artifacts(dream_run_id, artifact_type, status) values (?, ?, ?)", ("run-valid", "patch", "valid"))
            conn.execute("insert into graph_artifacts(dream_run_id, artifact_type, status) values (?, ?, ?)", ("run-missing-1", "patch", "invalid"))
            conn.execute("insert into graph_artifacts(dream_run_id, artifact_type, status) values (?, ?, ?)", ("run-failed", "patch", "invalid"))

        repo = DreamV2Repository(conn)
        rows = repo.list_missing_patch_dream_runs("session-a")
        self.assertEqual([row["dream_run_id"] for row in rows], ["run-missing-1", "run-missing-2"])

    def test_repair_missing_graph_patches_respects_limit_and_collects_paths(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table sessions (
                  session_id text primary key
                )
                """
            )
            conn.execute(
                """
                create table dream_runs (
                  dream_run_id text primary key,
                  session_id text,
                  status text,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  started_at text
                )
                """
            )
            conn.execute("create table graph_artifacts (dream_run_id text, artifact_type text, status text)")
            conn.execute("insert into sessions(session_id) values ('session-a')")
            conn.execute(
                "insert into dream_runs(dream_run_id, session_id, status, input_event_seq_from, input_event_seq_to, started_at) values (?, ?, ?, ?, ?, ?)",
                ("run-a", "session-a", "succeeded", 1, 10, "2026-06-10T10:00:00Z"),
            )
            conn.execute(
                "insert into dream_runs(dream_run_id, session_id, status, input_event_seq_from, input_event_seq_to, started_at) values (?, ?, ?, ?, ?, ?)",
                ("run-b", "session-a", "succeeded", 11, 20, "2026-06-10T10:05:00Z"),
            )
        session = conn.execute("select * from sessions where session_id='session-a'").fetchone()
        repo = DreamV2Repository(conn)

        calls: list[tuple[str, str]] = []

        def _fake_patch(
            patch_conn: sqlite3.Connection,
            patch_session: sqlite3.Row,
            dream_row: sqlite3.Row,
            runner: str,
            runner_model: str | None,
            timeout: int,
            args: argparse.Namespace | None,
        ) -> tuple[list[str], sqlite3.Connection]:
            calls.append((dream_row["dream_run_id"], runner))
            return [f"patch/{dream_row['dream_run_id']}.json"], patch_conn

        with patch("agent_context_engine.application.dreaming.v2_refactor.services.graph_repair.ensure_graph_patch_for_dream", side_effect=_fake_patch):
            repaired, paths, returned_conn = repair_missing_graph_patches(
                conn,
                repo,
                session,
                repair_limit=1,
                runner="codex",
                runner_model="gpt-5",
                timeout=1800,
                args=None,
            )

        self.assertEqual(repaired, 1)
        self.assertEqual(paths, ["patch/run-a.json"])
        self.assertEqual(calls, [("run-a", "codex")])
        self.assertIs(returned_conn, conn)

    def test_repository_session_state_updates_and_summary_upsert(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute("create table sessions (session_id text primary key, dream_status text, dream_runner_used text, dream_runner_status text, last_dream_event_seq int, last_dream_at text, last_dream_run_id text, session_brief text, summary_status text, last_summary_event_seq int, last_summary_at text)")
            conn.execute("create table dream_runs (dream_run_id text primary key, status text, pipeline_status text, finished_at text, output_summary_path text, output_memory_paths_json text, failed_stage text, error_message text)")
            conn.execute("create table dream_stage_runs (stage_run_id text primary key, dream_run_id text, status text, stage_order int, stage_name text)")
            conn.execute("create table summaries (session_id text primary key, summary_path text, created_at text, input_event_seq_to int, input_event_count int, summary_kind text)")
            conn.execute("insert into sessions(session_id) values ('session-1')")
            conn.execute("insert into dream_runs(dream_run_id, status, pipeline_status) values ('run-1', 'running', 'running')")

        repo = DreamV2Repository(conn)
        repo.update_session_dream_state(
            "session-1",
            dream_status="dreaming",
            dream_runner_used="codex",
            dream_runner_status="running",
            last_dream_event_seq=12,
        )
        repo.update_session_dream_state(
            "session-1",
            dream_status="dreamed",
            last_dream_event_seq=99,
            last_dream_at="2026-06-10T11:00:00Z",
            last_dream_run_id="run-1",
            session_brief="keep me",
            dream_runner_status="succeeded",
        )
        repo.update_session_dream_state(
            "session-1",
            dream_status="dreamed",
            session_brief="should_not_replace",
            keep_existing_session_brief=True,
        )
        session = conn.execute("select * from sessions where session_id='session-1'").fetchone()
        self.assertEqual(session["dream_status"], "dreamed")
        self.assertEqual(session["dream_runner_used"], "codex")
        self.assertEqual(session["dream_runner_status"], "succeeded")
        self.assertEqual(session["last_dream_event_seq"], 99)
        self.assertEqual(session["last_dream_at"], "2026-06-10T11:00:00Z")
        self.assertEqual(session["last_dream_run_id"], "run-1")
        self.assertEqual(session["session_brief"], "keep me")

        repo.upsert_session_dream_summary(
            "session-1",
            summary_path="summary.md",
            created_at="2026-06-10T11:00:00Z",
            input_event_seq_to=12,
            input_event_count=5,
        )
        summary = conn.execute("select * from summaries where session_id='session-1'").fetchone()
        self.assertEqual(summary["summary_path"], "summary.md")
        self.assertEqual(summary["summary_kind"], "dream_pipeline_v2")
        self.assertEqual(summary["input_event_seq_to"], 12)
        self.assertEqual(summary["input_event_count"], 5)

        repo.upsert_session_dream_summary(
            "session-1",
            summary_path="summary-2.md",
            created_at="2026-06-10T12:00:00Z",
            input_event_seq_to=22,
            input_event_count=9,
        )
        summary = conn.execute("select * from summaries where session_id='session-1'").fetchone()
        self.assertEqual(summary["summary_path"], "summary-2.md")
        self.assertEqual(summary["created_at"], "2026-06-10T12:00:00Z")
        self.assertEqual(summary["input_event_seq_to"], 22)

    def test_runtime_stage_helpers_preserve_stage_contract(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text not null,
                  session_id text not null,
                  stage_name text not null,
                  stage_order int not null,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )
            conn.execute(
                """
                insert into dream_stage_runs (
                  stage_run_id, dream_run_id, session_id, stage_name, stage_order,
                  runner, model, status, started_at, input_event_seq_from, input_event_seq_to,
                  created_by
                ) values (?, ?, ?, ?, ?, ?, ?, 'running', ?, 1, 2, 'unit_test')
                """,
                (
                    "seed",
                    "dream-test",
                    "session-test",
                    "window",
                    0,
                    "codex",
                    "gpt-5",
                    "2026-06-10T10:00:00Z",
                ),
            )

        stage_id, _, started_mono = stage_runtime.stage_start(
            conn,
            dream_run_id="dream-test",
            session_id="session-test",
            stage_name="semantic_extraction",
            stage_order=2,
            runner="codex",
            model="gpt-5",
            event_from=5,
            event_to=7,
        )

        self.assertEqual(stage_id, "stage_dream-test_02_semantic_extraction")
        row = conn.execute("select status from dream_stage_runs where stage_run_id = ?", (stage_id,)).fetchone()
        self.assertEqual(row[0], "running")

        stage_runtime.stage_finish(
            conn,
            stage_run_id=stage_id,
            started_mono=started_mono,
            status="succeeded",
            prompt_path=Path("/tmp/prompt.txt"),
            raw_output_path=Path("/tmp/raw.md"),
            parsed_output_path=Path("/tmp/parsed.json"),
            artifact_path=Path("/tmp/artifact.bin"),
            metadata={"token_usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}},
            validation={"ok": True},
        )
        finished = conn.execute(
            "select status, prompt_tokens, completion_tokens, total_tokens, metadata_json, validation_json, artifact_path from dream_stage_runs where stage_run_id = ?",
            (stage_id,),
        ).fetchone()
        self.assertIsNotNone(finished)
        self.assertEqual(finished["status"], "succeeded")
        self.assertEqual(finished["prompt_tokens"], 11)
        self.assertEqual(finished["completion_tokens"], 7)
        self.assertEqual(finished["total_tokens"], 18)
        self.assertEqual(finished["artifact_path"], "/tmp/artifact.bin")
        self.assertEqual(json.loads(finished["metadata_json"]), {"token_usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}})
        self.assertEqual(json.loads(finished["validation_json"]), {"ok": True})

    def test_runtime_stage_finish_records_error_on_failed_stage(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        with conn:
            conn.execute(
                """
                create table dream_stage_runs (
                  stage_run_id text primary key,
                  dream_run_id text not null,
                  session_id text not null,
                  stage_name text not null,
                  stage_order int not null,
                  runner text,
                  model text,
                  status text,
                  started_at text,
                  finished_at text,
                  duration_ms int,
                  input_event_seq_from int,
                  input_event_seq_to int,
                  prompt_path text,
                  raw_output_path text,
                  parsed_output_path text,
                  artifact_path text,
                  metadata_json text,
                  validation_json text,
                  error_message text,
                  prompt_tokens int,
                  cached_prompt_tokens int,
                  completion_tokens int,
                  reasoning_tokens int,
                  total_tokens int,
                  created_by text
                )
                """
            )

        stage_id, _, started_mono = stage_runtime.stage_start(
            conn,
            dream_run_id="dream-test",
            session_id="session-test",
            stage_name="operational_extraction",
            stage_order=4,
            runner="codex",
            model="gpt-5",
            event_from=1,
            event_to=3,
        )
        error_text = "simulated failure"
        stage_runtime.stage_finish(
            conn,
            stage_run_id=stage_id,
            started_mono=started_mono,
            status="failed",
            error=error_text,
            metadata={},
            validation={"ok": False, "errors": [error_text]},
        )

        finished = conn.execute(
            "select status, error_message, validation_json from dream_stage_runs where stage_run_id = ?",
            (stage_id,),
        ).fetchone()
        self.assertEqual(finished["status"], "failed")
        self.assertEqual(finished["error_message"], error_text)
        self.assertEqual(json.loads(finished["validation_json"]), {"ok": False, "errors": [error_text]})

    def test_runtime_record_artifact_persists_hash_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory(dir=stage_runtime.root()) as tmp:
            tmp_path = Path(tmp)
            artifact_path = tmp_path / "artifact.json"
            artifact_path.write_text("{\"ok\":true}\n", encoding="utf-8")
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            with conn:
                conn.execute(
                    """
                    create table dream_artifacts (
                      dream_artifact_id text primary key,
                      dream_run_id text,
                      stage_run_id text,
                      session_id text,
                      artifact_kind text,
                      artifact_role text,
                      path text,
                      sha256 text,
                      byte_count int,
                      char_count int,
                      created_at text,
                      metadata_json text
                    )
                    """
                )

            stage_runtime.record_artifact(
                conn,
                dream_run_id="dream-test",
                stage_run_id="stage-test",
                session_id="session-test",
                artifact_kind="audit",
                artifact_role="summary",
                path=artifact_path,
                metadata={"k": "v"},
            )

            stored = conn.execute("select * from dream_artifacts where dream_run_id = 'dream-test'").fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(stored["path"], Path(tmp_path.name, "artifact.json").as_posix())
            self.assertEqual(json.loads(stored["metadata_json"]), {"k": "v"})
            self.assertTrue(stored["sha256"])
            self.assertGreater(stored["byte_count"], 0)
            self.assertGreater(stored["char_count"], 0)
