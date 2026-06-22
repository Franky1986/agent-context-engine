from __future__ import annotations

import argparse
import atexit
import os
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..adapters.launchagent import DEFAULT_ENV_FILE, DEFAULT_LABEL, DEFAULT_LAUNCHD_PATH
from ..adapters.launchagent import cmd_install_launchagent as adapter_cmd_install_launchagent
from ..adapters.launchagent import cmd_launchagent_status as adapter_cmd_launchagent_status
from ..adapters.launchagent import cmd_uninstall_launchagent as adapter_cmd_uninstall_launchagent
from ..adapters.sqlite import scheduler as scheduler_repo
from ..adapters.sqlite import repositories as repositories_repo
from ..adapters.sqlite.request_db import connect as request_db_connect
from .maintenance import run_prune_logs
from ..application.sessions import cmd_sync_transcripts
from ..infrastructure.config import MEMORY_DIR, json_dumps
from .graph import cmd_neo4j_sync_pending
from .dream_queue import enqueue_pending_dream_jobs, process_dream_queue, recover_stale_running_dreams
from ..interfaces.hooks.main import cmd_replay_hook_queue
from ..infrastructure.locks import acquire_lock, release_lock
from .summaries import cmd_summarize
from .summaries import cmd_summarize_windows
from ..ports.clock import Clock
from ..ports.repositories.sqlite import SQLiteConnectionProvider


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        from ..infrastructure.config import utc_now

        return utc_now()


def _default_clock() -> Clock:
    return _DefaultClock()


def _now() -> str:
    return _default_clock().utc_now()


class _SchedulerDbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        return request_db_connect(*args, **kwargs)


def _default_db_provider() -> SQLiteConnectionProvider:
    return _SchedulerDbProvider()


def _connect(init: bool = True, db_provider: SQLiteConnectionProvider | None = None) -> sqlite3.Connection:
    provider = db_provider or _default_db_provider()
    return provider.connect(init=init)


def cmd_install_launchagent(args: argparse.Namespace) -> int:
    return adapter_cmd_install_launchagent(args)


def cmd_uninstall_launchagent(args: argparse.Namespace) -> int:
    return adapter_cmd_uninstall_launchagent(args)


def cmd_launchagent_status(args: argparse.Namespace) -> int:
    return adapter_cmd_launchagent_status(args)


@dataclass(frozen=True)
class SchedulerPorts:
    connect_db: Callable[[bool], sqlite3.Connection]
    acquire_lock: Callable[[str, str], Any]
    release_lock: Callable[[Any], None]
    replay_hook_queue: Callable[[], int]
    prune_logs: Callable[[argparse.Namespace], int]
    sync_transcripts: Callable[[], int]
    summarize_sessions: Callable[[], int]
    summarize_windows: Callable[[argparse.Namespace], int]
    recover_stale_dreams: Callable[[], int]
    enqueue_pending_dreams: Callable[[argparse.Namespace], int]
    process_dream_queue: Callable[[argparse.Namespace], int]
    neo4j_sync_pending: Callable[[argparse.Namespace], int]


@dataclass(frozen=True)
class SchedulerStep:
    name: str
    run: Callable[[argparse.Namespace], int]


@dataclass(frozen=True)
class SchedulerUseCase:
    ports: SchedulerPorts

    def connect_db(self, *, init: bool) -> sqlite3.Connection:
        return self.ports.connect_db(init)

    def scheduler_counts(self, conn: sqlite3.Connection) -> dict[str, int]:
        counts = scheduler_repo.table_counts(conn)
        counts["pending_summaries"] = scheduler_repo.pending_summary_count(conn)
        counts["pending_dreams"] = len(repositories_repo.dreamable_sessions(conn, True))
        counts["running_summary_windows"] = scheduler_repo.running_summary_window_count(conn)
        counts["running_dreams"] = scheduler_repo.running_dream_count(conn)
        return counts

    def counts_delta(self, before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
        keys = sorted(set(before) | set(after))
        return {
            key: int(after.get(key, 0)) - int(before.get(key, 0))
            for key in keys
            if int(after.get(key, 0)) != int(before.get(key, 0))
    }

    def classify_step_error(self, exc: BaseException) -> str:
        if isinstance(exc, ConnectionError):
            return "scheduler_step_retryable_failure"
        if isinstance(exc, sqlite3.OperationalError):
            if self.is_retryable_sqlite_error(exc):
                return "scheduler_step_retryable_failure"
            return "scheduler_step_hard_failure"
        if isinstance(exc, (sqlite3.DatabaseError, OSError, PermissionError)):
            return "scheduler_step_hard_failure"
        return "scheduler_step_hard_failure"

    def scheduler_label(self) -> str:
        service_name = os.environ.get("XPC_SERVICE_NAME", "")
        return (
            "launch_agent"
            if service_name.startswith("com.agent-context-engine.")
            or service_name.startswith("com.agent-memory.")
            or "agent-context-engine" in service_name
            or "agent-memory" in service_name
            else "manual"
        )

    def is_retryable_sqlite_error(self, exc: BaseException) -> bool:
        if not isinstance(exc, sqlite3.OperationalError):
            return False
        message = str(exc).lower()
        return "database is locked" in message or "database is busy" in message

    def with_db_retry(self, fn: Callable[[], Any], *, attempts: int = 3, delay_seconds: float = 1.0) -> Any:
        last_error: BaseException | None = None
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except sqlite3.OperationalError as exc:
                if not self.is_retryable_sqlite_error(exc) or attempt >= attempts:
                    raise
                last_error = exc
                print(
                    f"agent-context-engine scheduler db retry {attempt}/{attempts} after lock: {exc}",
                    file=sys.stderr,
                )
                time.sleep(delay_seconds * attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("database retry helper exhausted without error")

    def repair_abandoned_runs(self, conn: sqlite3.Connection) -> dict[str, int]:
        repaired = self.with_db_retry(
            lambda: scheduler_repo.repair_abandoned_scheduler_runs(
                conn,
                finished_at=_now(),
                notes="Recovered by a subsequent scheduler run after an unclean exit.",
                error_message="Recovered abandoned scheduler step after an unclean exit.",
            )
        )
        if repaired["runs"]:
            print(
                f"agent-context-engine scheduler recovered abandoned runs={repaired['runs']} steps={repaired['steps']}",
                file=sys.stderr,
            )
        return repaired

    def run(self, args: argparse.Namespace) -> int:
        scheduler_lock = self.ports.acquire_lock("scheduler-run", "global")
        if scheduler_lock is None:
            print("agent-context-engine scheduler skipped: already running")
            return 0
        atexit.register(self.ports.release_lock, scheduler_lock)
        try:
            return self._run_locked(args)
        finally:
            self.ports.release_lock(scheduler_lock)

    def _run_locked(self, args: argparse.Namespace) -> int:
        log_dir = MEMORY_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        conn = self.connect_db(init=True)
        self.repair_abandoned_runs(conn)
        started_at = _now()
        scheduler_run_id = f"scheduler_{started_at.replace(':', '-') .replace('+', 'Z')}_{os.getpid()}"
        run_before = self.scheduler_counts(conn)
        source_label = self.scheduler_label()
        self.with_db_retry(
            lambda: scheduler_repo.insert_scheduler_run(
                conn,
                scheduler_run_id=scheduler_run_id,
                label=source_label,
                started_at=started_at,
                grace_minutes=args.grace_minutes,
                runner=args.runner,
                runner_timeout=args.runner_timeout,
                cwd=str(Path.cwd()),
                pid=os.getpid(),
                before_counts_json=json_dumps(run_before),
            )
        )
        print(f"agent-context-engine scheduler start {started_at} run={scheduler_run_id}")

        exit_code = 0
        for step in self._step_plan(args):
            step_started = _now()
            step_before = self.scheduler_counts(conn)
            step_id = self.with_db_retry(
                lambda: scheduler_repo.insert_scheduler_step(
                    conn,
                    scheduler_run_id=scheduler_run_id,
                    step_name=step.name,
                    started_at=step_started,
                    before_counts_json=json_dumps(step_before),
                )
            )
            print(f"agent-context-engine scheduler step {step.name} start")
            step_result = 0
            step_status = "ok"
            step_error_message: str | None = None
            try:
                conn.close()
                conn = None
                step_result = int(step.run(args))
            except Exception as exc:  # noqa: BLE001 - scheduler should log and continue.
                failure_code = self.classify_step_error(exc)
                print(f"agent-context-engine scheduler step {step.name} failed [{failure_code}]: {exc}", file=sys.stderr)
                step_result = 1
                step_status = "failed"
                step_error_message = f"{failure_code}: {exc}"
                if failure_code == "scheduler_step_hard_failure":
                    exit_code = 1
            if conn is None:
                conn = self.connect_db(init=False)
            if step_result and step_status == "ok":
                step_status = "failed"
            if step_result:
                exit_code = step_result
            try:
                step_after = self.scheduler_counts(conn)
                self.with_db_retry(
                    lambda: scheduler_repo.mark_scheduler_step_finished(
                        conn,
                        step_id=step_id,
                        finished_at=_now(),
                        status=step_status,
                        exit_code=int(step_result),
                        after_counts_json=json_dumps(step_after),
                        error_message=step_error_message,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - scheduler should fail loudly but still close cleanly.
                failure_code = self.classify_step_error(exc)
                print(
                    f"agent-context-engine scheduler step {step.name} finalize failed [{failure_code}]: {exc}",
                    file=sys.stderr,
                )
                exit_code = 1
                raise
            print(f"agent-context-engine scheduler step {step.name} done rc={step_result}")

        run_after = self.scheduler_counts(conn)
        finished_at = _now()
        self.with_db_retry(
            lambda: scheduler_repo.mark_scheduler_run_finished(
                conn,
                scheduler_run_id=scheduler_run_id,
                finished_at=finished_at,
                status="ok" if exit_code == 0 else "failed",
                exit_code=exit_code,
                after_counts_json=json_dumps(run_after),
            )
        )
        delta = self.counts_delta(run_before, run_after)
        if delta:
            print(f"agent-context-engine scheduler delta {json_dumps(delta)}")
        print(f"agent-context-engine scheduler finished {finished_at} rc={exit_code}")
        conn.close()
        return exit_code

    def _step_plan(self, args: argparse.Namespace) -> list[SchedulerStep]:
        return [
            SchedulerStep("replay-hook-queue", lambda _args: self.ports.replay_hook_queue()),
            SchedulerStep(
                "prune-logs",
                lambda _args: self.ports.prune_logs(
                    argparse.Namespace(
                        days=int(os.environ.get("AGENT_MEMORY_LOG_RETENTION_DAYS", "3")),
                        all=False,
                        dry_run=False,
                    )
                ),
            ),
            SchedulerStep("sync-transcripts", lambda _args: self.ports.sync_transcripts()),
            SchedulerStep("summarize-sessions", lambda _args: self.ports.summarize_sessions()),
            SchedulerStep("summarize-windows", lambda _args: self.ports.summarize_windows(args)),
            SchedulerStep("recover-stale-dreams", lambda _args: self.ports.recover_stale_dreams()),
            SchedulerStep("enqueue-pending-dreams", self.ports.enqueue_pending_dreams),
            SchedulerStep("dream-queue", self.ports.process_dream_queue),
            SchedulerStep("neo4j-sync-pending", lambda _args: self.ports.neo4j_sync_pending(args)),
        ]

    def status(self, args: argparse.Namespace) -> int:
        conn = self.ports.connect_db()
        rows = scheduler_repo.scheduler_run_rows(conn, limit=args.limit)
        if not rows:
            print("No scheduler runs recorded.")
            return 0
        for row in rows:
            before = json_loads(row["before_counts_json"])
            after = json_loads(row["after_counts_json"]) if row["after_counts_json"] else {}
            delta = self.counts_delta(before, after) if after else {}
            print(
                f"{row['started_at']} {row['scheduler_run_id']} "
                f"status={row['status']} rc={row['exit_code']} label={row['label']} runner={row['runner']}"
            )
            print(f"  finished: {row['finished_at'] or '-'} cwd={row['cwd'] or '-'} pid={row['pid'] or '-'}")
            print(f"  pending before: summaries={before.get('pending_summaries', 0)} dreams={before.get('pending_dreams', 0)}")
            if after:
                print(f"  pending after: summaries={after.get('pending_summaries', 0)} dreams={after.get('pending_dreams', 0)}")
            print(f"  delta: {json_dumps(delta) if delta else '{}'}")
            steps = scheduler_repo.scheduler_step_rows(conn, scheduler_run_id=row["scheduler_run_id"])
            for step in steps:
                step_before = json_loads(step["before_counts_json"])
                step_after = json_loads(step["after_counts_json"]) if step["after_counts_json"] else {}
                step_delta = self.counts_delta(step_before, step_after) if step_after else {}
                print(
                    f"  - {step['step_name']}: status={step['status']} rc={step['exit_code']} "
                    f"started={step['started_at']} finished={step['finished_at'] or '-'} delta={json_dumps(step_delta) if step_delta else '{}'}"
                )
                if step["error_message"]:
                    print(f"    error: {step['error_message']}")
        return 0


def _default_scheduler_ports() -> SchedulerPorts:
    return SchedulerPorts(
        connect_db=lambda init=True: _connect(init=init),
        acquire_lock=acquire_lock,
        release_lock=release_lock,
        replay_hook_queue=lambda: cmd_replay_hook_queue(argparse.Namespace(client=None, limit=1000, stop_on_error=False)),
        prune_logs=lambda args: _prune_logs_step(args),
        sync_transcripts=lambda: cmd_sync_transcripts(argparse.Namespace(session=None)),
        summarize_sessions=lambda: cmd_summarize(argparse.Namespace(pending=True, session=None)),
        summarize_windows=lambda args: cmd_summarize_windows(argparse.Namespace(grace_minutes=args.grace_minutes, force=False, fix_gaps=True)),
        recover_stale_dreams=lambda: _recover_stale_dreams_step(),
        enqueue_pending_dreams=lambda args: _enqueue_pending_dreams_step(args),
        process_dream_queue=lambda args: process_dream_queue(args),
        neo4j_sync_pending=lambda args: cmd_neo4j_sync_pending(
            argparse.Namespace(
                limit=args.neo4j_sync_limit,
                dry_run=False,
                batch_size=args.neo4j_batch_size,
                timeout=args.neo4j_timeout,
                uri=args.uri,
                database=args.database,
                user=args.user,
                password_env=args.password_env,
            )
        )
        if args.sync_neo4j
        else 0,
    )


def _scheduler_service() -> SchedulerUseCase:
    return SchedulerUseCase(_default_scheduler_ports())


def scheduler_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return _scheduler_service().scheduler_counts(conn)


def counts_delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return _scheduler_service().counts_delta(before, after)


def cmd_scheduler_run(args: argparse.Namespace) -> int:
    return _scheduler_service().run(args)


def _cmd_scheduler_run_locked(args: argparse.Namespace) -> int:
    return _scheduler_service()._run_locked(args)


def _enqueue_pending_dreams_step(args: argparse.Namespace) -> int:
    conn = _connect(init=False)
    try:
        count = enqueue_pending_dream_jobs(
            conn,
            runner=args.runner,
            runner_model=args.runner_model,
            runner_timeout=args.runner_timeout,
            created_by="scheduler_queue",
            limit=getattr(args, "dream_enqueue_limit", 25),
        )
        print(f"enqueued pending dreams: {count}")
        return 0
    finally:
        conn.close()


def _recover_stale_dreams_step() -> int:
    conn = _connect(init=False)
    try:
        count = recover_stale_running_dreams(conn)
        print(f"recovered stale running dreams: {count}")
        return 0
    finally:
        conn.close()


def _prune_logs_step(args: argparse.Namespace) -> int:
    lines, exit_code = run_prune_logs(days=args.days, all=args.all, dry_run=args.dry_run)
    for line in lines:
        print(line)
    return exit_code


def cmd_scheduler_status(args: argparse.Namespace) -> int:
    return _scheduler_service().status(args)


def scheduler_label() -> str:
    return _scheduler_service().scheduler_label()


def json_loads(value: str) -> dict[str, int]:
    import json

    data = json.loads(value)
    return {str(key): int(val) for key, val in data.items()}
