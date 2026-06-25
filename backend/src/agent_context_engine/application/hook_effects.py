from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

from ..infrastructure.config import ENV_FILE_PATH, LOCK_DIR, ROOT, SCRIPT_PATH, json_dumps, utc_now
from ..infrastructure.locks import load_env_file
from ..infrastructure.db import connect
from .dream_queue import queue_dream_without_process, stop_dream_due
from ..interfaces.hooks.support.queue import hook_queue_status


def _runtime_env() -> dict[str, str]:
    return {
        **os.environ,
        **load_env_file(ENV_FILE_PATH),
    }


def spawn_stop_dream(session_id: str) -> None:
    env = _runtime_env()
    if env.get("AGENT_MEMORY_AUTO_DREAM_ON_STOP", "1") in {"0", "false", "False", "no"}:
        return
    if env.get("AGENT_MEMORY_DREAM") or env.get("AGENT_MEMORY_SCHEDULER"):
        return

    conn = connect()
    try:
        if not stop_dream_due(conn, session_id):
            return
    finally:
        conn.close()

    runner = env.get("AGENT_MEMORY_STOP_DREAM_RUNNER", "same-as-session")
    timeout = env.get("AGENT_MEMORY_STOP_DREAM_TIMEOUT", "180")
    queue_dream_without_process(
        session_id,
        reason="stop_event",
        runner=runner,
        runner_timeout=int(timeout),
        created_by="stop_event_queue",
        priority=50,
    )
    spawn_scheduler_kick("dream-stop")


def spawn_initial_prompt_dream(session_id: str) -> None:
    env = _runtime_env()
    if env.get("AGENT_MEMORY_INITIAL_DREAM_ON_PROMPT", "1") in {"0", "false", "False", "no"}:
        return
    if env.get("AGENT_MEMORY_DREAM") or env.get("AGENT_MEMORY_SCHEDULER"):
        return
    runner = env.get("AGENT_MEMORY_INITIAL_DREAM_RUNNER", "same-as-session")
    timeout = env.get("AGENT_MEMORY_INITIAL_DREAM_TIMEOUT", "60")
    queue_dream_without_process(
        session_id,
        reason="initial_prompt",
        runner=runner,
        runner_timeout=int(timeout),
        created_by="initial_prompt_queue",
        priority=10,
    )
    spawn_scheduler_kick("dream-initial")


def spawn_scheduler_kick(reason: str = "hook") -> None:
    env = _runtime_env()
    if env.get("AGENT_MEMORY_AUTO_WORKER_ON_HOOK", "1") in {"0", "false", "False", "no"}:
        return
    if env.get("AGENT_MEMORY_DREAM") or env.get("AGENT_MEMORY_SCHEDULER"):
        return
    try:
        debounce_seconds = max(5, int(env.get("AGENT_MEMORY_WORKER_DEBOUNCE_SECONDS", "30")))
    except ValueError:
        debounce_seconds = 30
    bypass_debounce = reason in {"dream-initial", "dream-stop"}
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    marker = LOCK_DIR / "scheduler-kick-last.json"
    now = datetime.now(timezone.utc)
    if marker.exists() and not bypass_debounce:
        try:
            age = now.timestamp() - marker.stat().st_mtime
            if age < debounce_seconds:
                return
        except OSError:
            pass
    marker.write_text(json_dumps({"reason": reason, "created_at": utc_now(), "pid": os.getpid()}), encoding="utf-8")
    grace = env.get("AGENT_MEMORY_WORKER_GRACE_MINUTES", "1")
    runner = env.get("AGENT_MEMORY_WORKER_RUNNER", "same-as-session")
    timeout = env.get("AGENT_MEMORY_WORKER_RUNNER_TIMEOUT", "180")
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "scheduler-run",
        "--grace-minutes",
        grace,
        "--runner",
        runner,
        "--runner-timeout",
        timeout,
        "--dream-queue-limit",
        env.get("AGENT_MEMORY_WORKER_DREAM_QUEUE_LIMIT", "5"),
        "--no-sync-neo4j",
    ]
    env = {
        **env,
        "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT),
        "AGENT_MEMORY_SCHEDULER": "1",
    }
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env=env,
    )


def spawn_hook_queue_kick(reason: str = "hook") -> None:
    env = _runtime_env()
    if env.get("AGENT_MEMORY_AUTO_WORKER_ON_HOOK", "1") in {"0", "false", "False", "no"}:
        return
    if env.get("AGENT_MEMORY_DREAM") or env.get("AGENT_MEMORY_SCHEDULER") or env.get("AGENT_MEMORY_HOOK_QUEUE_WORKER"):
        return
    queue = hook_queue_status()
    worker = queue.get("worker") or {}
    if worker.get("running") and not worker.get("stale"):
        return
    try:
        debounce_seconds = max(1, int(env.get("AGENT_MEMORY_HOOK_QUEUE_DEBOUNCE_SECONDS", "3")))
    except ValueError:
        debounce_seconds = 3
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    marker = LOCK_DIR / "hook-queue-kick-last.json"
    now = datetime.now(timezone.utc)
    if marker.exists():
        try:
            age = now.timestamp() - marker.stat().st_mtime
            queued_events = int(queue.get("queued_events") or 0)
            if age < debounce_seconds and queued_events <= 0:
                return
        except OSError:
            pass
    marker.write_text(json_dumps({"reason": reason, "created_at": utc_now(), "pid": os.getpid()}), encoding="utf-8")
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "replay-hook-queue",
        "--limit",
        env.get("AGENT_MEMORY_HOOK_QUEUE_LIMIT", "200"),
        "--worker",
    ]
    subprocess.Popen(
        command,
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        env={
            **env,
            "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT),
            "AGENT_MEMORY_HOOK_QUEUE_WORKER": "1",
        },
    )
