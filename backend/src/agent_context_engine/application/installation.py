from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..infrastructure.config import ROOT, session_short
from ..infrastructure.db import connect
from ..adapters.runners.cursor import CURSOR_EVENTS, cursor_status
from .integrations import cursor_project_background_runner_status
from .instance_profile import (
    DEFAULT_MONITOR_HOST,
    DEFAULT_MONITOR_PORT,
    INSTALLATION_PROFILE_RELATIVE_PATH,
    WORKFLOW_LABELS,
    WORKFLOW_RUNNER_DEFAULTS,
    WORKSPACE_ROOT_CLIENTS,
    agent_memory_cli_for_root as profile_agent_memory_cli_for_root,
    default_installation_profile as profile_default_installation_profile,
    installation_profile_path as profile_installation_profile_path,
    load_installation_profile as profile_load_installation_profile,
    merge_installation_profile as profile_merge_installation_profile,
    monitor_restart_command as profile_monitor_restart_command,
    normalize_launchagent_profile as profile_normalize_launchagent_profile,
    resolve_monitor_profile as profile_resolve_monitor_profile,
    resolve_runner_wrapper_name as profile_resolve_runner_wrapper_name,
    resolve_wrapper_command_name as profile_resolve_wrapper_command_name,
    resolve_wrapper_naming as profile_resolve_wrapper_naming,
    save_installation_profile as profile_save_installation_profile,
)
HEADLESS_INSTALL_GUIDANCE = {
    "codex": {
        "label": "Codex CLI",
        "install_command": "npm install -g @openai/codex",
        "login_command": "codex login",
        "detail": (
            "Codex GUI hooks in the workspace are separate from the Codex CLI. "
            "Dreaming, monitor ask, the Agent Context Engine wrapper, and other headless flows require the CLI."
        ),
        "auto_installable": True,
        "npm_package": "@openai/codex",
    },
    "claude": {
        "label": "Claude Code CLI",
        "install_command": "npm install -g @anthropic-ai/claude-code",
        "login_command": "claude auth login",
        "detail": (
            "Claude Desktop is separate from the Claude Code CLI. "
            "Dreaming, monitor ask, the Agent Context Engine wrapper, and other headless flows require the CLI."
        ),
        "auto_installable": True,
        "npm_package": "@anthropic-ai/claude-code",
    },
    "cursor": {
        "label": "Cursor background runner",
        "install_command": "Install Codex CLI or Claude Code CLI, then use one of them as the background LLM runner for Cursor projects.",
        "login_command": "codex login or claude auth login",
        "detail": (
            "Cursor IDE project hooks capture sessions inside Cursor, but firewall classification, dreaming, query expansion, and other background LLM workflows require `codex` or `claude` on the machine."
        ),
        "auto_installable": True,
        "npm_package": "",
    },
}

MINIMUM_PYTHON_VERSION = (3, 11, 0)
MINIMUM_NODE_VERSION = (20, 19, 0)
ALTERNATE_NODE_VERSION = (22, 12, 0)
MINIMUM_NPM_VERSION = (9, 5, 0)


def _format_version_tuple(parts: tuple[int, int, int]) -> str:
    return ".".join(str(part) for part in parts)


def _parse_semver(text: str) -> tuple[int, int, int] | None:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text or "")
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _version_gte(current: tuple[int, int, int], minimum: tuple[int, int, int]) -> bool:
    return current >= minimum


def _node_version_supported(version: tuple[int, int, int] | None) -> bool:
    if version is None:
        return False
    return _version_gte(version, MINIMUM_NODE_VERSION) or _version_gte(version, ALTERNATE_NODE_VERSION)


def _command_version(executable: str, flag: str = "--version") -> tuple[str, tuple[int, int, int] | None]:
    try:
        proc = subprocess.run(
            [executable, flag],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", None
    output = (proc.stdout or proc.stderr).strip()
    return output, _parse_semver(output)


def local_time(value: object) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def run_cursor_status(target: str | Path | None = None) -> tuple[list[str], int]:
    root = Path(target).expanduser().resolve() if target else ROOT
    status = cursor_status(root)
    background = cursor_project_background_runner_status(root, expected_memory_root=ROOT)
    lines: list[str] = [
        f"hooks config: {'ok' if status['hooks_exists'] else 'missing'} {status['hooks_path']}",
        f"hook wrapper: {'ok' if status['script_exists'] else 'missing'} {status['script_path']}",
        f"active events: {len(status['active_events'])}/{len(CURSOR_EVENTS)}",
        f"background runner: {background['headless_runner'] or '-'}",
        f"background readiness: {background['background_runner_status']}",
    ]
    if background.get("configured_background_runner"):
        lines.append(f"configured background runner: {background['configured_background_runner']}")
    if background.get("background_runner_login_command"):
        lines.append(f"background login hint: {background['background_runner_login_command']}")
    for event in status["active_events"]:
        lines.append(f"  - {event}")

    conn = connect()
    row = conn.execute("select count(*) as c from sessions where client_type = 'cursor'").fetchone()
    latest = conn.execute(
        """
        select session_id, project_id, status, last_event_at, last_event_seq
        from sessions
        where client_type = 'cursor'
        order by coalesce(last_event_at, started_at) desc
        limit 1
        """
    ).fetchone()
    lines.append(f"recorded cursor sessions: {row['c']}")
    if latest:
        lines.append(
            f"latest: {session_short(latest['session_id'])} {latest['project_id'] or 'unknown'} "
            f"{latest['status']} events={latest['last_event_seq']} last={local_time(latest['last_event_at'])}"
        )
    return lines, 0 if background["headless_runner_ready"] else 1


def backend_project_root(root: Path = ROOT) -> Path:
    direct = root / "backend"
    if direct.exists():
        return direct
    nested = root / "docs" / "skills" / "agent-context-engine" / "backend"
    if nested.exists():
        return nested
    return root / "docs" / "skills" / "agent-memory" / "backend"


def frontend_project_root(root: Path = ROOT) -> Path:
    direct = root / "frontend"
    if direct.exists():
        return direct
    nested = root / "docs" / "skills" / "agent-context-engine" / "frontend"
    if nested.exists():
        return nested
    return root / "docs" / "skills" / "agent-memory" / "frontend"


def venv_python_path(root: Path = ROOT) -> Path:
    default = root / ".venv" / "Scripts" / "python.exe" if os.name == "nt" else root / ".venv" / "bin" / "python"
    candidates = [
        default,
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return default


def preferred_runtime_python(root: Path = ROOT) -> Path:
    venv_python = venv_python_path(root)
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def agent_memory_cli_for_root(root: Path = ROOT) -> str:
    return profile_agent_memory_cli_for_root(root)


def installation_profile_path(root: Path = ROOT) -> Path:
    return profile_installation_profile_path(root)


def _normalize_path_strings(values: list[object] | tuple[object, ...] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        try:
            resolved = str(Path(str(value)).expanduser().resolve())
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        normalized.append(resolved)
    return normalized


def default_installation_profile() -> dict[str, Any]:
    return profile_default_installation_profile()


def _normalize_installation_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    from .platform import current_platform_profile_payload, legacy_platform_profile_payload

    profile = default_installation_profile()
    if isinstance(payload, dict):
        profile["version"] = int(payload.get("version") or 1)
        profile["platform"] = str(payload.get("platform") or profile["platform"])
        raw_platform_profile = payload.get("platform_profile")
        if isinstance(raw_platform_profile, dict) and str(raw_platform_profile.get("profile_id") or "").strip():
            profile["platform_profile"] = raw_platform_profile
        elif payload.get("platform") is not None:
            profile["platform_profile"] = legacy_platform_profile_payload(str(payload.get("platform") or profile["platform"]))
        else:
            profile["platform_profile"] = current_platform_profile_payload()
        workflows = payload.get("workflows")
        if isinstance(workflows, dict):
            for key, default_value in WORKFLOW_RUNNER_DEFAULTS.items():
                value = str(workflows.get(key) or default_value).strip()
                profile["workflows"][key] = value or default_value
        workspace_roots = payload.get("workspace_roots")
        if isinstance(workspace_roots, dict):
            for client in WORKSPACE_ROOT_CLIENTS:
                values = workspace_roots.get(client)
                if isinstance(values, (list, tuple)):
                    profile["workspace_roots"][client] = _normalize_path_strings(list(values))
        wrapper_naming = payload.get("wrapper_naming")
        if isinstance(wrapper_naming, dict):
            prefix = str(wrapper_naming.get("prefix") or "").strip()
            suffix = str(wrapper_naming.get("suffix") or "").strip()
            template = str(wrapper_naming.get("template") or "{prefix}{base}{suffix}").strip() or "{prefix}{base}{suffix}"
            profile["wrapper_naming"] = {
                "prefix": prefix,
                "suffix": suffix,
                "template": template,
            }
        monitor = payload.get("monitor")
        if isinstance(monitor, dict):
            host = str(monitor.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
            language = str(monitor.get("language") or "en").strip().lower() or "en"
            try:
                port = int(monitor.get("port") or DEFAULT_MONITOR_PORT)
            except (TypeError, ValueError):
                port = DEFAULT_MONITOR_PORT
            profile["monitor"] = {
                "host": host,
                "port": max(1, min(port, 65535)),
                "language": language if language in {"en", "de"} else "en",
            }
        launchagent = payload.get("launchagent")
        if isinstance(launchagent, dict):
            profile["launchagent"] = profile_normalize_launchagent_profile(launchagent)
    return profile


def load_installation_profile(root: Path = ROOT) -> dict[str, Any]:
    return profile_load_installation_profile(root)


def save_installation_profile(root: Path = ROOT, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    return profile_save_installation_profile(root, profile)


def merge_installation_profile(
    root: Path = ROOT,
    *,
    instance_id: str | None = None,
    root_path: Path | None = None,
    workflows: dict[str, str] | None = None,
    workspace_roots: dict[str, list[Path]] | None = None,
    wrapper_naming: dict[str, str] | None = None,
    monitor: dict[str, Any] | None = None,
    launchagent: dict[str, str] | None = None,
) -> dict[str, Any]:
    return profile_merge_installation_profile(
        root,
        instance_id=instance_id,
        root_path=root_path,
        workflows=workflows,
        workspace_roots=workspace_roots,
        wrapper_naming=wrapper_naming,
        monitor=monitor,
        launchagent=launchagent,
    )


def resolve_wrapper_naming(root: Path = ROOT) -> dict[str, str]:
    return profile_resolve_wrapper_naming(root)


def resolve_wrapper_command_name(base_name: str, *, root: Path = ROOT) -> str:
    return profile_resolve_wrapper_command_name(base_name, root=root)


def resolve_runner_wrapper_name(client: str, *, root: Path = ROOT) -> str:
    return profile_resolve_runner_wrapper_name(client, root=root)


def resolve_monitor_profile(root: Path = ROOT) -> dict[str, Any]:
    return profile_resolve_monitor_profile(root)


def monitor_restart_command(
    root: Path = ROOT,
    *,
    runner: str | None = None,
    replace_existing: bool = True,
    no_open: bool = True,
) -> str:
    return profile_monitor_restart_command(root, runner=runner, replace_existing=replace_existing, no_open=no_open)


def _python_import_available(python_path: Path, module_name: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            [str(python_path), "-c", f"import {module_name}"],
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    detail = (proc.stderr or proc.stdout).strip()
    return proc.returncode == 0, detail


def python_runtime_status(root: Path = ROOT) -> dict[str, Any]:
    python_path = preferred_runtime_python(root)
    yaml_ok, yaml_detail = _python_import_available(python_path, "yaml")
    python_version = (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    return {
        "python_path": str(python_path),
        "python_version": _format_version_tuple(python_version),
        "python_version_supported": _version_gte(python_version, MINIMUM_PYTHON_VERSION),
        "python_version_required": f">={_format_version_tuple(MINIMUM_PYTHON_VERSION)}",
        "venv_path": str(venv_python_path(root)),
        "venv_exists": venv_python_path(root).exists(),
        "using_venv": python_path == venv_python_path(root),
        "yaml_available": yaml_ok,
        "yaml_detail": yaml_detail,
        "backend_root": str(backend_project_root(root)),
    }


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def frontend_build_status(root: Path = ROOT) -> dict[str, Any]:
    project = frontend_project_root(root)
    dist_dir = project / "dist"
    dist_index = dist_dir / "index.html"
    node_modules = project / "node_modules"
    package_json = project / "package.json"
    src_dir = project / "src"
    source_paths = [path for path in [project / "index.html", project / "tsconfig.json", project / "vite.config.ts", project / "package.json", project / "package-lock.json"] if path.exists()]
    if src_dir.exists():
        source_paths.extend(path for path in src_dir.rglob("*") if path.is_file())
    dist_paths = list(dist_dir.rglob("*")) if dist_dir.exists() else []
    latest_source = max((_mtime(path) for path in source_paths), default=0.0)
    latest_dist = max((_mtime(path) for path in dist_paths if path.is_file()), default=0.0)
    stale = bool(dist_index.exists() and latest_source and latest_dist and latest_source > latest_dist)
    node_path = shutil.which("node") or ""
    npm_path = shutil.which("npm") or ""
    node_version_text, node_version = _command_version(node_path) if node_path else ("", None)
    npm_version_text, npm_version = _command_version(npm_path) if npm_path else ("", None)
    node_supported = _node_version_supported(node_version)
    npm_supported = bool(npm_version and _version_gte(npm_version, MINIMUM_NPM_VERSION))
    return {
        "project_root": str(project),
        "project_exists": package_json.exists(),
        "dist_dir": str(dist_dir),
        "dist_index": str(dist_index),
        "dist_exists": dist_index.exists(),
        "dist_stale": stale,
        "needs_build": (not dist_index.exists()) or stale,
        "node_modules_exists": node_modules.exists(),
        "node_path": node_path,
        "node_version": node_version_text,
        "node_version_supported": node_supported,
        "node_version_required": f">={_format_version_tuple(MINIMUM_NODE_VERSION)} or >={_format_version_tuple(ALTERNATE_NODE_VERSION)}",
        "npm_path": npm_path,
        "npm_version": npm_version_text,
        "npm_version_supported": npm_supported,
        "npm_version_required": f">={_format_version_tuple(MINIMUM_NPM_VERSION)}",
        "build_prerequisites_ready": bool(node_path and npm_path and node_supported and npm_supported),
    }


def ensure_runtime_venv(root: Path = ROOT, *, install_backend_dependencies: bool = True) -> list[str]:
    actions: list[str] = []
    venv_python = venv_python_path(root)
    if not venv_python.exists():
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], text=True, capture_output=True, timeout=120, check=True)
        actions.append(f"created virtualenv at {root / '.venv'}")
    if install_backend_dependencies:
        backend_root = backend_project_root(root)
        if not backend_root.exists():
            raise RuntimeError(f"backend root not found for runtime bootstrap: {backend_root}")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-e", str(backend_root)],
            text=True,
            capture_output=True,
            timeout=600,
            check=True,
        )
        actions.append(f"installed backend dependencies from {backend_root}")
    return actions


def ensure_monitor_frontend_build(
    root: Path = ROOT,
    *,
    install_dependencies: bool = False,
    force: bool = False,
) -> list[str]:
    status = frontend_build_status(root)
    if not status["project_exists"]:
        return []
    if not force and not status["needs_build"]:
        return []
    node_path = str(status["node_path"] or "")
    npm_path = str(status["npm_path"] or "")
    if not node_path:
        raise RuntimeError("node executable missing; install a supported Node.js runtime before building the monitor frontend")
    if not npm_path:
        raise RuntimeError("npm executable missing; cannot build monitor frontend")
    if not bool(status["node_version_supported"]):
        raise RuntimeError(
            "incompatible node version for the monitor frontend: "
            f"{status['node_version'] or 'unknown'} (required {status['node_version_required']})"
        )
    if not bool(status["npm_version_supported"]):
        raise RuntimeError(
            "incompatible npm version for the monitor frontend: "
            f"{status['npm_version'] or 'unknown'} (required {status['npm_version_required']})"
        )
    project = Path(status["project_root"])
    actions: list[str] = []
    if not status["node_modules_exists"]:
        if not install_dependencies:
            raise RuntimeError(
                f"frontend dependencies are missing in {project / 'node_modules'}; "
                f"run `{agent_memory_cli_for_root(root)} repair-installation --apply --install-frontend-deps` first"
            )
        subprocess.run([npm_path, "install"], text=True, capture_output=True, timeout=1200, check=True, cwd=str(project))
        actions.append(f"installed frontend dependencies in {project}")
    subprocess.run([npm_path, "run", "build"], text=True, capture_output=True, timeout=1200, check=True, cwd=str(project))
    actions.append(f"built monitor frontend in {project}")
    return actions


def install_headless_cli(client: str) -> list[str]:
    client_key = str(client or "").strip().lower()
    guidance = HEADLESS_INSTALL_GUIDANCE.get(client_key)
    if not guidance:
        raise RuntimeError(f"unsupported headless CLI install target: {client}")
    if not guidance.get("auto_installable"):
        raise RuntimeError(f"{client_key} must be installed manually: {guidance['install_command']}")
    npm_path = shutil.which("npm")
    if not npm_path:
        raise RuntimeError("npm executable missing; cannot install requested headless CLI")
    subprocess.run(
        [npm_path, "install", "-g", str(guidance["npm_package"])],
        text=True,
        capture_output=True,
        timeout=1800,
        check=True,
    )
    return [f"installed {client_key} CLI globally via {guidance['npm_package']}"]
