from __future__ import annotations

import os
import json
from datetime import datetime, timezone
from pathlib import Path

from .config import LOCK_DIR, json_dumps, safe_slug, utc_now


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def lock_path(kind: str, key: str) -> Path:
    return LOCK_DIR / f"{safe_slug(kind)}-{safe_slug(key)}.lock"


def acquire_lock(kind: str, key: str) -> Path | None:
    path = lock_path(kind, key)
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    try:
        path.mkdir()
    except FileExistsError:
        if is_stale_lock(path, kind, key):
            release_lock(path)
            try:
                path.mkdir()
            except FileExistsError:
                return None
        else:
            return None
    metadata = {"kind": kind, "key": key, "pid": os.getpid(), "created_at": utc_now()}
    (path / "metadata.json").write_text(json_dumps(metadata), encoding="utf-8")
    return path


def is_stale_lock(path: Path, kind: str, key: str) -> bool:
    """Return True when a previous process left a lock behind.

    Dream locks are authoritative through SQLite: if no matching dream run is
    currently marked running, a lock must not block later tail-window dreams.
    The age fallback covers summary locks and interrupted processes before a
    dream_run row was created.
    """
    metadata_path = path / "metadata.json"
    created_at = ""
    pid: int | None = None
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            created_at = str(metadata.get("created_at") or "")
            raw_pid = metadata.get("pid")
            pid = int(raw_pid) if raw_pid is not None else None
        except Exception:  # noqa: BLE001
            created_at = ""
            pid = None
    if kind == "dream-session":
        try:
            from .db import connect

            conn = connect()
            row = conn.execute(
                "select count(*) as c from dream_runs where session_id = ? and status = 'running'",
                (key,),
            ).fetchone()
            if row is not None and int(row["c"] or 0) == 0:
                return True
        except Exception:  # noqa: BLE001
            pass
    if pid and _pid_is_alive(pid):
        return False
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age = datetime.now(timezone.utc) - created.astimezone(timezone.utc)
            return age.total_seconds() > 900
        except ValueError:
            return True
    return False


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def release_lock(path: Path | None) -> None:
    if path is None or not path.exists():
        return
    for child in path.iterdir():
        child.unlink(missing_ok=True)
    try:
        path.rmdir()
    except FileNotFoundError:
        return

