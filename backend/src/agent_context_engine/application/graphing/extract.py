from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from ...infrastructure.config import ROOT, safe_slug, utc_now
from ...infrastructure.db import session_events
from .schema import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_RELATION_TYPES,
    GRAPH_SCHEMA_VERSION,
    MAX_EVIDENCE_PER_ITEM,
    apply_metadata,
    normalize_entity_language,
    normalized_metadata,
)


PATH_RE = re.compile(r"(?P<path>(?:/Users/[A-Za-z0-9._~+/@%-]+|(?:\.{1,2}/)?[A-Za-z0-9._~+@%-]+(?:/[A-Za-z0-9._~+@%-]+)+))")
FILE_TOKEN_RE = re.compile(r"\b[A-Za-z0-9._~+@%-]+\.(?:md|txt|json|toml|yaml|yml|py|js|ts|tsx|jsx|sh|zsh|plist)\b")
URL_RE = re.compile(r"https?://[^\s)>\"]+")
ENV_RE = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")
SKILL_RE = re.compile(r"(docs/skills/([A-Za-z0-9._-]+)(?:/[A-Za-z0-9._~+@%-]+)?)")
TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
COMMAND_PATH_RE = re.compile(r"(?:/Users/[^\s'\"]+|(?:\.{1,2}/)?[A-Za-z0-9._~+@%-]+(?:/[A-Za-z0-9._~+@%-]+)+)")
TECH_TERMS = {
    "codex": "Codex",
    "claude": "Claude Code",
    "cursor": "Cursor",
    "neo4j": "Neo4j",
    "sqlite": "SQLite",
    "d3": "D3",
    "d3.js": "D3.js",
    "node": "Node.js",
    "vitepress": "VitePress",
    "rollup": "Rollup",
    "notebooklm": "NotebookLM",
    "mcp": "MCP",
    "launchagent": "LaunchAgent",
}


def _safe_split_json(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(value).strip() for value in parsed if str(value).strip()]


def _normalize_graph_risk_level(raw: str | None) -> str:
    level = str(raw or "").strip().lower()
    if level == "critical":
        return "high"
    if level in {"low", "medium", "high", "unknown"}:
        return level
    if level == "none":
        return "low"
    return "low"


def _normalize_graph_injection_policy(raw: str | None) -> str:
    policy = str(raw or "").strip().lower()
    if policy in {"startup_safe", "on_demand", "never_auto"}:
        return policy
    if policy == "quarantine":
        return "never_auto"
    return "on_demand"


def _security_risk_metadata(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "memory_kind": "policy",
        "source_kind": "event",
        "confidence": 0.97,
        "risk_level": _normalize_graph_risk_level(row["risk_level"]),
        "sensitivity": str(row["sensitivity"] or "normal"),
        "injection_policy": _normalize_graph_injection_policy(row["injection_policy"]),
        "valid_from": row["created_at"],
    }


def _policy_patch_metadata(created_at: str | None) -> dict[str, Any]:
    return {
        "memory_kind": "policy",
        "source_kind": "event",
        "confidence": 0.98,
        "risk_level": "low",
        "sensitivity": "private",
        "injection_policy": "on_demand",
        "valid_from": created_at,
    }


def entity_key(entity_type: str, raw: str) -> str:
    value = raw.strip()
    if entity_type in {"File", "Directory", "Document", "ReferenceAsset", "GeneratedAsset", "ConfigFile"}:
        return str(normalize_path(value))
    if entity_type in {"CLICommand", "ShellCommand"}:
        return normalize_command(value)
    return safe_slug(value.lower())


def project_relative_path(path: Path, session: sqlite3.Row | None = None) -> str:
    return str(path.resolve())


def normalize_path(value: str, cwd: str | None = None) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (Path(cwd).expanduser() if cwd else ROOT) / path
    return path.resolve()


def normalize_command(value: str) -> str:
    text = " ".join(value.strip().split())
    if not text:
        return "unknown"
    text = COMMAND_PATH_RE.sub("<path>", text)
    text = text.replace("/<path>", "<path>")
    text = re.sub(r"\b[0-9a-f]{8}-[0-9a-f-]{27,}\b", "<uuid>", text, flags=re.I)
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}T[0-9:._+-Z]+\b", "<timestamp>", text)
    parts = text.split()
    executable = parts[0]
    return " ".join([executable, *parts[1:8]])


def command_family(value: str) -> str:
    normalized = normalize_command(value)
    parts = normalized.split()
    if not parts:
        return "unknown"
    executable = parts[0]
    if executable == "<path>" and len(parts) > 1:
        return f"{executable} {parts[1]}"
    if executable in {"git", "npm", "yarn", "npx", "python", "python3", "sqlite3"} and len(parts) > 1:
        return f"{executable} {parts[1]}"
    if executable in {"sed", "find", "rg", "ls", "du", "cat", "jq"}:
        return executable
    return executable


def command_family_key(value: str) -> str:
    return command_family(value)


def command_family_properties(value: str) -> dict[str, Any]:
    family = command_family(value)
    parts = family.split()
    return {
        "family": family,
        "executable": parts[0] if parts else "unknown",
        "arity": len(parts),
    }


def evidence(source_type: str, session_id: str, field: str, quote: str, event_seq: int | None = None, path: str | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "source_type": source_type,
        "session_id": session_id,
        "field": field,
    }
    if event_seq is not None:
        item["event_seq"] = event_seq
    if path:
        item["path"] = path
    if quote:
        item["quote"] = quote[:500]
    return item


class GraphBuilder:
    def __init__(self, session: sqlite3.Row):
        self.session = session
        self.entities: dict[tuple[str, str], dict[str, Any]] = {}
        self.relations: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def add_entity(
        self,
        entity_type: str,
        name: str,
        *,
        key: str | None = None,
        evidence_items: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if entity_type not in ALLOWED_ENTITY_TYPES:
            raise ValueError(f"unsupported entity type: {entity_type}")
        entity_key_value = key or entity_key(entity_type, name)
        dedupe = (entity_type, entity_key_value)
        existing = self.entities.get(dedupe)
        if existing is None:
            meta = normalized_metadata(metadata, default_source_kind="event")
            existing = {
                "type": entity_type,
                "key": entity_key_value,
                "name": name,
                "aliases": [],
                "properties": properties or {},
                "evidence": [],
            }
            normalize_entity_language(existing)
            apply_metadata(existing, meta)
            self.entities[dedupe] = existing
        elif properties:
            existing["properties"].update({k: v for k, v in properties.items() if v is not None})
        if metadata:
            meta = normalized_metadata(metadata, default_confidence=float(existing.get("confidence", 1.0) or 1.0))
            existing["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), meta["confidence"])
            for key in ("risk_level", "sensitivity", "injection_policy", "memory_kind", "source_kind", "valid_from", "valid_to", "staleness"):
                if meta.get(key) and not existing.get(key):
                    existing[key] = meta[key]
            flags = list(existing.get("poisoning_flags") or [])
            for flag in meta["poisoning_flags"]:
                if flag not in flags:
                    flags.append(flag)
            existing["poisoning_flags"] = flags
        for item in evidence_items or []:
            if len(existing["evidence"]) >= MAX_EVIDENCE_PER_ITEM:
                break
            if item not in existing["evidence"]:
                existing["evidence"].append(item)
        return existing

    def add_relation(
        self,
        from_entity: dict[str, Any],
        relation_type: str,
        to_entity: dict[str, Any],
        *,
        evidence_items: list[dict[str, Any]] | None = None,
        properties: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if relation_type not in ALLOWED_RELATION_TYPES:
            raise ValueError(f"unsupported relation type: {relation_type}")
        dedupe = (from_entity["type"], from_entity["key"], relation_type, f"{to_entity['type']}:{to_entity['key']}")
        existing = self.relations.get(dedupe)
        if existing is None:
            meta = normalized_metadata(metadata, default_source_kind="event")
            existing = {
                "from": {"type": from_entity["type"], "key": from_entity["key"]},
                "type": relation_type,
                "to": {"type": to_entity["type"], "key": to_entity["key"]},
                "properties": properties or {},
                "evidence": [],
            }
            apply_metadata(existing, meta)
            self.relations[dedupe] = existing
        elif properties:
            existing["properties"].update({k: v for k, v in properties.items() if v is not None})
        if metadata:
            meta = normalized_metadata(metadata, default_confidence=float(existing.get("confidence", 1.0) or 1.0))
            existing["confidence"] = max(float(existing.get("confidence", 0.0) or 0.0), meta["confidence"])
            flags = list(existing.get("poisoning_flags") or [])
            for flag in meta["poisoning_flags"]:
                if flag not in flags:
                    flags.append(flag)
            existing["poisoning_flags"] = flags
        for item in evidence_items or []:
            if len(existing["evidence"]) >= MAX_EVIDENCE_PER_ITEM:
                break
            if item not in existing["evidence"]:
                existing["evidence"].append(item)

    def patch(self, *, source_kind: str, source_id: str, generated_by: str = "deterministic") -> dict[str, Any]:
        return {
            "schema_version": GRAPH_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "generated_by": generated_by,
            "source": {
                "kind": source_kind,
                "id": source_id,
                "session_id": self.session["session_id"],
            },
            "entities": sorted(self.entities.values(), key=lambda e: (e["type"], e["key"])),
            "relations": sorted(self.relations.values(), key=lambda r: (r["from"]["type"], r["from"]["key"], r["type"], r["to"]["type"], r["to"]["key"])),
        }


def parse_tool_input_command(tool_input_json: str | None) -> str | None:
    if not tool_input_json:
        return None
    try:
        data = json.loads(tool_input_json)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        command = data.get("command") or data.get("cmd")
        if isinstance(command, str) and command.strip():
            return command.strip()
    return None


def likely_file_type(path: Path) -> str:
    if path.exists() and path.is_dir():
        return "Directory"
    if not path.suffix:
        return "Directory"
    if path.suffix in {".md", ".txt", ".jsonl"}:
        return "Document"
    if path.suffix in {".json", ".toml", ".yaml", ".yml", ".plist"}:
        return "ConfigFile"
    if path.suffix in {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".wav", ".mp3"}:
        return "ReferenceAsset"
    return "File"


def extract_paths(text: str) -> list[str]:
    paths: list[str] = []
    for match in PATH_RE.finditer(text):
        raw = match.group("path").rstrip(".,:;")
        first = raw.split("/", 1)[0].lstrip(".")
        looks_project_path = first in {"docs", "memory", "projects", "games", "frontend", "backend", "src", "scripts", ".codex", ".claude", ".cursor"}
        if "/" in raw and not raw.startswith("http") and (raw.startswith(("/Users/", "./", "../")) or Path(raw).suffix or looks_project_path):
            paths.append(raw)
    for match in FILE_TOKEN_RE.finditer(text):
        paths.append(match.group(0).rstrip(".,:;"))
    return sorted(set(paths))


def extract_urls(text: str) -> list[str]:
    return sorted({url.rstrip(".,") for url in URL_RE.findall(text)})


def extract_env_vars(text: str) -> list[str]:
    return []


def extract_tickets(text: str) -> list[str]:
    return sorted(set(TICKET_RE.findall(text)))


def patch_touched_files(text: str) -> list[str]:
    paths: list[str] = []
    for line in text.splitlines():
        if line.startswith("*** Update File: ") or line.startswith("*** Add File: "):
            paths.append(line.split(": ", 1)[1].strip())
    return paths


def add_semantic_entities(builder: GraphBuilder, session_entity: dict[str, Any], text: str, ev: dict[str, Any]) -> None:
    lowered = text.lower()
    for raw, label in TECH_TERMS.items():
        if raw in lowered:
            entity_type = "ClientHarness" if label in {"Codex", "Claude Code", "Cursor"} else "Technology"
            tech_entity = builder.add_entity(entity_type, label, key=safe_slug(label.lower()), evidence_items=[ev])
            builder.add_relation(session_entity, "USES_TECH" if entity_type == "Technology" else "USED_TOOL", tech_entity, evidence_items=[ev])
            concept_entity = builder.add_entity("Concept", label, key=safe_slug(label.lower()), evidence_items=[ev])
            builder.add_relation(session_entity, "MENTIONED", concept_entity, evidence_items=[ev])
    for ticket in extract_tickets(text):
        ticket_entity = builder.add_entity("Ticket", ticket, key=ticket, evidence_items=[ev])
        builder.add_relation(session_entity, "MENTIONED", ticket_entity, evidence_items=[ev])
    for marker in ("offen", "open task", "todo", "follow-up", "nächste", "naechste"):
        if marker in lowered:
            task_entity = builder.add_entity("OpenTask", marker, key=f"{builder.session['session_id']}:{safe_slug(marker)}", evidence_items=[ev], properties={"source_marker": marker})
            builder.add_relation(session_entity, "TRACKS", task_entity, evidence_items=[ev])
    for marker in ("entscheidung", "decision", "beschlossen", "gilt", "default"):
        if marker in lowered:
            decision_entity = builder.add_entity("Decision", marker, key=f"{builder.session['session_id']}:{safe_slug(marker)}", evidence_items=[ev], properties={"source_marker": marker})
            builder.add_relation(session_entity, "TRACKS", decision_entity, evidence_items=[ev])


def add_text_entities(builder: GraphBuilder, event: sqlite3.Row, session_entity: dict[str, Any], text: str, field: str) -> None:
    if not text:
        return
    ev = evidence("event", builder.session["session_id"], field, text, event_seq=int(event["seq"]))
    touched = set(patch_touched_files(text))
    paths = extract_paths(text)
    path_limit = 20 if field == "tool_response_text" else 35
    if len(paths) > path_limit:
        paths = paths[:path_limit]
    for raw_path in paths:
        path = normalize_path(raw_path, event["cwd"] or builder.session["last_workdir"] or builder.session["cwd"])
        entity_type = likely_file_type(path)
        key = project_relative_path(path, builder.session)
        properties = {"path": str(path), "path_key": key}
        file_entity = builder.add_entity(entity_type, key, key=key, evidence_items=[ev], properties=properties)
        relation_type = "TOUCHED_FILE" if raw_path in touched or str(path) in touched else "MENTIONED"
        builder.add_relation(session_entity, relation_type, file_entity, evidence_items=[ev])
        for skill_match in SKILL_RE.finditer(raw_path):
            skill_name = skill_match.group(2)
            skill_entity = builder.add_entity("Skill", skill_name, key=safe_slug(skill_name), evidence_items=[ev], properties={"path": skill_match.group(1)})
            builder.add_relation(session_entity, "USED_SKILL", skill_entity, evidence_items=[ev])
    for url in extract_urls(text):
        url_entity = builder.add_entity("ExternalURL", url, key=url, evidence_items=[ev], properties={"url": url})
        builder.add_relation(session_entity, "MENTIONED", url_entity, evidence_items=[ev])
    for env_name in extract_env_vars(text):
        env_entity = builder.add_entity("EnvironmentVariable", env_name, key=env_name, evidence_items=[ev])
        builder.add_relation(session_entity, "MENTIONED", env_entity, evidence_items=[ev])
    for concept in ["agent memory", "dream", "summary", "hooks", "memory", "graph", "handover"]:
        if concept in text.lower():
            concept_entity = builder.add_entity("Concept", concept, key=safe_slug(concept), evidence_items=[ev])
            builder.add_relation(session_entity, "MENTIONED", concept_entity, evidence_items=[ev])
    add_semantic_entities(builder, session_entity, text, ev)


FILE_ACCESS_RELATION = {
    "create": "CREATED_FILE",
    "modify": "MODIFIED_FILE",
    "delete": "DELETED_FILE",
    "rename": "RENAMED_FILE",
    "write": "WROTE_FILE",
}

GRAPH_FILE_CHANGE_OPERATIONS = set(FILE_ACCESS_RELATION)


def add_file_access_entities(builder: GraphBuilder, session_entity: dict[str, Any], access: sqlite3.Row) -> None:
    operation = str(access["operation"] or "")
    if operation not in GRAPH_FILE_CHANGE_OPERATIONS:
        return
    quote = access["evidence_quote"] or f"{access['operation']} {access['path_key']}"
    ev = evidence(
        "file_access",
        builder.session["session_id"],
        "file_accesses",
        quote,
        event_seq=int(access["seq"]),
        path=access["path_key"],
    )
    path_value = access["path_abs"] or access["path_raw"]
    file_type = likely_file_type(Path(path_value))
    file_entity = builder.add_entity(
        file_type,
        access["path_key"],
        key=access["path_key"],
        evidence_items=[ev],
        properties={"path": path_value, "path_key": access["path_key"]},
        metadata={"confidence": float(access["confidence"] or 0.8), "source_kind": "event", "memory_kind": "raw"},
    )
    change_type = "FileDelete" if operation == "delete" else "FileChange"
    change_entity = builder.add_entity(
        change_type,
        f"{access['operation']} {access['path_key']}",
        key=access["file_access_id"],
        evidence_items=[ev],
        properties={
            "operation": access["operation"],
            "seq": access["seq"],
            "tool_name": access["tool_name"],
            "tool_use_id": access["tool_use_id"],
            "status": access["status"],
            "source_kind": access["source_kind"],
            "path_key": access["path_key"],
        },
        metadata={"confidence": float(access["confidence"] or 0.8), "source_kind": "event", "memory_kind": "raw"},
    )
    relation_type = FILE_ACCESS_RELATION[operation]
    metadata = {"confidence": float(access["confidence"] or 0.8), "source_kind": "event", "memory_kind": "raw"}
    builder.add_relation(session_entity, relation_type, file_entity, evidence_items=[ev], properties={"seq": access["seq"], "tool_name": access["tool_name"], "status": access["status"], "source_kind": access["source_kind"]}, metadata=metadata)
    builder.add_relation(session_entity, "PERFORMED", change_entity, evidence_items=[ev], metadata=metadata)
    builder.add_relation(change_entity, "ON_FILE", file_entity, evidence_items=[ev], metadata=metadata)


def _collect_risk_evidence(conn: sqlite3.Connection, session_id: str, risk_event_id: str) -> list[dict[str, Any]]:
    evidence_rows = conn.execute(
        "select * from risk_evidence where risk_event_id = ? order by created_at, evidence_id",
        (risk_event_id,),
    )
    result: list[dict[str, Any]] = []
    for item in evidence_rows:
        quote = str(item["quote"] or "").strip()
        if not quote:
            continue
        result.append(
            {
                "source_type": str(item["source_kind"] or "risk_event"),
                "session_id": session_id,
                "field": item["field"] or "risk_evidence",
                "quote": quote[:500],
            }
        )
    return result


def _add_risk_event(
    builder: GraphBuilder,
    session_entity: dict[str, Any],
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    risk_events_by_id: dict[str, dict[str, Any]],
) -> None:
    evidence_items = _collect_risk_evidence(conn, builder.session["session_id"], row["risk_event_id"])
    ev = evidence(
        "risk_event",
        builder.session["session_id"],
        "risk_events",
        row["preview"] or row["reason"] or row["risk_event_id"],
        event_seq=int(row["event_seq"]) if row["event_seq"] is not None else None,
    )
    evidence_items = evidence_items or [ev]
    evidence_items = list({json.dumps(item, sort_keys=True): item for item in evidence_items}.values())
    risk_entity = builder.add_entity(
        "RiskEvent",
        row["risk_event_id"],
        key=row["risk_event_id"],
        evidence_items=evidence_items,
        properties={
            "status": row["status"],
            "decision": row["decision"],
            "policy": row["policy"],
            "source_kind": row["source_kind"],
            "source_ref": row["source_ref"],
            "workdir": row["workdir"],
            "tool_name": row["tool_name"],
            "approval_state": row["approval_state"],
            "approval_token": row["approval_token"],
            "command_hash": row["command_hash"],
            "event_seq": row["event_seq"],
            "client_type": row["client_type"],
            "impact": row["impact"],
            "reason": row["reason"],
            "confidence": row["confidence"],
            "tool_call_id": row["tool_call_id"],
        },
        metadata=_security_risk_metadata(row),
    )
    builder.add_relation(session_entity, "TRACKS", risk_entity, evidence_items=[ev], metadata=_security_risk_metadata(row))
    risk_events_by_id[row["risk_event_id"]] = {"entity": risk_entity}
    if row["tool_name"]:
        risk_entity["properties"]["tool_name"] = row["tool_name"]


def _add_risk_policy_overrides(
    builder: GraphBuilder,
    session_entity: dict[str, Any],
    conn: sqlite3.Connection,
    risk_events_by_id: dict[str, dict[str, Any]],
) -> None:
    if not risk_events_by_id:
        return
    risk_ids = tuple(risk_events_by_id.keys())
    placeholders = ",".join("?" for _ in risk_ids)
    query = f"""
        select *
        from risk_policy_overrides
        where risk_event_id in ({placeholders})
        order by created_at, risk_event_id
    """
    for row in conn.execute(query, risk_ids):
        ev = evidence("risk_policy_override", builder.session["session_id"], "risk_policy_overrides", row["reason"])
        override_entity = builder.add_entity(
            "RiskPolicyOverride",
            row["override_id"],
            key=row["override_id"],
            evidence_items=[ev],
            properties={
                "action": row["action"],
                "previous_decision": row["previous_decision"],
                "new_decision": row["new_decision"],
                "previous_risk_level": row["previous_risk_level"],
                "new_risk_level": row["new_risk_level"],
                "reviewer": row["reviewer"],
                "risk_event_id": row["risk_event_id"],
            },
            metadata={
                "memory_kind": "policy",
                "source_kind": "event",
                "confidence": 0.99,
                "risk_level": _normalize_graph_risk_level(row["new_risk_level"]),
                "sensitivity": "private",
                "injection_policy": "never_auto",
                "valid_from": row["created_at"],
            },
        )
        builder.add_relation(
            session_entity,
            "TRACKS",
            override_entity,
            evidence_items=[ev],
            metadata={**_policy_patch_metadata(row["created_at"]), "risk_level": _normalize_graph_risk_level(row["new_risk_level"])},
        )
        if row["risk_event_id"] in risk_events_by_id:
            builder.add_relation(
                risk_events_by_id[row["risk_event_id"]]["entity"],
                "TRACKS",
                override_entity,
                evidence_items=[ev],
                metadata={**_policy_patch_metadata(row["created_at"]), "risk_level": _normalize_graph_risk_level(row["new_risk_level"])},
            )


def _seq_required_sql(column: str, event_seq_from: int | None, event_seq_to: int | None) -> tuple[str, tuple[Any, ...]]:
    if event_seq_from is None or event_seq_to is None:
        return "", ()
    return f" and {column} >= ? and {column} <= ?", (event_seq_from, event_seq_to)


def _seq_optional_sql(column: str, event_seq_from: int | None, event_seq_to: int | None) -> tuple[str, tuple[Any, ...]]:
    if event_seq_from is None or event_seq_to is None:
        return "", ()
    return f" and ({column} is null or ({column} >= ? and {column} <= ?))", (event_seq_from, event_seq_to)


def add_security_entities(
    builder: GraphBuilder,
    session_entity: dict[str, Any],
    conn: sqlite3.Connection,
    *,
    event_seq_from: int | None = None,
    event_seq_to: int | None = None,
) -> None:
    risk_events_by_id: dict[str, dict[str, Any]] = {}
    risk_seq_sql, risk_seq_params = _seq_required_sql("event_seq", event_seq_from, event_seq_to)
    for row in conn.execute(
        f"""
        select *
        from risk_events
        where session_id = ?
          {risk_seq_sql}
        order by created_at, event_seq
        """,
        (builder.session["session_id"], *risk_seq_params),
    ):
        _add_risk_event(builder, session_entity, conn, row, risk_events_by_id)
    _add_risk_policy_overrides(builder, session_entity, conn, risk_events_by_id)

    reset_seq_sql, reset_seq_params = _seq_required_sql("event_seq", event_seq_from, event_seq_to)
    for row in conn.execute(
        f"""
        select *
        from session_taint_resets
        where session_id = ?
          {reset_seq_sql}
        order by created_at, event_seq
        """,
        (builder.session["session_id"], *reset_seq_params),
    ):
        ev = evidence("taint_reset", builder.session["session_id"], "session_taint_resets", str(row["reason"]), event_seq=int(row["event_seq"]))
        reset_entity = builder.add_entity(
            "TaintReset",
            row["reset_id"],
            key=row["reset_id"],
            evidence_items=[ev],
            properties={"reason": row["reason"], "reviewer": row["reviewer"], "event_seq": row["event_seq"]},
            metadata=_policy_patch_metadata(row["created_at"]),
        )
        builder.add_relation(session_entity, "TRACKS", reset_entity, evidence_items=[ev], metadata=_policy_patch_metadata(row["created_at"]))

    intent_seq_sql, intent_seq_params = _seq_required_sql("user_event_seq", event_seq_from, event_seq_to)
    for row in conn.execute(
        f"""
        select *
        from firewall_intent_approvals
        where session_id = ?
          {intent_seq_sql}
        order by created_at
        """,
        (builder.session["session_id"], *intent_seq_params),
    ):
        ev = evidence("firewall_intent", builder.session["session_id"], "firewall_intent_approvals", row["intent_text"], event_seq=int(row["user_event_seq"]) if row["user_event_seq"] is not None else None)
        intent_entity = builder.add_entity(
            "FirewallIntent",
            row["intent_id"],
            key=row["intent_id"],
            evidence_items=[ev],
            properties={
                "intent_text": row["intent_text"],
                "expires_at": row["expires_at"],
                "allowed_hosts": _safe_split_json(row["allowed_hosts_json"]),
                "allowed_actions": _safe_split_json(row["allowed_actions_json"]),
                "allowed_paths": _safe_split_json(row["allowed_paths_json"]),
                "constraints": row["constraints_json"],
            },
            metadata=_policy_patch_metadata(row["created_at"]),
        )
        builder.add_relation(session_entity, "TRACKS", intent_entity, evidence_items=[ev], metadata=_policy_patch_metadata(row["created_at"]))

    rule_seq_sql, rule_seq_params = _seq_optional_sql("created_from_event_seq", event_seq_from, event_seq_to)
    for row in conn.execute(
        f"""
        select *
        from firewall_rules
        where created_by = 'user_chat_direct' and coalesce(created_from_session_id, session_id) = ?
          {rule_seq_sql}
        order by created_at
        """,
        (builder.session["session_id"], *rule_seq_params),
    ):
        ev = evidence("firewall_rule", builder.session["session_id"], "firewall_rules", row["name"], event_seq=int(row["created_from_event_seq"]) if row["created_from_event_seq"] is not None else None)
        rule_entity = builder.add_entity(
            "FirewallRule",
            row["rule_id"],
            key=row["rule_id"],
            evidence_items=[ev],
            properties={
                "name": row["name"],
                "status": row["status"],
                "rule_kind": row["rule_kind"],
                "scope_type": row["scope_type"],
                "project_id": row["project_id"],
                "workdir_prefix": row["workdir_prefix"],
                "session_id": row["session_id"],
                "allowed_tools": _safe_split_json(row["allowed_tools_json"]),
                "allowed_actions": _safe_split_json(row["allowed_actions_json"]),
                "denied_actions": _safe_split_json(row["denied_actions_json"]),
                "allowed_hosts": _safe_split_json(row["allowed_hosts_json"]),
                "reason": row["reason"],
                "permanent": bool(row["permanent"]),
                "max_risk_level": row["max_risk_level"],
                "expires_at": row["expires_at"],
                "version": row["version"],
                "family_id": row["family_id"],
                "source_line": row["source_line"],
            },
            metadata=_policy_patch_metadata(row["created_at"]),
        )
        builder.add_relation(session_entity, "PRODUCED", rule_entity, evidence_items=[ev], metadata=_policy_patch_metadata(row["created_at"]))
        audit_seq_sql, audit_seq_params = _seq_optional_sql("event_seq", event_seq_from, event_seq_to)
        for audit in conn.execute(
            f"""
            select *
            from firewall_rule_audit
            where (rule_id = ? or family_id = ?) and (session_id is null or session_id = ?)
              {audit_seq_sql}
            order by created_at
            """,
            (row["rule_id"], row["family_id"], builder.session["session_id"], *audit_seq_params),
        ):
            audit_ev = evidence("firewall_rule_audit", builder.session["session_id"], "firewall_rule_audit", str(audit["reason"] or audit["action"]), event_seq=int(audit["event_seq"]) if audit["event_seq"] is not None else None)
            audit_entity = builder.add_entity(
                "FirewallRuleAudit",
                audit["audit_id"],
                key=audit["audit_id"],
                evidence_items=[audit_ev],
                properties={
                    "action": audit["action"],
                    "actor": audit["actor"],
                    "reason": audit["reason"],
                    "before_json": audit["before_json"],
                    "after_json": audit["after_json"],
                    "risk_event_id": audit["risk_event_id"],
                },
                metadata={**_policy_patch_metadata(audit["created_at"]), "risk_level": _normalize_graph_risk_level("medium")},
            )
            builder.add_relation(session_entity, "TRACKS", audit_entity, evidence_items=[audit_ev], metadata=_policy_patch_metadata(audit["created_at"]))
            builder.add_relation(
                audit_entity,
                "AFFECTS",
                rule_entity,
                evidence_items=[audit_ev],
                metadata={**_policy_patch_metadata(audit["created_at"]), "risk_level": "medium"},
            )
            if audit["risk_event_id"] and audit["risk_event_id"] in risk_events_by_id:
                link_metadata = {
                    "memory_kind": "policy",
                    "source_kind": "event",
                    "confidence": 0.96,
                    "risk_level": "high",
                    "sensitivity": "private",
                    "injection_policy": "never_auto",
                    "valid_from": audit["created_at"],
                }
                builder.add_relation(
                    risk_events_by_id[audit["risk_event_id"]]["entity"],
                    "AFFECTS",
                    rule_entity,
                    evidence_items=[audit_ev],
                    metadata=link_metadata,
                )
                builder.add_relation(
                    audit_entity,
                    "AFFECTS",
                    risk_events_by_id[audit["risk_event_id"]]["entity"],
                    evidence_items=[audit_ev],
                    metadata=link_metadata,
                )


def deterministic_graph_patch(conn: sqlite3.Connection, session: sqlite3.Row, *, dream_run: sqlite3.Row | None = None) -> dict[str, Any]:
    builder = GraphBuilder(session)
    event_seq_from = int(dream_run["input_event_seq_from"]) if dream_run is not None else None
    event_seq_to = int(dream_run["input_event_seq_to"]) if dream_run is not None else None
    session_ev = evidence("session", session["session_id"], "sessions", session["session_id"])
    session_entity = builder.add_entity(
        "Session",
        session["thread_name"] or session["session_id"],
        key=session["session_id"],
        evidence_items=[session_ev],
        properties={
            "client_type": session["client_type"],
            "project_id": session["project_id"],
            "started_at": session["started_at"],
            "last_event_at": session["last_event_at"],
            "status": session["status"],
        },
    )
    client_entity = builder.add_entity("ClientHarness", session["client_type"], key=session["client_type"], evidence_items=[session_ev])
    builder.add_relation(session_entity, "USED_TOOL", client_entity, evidence_items=[session_ev])
    project_id = session["project_id"] or "unknown"
    project_entity = builder.add_entity("Project", project_id, key=safe_slug(project_id), evidence_items=[session_ev])
    builder.add_relation(session_entity, "IN_PROJECT", project_entity, evidence_items=[session_ev])
    for field in ["cwd", "last_workdir"]:
        if session[field]:
            dir_ev = evidence("session", session["session_id"], field, session[field])
            dir_path = normalize_path(session[field])
            dir_key = project_relative_path(dir_path, session)
            dir_entity = builder.add_entity("Directory", dir_key, key=dir_key, evidence_items=[dir_ev], properties={"path": str(dir_path), "path_key": dir_key})
            builder.add_relation(project_entity, "HAS_PATH", dir_entity, evidence_items=[dir_ev])
    if session["transcript_path"]:
        transcript_ev = evidence("session", session["session_id"], "transcript_path", session["transcript_path"])
        transcript_path = normalize_path(session["transcript_path"])
        transcript_key = project_relative_path(transcript_path, session)
        transcript_entity = builder.add_entity("Document", transcript_key, key=transcript_key, evidence_items=[transcript_ev], properties={"path": str(transcript_path), "path_key": transcript_key})
        builder.add_relation(session_entity, "HAS_DOCUMENT", transcript_entity, evidence_items=[transcript_ev])
    if dream_run is not None:
        dream_ev = evidence("dream_run", session["session_id"], "dream_runs", dream_run["dream_run_id"], path=dream_run["output_summary_path"])
        dream_entity = builder.add_entity("DreamRun", dream_run["dream_run_id"], key=dream_run["dream_run_id"], evidence_items=[dream_ev], properties={"runner": dream_run["runner"], "status": dream_run["status"]})
        builder.add_relation(dream_entity, "SUMMARIZED", session_entity, evidence_items=[dream_ev])
    if event_seq_from is not None and event_seq_to is not None:
        events = conn.execute(
            "select * from events where session_id = ? and seq >= ? and seq <= ? order by recorded_at, seq",
            (session["session_id"], event_seq_from, event_seq_to),
        )
    else:
        events = session_events(conn, session["session_id"])
    for event in events:
        base = evidence("event", session["session_id"], "event_name", event["event_name"], event_seq=int(event["seq"]))
        for field in ["prompt", "last_assistant_message"]:
            add_text_entities(builder, event, session_entity, event[field] or "", field)
    add_security_entities(builder, session_entity, conn, event_seq_from=event_seq_from, event_seq_to=event_seq_to)
    if event_seq_from is not None and event_seq_to is not None:
        access_rows = conn.execute(
            "select * from file_accesses where session_id = ? and seq >= ? and seq <= ? order by recorded_at, seq, path_key",
            (session["session_id"], event_seq_from, event_seq_to),
        )
    else:
        access_rows = conn.execute("select * from file_accesses where session_id = ? order by recorded_at, seq, path_key", (session["session_id"],))
    for access in access_rows:
        add_file_access_entities(builder, session_entity, access)
    return builder.patch(source_kind="dream_run" if dream_run is not None else "session", source_id=dream_run["dream_run_id"] if dream_run is not None else session["session_id"])
