from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..infrastructure.config import ROOT, session_short
from ..infrastructure.db import connect
from ..adapters.runners.cursor import CURSOR_EVENTS, cursor_status
from ..adapters.launchagent import DEFAULT_ENV_FILE, DEFAULT_LABEL, launch_agent_path
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
        "login_command": "claude login",
        "detail": (
            "Claude Desktop is separate from the Claude Code CLI. "
            "Dreaming, monitor ask, the Agent Context Engine wrapper, and other headless flows require the CLI."
        ),
        "auto_installable": True,
        "npm_package": "@anthropic-ai/claude-code",
    },
    "cursor": {
        "label": "Cursor CLI",
        "install_command": "Install the Cursor CLI so the `cursor-agent` command exists, then run `cursor-agent login`.",
        "login_command": "cursor-agent login",
        "detail": (
            "Cursor IDE project hooks are separate from the headless Cursor CLI. "
            "Headless Cursor flows require `cursor-agent` on the machine."
        ),
        "auto_installable": False,
        "npm_package": "",
    },
}


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
    lines: list[str] = [
        f"hooks config: {'ok' if status['hooks_exists'] else 'missing'} {status['hooks_path']}",
        f"hook wrapper: {'ok' if status['script_exists'] else 'missing'} {status['script_path']}",
        f"active events: {len(status['active_events'])}/{len(CURSOR_EVENTS)}",
    ]
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
    return lines, 0


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
    return root / ".venv" / "bin" / "python"


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
    profile = default_installation_profile()
    if isinstance(payload, dict):
        profile["version"] = int(payload.get("version") or 1)
        profile["platform"] = str(payload.get("platform") or "mac")
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
            label = str(launchagent.get("label") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
            path = str(launchagent.get("path") or launch_agent_path(label)).strip() or str(launch_agent_path(label))
            env_file = str(launchagent.get("env_file") or DEFAULT_ENV_FILE).strip() or DEFAULT_ENV_FILE
            profile["launchagent"] = {
                "label": label,
                "path": path,
                "env_file": env_file,
            }
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
    return {
        "python_path": str(python_path),
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
    return {
        "project_root": str(project),
        "project_exists": package_json.exists(),
        "dist_dir": str(dist_dir),
        "dist_index": str(dist_index),
        "dist_exists": dist_index.exists(),
        "dist_stale": stale,
        "needs_build": (not dist_index.exists()) or stale,
        "node_modules_exists": node_modules.exists(),
        "npm_path": shutil.which("npm") or "",
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
    npm_path = str(status["npm_path"] or "")
    if not npm_path:
        raise RuntimeError("npm executable missing; cannot build monitor frontend")
    project = Path(status["project_root"])
    actions: list[str] = []
    if not status["node_modules_exists"]:
        if not install_dependencies:
            raise RuntimeError(
                f"frontend dependencies are missing in {project / 'node_modules'}; "
                f"run `{agent_memory_cli_for_root(root)} repair-installation --apply --install-frontend-deps` first"
            )
        subprocess.run([npm_path, "--prefix", str(project), "install"], text=True, capture_output=True, timeout=1200, check=True)
        actions.append(f"installed frontend dependencies in {project}")
    subprocess.run([npm_path, "--prefix", str(project), "run", "build"], text=True, capture_output=True, timeout=1200, check=True)
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
