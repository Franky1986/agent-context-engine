from __future__ import annotations

import sqlite3
from typing import Any


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def firewall_state(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("select * from firewall_state where id = 1").fetchone()


def upsert_firewall_state(
    conn: sqlite3.Connection,
    *,
    enabled: bool,
    updated_at: str,
    updated_by: str,
    reason: str,
    disabled_until: str | None,
    source: str,
) -> None:
    conn.execute(
        """
        insert into firewall_state (id, enabled, updated_at, updated_by, reason, disabled_until, source)
        values (1, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
          enabled = excluded.enabled,
          updated_at = excluded.updated_at,
          updated_by = excluded.updated_by,
          reason = excluded.reason,
          disabled_until = excluded.disabled_until,
          source = excluded.source
        """,
        (1 if enabled else 0, updated_at, updated_by, reason, disabled_until, source),
    )


def insert_firewall_audit(
    conn: sqlite3.Connection,
    *,
    audit_id: str,
    created_at: str,
    actor: str,
    action: str,
    previous_enabled: bool,
    new_enabled: bool,
    reason: str,
    disabled_until: str | None,
    source: str,
) -> None:
    conn.execute(
        """
        insert into firewall_audit (
          audit_id, created_at, actor, action, previous_enabled, new_enabled, reason, disabled_until, source
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            audit_id,
            created_at,
            actor,
            action,
            1 if previous_enabled else 0,
            1 if new_enabled else 0,
            reason,
            disabled_until,
            source,
        ),
    )


def firewall_audit_rows(conn: sqlite3.Connection, *, limit: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            select *
            from firewall_audit
            order by created_at desc
            limit ?
            """,
            (max(1, min(int(limit), 100)),),
        )
    )


def insert_firewall_override(
    conn: sqlite3.Connection,
    *,
    override_id: str,
    created_at: str,
    updated_at: str,
    expires_at: str,
    scope_type: str,
    reason: str,
    created_by: str,
    source: str,
    session_id: str | None = None,
    client_type: str | None = None,
    agent_name: str | None = None,
    thread_name: str | None = None,
    project_id: str | None = None,
    workdir: str | None = None,
) -> None:
    conn.execute(
        """
        insert into firewall_overrides (
          override_id, created_at, updated_at, expires_at, enabled, scope_type,
          session_id, client_type, agent_name, thread_name, project_id, workdir,
          reason, created_by, source
        ) values (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            override_id,
            created_at,
            updated_at,
            expires_at,
            scope_type,
            session_id,
            client_type,
            agent_name,
            thread_name,
            project_id,
            workdir,
            reason,
            created_by,
            source,
        ),
    )


def insert_firewall_override_audit(
    conn: sqlite3.Connection,
    *,
    audit_id: str,
    override_id: str,
    created_at: str,
    action: str,
    actor: str,
    reason: str,
) -> None:
    conn.execute(
        """
        insert into firewall_override_audit (audit_id, override_id, created_at, action, actor, reason)
        values (?, ?, ?, ?, ?, ?)
        """,
        (audit_id, override_id, created_at, action, actor, reason),
    )


def firewall_override(conn: sqlite3.Connection, *, override_id: str) -> sqlite3.Row | None:
    return conn.execute("select * from firewall_overrides where override_id = ?", (override_id,)).fetchone()


def disable_firewall_override(conn: sqlite3.Connection, *, override_id: str, updated_at: str) -> None:
    conn.execute(
        "update firewall_overrides set enabled = 0, updated_at = ? where override_id = ?",
        (updated_at, override_id),
    )


def firewall_override_rows(
    conn: sqlite3.Connection,
    *,
    include_expired: bool,
    now: str,
    limit: int,
) -> list[sqlite3.Row]:
    where = "" if include_expired else "where enabled = 1 and (expires_at = '9999-12-31T23:59:59+00:00' or datetime(expires_at) > datetime(?))"
    params: tuple[Any, ...] = () if include_expired else (now,)
    return list(
        conn.execute(
            f"""
            select *
            from firewall_overrides
            {where}
            order by datetime(expires_at) desc, created_at desc
            limit ?
            """,
            (*params, max(1, min(int(limit), 250))),
        )
    )


def firewall_override_audit_rows(conn: sqlite3.Connection, *, limit: int) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            select *
            from firewall_override_audit
            order by created_at desc
            limit ?
            """,
            (max(1, min(int(limit), 100)),),
        )
    )
