from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..adapters.sqlite import firewall as firewall_repo
from ..infrastructure.config import utc_now


VALID_SCOPE_TYPES = {"session", "agent", "project", "workdir", "global"}
PERMANENT_OVERRIDE_EXPIRES_AT = "9999-12-31T23:59:59+00:00"


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return firewall_repo.row_dict(row)


def _firewall_status_raw(conn: sqlite3.Connection) -> dict[str, Any]:
    row = firewall_repo.firewall_state(conn)
    if not row:
        return {
            "enabled": True,
            "updated_at": None,
            "updated_by": None,
            "reason": "default enabled",
            "disabled_until": None,
            "source": "default",
        }
    return {
        "enabled": bool(row["enabled"]),
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
        "reason": row["reason"],
        "disabled_until": row["disabled_until"] if "disabled_until" in row.keys() else None,
        "source": row["source"],
    }


def firewall_status(conn: sqlite3.Connection) -> dict[str, Any]:
    raw = _firewall_status_raw(conn)
    enabled = bool(raw["enabled"])
    disabled_until = raw.get("disabled_until")
    if enabled or not disabled_until:
        return raw
    try:
        until = datetime.fromisoformat(str(disabled_until).replace("Z", "+00:00"))
    except ValueError:
        until = None
    if until is not None and until <= datetime.now(timezone.utc):
        set_firewall_enabled(conn, enabled=True, actor="system", reason="disable window expired", source="expiry")
        return firewall_status(conn)
    return raw


def firewall_enabled(conn: sqlite3.Connection) -> bool:
    return bool(firewall_status(conn)["enabled"])


def set_firewall_enabled(
    conn: sqlite3.Connection,
    *,
    enabled: bool,
    actor: str = "monitor",
    reason: str = "",
    source: str = "monitor",
    disabled_minutes: int | None = None,
    permanent_disable: bool = False,
) -> dict[str, Any]:
    previous = _firewall_status_raw(conn)
    now = utc_now()
    disabled_until = None
    if not enabled:
        if permanent_disable:
            disabled_until = None
        else:
            minutes = max(1, min(int(disabled_minutes or 30), 240))
            disabled_until = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
    firewall_repo.upsert_firewall_state(
        conn,
        enabled=enabled,
        updated_at=now,
        updated_by=actor,
        reason=reason,
        disabled_until=disabled_until,
        source=source,
    )
    firewall_repo.insert_firewall_audit(
        conn,
        audit_id=f"fwaudit_{uuid.uuid4().hex[:16]}",
        created_at=now,
        actor=actor,
        action="enable" if enabled else "disable",
        previous_enabled=bool(previous["enabled"]),
        new_enabled=enabled,
        reason=reason,
        disabled_until=disabled_until,
        source=source,
    )
    return firewall_status(conn)


def firewall_audit(conn: sqlite3.Connection, limit: int = 20) -> list[dict[str, Any]]:
    return [_row_dict(row) for row in firewall_repo.firewall_audit_rows(conn, limit=limit)]


def _expires_at(minutes: int | None, *, permanent: bool = False) -> str:
    if permanent:
        return PERMANENT_OVERRIDE_EXPIRES_AT
    safe_minutes = max(1, min(int(minutes or 30), 240))
    return (datetime.now(timezone.utc) + timedelta(minutes=safe_minutes)).isoformat()


def create_firewall_override(
    conn: sqlite3.Connection,
    *,
    scope_type: str,
    reason: str,
    actor: str = "monitor",
    source: str = "monitor",
    disabled_minutes: int | None = None,
    permanent_disable: bool = False,
    session_id: str | None = None,
    client_type: str | None = None,
    agent_name: str | None = None,
    thread_name: str | None = None,
    project_id: str | None = None,
    workdir: str | None = None,
) -> dict[str, Any]:
    scope = (scope_type or "").strip().lower()
    if scope not in VALID_SCOPE_TYPES:
        raise ValueError(f"invalid firewall override scope: {scope_type}")
    if not reason.strip():
        raise ValueError("reason is required")
    if source != "monitor":
        raise ValueError("firewall overrides can only be created by monitor")
    if scope == "session" and not session_id:
        raise ValueError("session_id is required for session firewall override")
    if scope == "agent" and not (client_type or agent_name or thread_name):
        raise ValueError("client_type, agent_name, or thread_name is required for agent firewall override")
    if scope == "project" and not project_id:
        raise ValueError("project_id is required for project firewall override")
    if scope == "workdir" and not workdir:
        raise ValueError("workdir is required for workdir firewall override")
    now = utc_now()
    oid = f"fwovr_{uuid.uuid4().hex[:16]}"
    expires_at = _expires_at(disabled_minutes, permanent=permanent_disable)
    firewall_repo.insert_firewall_override(
        conn,
        override_id=oid,
        created_at=now,
        updated_at=now,
        expires_at=expires_at,
        scope_type=scope,
        session_id=session_id or None,
        client_type=client_type or None,
        agent_name=agent_name or None,
        thread_name=thread_name or None,
        project_id=project_id or None,
        workdir=workdir or None,
        reason=reason,
        created_by=actor or "monitor",
        source=source,
    )
    firewall_repo.insert_firewall_override_audit(
        conn,
        audit_id=f"fwoaudit_{uuid.uuid4().hex[:16]}",
        override_id=oid,
        created_at=now,
        action="create",
        actor=actor or "monitor",
        reason=reason,
    )
    row = firewall_repo.firewall_override(conn, override_id=oid)
    data = _row_dict(row)
    data["permanent"] = bool(permanent_disable)
    return data


def revoke_firewall_override(conn: sqlite3.Connection, override_id: str, *, actor: str = "monitor", reason: str = "") -> dict[str, Any]:
    now = utc_now()
    firewall_repo.disable_firewall_override(conn, override_id=override_id, updated_at=now)
    firewall_repo.insert_firewall_override_audit(
        conn,
        audit_id=f"fwoaudit_{uuid.uuid4().hex[:16]}",
        override_id=override_id,
        created_at=now,
        action="revoke",
        actor=actor or "monitor",
        reason=reason,
    )
    row = firewall_repo.firewall_override(conn, override_id=override_id)
    if not row:
        raise ValueError(f"unknown firewall override: {override_id}")
    return _row_dict(row)


def firewall_overrides(conn: sqlite3.Connection, *, include_expired: bool = False, limit: int = 100) -> list[dict[str, Any]]:
    now = utc_now()
    rows = firewall_repo.firewall_override_rows(conn, include_expired=include_expired, now=now, limit=limit)
    items = [_row_dict(row) for row in rows]
    for item in items:
        item["permanent"] = str(item.get("expires_at") or "") == PERMANENT_OVERRIDE_EXPIRES_AT
    return items


def firewall_override_audit(conn: sqlite3.Connection, limit: int = 30) -> list[dict[str, Any]]:
    rows = firewall_repo.firewall_override_audit_rows(conn, limit=limit)
    return [_row_dict(row) for row in rows]


def _matches_path(scope_path: str | None, current_path: str | None) -> bool:
    if not scope_path or not current_path:
        return False
    base = scope_path.rstrip("/")
    current = current_path.rstrip("/")
    return current == base or current.startswith(base + "/")


def active_firewall_override(
    conn: sqlite3.Connection,
    *,
    session_id: str | None = None,
    client_type: str | None = None,
    agent_name: str | None = None,
    thread_name: str | None = None,
    project_id: str | None = None,
    workdir: str | None = None,
) -> dict[str, Any] | None:
    rows = firewall_overrides(conn, include_expired=False, limit=250)
    for row in rows:
        scope = row.get("scope_type")
        if scope == "global":
            return row
        if scope == "session" and row.get("session_id") and row.get("session_id") == session_id:
            return row
        if scope == "agent":
            if row.get("client_type") and row.get("client_type") != client_type:
                continue
            if row.get("agent_name") and row.get("agent_name") not in {agent_name, thread_name}:
                continue
            if row.get("thread_name") and row.get("thread_name") != thread_name:
                continue
            if row.get("project_id") and row.get("project_id") != project_id:
                continue
            if row.get("workdir") and not _matches_path(row.get("workdir"), workdir):
                continue
            return row
        if scope == "project" and row.get("project_id") and row.get("project_id") == project_id:
            return row
        if scope == "workdir" and _matches_path(row.get("workdir"), workdir):
            return row
    return None
