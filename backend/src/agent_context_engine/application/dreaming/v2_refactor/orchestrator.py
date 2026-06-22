"""Dreaming v2 orchestration implementation."""

from __future__ import annotations

import argparse
import atexit
import os
import traceback
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any, Callable


@dataclass(frozen=True)
class SessionRunnerDependencies:
    acquire_lock: Callable[..., Any]
    release_lock: Callable[[Any], None]
    connect: Callable[[], Any]
    repo_cls: type
    resolve_dream_runner: Callable[..., tuple[str, str | None]]
    next_undreamed_range: Callable[..., tuple[int, int] | None]
    now: Callable[[], str]
    safe_slug: Callable[[str], str]
    dream_dir: Callable[[], Path]
    detect_client_version: Callable[[str], str]
    transcript_mtime: Callable[[str | None], str | None]
    last_dream_summary: Callable[[Any, str], str]
    current_session_handover: Callable[[Any, str], str]
    same_session_semantic_context: Callable[[Any, str], dict[str, Any]]
    default_clock: Callable[[], Any]
    default_file_system: Callable[[], Any]
    default_db_provider: Callable[[], Any]
    run_artifacts_cls: type
    context_cls: type
    stage_context_cls: type
    build_dream_prompt: Callable[..., str]
    json_dumps: Callable[[Any], str]
    plain_event_window: Callable[[list[Any]], str]
    budget: Callable[[str, str, int, int], dict[str, Any]]
    run_window_stage: Callable[..., dict[str, Any]]
    run_narrative_stage: Callable[..., dict[str, Any]]
    run_semantic_stage: Callable[..., dict[str, Any]]
    run_normalization_stage: Callable[..., dict[str, Any]]
    run_operational_extraction_stage: Callable[..., dict[str, Any]]
    run_candidate_search_stage: Callable[..., dict[str, Any]]
    run_reconciliation_stage: Callable[..., dict[str, Any]]
    run_persistence_stage: Callable[..., dict[str, Any]]
    run_audit_stage: Callable[..., dict[str, Any]]
    root: Callable[[], Path]
    append_project_memory_ref: Callable[..., Path]
    extract_session_brief: Callable[[str], str]
    record_artifact: Callable[..., None]
    aggregate_stage_metrics: Callable[..., dict[str, int | None]]
    contiguous_dreamed_event_seq: Callable[..., int]


@dataclass(frozen=True)
class CommandRunnerDependencies:
    acquire_lock: Callable[..., Any]
    release_lock: Callable[[Any], None]
    connect: Callable[[], Any]
    repo_cls: type
    repair_missing_graph_patches: Callable[..., tuple[int, list[str], Any]]
    run_v2_for_session: Callable[[argparse.Namespace, str], int]


def run_v2_for_session(
    args: argparse.Namespace,
    session_id: str,
    *,
    deps: SessionRunnerDependencies,
) -> int:
    dream_lock = deps.acquire_lock("dream-session", session_id)
    if dream_lock is None:
        print(f"skipped {session_id}: dream already running")
        return 0
    atexit.register(deps.release_lock, dream_lock)
    conn = deps.connect()
    dream_run_id: str | None = None
    run_started_mono: float | None = None
    try:
        repo = deps.repo_cls(conn)
        current = repo.fetch_session(session_id)
        if current is None:
            print(f"No session found for selector: {session_id}")
            return 1
        requested_runner = getattr(args, "runner", "same-as-session")
        try:
            runner, runner_model = deps.resolve_dream_runner(
                current,
                requested_runner,
                getattr(args, "runner_model", None),
                conn=conn,
                map_deterministic_to_session=False,
                allow_standalone_deterministic=True,
            )
        except Exception as exc:  # noqa: BLE001
            with conn:
                repo.update_session_dream_state(session_id, dream_status="failed", dream_runner_status=str(exc))
            print(f"failed {session_id}: {exc}")
            return 1
        forced_event_from = getattr(args, "force_event_seq_from", None)
        forced_event_to = getattr(args, "force_event_seq_to", None)
        gap = (
            (int(forced_event_from), int(forced_event_to))
            if forced_event_from is not None and forced_event_to is not None
            else deps.next_undreamed_range(conn, current["session_id"], int(current["last_event_seq"]))
        )
        if gap is None:
            with conn:
                repo.update_session_dream_state(
                    current["session_id"],
                    dream_status="dreamed",
                    last_dream_event_seq=int(current["last_event_seq"]),
                    dream_runner_status="succeeded",
                )
            print(f"skipped {current['session_id']}: no undreamed events")
            return 0
        event_from, event_to = gap
        dry_run = bool(getattr(args, "dry_run", False))
        reuse_from_dream_run_id = getattr(args, "reuse_from_dream_run_id", None) if bool(getattr(args, "reuse_validated_stages", False)) else None
        if reuse_from_dream_run_id:
            prior = repo.fetch_dream_run(reuse_from_dream_run_id)
            if prior is None:
                raise RuntimeError(f"cannot reuse stages: prior dream run not found: {reuse_from_dream_run_id}")
            if prior["session_id"] != current["session_id"] or int(prior["input_event_seq_from"]) != event_from or int(prior["input_event_seq_to"]) != event_to:
                raise RuntimeError("cannot reuse stages: prior dream run event window does not match current rerun window")
        events = repo.list_events_for_session_range(current["session_id"], event_from, event_to)
        started = deps.now()
        run_started_mono = monotonic()
        dream_run_id = f"dream_{started.replace(':', '-').replace('+', 'Z')}_{deps.safe_slug(session_id)}_{os.getpid()}"
        run_dir = deps.dream_dir() / "v2" / "runs" / deps.safe_slug(dream_run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        with conn:
            repo.insert_dream_run(
                dream_run_id=dream_run_id,
                session_id=current["session_id"],
                client_type=current["client_type"],
                runner=runner,
                runner_version=deps.detect_client_version(runner),
                runner_model=runner_model,
                started_at=started,
                event_from=event_from,
                event_to=event_to,
                event_count=len(events),
                transcript_path=current["transcript_path"],
                transcript_mtime=deps.transcript_mtime(current["transcript_path"]),
                created_by=getattr(args, "created_by", "manual"),
            )
            repo.update_session_dream_state(
                current["session_id"],
                dream_status="dreaming",
                dream_runner_used=runner,
                dream_runner_status="running",
            )

        previous_summary = deps.last_dream_summary(conn, session_id)
        current_handover = deps.current_session_handover(conn, session_id)
        semantic_context = deps.same_session_semantic_context(conn, session_id)
        event_rows = [dict(event) for event in events]
        pipeline_context = deps.context_cls(
            conn=conn,
            dream_run_id=dream_run_id,
            session_id=session_id,
            event_from=event_from,
            event_to=event_to,
            run_dir=run_dir,
            dry_run=dry_run,
            clock=deps.default_clock(),
            file_system=deps.default_file_system(),
            db_provider=deps.default_db_provider(),
            run_artifacts=deps.run_artifacts_cls(),
        )
        deps.run_window_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="window",
                stage_order=0,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_00_window",
                parsed_output_path=run_dir / "00-window" / "conversation.md",
            ),
            event_rows=event_rows,
            current=dict(current),
            previous_summary=previous_summary,
            semantic_context=semantic_context,
        )

        narrative = deps.run_narrative_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="dream_narrative",
                stage_order=1,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_01_dream_narrative",
                raw_output_path=run_dir / "01-dream-narrative" / "raw-output.md",
                parsed_output_path=run_dir / "01-dream-narrative" / "dream.md",
            ),
            event_rows=event_rows,
            session=dict(current),
            prompt_text=deps.build_dream_prompt(
                current,
                events,
                previous_summary,
                semantic_context,
                current_handover,
                json_dumps_fn=deps.json_dumps,
                plain_event_window_fn=deps.plain_event_window,
                budget_fn=deps.budget,
            ),
            prior_dream_summary=previous_summary,
            current_handover=current_handover,
            semantic_context=semantic_context,
            runner=runner,
            runner_model=runner_model,
            reuse_from_dream_run_id=reuse_from_dream_run_id,
            runner_timeout=int(getattr(args, "runner_timeout", 1800)),
            dry_run=dry_run,
        )
        response = narrative["response"]
        project_dream_path = Path(narrative["project_dream_path"]) if narrative["project_dream_path"] else None
        semantic_stage = deps.run_semantic_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="semantic_extraction",
                stage_order=2,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_02_semantic_extraction",
                raw_output_path=run_dir / "02-semantic-extraction" / "raw-output.json",
                parsed_output_path=run_dir / "02-semantic-extraction" / "semantic-proposals.json",
            ),
            current=current,
            events=event_rows,
            narrative_response=response,
            semantic_context=semantic_context,
            runner=runner,
            runner_model=runner_model,
            reuse_from_dream_run_id=reuse_from_dream_run_id,
            runner_timeout=int(getattr(args, "runner_timeout", 1800)),
            args=args,
        )
        semantic_payload = semantic_stage["semantic_payload"]
        semantic_id_map = semantic_stage["semantic_id_map"]

        normalization_stage = deps.run_normalization_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="normalization",
                stage_order=3,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_03_normalization",
                parsed_output_path=run_dir / "03-normalization" / "normalized-semantic-proposals.json",
            ),
            semantic_payload=semantic_payload,
            dry_run=dry_run,
        )
        semantic_payload = normalization_stage["semantic_payload"]

        operational_stage = deps.run_operational_extraction_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="operational_extraction",
                stage_order=4,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_04_operational_extraction",
                parsed_output_path=run_dir / "04-operational-extraction" / "operational-facts.json",
            ),
        )
        operational = operational_stage["operational_payload"]

        candidate_search_stage = deps.run_candidate_search_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="candidate_search",
                stage_order=5,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_05_candidate_search",
                raw_output_path=run_dir / "05-candidate-search" / "raw-output.json",
                parsed_output_path=run_dir / "05-candidate-search" / "candidates.json",
            ),
            semantic_payload=semantic_payload,
            args=args,
        )
        candidates = candidate_search_stage["candidates"]
        reconciliation_stage = deps.run_reconciliation_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="reconciliation",
                stage_order=6,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_06_reconciliation",
                raw_output_path=run_dir / "06-reconciliation" / "raw-output.json",
                parsed_output_path=run_dir / "06-reconciliation" / "decisions.json",
            ),
            semantic_payload=semantic_payload,
            candidates=candidates,
            runner=runner,
            runner_model=runner_model,
            semantic_id_map=semantic_id_map,
            reuse_from_dream_run_id=reuse_from_dream_run_id,
            runner_timeout=int(getattr(args, "runner_timeout", 1800)),
            args=args,
        )
        reconciliation_payload = reconciliation_stage["reconciliation_payload"]

        persistence_stage = deps.run_persistence_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="persistence",
                stage_order=7,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_07_persistence",
                raw_output_path=run_dir / "07-persistence" / "raw-output.json",
                parsed_output_path=run_dir / "07-persistence" / "sqlite-writes.json",
            ),
            session=current,
            reconciliation_payload=reconciliation_payload,
            semantic_payload=semantic_payload,
            dry_run=dry_run,
            runner=runner,
            runner_model=runner_model,
            args=args,
        )
        conn = persistence_stage.get("conn", conn)
        repo = deps.repo_cls(conn)
        persistence = persistence_stage["persistence"]

        audit = deps.run_audit_stage(
            conn=conn,
            context=pipeline_context,
            stage_context=deps.stage_context_cls(
                stage_name="audit",
                stage_order=8,
                stage_run_id=f"stage_{deps.safe_slug(dream_run_id)}_08_audit",
                parsed_output_path=run_dir / "audit" / "summary.md",
            ),
            session=current,
            semantic_payload=semantic_payload,
            reconciliation_payload=reconciliation_payload,
            operational=operational,
            candidates=candidates,
            persistence_result=persistence,
            validation={"status": "succeeded"},
            dry_run=dry_run,
            event_count=len(events),
        )
        audit_paths = audit["audit_paths"]
        output_paths = [str(path.relative_to(deps.root())) for path in audit_paths.values()]
        output_summary_path = str(audit_paths.get("summary").relative_to(deps.root()))
        if project_dream_path is not None:
            project_ref = deps.append_project_memory_ref(
                current,
                str(project_dream_path.relative_to(deps.root())),
                str(project_dream_path.relative_to(deps.root())),
                dream_run_id,
                runner,
                runner_model,
            )
            output_paths = [
                str(project_dream_path.relative_to(deps.root())),
                str(project_ref.relative_to(deps.root())),
                *output_paths,
            ]
        session_brief = deps.extract_session_brief(response)
        finished = deps.now()
        duration_ms = int((monotonic() - run_started_mono) * 1000)
        with conn:
            for role, path in audit_paths.items():
                deps.record_artifact(
                    conn,
                    dream_run_id=dream_run_id,
                    stage_run_id=None,
                    session_id=session_id,
                    artifact_kind="audit",
                    artifact_role=role,
                    path=path,
                )
            deps.aggregate_stage_metrics(conn, dream_run_id, duration_ms)
            repo.update_dream_run_status(
                dream_run_id,
                finished_at=finished,
                status="succeeded",
                pipeline_status="dry_run" if dry_run else "succeeded",
                output_summary_path=output_summary_path,
                output_memory_paths_json=deps.json_dumps(output_paths),
                error_message=None,
            )
            if not dry_run:
                contiguous = deps.contiguous_dreamed_event_seq(conn, session_id, int(current["last_event_seq"]))
                dream_status = "dreamed" if contiguous >= int(current["last_event_seq"]) else "dream_pending"
                repo.update_session_dream_state(
                    session_id,
                    dream_status=dream_status,
                    last_dream_event_seq=contiguous,
                    last_dream_at=finished,
                    last_dream_run_id=dream_run_id,
                    session_brief=session_brief,
                    keep_existing_session_brief=True,
                    dream_runner_used=runner,
                    dream_runner_status="succeeded",
                )
                if output_summary_path:
                    summary_input_count = max(0, event_to - event_from + 1 if event_to >= event_from else 0)
                    repo.upsert_session_dream_summary(
                        session_id,
                        summary_path=output_summary_path,
                        created_at=finished,
                        input_event_seq_to=contiguous,
                        input_event_count=summary_input_count,
                    )
                    repo.update_session_dream_state(
                        session_id,
                        summary_status="summarized",
                        last_summary_event_seq=contiguous,
                        last_summary_at=finished,
                    )
            else:
                repo.update_session_dream_state(
                    session_id,
                    dream_status="dream_pending",
                    dream_runner_used=runner,
                    dream_runner_status="dry_run_succeeded",
                )
        mode = "dry-run " if dry_run else ""
        print(f"{mode}dreamed {current['client_type']} {session_id} pipeline=2 runner={runner} model={runner_model or '-'} -> {', '.join(output_paths)}")
        return 0
    except Exception as exc:  # noqa: BLE001
        trace = traceback.format_exc()
        with conn:
            if dream_run_id and run_started_mono is not None:
                finished = deps.now()
                duration_ms = int((monotonic() - run_started_mono) * 1000)
                deps.aggregate_stage_metrics(conn, dream_run_id, duration_ms)
                repo.update_dream_run_status(
                    dream_run_id,
                    finished_at=finished,
                    status="failed",
                    pipeline_status="failed",
                    failed_stage=repo.current_running_stage_name(dream_run_id),
                    error_message=trace[-8000:],
                )
                repo.mark_running_stages_failed(dream_run_id, finished_at=finished, error_message=trace[-8000:])
            repo.update_session_dream_state(session_id, dream_status="failed", dream_runner_status=str(exc))
        print(f"failed {session_id}: {exc}\n{trace}")
        return 1
    finally:
        conn.close()
        deps.release_lock(dream_lock)


def cmd_dream_v2(
    args: argparse.Namespace,
    *,
    deps: CommandRunnerDependencies,
) -> int:
    global_dream_lock = deps.acquire_lock("dream-run", "global")
    if global_dream_lock is None:
        print("agent-memory dream skipped: another dream process is already running")
        return 0
    atexit.register(deps.release_lock, global_dream_lock)
    try:
        conn = deps.connect()
        repo = deps.repo_cls(conn)
        try:
            if getattr(args, "session", None):
                selected = repo.resolve_session_selector(args.session)
                sessions = [selected] if selected is not None else []
            else:
                sessions = repo.list_sessions_pending_dream()
            if not sessions:
                repair_limit = max(0, int(getattr(args, "repair_missing_graph_patches_limit", 0) or 0))
                repaired = 0
                repaired_paths: list[str] = []
                if repair_limit:
                    repair_sessions = repo.list_sessions_missing_graph_artifacts()
                    remaining_repair_limit = repair_limit
                    for repair_session in repair_sessions:
                        repaired_for_session, repaired_session_paths, conn = deps.repair_missing_graph_patches(
                            conn,
                            repo,
                            repair_session,
                            repair_limit=remaining_repair_limit,
                            runner=getattr(args, "runner", "deterministic"),
                            runner_model=getattr(args, "runner_model", None),
                            timeout=int(getattr(args, "runner_timeout", 1800)),
                            args=args,
                        )
                        repaired += repaired_for_session
                        repaired_paths.extend(repaired_session_paths)
                        if repaired_for_session:
                            print(f"repaired graph patches {repair_session['session_id']} count={repaired_for_session}")
                        remaining_repair_limit -= repaired_for_session
                        if remaining_repair_limit <= 0:
                            break
                if repaired:
                    print(f"graph artifacts -> {', '.join(repaired_paths)}")
                    return 0
                print("No sessions to dream.")
                return 0
            session_ids = [row["session_id"] for row in sessions]
        finally:
            conn.close()
        exit_code = 0
        for session_id in session_ids:
            try:
                result = deps.run_v2_for_session(args, session_id)
            except Exception as exc:  # noqa: BLE001
                print(f"failed {session_id}: {exc}")
                result = 1
            if result:
                exit_code = result
        return exit_code
    finally:
        deps.release_lock(global_dream_lock)
