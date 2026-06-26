from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = SKILL_ROOT / "scripts" / "agent_context_engine.py"
INSTALLATION_PROFILE_PATH = Path("memory") / "local" / "installation-profile.json"
DEFAULT_STORAGE_SCHEMA_VERSION = 1
CANONICAL_ENV_FILENAME = "agent-context-engine.env"
LEGACY_ENV_FILENAME = "agent-memory.env"
ROOT_ENV_VAR = "AGENT_CONTEXT_ENGINE_ROOT"
STORAGE_ROOT_ENV_VAR = "AGENT_CONTEXT_ENGINE_STORAGE_ROOT"
LEGACY_STORAGE_ROOT_ENV_VAR = "AGENT_MEMORY_STORAGE_ROOT"


def default_root_for_skill(skill_root: Path) -> Path:
    if skill_root.name in {"agent-memory", "agent-context-engine"} and skill_root.parent.name == "skills" and skill_root.parent.parent.name == "docs":
        return skill_root.parents[2]
    return skill_root


_root_override = os.environ.get(ROOT_ENV_VAR)
ROOT = Path(_root_override).expanduser().resolve() if _root_override else default_root_for_skill(SKILL_ROOT)


def _read_installation_profile_payload(root: Path) -> dict[str, Any]:
    path = root / INSTALLATION_PROFILE_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _legacy_memory_dir(root: Path) -> Path:
    return (root / "memory").resolve()


def install_root() -> Path:
    return ROOT


def memory_root(root: Path = ROOT) -> Path:
    override = os.environ.get(STORAGE_ROOT_ENV_VAR) or os.environ.get(LEGACY_STORAGE_ROOT_ENV_VAR)
    if override:
        try:
            return Path(override).expanduser().resolve()
        except OSError:
            pass
    payload = _read_installation_profile_payload(root)
    storage = payload.get("storage")
    if not isinstance(storage, dict):
        return _legacy_memory_dir(root)
    memory_root_text = str(storage.get("memory_root") or "").strip()
    if not memory_root_text:
        return _legacy_memory_dir(root)
    try:
        candidate = Path(memory_root_text).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        return candidate.resolve()
    except OSError:
        return _legacy_memory_dir(root)


def db_path(root: Path = ROOT) -> Path:
    return memory_root(root) / "status" / "agent-memory.sqlite3"


def dream_dir(root: Path = ROOT) -> Path:
    return memory_root(root) / "dream"


def lock_dir(root: Path = ROOT) -> Path:
    return memory_root(root) / "status" / "locks"


def env_file_path(root: Path = ROOT) -> Path:
    local_dir = memory_root(root) / "local"
    canonical = local_dir / CANONICAL_ENV_FILENAME
    legacy = local_dir / LEGACY_ENV_FILENAME
    if canonical.exists() or not legacy.exists():
        return canonical
    return legacy


def storage_profile_path(root: Path = ROOT) -> Path:
    return memory_root(root) / "local" / "storage-profile.json"


def storage_paths(root: Path = ROOT) -> dict[str, Path]:
    memory = memory_root(root)
    return {
        "install_root": root,
        "memory_root": memory,
        "db_path": memory / "status" / "agent-memory.sqlite3",
        "dream_dir": memory / "dream",
        "lock_dir": memory / "status" / "locks",
        "env_file": env_file_path(root),
        "storage_profile": memory / "local" / "storage-profile.json",
    }


MEMORY_DIR = memory_root(ROOT)
DB_PATH = db_path(ROOT)
REPOS_INDEX = MEMORY_DIR / "knowledge" / "repos.md"
LEGACY_REPOS_INDEX = ROOT / "docs" / "knowledge" / "repos.md"
CODEX_SESSION_INDEX = Path.home() / ".codex" / "session_index.jsonl"
DREAM_DIR = dream_dir(ROOT)
LOCK_DIR = lock_dir(ROOT)
ENV_FILE_PATH = env_file_path(ROOT)
STORAGE_PROFILE_PATH = storage_profile_path(ROOT)

CODEX_DREAM_MODEL = os.environ.get("AGENT_MEMORY_CODEX_DREAM_MODEL", "gpt-5.4-mini")
CLAUDE_DREAM_MODEL = os.environ.get("AGENT_MEMORY_CLAUDE_DREAM_MODEL", "claude-haiku-4-5-20251001")
CURSOR_DREAM_MODEL = os.environ.get("AGENT_MEMORY_CURSOR_DREAM_MODEL", "gpt-5.4-mini-medium")
GEMINI_DREAM_MODEL = os.environ.get("AGENT_MEMORY_GEMINI_DREAM_MODEL", "gemini-3.1-flash-lite")
ANTIGRAVITY_DREAM_MODEL = os.environ.get("AGENT_MEMORY_ANTIGRAVITY_DREAM_MODEL", "gemini-3.1-flash-lite")
OPENCODE_DREAM_MODEL = os.environ.get("AGENT_MEMORY_OPENCODE_DREAM_MODEL", "ollama/gpt-oss:20b-cloud")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def repos_index_path(root: Path = ROOT) -> Path:
    return memory_root(root) / "knowledge" / "repos.md"


def legacy_repos_index_path(root: Path = ROOT) -> Path:
    return root / "docs" / "knowledge" / "repos.md"


def _is_default_legacy_repos_index(text: str) -> bool:
    normalized = text.replace("\r\n", "\n").strip()
    return "### `example-project`" in normalized and "Replace this placeholder with the project purpose." in normalized


def ensure_repos_index(root: Path = ROOT) -> Path:
    canonical = repos_index_path(root)
    if canonical.exists():
        return canonical
    legacy = legacy_repos_index_path(root)
    if not legacy.exists():
        return canonical
    try:
        text = legacy.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return canonical
    if _is_default_legacy_repos_index(text):
        return canonical
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_text(text, encoding="utf-8")
    return canonical


def read_repos_index_text(root: Path = ROOT) -> str:
    path = ensure_repos_index(root)
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def write_repos_index_text(content: str, root: Path = ROOT) -> Path:
    path = repos_index_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    return slug or "unknown"


def session_short(session_id: str) -> str:
    return safe_slug(session_id)[:12]


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


@dataclass(frozen=True)
class ProjectRef:
    name: str
    path: Path


def load_project_refs() -> list[ProjectRef]:
    text = read_repos_index_text(ROOT)
    if not text:
        return []
    refs: list[ProjectRef] = []
    current_name = ""
    heading_re = re.compile(r"^### `([^`]+)`")
    file_re = re.compile(r"file://([^)]+)")
    for line in text.splitlines():
        heading = heading_re.match(line)
        if heading:
            current_name = heading.group(1)
            continue
        if "Path:" not in line and "Pfad:" not in line:
            continue
        match = file_re.search(line)
        if not match:
            continue
        path_text = match.group(1).replace("%20", " ")
        refs.append(ProjectRef(current_name or Path(path_text).name, Path(path_text)))
    refs.sort(key=lambda ref: len(str(ref.path)), reverse=True)
    return refs


def detect_project(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    cwd_path = Path(cwd).resolve()
    for ref in load_project_refs():
        try:
            cwd_path.relative_to(ref.path.resolve())
            return safe_slug(ref.name)
        except ValueError:
            continue
    try:
        cwd_path.relative_to(ROOT.resolve())
        return safe_slug(ROOT.name)
    except ValueError:
        return safe_slug(cwd_path.name)
