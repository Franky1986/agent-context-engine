from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ...infrastructure.config import CODEX_SESSION_INDEX, MEMORY_DIR, ROOT, json_dumps


def _normalize_path_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return str(Path(value).expanduser())


def _path_overlaps(folder: str, candidate: str | None) -> bool:
    folder = _normalize_path_text(folder)
    candidate = _normalize_path_text(candidate)
    if not folder or not candidate:
        return False
    return candidate == folder or candidate.startswith(folder + "/") or folder.startswith(candidate + "/")


def codex_runtime_home() -> Path:
    override = os.environ.get("AGENT_MEMORY_CODEX_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (MEMORY_DIR / "local" / "codex-home").resolve()


def _sync_codex_runtime_file(source: Path, target: Path) -> None:
    if not source.exists() or not source.is_file():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        try:
            if target.resolve() == source.resolve():
                return
        except OSError:
            pass
        target.unlink()
    if not target.exists():
        try:
            target.symlink_to(source)
        except OSError:
            shutil.copy2(source, target)
        return
    if not target.is_file():
        return
    try:
        source_stat = source.stat()
        target_stat = target.stat()
    except OSError:
        return
    if source_stat.st_size != target_stat.st_size or source_stat.st_mtime_ns > target_stat.st_mtime_ns:
        shutil.copy2(source, target)


def prepare_codex_runtime_home() -> Path:
    runtime_home = codex_runtime_home()
    runtime_home.mkdir(parents=True, exist_ok=True)
    source_home = Path.home() / ".codex"
    for name in ("auth.json", "installation_id", "version.json"):
        _sync_codex_runtime_file(source_home / name, runtime_home / name)
    return runtime_home


def codex_subprocess_env(
    *,
    base_env: dict[str, str] | None = None,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = dict(base_env or os.environ)
    _prepend_windows_command_paths(env)
    env["CODEX_HOME"] = str(prepare_codex_runtime_home())
    if extra:
        env.update(extra)
    return env


def _prepend_windows_command_paths(env: dict[str, str]) -> None:
    if os.name != "nt":
        return
    candidates: list[str] = []
    appdata = env.get("APPDATA") or os.environ.get("APPDATA")
    userprofile = env.get("USERPROFILE") or os.environ.get("USERPROFILE")
    if appdata:
        candidates.append(os.path.join(appdata, "npm"))
    if userprofile:
        candidates.append(os.path.join(userprofile, ".local", "bin"))
    existing = env.get("PATH") or env.get("Path") or ""
    existing_parts = [part for part in existing.split(os.pathsep) if part]
    existing_norm = {os.path.normcase(os.path.normpath(part)) for part in existing_parts}
    prefix = [
        path
        for path in candidates
        if path and os.path.normcase(os.path.normpath(path)) not in existing_norm
    ]
    if prefix:
        env["PATH"] = os.pathsep.join(prefix + existing_parts)


def codex_thread_name(session_id: str) -> str | None:
    if not CODEX_SESSION_INDEX.exists():
        return None
    found: str | None = None
    with CODEX_SESSION_INDEX.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if session_id not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("id") == session_id and row.get("thread_name"):
                found = str(row["thread_name"])
    return found


def codex_session_id_from_path(path: Path) -> str | None:
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$", path.name)
    return match.group(1) if match else None


def text_from_codex_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
        return "\n".join(parts)
    return ""


def codex_transcript_info(path: Path) -> dict[str, object] | None:
    session_id = codex_session_id_from_path(path)
    if not session_id:
        return None
    info: dict[str, object] = {
        "session_id": session_id,
        "path": str(path),
        "cwd": "",
        "started_at": "",
        "last_at": "",
        "hint": "",
    }
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = str(row.get("timestamp") or "")
            if timestamp:
                info["last_at"] = timestamp
                if not info["started_at"]:
                    info["started_at"] = timestamp
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            cwd = payload.get("cwd") or row.get("cwd")
            if isinstance(cwd, str) and cwd:
                info["cwd"] = cwd
            if row.get("type") == "turn_context" and isinstance(payload.get("cwd"), str):
                info["cwd"] = payload["cwd"]
            message = payload if payload.get("type") == "message" else payload.get("message")
            if isinstance(message, dict) and message.get("role") == "user":
                text = text_from_codex_content(message.get("content"))
                if text.strip():
                    info["hint"] = re.sub(r"\s+", " ", text).strip()[:180]
            if payload.get("type") == "task_complete" and payload.get("last_agent_message") and not info["hint"]:
                info["hint"] = re.sub(r"\s+", " ", str(payload["last_agent_message"])).strip()[:180]
    return info


def iter_codex_transcript_messages(path: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    info = codex_transcript_info(path) or {}
    messages: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = str(row.get("timestamp") or info.get("last_at") or "")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            message = payload if payload.get("type") == "message" else payload.get("message")
            if isinstance(message, dict) and message.get("role") in {"user", "assistant"}:
                text = text_from_codex_content(message.get("content"))
                if not text.strip():
                    continue
                messages.append(
                    {
                        "line_no": line_no,
                        "timestamp": timestamp,
                        "role": message.get("role"),
                        "text": text,
                        "raw": payload,
                    }
                )
    return info, messages


def discover_codex_transcripts_for_folder(folder: str, known_session_ids: set[str], limit: int) -> list[dict[str, object]]:
    base = Path.home() / ".codex" / "sessions"
    if not base.exists():
        return []
    matches: list[dict[str, object]] = []
    for path in sorted(base.glob("**/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        info = codex_transcript_info(path)
        if not info or str(info["session_id"]) in known_session_ids:
            continue
        if _path_overlaps(folder, str(info.get("cwd") or "")):
            matches.append(info)
            if len(matches) >= limit:
                break
    return matches


def detect_client_version(client: str) -> str | None:
    exe = shutil.which(client)
    if not exe:
        return None
    for args in ([exe, "--version"], [exe, "version"]):
        try:
            proc = subprocess.run(args, text=True, capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            continue
        output = (proc.stdout or proc.stderr).strip()
        if proc.returncode == 0 and output:
            return output.splitlines()[0][:200]
    return None


def sync_transcript_metrics(conn: sqlite3.Connection, session_id: str, transcript_path: str) -> None:
    path = Path(transcript_path)
    if not path.exists():
        return
    current_turn_id: str | None = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = row.get("timestamp")
            row_type = row.get("type")
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            if row_type == "turn_context" and payload.get("turn_id"):
                current_turn_id = str(payload["turn_id"])
                continue
            if row_type != "event_msg":
                continue
            event_type = payload.get("type")
            if event_type == "task_started" and payload.get("turn_id"):
                turn_id = str(payload["turn_id"])
                current_turn_id = turn_id
                with conn:
                    conn.execute(
                        """
                        insert into turn_metrics (
                          session_id, turn_id, started_at, raw_started_json
                        ) values (?, ?, ?, ?)
                        on conflict(session_id, turn_id) do update set
                          started_at = coalesce(excluded.started_at, turn_metrics.started_at),
                          raw_started_json = excluded.raw_started_json
                        """,
                        (session_id, turn_id, timestamp, json_dumps(payload)),
                    )
            elif event_type == "task_complete" and payload.get("turn_id"):
                turn_id = str(payload["turn_id"])
                with conn:
                    conn.execute(
                        """
                        insert into turn_metrics (
                          session_id, turn_id, completed_at, duration_ms,
                          time_to_first_token_ms, last_agent_message, raw_complete_json
                        ) values (?, ?, ?, ?, ?, ?, ?)
                        on conflict(session_id, turn_id) do update set
                          completed_at = excluded.completed_at,
                          duration_ms = excluded.duration_ms,
                          time_to_first_token_ms = excluded.time_to_first_token_ms,
                          last_agent_message = excluded.last_agent_message,
                          raw_complete_json = excluded.raw_complete_json
                        """,
                        (
                            session_id,
                            turn_id,
                            timestamp,
                            payload.get("duration_ms"),
                            payload.get("time_to_first_token_ms"),
                            payload.get("last_agent_message"),
                            json_dumps(payload),
                        ),
                    )
            elif event_type == "token_count":
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                usage = info.get("last_token_usage") or info.get("total_token_usage")
                if not isinstance(usage, dict):
                    continue
                with conn:
                    conn.execute(
                        """
                        insert or ignore into token_usage (
                          session_id, turn_id, recorded_at, input_tokens,
                          cached_input_tokens, output_tokens, reasoning_output_tokens,
                          total_tokens, model_context_window, raw_json
                        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            current_turn_id,
                            timestamp,
                            usage.get("input_tokens"),
                            usage.get("cached_input_tokens"),
                            usage.get("output_tokens"),
                            usage.get("reasoning_output_tokens"),
                            usage.get("total_tokens"),
                            info.get("model_context_window"),
                            json_dumps(payload),
                        ),
                    )


def transcript_mtime(path_text: str | None) -> str | None:
    if not path_text:
        return None
    path = Path(path_text)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
