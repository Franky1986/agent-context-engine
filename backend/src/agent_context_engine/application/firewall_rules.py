from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import shlex
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from ..ports.clock import Clock
from .firewall import create_firewall_override, firewall_overrides, revoke_firewall_override
from .risk import NON_OVERRIDABLE_HARD_BLOCK_FLAGS, RiskDecision, shell_action_class


VALID_ACTIONS = {
    "read",
    "verify",
    "write",
    "write_execute",
    "network",
    "deploy",
    "delete",
    "protect_secret",
    "unknown",
}
VALID_RISK_LEVELS = {"none", "low", "medium", "high", "critical"}
MUTATING_FIREWALL_COMMANDS = {"add", "update", "disable", "enable", "delete", "revoke"}
CONTROL_PREFIX = "firewall"
HOSTLIKE_EXCLUDED_SUFFIXES = {
    "css",
    "go",
    "html",
    "js",
    "json",
    "jsx",
    "md",
    "mjs",
    "patch",
    "py",
    "sql",
    "ts",
    "tsx",
    "txt",
    "yaml",
    "yml",
}
SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/\-]+=*"),
    re.compile(r"(?i)(api[_-]?key|token|password|passwd|secret)=([^\s'\"&]+)"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
]


@dataclass
class FirewallRuleSpec:
    name: str
    reason: str
    source_line: str
    rule_kind: str = "deterministic"
    description: str = ""
    scope_type: str = "global"
    project_id: str | None = None
    workdir_prefix: str | None = None
    session_id: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    allowed_actions: list[str] = field(default_factory=list)
    denied_actions: list[str] = field(default_factory=list)
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_local_paths: list[str] = field(default_factory=list)
    allowed_remote_paths: list[str] = field(default_factory=list)
    command_patterns: list[str] = field(default_factory=list)
    max_risk_level: str | None = None
    expires_at: str | None = None
    permanent: bool = False
    policy_text: str | None = None

    def rule_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rule_kind": self.rule_kind,
            "description": self.description,
            "scope_type": self.scope_type,
            "project_id": self.project_id,
            "workdir_prefix": self.workdir_prefix,
            "session_id": self.session_id,
            "allowed_tools": self.allowed_tools,
            "allowed_actions": self.allowed_actions,
            "denied_actions": self.denied_actions,
            "allowed_hosts": self.allowed_hosts,
            "allowed_local_paths": self.allowed_local_paths,
            "allowed_remote_paths": self.allowed_remote_paths,
            "command_patterns": self.command_patterns,
            "max_risk_level": self.max_risk_level,
            "expires_at": self.expires_at,
            "permanent": bool(self.permanent),
            "reason": self.reason,
            "policy_text": self.policy_text,
        }


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        return _utc_now()


def _default_clock() -> Clock:
    return _DefaultClock()


def _json_dumps(value: Any) -> str:
    from ..infrastructure.config import json_dumps

    return json_dumps(value)


def _utc_now() -> str:
    from ..infrastructure.config import utc_now

    return utc_now()


def _now() -> str:
    return _default_clock().utc_now()


def _json_list(raw: str | None) -> list[str]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item)]


def _policy_context_fields(spec: FirewallRuleSpec) -> tuple[str | None, str | None, str | None]:
    if spec.rule_kind != "llm_context":
        return None, None, None
    policy_text_sanitized, _report = redact_sensitive_text(str(spec.policy_text or "").strip())
    context = (
        "Agent Context Engine firewall LLM context rule. "
        f"Rule name: {spec.name}. Scope: {spec.scope_type}. Reason: {spec.reason}. "
        f"Policy: {policy_text_sanitized}"
    )
    context_hash = hashlib.sha256(context.encode("utf-8", errors="replace")).hexdigest()
    return policy_text_sanitized, context, context_hash


def _row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _split_csv(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        for item in str(value or "").split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return result


def _spec_from_rule_row(row: sqlite3.Row) -> FirewallRuleSpec:
    return FirewallRuleSpec(
        name=row["name"],
        reason=row["reason"],
        source_line=row["source_line"],
        rule_kind=row["rule_kind"] or "deterministic",
        description=row["description"] or "",
        scope_type=row["scope_type"] or "global",
        project_id=row["project_id"],
        workdir_prefix=row["workdir_prefix"],
        session_id=row["session_id"],
        allowed_tools=_json_list(row["allowed_tools_json"]),
        allowed_actions=_json_list(row["allowed_actions_json"]),
        denied_actions=_json_list(row["denied_actions_json"]),
        allowed_hosts=_json_list(row["allowed_hosts_json"]),
        allowed_local_paths=_json_list(row["allowed_local_paths_json"]),
        allowed_remote_paths=_json_list(row["allowed_remote_paths_json"]),
        command_patterns=_json_list(row["command_patterns_json"]),
        max_risk_level=row["max_risk_level"],
        expires_at=row["expires_at"],
        permanent=bool(row["permanent"]) if "permanent" in row.keys() else False,
        policy_text=row["policy_text"],
    )


def _list_update(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return _split_csv([str(raw)])


def _apply_rule_updates(spec: FirewallRuleSpec, updates: dict[str, Any]) -> None:
    scalar_fields = {
        "name",
        "reason",
        "rule_kind",
        "description",
        "scope_type",
        "project_id",
        "workdir_prefix",
        "session_id",
        "max_risk_level",
        "expires_at",
        "permanent",
        "policy_text",
    }
    list_fields = {
        "allowed_tools",
        "allowed_actions",
        "denied_actions",
        "allowed_hosts",
        "allowed_local_paths",
        "allowed_remote_paths",
        "command_patterns",
    }
    for key, value in (updates or {}).items():
        normalized = str(key).replace("-", "_")
        if normalized == "permanent":
            setattr(spec, normalized, str(value).strip().lower() in {"1", "true", "yes", "on", "permanent", "never"})
        elif normalized in scalar_fields:
            setattr(spec, normalized, None if value is None else str(value).strip())
        elif normalized in list_fields:
            setattr(spec, normalized, _list_update(value))


def parse_duration(value: str | None) -> str | None:
    raw = str(value or "").strip().lower()
    if not raw:
        return None
    if raw in {"never", "none", "permanent"}:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}t", raw):
        return raw
    match = re.fullmatch(r"(\d+)(m|h|d)", raw)
    if not match:
        raise ValueError("expires must be an ISO timestamp or duration like 30m, 12h, 7d")
    amount = int(match.group(1))
    unit = match.group(2)
    delta = {"m": timedelta(minutes=amount), "h": timedelta(hours=amount), "d": timedelta(days=amount)}[unit]
    return (datetime.now(timezone.utc) + delta).isoformat()


def _join_command_parts(lines: list[str]) -> str:
    command = ""
    for raw in lines:
        part = str(raw or "").strip()
        if not part:
            continue
        if not command:
            command = part
        elif command.endswith(("/", "=", ":")) and not part.startswith("--"):
            command += part
        else:
            command += " " + part
    return command


def parse_firewall_add_line(line: str) -> FirewallRuleSpec:
    try:
        parts = shlex.split(_join_command_parts(str(line or "").splitlines()))
    except ValueError as exc:
        raise ValueError(f"invalid firewall command quoting: {exc}") from exc
    if len(parts) < 2 or [part.lower() for part in parts[:2]] != ["firewall", "add"]:
        raise ValueError("expected: firewall add ...")
    args = parts[2:]
    values: dict[str, list[str]] = {}
    boolean_flags = {"permanent"}
    i = 0
    while i < len(args):
        key = args[i]
        if not key.startswith("--"):
            raise ValueError(f"unexpected firewall add token: {key}")
        if "=" in key:
            raw_name, raw_value = key[2:].split("=", 1)
            name = raw_name.replace("-", "_")
            values.setdefault(name, []).append(raw_value)
            i += 1
            continue
        name = key[2:].replace("-", "_")
        if name in boolean_flags:
            values.setdefault(name, []).append("true")
            i += 1
            continue
        if i + 1 >= len(args) or args[i + 1].startswith("--"):
            raise ValueError(f"value is required for --{name.replace('_', '-')}")
        values.setdefault(name, []).append(args[i + 1])
        i += 2
    expires_raw = (values.get("expires") or values.get("expires_at") or [None])[-1]
    permanent = str((values.get("permanent") or ["false"])[-1]).strip().lower() in {"1", "true", "yes", "on"}
    if str(expires_raw or "").strip().lower() in {"never", "none", "permanent"}:
        permanent = True
    spec = FirewallRuleSpec(
        name=(values.get("name") or [""])[-1].strip(),
        reason=(values.get("reason") or [""])[-1].strip(),
        source_line=_join_command_parts(str(line or "").splitlines()),
        rule_kind=(values.get("kind") or values.get("rule_kind") or ["deterministic"])[-1].strip().lower().replace("-", "_"),
        description=(values.get("description") or [""])[-1].strip(),
        scope_type=(values.get("scope") or values.get("scope_type") or ["global"])[-1].strip().lower(),
        project_id=(values.get("project") or values.get("project_id") or [None])[-1],
        workdir_prefix=(values.get("workdir") or values.get("workdir_prefix") or [None])[-1],
        session_id=(values.get("session") or values.get("session_id") or [None])[-1],
        allowed_tools=_split_csv(values.get("tool") or values.get("tools") or []),
        allowed_actions=_split_csv(values.get("action") or values.get("actions") or []),
        denied_actions=_split_csv(values.get("deny_action") or values.get("deny_actions") or []),
        allowed_hosts=_split_csv(values.get("host") or values.get("hosts") or []),
        allowed_local_paths=_split_csv(values.get("local_path") or values.get("local_paths") or []),
        allowed_remote_paths=_split_csv(values.get("remote_path") or values.get("remote_paths") or []),
        command_patterns=_split_csv(values.get("command_pattern") or values.get("command_patterns") or []),
        max_risk_level=(values.get("max_risk") or values.get("max_risk_level") or [None])[-1],
        expires_at=None if permanent else parse_duration(expires_raw),
        permanent=permanent,
        policy_text=(values.get("policy_text") or values.get("policy") or [None])[-1],
    )
    validate_firewall_rule_spec(spec)
    return spec


def validate_firewall_rule_spec(spec: FirewallRuleSpec) -> None:
    if not spec.name:
        raise ValueError("--name is required")
    if not spec.reason:
        raise ValueError("--reason is required")
    if spec.rule_kind not in {"deterministic", "llm_context"}:
        raise ValueError("--kind must be deterministic or llm_context")
    if spec.scope_type not in {"global", "project", "workdir", "session"}:
        raise ValueError("--scope must be global, project, workdir, or session")
    if spec.scope_type == "project" and not spec.project_id:
        raise ValueError("--project is required for project scope")
    if spec.scope_type == "workdir" and not spec.workdir_prefix:
        raise ValueError("--workdir is required for workdir scope")
    if spec.scope_type == "session" and not spec.session_id:
        raise ValueError("--session is required for session scope")
    if spec.rule_kind == "llm_context" and not str(spec.policy_text or "").strip():
        raise ValueError("--policy-text is required for llm_context rules")
    if spec.rule_kind == "deterministic" and not (spec.allowed_actions or spec.denied_actions):
        raise ValueError("at least one --action or --deny-action is required")
    invalid = sorted((set(spec.allowed_actions) | set(spec.denied_actions)) - VALID_ACTIONS)
    if invalid:
        raise ValueError(f"invalid firewall action(s): {', '.join(invalid)}")
    if spec.max_risk_level and spec.max_risk_level not in VALID_RISK_LEVELS:
        raise ValueError("--max-risk must be none, low, medium, high, or critical")
    if "*" in spec.allowed_hosts:
        raise ValueError("global host wildcards are not allowed")
    for path in [*(spec.allowed_local_paths or []), spec.workdir_prefix or ""]:
        if path in {"/", "~", "$HOME"}:
            raise ValueError("broad local path scopes are not allowed")
    for pattern in spec.command_patterns:
        if pattern.strip() in {"*", "**"}:
            raise ValueError("broad command patterns are not allowed")
    risky = {"network", "deploy", "write_execute", "delete"} & set(spec.allowed_actions)
    if risky and not (spec.expires_at or spec.permanent):
        raise ValueError("riskier actions require --expires or --permanent")


def record_session_target_scope(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    scope_path: str | None,
    source: str,
    reason: str | None = None,
    event_seq: int | None = None,
) -> None:
    session = str(session_id or "").strip()
    path = str(scope_path or "").strip().rstrip("/")
    if not session or not path or not path.startswith("/") or path in {"/", "~", "$HOME"}:
        return
    now = _now()
    conn.execute(
        """
        insert into firewall_session_scopes (
          session_id, scope_path, created_at, updated_at, source, reason, event_seq
        ) values (?, ?, ?, ?, ?, ?, ?)
        on conflict(session_id, scope_path) do update set
          updated_at = excluded.updated_at,
          source = excluded.source,
          reason = excluded.reason,
          event_seq = excluded.event_seq
        """,
        (session, path, now, now, source, reason, event_seq),
    )


def session_target_workdirs(conn: sqlite3.Connection, *, session_id: str | None, limit: int = 20) -> list[str]:
    session = str(session_id or "").strip()
    if not session:
        return []
    rows = conn.execute(
        """
        select scope_path
        from firewall_session_scopes
        where session_id = ?
        order by updated_at desc
        limit ?
        """,
        (session, max(1, min(int(limit), 50))),
    )
    return [str(row["scope_path"]) for row in rows if row["scope_path"]]


def _direct_user_control_blocks(prompt: str | None, start_pattern: str) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw in (prompt or "").splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        starts_control = bool(re.match(r"^(firewall\s+(add|disable)|approve\s+explain)\b", stripped, re.I))
        if re.match(start_pattern, stripped, re.I):
            if current:
                blocks.append(current)
            current = [stripped]
            continue
        if current and starts_control:
            blocks.append(current)
            current = []
            continue
        if current:
            current.append(stripped)
    if current:
        blocks.append(current)
    return [_join_command_parts(block) for block in blocks]


def direct_user_firewall_add_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, r"^firewall\s+add\b")


def direct_user_firewall_disable_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, r"^firewall\s+disable\b")


def direct_user_firewall_enable_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, r"^firewall\s+enable\b")


def direct_user_approve_explain_lines(prompt: str | None) -> list[str]:
    return _direct_user_control_blocks(prompt, r"^approve\s+explain\b")


def prompt_contains_only_firewall_control(prompt: str | None) -> bool:
    lines = [line.strip() for line in (prompt or "").splitlines() if line.strip()]
    if not lines:
        return False
    return bool(
        direct_user_firewall_add_lines(prompt)
        or direct_user_firewall_disable_lines(prompt)
        or direct_user_firewall_enable_lines(prompt)
        or direct_user_approve_explain_lines(prompt)
    )


def redact_control_plane_prompt(prompt: str | None) -> str | None:
    if prompt_contains_only_firewall_control(prompt):
        return "[agent-memory control-plane firewall command redacted; see firewall_rule_audit]"
    return prompt


def create_firewall_rule(
    conn: sqlite3.Connection,
    spec: FirewallRuleSpec,
    *,
    actor: str,
    session_id: str | None = None,
    event_seq: int | None = None,
) -> dict[str, Any]:
    validate_firewall_rule_spec(spec)
    now = _now()
    rule_id = f"fwrule_{uuid.uuid4().hex[:16]}"
    family_id = rule_id
    policy_text_sanitized, classifier_context, context_hash = _policy_context_fields(spec)
    conn.execute(
        """
        insert into firewall_rules (
          rule_id, family_id, version, rule_kind, created_at, updated_at, status, name, description, scope_type,
          project_id, workdir_prefix, session_id, allowed_tools_json,
          allowed_actions_json, denied_actions_json, allowed_hosts_json,
          allowed_local_paths_json, allowed_remote_paths_json, command_patterns_json,
          max_risk_level, expires_at, permanent, created_by, created_from_session_id,
          created_from_event_seq, source_line, reason, policy_text, policy_text_sanitized,
          classifier_context, context_hash, rule_json
        ) values (?, ?, 1, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rule_id,
            family_id,
            spec.rule_kind,
            now,
            now,
            spec.name,
            spec.description,
            spec.scope_type,
            spec.project_id,
            spec.workdir_prefix,
            spec.session_id,
            _json_dumps(spec.allowed_tools),
            _json_dumps(spec.allowed_actions),
            _json_dumps(spec.denied_actions),
            _json_dumps(spec.allowed_hosts),
            _json_dumps(spec.allowed_local_paths),
            _json_dumps(spec.allowed_remote_paths),
            _json_dumps(spec.command_patterns),
            spec.max_risk_level,
            spec.expires_at,
            1 if spec.permanent else 0,
            actor,
            session_id,
            event_seq,
            spec.source_line,
            spec.reason,
            spec.policy_text,
            policy_text_sanitized,
            classifier_context,
            context_hash,
            _json_dumps(spec.rule_json()),
        ),
    )
    conn.execute(
        """
        insert into firewall_rule_audit (
          audit_id, rule_id, family_id, created_at, action, actor, reason, after_json, session_id, event_seq
        ) values (?, ?, ?, ?, 'created', ?, ?, ?, ?, ?)
        """,
            (f"fwraudit_{uuid.uuid4().hex[:16]}", rule_id, family_id, now, actor, spec.reason, _json_dumps(spec.rule_json()), session_id, event_seq),
    )
    if spec.scope_type == "workdir" and spec.workdir_prefix:
        record_session_target_scope(
            conn,
            session_id=session_id,
            scope_path=spec.workdir_prefix,
            source="firewall_rule_created",
            reason=spec.reason,
            event_seq=event_seq,
        )
    row = conn.execute("select * from firewall_rules where rule_id = ?", (rule_id,)).fetchone()
    return _row_dict(row)


def disable_firewall_rule(
    conn: sqlite3.Connection,
    rule_id: str,
    *,
    actor: str,
    reason: str,
    session_id: str | None = None,
    event_seq: int | None = None,
) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("--reason is required")
    row = conn.execute("select * from firewall_rules where rule_id = ?", (rule_id,)).fetchone()
    if row is None:
        raise ValueError(f"firewall rule not found: {rule_id}")
    before = _row_dict(row)
    now = _now()
    conn.execute("update firewall_rules set status = 'disabled', updated_at = ? where rule_id = ?", (now, rule_id))
    after = conn.execute("select * from firewall_rules where rule_id = ?", (rule_id,)).fetchone()
    conn.execute(
        """
        insert into firewall_rule_audit (
          audit_id, rule_id, family_id, created_at, action, actor, reason, before_json, after_json, session_id, event_seq
        ) values (?, ?, ?, ?, 'disabled', ?, ?, ?, ?, ?, ?)
        """,
                (f"fwraudit_{uuid.uuid4().hex[:16]}", rule_id, before.get("family_id"), now, actor, reason, _json_dumps(before), _json_dumps(_row_dict(after)), session_id, event_seq),
    )
    return _row_dict(after)


def create_firewall_rule_version(
    conn: sqlite3.Connection,
    rule_id: str,
    updates: dict[str, Any],
    *,
    actor: str,
    reason: str,
    session_id: str | None = None,
    event_seq: int | None = None,
) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("reason is required")
    row = conn.execute("select * from firewall_rules where rule_id = ?", (rule_id,)).fetchone()
    if row is None:
        raise ValueError(f"firewall rule not found: {rule_id}")
    before = _row_dict(row)
    spec = _spec_from_rule_row(row)
    _apply_rule_updates(spec, updates)
    validate_firewall_rule_spec(spec)
    now = _now()
    new_rule_id = f"fwrule_{uuid.uuid4().hex[:16]}"
    family_id = str(before.get("family_id") or before.get("rule_id") or new_rule_id)
    version = int(before.get("version") or 1) + 1
    policy_text_sanitized, classifier_context, context_hash = _policy_context_fields(spec)
    conn.execute("update firewall_rules set status = 'superseded', updated_at = ? where rule_id = ?", (now, rule_id))
    conn.execute(
        """
        insert into firewall_rules (
          rule_id, family_id, version, supersedes_rule_id, rule_kind, created_at, updated_at,
          status, name, description, scope_type, project_id, workdir_prefix, session_id,
          allowed_tools_json, allowed_actions_json, denied_actions_json, allowed_hosts_json,
          allowed_local_paths_json, allowed_remote_paths_json, command_patterns_json,
          max_risk_level, expires_at, permanent, created_by, created_from_session_id,
          created_from_event_seq, source_line, reason, policy_text, policy_text_sanitized,
          classifier_context, context_hash, rule_json
        ) values (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_rule_id,
            family_id,
            version,
            rule_id,
            spec.rule_kind,
            now,
            now,
            spec.name,
            spec.description,
            spec.scope_type,
            spec.project_id,
            spec.workdir_prefix,
            spec.session_id,
            _json_dumps(spec.allowed_tools),
            _json_dumps(spec.allowed_actions),
            _json_dumps(spec.denied_actions),
            _json_dumps(spec.allowed_hosts),
            _json_dumps(spec.allowed_local_paths),
            _json_dumps(spec.allowed_remote_paths),
            _json_dumps(spec.command_patterns),
            spec.max_risk_level,
            spec.expires_at,
            1 if spec.permanent else 0,
            actor,
            session_id,
            event_seq,
            spec.source_line,
            reason,
            spec.policy_text,
            policy_text_sanitized,
            classifier_context,
            context_hash,
            _json_dumps(spec.rule_json()),
        ),
    )
    if spec.scope_type == "workdir" and spec.workdir_prefix:
        record_session_target_scope(
            conn,
            session_id=session_id,
            scope_path=spec.workdir_prefix,
            source="firewall_rule_version",
            reason=reason,
            event_seq=event_seq,
        )
    after = conn.execute("select * from firewall_rules where rule_id = ?", (new_rule_id,)).fetchone()
    conn.execute(
        """
        insert into firewall_rule_audit (
          audit_id, rule_id, family_id, created_at, action, actor, reason,
          before_json, after_json, session_id, event_seq
        ) values (?, ?, ?, ?, 'edited_new_version', ?, ?, ?, ?, ?, ?)
        """,
                (f"fwraudit_{uuid.uuid4().hex[:16]}", new_rule_id, family_id, now, actor, reason, _json_dumps(before), _json_dumps(_row_dict(after)), session_id, event_seq),
    )
    conn.execute(
        """
        insert into firewall_rule_audit (
          audit_id, rule_id, family_id, created_at, action, actor, reason,
          before_json, after_json, session_id, event_seq
        ) values (?, ?, ?, ?, 'superseded', ?, ?, ?, ?, ?, ?)
        """,
        (
            f"fwraudit_{uuid.uuid4().hex[:16]}",
            rule_id,
            family_id,
            now,
            "system",
            f"superseded by {new_rule_id}",
            _json_dumps(before),
            _json_dumps({"superseded_by": new_rule_id}),
            session_id,
            event_seq,
        ),
    )
    return _row_dict(after)


def parse_firewall_disable_line(line: str) -> tuple[str, str]:
    try:
        parts = shlex.split(str(line or ""))
    except ValueError as exc:
        raise ValueError(f"invalid firewall command quoting: {exc}") from exc
    if len(parts) < 4 or [part.lower() for part in parts[:2]] != ["firewall", "disable"]:
        raise ValueError("expected: firewall disable <rule_id> --reason ...")
    rule_id = parts[2]
    reason = ""
    idx = 3
    while idx < len(parts):
        if parts[idx] != "--reason" or idx + 1 >= len(parts):
            raise ValueError("firewall disable requires --reason")
        reason = parts[idx + 1]
        idx += 2
    if not reason.strip():
        raise ValueError("--reason is required")
    return rule_id, reason


def _parse_session_firewall_disable_line(line: str) -> int | None:
    try:
        parts = shlex.split(str(line or ""))
    except ValueError as exc:
        raise ValueError(f"invalid firewall command quoting: {exc}") from exc
    lowered = [part.lower() for part in parts]
    if len(parts) < 3 or lowered[:3] != ["firewall", "disable", "session"]:
        raise ValueError("expected: firewall disable session [30m|2h|1d]")
    if len(parts) == 3:
        return None
    token = lowered[3]
    match = re.fullmatch(r"(\d+)(m|h|d)?", token)
    if not match:
        raise ValueError("expected duration like 30m, 2h, or 1d")
    value = int(match.group(1))
    unit = match.group(2) or "m"
    if unit == "m":
        return value
    if unit == "h":
        return value * 60
    return value * 24 * 60


def _is_session_firewall_disable_line(line: str) -> bool:
    return bool(re.match(r"^\s*firewall\s+disable\s+session\b", str(line or ""), re.I))


def _is_session_firewall_enable_line(line: str) -> bool:
    return bool(re.match(r"^\s*firewall\s+enable\s+session\b", str(line or ""), re.I))


def apply_direct_user_firewall_commands(
    conn: sqlite3.Connection,
    prompt: str | None,
    *,
    session_id: str,
    event_seq: int | None,
) -> list[str]:
    messages: list[str] = []
    for line in direct_user_firewall_add_lines(prompt):
        spec = parse_firewall_add_line(line)
        row = create_firewall_rule(conn, spec, actor="user_chat_direct", session_id=session_id, event_seq=event_seq)
        messages.append(f"Firewall rule created: {row['rule_id']} name={row['name']}")
    for line in direct_user_firewall_disable_lines(prompt):
        if _is_session_firewall_disable_line(line):
            minutes = _parse_session_firewall_disable_line(line)
            row = create_firewall_override(
                conn,
                scope_type="session",
                reason="direct user chat session firewall disable",
                actor="user_chat_direct",
                source="monitor",
                disabled_minutes=minutes,
                permanent_disable=minutes is None,
                session_id=session_id,
            )
            if row.get("permanent"):
                messages.append(f"Session firewall disabled: {row['override_id']} expires=indefinite")
            else:
                messages.append(f"Session firewall disabled: {row['override_id']} expires={row['expires_at']}")
            continue
        rule_id, reason = parse_firewall_disable_line(line)
        row = disable_firewall_rule(conn, rule_id, actor="user_chat_direct", reason=reason, session_id=session_id, event_seq=event_seq)
        messages.append(f"Firewall rule disabled: {row['rule_id']} name={row['name']}")
    for line in direct_user_firewall_enable_lines(prompt):
        if not _is_session_firewall_enable_line(line):
            continue
        active = [
            row for row in firewall_overrides(conn, include_expired=False, limit=200)
            if str(row.get("scope_type") or "") == "session"
            and str(row.get("session_id") or "") == session_id
            and bool(row.get("enabled"))
        ]
        for row in active:
            revoke_firewall_override(
                conn,
                str(row["override_id"]),
                actor="user_chat_direct",
                reason="direct user chat session firewall enable",
            )
        messages.append(f"Session firewall enabled: revoked={len(active)}")
    for line in direct_user_approve_explain_lines(prompt):
        intent = create_firewall_intent_approval(conn, line, session_id=session_id, event_seq=event_seq)
        messages.append(f"Firewall intent recorded: {intent['intent_id']} expires={intent['expires_at']}")
    return messages


def _parse_approve_explain_line(line: str) -> tuple[str, str]:
    text = re.sub(r"^approve\s+explain\b", "", str(line or ""), flags=re.I).strip()
    if not text:
        raise ValueError("approve explain requires an explanation")
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    return text, expires_at


def _extract_actions_from_text(text: str) -> list[str]:
    lower = str(text or "").lower()
    actions: list[str] = []
    mapping = {
        "deploy": ["deploy", "ssh", "docker compose", "hetzner", "server"],
        "network": ["network", "host", "http", "https", "curl", "ssh", "deploy"],
        "write": ["write", "edit", "patch", "change", "update"],
        "delete": ["delete", "remove", "rm"],
        "verify": ["test", "typecheck", "lint", "audit", "verify"],
    }
    for action, needles in mapping.items():
        if any(needle in lower for needle in needles):
            actions.append(action)
    return actions


def create_firewall_intent_approval(
    conn: sqlite3.Connection,
    line: str,
    *,
    session_id: str | None,
    event_seq: int | None,
) -> dict[str, Any]:
    text, expires_at = _parse_approve_explain_line(line)
    now = _now()
    intent_id = f"fwintent_{uuid.uuid4().hex[:16]}"
    hosts = _extract_hosts(text, include_bare_domains=True)
    _local_paths, remote_paths = _extract_paths(text)
    actions = _extract_actions_from_text(text)
    conn.execute(
        """
        insert into firewall_intent_approvals (
          intent_id, created_at, expires_at, session_id, user_event_seq, intent_text,
          allowed_hosts_json, allowed_actions_json, allowed_paths_json, constraints_json,
          source_user_message_hash
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            intent_id,
            now,
            expires_at,
            session_id,
            event_seq,
            text,
            _json_dumps(hosts),
            _json_dumps(actions),
            _json_dumps(remote_paths),
            _json_dumps({"source": "direct_user_approve_explain", "line_redacted_from_event_prompt": True}),
            hashlib.sha256(str(line or "").encode("utf-8", errors="replace")).hexdigest(),
        ),
    )
    row = conn.execute("select * from firewall_intent_approvals where intent_id = ?", (intent_id,)).fetchone()
    return _row_dict(row)


def active_firewall_intent_summaries(conn: sqlite3.Connection, *, session_id: str | None, limit: int = 5) -> list[dict[str, Any]]:
    now = _now()
    rows = conn.execute(
        """
        select *
        from firewall_intent_approvals
        where session_id = ?
          and datetime(expires_at) > datetime(?)
        order by created_at desc
        limit ?
        """,
        (session_id, now, max(1, min(int(limit), 20))),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "intent_id": row["intent_id"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "intent_text": row["intent_text"],
                "allowed_hosts": _json_list(row["allowed_hosts_json"]),
                "allowed_actions": _json_list(row["allowed_actions_json"]),
                "allowed_paths": _json_list(row["allowed_paths_json"]),
                "policy_note": "Direct user approve-explain intent; context only, not a durable approval and not a rule.",
            }
        )
    return result


def list_firewall_rules(
    conn: sqlite3.Connection,
    *,
    status: str | None = "active",
    rule_kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_parts: list[str] = []
    if status:
        where_parts.append("status = ?")
        params.append(status)
    if rule_kind:
        where_parts.append("rule_kind = ?")
        params.append(rule_kind)
    where = "where " + " and ".join(where_parts) if where_parts else ""
    rows = conn.execute(
        f"""
        select r.*,
               (select count(*) from firewall_rule_audit a where a.rule_id = r.rule_id and a.action = 'matched') as match_count,
               (select max(a.created_at) from firewall_rule_audit a where a.rule_id = r.rule_id and a.action = 'matched') as last_matched_at
        from firewall_rules r
        {where}
        order by updated_at desc
        limit ?
        """,
        (*params, max(1, min(int(limit), 250))),
    )
    return [_row_dict(row) for row in rows]


def get_firewall_rule(conn: sqlite3.Connection, rule_id: str) -> dict[str, Any] | None:
    row = conn.execute("select * from firewall_rules where rule_id = ?", (rule_id,)).fetchone()
    if row is None:
        return None
    data = _row_dict(row)
    family_id = str(data.get("family_id") or data.get("rule_id") or "")
    audit = conn.execute(
        """
        select *
        from firewall_rule_audit
        where rule_id = ? or family_id = ?
        order by created_at desc
        limit 150
        """,
        (rule_id, family_id),
    )
    data["audit"] = [_row_dict(item) for item in audit]
    history = conn.execute(
        """
        select r.*,
               (select count(*) from firewall_rule_audit a where a.rule_id = r.rule_id and a.action = 'matched') as match_count,
               (select max(a.created_at) from firewall_rule_audit a where a.rule_id = r.rule_id and a.action = 'matched') as last_matched_at
        from firewall_rules r
        where r.family_id = ?
        order by r.version desc, r.created_at desc
        """,
        (family_id,),
    )
    data["history"] = [_row_dict(item) for item in history]
    return data


def active_llm_firewall_contexts(
    conn: sqlite3.Connection,
    *,
    session_id: str | None,
    project_id: str | None,
    workdir: str | None,
    target_workdirs: list[str] | None = None,
    event_seq: int | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    now = _now()
    rows = conn.execute(
        """
        select *
        from firewall_rules
        where status = 'active'
          and rule_kind = 'llm_context'
          and classifier_context is not null
          and (expires_at is null or datetime(expires_at) > datetime(?))
        order by updated_at desc
        limit 50
        """,
        (now,),
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        scope = str(row["scope_type"] or "global")
        if scope == "session" and row["session_id"] and row["session_id"] != session_id:
            continue
        if scope == "project" and row["project_id"] and row["project_id"] != project_id:
            continue
        workdir_candidates = [item for item in [workdir, *(target_workdirs or [])] if item]
        if scope == "workdir" and row["workdir_prefix"] and not _path_matches([row["workdir_prefix"]], workdir_candidates):
            continue
        context = {
            "rule_id": row["rule_id"],
            "family_id": row["family_id"],
            "version": row["version"],
            "name": row["name"],
            "scope_type": row["scope_type"],
            "reason": row["reason"],
            "classifier_context": row["classifier_context"],
            "context_hash": row["context_hash"],
            "policy_note": "Versioned direct-user/monitor-audited LLM firewall context rule.",
        }
        result.append(context)
        conn.execute(
            """
            insert into firewall_rule_audit (
              audit_id, rule_id, family_id, created_at, action, actor, reason,
              after_json, session_id, event_seq
            ) values (?, ?, ?, ?, 'injected_into_classifier', 'system', ?, ?, ?, ?)
            """,
            (
                f"fwraudit_{uuid.uuid4().hex[:16]}",
                row["rule_id"],
                row["family_id"],
                now,
                "llm context rule included in classifier payload",
                _json_dumps({"context_hash": row["context_hash"], "scope_type": row["scope_type"]}),
                session_id,
                event_seq,
            ),
        )
        if len(result) >= max(1, min(int(limit), 20)):
            break
    return result


def _extract_hosts(command: str, *, include_bare_domains: bool = False) -> list[str]:
    hosts: list[str] = []
    try:
        parts = shlex.split(str(command or ""))
    except ValueError:
        parts = str(command or "").split()
    if parts and parts[0] == "ssh":
        skip_next = False
        for token in parts[1:]:
            if skip_next:
                skip_next = False
                continue
            if token in {"-i", "-p", "-l", "-F", "-o"}:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            target = token.split("@", 1)[-1]
            target = target.split(":", 1)[0]
            if target and target not in hosts:
                hosts.append(target)
            break
    patterns = [
        r"\b(?:scp|rsync)\b[^;\n]*?(?:[A-Za-z0-9_.-]+@)([A-Za-z0-9_.-]+):",
        r"https?://([^/\s'\";]+)",
    ]
    if include_bare_domains:
        patterns.append(r"\b([A-Za-z0-9][A-Za-z0-9_.-]*\.[A-Za-z]{2,})\b")
    for pattern in patterns:
        for match in re.finditer(pattern, command or ""):
            host = match.group(1).strip()
            suffix = host.rsplit(".", 1)[-1].lower() if "." in host else ""
            if suffix in HOSTLIKE_EXCLUDED_SUFFIXES:
                continue
            if host and host not in hosts and not host.startswith("-"):
                hosts.append(host)
    return hosts


def _extract_paths(command: str) -> tuple[list[str], list[str]]:
    local: list[str] = []
    remote: list[str] = []
    for item in re.findall(r"(?:^|\s)(/[A-Za-z0-9_./~+-]+)", command or ""):
        if item not in local:
            local.append(item)
    for item in re.findall(r":(/[A-Za-z0-9_./~+-]+)", command or ""):
        if item not in remote:
            remote.append(item)
    return local, remote


def _path_matches(prefixes: list[str], values: list[str], fallback: str | None = None) -> bool:
    if not prefixes:
        return True
    candidates = list(values)
    if fallback:
        candidates.append(fallback)
    expanded_candidates: list[str] = []
    for candidate in candidates:
        expanded_candidates.append(candidate)
        if str(candidate).startswith("/private/var/"):
            expanded_candidates.append("/var/" + str(candidate)[len("/private/var/") :])
        elif str(candidate).startswith("/var/"):
            expanded_candidates.append("/private/var/" + str(candidate)[len("/var/") :])
    for prefix in prefixes:
        prefix_values = [prefix]
        if str(prefix).startswith("/private/var/"):
            prefix_values.append("/var/" + str(prefix)[len("/private/var/") :])
        elif str(prefix).startswith("/var/"):
            prefix_values.append("/private/var/" + str(prefix)[len("/var/") :])
        for prefix_value in prefix_values:
            base = prefix_value.rstrip("/")
            for value in expanded_candidates:
                current = str(value or "").rstrip("/")
                if current == base or current.startswith(base + "/"):
                    return True
    return False


def _any_pattern_match(patterns: list[str], values: list[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns for value in values)


def _active_rule_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    now = _now()
    return list(
        conn.execute(
            """
            select *
            from firewall_rules
            where status = 'active'
              and rule_kind = 'deterministic'
              and (expires_at is null or datetime(expires_at) > datetime(?))
            order by updated_at desc
            limit 250
            """,
            (now,),
        )
    )


def match_firewall_rules(
    conn: sqlite3.Connection,
    *,
    command: str,
    tool_name: str | None,
    action_class: str,
    session_id: str | None,
    project_id: str | None,
    workdir: str | None,
    target_workdirs: list[str] | None = None,
) -> dict[str, Any] | None:
    normalized_tool = str(tool_name or "").lower()
    hosts = _extract_hosts(command)
    local_paths, remote_paths = _extract_paths(command)
    scope_candidates = [item for item in [workdir, *(target_workdirs or []), *local_paths] if item]
    normalized_command = " ".join(str(command or "").strip().split())
    for row in _active_rule_rows(conn):
        denied = set(_json_list(row["denied_actions_json"]))
        if action_class in denied:
            return {"matched": False, "deny": True, "rule": _row_dict(row), "reason": "deny action matched"}
        allowed_actions = _json_list(row["allowed_actions_json"])
        if allowed_actions and action_class not in allowed_actions:
            continue
        tools = [item.lower() for item in _json_list(row["allowed_tools_json"])]
        if tools and normalized_tool not in tools:
            continue
        scope = str(row["scope_type"] or "global")
        if scope == "session" and row["session_id"] and row["session_id"] != session_id:
            continue
        if scope == "project" and row["project_id"] and row["project_id"] != project_id:
            continue
        if scope == "workdir" and row["workdir_prefix"] and not _path_matches([row["workdir_prefix"]], scope_candidates):
            continue
        rule_hosts = _json_list(row["allowed_hosts_json"])
        if rule_hosts and not _any_pattern_match(rule_hosts, hosts):
            continue
        if not _path_matches(_json_list(row["allowed_local_paths_json"]), local_paths, workdir):
            continue
        if not _path_matches(_json_list(row["allowed_remote_paths_json"]), remote_paths):
            continue
        if not _any_pattern_match(_json_list(row["command_patterns_json"]), [normalized_command]):
            continue
        return {
            "matched": True,
            "deny": False,
            "rule": _row_dict(row),
            "hosts": hosts,
            "local_paths": local_paths,
            "remote_paths": remote_paths,
            "scope_candidates": scope_candidates,
            "target_workdirs": target_workdirs or [],
        }
    return None


def apply_firewall_rule_match(
    conn: sqlite3.Connection,
    decision: RiskDecision,
    match: dict[str, Any] | None,
    *,
    session_id: str | None,
    event_seq: int | None,
) -> RiskDecision:
    if not match:
        return decision
    rule = match.get("rule") or {}
    rule_id = str(rule.get("rule_id") or "")
    already_matched = f"firewall_rule:{rule_id}" in (decision.deterministic_flags or [])
    now = _now()
    flags = set(decision.categories or []) | set(decision.poisoning_flags or []) | set(decision.deterministic_flags or [])
    if match.get("deny"):
        decision.decision = "block"
        decision.risk_level = "critical" if decision.risk_level == "critical" else "high"
        decision.approval_state = "firewall_rule_denied"
        if "firewall_rule_denied" not in decision.deterministic_flags:
            decision.deterministic_flags.append("firewall_rule_denied")
        decision.reason = f"Firewall rule {rule_id} denied this action. Original reason: {decision.reason}"
        conn.execute(
            """
            insert into firewall_rule_audit (
              audit_id, rule_id, family_id, created_at, action, actor, reason, session_id, event_seq
            ) values (?, ?, ?, ?, 'rejected', 'system', ?, ?, ?)
            """,
            (f"fwraudit_{uuid.uuid4().hex[:16]}", rule_id, rule.get("family_id"), now, "deny action matched", session_id, event_seq),
        )
        return decision
    if flags & NON_OVERRIDABLE_HARD_BLOCK_FLAGS:
        return decision
    if decision.should_block or decision.decision == "quarantine" or decision.approval_state == "required":
        decision.decision = "warn"
        if decision.risk_level == "critical":
            decision.risk_level = "high"
        elif decision.risk_level not in {"high", "medium", "low"}:
            decision.risk_level = "medium"
        decision.approval_state = "firewall_rule_matched"
        decision.memory_action = "reference_only"
        decision.injection_policy = "on_demand"
        for flag in ("firewall_rule_matched", f"firewall_rule:{rule_id}"):
            if flag not in decision.deterministic_flags:
                decision.deterministic_flags.append(flag)
        decision.reason = f"Firewall rule {rule_id} matched: {rule.get('reason')}. Original reason: {decision.reason}"
        decision.impact = "A direct-user-created firewall rule matched this tool use; execution is downgraded to an audited warning, not silently allowed."
        decision.confidence = max(float(decision.confidence or 0), 0.95)
    if not already_matched:
        conn.execute(
            """
            insert into firewall_rule_audit (
              audit_id, rule_id, family_id, created_at, action, actor, reason, after_json, session_id, event_seq
            ) values (?, ?, ?, ?, 'matched', 'system', ?, ?, ?, ?)
            """,
            (
                f"fwraudit_{uuid.uuid4().hex[:16]}",
                rule_id,
                rule.get("family_id"),
                now,
                "rule matched pretool decision",
                _json_dumps({"decision": decision.to_json(), "match": {k: v for k, v in match.items() if k != "rule"}}),
                session_id,
                event_seq,
            ),
        )
    return decision


def firewall_policy_summary(match: dict[str, Any] | None) -> dict[str, Any] | None:
    if not match or not match.get("matched"):
        return None
    rule = match.get("rule") or {}
    return {
        "rule_id": rule.get("rule_id"),
        "name": rule.get("name"),
        "reason": rule.get("reason"),
        "scope_type": rule.get("scope_type"),
        "allowed_actions": _json_list(rule.get("allowed_actions_json")),
        "allowed_hosts": _json_list(rule.get("allowed_hosts_json")),
        "allowed_local_paths": _json_list(rule.get("allowed_local_paths_json")),
        "allowed_remote_paths": _json_list(rule.get("allowed_remote_paths_json")),
        "policy_note": (
            "A direct-user-created firewall rule matches this candidate tool use. "
            "Use it only as policy context; hard blockers and deny rules still override it."
        ),
    }


def redact_sensitive_text(text: str) -> tuple[str, dict[str, int]]:
    redacted = str(text or "")
    report: dict[str, int] = {}
    for idx, pattern in enumerate(SECRET_PATTERNS):
        count = 0

        def repl(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            if match.lastindex and match.lastindex >= 1 and pattern.pattern.startswith("(?i)("):
                return f"{match.group(1)}<redacted>"
            return "<redacted-secret>"

        redacted = pattern.sub(repl, redacted)
        if count:
            report[f"pattern_{idx}"] = count
    return redacted, report


def suggest_firewall_rules(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
    until: str | None = None,
    session_id: str | None = None,
    workdir: str | None = None,
    host: str | None = None,
    action: str | None = None,
    limit: int = 50,
    store: bool = True,
) -> dict[str, Any]:
    where = ["status in ('blocked', 'warned', 'bypassed_by_firewall_override')"]
    params: list[Any] = []
    if since:
        where.append("created_at >= ?")
        params.append(since)
    if until:
        where.append("created_at <= ?")
        params.append(until)
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if workdir:
        where.append("workdir like ?")
        params.append(f"{workdir.rstrip('/')}%")
    rows = list(
        conn.execute(
            f"""
            select *
            from risk_events
            where {' and '.join(where)}
            order by created_at desc
            limit ?
            """,
            (*params, max(1, min(int(limit), 250))),
        )
    )
    clusters: dict[tuple[str, str, str], dict[str, Any]] = {}
    redaction_report: dict[str, int] = {}
    for row in rows:
        preview, report = redact_sensitive_text(row["preview"] or "")
        for key, value in report.items():
            redaction_report[key] = redaction_report.get(key, 0) + value
        command_action = shell_action_class(preview)
        if action and command_action != action:
            continue
        hosts = _extract_hosts(preview)
        if host and host not in hosts:
            continue
        cluster_host = hosts[0] if hosts else ""
        key = (command_action, cluster_host, row["workdir"] or "")
        item = clusters.setdefault(
            key,
            {
                "action": command_action,
                "host": cluster_host,
                "workdir": row["workdir"],
                "count": 0,
                "first_seen_at": row["created_at"],
                "last_seen_at": row["created_at"],
                "risk_event_ids": [],
                "redacted_previews": [],
            },
        )
        item["count"] += 1
        item["first_seen_at"] = min(item["first_seen_at"], row["created_at"])
        item["last_seen_at"] = max(item["last_seen_at"], row["created_at"])
        item["risk_event_ids"].append(row["risk_event_id"])
        if len(item["redacted_previews"]) < 3:
            item["redacted_previews"].append(preview[:240])
    def suggestion_priority(item: dict[str, Any]) -> tuple[int, int, int, str]:
        action_priority = 1 if item["action"] in {"network", "deploy", "write_execute", "delete"} else 0
        host_priority = 1 if item.get("host") else 0
        return (action_priority, host_priority, int(item["count"]), str(item["last_seen_at"]))

    suggestions = sorted(clusters.values(), key=suggestion_priority, reverse=True)
    if suggestions:
        top = suggestions[0]
        expires = "7d" if top["action"] in {"deploy", "network", "write_execute"} else "30d"
        parts = [
            "firewall",
            "add",
            "--name",
            shlex.quote(f"{top['action']} {top['host'] or 'local'}".strip()),
            "--reason",
            shlex.quote(f"reviewed repeated {top['action']} pattern from blocked Agent Context Engine risk events"),
            "--action",
            shlex.quote(top["action"]),
            "--expires",
            expires,
        ]
        if top["host"]:
            parts.extend(["--host", shlex.quote(top["host"])])
        if top["workdir"]:
            parts.extend(["--scope", "workdir", "--workdir", shlex.quote(top["workdir"])])
        suggested_command = " ".join(parts)
    else:
        suggested_command = ""
    result = {
        "suggestions": suggestions,
        "suggested_command": suggested_command,
        "redaction_report": redaction_report,
        "safety_notes": [
            "Suggestions are derived from redacted risk-event summaries.",
            "Raw blocked payloads are not stored in suggestion evidence.",
            "A rule is active only after the user sends the final firewall add line directly.",
        ],
    }
    if store and suggested_command:
        suggestion_id = f"fwsug_{uuid.uuid4().hex[:16]}"
        now = _now()
        conn.execute(
            """
            insert into firewall_rule_suggestions (
              suggestion_id, created_at, status, source_window_start, source_window_end,
              source_filters_json, summary_json, suggested_command, safety_notes_json,
              redaction_report_json
            ) values (?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suggestion_id,
                now,
                since,
                until,
                _json_dumps({"session_id": session_id, "workdir": workdir, "host": host, "action": action, "limit": limit}),
                _json_dumps({"suggestions": suggestions}),
                suggested_command,
                _json_dumps(result["safety_notes"]),
                _json_dumps(redaction_report),
            ),
        )
        for item in suggestions[:10]:
            for risk_event_id in item["risk_event_ids"][:10]:
                conn.execute(
                    """
                    insert into firewall_rule_suggestion_evidence (
                      evidence_id, suggestion_id, source_kind, source_id, trusted_level,
                      raw_payload_included, tainted_source, allowed_for_policy_generation, summary_json
                    ) values (?, ?, 'risk_event_summary', ?, 'redacted_summary', 0, 1, 1, ?)
                    """,
                    (f"fwsevd_{uuid.uuid4().hex[:16]}", suggestion_id, risk_event_id, _json_dumps({"action": item["action"], "host": item["host"], "workdir": item["workdir"]})),
                )
        result["suggestion_id"] = suggestion_id
    return result
