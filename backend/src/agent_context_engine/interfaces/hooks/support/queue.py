from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....infrastructure.config import DB_PATH, MEMORY_DIR, ROOT, json_dumps, safe_slug, utc_now
from ....infrastructure.db import connect


HOOK_QUEUE_DIR = MEMORY_DIR / "events" / "queue"
HOOK_QUEUE_FAILURE_DIR = MEMORY_DIR / "events" / "queue-failed"
HOOK_QUEUE_LOG_PATH = MEMORY_DIR / "logs" / "hooks-queue.log"
HOOK_BRIDGE_LOG_PATH = MEMORY_DIR / "logs" / "opencode-hook.err.log"
HOOK_QUEUE_STATUS_PATH = MEMORY_DIR / "status" / "hook-queue-worker.json"


def hook_queue_file_count() -> int:
    return len(list(HOOK_QUEUE_DIR.glob("*/*.json")))


def hook_queue_failed_file_count() -> int:
    return len(list(HOOK_QUEUE_FAILURE_DIR.glob("*/*.json")))


def hook_queue_status() -> dict[str, Any]:
    status: dict[str, Any] = {
        "queued_events": hook_queue_file_count(),
        "failed_events": hook_queue_failed_file_count(),
        "oldest_queued_at": _oldest_file_timestamp(HOOK_QUEUE_DIR),
        "oldest_failed_at": _oldest_file_timestamp(HOOK_QUEUE_FAILURE_DIR),
        "queue_log": _tail_log_summary(HOOK_QUEUE_LOG_PATH),
        "bridge_log": _tail_log_summary(HOOK_BRIDGE_LOG_PATH, parse_json=False),
        "worker": {
            "running": False,
            "pid": None,
            "started_at": "",
            "heartbeat_at": "",
            "last_reason": "",
            "last_exit_at": "",
            "stale": False,
        },
    }
    if HOOK_QUEUE_STATUS_PATH.exists():
        try:
            loaded = json.loads(HOOK_QUEUE_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        worker = loaded.get("worker")
        if isinstance(worker, dict):
            heartbeat = str(worker.get("heartbeat_at") or "")
            age_seconds = _age_seconds(heartbeat)
            status["worker"] = {
                "running": bool(worker.get("running")),
                "pid": worker.get("pid"),
                "started_at": str(worker.get("started_at") or ""),
                "heartbeat_at": heartbeat,
                "last_reason": str(worker.get("last_reason") or ""),
                "last_exit_at": str(worker.get("last_exit_at") or ""),
                "stale": bool(worker.get("running")) and age_seconds is not None and age_seconds > 90,
            }
    reasons: list[str] = []
    if int(status["failed_events"] or 0) > 0:
        reasons.append("dead_letter_events_present")
    if bool(status["worker"].get("stale")):
        reasons.append("hook_queue_worker_stale")
    queue_log = status.get("queue_log") if isinstance(status.get("queue_log"), dict) else {}
    bridge_log = status.get("bridge_log") if isinstance(status.get("bridge_log"), dict) else {}
    if queue_log.get("has_error"):
        reasons.append("recent_hook_queue_error")
    if bridge_log.get("has_error"):
        reasons.append("recent_hook_bridge_error")
    status["degraded"] = bool(reasons)
    status["degradation_reasons"] = reasons
    return status


def reserve_queue_slot(
    *,
    client: str,
    payload: dict[str, Any],
    event_name: str,
    hook_mode: str,
    recorded_at: str,
    cwd: str,
    workdir: str,
    project_id: str,
    transcript_path: str | None,
    client_version: str | None,
    thread_name: str | None,
    session_brief: str | None,
    preferred_dream_runner: str | None,
    native_resume_command: str | None,
    session_id: str,
) -> dict[str, Any]:
    event_id = str(uuid.uuid4())
    queued_at = utc_now()
    conn = connect(init=not DB_PATH.exists())
    try:
        conn.execute("begin immediate")
        row = conn.execute(
            "select last_event_seq, last_reserved_event_seq, started_at from sessions where session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            reserved_seq = 1
            conn.execute(
                """
                insert into sessions (
                  session_id, client_type, client_version, thread_name, session_brief,
                  project_id, cwd, last_workdir, transcript_path, started_at,
                  last_event_at, status, summary_status, dream_status,
                  last_event_seq, last_reserved_event_seq, native_resume_command,
                  preferred_dream_runner
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', 'summary_pending',
                          'dream_pending', 0, ?, ?, ?)
                """,
                (
                    session_id,
                    client,
                    client_version,
                    thread_name,
                    session_brief,
                    project_id,
                    cwd,
                    workdir or cwd,
                    transcript_path,
                    recorded_at,
                    recorded_at,
                    reserved_seq,
                    native_resume_command,
                    preferred_dream_runner or client,
                ),
            )
        else:
            reserved_seq = max(int(row["last_event_seq"] or 0), int(row["last_reserved_event_seq"] or 0)) + 1
            started_at = recorded_at if not row["started_at"] else None
            conn.execute(
                """
                update sessions
                set client_version = coalesce(?, client_version),
                    thread_name = coalesce(?, thread_name),
                    session_brief = coalesce(session_brief, ?),
                    project_id = ?,
                    cwd = ?,
                    last_workdir = ?,
                    transcript_path = coalesce(?, transcript_path),
                    native_resume_command = coalesce(?, native_resume_command),
                    last_event_at = ?,
                    started_at = coalesce(started_at, ?),
                    summary_status = 'summary_pending',
                    dream_status = 'dream_pending',
                    last_reserved_event_seq = ?,
                    preferred_dream_runner = coalesce(preferred_dream_runner, ?)
                where session_id = ?
                """,
                (
                    client_version,
                    thread_name,
                    session_brief,
                    project_id,
                    cwd,
                    workdir or cwd,
                    transcript_path,
                    native_resume_command,
                    recorded_at,
                    started_at,
                    reserved_seq,
                    preferred_dream_runner or client,
                    session_id,
                ),
            )
        conn.execute(
            """
            insert or replace into hook_queue_audit (
              event_id, session_id, reserved_seq, client_type, event_name,
              hook_mode, recorded_at, queued_at, status
            ) values (?, ?, ?, ?, ?, ?, ?, ?, 'queued')
            """,
            (event_id, session_id, reserved_seq, client, event_name, hook_mode, recorded_at, queued_at),
        )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
    return {
        "event_id": event_id,
        "reserved_seq": reserved_seq,
        "recorded_at": recorded_at,
        "queued_at": queued_at,
        "session_id": session_id,
    }


def queue_hook_event(
    client: str,
    payload: dict[str, Any],
    error: str,
    *,
    event_id: str | None = None,
    reserved_seq: int | None = None,
    recorded_at: str | None = None,
    queued_at: str | None = None,
    event_name: str | None = None,
    hook_mode: str = "queue",
    synchronous_decision: str = "",
    synchronous_decision_data: dict[str, Any] | None = None,
) -> Path:
    queued_at_value = queued_at or utc_now()
    queue_dir = HOOK_QUEUE_DIR / safe_slug(client)
    queue_dir.mkdir(parents=True, exist_ok=True)
    seq_label = "pending"
    if reserved_seq not in (None, ""):
        try:
            seq_label = f"{int(reserved_seq):012d}"
        except (TypeError, ValueError):
            seq_label = safe_slug(str(reserved_seq))
    filename_parts = [
        (queued_at_value or utc_now()).replace(":", "-").replace("+", "Z"),
        safe_slug(seq_label),
        safe_slug(str(event_id or uuid.uuid4())),
    ]
    path = queue_dir / ("-".join(filename_parts) + ".json")
    path.write_text(
        json_dumps(
            {
                "queued_at": queued_at_value,
                "recorded_at": recorded_at or queued_at_value,
                "client_type": client,
                "session_id": str(payload.get("session_id") or ""),
                "error": error[:1000],
                "event_id": event_id,
                "reserved_seq": reserved_seq,
                "event_name": event_name,
                "hook_mode": hook_mode,
                "synchronous_decision": synchronous_decision,
                "synchronous_decision_data": synchronous_decision_data or None,
                "payload": payload,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def write_hook_queue_failure_artifact(
    client: str,
    payload: dict[str, Any],
    *,
    error: str,
    event_id: str | None = None,
    reserved_seq: int | None = None,
    recorded_at: str | None = None,
    queued_at: str | None = None,
    event_name: str | None = None,
    hook_mode: str | None = None,
    synchronous_decision: str | None = None,
) -> Path | None:
    try:
        client_dir = HOOK_QUEUE_FAILURE_DIR / safe_slug(client)
        client_dir.mkdir(parents=True, exist_ok=True)
        stamp = (utc_now()).replace(":", "-").replace("+", "Z")
        event_slug = safe_slug(str(event_id or uuid.uuid4()))
        path = client_dir / f"{stamp}-{event_slug}.json"
        path.write_text(
            json_dumps(
                {
                    "failed_at": utc_now(),
                    "client_type": client,
                    "session_id": str(payload.get("session_id") or ""),
                    "event_id": event_id or "",
                    "reserved_seq": reserved_seq,
                    "recorded_at": recorded_at or "",
                    "queued_at": queued_at or "",
                    "event_name": event_name or "",
                    "hook_mode": hook_mode or "",
                    "synchronous_decision": synchronous_decision or "",
                    "error": error[:1000],
                    "payload": payload,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return path
    except Exception:
        return None


def append_hook_queue_log(message: str, **fields: Any) -> None:
    try:
        HOOK_QUEUE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        record = {"timestamp": utc_now(), "message": message}
        for key, value in fields.items():
            if value is None:
                continue
            record[str(key)] = value
        with HOOK_QUEUE_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json_dumps(record) + "\n")
    except Exception:
        pass


def update_hook_queue_audit(
    event_id: str,
    *,
    status: str,
    processed_at: str | None = None,
    error: str | None = None,
    synchronous_decision: str | None = None,
) -> None:
    if not event_id:
        return
    conn = connect(init=not DB_PATH.exists())
    try:
        conn.execute(
            """
            update hook_queue_audit
            set status = ?,
                processed_at = coalesce(?, processed_at),
                error = coalesce(?, error),
                synchronous_decision = coalesce(?, synchronous_decision)
            where event_id = ?
            """,
            (status, processed_at, error, synchronous_decision, event_id),
        )
        conn.commit()
    finally:
        conn.close()


def load_hook_queue_item(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"queue file {path} does not contain an object")
    return loaded


def hook_queue_sort_key(path: Path, item: dict[str, Any]) -> tuple[str, str, str, int, str, str]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    session_id = str(item.get("session_id") or payload.get("session_id") or "")
    try:
        reserved_seq = int(item.get("reserved_seq")) if item.get("reserved_seq") not in (None, "") else 0
    except (TypeError, ValueError):
        reserved_seq = 0
    recorded_at = str(item.get("recorded_at") or "")
    queued_at = str(item.get("queued_at") or recorded_at or "")
    event_id = str(item.get("event_id") or "")
    return (recorded_at, queued_at, session_id, reserved_seq, event_id, path.name)


def recover_failed_hook_queue_events(*, client: str | None = None, limit: int = 200) -> dict[str, Any]:
    paths = (
        sorted((HOOK_QUEUE_FAILURE_DIR / safe_slug(client)).glob("*.json"))
        if client
        else sorted(HOOK_QUEUE_FAILURE_DIR.glob("*/*.json"))
    )
    recovered = 0
    failed = 0
    max_items = max(1, limit)
    for path in paths[:max_items]:
        try:
            item = load_hook_queue_item(path)
            payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
            queue_hook_event(
                str(item.get("client_type") or client or "unknown"),
                payload,
                str(item.get("error") or "recovered-dead-letter"),
                event_id=str(item.get("event_id") or "") or None,
                reserved_seq=item.get("reserved_seq"),
                recorded_at=str(item.get("recorded_at") or "") or None,
                queued_at=utc_now(),
                event_name=str(item.get("event_name") or "") or None,
                hook_mode=str(item.get("hook_mode") or "queue"),
                synchronous_decision=str(item.get("synchronous_decision") or ""),
            )
            event_id = str(item.get("event_id") or "")
            if event_id:
                update_hook_queue_audit(event_id, status="queued", synchronous_decision=str(item.get("synchronous_decision") or "") or None)
            append_hook_queue_log(
                "recovered dead-letter hook queue event",
                event_id=event_id,
                session_id=str(item.get("session_id") or ""),
                source_path=str(path),
            )
            path.unlink(missing_ok=True)
            recovered += 1
        except Exception as exc:
            failed += 1
            append_hook_queue_log("dead-letter recovery failed", path=str(path), error=str(exc))
    remaining = max(0, hook_queue_failed_file_count())
    return {"recovered": recovered, "failed": failed, "remaining": remaining}


def write_hook_worker_status(
    *,
    running: bool,
    reason: str,
    heartbeat_at: str | None = None,
    started_at: str | None = None,
    last_exit_at: str | None = None,
) -> None:
    HOOK_QUEUE_STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    previous: dict[str, Any] = {}
    if HOOK_QUEUE_STATUS_PATH.exists():
        try:
            previous = json.loads(HOOK_QUEUE_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    worker = previous.get("worker") if isinstance(previous.get("worker"), dict) else {}
    payload = {
        "root": str(ROOT),
        "worker": {
            "running": running,
            "pid": os.getpid() if running else worker.get("pid"),
            "started_at": started_at or worker.get("started_at") or utc_now(),
            "heartbeat_at": heartbeat_at or utc_now(),
            "last_reason": reason,
            "last_exit_at": last_exit_at or worker.get("last_exit_at") or "",
        },
    }
    if not running:
        payload["worker"]["pid"] = worker.get("pid")
        payload["worker"]["started_at"] = worker.get("started_at") or started_at or ""
        payload["worker"]["last_exit_at"] = last_exit_at or utc_now()
    HOOK_QUEUE_STATUS_PATH.write_text(json_dumps(payload) + "\n", encoding="utf-8")


def _age_seconds(value: str) -> float | None:
    if not value:
        return None
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        then = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (now - then.astimezone(timezone.utc)).total_seconds()
    except Exception:
        return None


def _oldest_file_timestamp(root: Path) -> str:
    oldest_epoch: float | None = None
    for path in root.glob("*/*.json"):
        try:
            stamp = path.stat().st_mtime
        except OSError:
            continue
        if oldest_epoch is None or stamp < oldest_epoch:
            oldest_epoch = stamp
    if oldest_epoch is None:
        return ""
    return datetime.fromtimestamp(oldest_epoch, tz=timezone.utc).isoformat()


def _tail_log_summary(path: Path, *, parse_json: bool = True, max_lines: int = 40) -> dict[str, Any]:
    summary = {"path": str(path), "exists": path.exists(), "has_error": False, "last_at": "", "last_message": ""}
    if not path.exists():
        return summary
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return summary
    for raw in reversed(lines[-max_lines:]):
        text = raw.strip()
        if not text:
            continue
        if parse_json:
            try:
                record = json.loads(text)
            except Exception:
                record = {"message": text}
            summary["last_at"] = str(record.get("timestamp") or "")
            summary["last_message"] = str(record.get("message") or text)
        else:
            summary["last_message"] = text
            if text.startswith("[") and "]" in text:
                summary["last_at"] = text[1 : text.index("]")]
        lowered = summary["last_message"].lower()
        if any(token in lowered for token in ("failed", "error", "stale", "dead-letter")):
            summary["has_error"] = True
            break
        if not summary["last_message"]:
            continue
        break
    return summary
