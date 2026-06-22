from __future__ import annotations

import hashlib
import json
import re
import shlex
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..infrastructure.config import ROOT, safe_slug, utc_now


PATH_LIKE_RE = re.compile(r"^(?:/|\.{1,2}/|~|[A-Za-z0-9._@%+-]+/).+")
REDIRECT_RE = re.compile(r"(?:^|\s)(?:>>?|2>|2>>)\s*([^\s]+)")
READ_COMMANDS = {"cat", "sed", "head", "tail", "less", "more", "bat", "jq", "awk", "grep", "rg"}
LIST_COMMANDS = {"ls", "find", "tree"}
CREATE_COMMANDS = {"touch", "mkdir"}
DELETE_COMMANDS = {"rm", "rmdir", "unlink"}
COPY_COMMANDS = {"cp", "install"}
RENAME_COMMANDS = {"mv"}
WRITE_COMMANDS = {"tee"}


@dataclass(frozen=True)
class FileAccess:
    operation: str
    path_raw: str
    path_abs: str
    path_key: str
    source_kind: str
    confidence: float
    evidence_quote: str


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


def parse_tool_input_workdir(tool_input_json: str | None) -> str | None:
    if not tool_input_json:
        return None
    try:
        data = json.loads(tool_input_json)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        value = data.get("workdir") or data.get("working_dir") or data.get("cwd")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def normalize_path(value: str, cwd: str | None = None) -> Path:
    text = value.strip().strip("'\"")
    path = Path(text).expanduser()
    if not path.is_absolute():
        base = Path(cwd).expanduser() if cwd else ROOT
        path = base / path
    return path.resolve()


def path_key(path: Path, project_id: str | None, cwd: str | None = None) -> str:
    return str(path.resolve())


def is_option(token: str) -> bool:
    return token.startswith("-") and token not in {"-", "--"}


def is_probable_path(token: str) -> bool:
    token = token.strip().strip("'\"")
    if not token or token in {"|", "&&", ";"} or token.startswith("$"):
        return False
    if token in {"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/stdin"}:
        return False
    if "*" in token or "?" in token or "[" in token:
        return False
    if token.startswith(("http://", "https://")):
        return False
    if PATH_LIKE_RE.match(token):
        return True
    return bool(Path(token).suffix)


def access_for(raw_path: str, operation: str, command: str, source_kind: str, cwd: str | None, project_id: str | None, confidence: float = 1.0) -> FileAccess:
    normalized = normalize_path(raw_path, cwd)
    return FileAccess(
        operation=operation,
        path_raw=raw_path,
        path_abs=str(normalized),
        path_key=path_key(normalized, project_id, cwd),
        source_kind=source_kind,
        confidence=confidence,
        evidence_quote=command[:2000],
    )


def dedupe(accesses: list[FileAccess]) -> list[FileAccess]:
    seen: set[tuple[str, str, str]] = set()
    result: list[FileAccess] = []
    for access in accesses:
        key = (access.operation, access.path_key, access.source_kind)
        if key in seen:
            continue
        seen.add(key)
        result.append(access)
    return result


def parse_patch_accesses(command: str, cwd: str | None, project_id: str | None) -> list[FileAccess]:
    accesses: list[FileAccess] = []
    pending_update: str | None = None
    for line in command.splitlines():
        if line.startswith("*** Add File: "):
            raw = line.split(": ", 1)[1].strip()
            accesses.append(access_for(raw, "create", command, "apply_patch", cwd, project_id))
            pending_update = None
        elif line.startswith("*** Update File: "):
            pending_update = line.split(": ", 1)[1].strip()
            accesses.append(access_for(pending_update, "modify", command, "apply_patch", cwd, project_id))
        elif line.startswith("*** Delete File: "):
            raw = line.split(": ", 1)[1].strip()
            accesses.append(access_for(raw, "delete", command, "apply_patch", cwd, project_id))
            pending_update = None
        elif line.startswith("*** Move to: ") and pending_update:
            raw = line.split(": ", 1)[1].strip()
            accesses.append(access_for(pending_update, "rename", command, "apply_patch", cwd, project_id))
            accesses.append(access_for(raw, "rename", command, "apply_patch", cwd, project_id))
            pending_update = None
    return dedupe(accesses)


def shell_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command, posix=True)
    except ValueError:
        return command.split()


def command_family(tokens: list[str]) -> str:
    if not tokens:
        return ""
    return Path(tokens[0]).name


def path_tokens(tokens: list[str], *, skip_first: bool = True) -> list[str]:
    items = tokens[1:] if skip_first else tokens
    result: list[str] = []
    skip_next = False
    for token in items:
        if skip_next:
            skip_next = False
            continue
        if is_option(token):
            if token in {"-n", "-e", "-f", "-g", "--glob", "--config", "--exclude", "--include", "-name", "-iname", "-path", "-ipath", "-regex", "-type", "-maxdepth", "-mindepth"}:
                skip_next = True
            continue
        if is_probable_path(token):
            result.append(token)
    return result


def parse_shell_accesses(command: str, cwd: str | None, project_id: str | None) -> list[FileAccess]:
    tokens = shell_tokens(command)
    family = command_family(tokens)
    accesses: list[FileAccess] = []
    if not family:
        return accesses
    operation = ""
    confidence = 0.9
    if family in READ_COMMANDS:
        operation = "read"
        confidence = 0.85 if family in {"rg", "grep", "awk"} else 0.95
    elif family in LIST_COMMANDS:
        operation = "list"
        confidence = 0.9
    elif family in CREATE_COMMANDS:
        operation = "create"
    elif family in DELETE_COMMANDS:
        operation = "delete"
    elif family in COPY_COMMANDS:
        operation = "create"
        confidence = 0.8
    elif family in RENAME_COMMANDS:
        operation = "rename"
    elif family in WRITE_COMMANDS:
        operation = "write"
    if operation:
        for raw in path_tokens(tokens):
            accesses.append(access_for(raw, operation, command, "shell_command", cwd, project_id, confidence))
    for raw in REDIRECT_RE.findall(command):
        if is_probable_path(raw):
            accesses.append(access_for(raw, "write", command, "shell_redirection", cwd, project_id, 0.8))
    return dedupe(accesses)


def extract_file_accesses(tool_name: str | None, tool_input_json: str | None, cwd: str | None, project_id: str | None) -> list[FileAccess]:
    command = parse_tool_input_command(tool_input_json)
    if not command:
        return []
    cwd = parse_tool_input_workdir(tool_input_json) or cwd
    if tool_name == "apply_patch" or command.startswith("*** Begin Patch"):
        return parse_patch_accesses(command, cwd, project_id)
    return parse_shell_accesses(command, cwd, project_id)


def upsert_file_accesses_for_event(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    seq: int,
    recorded_at: str,
    client_type: str,
    project_id: str | None,
    cwd: str | None,
    tool_name: str | None,
    tool_use_id: str | None,
    input_json: str | None,
    status: str,
) -> int:
    accesses = extract_file_accesses(tool_name, input_json, cwd, project_id)
    now = utc_now()
    count = 0
    for access in accesses:
        digest = hashlib.sha1(f"{session_id}:{seq}:{access.operation}:{access.path_key}:{access.source_kind}".encode("utf-8", errors="replace")).hexdigest()[:20]
        access_id = f"fileacc_{safe_slug(session_id)}_{seq}_{digest}"
        conn.execute(
            """
            insert or replace into file_accesses (
              file_access_id, session_id, seq, recorded_at, client_type, project_id,
              tool_name, tool_use_id, operation, path_raw, path_abs, path_key,
              source_kind, confidence, status, evidence_quote, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                access_id,
                session_id,
                seq,
                recorded_at,
                client_type,
                project_id,
                tool_name,
                tool_use_id,
                access.operation,
                access.path_raw,
                access.path_abs,
                access.path_key,
                access.source_kind,
                access.confidence,
                status,
                access.evidence_quote,
                now,
            ),
        )
        count += 1
    return count


def rebuild_file_accesses(conn: sqlite3.Connection, session_id: str | None = None) -> int:
    where = ""
    params: tuple[str, ...] = ()
    if session_id:
        where = "where session_id = ?"
        params = (session_id,)
    rows = list(conn.execute(f"select * from events {where} order by recorded_at, seq", params))
    with conn:
        if session_id:
            conn.execute("delete from file_accesses where session_id = ?", (session_id,))
        else:
            conn.execute("delete from file_accesses")
        count = 0
        for row in rows:
            status = "successful"
            if row["tool_response_text"] is None and row["event_name"].startswith("Pre"):
                status = "planned"
            elif row["tool_response_text"] is not None and "tool_status=failed" in row["tool_response_text"]:
                status = "failed"
            count += upsert_file_accesses_for_event(
                conn,
                session_id=row["session_id"],
                seq=int(row["seq"]),
                recorded_at=row["recorded_at"],
                client_type=row["client_type"],
                project_id=row["project_id"],
                cwd=row["cwd"],
                tool_name=row["tool_name"],
                tool_use_id=row["tool_use_id"],
                input_json=row["tool_input_json"],
                status=status,
            )
    return count
