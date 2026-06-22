from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .classifier import deterministic_classifier
from .firewall import (
    create_firewall_override,
    firewall_audit,
    firewall_override_audit,
    firewall_overrides,
    firewall_status,
    revoke_firewall_override,
    set_firewall_enabled,
)
from .firewall_rules import create_firewall_rule_version, disable_firewall_rule, get_firewall_rule, list_firewall_rules, suggest_firewall_rules
from ..ports.clock import Clock
from ..ports.filesystem import FileSystem
from ..ports.repositories.sqlite import SQLiteConnectionProvider
from .risk import record_risk_event, scan_text, scan_tool_input


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        return _utc_now()


class _DefaultFileSystem(FileSystem):
    def exists(self, path: Path) -> bool:
        return path.exists()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8")

    def write_text(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)


class _RequestDbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        from ..adapters.sqlite.request_db import connect

        if "init" not in kwargs:
            kwargs["init"] = True
        return connect(*args, **kwargs)


def _default_clock() -> Clock:
    return _DefaultClock()


def _default_file_system() -> FileSystem:
    return _DefaultFileSystem()


def _default_db_provider() -> SQLiteConnectionProvider:
    return _RequestDbProvider()


def _memory_dir() -> Path:
    from ..infrastructure.config import MEMORY_DIR

    return MEMORY_DIR


def _json_dumps(value: Any) -> str:
    from ..infrastructure.config import json_dumps

    return json_dumps(value)


def _utc_now() -> str:
    from ..infrastructure.config import utc_now

    return utc_now()


def _now() -> str:
    return _default_clock().utc_now()


def _row_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def _connect_monitor_db(required_table: str = "firewall_state", db_provider: SQLiteConnectionProvider | None = None) -> Any:
    provider = db_provider or _default_db_provider()
    conn = provider.connect()
    exists = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (required_table,),
    ).fetchone()
    if exists is None:
        conn.close()
        raise RuntimeError(f"monitor database is not initialized: missing table {required_table}")
    return conn


def _builtin_firewall_policy_rows() -> list[dict[str, Any]]:
    return [
        {
            "rule_id": "builtin:simple-read-only-shell",
            "name": "Simple local read-only shell",
            "source": "builtin_classifier",
            "status": "active",
            "rule_kind": "builtin",
            "scope_type": "global",
            "description": "Deterministic allowlist for local read-only commands without shell side effects.",
            "allowed_actions_json": json.dumps(["read"]),
            "allowed_hosts_json": json.dumps([]),
            "command_patterns_json": json.dumps(
                [
                    "pwd",
                    "ls",
                    "cat",
                    "head",
                    "tail",
                    "sed -n ...p",
                    "rg",
                    "find",
                    "nl",
                    "git read-only",
                    "read-only pipelines with sort/uniq/wc/head/tail/sed/rg/cat",
                ]
            ),
            "expires_at": None,
            "match_count": None,
            "last_matched_at": None,
            "audit_note": "Code policy in agent_context_engine.domain.risk; matches are audited as risk_events/classifier_runs, not firewall_rule_audit.",
        },
        {
            "rule_id": "builtin:verification-shell",
            "name": "Local verification commands",
            "source": "builtin_classifier",
            "status": "active",
            "rule_kind": "builtin",
            "scope_type": "global",
            "description": "Deterministic allowlist for local verification without install, deploy, delete, or network shell actions.",
            "allowed_actions_json": json.dumps(["verify"]),
            "allowed_hosts_json": json.dumps([]),
            "command_patterns_json": json.dumps(["npm test/lint/audit/check", "bun test", "pnpm/yarn verification", "tsc --noEmit"]),
            "expires_at": None,
            "match_count": None,
            "last_matched_at": None,
            "audit_note": "Code policy in agent_context_engine.domain.risk.",
        },
        {
            "rule_id": "builtin:agent-memory-cli-readonly",
            "name": "Agent Context Engine CLI read-only",
            "source": "builtin_classifier",
            "status": "active",
            "rule_kind": "builtin",
            "scope_type": "global",
            "description": "Agent Context Engine CLI read and diagnostic commands may continue after classification; mutating approval and firewall commands remain blocked.",
            "allowed_actions_json": json.dumps(["read", "verify"]),
            "allowed_hosts_json": json.dumps([]),
            "command_patterns_json": json.dumps(["./scripts/agent-context-engine doctor/search/retrieve/last/..."]),
            "expires_at": None,
            "match_count": None,
            "last_matched_at": None,
            "audit_note": "Code policy in agent_context_engine.domain.risk.",
        },
        {
            "rule_id": "builtin:secret-permission-hardening",
            "name": "Secret permission hardening",
            "source": "builtin_classifier",
            "status": "active",
            "rule_kind": "builtin",
            "scope_type": "global",
            "description": "Lokales chmod 600/0600 auf secret-artige Dateien ohne Shell-Komposition.",
            "allowed_actions_json": json.dumps(["protect_secret"]),
            "allowed_hosts_json": json.dumps([]),
            "command_patterns_json": json.dumps(["chmod 600 *.env/*.key/*.pem/*.token", "chmod go-rwx trello.env"]),
            "expires_at": None,
            "match_count": None,
            "last_matched_at": None,
            "audit_note": "Code policy in agent_context_engine.domain.risk.",
        },
    ]


def _safe_json_list(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if str(item).strip()]
    if raw is None:
        return []
    try:
        loaded = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if str(item).strip()]


def _safe_json_value(raw: Any) -> Any:
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, json.JSONDecodeError):
        return []


def _rule_origin(row: dict[str, Any]) -> str:
    source = str(row.get("source") or "").strip()
    if source and source != "firewall_rules":
        return source
    if str(row.get("source_line") or "").strip():
        return "firewall_add"
    return "firewall_add"


def _rule_effect(row: dict[str, Any]) -> str:
    denied = _safe_json_list(row.get("denied_actions_json"))
    if denied:
        return "deny"
    return "allow"


def _rule_origin_label(origin: str) -> str:
    match = str(origin or "").strip()
    return {
        "firewall_add": "Firewall Add",
        "firewall_rules": "Firewall Add",
        "builtin_classifier": "Builtin (Classifier)",
        "risk_allowlist_file": "Policy File",
        "builtin": "Builtin",
    }.get(match, match or "Unknown")


def _rule_effect_label(effect: str) -> str:
    return {"deny": "Deny", "allow": "Allow"}.get(str(effect or "").strip(), "Unknown")


def _enrich_firewall_rule_row(row: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(row)
    origin = _rule_origin(enriched)
    effect = _rule_effect(enriched)
    enriched["origin"] = origin
    enriched["origin_label"] = _rule_origin_label(origin)
    enriched["rule_effect"] = effect
    enriched["rule_effect_label"] = _rule_effect_label(effect)
    return enriched


def _risk_allowlist_policy_rows(
    memory_dir: Path | None = None,
    file_system: FileSystem | None = None,
) -> list[dict[str, Any]]:
    fs = file_system or _default_file_system()
    base_dir = memory_dir or _memory_dir()
    path = base_dir / "policies" / "risk-allowlist.json"
    if not fs.exists(path):
        return []
    try:
        data = json.loads(fs.read_text(path))
    except (OSError, json.JSONDecodeError):
        return [
            {
                "rule_id": "policy:risk-allowlist:invalid",
                "name": "risk-allowlist.json invalid",
                "source": "risk_allowlist_file",
                "status": "invalid",
                "rule_kind": "policy_file",
                "scope_type": "file",
                "description": str(path),
                "allowed_actions_json": json.dumps([]),
                "allowed_hosts_json": json.dumps([]),
                "command_patterns_json": json.dumps([]),
                "expires_at": None,
                "match_count": None,
                "last_matched_at": None,
                "audit_note": "Policy file could not be parsed.",
            }
        ]
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "rule_id": f"policy:risk-allowlist:{index + 1}",
                "name": str(entry.get("name") or entry.get("id") or entry.get("command_pattern") or f"risk allowlist {index + 1}"),
                "source": "risk_allowlist_file",
                "status": "disabled" if entry.get("enabled") is False else "active",
                "rule_kind": "policy_file",
                "scope_type": "workdir" if entry.get("workdir_prefix") else "global",
                "description": str(entry.get("reason") or ""),
                "allowed_actions_json": json.dumps([str(entry.get("action") or "policy_allowlist")]),
                "allowed_hosts_json": json.dumps([]),
                "command_patterns_json": json.dumps([str(entry.get("command_pattern") or ""), *[str(item) for item in entry.get("command_hashes") or [] if item]]),
                "expires_at": entry.get("expires_at"),
                "workdir_prefix": entry.get("workdir_prefix"),
                "match_count": None,
                "last_matched_at": None,
                "audit_note": f"Loaded from {path}. Matches are audited as risk_events approval_state=policy_allowlisted.",
            }
        )
    return rows


def monitor_effective_fixed_rules() -> list[dict[str, Any]]:
    return [_enrich_firewall_rule_row(row) for row in (*_builtin_firewall_policy_rows(), *_risk_allowlist_policy_rows())]


def monitor_risk_events(
    limit: int = 100,
    status: str | None = None,
    client_type: str | None = None,
    category: str | None = None,
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    where = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if client_type:
        where.append("client_type = ?")
        params.append(client_type)
    if category:
        where.append("categories_json like ?")
        params.append(f"%{category}%")
    where_sql = "where " + " and ".join(where) if where else ""
    events = [
        _decorate_risk_row(row)
        for row in conn.execute(
            f"""
            select *
            from risk_events
            {where_sql}
            order by created_at desc
            limit ?
            """,
            (*params, max(1, min(limit, 500))),
        )
    ]
    totals = {
        row["status"]: row["c"]
        for row in conn.execute(
            f"""
            select status, count(*) as c
            from risk_events
            {where_sql}
            group by status
            """,
            params,
        )
    }
    classifier_totals = conn.execute(
        """
        select count(*) as runs, coalesce(sum(total_tokens), 0) as total_tokens,
               coalesce(sum(duration_ms), 0) as duration_ms
        from classifier_runs
        """
    ).fetchone()
    active_rules = [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=None, limit=200)]
    deterministic_rules = [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=None, rule_kind="deterministic", limit=250)]
    llm_rules = [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=None, rule_kind="llm_context", limit=250)]
    return {
        "events": events,
        "total": sum(int(value) for value in totals.values()),
        "totals": totals,
        "classifier_totals": _row_dict(classifier_totals),
        "firewall": {
            **firewall_status(conn),
            "audit": firewall_audit(conn, limit=10),
            "overrides": firewall_overrides(conn, limit=50),
            "override_audit": firewall_override_audit(conn, limit=10),
            "rules": list(active_rules),
            "deterministic_rules": list(deterministic_rules),
            "effective_fixed_rules": monitor_effective_fixed_rules(),
            "llm_rules": list(llm_rules),
            "suggestions": monitor_firewall_suggestions(limit=20, db_provider=db_provider)["suggestions"],
        },
    }


def monitor_firewall_state(*, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any]:
    conn = _connect_monitor_db(db_provider=db_provider)
    deterministic_rules = [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=None, rule_kind="deterministic", limit=100)]
    llm_rules = [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=None, rule_kind="llm_context", limit=100)]
    return {
        **firewall_status(conn),
        "audit": firewall_audit(conn, limit=30),
        "overrides": firewall_overrides(conn, limit=100),
        "override_audit": firewall_override_audit(conn, limit=30),
        "rules": [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=None, limit=100)],
        "deterministic_rules": deterministic_rules,
        "effective_fixed_rules": monitor_effective_fixed_rules(),
        "llm_rules": llm_rules,
        "suggestions": monitor_firewall_suggestions(limit=20, db_provider=db_provider)["suggestions"],
    }


def monitor_firewall_rules(
    status: str | None = None,
    rule_kind: str | None = None,
    limit: int = 100,
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db("firewall_rules", db_provider=db_provider)
    active_rules = [_enrich_firewall_rule_row(row) for row in list_firewall_rules(conn, status=status, rule_kind=rule_kind, limit=limit)]
    return {"rules": list(active_rules)}


def monitor_firewall_rule(rule_id: str, *, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any]:
    conn = _connect_monitor_db("firewall_rules", db_provider=db_provider)
    rule = get_firewall_rule(conn, rule_id)
    if not rule:
        return {"error": "not found"}
    rule = _enrich_firewall_rule_row(rule)
    return {"rule": rule}


def monitor_firewall_suggestions(limit: int = 20, *, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any]:
    conn = _connect_monitor_db("firewall_rule_suggestions", db_provider=db_provider)
    rows = [
        _row_dict(row)
        for row in conn.execute(
            """
            select *
            from firewall_rule_suggestions
            order by created_at desc
            limit ?
            """,
            (max(1, min(int(limit), 100)),),
        )
    ]
    return {"suggestions": rows}


def monitor_firewall_suggest(
    payload: dict[str, Any],
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db("firewall_rule_suggestions", db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        data = suggest_firewall_rules(
            conn,
            since=str(payload.get("since") or "") or None,
            until=str(payload.get("until") or "") or None,
            session_id=str(payload.get("session_id") or "") or None,
            workdir=str(payload.get("workdir") or "") or None,
            host=str(payload.get("host") or "") or None,
            action=str(payload.get("action") or "") or None,
            limit=int(payload.get("limit") or 50),
            store=True,
        )
        conn.commit()
        return data
    except Exception:
        conn.rollback()
        raise


def monitor_disable_firewall_rule(
    payload: dict[str, Any],
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db("firewall_rules", db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        rule = disable_firewall_rule(
            conn,
            str(payload.get("rule_id") or ""),
            actor=str(payload.get("actor") or "monitor"),
            reason=str(payload.get("reason") or ""),
            session_id=str(payload.get("session_id") or "") or None,
            event_seq=None,
        )
        conn.commit()
        return {"rule": rule, "firewall": monitor_firewall_state(db_provider=db_provider)}
    except Exception:
        conn.rollback()
        raise


def monitor_firewall_rule_version(
    payload: dict[str, Any],
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db("firewall_rules", db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        rule = create_firewall_rule_version(
            conn,
            str(payload.get("rule_id") or ""),
            dict(payload.get("updates") or {}),
            actor=str(payload.get("actor") or "monitor"),
            reason=str(payload.get("reason") or ""),
            session_id=str(payload.get("session_id") or "") or None,
            event_seq=None,
        )
        conn.commit()
        return {"rule": rule, "firewall": monitor_firewall_state(db_provider=db_provider)}
    except Exception:
        conn.rollback()
        raise


def monitor_set_firewall_state(
    enabled: bool,
    actor: str,
    reason: str,
    disabled_minutes: int | None = None,
    permanent_disable: bool = False,
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db(db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        state = set_firewall_enabled(
            conn,
            enabled=enabled,
            actor=actor or "monitor",
            reason=reason or ("enabled by monitor" if enabled else "disabled by monitor"),
            source="monitor",
            disabled_minutes=disabled_minutes,
            permanent_disable=permanent_disable,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        **state,
        "audit": firewall_audit(conn, limit=30),
        "overrides": firewall_overrides(conn, limit=100),
        "override_audit": firewall_override_audit(conn, limit=30),
    }


def monitor_create_firewall_override(
    payload: dict[str, Any],
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db(db_provider=db_provider)
    try:
        scope_type = str(payload.get("scope_type") or "")
        reason = str(payload.get("reason") or "").strip()
        if not reason:
            reason = f"temporary scoped override via monitor: {scope_type or 'unknown scope'}"
        conn.execute("begin immediate")
        override = create_firewall_override(
            conn,
            scope_type=scope_type,
            session_id=str(payload.get("session_id") or "") or None,
            client_type=str(payload.get("client_type") or "") or None,
            agent_name=str(payload.get("agent_name") or "") or None,
            thread_name=str(payload.get("thread_name") or "") or None,
            project_id=str(payload.get("project_id") or "") or None,
            workdir=str(payload.get("workdir") or "") or None,
            actor=str(payload.get("actor") or "monitor"),
            reason=reason,
            source="monitor",
            disabled_minutes=int(payload.get("disabled_minutes") or 30),
        )
        conn.commit()
        return {"override": override, "firewall": monitor_firewall_state(db_provider=db_provider)}
    except Exception:
        conn.rollback()
        raise


def monitor_revoke_firewall_override(
    payload: dict[str, Any],
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db(db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        override = revoke_firewall_override(
            conn,
            str(payload.get("override_id") or ""),
            actor=str(payload.get("actor") or "monitor"),
            reason=str(payload.get("reason") or "revoked by monitor"),
        )
        conn.commit()
        return {"override": override, "firewall": monitor_firewall_state(db_provider=db_provider)}
    except Exception:
        conn.rollback()
        raise


def _risk_graph(row: Any, evidence: list[dict[str, Any]], classifier: dict[str, Any] | None, overrides: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [
        {"id": row["risk_event_id"], "type": "RiskEvent", "label": row["status"]},
        {"id": f"source:{row['source_ref'] or row['source_kind']}", "type": "Source", "label": row["source_kind"]},
    ]
    links = [{"source": row["risk_event_id"], "target": nodes[1]["id"], "type": "FROM_SOURCE"}]
    if row["classifier_run_id"]:
        nodes.append({"id": row["classifier_run_id"], "type": "ClassifierRun", "label": row["decision"]})
        links.append({"source": row["classifier_run_id"], "target": row["risk_event_id"], "type": "CLASSIFIED"})
    for item in evidence[:8]:
        eid = item.get("evidence_id") or f"evidence:{len(nodes)}"
        nodes.append({"id": eid, "type": "Evidence", "label": item.get("field") or "evidence"})
        links.append({"source": row["risk_event_id"], "target": eid, "type": "HAS_EVIDENCE"})
    for item in overrides[:8]:
        oid = item.get("override_id") or f"override:{len(nodes)}"
        nodes.append({"id": oid, "type": "Override", "label": item.get("action") or "override"})
        links.append({"source": oid, "target": row["risk_event_id"], "type": "OVERRIDES"})
    return {"nodes": nodes, "links": links}


def _risk_raw(row: Any, *, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any]:
    if row["source_kind"] == "tool_output_text" and row["source_ref"]:
        provider = db_provider or _default_db_provider()
        conn = provider.connect()
        try:
            output = conn.execute(
                "select tool_output_id, sha256, byte_count, char_count, content_text from tool_outputs where tool_output_id = ?",
                (row["source_ref"],),
            ).fetchone()
        finally:
            conn.close()
        if output:
            return {
                "available": True,
                "source_kind": row["source_kind"],
                "source_ref": row["source_ref"],
                "sha256": output["sha256"],
                "byte_count": output["byte_count"],
                "char_count": output["char_count"],
                "content": output["content_text"] or "",
            }
    return {"available": False, "reason": "Raw content is not stored for this risk source or requires direct source inspection.", "source_kind": row["source_kind"], "source_ref": row["source_ref"]}


def _decorate_risk_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = _row_dict(row) if not isinstance(row, dict) else dict(row)
    taint_context = _safe_json_value(item.get("taint_context_json"))
    if not isinstance(taint_context, list):
        taint_context = []
    item["categories"] = _safe_json_list(item.get("categories_json"))
    item["poisoning_flags"] = _safe_json_list(item.get("poisoning_flags_json"))
    item["deterministic_flags"] = _safe_json_list(item.get("deterministic_flags_json"))
    item["taint_context"] = taint_context
    item["taint_source_refs"] = [
        str(entry.get("risk_event_id") or "")
        for entry in taint_context
        if isinstance(entry, dict) and str(entry.get("risk_event_id") or "")
    ]
    item["command_ref"] = f"monitor:risk_events:{item.get('risk_event_id')}" if item.get("risk_event_id") else ""
    approval_token = str(item.get("approval_token") or "")
    if str(item.get("approval_state") or "") == "required" and item.get("risk_event_id") and approval_token:
        item["approval_line"] = f"approve {item['risk_event_id']} {approval_token}"
    else:
        item["approval_line"] = ""
    item.pop("categories_json", None)
    item.pop("poisoning_flags_json", None)
    item.pop("deterministic_flags_json", None)
    item.pop("taint_context_json", None)
    return item


def _decorate_classifier_payload(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return payload
    decorated = dict(payload)
    result = decorated.get("result")
    if isinstance(result, dict):
        normalized = dict(result)
        normalized["categories"] = _safe_json_list(normalized.get("categories_json"))
        normalized["poisoning_flags"] = _safe_json_list(normalized.get("poisoning_flags_json"))
        normalized.pop("categories_json", None)
        normalized.pop("poisoning_flags_json", None)
        decorated["result"] = normalized
    return decorated


def monitor_risk_event(
    risk_event_id: str,
    include_raw: bool = False,
    *,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    row = conn.execute("select * from risk_events where risk_event_id = ?", (risk_event_id,)).fetchone()
    if not row:
        return {"error": "not found"}
    evidence = [_row_dict(item) for item in conn.execute("select * from risk_evidence where risk_event_id = ? order by created_at", (risk_event_id,))]
    overrides = [_row_dict(item) for item in conn.execute("select * from risk_policy_overrides where risk_event_id = ? order by created_at desc", (risk_event_id,))]
    classifier = None
    if row["classifier_run_id"]:
        run = conn.execute("select * from classifier_runs where run_id = ?", (row["classifier_run_id"],)).fetchone()
        result = conn.execute("select * from classifier_results where run_id = ?", (row["classifier_run_id"],)).fetchone()
        feedback = [_row_dict(item) for item in conn.execute("select * from classifier_feedback where run_id = ? order by created_at", (row["classifier_run_id"],))]
        classifier = _decorate_classifier_payload({"run": _row_dict(run) if run else None, "result": _row_dict(result) if result else None, "feedback": feedback})
    data = {"risk_event": _decorate_risk_row(row), "evidence": evidence, "overrides": overrides, "classifier": classifier, "graph": _risk_graph(row, evidence, classifier, overrides)}
    if include_raw:
        data["raw"] = _risk_raw(row, db_provider=db_provider)
    return data


def scan_risk_file(
    path: str,
    *,
    file_system: FileSystem | None = None,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    fs = file_system or _default_file_system()
    decision = scan_text(fs.read_text(Path(path)), source_kind="file_content")
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        risk_id = record_risk_event(
            conn,
            decision,
            source_kind="file_content",
            source_ref=path,
            status="quarantined" if decision.decision == "quarantine" else "warned" if decision.decision == "warn" else "allowed",
            evidence=[{"source_kind": "file_content", "source_ref": path, "field": "file", "quote": decision.preview}],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"risk_event_id": risk_id, **decision.to_json(), "preview": decision.preview}


def scan_risk_text(text: str, *, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any]:
    decision = scan_text(text, source_kind="text")
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        risk_id = record_risk_event(
            conn,
            decision,
            source_kind="text",
            source_ref="stdin",
            status="quarantined" if decision.decision == "quarantine" else "warned" if decision.decision == "warn" else "allowed",
            evidence=[{"source_kind": "text", "source_ref": "stdin", "field": "stdin", "quote": decision.preview}],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"risk_event_id": risk_id, **decision.to_json(), "preview": decision.preview}


def scan_risk_command(command: str, *, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any]:
    decision = scan_tool_input("Bash", {"command": command})
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    try:
        conn.execute("begin immediate")
        risk_id = record_risk_event(
            conn,
            decision,
            source_kind="shell_command",
            source_ref="cli",
            status="blocked" if decision.decision == "block" else "warned" if decision.decision == "warn" else "allowed",
            evidence=[{"source_kind": "shell_command", "source_ref": "cli", "field": "command", "quote": decision.preview}],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"risk_event_id": risk_id, **decision.to_json(), "preview": decision.preview, "block": decision.should_block}


def list_risk_events(
    *,
    status: str | None = None,
    category: str | None = None,
    client: str | None = None,
    session: str | None = None,
    limit: int = 50,
    db_provider: SQLiteConnectionProvider | None = None,
) -> list[dict[str, Any]]:
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    where = []
    params: list[Any] = []
    if status:
        where.append("status = ?")
        params.append(status)
    if category:
        where.append("categories_json like ?")
        params.append(f"%{category}%")
    if client:
        where.append("client_type = ?")
        params.append(client)
    if session:
        where.append("session_id like ?")
        params.append(f"{session}%")
    where_sql = "where " + " and ".join(where) if where else ""
    rows = list(
        conn.execute(
            f"""
            select *
            from risk_events
            {where_sql}
            order by created_at desc
            limit ?
            """,
            (*params, max(1, min(int(limit), 500))),
        )
    )
    return [_decorate_risk_row(row) for row in rows]


def explain_risk_events(
    *,
    status: str | None = None,
    category: str | None = None,
    client: str | None = None,
    session: str | None = None,
    limit: int = 50,
    db_provider: SQLiteConnectionProvider | None = None,
) -> list[dict[str, Any]]:
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    where = []
    params: list[Any] = []
    if session:
        where.append("r.session_id like ?")
        params.append(f"{session}%")
    if status:
        where.append("r.status = ?")
        params.append(status)
    if category:
        where.append("(r.categories_json like ? or r.poisoning_flags_json like ? or r.deterministic_flags_json like ?)")
        params.extend([f"%{category}%", f"%{category}%", f"%{category}%"])
    where_sql = "where " + " and ".join(where) if where else ""
    rows = list(
        conn.execute(
            f"""
            select r.risk_event_id, r.created_at, r.session_id, r.event_seq,
                   r.status, r.decision, r.risk_level, r.approval_state,
                   r.reason, r.impact, r.preview, r.categories_json,
                   r.poisoning_flags_json, r.deterministic_flags_json,
                   r.command_hash, r.taint_context_json,
                   cr.run_id as classifier_run_id, cr.runner, cr.model,
                   cr.duration_ms, cr.total_tokens, cr.status as classifier_status,
                   rs.decision as classifier_decision, rs.risk_level as classifier_risk_level,
                   rs.reason as classifier_reason
            from risk_events r
            left join classifier_runs cr on cr.run_id = r.classifier_run_id
            left join classifier_results rs on rs.run_id = r.classifier_run_id
            {where_sql}
            order by r.created_at desc
            limit ?
            """,
            (*params, max(1, min(int(limit), 500))),
        )
    )
    return [_row_dict(row) for row in rows]


def get_risk_event(risk_event_id: str, *, db_provider: SQLiteConnectionProvider | None = None) -> dict[str, Any] | None:
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    row = conn.execute("select * from risk_events where risk_event_id = ?", (risk_event_id,)).fetchone()
    if not row:
        return None
    evidence = list(conn.execute("select * from risk_evidence where risk_event_id = ? order by created_at", (risk_event_id,)))
    classifiers = []
    if row["classifier_run_id"]:
        run = conn.execute("select * from classifier_runs where run_id = ?", (row["classifier_run_id"],)).fetchone()
        result = conn.execute("select * from classifier_results where run_id = ?", (row["classifier_run_id"],)).fetchone()
        classifiers = [{"run": _row_dict(run) if run else None, "result": _row_dict(result) if result else None}]
    return {
        "risk_event": _decorate_risk_row(row),
        "evidence": [_row_dict(item) for item in evidence],
        "classifiers": [_decorate_classifier_payload(item) for item in classifiers],
    }


def _insert_risk_override(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    action: str,
    new_decision: str,
    new_risk_level: str,
    reason: str,
    reviewer: str | None,
) -> str:
    override_id = f"riskovr_{uuid.uuid4().hex[:16]}"
    conn.execute(
        """
        insert into risk_policy_overrides (
          override_id, risk_event_id, created_at, reviewer, action,
          previous_decision, new_decision, previous_risk_level, new_risk_level, reason
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            override_id,
            row["risk_event_id"],
            _now(),
            reviewer,
            action,
            row["decision"],
            new_decision,
            row["risk_level"],
            new_risk_level,
            reason,
        ),
    )
    return override_id


def _insert_classifier_feedback(
    conn: sqlite3.Connection,
    *,
    run_id: str | None,
    verdict: str,
    corrected_decision: str | None,
    corrected_risk_level: str | None,
    note: str,
    reviewer: str | None,
) -> str | None:
    if not run_id:
        return None
    feedback_id = f"clffb_{uuid.uuid4().hex[:16]}"
    conn.execute(
        """
        insert into classifier_feedback (
          feedback_id, run_id, created_at, reviewer, verdict,
          corrected_decision, corrected_risk_level, note
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (feedback_id, run_id, _now(), reviewer, verdict, corrected_decision, corrected_risk_level, note),
    )
    return feedback_id


def risk_review_action(
    risk_event_id: str,
    *,
    action: str,
    reason: str,
    reviewer: str | None = None,
    force: bool = False,
    db_provider: SQLiteConnectionProvider | None = None,
) -> dict[str, Any]:
    if action not in {"mark-safe", "block", "keep-quarantined"}:
        raise ValueError("action must be mark-safe, block, or keep-quarantined")
    review = None
    conn = _connect_monitor_db("risk_events", db_provider=db_provider)
    with conn:
        row = conn.execute("select * from risk_events where risk_event_id = ?", (risk_event_id,)).fetchone()
        if not row:
            raise ValueError(f"risk event not found: {risk_event_id}")
        if action == "mark-safe":
            risk_payload = _json_dumps(_row_dict(row))
            review = deterministic_classifier(
                conn,
                stage="quarantine_release_review",
                source_kind="risk_event_review",
                payload=risk_payload,
                deterministic=scan_text(risk_payload, source_kind="risk_event_review"),
                source_ref=risk_event_id,
                runner="auto",
            )
            if review.decision.decision in {"quarantine", "block"} and not force:
                _insert_classifier_feedback(
                    conn,
                    run_id=review.run_id,
                    verdict="release_rejected",
                    corrected_decision=None,
                    corrected_risk_level=None,
                    note=reason or "Release rejected by quarantine release review.",
                    reviewer=reviewer,
                )
                return {
                    "ok": False,
                    "risk_event_id": risk_event_id,
                    "action": action,
                    "message": "quarantine release review rejected mark-safe; pass --force to override",
                    "review": {"classifier_run_id": review.run_id, **review.decision.to_json(), "status": review.status},
                }
            new_status, new_decision, new_risk_level = "reviewed_safe", "allow", "low"
            verdict = "false_positive"
        elif action == "block":
            new_status, new_decision, new_risk_level = "blocked", "block", "critical"
            verdict = "confirmed_risky"
        else:
            new_status, new_decision, new_risk_level = "quarantined", "quarantine", row["risk_level"]
            verdict = "keep_quarantined"
        override_id = _insert_risk_override(
            conn,
            row,
            action=action,
            new_decision=new_decision,
            new_risk_level=new_risk_level,
            reason=reason,
            reviewer=reviewer,
        )
        feedback_id = _insert_classifier_feedback(
            conn,
            run_id=(review.run_id if review else row["classifier_run_id"]),
            verdict=verdict,
            corrected_decision=new_decision,
            corrected_risk_level=new_risk_level,
            note=reason,
            reviewer=reviewer,
        )
        conn.execute(
            """
            update risk_events
            set updated_at = ?,
                status = ?,
                decision = ?,
                policy = ?,
                risk_level = ?,
                approval_state = case when ? = 'mark-safe' then 'approved' else approval_state end
            where risk_event_id = ?
            """,
            (_now(), new_status, new_decision, action, new_risk_level, action, risk_event_id),
        )
    return {
        "ok": True,
        "risk_event_id": risk_event_id,
        "action": action,
        "status": new_status,
        "decision": new_decision,
        "risk_level": new_risk_level,
        "override_id": override_id,
        "feedback_id": feedback_id,
        "review": {"classifier_run_id": review.run_id, **review.decision.to_json(), "status": review.status} if review else None,
    }
