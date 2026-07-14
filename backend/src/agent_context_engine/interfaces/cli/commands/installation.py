from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import socket
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from ....infrastructure.config import (
    DEFAULT_STORAGE_SCHEMA_VERSION,
    ROOT,
    ROOT_ENV_VAR,
    SKILL_ROOT,
    STORAGE_ROOT_ENV_VAR,
    active_root_path,
    central_hub_path,
    ensure_repos_index as ensure_runtime_repos_index,
    legacy_repos_index_path,
    safe_slug,
    storage_root,
    write_repos_index_text,
)
from ....application.installation import (
    ensure_monitor_frontend_build,
    ensure_runtime_venv,
    frontend_build_status,
    HEADLESS_INSTALL_GUIDANCE,
    install_headless_cli,
    python_runtime_status,
    run_cursor_status,
)
from ....application.instance_profile import (
    DEFAULT_MONITOR_HOST,
    DEFAULT_MONITOR_PORT,
    WORKFLOW_LABELS,
    WORKFLOW_RUNNER_DEFAULTS,
    _utc_timestamp,
    active_monitor_runtime_entries,
    default_instance_install_root,
    default_launchagent_profile,
    default_user_storage_root,
    ensure_storage_profile,
    instance_metadata_path_for_root,
    installation_profile_path,
    load_installation_profile,
    load_link_registry,
    normalize_launchagent_profile,
    preferred_agent_memory_cli_for_root,
    load_user_config,
    load_storage_profile,
    merge_user_config,
    merge_installation_profile,
    monitor_restart_command,
    record_link_registry_entry,
    resolve_storage_profile,
    storage_profile_path,
    sync_instance_metadata,
    link_registry_path,
    user_cli_link_path,
    user_config_path,
)
from ....adapters.launchagent import DEFAULT_ENV_FILE, DEFAULT_LABEL, launchagent_runtime_status
from ....application.integrations import (
    _project_local_hook_command,
    antigravity_status,
    append_integration_history,
    cursor_background_runner_status,
    ensure_antigravity_project,
    ensure_gemini_project,
    ensure_opencode_project,
    gemini_status,
    integration_hook_command,
    integration_summary,
    manage_integration_hooks,
    integration_projects_status,
    opencode_status,
    shell_hook_adapter_status,
    workspace_binding_status,
    write_workspace_binding,
)
from ....application.hooks_state import hooks_control_status, set_hooks_enabled
from ....application.hook_rendering import HUB_RENDER_SPEC_VERSION


def copy_text(src: Path, dest: Path, replacements: dict[str, str] | None = None) -> None:
    text = src.read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        text = text.replace(key, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


def _quote_platform_path(value: str | Path) -> str:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_path_quoting_adapter

    return select_path_quoting_adapter(current_platform_profile()).quote(str(value))


def _mark_platform_executable(path: Path) -> None:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_executable_permission_adapter

    select_executable_permission_adapter(current_platform_profile()).ensure_executable(path)


def ensure_user_cli_link(target: Path, *, force: bool) -> Path:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_command_publisher

    link_path = user_cli_link_path()
    cli_target = (target / agent_memory_cli_for_root(target).replace("./", "")).resolve()
    link_path.parent.mkdir(parents=True, exist_ok=True)
    if link_path.exists() or link_path.is_symlink():
        try:
            existing = link_path.resolve(strict=False)
        except OSError:
            existing = None
        if existing == cli_target:
            record_link_registry_entry(
                logical_name=link_path.name,
                link_kind="user_cli_shortcut",
                path=link_path,
                target=cli_target,
                status="linked",
                installation_root=target,
                command_name=link_path.name,
            )
            return link_path
        if not force:
            raise FileExistsError(f"user CLI shortcut already exists and points elsewhere: {link_path} -> {existing or '<unresolved>'}")
        if link_path.is_dir() and not link_path.is_symlink():
            raise FileExistsError(f"user CLI shortcut path is an existing directory: {link_path}")
    select_command_publisher(current_platform_profile()).create_symlink(link_path, cli_target, force=force)
    record_link_registry_entry(
        logical_name=link_path.name,
        link_kind="user_cli_shortcut",
        path=link_path,
        target=cli_target,
        status="linked",
        installation_root=target,
        command_name=link_path.name,
    )
    return link_path


LANGUAGE_LABELS = {
    "en": "English",
    "de": "German",
}

LANGUAGE_CODES_BY_LABEL = {
    "english": "en",
    "german": "de",
    "deutsch": "de",
}

DEFAULT_HOME_MEMORY_ROOT_NAME = ".agent-context-engine"


def _default_home_memory_root() -> Path:
    return default_user_storage_root()


def _default_home_install_root() -> Path:
    return default_instance_install_root()


def _isolated_default_memory_root(target_root: Path) -> Path:
    return (target_root / "memory").resolve()


def _isolated_instance_name_for_target(target_root: Path) -> str:
    return safe_slug(target_root.name) or "isolated"


def _recommended_memory_root_source_text(source: str) -> str:
    mapping = {
        "explicit": "explicit",
        "user_config_default_memory_root": "user config default",
        "default_home_root": "default home root",
        "default_home_root_existing": "default home root already exists",
        "default_home_root_profile": "default home root with existing storage profile",
        "current_installation": "current installation",
        "paired_checkout_installation": "paired checkout installation",
        "sibling_installation": "sibling installation",
    }
    return mapping.get(source, source or "detected")


def _default_global_wrapper_links() -> list[str]:
    return list(GLOBAL_WRAPPERS)


def _link_flag_enabled(args: argparse.Namespace, flag_name: str, *, default: bool = True) -> bool:
    value = getattr(args, flag_name, None)
    if value is None:
        return default
    return bool(value)


def _checkout_change_mode_text(*, checkout_root: Path, target_root: Path, language: str) -> str:
    if checkout_root.resolve() == target_root.resolve():
        return _ui_text(
            language,
            en="installing into this checkout",
            de="Installation direkt in dieses Checkout",
        )
    return _ui_text(
        language,
        en="this checkout stays unchanged; install writes into the central user root",
        de="dieses Checkout bleibt unveraendert; die Installation schreibt in den zentralen Nutzer-Root",
    )


def _monitor_port_reason_text(*, recommended_port: int, default_port: int, language: str) -> str:
    if recommended_port == default_port:
        return _ui_text(language, en="default port", de="Standard-Port")
    return _ui_text(
        language,
        en=f"adjusted because {default_port} is already reserved or busy",
        de=f"angepasst, weil {default_port} bereits reserviert oder belegt ist",
    )


def _launchagent_recommendation_source_text(source: str, *, language: str = "en") -> str:
    if source == "saved_user_default":
        return _ui_text(language, en="saved user default", de="gespeicherter Nutzer-Default")
    if source == "fresh_install_default_ignored_saved_opt_out":
        return _ui_text(
            language,
            en="fresh-install default; saved user opt-out not applied automatically",
            de="Neuinstallations-Default; gespeicherter Nutzer-Opt-out wird nicht automatisch uebernommen",
        )
    return _ui_text(language, en="fresh-install default", de="Neuinstallations-Default")


GLOBAL_WRAPPERS = (
    "codex-ace",
    "claude-ace",
    "cursor-ace",
    "agy-ace",
    "gemini-ace",
    "opencode-ace",
)

LEGACY_GLOBAL_WRAPPERS = (
    "antigravity-ace",
)

GLOBAL_CLI_COMMAND_NAME = "agent-context-engine"

PUBLIC_WRAPPER_NAME_TO_SCRIPT = {
    "codex-memory": "codex-ace",
    "claude-memory": "claude-ace",
    "cursor-memory": "cursor-ace",
    "agy-memory": "agy-ace",
    "antigravity-memory": "antigravity-ace",
    "gemini-memory": "gemini-ace",
    "opencode-memory": "opencode-ace",
    "codex-ace": "codex-ace",
    "claude-ace": "claude-ace",
    "cursor-ace": "cursor-ace",
    "agy-ace": "agy-ace",
    "antigravity-ace": "antigravity-ace",
    "gemini-ace": "gemini-ace",
    "opencode-ace": "opencode-ace",
}


def _normalize_wrapper_script_name(name: str) -> str:
    normalized = str(name or "").strip()
    return PUBLIC_WRAPPER_NAME_TO_SCRIPT.get(normalized, normalized)

PUBLIC_CHECKOUT_NAME_HINTS = {
    "agent-context-engine",
    "agent-memory-public",
}

SOURCE_CHECKOUT_NAME_HINTS = {
    "agent-memory",
}

WORKFLOW_RUNNER_CHOICES = ("codex", "claude", "cursor", "antigravity", "gemini", "opencode")
WORKFLOW_RUNNER_SPECIALS = {
    "monitor_runner": (),
    "dream_runner": ("deterministic",),
    "query_expansion_runner": ("deterministic", "off"),
}

MANAGED_INSTALL_PATHS = (
    "docs/skills/agent-context-engine",
    ".codex/hooks.json",
    ".codex/hooks/hook_adapter.sh",
    ".codex/hooks/hook_adapter.cmd",
    ".codex/hooks/hook_adapter.ps1",
    ".claude/settings.json",
    ".claude/hooks/hook_adapter.sh",
    ".claude/hooks/hook_adapter.cmd",
    ".claude/hooks/hook_adapter.ps1",
    ".agents/hooks.json",
    ".agents/hooks/hook_adapter.sh",
    ".agents/hooks/hook_adapter.cmd",
    ".agents/hooks/hook_adapter.ps1",
    ".gemini/settings.json",
    ".gemini/hooks/hook_adapter.sh",
    ".gemini/hooks/hook_adapter.cmd",
    ".gemini/hooks/hook_adapter.ps1",
    "session-start-hook-entry.md",
)


def normalize_language(value: str | None) -> str:
    normalized = (value or "en").strip().lower()
    if normalized in {"en", "eng", "english"}:
        return "en"
    if normalized in {"de", "deu", "ger", "german", "deutsch"}:
        return "de"
    if normalized in {"auto", "default"}:
        return "en"
    return "en"


def ask_preferred_language(default: str = "en", *, language: str | None = None) -> str:
    if not sys.stdin.isatty():
        return default
    prompt_language = normalize_language(language or default)
    print("")
    print(_ui_text(prompt_language, en="Preferred interaction language", de="Bevorzugte Interaktionssprache"))
    print(
        _ui_text(
            prompt_language,
            en="Choose the language future agents should use when talking to you.",
            de="Waehle die Sprache, die kuenftige Agenten fuer Antworten verwenden sollen.",
        )
    )
    answer = input(_ui_text(prompt_language, en=f"Language [en/de] (default: {default}): ", de=f"Sprache [en/de] (Standard: {default}): ")).strip()
    return normalize_language(answer or default)


def ask_yes_no(prompt: str, *, default: bool) -> bool:
    if not sys.stdin.isatty():
        return default
    suffix = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {suffix}: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "j", "ja", "1", "true"}


def _ui_text(language: str, *, en: str, de: str) -> str:
    return de if language == "de" else en


def _scheduler_capability(profile) -> object | None:
    if profile is None:
        return None
    capability = getattr(profile, "capability", None)
    if callable(capability):
        return capability("scheduler_backend")
    return None


def _scheduler_display_name(profile) -> str:
    capability = _scheduler_capability(profile)
    implementation = str(getattr(capability, "implementation", "") or "").strip()
    if implementation == "windows_task_scheduler":
        return "Windows Task Scheduler"
    if implementation == "launchagent":
        return "LaunchAgent"
    if implementation == "systemd_user":
        return "systemd user service"
    if implementation == "wsl_scheduler":
        return "WSL scheduler bridge"
    if implementation == "cron":
        return "cron scheduler"
    return "scheduler"


def _scheduler_install_command(*, root: Path, profile, launchagent_label: str, launchagent_path: str, launchagent_env_file: str) -> str:
    capability = _scheduler_capability(profile)
    implementation = str(getattr(capability, "implementation", "") or "").strip()
    base = f"{agent_memory_cli_for_root(root)} install-launchagent"
    if implementation == "launchagent":
        return (
            base
            + f" --label {launchagent_label} "
            + f"--plist-path {_quote_platform_path(launchagent_path)} --env-file {_quote_platform_path(launchagent_env_file)} --load"
        )
    return base + " --load"


def _scheduler_install_subcommand_args(*, profile, launchagent_label: str, launchagent_path: str, launchagent_env_file: str) -> list[str]:
    capability = _scheduler_capability(profile)
    implementation = str(getattr(capability, "implementation", "") or "").strip()
    command = ["install-launchagent"]
    if implementation == "launchagent":
        command.extend(
            [
                "--label",
                launchagent_label,
                "--plist-path",
                launchagent_path,
                "--env-file",
                launchagent_env_file,
            ]
        )
    command.append("--load")
    return command


def _direct_backend_dependency_command(runtime: dict[str, object]) -> str:
    venv_path = str(runtime.get("venv_path") or "").strip()
    backend_root = str(runtime.get("backend_root") or "").strip()
    if not venv_path or not backend_root:
        return "repair-installation --apply"
    return f"{_quote_platform_path(venv_path)} -m pip install -e {_quote_platform_path(backend_root)}"


def _prerequisite_suggestions(*, runtime: dict[str, object], frontend: dict[str, object], language: str) -> list[str]:
    suggestions: list[str] = []
    if not runtime.get("python_version_supported"):
        suggestions.append(
            _ui_text(
                language,
                en=f"Install or switch to Python {runtime['python_version_required']} before running install.",
                de=f"Vor der Installation Python {runtime['python_version_required']} installieren oder aktivieren.",
            )
        )
    if not frontend.get("node_path"):
        suggestions.append(
            _ui_text(
                language,
                en=f"Install Node.js {frontend['node_version_required']} so the monitor frontend can be built.",
                de=f"Node.js {frontend['node_version_required']} installieren, damit das Monitor-Frontend gebaut werden kann.",
            )
        )
    elif not frontend.get("node_version_supported"):
        suggestions.append(
            _ui_text(
                language,
                en=f"Upgrade Node.js from {frontend['node_version'] or 'the current version'} to {frontend['node_version_required']}.",
                de=f"Node.js von {frontend['node_version'] or 'der aktuellen Version'} auf {frontend['node_version_required']} aktualisieren.",
            )
        )
    if not frontend.get("npm_path"):
        suggestions.append(
            _ui_text(
                language,
                en=f"Install npm {frontend['npm_version_required']} or a Node.js distribution that provides it.",
                de=f"npm {frontend['npm_version_required']} oder eine passende Node.js-Distribution mit npm installieren.",
            )
        )
    elif not frontend.get("npm_version_supported"):
        suggestions.append(
            _ui_text(
                language,
                en=f"Upgrade npm from {frontend['npm_version'] or 'the current version'} to {frontend['npm_version_required']}.",
                de=f"npm von {frontend['npm_version'] or 'der aktuellen Version'} auf {frontend['npm_version_required']} aktualisieren.",
            )
        )
    return suggestions


def _environment_language(default: str = "en") -> str:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = str(os.environ.get(key) or "").strip().lower()
        if not value:
            continue
        if value.startswith("de"):
            return "de"
        if value.startswith("en"):
            return "en"
    return default


def _resolved_discovery_language(
    *,
    checkout_root: Path,
    user_config: dict[str, object],
    language_hint: str | None = None,
) -> tuple[str, str]:
    explicit = str(language_hint or "").strip()
    if explicit:
        return normalize_language(explicit), "explicit"
    env_language = _environment_language("")
    if env_language:
        return normalize_language(env_language), "environment"
    target_language = installation_language_for_target(target=checkout_root, default="")
    if target_language:
        return normalize_language(target_language), "checkout_installation"
    configured = str(user_config.get("default_language") or "").strip().lower()
    if configured:
        return normalize_language(configured), "user_config_default_language"
    return "en", "fallback_default"


def _command_script_for_root(root: Path) -> str:
    if (root / "scripts" / "agent_context_engine.py").exists():
        return "python3 scripts/agent_context_engine.py"
    return "python3 docs/skills/agent-context-engine/scripts/agent_context_engine.py"


def _looks_like_agent_memory_checkout(path: Path) -> bool:
    return bool(
        (path / "scripts" / "agent_context_engine.py").exists()
        or (path / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent_context_engine.py").exists()
        or (path / "docs" / "skills" / "agent-memory" / "scripts" / "agent_context_engine.py").exists()
        or (path / "backend" / "src" / "agent_context_engine").exists()
        or (path / "backend" / "src" / "agent_memory").exists()
    )


def _is_public_checkout_name(name: str) -> bool:
    normalized = name.strip().lower()
    return normalized in PUBLIC_CHECKOUT_NAME_HINTS or normalized.endswith("-public")


def _public_wrapper_suffix_for_checkout(path: Path) -> str:
    normalized = safe_slug(path.name).strip("-")
    if normalized in {"agent-context-engine", "agent-context-engine-public", "agent-memory-public"}:
        return "-ace"
    parts = [part for part in normalized.split("-") if part]
    acronym = "".join(part[0] for part in parts[:4])
    if 2 <= len(acronym) <= 6:
        return f"-{acronym}"
    short_name = normalized[:12] if len(normalized) > 12 else normalized
    return f"-{short_name}" if short_name else ""


def _checkout_root_from_path(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if _looks_like_agent_memory_checkout(candidate):
            return candidate
    return start.resolve()


def _paired_checkout(path: Path) -> Path | None:
    name = path.name
    lowered = name.lower()
    if lowered == "agent-memory":
        candidate = path.parent / "agent-context-engine"
        if candidate.exists():
            return candidate
    if name.endswith("-public"):
        candidate = path.parent / name[: -len("-public")]
        return candidate if candidate.exists() else None
    candidate = path.parent / f"{name}-public"
    return candidate if candidate.exists() else None


def _checkout_role(path: Path) -> str:
    if not _looks_like_agent_memory_checkout(path):
        return "unknown_checkout"
    name = path.name.lower()
    if _is_public_checkout_name(name):
        return "public_checkout"
    if name in SOURCE_CHECKOUT_NAME_HINTS and (path / ".git").exists():
        return "source_checkout"
    if installation_profile_path(path).exists():
        return "existing_installation"
    return "fresh_installation_candidate"


def _discovery_installation_roots(current_root: Path) -> list[Path]:
    candidates: list[Path] = []
    seen: set[Path] = set()
    for candidate in [current_root, *sorted([path for path in current_root.parent.iterdir() if path.is_dir()], key=lambda item: item.name.lower())]:
        resolved = candidate.resolve()
        if resolved in seen or not _looks_like_agent_memory_checkout(resolved):
            continue
        seen.add(resolved)
        candidates.append(resolved)
    return candidates


def _discovered_memory_root_candidates(current_root: Path) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    seen_memory_roots: set[str] = set()
    paired = _paired_checkout(current_root)
    for install_root in _discovery_installation_roots(current_root):
        profile_exists = installation_profile_path(install_root).exists()
        if not profile_exists:
            continue
        storage = resolve_storage_profile(install_root)
        memory_root = str(storage.get("memory_root") or "").strip()
        if not memory_root or memory_root in seen_memory_roots:
            continue
        seen_memory_roots.add(memory_root)
        role = _checkout_role(install_root)
        reason = "sibling_installation"
        confidence = "medium"
        if install_root == current_root:
            reason = "current_installation"
            confidence = "high"
        elif paired is not None and install_root == paired.resolve():
            reason = "paired_checkout_installation"
            confidence = "high"
        memory_root_exists = Path(memory_root).exists()
        if not memory_root_exists and reason not in {"current_installation", "paired_checkout_installation"}:
            continue
        candidates.append(
            {
                "installation_root": str(install_root),
                "memory_root": memory_root,
                "schema_version": int(storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION),
                "reason": reason,
                "confidence": confidence,
                "checkout_role": role,
                "exists": memory_root_exists,
                "language": installation_language_for_target(target=install_root, memory_root=Path(memory_root)),
            }
        )
    candidates.sort(
        key=lambda item: (
            0 if item["reason"] == "current_installation" else 1 if item["reason"] == "paired_checkout_installation" else 2,
            0 if item["exists"] else 1,
            str(item["installation_root"]),
        )
    )
    return candidates


def _known_monitor_ports(
    *,
    checkout_root: Path,
    target_root: Path,
    target_memory_root: Path | None,
    user_config: dict[str, object],
) -> set[tuple[str, int]]:
    reserved: set[tuple[str, int]] = set()
    normalized_target_root = str(target_root.resolve())
    normalized_target_memory_root = str(target_memory_root.resolve()) if target_memory_root is not None else ""
    candidate_roots: list[Path] = []
    seen: set[Path] = set()
    for candidate in _discovery_installation_roots(checkout_root):
        if installation_profile_path(candidate).exists():
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                candidate_roots.append(resolved)
    last_used_root = str(user_config.get("last_used_installation_root") or "").strip()
    if last_used_root:
        try:
            resolved = Path(last_used_root).expanduser().resolve()
        except OSError:
            resolved = None
        if resolved is not None and installation_profile_path(resolved).exists() and resolved not in seen:
            seen.add(resolved)
            candidate_roots.append(resolved)
    for root in candidate_roots:
        if root == target_root and not installation_profile_path(root).exists():
            continue
        root_storage = resolve_storage_profile(root)
        root_memory_root = str(root_storage.get("memory_root") or "").strip()
        if normalized_target_memory_root and root != target_root and root_memory_root == normalized_target_memory_root:
            continue
        monitor = dict(load_installation_profile(root).get("monitor") or {})
        host = str(monitor.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
        try:
            port = max(1, min(int(monitor.get("port") or DEFAULT_MONITOR_PORT), 65535))
        except (TypeError, ValueError):
            continue
        reserved.add((host, port))
    for entry in active_monitor_runtime_entries():
        host = str(entry.get("active_host") or entry.get("configured_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
        entry_memory_root = str(entry.get("memory_root") or "").strip()
        entry_installation_root = str(entry.get("installation_root") or "").strip()
        if entry_installation_root == normalized_target_root:
            continue
        if normalized_target_memory_root and entry_memory_root == normalized_target_memory_root:
            continue
        try:
            port = max(1, min(int(entry.get("active_port") or entry.get("configured_port") or 0), 65535))
        except (TypeError, ValueError):
            continue
        if port:
            reserved.add((host, port))
    return reserved


def _next_monitor_port(preferred: int, *, host: str = DEFAULT_MONITOR_HOST, reserved_ports: set[tuple[str, int]] | None = None) -> int:
    reserved = reserved_ports or set()
    if (host, preferred) not in reserved and _port_conflict_status(host, preferred)["available"]:
        return preferred
    for port in range(preferred + 1, min(preferred + 50, 65536)):
        if (host, port) in reserved:
            continue
        if _port_conflict_status(host, port)["available"]:
            return port
    for port in range(max(1, preferred - 50), preferred):
        if (host, port) in reserved:
            continue
        if _port_conflict_status(host, port)["available"]:
            return port
    return preferred


def _resolve_final_monitor_port(
    *,
    checkout_root: Path,
    target_root: Path,
    target_memory_root: Path,
    host: str,
    requested_port: int,
    user_config: dict[str, object],
) -> tuple[int, str]:
    active_entries = [entry for entry in active_monitor_runtime_entries() if isinstance(entry, dict)]
    reserved_other: set[tuple[str, int]] = set()
    same_target_active = False
    normalized_target = str(target_root.resolve())
    normalized_target_memory_root = str(target_memory_root.resolve())
    for entry in active_entries:
        entry_root = str(entry.get("installation_root") or "").strip()
        entry_memory_root = str(entry.get("memory_root") or "").strip()
        entry_host = str(entry.get("active_host") or entry.get("configured_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
        try:
            entry_port = max(1, min(int(entry.get("active_port") or entry.get("configured_port") or 0), 65535))
        except (TypeError, ValueError):
            continue
        if not entry_port:
            continue
        if entry_root == normalized_target and entry_host == host and entry_port == requested_port:
            same_target_active = True
            continue
        if entry_root != normalized_target and entry_memory_root == normalized_target_memory_root:
            continue
        if entry_root != normalized_target:
            reserved_other.add((entry_host, entry_port))

    port_status = _port_conflict_status(host, requested_port)
    if (host, requested_port) not in reserved_other and (port_status["available"] or same_target_active):
        return requested_port, ""

    reserved_known = _known_monitor_ports(
        checkout_root=checkout_root,
        target_root=target_root,
        target_memory_root=target_memory_root,
        user_config=user_config,
    )
    reserved_known.update(reserved_other)
    resolved_port = _next_monitor_port(requested_port, host=host, reserved_ports=reserved_known)
    if resolved_port == requested_port:
        return requested_port, ""
    if (host, requested_port) in reserved_other:
        reason = f"reserved by another active monitor runtime entry on {host}:{requested_port}"
    elif not port_status["available"]:
        reason = str(port_status["error"] or f"{host}:{requested_port} is not currently bindable")
    else:
        reason = f"reserved during final install reconciliation on {host}:{requested_port}"
    return resolved_port, reason


def _acceptable_wrapper_targets(checkout_root: Path, wrapper_name: str) -> set[Path]:
    candidates = {
        checkout_root / "scripts" / wrapper_name,
        checkout_root / "docs" / "skills" / "agent-context-engine" / "scripts" / wrapper_name,
        checkout_root / "docs" / "skills" / "agent-memory" / "scripts" / wrapper_name,
    }
    resolved: set[Path] = set()
    for candidate in candidates:
        try:
            if candidate.exists():
                resolved.add(candidate.resolve())
        except OSError:
            continue
    return resolved


def _wrapper_conflicts(*, checkout_root: Path, prefix: str, suffix: str) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for wrapper_name in GLOBAL_WRAPPERS:
        command_name = link_command_name(wrapper_name, prefix, suffix)
        resolved = shutil.which(command_name)
        if not resolved:
            continue
        resolved_path = Path(resolved).expanduser().resolve()
        acceptable_targets = _acceptable_wrapper_targets(checkout_root, wrapper_name)
        points_to_current = resolved_path in acceptable_targets
        conflicts.append(
            {
                "wrapper": wrapper_name,
                "command_name": command_name,
                "resolved_path": str(resolved_path),
                "points_to_current_checkout": points_to_current,
                "conflict": not points_to_current,
            }
        )
    return conflicts


def _user_cli_conflict(target_root: Path) -> dict[str, object]:
    link_path = user_cli_link_path()
    cli_target = agent_memory_cli_path_for_root(target_root).resolve()
    if not (link_path.exists() or link_path.is_symlink()):
        return {
            "path": str(link_path),
            "target": str(cli_target),
            "exists": False,
            "points_to_target": False,
            "conflict": False,
        }
    try:
        existing = link_path.resolve(strict=False)
    except OSError:
        existing = None
    points_to_target = existing == cli_target
    return {
        "path": str(link_path),
        "target": str(cli_target),
        "exists": True,
        "resolved_path": str(existing) if existing is not None else "",
        "points_to_target": points_to_target,
        "conflict": not points_to_target,
    }


def _launchagent_identity_status(*, label: str, env_file: str, plist_path: str) -> dict[str, object]:
    status = launchagent_runtime_status(label=label, env_file=env_file, plist_path=plist_path, root=ROOT)
    return {
        "label": label,
        "plist_path": plist_path,
        "env_file": env_file,
        "installed": bool(status.get("installed")),
        "loaded": bool(status.get("loaded")),
        "drift_detected": bool((status.get("drift") or {}).get("detected")),
        "drift_reasons": list((status.get("drift") or {}).get("reasons") or []),
    }


def _launchagent_identity_for_target(
    *,
    checkout_role: str,
    target_root: Path,
    recommended_memory_root: str,
) -> tuple[str, str, str]:
    fallback_memory_root = Path(recommended_memory_root).expanduser().resolve() if recommended_memory_root else (target_root / "memory").resolve()
    default_profile = _default_launchagent_profile_for_target(
        checkout_role=checkout_role,
        target_root=target_root,
        memory_root=fallback_memory_root,
    )
    if installation_profile_path(target_root).exists():
        launchagent = normalize_launchagent_profile(dict(load_installation_profile(target_root).get("launchagent") or {}))
        label = str(launchagent.get("label") or "").strip()
        path = str(launchagent.get("path") or "").strip()
        env_file = str(launchagent.get("env_file") or "").strip()
        if label and path and env_file:
            return label, env_file, path
    return default_profile["label"], default_profile["env_file"], default_profile["path"]


def _discovery_summary(*, start: Path, target_hint: Path | None = None, memory_root_hint: str | None = None, language_hint: str | None = None) -> dict[str, object]:
    checkout_root = _checkout_root_from_path(start)
    role = _checkout_role(checkout_root)
    if target_hint is not None:
        target_root = target_hint.expanduser().resolve()
    else:
        target_root = checkout_root
    paired = _paired_checkout(checkout_root)
    memory_candidates = _discovered_memory_root_candidates(checkout_root)
    user_config = load_user_config()
    has_user_config = user_config_path().exists()
    recommended_memory_root = str(memory_root_hint or "").strip()
    recommended_memory_root_source = "explicit"
    discarded_foreign_install_defaults = False
    if not recommended_memory_root:
        configured_default_root = str(user_config.get("default_memory_root") or "").strip()
        default_home_root = _default_home_memory_root()
        if configured_default_root and has_user_config:
            configured_candidate = Path(configured_default_root).expanduser().resolve()
            configured_installation_root = configured_candidate.parent if configured_candidate.name == "memory" else None
            configured_is_checkout_local = bool(
                configured_installation_root is not None
                and (configured_installation_root / "scripts" / "agent-context-engine").exists()
            )
            if configured_is_checkout_local and configured_installation_root.resolve() != target_root.resolve():
                discarded_foreign_install_defaults = True
                recommended_memory_root = str(default_home_root)
                if (default_home_root / "local" / "storage-profile.json").exists():
                    recommended_memory_root_source = "default_home_root_profile"
                elif default_home_root.exists():
                    recommended_memory_root_source = "default_home_root_existing"
                else:
                    recommended_memory_root_source = "default_home_root"
            else:
                recommended_memory_root = str(configured_candidate)
                recommended_memory_root_source = "user_config_default_memory_root"
        else:
            recommended_memory_root = str(default_home_root)
            if (default_home_root / "local" / "storage-profile.json").exists():
                recommended_memory_root_source = "default_home_root_profile"
            elif default_home_root.exists():
                recommended_memory_root_source = "default_home_root_existing"
            else:
                recommended_memory_root_source = "default_home_root"
    language, language_source = _resolved_discovery_language(
        checkout_root=checkout_root,
        user_config=user_config,
        language_hint=language_hint,
    )
    monitor_host = str(user_config.get("default_monitor_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    try:
        monitor_port = max(1, min(int(user_config.get("default_monitor_port") or DEFAULT_MONITOR_PORT), 65535))
    except (TypeError, ValueError):
        monitor_port = DEFAULT_MONITOR_PORT
    discovery_memory_root = Path(recommended_memory_root).expanduser().resolve() if recommended_memory_root else (target_root / "memory").resolve()
    reserved_monitor_ports = _known_monitor_ports(
        checkout_root=checkout_root,
        target_root=target_root,
        target_memory_root=discovery_memory_root,
        user_config=user_config,
    )
    active_monitor_entries = active_monitor_runtime_entries()
    recommended_port = _next_monitor_port(monitor_port, host=monitor_host, reserved_ports=reserved_monitor_ports)
    recommended_wrapper_prefix = "" if discarded_foreign_install_defaults else str(user_config.get("default_wrapper_prefix") or "").strip()
    recommended_wrapper_suffix = str(user_config.get("default_wrapper_suffix") or "").strip()
    launchagent_user_default = bool(user_config.get("default_launchagent_enabled", True))
    if role == "public_checkout":
        if not recommended_wrapper_suffix:
            recommended_wrapper_suffix = _public_wrapper_suffix_for_checkout(checkout_root)
    current_installation_exists = installation_profile_path(target_root).exists()
    launchagent_recommended = True
    launchagent_recommendation_source = "fresh_install_default"
    if current_installation_exists:
        launchagent_recommended = launchagent_user_default
        launchagent_recommendation_source = "saved_user_default"
    elif not launchagent_user_default:
        launchagent_recommendation_source = "fresh_install_default_ignored_saved_opt_out"
    if current_installation_exists:
        target_monitor = dict(load_installation_profile(target_root).get("monitor") or {})
        target_host = str(target_monitor.get("host") or monitor_host).strip() or monitor_host
        try:
            target_port = max(1, min(int(target_monitor.get("port") or monitor_port), 65535))
        except (TypeError, ValueError):
            target_port = monitor_port
        target_entry_active = any(
            str(entry.get("installation_root") or "").strip() == str(target_root.resolve())
            and str(entry.get("active_host") or entry.get("configured_host") or DEFAULT_MONITOR_HOST).strip() == target_host
            and int(entry.get("active_port") or entry.get("configured_port") or 0) == target_port
            for entry in active_monitor_entries
            if isinstance(entry, dict)
        )
        target_port_status = _port_conflict_status(target_host, target_port)
        if target_entry_active or target_port_status["available"]:
            recommended_port = target_port
    if current_installation_exists:
        recommended_install_mode = "repair_existing_installation"
    elif recommended_memory_root_source in {"default_home_root", "explicit"} and not Path(recommended_memory_root).exists():
        recommended_install_mode = "fresh_installation"
    elif recommended_memory_root:
        recommended_install_mode = "install_with_existing_memory_root"
    else:
        recommended_install_mode = "fresh_installation"
    launchagent_label, launchagent_env_file, launchagent_path_text = _launchagent_identity_for_target(
        checkout_role=role,
        target_root=target_root,
        recommended_memory_root=recommended_memory_root,
    )
    wrapper_conflicts = _wrapper_conflicts(checkout_root=checkout_root, prefix=recommended_wrapper_prefix, suffix=recommended_wrapper_suffix)
    user_cli_conflict = _user_cli_conflict(target_root)
    replace_existing_global_links = any(bool(item.get("conflict")) for item in wrapper_conflicts) or bool(user_cli_conflict.get("conflict"))
    launchagent_identity = _launchagent_identity_status(label=launchagent_label, env_file=launchagent_env_file, plist_path=launchagent_path_text)
    repo_index_status = _repo_index_discovery_status(
        checkout_root=checkout_root,
        memory_root=Path(recommended_memory_root).expanduser().resolve() if recommended_memory_root else (target_root / "memory").resolve(),
    )
    recommended_plan = {
        "target_root": str(target_root),
        "memory_root_mode": "attach_existing" if recommended_memory_root else "new",
        "memory_root": recommended_memory_root,
        "monitor_port": recommended_port,
        "monitor_port_revalidated_at_install": True,
        "wrapper_prefix": recommended_wrapper_prefix,
        "wrapper_suffix": recommended_wrapper_suffix,
        "global_wrapper_links": _default_global_wrapper_links(),
        "replace_existing_global_links": replace_existing_global_links,
        "install_launchagent": launchagent_recommended,
        "language": language,
        "install_mode": recommended_install_mode,
        "requires_user_confirmation": True,
    }
    return {
        "start_path": str(start.resolve()),
        "checkout_root": str(checkout_root),
        "checkout_role": role,
        "target_root": str(target_root),
        "current_installation_exists": current_installation_exists,
        "recommended_install_mode": recommended_install_mode,
        "paired_checkout": str(paired.resolve()) if paired is not None else "",
        "detected_source_checkout": str(paired.resolve()) if role == "public_checkout" and paired is not None else "",
        "reply_language": language,
        "reply_language_source": language_source,
        "memory_root_candidates": memory_candidates,
        "recommended_memory_root": recommended_memory_root,
        "recommended_memory_root_source": recommended_memory_root_source if recommended_memory_root else "",
        "user_config_path": str(user_config_path()),
        "recommended_monitor_host": monitor_host,
        "recommended_monitor_port": recommended_port,
        "default_monitor_port": monitor_port,
        "active_monitor_runtime_entries": active_monitor_entries,
        "recommended_wrapper_prefix": recommended_wrapper_prefix,
        "recommended_wrapper_suffix": recommended_wrapper_suffix,
        "recommended_install_launchagent": launchagent_recommended,
        "recommended_install_launchagent_source": launchagent_recommendation_source,
        "wrapper_conflicts": wrapper_conflicts,
        "user_cli_conflict": user_cli_conflict,
        "launchagent_identity": launchagent_identity,
        "repo_index_status": repo_index_status,
        "recommended_plan": recommended_plan,
        "requires_user_confirmation": True,
    }


def _render_install_discovery(summary: dict[str, object], *, language: str | None = None) -> str:
    from ....application.platform import current_platform_profile

    lang = normalize_language(language or str(summary.get("reply_language") or "en"))
    checkout_root = Path(str(summary["checkout_root"])).expanduser().resolve()
    target_root = Path(str(summary["target_root"])).expanduser().resolve()
    runtime = python_runtime_status(checkout_root)
    frontend = frontend_build_status(checkout_root)
    platform_profile = current_platform_profile()
    scheduler_name = _scheduler_display_name(platform_profile)
    language_source = str(summary.get("reply_language_source") or "unknown")
    monitor_reason = _monitor_port_reason_text(
        recommended_port=int(summary["recommended_monitor_port"]),
        default_port=int(summary.get("default_monitor_port") or DEFAULT_MONITOR_PORT),
        language=lang,
    )
    lines = [
        _ui_text(lang, en="Installation discovery", de="Installations-Discovery"),
        f"- {_ui_text(lang, en='checkout root', de='Checkout-Root')}: {summary['checkout_root']}",
        f"- {_ui_text(lang, en='checkout role', de='Checkout-Rolle')}: {summary['checkout_role']}",
        f"- {_ui_text(lang, en='recommended mode', de='Empfohlener Modus')}: {summary['recommended_install_mode']}",
        f"- {_ui_text(lang, en='suggested target', de='Vorgeschlagenes Ziel')}: {summary['target_root']}",
        f"- {_ui_text(lang, en='reply language', de='Antwortsprache')}: {summary['reply_language']}",
        f"- {_ui_text(lang, en='reply language source', de='Quelle der Antwortsprache')}: {language_source}",
        f"- {_ui_text(lang, en='checkout change mode', de='Checkout-Aenderungsmodus')}: {_checkout_change_mode_text(checkout_root=checkout_root, target_root=target_root, language=lang)}",
        f"- {_ui_text(lang, en='suggested monitor port', de='Vorgeschlagener Monitor-Port')}: {summary['recommended_monitor_host']}:{summary['recommended_monitor_port']} ({monitor_reason})",
        f"- {_ui_text(lang, en='suggested wrapper prefix', de='Vorgeschlagenes Wrapper-Prefix')}: {summary['recommended_wrapper_prefix'] or '-'}",
        f"- {_ui_text(lang, en='suggested wrapper suffix', de='Vorgeschlagenes Wrapper-Suffix')}: {summary['recommended_wrapper_suffix'] or '-'}",
        f"- {_ui_text(lang, en='global PATH wrapper links', de='Globale PATH-Wrapper-Links')}: "
        + ", ".join(
            link_command_name(
                wrapper_name,
                str(summary.get("recommended_wrapper_prefix") or "").strip(),
                str(summary.get("recommended_wrapper_suffix") or "").strip(),
            )
            for wrapper_name in _default_global_wrapper_links()
        ),
        f"- {_ui_text(lang, en=f'{scheduler_name} install/load in this plan', de=f'{scheduler_name}-Installation/Aktivierung in diesem Plan')}: "
        + _ui_text(lang, en="enabled by default" if summary["recommended_install_launchagent"] else "deferred by default", de="standardmaessig aktiv" if summary["recommended_install_launchagent"] else "standardmaessig spaeter"),
        f"- {_ui_text(lang, en=f'{scheduler_name} recommendation source', de=f'Quelle der {scheduler_name}-Empfehlung')}: "
        + _launchagent_recommendation_source_text(str(summary.get("recommended_install_launchagent_source") or ""), language=lang),
        f"- {_ui_text(lang, en='runtime bootstrap', de='Runtime-Bootstrap')}: {_ui_text(lang, en='yes', de='ja')}",
        f"- {_ui_text(lang, en='monitor startup after install', de='Monitorstart nach der Installation')}: {_ui_text(lang, en='yes', de='ja')}",
        f"- {_ui_text(lang, en='user confirmation required', de='Nutzerfreigabe erforderlich')}: "
        + _ui_text(lang, en="yes", de="ja"),
        f"- {_ui_text(lang, en='agent approval boundary', de='Agent-Freigabegrenze')}: "
        + _ui_text(
            lang,
            en="agents must stop after presenting this plan and wait for an explicit user chat approval before running or confirming install",
            de="Agenten muessen nach diesem Plan stoppen und vor Ausfuehrung oder Bestaetigung der Installation eine ausdrueckliche Chat-Freigabe des Nutzers abwarten",
        ),
    ]
    if summary.get("detected_source_checkout"):
        lines.append(
            f"- {_ui_text(lang, en='detected source checkout', de='Erkanntes Source-Checkout')}: {summary['detected_source_checkout']}"
        )
    launchagent_identity = dict(summary.get("launchagent_identity") or {})
    if launchagent_identity:
        lines.append(f"- {_ui_text(lang, en='launchagent label', de='LaunchAgent-Label')}: {launchagent_identity.get('label')}")
        if launchagent_identity.get("drift_detected"):
            lines.append(
                f"- {_ui_text(lang, en='launchagent drift', de='LaunchAgent-Drift')}: "
                + "; ".join(str(item) for item in launchagent_identity.get("drift_reasons") or [])
            )
    recommended_memory_root = str(summary.get("recommended_memory_root") or "")
    if recommended_memory_root:
        source_text = _recommended_memory_root_source_text(str(summary.get('recommended_memory_root_source') or ''))
        lines.append(
            f"- {_ui_text(lang, en='suggested memory root', de='Vorgeschlagener Memory-Root')}: "
            + f"{recommended_memory_root} ({source_text})"
        )
        lines.append(
            f"- {_ui_text(lang, en='runtime storage behavior', de='Runtime-Storage-Verhalten')}: "
            + _ui_text(
                lang,
                en=(
                    "this install uses a target-local runtime storage root by default"
                    if bool((summary.get("recommended_plan") or {}).get("isolated"))
                    else "this install reuses the central runtime storage unless you override --memory-root"
                ),
                de=(
                    "diese Installation nutzt standardmaessig einen ziel-lokalen Runtime-Storage-Root"
                    if bool((summary.get("recommended_plan") or {}).get("isolated"))
                    else "diese Installation nutzt den zentralen Runtime-Storage weiter, solange du --memory-root nicht ueberschreibst"
                ),
            )
        )
    candidates = list(summary.get("memory_root_candidates") or [])
    if candidates:
        lines.append(_ui_text(lang, en="- discovered memory roots:", de="- erkannte Memory-Roots:"))
        for item in candidates[:5]:
            lines.append(
                "  - "
                + f"{item['memory_root']} "
                + f"[{item['reason']}, {item['confidence']}, "
                + ("exists" if item.get("exists") else "missing")
                + "]"
            )
    wrapper_conflicts = [item for item in list(summary.get("wrapper_conflicts") or []) if item.get("conflict")]
    if wrapper_conflicts:
        lines.append(
            _ui_text(
                lang,
                en="- wrapper conflicts: existing global ACE wrapper links will be moved to this installation by default",
                de="- Wrapper-Konflikte: bestehende globale ACE-Wrapper-Links werden standardmaessig auf diese Installation umgezogen",
            )
        )
        for item in wrapper_conflicts[:5]:
            lines.append(f"  - {item['command_name']} -> {item['resolved_path']}")
    user_cli_conflict = dict(summary.get("user_cli_conflict") or {})
    if user_cli_conflict.get("conflict"):
        lines.append(
            f"- {_ui_text(lang, en='global cli link takeover', de='Uebernahme des globalen CLI-Links')}: "
            + _ui_text(
                lang,
                en=f"{user_cli_conflict.get('path')} currently points to {user_cli_conflict.get('resolved_path') or '-'} and will be moved to this installation by default",
                de=f"{user_cli_conflict.get('path')} zeigt derzeit auf {user_cli_conflict.get('resolved_path') or '-'} und wird standardmaessig auf diese Installation umgezogen",
            )
        )
    if bool((summary.get("recommended_plan") or {}).get("isolated")):
        lines.append(
            f"- {_ui_text(lang, en='isolated install contract', de='Isolierter Installationsvertrag')}: "
            + _ui_text(
                lang,
                en="target-local memory root, instance-prefixed wrapper names, and no takeover of shared agent-context-engine/ace",
                de="ziel-lokaler Memory-Root, instanzpraefixierte Wrapper-Namen und keine Uebernahme von agent-context-engine/ace",
            )
        )
    active_monitors = [item for item in list(summary.get("active_monitor_runtime_entries") or []) if isinstance(item, dict)]
    if active_monitors:
        lines.append(_ui_text(lang, en="- active monitor runtime entries:", de="- aktive Monitor-Runtime-Eintraege:"))
        for item in active_monitors[:5]:
            lines.append(
                "  - "
                + f"{item.get('instance_id') or 'unknown'} "
                + f"{item.get('active_host') or item.get('configured_host') or DEFAULT_MONITOR_HOST}:"
                + f"{item.get('active_port') or item.get('configured_port') or 0} "
                + f"[pid={item.get('pid') or 0}, status={item.get('status') or 'unknown'}]"
            )
    repo_index_status = dict(summary.get("repo_index_status") or {})
    repo_source = str(repo_index_status.get("source") or "missing")
    repo_count = int(repo_index_status.get("entry_count") or 0)
    repo_path = str(repo_index_status.get("path") or "")
    if repo_source != "missing" and repo_count > 0:
        lines.append(
            f"- {_ui_text(lang, en='recognized repos/folders', de='Erkannte Repos/Ordner')}: "
            + _ui_text(
                lang,
                en=f"{repo_count} entry/entries already known via {'runtime memory' if repo_source == 'runtime' else 'legacy repo index fallback'}",
                de=f"{repo_count} Eintrag/Eintraege bereits bekannt ueber {'Runtime-Memory' if repo_source == 'runtime' else 'Legacy-Repo-Index-Fallback'}",
            )
        )
        lines.append(f"- {_ui_text(lang, en='repo index location', de='Repo-Index-Ablage')}: {repo_path}")
        sample_entries = [str(item) for item in list(repo_index_status.get("entries") or []) if str(item).strip()]
        if sample_entries:
            lines.append(
                f"- {_ui_text(lang, en='known repo examples', de='Beispiele bekannter Repos')}: "
                + ", ".join(sample_entries[:5])
            )
    else:
        lines.append(
            f"- {_ui_text(lang, en='recognized repos/folders', de='Erkannte Repos/Ordner')}: "
            + _ui_text(
                lang,
                en="none yet; you can add them now with --project or later in the monitor",
                de="noch keine; du kannst sie jetzt mit --project oder spaeter im Monitor aufnehmen",
            )
        )
    lines.append(
        f"- {_ui_text(lang, en='monitor repo knowledge view', de='Monitor-Ansicht fuer Repo-Wissen')}: "
        + _ui_text(lang, en="Personal -> Repo-Index", de="Persoenlich -> Repo-Index")
    )
    lines.append(
        f"- {_ui_text(lang, en='later repo/folder updates', de='Spaetere Repo-/Ordner-Ergaenzungen')}: "
        + _ui_text(
            lang,
            en="agents can add or edit entries in the monitor Repo-Index panel; install also accepts repeated --project name=/absolute/path",
            de="Agents koennen Eintraege spaeter im Monitor-Panel Repo-Index ergaenzen oder bearbeiten; die Installation akzeptiert ausserdem wiederholte --project name=/absoluter/pfad",
        )
    )
    lines.append(_ui_text(lang, en="- local prerequisite probe:", de="- lokaler Voraussetzungs-Check:"))
    lines.append(
        "  - "
        + _ui_text(
            lang,
            en=f"python {runtime['python_version']} ({'ok' if runtime['python_version_supported'] else 'unsupported'}, required {runtime['python_version_required']})",
            de=f"Python {runtime['python_version']} ({'ok' if runtime['python_version_supported'] else 'nicht unterstuetzt'}, erforderlich {runtime['python_version_required']})",
        )
    )
    lines.append(
        "  - "
        + _ui_text(
            lang,
            en=f"node {frontend['node_version'] or 'missing'} ({'ok' if frontend['node_version_supported'] else 'unsupported'}, required {frontend['node_version_required']})",
            de=f"Node {frontend['node_version'] or 'fehlt'} ({'ok' if frontend['node_version_supported'] else 'nicht unterstuetzt'}, erforderlich {frontend['node_version_required']})",
        )
    )
    lines.append(
        "  - "
        + _ui_text(
            lang,
            en=f"npm {frontend['npm_version'] or 'missing'} ({'ok' if frontend['npm_version_supported'] else 'unsupported'}, required {frontend['npm_version_required']})",
            de=f"npm {frontend['npm_version'] or 'fehlt'} ({'ok' if frontend['npm_version_supported'] else 'nicht unterstuetzt'}, erforderlich {frontend['npm_version_required']})",
        )
    )
    prerequisite_suggestions = _prerequisite_suggestions(runtime=runtime, frontend=frontend, language=lang)
    if prerequisite_suggestions:
        lines.append(
            _ui_text(
                lang,
                en="- prerequisite suggestions:",
                de="- Vorschlaege fuer lokale Voraussetzungen:",
            )
        )
        for item in prerequisite_suggestions:
            lines.append(f"  - {item}")
    if not bool(summary.get("recommended_install_launchagent", True)):
        lines.append(
            "  - "
            + _ui_text(
                lang,
                en=f"For periodic dreaming, summary catch-up, and background queue processing, install the {scheduler_name} after explicit approval.",
                de=f"Fuer periodisches Dreaming, Summary-Catch-up und Hintergrund-Queue-Verarbeitung den {scheduler_name} nach ausdruecklicher Freigabe installieren.",
            )
        )
    lines.append("")
    lines.append(
        _ui_text(
            lang,
            en="Do not apply the suggested target, memory root, monitor port, wrapper naming, or refresh mode until the user confirms them.",
            de="Vorgeschlagenes Ziel, Memory-Root, Monitor-Port, Wrapper-Namensschema oder Refresh-Modus erst nach ausdruecklicher Nutzerfreigabe anwenden.",
        )
    )
    lines.append(
        _ui_text(
            lang,
            en="The proposed monitor port is a discovery default; the installer revalidates it again immediately before writing config.",
            de="Der vorgeschlagene Monitor-Port ist ein Discovery-Default; der Installer validiert ihn unmittelbar vor dem Schreiben der Konfiguration erneut.",
        )
    )
    if str(summary.get("reply_language") or "") == "en" and language_source in {"checkout_installation", "user_config_default_language", "fallback_default"}:
        lines.append(
            _ui_text(
                lang,
                en="Language warning: English was inferred from the checkout or saved defaults, not from an explicit install-language choice. If the user asked in another language or later switched the install conversation language, rerun install-discovery with --language de or --language en explicitly.",
                de="Sprachwarnung: Englisch wurde aus dem Checkout oder aus gespeicherten Defaults abgeleitet, nicht aus einer expliziten Installations-Sprachwahl. Wenn der Nutzer in einer anderen Sprache gefragt hat oder die Sprache spaeter gewechselt hat, install-discovery explizit mit --language de oder --language en neu starten.",
            )
        )
    return "\n".join(lines)


def _apply_isolated_discovery_overrides(summary: dict[str, object]) -> dict[str, object]:
    target_root = Path(str(summary["target_root"])).expanduser().resolve()
    instance_name = _isolated_instance_name_for_target(target_root)
    summary["recommended_memory_root"] = str(_isolated_default_memory_root(target_root))
    summary["recommended_memory_root_source"] = "current_installation"
    summary["recommended_wrapper_prefix"] = f"{instance_name}-"
    summary["recommended_plan"] = {
        **dict(summary.get("recommended_plan") or {}),
        "memory_root": str(_isolated_default_memory_root(target_root)),
        "wrapper_prefix": f"{instance_name}-",
        "replace_existing_global_links": False,
        "install_mode": "isolated_installation",
        "isolated": True,
    }
    summary["recommended_install_mode"] = "isolated_installation"
    summary["wrapper_conflicts"] = []
    summary["user_cli_conflict"] = {
        **dict(summary.get("user_cli_conflict") or {}),
        "conflict": False,
    }
    return summary


def _coerce_str_list(values: object) -> list[str]:
    if not values:
        return []
    items = values if isinstance(values, (list, tuple)) else [values]
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def _coerce_plan_json_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


def _load_install_plan(path: str) -> dict[str, object]:
    payload_text = Path(path).expanduser().resolve().read_text(encoding="utf-8")
    payload = json.loads(payload_text)
    if not isinstance(payload, dict):
        raise ValueError("install plan file did not contain a JSON object")
    if "install_plan" in payload and isinstance(payload.get("install_plan"), dict):
        payload = payload["install_plan"]
        if not isinstance(payload, dict):
            raise ValueError("install plan payload had invalid install_plan field")
    return payload


def _guided_install_plan(summary: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    target_root = Path(str(args.target or summary["target_root"])).expanduser().resolve()
    inferred_target = bool(getattr(args, "_guided_target_inferred", False))
    isolated = bool(getattr(args, "isolated", False))
    explicit_memory_root = str(getattr(args, "memory_root", None) or "").strip()
    discovered_memory_root = str(summary.get("recommended_memory_root") or "").strip() if inferred_target else ""
    memory_root_text = explicit_memory_root or (str(_isolated_default_memory_root(target_root)) if isolated else discovered_memory_root)
    monitor_port = int(getattr(args, "monitor_port", None) or summary["recommended_monitor_port"])
    wrapper_prefix = str(
        getattr(args, "wrapper_prefix", None)
        or (safe_slug(str(getattr(args, "instance_name", None))) + "-" if isolated and getattr(args, "instance_name", None) else "")
        or (f"{_isolated_instance_name_for_target(target_root)}-" if isolated and not getattr(args, "instance_name", None) else "")
        or summary.get("recommended_wrapper_prefix")
        or ""
    ).strip()
    wrapper_suffix = str(getattr(args, "wrapper_suffix", None) or summary.get("recommended_wrapper_suffix") or "").strip()
    monitor_host = str(getattr(args, "monitor_host", None) or summary.get("recommended_monitor_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    launchagent_identity = dict(summary.get("launchagent_identity") or {})
    default_launchagent = _default_launchagent_profile_for_target(
        checkout_role=str(summary.get("checkout_role") or "unknown_checkout"),
        target_root=target_root,
        memory_root=Path(memory_root_text).expanduser().resolve() if memory_root_text else _default_storage_root_for_install(target_root, args),
    )
    launchagent_label = str(
        getattr(args, "launchagent_label", None)
        or launchagent_identity.get("label")
        or default_launchagent["label"]
    ).strip()
    launchagent_path = str(
        getattr(args, "launchagent_path", None)
        or launchagent_identity.get("plist_path")
        or _expected_launchagent_plist_path(launchagent_label)
    ).strip()
    launchagent_env_file = str(
        getattr(args, "launchagent_env_file", None)
        or launchagent_identity.get("env_file")
        or default_launchagent["env_file"]
    ).strip()
    install_launchagent = bool(getattr(args, "install_launchagent", summary.get("recommended_install_launchagent", True)))
    replace_existing_global_links = False if isolated else bool(
        getattr(args, "replace_existing_global_links", summary.get("recommended_plan", {}).get("replace_existing_global_links", False))
    )
    bootstrap_runtime = bool(getattr(args, "bootstrap_runtime", True))
    start_monitor = bool(getattr(args, "start_monitor", True))
    language = normalize_language(str(getattr(args, "language", None) or summary.get("reply_language") or "en"))
    workspace_roots = _workspace_root_overrides(args)
    workflows = {
        key: _normalize_workflow_runner(key, str(getattr(args, key, None) or WORKFLOW_RUNNER_DEFAULTS[key]))
        for key in WORKFLOW_RUNNER_DEFAULTS
    }
    effective_memory_root = (
        Path(memory_root_text).expanduser().resolve()
        if memory_root_text
        else _default_storage_root_for_install(target_root, args)
    )
    install_mode = "isolated_installation" if isolated else "fresh_installation"
    if installation_profile_path(target_root).exists():
        install_mode = "repair_existing_installation"
    elif effective_memory_root.exists() and not isolated:
        install_mode = "install_with_existing_memory_root"
    return {
        "target_root": str(target_root),
        "memory_root_mode": "target_local_isolated" if isolated and not explicit_memory_root else ("attach_existing" if memory_root_text else "new"),
        "memory_root": memory_root_text,
        "monitor_host": monitor_host,
        "monitor_port": monitor_port,
        "launchagent_label": launchagent_label,
        "launchagent_path": launchagent_path,
        "launchagent_env_file": launchagent_env_file,
        "monitor_port_revalidated_at_install": bool(summary.get("recommended_plan", {}).get("monitor_port_revalidated_at_install", True)),
        "wrapper_prefix": wrapper_prefix,
        "wrapper_suffix": wrapper_suffix,
        "link_dir": str(Path(getattr(args, "link_dir", None) or "~/.local/bin").expanduser().resolve()),
        "workspace_roots": {key: [str(path) for path in paths] for key, paths in workspace_roots.items()},
        "workflows": workflows,
        "bootstrap_runtime": bootstrap_runtime,
        "install_launchagent": install_launchagent,
        "start_monitor": start_monitor,
        "global_wrapper_links": _linked_wrapper_specs(args),
        "replace_existing_global_links": replace_existing_global_links,
        "language": language,
        "install_mode": install_mode,
        "isolated": isolated,
        "detected_source_checkout": str(summary.get("detected_source_checkout") or ""),
        "checkout_role": str(summary.get("checkout_role") or ""),
        "requires_user_confirmation": bool(summary.get("requires_user_confirmation", True)),
    }


def _apply_install_plan(args: argparse.Namespace, plan: dict[str, object]) -> None:
    target_root = str(plan.get("target_root") or "").strip()
    if not target_root:
        raise ValueError("install plan is missing required field: target_root")
    args.target = target_root
    memory_root = str(plan.get("memory_root") or "").strip()
    if memory_root:
        args.memory_root = memory_root
    args.monitor_host = str(plan.get("monitor_host") or getattr(args, "monitor_host", DEFAULT_MONITOR_HOST) or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = plan.get("monitor_port")
    if monitor_port is not None:
        try:
            args.monitor_port = int(monitor_port)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"install plan has invalid monitor_port: {monitor_port!r}") from exc
    args.bootstrap_runtime = _coerce_plan_json_bool(plan.get("bootstrap_runtime", getattr(args, "bootstrap_runtime", True)))
    args.start_monitor = _coerce_plan_json_bool(plan.get("start_monitor", getattr(args, "start_monitor", True)))
    args.install_launchagent = _coerce_plan_json_bool(plan.get("install_launchagent", getattr(args, "install_launchagent", True)))
    args.replace_existing_global_links = _coerce_plan_json_bool(
        plan.get("replace_existing_global_links", getattr(args, "replace_existing_global_links", False))
    )
    args.isolated = _coerce_plan_json_bool(plan.get("isolated", getattr(args, "isolated", False)))
    wrapper_prefix = str(plan.get("wrapper_prefix") or "").strip()
    if wrapper_prefix:
        args.wrapper_prefix = wrapper_prefix
    wrapper_suffix = str(plan.get("wrapper_suffix") or "").strip()
    if wrapper_suffix:
        args.wrapper_suffix = wrapper_suffix
    launchagent_label = str(plan.get("launchagent_label") or "").strip()
    if launchagent_label:
        args.launchagent_label = launchagent_label
    launchagent_path = str(plan.get("launchagent_path") or "").strip()
    if launchagent_path:
        args.launchagent_path = launchagent_path
    launchagent_env_file = str(plan.get("launchagent_env_file") or "").strip()
    if launchagent_env_file:
        args.launchagent_env_file = launchagent_env_file
    link_dir = str(plan.get("link_dir") or "").strip()
    if link_dir:
        args.link_dir = link_dir
    language = str(plan.get("language") or "").strip()
    if language:
        args.language = language
    workflow_runners = plan.get("workflows")
    if isinstance(workflow_runners, dict):
        for key, value in workflow_runners.items():
            if key in WORKFLOW_RUNNER_DEFAULTS:
                setattr(args, key, str(value))
    workspace_roots = plan.get("workspace_roots")
    if isinstance(workspace_roots, dict):
        for key in ("codex", "claude", "cursor"):
            value = workspace_roots.get(key)
            if isinstance(value, str):
                setattr(args, f"{key}_workspace_root", [value])
            elif value:
                setattr(args, f"{key}_workspace_root", _coerce_str_list(value))
    raw_wrappers = plan.get("global_wrapper_links")
    linked_wrappers = [str(value).strip() for value in list(raw_wrappers or _default_global_wrapper_links()) if str(value).strip()]
    linked_wrappers = list(dict.fromkeys(linked_wrappers))
    for flag_name, wrapper_name in [
        ("link_codex_memory", "codex-ace"),
        ("link_claude_memory", "claude-ace"),
        ("link_cursor_memory", "cursor-ace"),
        ("link_agy_memory", "agy-ace"),
        ("link_antigravity_memory", "antigravity-ace"),
        ("link_gemini_memory", "gemini-ace"),
        ("link_opencode_memory", "opencode-ace"),
    ]:
        setattr(args, flag_name, wrapper_name in linked_wrappers)


def _effective_memory_root_for_plan(target_root: Path, args: argparse.Namespace, summary: dict[str, object]) -> Path:
    if bool(getattr(args, "isolated", False)):
        explicit = str(getattr(args, "memory_root", None) or "").strip()
        if explicit:
            return Path(explicit).expanduser().resolve()
        return _isolated_default_memory_root(target_root)
    explicit = str(getattr(args, "memory_root", None) or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    recommended = str(summary.get("recommended_memory_root") or "").strip()
    if recommended:
        return Path(recommended).expanduser().resolve()
    return (target_root / "memory").resolve()


def _render_install_plan(summary: dict[str, object], args: argparse.Namespace, *, language: str) -> str:
    from ....application.platform import current_platform_profile

    target_root = Path(str(args.target or summary["target_root"])).expanduser().resolve()
    memory_root = _effective_memory_root_for_plan(target_root, args, summary)
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    monitor_host = str(getattr(args, "monitor_host", None) or summary.get("recommended_monitor_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = int(getattr(args, "monitor_port", None) or summary["recommended_monitor_port"])
    plan = _guided_install_plan(summary, args)
    install_launchagent = bool(plan.get("install_launchagent"))
    scheduler_name = _scheduler_display_name(current_platform_profile())
    install_mode = str(plan.get("install_mode") or summary.get("recommended_install_mode") or "fresh_installation")
    linked_wrappers = list(plan.get("global_wrapper_links") or [])
    display_wrapper_links = [link_command_name(wrapper_name, prefix, suffix) for wrapper_name in linked_wrappers]
    replace_existing_global_links = bool(plan.get("replace_existing_global_links"))
    isolated = bool(plan.get("isolated"))
    repo_index_status = dict(summary.get("repo_index_status") or {})
    repo_count = int(repo_index_status.get("entry_count") or 0)
    repo_path = str(repo_index_status.get("path") or "")
    lines = [
        _ui_text(language, en="Installation plan", de="Installationsplan"),
        f"- {_ui_text(language, en='mode', de='Modus')}: {install_mode}",
        f"- {_ui_text(language, en='target root', de='Ziel-Root')}: {target_root}",
        f"- {_ui_text(language, en='memory root', de='Memory-Root')}: {memory_root}",
        f"- {_ui_text(language, en='monitor', de='Monitor')}: {monitor_host}:{monitor_port}",
        f"- {_ui_text(language, en='wrapper naming', de='Wrapper-Namensschema')}: prefix={prefix or '-'} suffix={suffix or '-'}",
        f"- {_ui_text(language, en='global PATH wrapper links', de='Globale PATH-Wrapper-Links')}: "
        + (", ".join(display_wrapper_links) if display_wrapper_links else _ui_text(language, en="disabled", de="deaktiviert")),
        f"- {_ui_text(language, en='runtime bootstrap', de='Runtime-Bootstrap')}: "
        + _ui_text(language, en="yes" if plan.get("bootstrap_runtime") else "no", de="ja" if plan.get("bootstrap_runtime") else "nein"),
        f"- {_ui_text(language, en='monitor startup after install', de='Monitorstart nach der Installation')}: "
        + _ui_text(language, en="yes" if plan.get("start_monitor") else "no", de="ja" if plan.get("start_monitor") else "nein"),
        f"- {_ui_text(language, en=f'install {scheduler_name} now', de=f'{scheduler_name} jetzt installieren')}: "
        + _ui_text(language, en="yes" if install_launchagent else "later", de="ja" if install_launchagent else "spaeter"),
        f"- {_ui_text(language, en='existing global ACE links', de='Bestehende globale ACE-Links')}: "
        + _ui_text(
            language,
            en="relink to this installation" if replace_existing_global_links else "leave unchanged unless explicitly forced",
            de="werden auf diese Installation umgezogen" if replace_existing_global_links else "bleiben unveraendert, solange nicht explizit erzwungen",
        ),
        f"- {_ui_text(language, en='checkout change mode', de='Checkout-Aenderungsmodus')}: {_checkout_change_mode_text(checkout_root=Path(str(summary['checkout_root'])).expanduser().resolve(), target_root=target_root, language=language)}",
        f"- {_ui_text(language, en='monitor port finalization', de='Finalisierung des Monitor-Ports')}: "
        + _ui_text(language, en="revalidated immediately before writing config", de="wird unmittelbar vor dem Schreiben der Konfiguration erneut validiert"),
        f"- {_ui_text(language, en='repo knowledge in monitor', de='Repo-Wissen im Monitor')}: "
        + _ui_text(language, en="Personal -> Repo-Index", de="Persoenlich -> Repo-Index"),
        f"- {_ui_text(language, en='recognized repos/folders', de='Erkannte Repos/Ordner')}: "
        + (
            _ui_text(language, en=f"{repo_count} known", de=f"{repo_count} bekannt")
            if repo_count > 0
            else _ui_text(language, en="none yet", de="noch keine")
        ),
    ]
    if repo_path:
        lines.append(f"- {_ui_text(language, en='repo index location', de='Repo-Index-Ablage')}: {repo_path}")
    lines.append(
        f"- {_ui_text(language, en='later repo/folder updates', de='Spaetere Repo-/Ordner-Ergaenzungen')}: "
        + _ui_text(
            language,
            en="agents can update the Repo-Index in the monitor later; install also accepts repeated --project name=/absolute/path",
            de="Agents koennen den Repo-Index spaeter im Monitor aktualisieren; die Installation akzeptiert ausserdem wiederholte --project name=/absoluter/pfad",
        )
    )
    lines.append(
        f"- {_ui_text(language, en='agent approval boundary', de='Agent-Freigabegrenze')}: "
        + _ui_text(
            language,
            en="agents must stop here and get explicit user chat approval before answering yes to the final install prompt",
            de="Agenten muessen hier stoppen und vor einem Ja zum finalen Installationsprompt eine ausdrueckliche Chat-Freigabe des Nutzers einholen",
        )
    )
    if isolated:
        lines.append(
            f"- {_ui_text(language, en='isolated install contract', de='Isolierter Installationsvertrag')}: "
            + _ui_text(
                language,
                en="target-local memory root, instance-specific wrapper names, no shared agent-context-engine/ace takeover",
                de="ziel-lokaler Memory-Root, instanzspezifische Wrapper-Namen, keine Uebernahme von agent-context-engine/ace",
            )
        )
    if install_mode == "repair_existing_installation":
        lines.append(
            f"- {_ui_text(language, en='existing install interpretation', de='Interpretation bestehender Installation')}: "
            + _ui_text(
                language,
                en="the central target already looks like an existing managed install",
                de="das zentrale Ziel sieht bereits wie eine bestehende verwaltete Installation aus",
            )
        )
    return "\n".join(lines)


def _run_post_install_checks(target: Path, *, language: str, include_doctor: bool = True) -> dict[str, int]:
    doctor_summary = "0" if include_doctor else "skipped"
    if os.environ.get("AGENT_MEMORY_TEST_SKIP_POST_INSTALL_CHECKS", "") in {"1", "true", "True", "yes"}:
        print(
            _ui_text(
                language,
                en=f"verification summary: doctor={doctor_summary} check-installation=0",
                de=f"Verifikationszusammenfassung: doctor={doctor_summary} check-installation=0",
            )
        )
        return {"doctor_exit": 0, "check_installation_exit": 0}
    cli_path = agent_memory_cli_path_for_root(target)
    doctor_exit = 0
    if include_doctor:
        doctor = subprocess.run(
            [str(cli_path), "doctor"],
            cwd=str(target),
            env={**os.environ, ROOT_ENV_VAR: str(target)},
            text=True,
            capture_output=True,
            check=False,
        )
        doctor_output = "\n".join(part for part in [doctor.stdout.strip(), doctor.stderr.strip()] if part)
        if doctor.returncode != 0 and doctor_output:
            print(doctor_output)
        doctor_exit = int(doctor.returncode)
        doctor_summary = str(doctor_exit)
    check_args = argparse.Namespace(
        target=str(target),
        memory_root=None,
        codex_workspace_root=None,
        claude_workspace_root=None,
        cursor_workspace_root=None,
        monitor_runner=None,
        dream_runner=None,
        query_expansion_runner=None,
    )
    check_payload = _installation_check_payload(root=target, args=check_args)
    integration_items = list(((check_payload.get("integrations") or {}).get("items") or []))
    headless_readiness: list[str] = []
    for client in ("codex", "claude"):
        item = next((candidate for candidate in integration_items if str(candidate.get("client") or "") == client), None)
        if not item:
            continue
        status = "ready" if bool(item.get("ready")) else str(item.get("readiness_status") or "not_ready")
        headless_readiness.append(f"{client}={status}")
    if headless_readiness:
        print(
            _ui_text(
                language,
                en="authoritative post-install headless CLI readiness: ",
                de="Massgebliche Post-Installationsbereitschaft der Headless-CLIs: ",
            )
            + ", ".join(headless_readiness)
        )
    findings = list(check_payload.get("findings") or [])
    error_count = sum(1 for finding in findings if str(finding.get("severity") or "") == "error")
    notice_count = sum(1 for finding in findings if str(finding.get("severity") or "") == "notice")
    warning_count = len(findings) - error_count - notice_count
    check_exit = 1 if error_count else 0
    if findings:
        print(
            _ui_text(
                language,
                en=(
                    f"post-install check recorded {error_count} error(s), {warning_count} warning(s), "
                    f"and {notice_count} maintenance notice(s); "
                    "run `agent-context-engine check-installation` for details"
                ),
                de=(
                    f"Post-Installationspruefung hat {error_count} Fehler, {warning_count} Warnung(en) "
                    f"und {notice_count} Wartungshinweis(e) erfasst; "
                    "Details mit `agent-context-engine check-installation`"
                ),
            )
        )
        registry_notice_count = sum(
            1 for finding in findings if str(finding.get("code") or "").endswith("_central_registry_drift")
        )
        if registry_notice_count:
            print(
                _ui_text(
                    language,
                    en=(
                        f"maintenance notices: {registry_notice_count} historical project hook binding(s) need reconciliation; "
                        "the current installation prerequisites are healthy"
                    ),
                    de=(
                        f"Wartungshinweise: {registry_notice_count} historische Projekt-Hook-Bindung(en) muessen abgeglichen werden; "
                        "die Voraussetzungen der aktuellen Installation sind gesund"
                    ),
                )
            )
    print(
        _ui_text(
            language,
            en=f"verification summary: doctor={doctor_summary} check-installation={check_exit}",
            de=f"Verifikationszusammenfassung: doctor={doctor_summary} check-installation={check_exit}",
        )
    )
    return {"doctor_exit": doctor_exit, "check_installation_exit": check_exit}


def _recommended_install_command(summary: dict[str, object]) -> str:
    checkout_root = Path(str(summary["checkout_root"]))
    isolated = bool((summary.get("recommended_plan") or {}).get("isolated"))
    command = [
        _command_script_for_root(checkout_root),
        "install",
        "--target",
        _quote_platform_path(str(summary["target_root"])),
        "--language",
        str(summary["reply_language"]),
        "--monitor-port",
        str(summary["recommended_monitor_port"]),
    ]
    if isolated:
        command.append("--isolated")
    memory_root = str(summary.get("recommended_memory_root") or "").strip()
    if memory_root:
        command.extend(["--memory-root", _quote_platform_path(memory_root)])
    prefix = str(summary.get("recommended_wrapper_prefix") or "").strip()
    suffix = str(summary.get("recommended_wrapper_suffix") or "").strip()
    if prefix:
        command.extend(["--wrapper-prefix", prefix])
    if suffix:
        command.extend(["--wrapper-suffix", suffix.lstrip("-")])
    command.append("--bootstrap-runtime")
    for wrapper_name in _default_global_wrapper_links():
        command.append(f"--link-{wrapper_name}")
    if not bool(summary.get("recommended_install_launchagent", True)):
        command.append("--no-install-launchagent")
    return " ".join(command)


def _linked_wrapper_specs(args: argparse.Namespace) -> list[str]:
    wrappers: list[str] = []
    for flag_name, wrapper_name in [
        ("link_codex_memory", "codex-ace"),
        ("link_claude_memory", "claude-ace"),
        ("link_cursor_memory", "cursor-ace"),
        ("link_agy_memory", "agy-ace"),
        ("link_antigravity_memory", "antigravity-ace"),
        ("link_gemini_memory", "gemini-ace"),
        ("link_opencode_memory", "opencode-ace"),
    ]:
        if _link_flag_enabled(args, flag_name, default=wrapper_name != "antigravity-ace"):
            wrappers.append(wrapper_name)
    return wrappers


def _verify_global_wrapper_links(*, args: argparse.Namespace, prefix: str, suffix: str) -> list[dict[str, str]]:
    link_dir = Path(args.link_dir).expanduser().resolve()
    results: list[dict[str, str]] = []
    for wrapper_name in _linked_wrapper_specs(args):
        command_name = link_command_name(wrapper_name, prefix, suffix)
        link_path = link_dir / command_name
        published_link_path = Path(f"{link_path}.cmd") if os.name == "nt" and link_path.suffix.lower() != ".cmd" else link_path
        try:
            target = str(published_link_path.resolve(strict=False)) if (published_link_path.exists() or published_link_path.is_symlink()) else ""
        except OSError:
            target = ""
        resolved = shutil.which(command_name) or ""
        results.append(
            {
                "wrapper_name": wrapper_name,
                "command_name": command_name,
                "link_path": str(published_link_path),
                "link_exists": "yes" if (published_link_path.exists() or published_link_path.is_symlink()) else "no",
                "target": target,
                "path_resolved": resolved,
            }
        )
    return results


def _wrapper_start_hints(target: Path, args: argparse.Namespace) -> list[str]:
    linked_wrappers = _linked_wrapper_specs(args)
    if linked_wrappers:
        prefix = install_wrapper_prefix(args)
        suffix = install_wrapper_suffix(args)
        return [link_command_name(name, prefix, suffix) for name in linked_wrappers]
    hints: list[str] = []
    for wrapper_name in GLOBAL_WRAPPERS:
        wrapper_path = wrapper_script_path(target, wrapper_name)
        try:
            display = f"./{wrapper_path.relative_to(target)}"
        except ValueError:
            display = str(wrapper_path)
        hints.append(display)
    return hints


def _default_launchagent_label_for_target(target: Path) -> str:
    return _default_launchagent_profile_for_target(
        checkout_role="unknown_checkout",
        target_root=target,
        memory_root=(target / "memory").resolve(),
    )["label"]


def _default_launchagent_profile_for_target(
    *,
    checkout_role: str,
    target_root: Path,
    memory_root: Path,
) -> dict[str, str]:
    label = (
        f"{DEFAULT_LABEL.rsplit('.', 1)[0]}.{safe_slug(target_root.name)}"
        if checkout_role in {"public_checkout", "fresh_installation_candidate", "unknown_checkout"}
        else DEFAULT_LABEL
    )
    profile = default_launchagent_profile(label=label)
    profile["env_file"] = _default_launchagent_env_file_for_storage(memory_root)
    return profile


def _monitor_start_command(target: Path, *, runner: str, host: str, port: int, language: str) -> list[str]:
    cli_path = agent_memory_cli_path_for_root(target)
    if os.name == "nt":
        cli_path_obj = Path(cli_path)
        if not cli_path_obj.is_absolute():
            cli_path = str((target / cli_path_obj).resolve())
    return [
        str(cli_path),
        "monitor",
        "--runner",
        runner,
        "--host",
        host,
        "--port",
        str(port),
        "--language",
        language,
        "--no-open",
    ]


def _open_monitor_howto(*, host: str, port: int, runner: str, language: str) -> None:
    if os.environ.get("AGENT_MEMORY_TEST_SKIP_MONITOR_OPEN", "") in {"1", "true", "True", "yes"}:
        return
    url = f"http://{host}:{port}/?runner={quote(runner)}&lang={quote(language)}#howto"
    threading.Timer(0.35, lambda: webbrowser.open(url)).start()


def _superseded_monitor_candidates(*, target: Path, memory_root: Path) -> list[dict[str, object]]:
    normalized_target = str(target.resolve())
    normalized_memory_root = str(memory_root.resolve())
    candidates: list[dict[str, object]] = []
    seen: set[tuple[str, int, str]] = set()
    for entry in active_monitor_runtime_entries(include_shutdown_token=True):
        if not isinstance(entry, dict):
            continue
        entry_root = str(entry.get("installation_root") or "").strip()
        entry_memory_root = str(entry.get("memory_root") or "").strip()
        if not entry_root or entry_root == normalized_target or entry_memory_root != normalized_memory_root:
            continue
        host = str(entry.get("active_host") or entry.get("configured_host") or DEFAULT_MONITOR_HOST).strip()
        try:
            port = int(entry.get("active_port") or entry.get("configured_port") or 0)
        except (TypeError, ValueError):
            continue
        if not host or port <= 0 or _local_monitor_probe_host(host) is None:
            continue
        key = (host, port, entry_root)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            {
                "host": host,
                "port": port,
                "installation_root": entry_root,
                "shutdown_token": str(entry.get("shutdown_token") or ""),
            }
        )
    if os.name != "nt":
        try:
            processes = subprocess.run(
                ["ps", "-axo", "pid=,command="],
                text=True,
                capture_output=True,
                check=False,
                timeout=3,
            )
        except (OSError, subprocess.SubprocessError):
            processes = None
        for line in (processes.stdout.splitlines() if processes and processes.returncode == 0 else []):
            match = re.match(r"^\s*\d+\s+(.+)$", line)
            if not match:
                continue
            try:
                tokens = shlex.split(match.group(1))
            except ValueError:
                continue
            try:
                monitor_index = tokens.index("monitor")
            except ValueError:
                continue
            command_prefix = " ".join(tokens[:monitor_index])
            if "agent_context_engine.py" not in command_prefix and "agent-context-engine" not in command_prefix:
                continue
            monitor_args = tokens[monitor_index + 1 :]
            host = DEFAULT_MONITOR_HOST
            port = DEFAULT_MONITOR_PORT
            if "--host" in monitor_args:
                index = monitor_args.index("--host")
                if index + 1 < len(monitor_args):
                    host = str(monitor_args[index + 1]).strip() or DEFAULT_MONITOR_HOST
            if "--port" in monitor_args:
                index = monitor_args.index("--port")
                if index + 1 < len(monitor_args):
                    try:
                        port = int(monitor_args[index + 1])
                    except ValueError:
                        continue
            payload = _monitor_status_payload(host, port)
            if not payload:
                continue
            entry_root = str(payload.get("root") or payload.get("install_root") or "").strip()
            entry_memory_root = str(payload.get("memory_root") or "").strip()
            if not entry_root or entry_root == normalized_target or entry_memory_root != normalized_memory_root:
                continue
            key = (host, port, entry_root)
            if key in seen:
                continue
            seen.add(key)
            candidates.append({"host": host, "port": port, "installation_root": entry_root})
    return candidates


def _monitor_status_payload(host: str, port: int, *, timeout: float = 0.5) -> dict[str, object] | None:
    probe_host = _local_monitor_probe_host(host)
    if probe_host is None:
        return None
    url_host = f"[{probe_host}]" if ":" in probe_host else probe_host
    try:
        with urlopen(f"http://{url_host}:{port}/api/status", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _local_monitor_probe_host(host: str) -> str | None:
    normalized = str(host or "").strip().strip("[]").lower()
    if normalized == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError:
        return None
    if address.is_loopback:
        return str(address)
    if address.is_unspecified:
        return "::1" if address.version == 6 else "127.0.0.1"
    return None


def _wait_for_monitor_identity(
    *,
    target: Path,
    memory_root: Path,
    host: str,
    port: int,
    timeout: float = 20.0,
) -> tuple[bool, dict[str, object] | None]:
    expected_root = str(target.resolve())
    expected_memory_root = str(memory_root.resolve())
    deadline = time.monotonic() + max(0.1, timeout)
    latest: dict[str, object] | None = None
    while time.monotonic() < deadline:
        latest = _monitor_status_payload(host, port)
        if (
            latest
            and str(latest.get("root") or latest.get("install_root") or "").strip() == expected_root
            and str(latest.get("memory_root") or "").strip() == expected_memory_root
        ):
            return True, latest
        time.sleep(0.2)
    return False, latest


def _stop_submitted_monitor_launchctl_job(
    *, host: str, port: int, expected_installation_root: str
) -> tuple[str | None, str | None]:
    if sys.platform != "darwin" or host not in {"127.0.0.1", "localhost", "::1"}:
        return None, None
    launchctl = shutil.which("launchctl")
    if not launchctl:
        return None, None
    service = f"gui/{os.getuid()}/com.agent-context-engine.monitor-{port}"
    try:
        inspection = subprocess.run(
            [launchctl, "print", service],
            text=True,
            capture_output=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None
    if inspection.returncode != 0:
        return None, None
    ownership_evidence = inspection.stdout or ""
    if (
        expected_installation_root not in ownership_evidence
        or "monitor" not in ownership_evidence
        or str(port) not in ownership_evidence
    ):
        return None, f"submitted monitor job {service} exists but its ownership could not be verified"
    try:
        stopped = subprocess.run(
            [launchctl, "bootout", service],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not unload submitted monitor job {service}: {exc}"
    if stopped.returncode != 0:
        detail = (stopped.stderr or stopped.stdout).strip() or f"exit {stopped.returncode}"
        return None, f"could not unload submitted monitor job {service}: {detail}"
    return f"unloaded submitted monitor job {service}", None


def _stop_windows_monitor_task(
    *,
    port: int,
    expected_installation_root: str,
    memory_root: Path,
) -> tuple[str | None, str | None]:
    if os.name != "nt":
        return None, None
    scheduler_bin = shutil.which("schtasks")
    if not scheduler_bin:
        scheduler_bin = str(Path(os.environ.get("SystemRoot", r"C:\\Windows")) / "System32" / "schtasks.exe")
    if not os.path.exists(scheduler_bin):
        return None, None
    task_name = _windows_monitor_task_name(Path(expected_installation_root))
    script_path = _windows_monitor_start_script_path(Path(expected_installation_root), memory_root)
    try:
        query = subprocess.run(
            [scheduler_bin, "/Query", "/TN", task_name, "/XML"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not inspect Windows monitor task {task_name}: {exc}"
    if query.returncode != 0:
        return None, None
    script_text = ""
    try:
        script_text = script_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    ownership_evidence = query.stdout or ""
    if str(script_path) not in ownership_evidence or expected_installation_root not in script_text or str(port) not in script_text:
        return None, f"Windows monitor task {task_name} exists but its ownership could not be verified"
    try:
        subprocess.run(
            [scheduler_bin, "/End", "/TN", task_name],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        deleted = subprocess.run(
            [scheduler_bin, "/Delete", "/TN", task_name, "/F"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"could not stop Windows monitor task {task_name}: {exc}"
    if deleted.returncode != 0:
        detail = (deleted.stderr or deleted.stdout or "").strip()
        return None, f"could not delete Windows monitor task {task_name}: {detail or deleted.returncode}"
    return f"ended and removed Windows monitor task {task_name}", None


def _stop_owned_monitor_launcher(
    *,
    host: str,
    port: int,
    expected_installation_root: str,
    memory_root: Path,
) -> tuple[str | None, str | None]:
    if os.name == "nt":
        return _stop_windows_monitor_task(
            port=port,
            expected_installation_root=expected_installation_root,
            memory_root=memory_root,
        )
    return _stop_submitted_monitor_launchctl_job(
        host=host,
        port=port,
        expected_installation_root=expected_installation_root,
    )


def _request_monitor_shutdown(*, host: str, port: int, token: str) -> tuple[str | None, str | None]:
    probe_host = _local_monitor_probe_host(host)
    if probe_host is None or not token:
        return None, None
    url_host = f"[{probe_host}]" if ":" in probe_host else probe_host
    request = Request(
        f"http://{url_host}:{port}/api/runtime/shutdown",
        data=b"{}",
        headers={
            "content-type": "application/json",
            "x-agent-context-engine-monitor-token": token,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=2.0) as response:
            if int(getattr(response, "status", 0) or response.getcode()) != 202:
                return None, f"monitor shutdown at {host}:{port} returned HTTP {response.status}"
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        return None, f"monitor shutdown request failed at {host}:{port}: {exc}"
    return f"requested authenticated shutdown for superseded monitor at {host}:{port}", None


def _candidate_monitor_identity(candidate: dict[str, object]) -> tuple[str, int, str] | None:
    host = str(candidate.get("host") or "").strip()
    expected_root = str(candidate.get("installation_root") or "").strip()
    try:
        port = int(candidate.get("port") or 0)
    except (TypeError, ValueError):
        return None
    if not host or port <= 0 or not expected_root or _local_monitor_probe_host(host) is None:
        return None
    return host, port, expected_root


def _verify_superseded_monitors_stay_stopped(
    *,
    candidates: list[dict[str, object]],
    target: Path,
    memory_root: Path,
    desired_host: str | None = None,
    desired_port: int | None = None,
    stability_seconds: float = 8.0,
    poll_seconds: float = 0.25,
) -> list[str]:
    if not candidates:
        return []
    expected_target = str(target.resolve())
    expected_memory_root = str(memory_root.resolve())
    deadline = time.monotonic() + max(0.1, stability_seconds)
    while time.monotonic() < deadline:
        for candidate in candidates:
            identity = _candidate_monitor_identity(candidate)
            if identity is None:
                continue
            host, port, expected_old_root = identity
            payload = _monitor_status_payload(host, port)
            if not payload:
                continue
            observed_root = str(payload.get("root") or payload.get("install_root") or "").strip()
            observed_memory_root = str(payload.get("memory_root") or "").strip()
            if (
                host == desired_host
                and port == desired_port
                and observed_root == expected_target
                and observed_memory_root == expected_memory_root
            ):
                continue
            if observed_root == expected_old_root and observed_memory_root == expected_memory_root:
                return [f"superseded monitor reappeared at {host}:{port} root={observed_root}"]
            return [
                f"unexpected listener at {host}:{port} root={observed_root or '-'} "
                f"memory_root={observed_memory_root or '-'}"
            ]
        time.sleep(max(0.01, poll_seconds))
    return []


def _wait_for_superseded_monitors_to_stop(
    *,
    candidates: list[dict[str, object]],
    memory_root: Path,
    timeout: float = 5.0,
    poll_seconds: float = 0.2,
) -> list[str]:
    expected_memory_root = str(memory_root.resolve())
    pending = list(candidates)
    deadline = time.monotonic() + max(0.1, timeout)
    while pending and time.monotonic() < deadline:
        remaining: list[dict[str, object]] = []
        for candidate in pending:
            identity = _candidate_monitor_identity(candidate)
            if identity is None:
                continue
            host, port, expected_root = identity
            payload = _monitor_status_payload(host, port)
            if not payload:
                continue
            observed_root = str(payload.get("root") or payload.get("install_root") or "").strip()
            observed_memory_root = str(payload.get("memory_root") or "").strip()
            if observed_root != expected_root or observed_memory_root != expected_memory_root:
                return [
                    f"unexpected listener while stopping {host}:{port} root={observed_root or '-'} "
                    f"memory_root={observed_memory_root or '-'}"
                ]
            remaining.append(candidate)
        pending = remaining
        if pending:
            time.sleep(max(0.01, poll_seconds))
    return [
        f"superseded monitor did not stop at {host}:{port} root={expected_root}"
        for candidate in pending
        if (identity := _candidate_monitor_identity(candidate)) is not None
        for host, port, expected_root in (identity,)
    ]


def _stop_superseded_monitors_for_memory_root(
    *,
    target: Path,
    memory_root: Path,
    candidates: list[dict[str, object]] | None = None,
) -> tuple[list[str], list[str]]:
    normalized_memory_root = str(memory_root.resolve())
    candidates = candidates if candidates is not None else _superseded_monitor_candidates(
        target=target,
        memory_root=memory_root,
    )
    actions: list[str] = []
    failures: list[str] = []
    active_candidates: list[dict[str, object]] = []
    for candidate in candidates:
        identity = _candidate_monitor_identity(candidate)
        if identity is None:
            actions.append(f"skipped invalid superseded monitor candidate: {candidate!r}")
            continue
        host, port, expected_root = identity
        payload = _monitor_status_payload(host, port)
        if not payload:
            failures.append(
                f"registered superseded monitor at {host}:{port} root={expected_root} is unreachable; "
                "takeover refused until its launcher is stopped or the monitor responds"
            )
            continue
        observed_root = str(payload.get("root") or payload.get("install_root") or "").strip()
        observed_memory_root = str(payload.get("memory_root") or "").strip()
        if observed_root != expected_root or observed_memory_root != normalized_memory_root:
            failures.append(
                f"monitor identity mismatch at {host}:{port} root={observed_root or '-'} "
                f"memory_root={observed_memory_root or '-'}"
            )
            continue
        active_candidates.append(candidate)
        owner_action, owner_failure = _stop_owned_monitor_launcher(
            host=host,
            port=port,
            expected_installation_root=expected_root,
            memory_root=memory_root,
        )
        if owner_failure:
            failures.append(owner_failure)
        elif owner_action:
            actions.append(owner_action)
        else:
            shutdown_action, shutdown_failure = _request_monitor_shutdown(
                host=host,
                port=port,
                token=str(candidate.get("shutdown_token") or ""),
            )
            if shutdown_failure:
                failures.append(shutdown_failure)
            elif shutdown_action:
                actions.append(shutdown_action)
            else:
                failures.append(
                    f"refused to terminate unmanaged superseded monitor at {host}:{port} root={expected_root}; "
                    "stop it explicitly and rerun installation"
                )
    if failures:
        return actions, failures
    failures.extend(
        _wait_for_superseded_monitors_to_stop(
            candidates=active_candidates,
            memory_root=memory_root,
        )
    )
    if failures:
        return actions, failures
    failures.extend(
        _verify_superseded_monitors_stay_stopped(
            candidates=active_candidates,
            target=target,
            memory_root=memory_root,
        )
    )
    return actions, failures


def _stop_superseded_launchagents_for_memory_root(*, target: Path, memory_root: Path) -> list[str]:
    from ....application.scheduler_installation import stop_superseded_platform_schedulers

    return stop_superseded_platform_schedulers(target=target, memory_root=memory_root)


def _windows_monitor_task_name(target: Path) -> str:
    resolved = str(target.expanduser().resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:12]
    return f"AgentContextEngine\\Monitor-{safe_slug(target.name)}-{digest}"


def _windows_monitor_start_script_path(target: Path, memory_root: Path) -> Path:
    task_slug = _windows_monitor_task_name(target).split("\\", 1)[-1]
    return memory_root / "local" / f"windows-monitor-start-{task_slug}.cmd"


def _write_windows_monitor_start_script(target: Path, command: list[str], memory_root: Path) -> Path:
    script_path = _windows_monitor_start_script_path(target, memory_root)
    log_dir = memory_root / "logs"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout = log_dir / "monitor-windows-task.out.log"
    stderr = log_dir / "monitor-windows-task.err.log"
    script_path.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                f"cd /d \"{target}\"",
                f"set {ROOT_ENV_VAR}={target}",
                f"set {STORAGE_ROOT_ENV_VAR}={memory_root}",
                f"{subprocess.list2cmdline(command)} >> \"{stdout}\" 2>> \"{stderr}\"",
                "exit /b %ERRORLEVEL%",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return script_path


def _autostart_monitor_via_windows_task(
    target: Path,
    *,
    command: list[str],
    host: str,
    port: int,
    memory_root: Path,
) -> tuple[bool, str]:
    scheduler_bin = shutil.which("schtasks")
    if not scheduler_bin:
        scheduler_bin = str(Path(os.environ.get("SystemRoot", r"C:\\Windows")) / "System32" / "schtasks.exe")
    if not os.path.exists(scheduler_bin):
        return False, "Windows Task Scheduler command `schtasks` is unavailable"
    script_path = _write_windows_monitor_start_script(target, command, memory_root)
    task_name = _windows_monitor_task_name(target)
    start_time = (datetime.now() + timedelta(minutes=1)).strftime("%H:%M")
    create = subprocess.run(
        [
            scheduler_bin,
            "/Create",
            "/TN",
            task_name,
            "/SC",
            "ONCE",
            "/ST",
            start_time,
            "/RL",
            "LIMITED",
            "/TR",
            f'"{script_path}"',
            "/F",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if create.returncode != 0:
        detail = (create.stderr or create.stdout).strip() or f"schtasks create exit {create.returncode}"
        return False, f"Windows Task Scheduler monitor task create failed: {detail}"
    run = subprocess.run([scheduler_bin, "/Run", "/TN", task_name], text=True, capture_output=True, check=False)
    if run.returncode != 0:
        detail = (run.stderr or run.stdout).strip() or f"schtasks run exit {run.returncode}"
        return False, f"Windows Task Scheduler monitor task run failed: {detail}"
    ready, payload = _wait_for_monitor_identity(
        target=target,
        memory_root=memory_root,
        host=host,
        port=port,
        timeout=20.0,
    )
    if ready:
        return True, f"launched and identity-verified via Windows Task Scheduler task={task_name} script={script_path}"
    observed_root = str((payload or {}).get("root") or (payload or {}).get("install_root") or "-")
    cleanup_action, cleanup_failure = _stop_windows_monitor_task(
        port=port,
        expected_installation_root=str(target.resolve()),
        memory_root=memory_root,
    )
    cleanup_detail = cleanup_action or cleanup_failure or "task cleanup not required"
    return False, (
        f"Windows Task Scheduler monitor task did not expose the expected identity at {host}:{port} "
        f"observed_root={observed_root} task={task_name} script={script_path}; {cleanup_detail}"
    )


def _rollback_spawned_monitor(
    process: subprocess.Popen[str],
    *,
    target: Path,
    memory_root: Path,
    host: str,
    port: int,
) -> tuple[bool, str]:
    stop_error = ""
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=5)
            except (OSError, subprocess.SubprocessError) as exc:
                stop_error = f"could not force-stop new monitor pid={process.pid}: {exc}"
        except (OSError, subprocess.SubprocessError) as exc:
            stop_error = f"could not stop new monitor pid={process.pid}: {exc}"
    payload = _monitor_status_payload(host, port)
    observed_root = str((payload or {}).get("root") or (payload or {}).get("install_root") or "").strip()
    observed_memory_root = str((payload or {}).get("memory_root") or "").strip()
    if observed_root == str(target.resolve()) and observed_memory_root == str(memory_root.resolve()):
        return False, f"new monitor identity still responds after rollback pid={process.pid}"
    if process.poll() is None:
        detail = stop_error or f"new monitor child did not report exit after rollback pid={process.pid}"
        return False, detail + "; monitor identity no longer responds"
    return True, f"rolled back new monitor pid={process.pid}"


def _autostart_monitor_after_install(
    target: Path,
    *,
    runner: str,
    host: str,
    port: int,
    language: str,
    memory_root: Path,
) -> tuple[bool, str]:
    superseded_candidates = _superseded_monitor_candidates(target=target, memory_root=memory_root)
    stop_actions, stop_failures = _stop_superseded_monitors_for_memory_root(
        target=target,
        memory_root=memory_root,
        candidates=superseded_candidates,
    )
    if stop_failures:
        detail = "superseded monitor takeover refused: " + "; ".join(stop_failures)
        if stop_actions:
            detail += " superseded_monitors=" + "; ".join(stop_actions)
        return False, detail
    command = _monitor_start_command(target, runner=runner, host=host, port=port, language=language)
    env = {**os.environ, ROOT_ENV_VAR: str(target), STORAGE_ROOT_ENV_VAR: str(memory_root)}
    if os.name == "nt":
        task_started, task_detail = _autostart_monitor_via_windows_task(
            target,
            command=command,
            host=host,
            port=port,
            memory_root=memory_root,
        )
        if task_started:
            cleanup_failures = _verify_superseded_monitors_stay_stopped(
                candidates=superseded_candidates,
                target=target,
                memory_root=memory_root,
                desired_host=host,
                desired_port=port,
            )
            if cleanup_failures:
                cleanup_action, cleanup_failure = _stop_windows_monitor_task(
                    port=port,
                    expected_installation_root=str(target.resolve()),
                    memory_root=memory_root,
                )
                rollback_detail = cleanup_action or cleanup_failure or "Windows monitor task rollback unavailable"
                return False, (
                    "monitor started, but superseded monitor cleanup could not be verified: "
                    + "; ".join(cleanup_failures)
                    + f"; {rollback_detail}"
                )
            detail = task_detail
            if stop_actions:
                detail += " superseded_monitors=" + "; ".join(stop_actions)
            return True, detail
        detail = f"windows monitor identity not verified; {task_detail}"
        if stop_actions:
            detail += " superseded_monitors=" + "; ".join(stop_actions)
        return False, detail
    process = subprocess.Popen(
        command,
        cwd=str(target),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
        close_fds=True,
    )
    time.sleep(0.4)
    if process.poll() is not None:
        detail = f"exit {process.returncode}"
        if stop_actions:
            detail += " superseded_monitors=" + "; ".join(stop_actions)
        return False, detail
    ready, status_payload = _wait_for_monitor_identity(
        target=target,
        memory_root=memory_root,
        host=host,
        port=port,
    )
    if not ready:
        _rolled_back, rollback_detail = _rollback_spawned_monitor(
            process,
            target=target,
            memory_root=memory_root,
            host=host,
            port=port,
        )
        observed_root = str((status_payload or {}).get("root") or (status_payload or {}).get("install_root") or "-")
        detail = (
            f"monitor did not expose the expected identity at {host}:{port}; "
            f"observed_root={observed_root}; {rollback_detail}"
        )
        if stop_actions:
            detail += " superseded_monitors=" + "; ".join(stop_actions)
        return False, detail
    cleanup_failures = _verify_superseded_monitors_stay_stopped(
        candidates=superseded_candidates,
        target=target,
        memory_root=memory_root,
        desired_host=host,
        desired_port=port,
    )
    if cleanup_failures:
        _rolled_back, rollback_detail = _rollback_spawned_monitor(
            process,
            target=target,
            memory_root=memory_root,
            host=host,
            port=port,
        )
        detail = "monitor started, but superseded monitor cleanup could not be verified: " + "; ".join(cleanup_failures)
        detail += f"; {rollback_detail}"
        if stop_actions:
            detail += " superseded_monitors=" + "; ".join(stop_actions)
        return False, detail
    monitor_process = status_payload.get("monitor_process") if isinstance(status_payload, dict) and isinstance(status_payload.get("monitor_process"), dict) else {}
    monitor_pid = int(monitor_process.get("pid") or process.pid)
    detail = f"pid={monitor_pid} identity=verified takeover=verified command={monitor_restart_command(target, runner=runner)}"
    if stop_actions:
        detail += " superseded_monitors=" + "; ".join(stop_actions)
    return True, detail


def cmd_install_discovery(args: argparse.Namespace) -> int:
    start = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else Path.cwd()
    summary = _discovery_summary(
        start=start,
        target_hint=Path(args.target).expanduser().resolve() if getattr(args, "target", None) else None,
        memory_root_hint=getattr(args, "memory_root", None),
        language_hint=getattr(args, "language", None),
    )
    if getattr(args, "isolated", False):
        summary = _apply_isolated_discovery_overrides(summary)
    plan = _guided_install_plan(summary, args)
    if getattr(args, "plan_json", None):
        plan_path = Path(str(args.plan_json)).expanduser().resolve()
        try:
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            if not getattr(args, "json", False):
                print(f"wrote install plan to {plan_path}")
        except (OSError, ValueError) as exc:
            print(f"error: could not write install plan to {plan_path}: {exc}", file=sys.stderr)
            return 1
    if getattr(args, "json", False):
        print(json.dumps({**summary, "install_plan": plan}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(_render_install_discovery(summary))
    print("")
    if getattr(args, "plan_json", None):
        apply_plan_command = (
            f"{_command_script_for_root(Path(str(summary['checkout_root'])))} install --plan-json "
            f"{_quote_platform_path(Path(str(args.plan_json)).expanduser().resolve())}"
        )
        print(_ui_text(summary["reply_language"], en="recommended command from plan:", de="empfohlener Befehl aus Plan:"))
        print(apply_plan_command)
    else:
        print(
            _ui_text(
                summary["reply_language"],
                en=(
                    "Agent-driven handoff: rerun discovery with `--plan-json <file>` before requesting approval, "
                    "then execute that unchanged plan file."
                ),
                de=(
                    "Agentengesteuerte Uebergabe: Discovery vor der Freigabe mit `--plan-json <datei>` wiederholen "
                    "und danach genau diese unveraenderte Plan-Datei ausfuehren."
                ),
            )
        )
        print(_ui_text(summary["reply_language"], en="recommended command:", de="empfohlener Befehl:"))
        print(_recommended_install_command(summary))
    return 0


def agents_memory_block(language: str, *, command_prefix: str = "./scripts/agent-context-engine") -> str:
    from ....application.agent_flow import build_agent_flow_contract
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_instruction_renderer

    contract = build_agent_flow_contract(preferred_language=language, command_prefix=command_prefix)
    return select_instruction_renderer(current_platform_profile()).render_agents_quick_path(contract)


HOOK_SESSION_ENTRY_NOTE = """## Hook Session Entry

- Hook-based runtime sessions are expected to load `session-start-hook-entry.md` first.
- That file contains the operational Agent Context Engine workflow and the available context-loading commands.
- Keep `AGENTS.md` as the canonical source for project rules, installation/bootstrap guidance, and repository-level operating constraints.
"""


REPOS_HEADER = """# Repository Index

Agent Context Engine uses this optional index to map working directories to project names.

## Projects
"""


CLAUDE_ENTRYPOINT = """# Claude Entry Point

Follow `AGENTS.md` in this directory as the canonical project instructions.

Do not duplicate or reinterpret the project rules here. When instructions need to change, update `AGENTS.md`.

Important startup behavior:

- Read `AGENTS.md` first.
- Use the Agent Context Engine quick path from `AGENTS.md` for earlier sessions, handovers, project context, and "what happened last" questions.
- Keep startup context small; load deeper docs only when the concrete task needs them.
"""


CURSOR_EVERY_CHAT_RULE = """---
description: Canonical project entrypoint for every Cursor chat
globs:
  - "**/*"
alwaysApply: true
---

# Project Instructions

`AGENTS.md` in this directory is the canonical instruction file for this project.

Cursor must use `AGENTS.md` as the source of truth for:

- local Git rules
- safety rules for file operations
- Agent Context Engine lookup workflow
- linked workflow references
- commit behavior

Do not duplicate those rules here. If project instructions need to change, update `AGENTS.md`.

At the start of a chat, read `AGENTS.md` before loading deeper project context.
"""


def session_start_hook_entry_path(target: Path) -> Path:
    return target / "session-start-hook-entry.md"


def render_session_start_hook_entry(target: Path, *, command_prefix: str, language: str, memory_root: Path | None = None) -> str:
    from ....application.agent_flow import build_agent_flow_contract
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_instruction_renderer

    resolved_memory_root = (memory_root or target).resolve()
    monitor_runner = str(
        load_installation_profile(resolved_memory_root).get("workflows", {}).get("monitor_runner") or WORKFLOW_RUNNER_DEFAULTS["monitor_runner"]
    ).strip()
    contract = build_agent_flow_contract(
        preferred_language=language,
        command_prefix=command_prefix,
        repo_context_path="memory/knowledge/repos.md",
        monitor_runner=monitor_runner,
    )
    return select_instruction_renderer(current_platform_profile()).render_session_start_hook_entry(contract)


def render_claude_entrypoint() -> str:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_instruction_renderer

    return select_instruction_renderer(current_platform_profile()).render_claude_entrypoint()


def render_cursor_every_chat_rule() -> str:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_instruction_renderer

    return select_instruction_renderer(current_platform_profile()).render_cursor_every_chat_rule()


def ensure_session_start_hook_entry(target: Path, *, command_prefix: str, language: str, memory_root: Path | None = None) -> Path:
    path = session_start_hook_entry_path(target)
    path.write_text(
        render_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=memory_root),
        encoding="utf-8",
    )
    return path


def ensure_agents_memory_block(target: Path, *, language: str, command_prefix: str = "./scripts/agent-context-engine") -> Path:
    target.mkdir(parents=True, exist_ok=True)
    path = target / "AGENTS.md"
    block = agents_memory_block(language, command_prefix=command_prefix)
    hook_note = HOOK_SESSION_ENTRY_NOTE
    if path.exists():
        text = path.read_text(encoding="utf-8")
        updated = text
        quick_path_re = re.compile(r"(?ms)^## Agent (?:Memory|Context Engine) Quick Path\n.*?(?=^## |\Z)")
        hook_note_re = re.compile(r"(?ms)^## Hook Session Entry\n.*?(?=^## |\Z)")
        if quick_path_re.search(updated):
            updated = quick_path_re.sub(block.rstrip() + "\n\n", updated, count=1)
        elif "## Agent Memory Schnellpfad" in text:
            updated = re.sub(r"(?ms)^## Agent Memory Schnellpfad\n.*?(?=^## |\Z)", block.rstrip() + "\n\n", updated, count=1)
        else:
            suffix = "" if updated.endswith("\n") else "\n"
            updated = updated + suffix + "\n" + block
        if hook_note_re.search(updated):
            updated = hook_note_re.sub(hook_note.rstrip() + "\n\n", updated, count=1)
        else:
            suffix = "" if updated.endswith("\n") else "\n"
            updated = updated + suffix + "\n" + hook_note
        if updated != text:
            path.write_text(updated, encoding="utf-8")
        return path
    path.write_text("# Agent Instructions\n\n" + block + "\n\n" + hook_note, encoding="utf-8")
    return path


def ensure_harness_entrypoints(target: Path) -> list[Path]:
    written: list[Path] = []
    claude_path = target / "CLAUDE.md"
    claude_entrypoint = render_claude_entrypoint()
    if not claude_path.exists() or "AGENTS.md" not in claude_path.read_text(encoding="utf-8", errors="replace"):
        claude_path.write_text(claude_entrypoint, encoding="utf-8")
        written.append(claude_path)
    cursor_rule = target / ".cursor" / "rules" / "everyChat.mdc"
    cursor_entrypoint = render_cursor_every_chat_rule()
    if not cursor_rule.exists() or "AGENTS.md" not in cursor_rule.read_text(encoding="utf-8", errors="replace"):
        cursor_rule.parent.mkdir(parents=True, exist_ok=True)
        cursor_rule.write_text(cursor_entrypoint, encoding="utf-8")
        written.append(cursor_rule)
    return written


def file_url(path: Path) -> str:
    return "file://" + quote(str(path.expanduser().resolve()), safe="/:")


def project_spec_entry(spec: str) -> tuple[str, Path]:
    text = spec.strip()
    if not text:
        raise ValueError("empty project spec")
    if "=" in text:
        name, path_text = text.split("=", 1)
    elif ":" in text:
        name, path_text = text.split(":", 1)
    else:
        path_text = text
        name = Path(path_text).expanduser().name
    name = name.strip() or Path(path_text).expanduser().name
    path = Path(path_text.strip()).expanduser().resolve()
    return name, path


def render_repos_index(entries: list[tuple[str, Path]]) -> str:
    lines = [REPOS_HEADER.rstrip(), ""]
    if not entries:
        lines.extend(
            [
                "### `example-project`",
                "",
                "- Path: [example-project](file:///path/to/example-project)",
                "- Entry point: `README.md`",
                "- Note: Replace this placeholder with the project purpose.",
                "",
            ]
        )
    for name, path in entries:
        lines.extend(
            [
                f"### `{name}`",
                "",
                f"- Path: [{name}]({file_url(path)})",
                "- Entry point: `README.md`",
                "- Note: TODO",
                "",
            ]
        )
    return "\n".join(lines)


def _repo_index_entries_from_text(text: str) -> list[str]:
    entries: list[str] = []
    current_name = ""
    for raw_line in text.splitlines():
        heading = re.match(r"^### `([^`]+)`", raw_line)
        if heading:
            current_name = heading.group(1).strip()
            if current_name and current_name != "example-project":
                entries.append(current_name)
    return entries


def _repo_index_discovery_status(*, checkout_root: Path, memory_root: Path) -> dict[str, object]:
    runtime_path = memory_root / "knowledge" / "repos.md"
    legacy_path = legacy_repos_index_path(checkout_root)
    source = "missing"
    path = runtime_path
    text = ""
    if runtime_path.exists():
        source = "runtime"
        path = runtime_path
        text = runtime_path.read_text(encoding="utf-8", errors="replace")
    elif legacy_path.exists():
        source = "legacy"
        path = legacy_path
        text = legacy_path.read_text(encoding="utf-8", errors="replace")
    entries = _repo_index_entries_from_text(text)
    return {
        "source": source,
        "path": str(path),
        "entry_count": len(entries),
        "entries": entries[:8],
    }


def ask_project_entries(*, language: str = "en") -> list[tuple[str, Path]]:
    if not sys.stdin.isatty():
        return []
    print("")
    print(_ui_text(language, en="Initial repo index", de="Initialer Repo-Index"))
    print(
        _ui_text(
            language,
            en="Add repos or folders Agent Context Engine should recognize. Press Enter on an empty name to finish. You can review and edit them later in the monitor under Personal -> Repo-Index.",
            de="Fuege Repos oder Ordner hinzu, die Agent Context Engine erkennen soll. Leerer Name beendet die Eingabe. Spaeter kannst du sie im Monitor unter Persoenlich -> Repo-Index ansehen und bearbeiten.",
        )
    )
    entries: list[tuple[str, Path]] = []
    while True:
        name = input(_ui_text(language, en="Project name: ", de="Projektname: ")).strip()
        if not name:
            break
        path_text = input(_ui_text(language, en="Project path: ", de="Projektpfad: ")).strip()
        if not path_text:
            print(_ui_text(language, en="Skipped: missing path.", de="Uebersprungen: Pfad fehlt."))
            continue
        entries.append((name, Path(path_text).expanduser().resolve()))
    return entries


def ensure_repos_runtime_index(target: Path, project_specs: list[str], *, interactive: bool, language: str = "en") -> Path:
    repos_index = ensure_runtime_repos_index(target)
    if repos_index.exists():
        return repos_index
    entries: list[tuple[str, Path]] = []
    for spec in project_specs:
        entries.append(project_spec_entry(spec))
    if interactive and not entries:
        entries = ask_project_entries(language=language)
    return write_repos_index_text(render_repos_index(entries), target)


def _workspace_roots(values: list[str] | None) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()
    for value in values or []:
        path = Path(value).expanduser().resolve()
        if path in seen:
            continue
        seen.add(path)
        roots.append(path)
    return roots


def _workflow_choices(key: str) -> tuple[str, ...]:
    return WORKFLOW_RUNNER_CHOICES + tuple(WORKFLOW_RUNNER_SPECIALS.get(key, ()))


def _normalize_workflow_runner(key: str, value: str | None) -> str:
    default = WORKFLOW_RUNNER_DEFAULTS[key]
    normalized = str(value or default).strip().lower()
    if normalized in _workflow_choices(key):
        return normalized
    raise ValueError(f"unsupported {key}: {value!r}; expected one of {', '.join(_workflow_choices(key))}")


def ask_workflow_runner(key: str, default: str, *, language: str = "en") -> str:
    if not sys.stdin.isatty():
        return default
    label = WORKFLOW_LABELS.get(key, key)
    choices = "/".join(_workflow_choices(key))
    print("")
    print(label)
    print(
        _ui_text(
            language,
            en=f"Choose the runner Agent Context Engine should depend on for this workflow. Options: {choices}",
            de=f"Waehle den Runner, von dem Agent Context Engine fuer diesen Workflow abhaengen soll. Optionen: {choices}",
        )
    )
    answer = input(
        _ui_text(
            language,
            en=f"{key} [{choices}] (default: {default}): ",
            de=f"{key} [{choices}] (Standard: {default}): ",
        )
    ).strip()
    return _normalize_workflow_runner(key, answer or default)


def _workflow_runner_overrides(args: argparse.Namespace) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for key in WORKFLOW_RUNNER_DEFAULTS:
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = _normalize_workflow_runner(key, value)
    return overrides


def _workspace_root_overrides(args: argparse.Namespace) -> dict[str, list[Path]]:
    return {
        "codex": _workspace_roots(getattr(args, "codex_workspace_root", None)),
        "claude": _workspace_roots(getattr(args, "claude_workspace_root", None)),
        "cursor": _workspace_roots(getattr(args, "cursor_workspace_root", None)),
    }


def _resolved_installation_profile(root: Path, args: argparse.Namespace) -> dict[str, object]:
    profile = load_installation_profile(root)
    workflows = dict(profile.get("workflows") or {})
    for key, value in _workflow_runner_overrides(args).items():
        workflows[key] = value
    workspace_roots = dict(profile.get("workspace_roots") or {})
    for client, paths in _workspace_root_overrides(args).items():
        if paths:
            workspace_roots[client] = [str(path.resolve()) for path in paths]
    storage = dict(profile.get("storage") or {})
    memory_root_arg = getattr(args, "memory_root", None)
    if memory_root_arg:
        storage["memory_root"] = str(Path(str(memory_root_arg)).expanduser().resolve())
    return {
        **profile,
        "workflows": workflows,
        "workspace_roots": workspace_roots,
        "storage": storage,
    }


def _workspace_hook_status(client: str, workspace_root: Path) -> dict[str, object]:
    summary = integration_summary(root=workspace_root, probe_gemini=False)
    return next((item for item in summary["items"] if item.get("client") == client), {})


def _port_conflict_status(host: str, port: int) -> dict[str, object]:
    probe_host = host.strip() or DEFAULT_MONITOR_HOST
    connect_host = "127.0.0.1" if probe_host in {"0.0.0.0", "::", "::1", "localhost"} else probe_host
    connect_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        connect_probe.settimeout(0.2)
        if connect_probe.connect_ex((connect_host, port)) == 0:
            return {"available": False, "error": f"port already accepting connections on {connect_host}:{port}"}
    except OSError:
        pass
    finally:
        try:
            connect_probe.close()
        except OSError:
            pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.bind((probe_host, port))
    except OSError as exc:
        return {"available": False, "error": str(exc)}
    finally:
        try:
            probe.close()
        except OSError:
            pass
    return {"available": True, "error": ""}


def _configured_monitor_port_status(*, root: Path, host: str, port: int) -> dict[str, object]:
    normalized_root = str(root.expanduser().resolve())
    active = False
    for entry in active_monitor_runtime_entries():
        if not isinstance(entry, dict):
            continue
        try:
            entry_port = int(entry.get("active_port") or entry.get("configured_port") or 0)
        except (TypeError, ValueError):
            continue
        entry_host = str(
            entry.get("active_host") or entry.get("configured_host") or DEFAULT_MONITOR_HOST
        ).strip()
        if (
            str(entry.get("installation_root") or "").strip() == normalized_root
            and entry_host == host
            and entry_port == port
        ):
            active = True
            break
    if active:
        return {"available": False, "active": True, "status": "active", "error": ""}
    port_status = _port_conflict_status(host, port)
    available = bool(port_status.get("available"))
    return {
        "available": available,
        "active": False,
        "status": "available" if available else "conflict",
        "error": str(port_status.get("error") or ""),
    }


def _port_accepting(host: str, port: int) -> bool:
    return not bool(_port_conflict_status(host, port).get("available"))


def _default_storage_root_for_install(target: Path, args: argparse.Namespace) -> Path:
    memory_root_arg = getattr(args, "memory_root", None)
    if memory_root_arg:
        return Path(str(memory_root_arg)).expanduser().resolve()
    return _default_home_memory_root()


def _default_launchagent_env_file_for_storage(memory_root: Path) -> str:
    return str((memory_root / "local" / "agent-context-engine.env").resolve())


def _legacy_launchagent_env_file_specs() -> set[str]:
    return {
        DEFAULT_ENV_FILE,
        "memory/local/agent-memory.env",
        "memory/local/agent-context-engine.env",
    }


def _expected_launchagent_plist_path(label: str) -> str:
    return default_launchagent_profile(label=label)["path"]


def _default_instance_id_for_target(target: Path, args: argparse.Namespace) -> str:
    if getattr(args, "instance_name", None):
        return safe_slug(str(args.instance_name))
    resolved = target.expanduser().resolve()
    default_install = default_instance_install_root()
    if resolved == default_install:
        return "default"
    if resolved.name == "install" and resolved.parent.parent.name == "instances":
        return safe_slug(resolved.parent.name)
    return target.name


def _existing_parent(path: Path) -> Path | None:
    current = path
    while True:
        if current.exists():
            return current
        if current.parent == current:
            return None
        current = current.parent


def _relocate_runtime_storage(old_memory_root: Path, new_memory_root: Path) -> list[str]:
    if old_memory_root.resolve() == new_memory_root.resolve():
        return []
    if not old_memory_root.exists():
        return []
    actions: list[str] = []
    new_memory_root.parent.mkdir(parents=True, exist_ok=True)
    if not new_memory_root.exists():
        shutil.copytree(old_memory_root, new_memory_root)
        shutil.rmtree(old_memory_root)
        return [
            f"copied runtime storage from {old_memory_root} to {new_memory_root}",
            f"removed previous runtime storage root {old_memory_root}",
        ]
    for child in sorted(old_memory_root.iterdir(), key=lambda item: item.name):
        destination = new_memory_root / child.name
        if destination.exists():
            if child.is_dir() and destination.is_dir():
                shutil.copytree(child, destination, dirs_exist_ok=True)
                shutil.rmtree(child)
                actions.append(f"merged runtime storage directory {child} into {destination}")
                continue
            actions.append(f"kept existing destination {destination}; left source in place {child}")
            continue
        shutil.move(str(child), str(destination))
        actions.append(f"moved runtime storage entry {child} to {destination}")
    try:
        old_memory_root.rmdir()
        actions.append(f"removed previous runtime storage root {old_memory_root}")
    except OSError:
        pass
    return actions


def _should_rewrite_launchagent_env_file(current_env_file: str, *, old_memory_root: Path) -> bool:
    text = str(current_env_file or "").strip()
    if not text or text in _legacy_launchagent_env_file_specs():
        return True
    try:
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            return False
        return candidate.resolve() in {
            (old_memory_root / "local" / "agent-memory.env").resolve(),
            (old_memory_root / "local" / "agent-context-engine.env").resolve(),
        }
    except OSError:
        return False


def _storage_status(*, root: Path, profile: dict[str, object]) -> dict[str, object]:
    storage = dict(profile.get("storage") or {})
    memory_root_text = str(storage.get("memory_root") or (root / "memory")).strip() or str((root / "memory").resolve())
    memory_root = Path(memory_root_text).expanduser()
    if not memory_root.is_absolute():
        memory_root = (root / memory_root).resolve()
    try:
        schema_version = max(1, int(storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION))
    except (TypeError, ValueError):
        schema_version = DEFAULT_STORAGE_SCHEMA_VERSION
    exists = memory_root.exists()
    writable = False
    error = ""
    if exists:
        writable = os.access(memory_root, os.W_OK | os.X_OK)
        if not writable:
            error = "path exists but is not writable"
    else:
        parent = _existing_parent(memory_root.parent)
        if parent is None:
            error = "no existing parent directory found"
        else:
            writable = os.access(parent, os.W_OK | os.X_OK)
            if not writable:
                error = f"parent directory is not writable: {parent}"
    profile_path = storage_profile_path(memory_root)
    storage_profile = load_storage_profile(memory_root)
    return {
        "memory_root": str(memory_root),
        "schema_version": schema_version,
        "exists": exists or memory_root.exists(),
        "writable": writable,
        "error": error,
        "profile_path": str(profile_path),
        "attached_at": str(storage.get("attached_at") or ""),
        "managed_by_installation": bool(storage.get("managed_by_installation", True)),
        "legacy_co_located": str(memory_root) == str((root / "memory").resolve()),
        "storage_instance_id": str(storage_profile.get("storage_instance_id") or ""),
    }


def _workspace_rewrite_requires_confirmation(client: str, workspace_root: Path, memory_root: Path) -> tuple[bool, dict[str, object]]:
    if client not in {"codex", "claude", "gemini"}:
        return False, {}
    status = shell_hook_adapter_status(client, root=workspace_root, memory_root=memory_root)
    return status.get("status") in {"root_mismatch", "script_mismatch", "unmanaged"}, status


def _enable_workspace_hooks(*, client: str, target: Path, memory_root: Path) -> dict[str, object]:
    command_prefix = agent_memory_command_prefix_for_target(target, memory_root)
    language = installation_language_for_target(target=target, memory_root=memory_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=memory_root)
    ensure_harness_entrypoints(target)
    result, target_item = _run_integration_hook_action(client=client, action="enable", target=target, memory_root=memory_root)
    return {
        "result": result,
        "target_item": target_item,
    }


def _metadata_dir_for_runtime_root(runtime_root: Path) -> Path:
    metadata_base = runtime_root.expanduser().resolve()
    if metadata_base.name == "memory" and metadata_base.parent.name == ".agent-context-engine":
        metadata_base = metadata_base.parent.parent
    return metadata_base / ".agent-context-engine"


def _ensure_central_hub_and_active_root(
    installation_root: Path,
    *,
    metadata_root: Path | None = None,
    publish_shared_active_root: bool = False,
) -> list[str]:
    """Write the central active-root file and refresh supported hub scripts.

    This is idempotent and safe to call during both install and repair. The
    caller explicitly decides whether the installation owns the shared home
    active-root or only its installation-specific metadata root.
    """
    from ....application.hook_rendering import build_central_hub_spec, render_central_hub_script

    actions: list[str] = []
    requested_metadata_root = (metadata_root or storage_root()).expanduser().resolve()
    meta_dir = _metadata_dir_for_runtime_root(requested_metadata_root)
    meta_dir.mkdir(parents=True, exist_ok=True)

    active_root = meta_dir / "active-root"
    active_root.write_text(str(installation_root.resolve()) + "\n", encoding="utf-8")
    actions.append(f"updated active-root: {active_root}")

    legacy_nested_active_root = requested_metadata_root / ".agent-context-engine" / "active-root"
    if legacy_nested_active_root != active_root and (
        legacy_nested_active_root.is_file() or legacy_nested_active_root.is_symlink()
    ):
        legacy_nested_active_root.unlink()
        if os.name == "nt":
            legacy_nested_active_root.write_text(str(installation_root.resolve()) + "\n", encoding="utf-8")
            actions.append(f"refreshed legacy nested active-root compatibility file: {legacy_nested_active_root}")
        else:
            legacy_nested_active_root.symlink_to(active_root)
            actions.append(f"linked legacy nested active-root to canonical metadata: {legacy_nested_active_root}")

    if publish_shared_active_root:
        shared_active_root = Path.home().expanduser().resolve() / ".agent-context-engine" / "active-root"
        if shared_active_root.resolve() != active_root.resolve():
            shared_active_root.parent.mkdir(parents=True, exist_ok=True)
            shared_active_root.write_text(str(installation_root.resolve()) + "\n", encoding="utf-8")
            actions.append(f"updated shared active-root: {shared_active_root}")

    for runner in ("codex", "claude", "antigravity", "gemini"):
        hub_path = meta_dir / "hooks" / runner / "hook_adapter.sh"
        hub_path.parent.mkdir(parents=True, exist_ok=True)
        hub_text = render_central_hub_script(build_central_hub_spec(runner))
        hub_path.write_text(hub_text, encoding="utf-8")
        _mark_platform_executable(hub_path)
        actions.append(f"refreshed central hub: {hub_path}")

    return actions


def _write_project_hook_adapter(
    *,
    script_path: Path,
    runner: str,
    installation_root: Path,
    metadata_root: Path,
    hook_renderer: object,
    windows: bool | None = None,
) -> list[Path]:
    use_windows = os.name == "nt" if windows is None else windows
    script_path.parent.mkdir(parents=True, exist_ok=True)
    if use_windows:
        from ....adapters.windows import render_cmd_powershell_launcher
        from ....application.hook_rendering import build_shell_hook_adapter_spec

        if script_path.exists() or script_path.is_symlink():
            script_path.unlink()
        script_text = hook_renderer.render_shell_hook_adapter(
            build_shell_hook_adapter_spec(
                runner,
                agent_context_engine_root=installation_root,
                agent_memory_script=str(
                    (installation_root / agent_memory_script_for_root(installation_root)).resolve()
                ),
            )
        )
        companion_path = script_path.with_suffix(".ps1")
        if companion_path.exists() or companion_path.is_symlink():
            companion_path.unlink()
        companion_path.write_text(script_text, encoding="utf-8")
        script_path.write_text(render_cmd_powershell_launcher(companion_path.name), encoding="utf-8")
        _mark_platform_executable(companion_path)
        _mark_platform_executable(script_path)
        return [companion_path, script_path]

    hub_path = (_metadata_dir_for_runtime_root(metadata_root) / "hooks" / runner / "hook_adapter.sh").resolve()
    if script_path.exists() or script_path.is_symlink():
        script_path.unlink()
    script_path.symlink_to(hub_path)
    _mark_platform_executable(hub_path)
    return [script_path]


def _activate_installation_hooks(
    *,
    target: Path,
    runtime_memory_root: Path,
    script_abs: str,
    hook_renderer: object,
    workspace_roots: dict[str, list[Path]],
) -> list[Path]:
    activated_paths: list[Path] = []
    codex_templates = SKILL_ROOT / "templates" / "codex-hooks"
    codex_script_path = target / ".codex" / "hooks" / ("hook_adapter.cmd" if os.name == "nt" else "hook_adapter.sh")
    claude_script_path = target / ".claude" / "hooks" / ("hook_adapter.cmd" if os.name == "nt" else "hook_adapter.sh")
    antigravity_script_path = target / ".agents" / "hooks" / ("hook_adapter.cmd" if os.name == "nt" else "hook_adapter.sh")
    gemini_script_path = target / ".gemini" / "hooks" / ("hook_adapter.cmd" if os.name == "nt" else "hook_adapter.sh")
    for path in [codex_script_path, claude_script_path, antigravity_script_path, gemini_script_path]:
        path.parent.mkdir(parents=True, exist_ok=True)

    def write_project_adapter(script_path: Path, runner: str) -> None:
        activated_paths.extend(
            _write_project_hook_adapter(
                script_path=script_path,
                runner=runner,
                installation_root=target,
                metadata_root=runtime_memory_root,
                hook_renderer=hook_renderer,
            )
        )

    _write_json(
        target / ".codex" / "hooks.json",
        _render_shell_hook_config(
            codex_templates / "hooks.json",
            command=_project_local_hook_command("codex", root=target),
        ),
    )
    write_project_adapter(codex_script_path, "codex")
    claude_templates = SKILL_ROOT / "templates" / "claude-hooks"
    _write_json(
        target / ".claude" / "settings.json",
        _render_shell_hook_config(
            claude_templates / "settings.json",
            command=_project_local_hook_command("claude", root=target),
        ),
    )
    write_project_adapter(claude_script_path, "claude")
    _write_json(target / ".agents" / "hooks.json", _render_antigravity_hook_config(hook_script=antigravity_script_path))
    write_project_adapter(antigravity_script_path, "antigravity")
    gemini_templates = SKILL_ROOT / "templates" / "gemini-hooks"
    _write_json(
        target / ".gemini" / "settings.json",
        _render_shell_hook_config(
            gemini_templates / "settings.json",
            command=_project_local_hook_command("gemini", root=target),
        ),
    )
    write_project_adapter(gemini_script_path, "gemini")
    write_workspace_binding("codex", root=target, memory_root=target, written_by="install")
    write_workspace_binding("claude", root=target, memory_root=target, written_by="install")
    write_workspace_binding("antigravity", root=target, memory_root=target, written_by="install")
    write_workspace_binding("gemini", root=target, memory_root=target, written_by="install")
    opencode_paths = ensure_opencode_project(
        target,
        memory_root=runtime_memory_root,
    )
    _run_integration_hook_action(client="opencode", action="enable", target=target, memory_root=runtime_memory_root)
    activated_paths.extend([opencode_paths["config"], opencode_paths["plugin_file"]])
    for workspace_root in workspace_roots["codex"]:
        try:
            _enable_workspace_hooks(client="codex", target=workspace_root, memory_root=target)
            print(f"enabled Codex GUI workspace hooks: {workspace_root}")
        except Exception as exc:  # noqa: BLE001
            print(f"warn: could not enable Codex workspace hooks in {workspace_root}: {exc}", file=sys.stderr)
    for workspace_root in workspace_roots["claude"]:
        try:
            _enable_workspace_hooks(client="claude", target=workspace_root, memory_root=target)
            print(f"enabled Claude workspace hooks: {workspace_root}")
        except Exception as exc:  # noqa: BLE001
            print(f"warn: could not enable Claude workspace hooks in {workspace_root}: {exc}", file=sys.stderr)
    for workspace_root in workspace_roots["cursor"]:
        try:
            _enable_workspace_hooks(client="cursor", target=workspace_root, memory_root=target)
            print(f"enabled Cursor workspace hooks: {workspace_root}")
        except Exception as exc:  # noqa: BLE001
            print(f"warn: could not enable Cursor workspace hooks in {workspace_root}: {exc}", file=sys.stderr)
    for path in [
        codex_script_path,
        claude_script_path,
        antigravity_script_path,
        gemini_script_path,
        codex_script_path.with_suffix(".ps1"),
        claude_script_path.with_suffix(".ps1"),
        antigravity_script_path.with_suffix(".ps1"),
        gemini_script_path.with_suffix(".ps1"),
    ]:
        if path.exists():
            _mark_platform_executable(path)
            activated_paths.append(path)
    missing_artifacts = _missing_installation_hook_artifacts(target)
    if missing_artifacts:
        missing = ", ".join(str(path) for path in missing_artifacts)
        raise RuntimeError(
            f"installation hook finalization incomplete; missing required artifacts: {missing}"
        )
    return activated_paths


def _missing_installation_hook_artifacts(target: Path) -> list[Path]:
    adapter_name = "hook_adapter.cmd" if os.name == "nt" else "hook_adapter.sh"
    required = [
        target / ".codex" / "hooks.json",
        target / ".codex" / "hooks" / adapter_name,
        target / ".claude" / "settings.json",
        target / ".claude" / "hooks" / adapter_name,
        target / ".agents" / "hooks.json",
        target / ".agents" / "hooks" / adapter_name,
        target / ".gemini" / "settings.json",
        target / ".gemini" / "hooks" / adapter_name,
        target / "opencode.json",
        target / ".opencode" / "plugins" / "agent-memory.js",
    ]
    return [path for path in required if not path.exists() and not path.is_symlink()]


def _print_headless_guidance(client: str) -> None:
    guidance = HEADLESS_INSTALL_GUIDANCE.get(client)
    if not guidance:
        return
    print(f"  headless requirement: {guidance['detail']}")
    print(f"  install hint: {guidance['install_command']}")
    if guidance.get("login_command"):
        print(f"  login hint: {guidance['login_command']}")


def _runtime_bootstrap_failure_hint(exc: Exception) -> str:
    detail = " ".join(
        str(part or "")
        for part in [
            getattr(exc, "stderr", ""),
            getattr(exc, "stdout", ""),
            str(exc),
        ]
    ).lower()
    if "certificate_verify_failed" in detail or "ssl:" in detail or "tls" in detail:
        return " Check Python package trust/proxy settings for PyPI or use your approved internal package mirror before rerunning repair-installation."
    return ""


def _frontend_build_failure_hint(root: Path) -> str:
    status = frontend_build_status(root)
    if not status["node_path"]:
        return f" Install Node.js {status['node_version_required']} and ensure `node`/`npm` are on PATH."
    if not status["node_version_supported"]:
        return f" Upgrade Node.js to {status['node_version_required']} before rerunning the frontend repair step."
    if not status["npm_path"]:
        return f" Install npm {status['npm_version_required']} and ensure it is on PATH."
    if not status["npm_version_supported"]:
        return f" Upgrade npm to {status['npm_version_required']} before rerunning the frontend repair step."
    return ""

def _installation_check_payload(*, root: Path, args: argparse.Namespace) -> dict[str, object]:
    runtime = python_runtime_status(root)
    frontend = frontend_build_status(root)
    integrations = integration_summary(root=root, probe_gemini=False)
    profile = _resolved_installation_profile(root, args)
    storage_status = _storage_status(root=root, profile=profile)
    metadata_root = Path(str(storage_status["memory_root"])).expanduser().resolve()
    metadata_dir = _metadata_dir_for_runtime_root(metadata_root)
    findings: list[dict[str, str]] = []
    repair_actions: list[dict[str, str]] = []
    manual_actions: list[dict[str, str]] = []
    agent_actions: list[dict[str, str]] = []
    workflow_checks: list[dict[str, object]] = []
    agent_action_seen: set[str] = set()
    manual_action_seen: set[str] = set()

    def add_agent_action(*, code: str, message: str, command: str) -> None:
        if command in agent_action_seen:
            return
        agent_action_seen.add(command)
        agent_actions.append({"code": code, "message": message, "command": command})

    def add_manual_action(*, code: str, message: str, command: str) -> None:
        if command in manual_action_seen:
            return
        manual_action_seen.add(command)
        manual_actions.append({"code": code, "message": message, "command": command})

    if not runtime["python_version_supported"]:
        findings.append(
            {
                "severity": "error",
                "code": "python_version_unsupported",
                "message": (
                    f"Python {runtime['python_version']} is unsupported for this checkout; "
                    f"required {runtime['python_version_required']}"
                ),
            }
        )
        add_manual_action(
            code="install_supported_python",
            message=f"Install a supported Python runtime ({runtime['python_version_required']}) and recreate `.venv`.",
            command="Install Python 3.11+ and rerun install or repair-installation --apply.",
        )

    if not runtime["venv_exists"]:
        findings.append({"severity": "warn", "code": "missing_venv", "message": f"Local runtime virtualenv is missing: {runtime['venv_path']}"})
        repair_actions.append({"code": "create_venv", "message": "Create `.venv` and install backend dependencies."})
        add_agent_action(
            code="create_venv",
            message="Create `.venv` and install backend dependencies.",
            command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
        )
        add_manual_action(
            code="create_venv_direct",
            message="Create the local `.venv` directly.",
            command=f"{_quote_platform_path(sys.executable)} -m venv {_quote_platform_path(root / '.venv')}",
        )
    if not runtime["yaml_available"]:
        findings.append({"severity": "error", "code": "missing_pyyaml", "message": f"PyYAML is missing for the selected runtime python: {runtime['python_path']}"})
        repair_actions.append({"code": "install_backend_dependencies", "message": "Install backend dependencies into `.venv` so monitor/OpenAPI imports work."})
        add_agent_action(
            code="install_backend_dependencies",
            message="Install backend dependencies into `.venv` so monitor/OpenAPI imports work.",
            command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
        )
        add_manual_action(
            code="install_backend_dependencies_direct",
            message="Install backend dependencies directly into the selected runtime environment.",
            command=_direct_backend_dependency_command(runtime),
        )
    if frontend["needs_build"]:
        if not frontend["node_path"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "missing_node",
                    "message": "Node.js is missing from PATH; the monitor frontend cannot be built.",
                }
            )
            add_manual_action(
                code="install_node",
                message=f"Install Node.js {frontend['node_version_required']} and ensure `node`/`npm` are on PATH.",
                command=f"Install Node.js {frontend['node_version_required']} and rerun install or repair-installation --apply --install-frontend-deps.",
            )
        elif not frontend["node_version_supported"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "node_version_unsupported",
                    "message": (
                        f"Node.js {frontend['node_version'] or 'unknown'} is unsupported for the monitor frontend; "
                        f"required {frontend['node_version_required']}"
                    ),
                }
            )
            add_manual_action(
                code="upgrade_node",
                message=f"Upgrade Node.js to {frontend['node_version_required']} before rebuilding the monitor frontend.",
                command=f"Upgrade Node.js to {frontend['node_version_required']} and rerun install or repair-installation --apply --install-frontend-deps.",
            )
        if not frontend["npm_path"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "missing_npm",
                    "message": "npm is missing from PATH; the monitor frontend cannot install its dependencies.",
                }
            )
            add_manual_action(
                code="install_npm",
                message=f"Install npm {frontend['npm_version_required']} or a Node.js distribution that provides it.",
                command=f"Install npm {frontend['npm_version_required']} and rerun install or repair-installation --apply --install-frontend-deps.",
            )
        elif not frontend["npm_version_supported"]:
            findings.append(
                {
                    "severity": "error",
                    "code": "npm_version_unsupported",
                    "message": (
                        f"npm {frontend['npm_version'] or 'unknown'} is unsupported for the monitor frontend; "
                        f"required {frontend['npm_version_required']}"
                    ),
                }
            )
            add_manual_action(
                code="upgrade_npm",
                message=f"Upgrade npm to {frontend['npm_version_required']} before rebuilding the monitor frontend.",
                command=f"Upgrade npm to {frontend['npm_version_required']} and rerun install or repair-installation --apply --install-frontend-deps.",
            )
        findings.append(
            {
                "severity": "warn" if frontend["dist_exists"] else "error",
                "code": "frontend_build_needed",
                "message": (
                    "Monitor frontend build is stale."
                    if frontend["dist_exists"]
                    else f"Monitor frontend build is missing: {frontend['dist_index']}"
                ),
            }
        )
        repair_actions.append({"code": "build_frontend", "message": "Build the monitor frontend before restart."})
        if frontend["build_prerequisites_ready"]:
            add_agent_action(
                code="build_frontend",
                message="Build the monitor frontend before restart.",
                command=f"{agent_memory_cli_for_root(root)} repair-installation --apply --install-frontend-deps",
            )
        if not frontend["node_modules_exists"]:
            repair_actions.append({"code": "install_frontend_dependencies", "message": "Install frontend dependencies before building the monitor UI."})
            if frontend["build_prerequisites_ready"]:
                add_agent_action(
                    code="install_frontend_dependencies",
                    message="Install frontend dependencies before building the monitor UI.",
                    command=f"{agent_memory_cli_for_root(root)} repair-installation --apply --install-frontend-deps",
                )

    if not storage_status["writable"]:
        findings.append(
            {
                "severity": "error",
                "code": "storage_not_writable",
                "message": f"Configured memory root is not writable: {storage_status['memory_root']} ({storage_status['error'] or 'unknown error'})",
            }
        )

    active_root_file = metadata_dir / "active-root"
    if not active_root_file.exists():
        findings.append(
            {
                "severity": "warn",
                "code": "active_root_missing",
                "message": f"Central active-root file is missing: {active_root_file}",
            }
        )
        repair_actions.append({"code": "refresh_active_root", "message": "Recreate central active-root during repair."})
        add_agent_action(
            code="refresh_active_root",
            message="Recreate central active-root during repair.",
            command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
        )
    elif not active_root_file.is_file():
        findings.append(
            {
                "severity": "error",
                "code": "active_root_not_file",
                "message": f"Central active-root path is not a file: {active_root_file}",
            }
        )
    else:
        try:
            active_root_content = active_root_file.read_text(encoding="utf-8").strip().splitlines()
        except OSError as exc:
            findings.append(
                {
                    "severity": "error",
                    "code": "active_root_unreadable",
                    "message": f"Cannot read central active-root at {active_root_file}: {exc}",
                }
            )
        else:
            active_root_text = active_root_content[0].strip() if active_root_content else ""
            if not active_root_text:
                findings.append(
                    {
                        "severity": "error",
                        "code": "active_root_empty",
                        "message": f"Central active-root file is empty: {active_root_file}",
                    }
                )
            else:
                try:
                    active_root_value = Path(active_root_text).expanduser()
                except OSError as exc:
                    findings.append(
                        {
                            "severity": "error",
                            "code": "active_root_invalid_path",
                            "message": f"Central active-root contains invalid path '{active_root_text}': {exc}",
                        }
                    )
                else:
                    if not active_root_value.is_absolute():
                        findings.append(
                            {
                                "severity": "error",
                                "code": "active_root_relative",
                                "message": f"Central active-root is not absolute: {active_root_text}",
                            }
                        )
                    elif not active_root_value.exists() or not active_root_value.is_dir():
                        findings.append(
                            {
                                "severity": "error",
                                "code": "active_root_invalid_dir",
                                "message": f"Central active-root points to missing/non-directory path: {active_root_text}",
                            }
                        )
                    elif str(active_root_value.resolve()) != str(root.resolve()):
                        findings.append(
                            {
                                "severity": "warn",
                                "code": "active_root_mismatch",
                                "message": (
                                    f"Central active-root points to {active_root_value}, which is different from this installation root {root}. "
                                    "Hooks may resolve to a different runtime."
                                ),
                            }
                        )
    for client in ("codex", "claude", "antigravity", "gemini"):
        hub_path = metadata_dir / "hooks" / client / "hook_adapter.sh"
        if not hub_path.exists():
            findings.append(
                {
                    "severity": "error",
                    "code": f"{client}_central_hub_missing",
                    "message": f"Central {client} hub script is missing: {hub_path}",
                }
            )
            repair_actions.append(
                {
                    "code": f"{client}_central_hub_refresh",
                    "message": f"Recreate the central {client} hub script with the active installation during repair.",
                }
            )
            add_agent_action(
                code=f"refresh_{client}_hub",
                message=f"Recreate the central {client} hub script with the active installation during repair.",
                command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
            )
            continue
        if not os.path.isfile(hub_path):
            findings.append(
                {
                    "severity": "error",
                    "code": f"{client}_central_hub_not_file",
                    "message": f"Central {client} hub path is not a regular file: {hub_path}",
                }
            )
            continue
        if not os.access(hub_path, os.X_OK):
            findings.append(
                {
                    "severity": "warn",
                    "code": f"{client}_central_hub_not_executable",
                    "message": f"Central {client} hub script is not executable: {hub_path}",
                }
            )
            repair_actions.append(
                {
                    "code": f"{client}_central_hub_refresh",
                    "message": f"Recreate the central {client} hub script with executable permissions during repair.",
                }
            )
            add_agent_action(
                code=f"refresh_{client}_hub",
                message=f"Recreate the central {client} hub script with executable permissions during repair.",
                command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
            )
        hub_spec_version = ""
        try:
            for line in hub_path.read_text(encoding="utf-8").splitlines():
                match = re.match(r"^#\s*spec_version=(.+)$", line.strip())
                if match:
                    hub_spec_version = match.group(1).strip()
                    break
        except OSError as exc:
            findings.append(
                {
                    "severity": "warn",
                    "code": f"{client}_central_hub_unreadable",
                    "message": f"Cannot read central {client} hub script at {hub_path}: {exc}",
                }
            )
        else:
            if not hub_spec_version:
                findings.append(
                    {
                        "severity": "warn",
                        "code": f"{client}_central_hub_spec_version_missing",
                        "message": f"Central {client} hub script does not expose a spec version marker: {hub_path}",
                    }
                )
            elif hub_spec_version != HUB_RENDER_SPEC_VERSION:
                findings.append(
                    {
                        "severity": "warn",
                        "code": f"{client}_central_hub_spec_version_mismatch",
                        "message": (
                            f"Central {client} hub script spec-version is {hub_spec_version}, "
                            f"expected {HUB_RENDER_SPEC_VERSION}: {hub_path}"
                        ),
                    }
                )
                repair_actions.append(
                    {
                        "code": f"{client}_central_hub_refresh",
                        "message": f"Recreate the central {client} hub script with the current spec version during repair.",
                    }
                )
                add_agent_action(
                    code=f"refresh_{client}_hub",
                    message=f"Recreate the central {client} hub script with the current spec version during repair.",
                    command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
                )

    monitor_profile = dict(profile.get("monitor") or {})
    monitor_host = str(monitor_profile.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = int(monitor_profile.get("port") or DEFAULT_MONITOR_PORT)
    monitor_port_status = _configured_monitor_port_status(
        root=root,
        host=monitor_host,
        port=monitor_port,
    )
    if monitor_port_status["status"] == "conflict":
        findings.append(
            {
                "severity": "warn",
                "code": "monitor_port_conflict",
                "message": f"Configured monitor default {monitor_host}:{monitor_port} is not currently bindable: {monitor_port_status['error']}",
            }
        )

    launchagent_profile = normalize_launchagent_profile(dict(profile.get("launchagent") or {}))
    launchagent_label = launchagent_profile["label"]
    launchagent_path = launchagent_profile["path"]
    launchagent_env_file = launchagent_profile["env_file"]
    launchagent_status = launchagent_runtime_status(label=launchagent_label, env_file=launchagent_env_file, plist_path=launchagent_path, root=root)
    expected_launchagent_path = _expected_launchagent_plist_path(launchagent_label)
    if launchagent_path != expected_launchagent_path and str((launchagent_status.get("installed") or {}).get("plist_path") or "") == expected_launchagent_path:
        findings.append(
            {
                "severity": "warn",
                "code": "launchagent_path_drift",
                "message": (
                    f"Configured LaunchAgent plist path is {launchagent_path}, but runtime status still resolves the installed plist at {expected_launchagent_path}. "
                    "This instance may still be sharing the default LaunchAgent location."
                ),
            }
        )
    if bool((launchagent_status.get("drift") or {}).get("detected")):
        findings.append(
            {
                "severity": "warn",
                "code": "launchagent_drift",
                "message": "LaunchAgent runtime drift detected: " + "; ".join((launchagent_status.get("drift") or {}).get("reasons") or []),
            }
        )

    central_items = {str(item.get("client")): item for item in integrations["items"]}

    workflow_commands = dict(profile.get("workflows") or {})
    for key in WORKFLOW_RUNNER_DEFAULTS:
        runner = str(workflow_commands.get(key) or WORKFLOW_RUNNER_DEFAULTS[key]).strip().lower()
        if runner in {"deterministic", "off"}:
            workflow_checks.append(
                {
                    "key": key,
                    "label": WORKFLOW_LABELS[key],
                    "runner": runner,
                    "ready": True,
                    "status": "ready",
                    "message": "No additional headless CLI required.",
                }
            )
            continue
        item = central_items.get(runner, {})
        ready = bool(item.get("ready"))
        status_text = str(item.get("readiness_status") or ("ready" if ready else "not_ready"))
        guidance = HEADLESS_INSTALL_GUIDANCE.get(runner)
        message = str(item.get("usage_hint") or "")
        if not ready and guidance:
            message = (
                f"{WORKFLOW_LABELS[key]} is configured to use {item.get('label') or runner}, "
                f"but the required headless CLI is not ready. {guidance['detail']}"
            )
            findings.append({"severity": "error", "code": f"{key}_{runner}_not_ready", "message": message})
            if guidance.get("auto_installable"):
                add_agent_action(
                    code=f"install_{runner}_cli",
                    message=f"Install the {guidance['label']} required for {WORKFLOW_LABELS[key]}.",
                    command=f"{agent_memory_cli_for_root(root)} repair-installation --apply --install-cli {runner}",
                )
            add_manual_action(
                code=f"{runner}_install_hint",
                message=f"Install the {guidance['label']} required for {WORKFLOW_LABELS[key]}.",
                command=str(guidance["install_command"]),
            )
            if guidance.get("login_command"):
                add_manual_action(
                    code=f"{runner}_login_hint",
                    message=f"Log in to {guidance['label']} before first headless use.",
                    command=str(guidance["login_command"]),
                )
        elif not ready:
            message = f"{WORKFLOW_LABELS[key]} is configured to use {runner}, but that runner is not ready ({status_text})."
            findings.append({"severity": "warn", "code": f"{key}_{runner}_not_ready", "message": message})
        workflow_checks.append(
            {
                "key": key,
                "label": WORKFLOW_LABELS[key],
                "runner": runner,
                "ready": ready,
                "status": status_text,
                "message": message,
            }
        )

    workspace_roots = {
        client: [Path(path).expanduser().resolve() for path in list((profile.get("workspace_roots") or {}).get(client) or [])]
        for client in ("codex", "claude", "cursor")
    }
    for client, roots in workspace_roots.items():
        for workspace_root in roots:
            item = _workspace_hook_status(client, workspace_root)
            requires_confirmation, adapter_status = _workspace_rewrite_requires_confirmation(client, workspace_root, root)
            binding_status = workspace_binding_status(client, root=workspace_root, expected_memory_root=root)
            if requires_confirmation:
                findings.append(
                    {
                        "severity": "error",
                        "code": f"{client}_workspace_adapter_mismatch",
                        "message": (
                            f"{client} workspace adapter in {workspace_root} points at "
                            f"{adapter_status.get('detected_root') or 'an unknown root'} instead of {adapter_status.get('expected_root')}. "
                            "Repair should not rewrite this automatically without explicit confirmation."
                        ),
                    }
                )
                add_agent_action(
                    code=f"rewrite_{client}_workspace_adapter",
                    message=f"Rewrite the {client} workspace hook adapter in {workspace_root} after reviewing the root mapping.",
                    command=(
                        f"{agent_memory_cli_for_root(root)} repair-installation --apply "
                        f"--rewrite-workspace-hook-adapters --{client}-workspace-root {_quote_platform_path(workspace_root)}"
                    ),
                )
            if str(item.get("hooks_state") or "") != "enabled":
                findings.append(
                    {
                        "severity": "warn",
                        "code": f"{client}_workspace_not_enabled",
                        "message": f"{client} hooks are not enabled in workspace root {workspace_root}",
                    }
                )
                repair_actions.append(
                    {
                        "code": f"enable_{client}_workspace",
                        "message": f"Enable {client} hooks in {workspace_root}",
                    }
                )
                add_agent_action(
                    code=f"enable_{client}_workspace",
                    message=f"Enable {client} hooks in {workspace_root}",
                    command=(
                        f"{agent_memory_cli_for_root(root)} repair-installation --apply "
                        f"--{client}-workspace-root {_quote_platform_path(workspace_root)}"
                        + (" --rewrite-workspace-hook-adapters" if requires_confirmation else "")
                    ),
                )
            binding_state = str(binding_status.get("hook_binding_state") or "")
            if binding_state != "bound":
                findings.append(
                    {
                        "severity": "error",
                        "code": f"{client}_workspace_binding_{binding_state or 'invalid'}",
                        "message": (
                            f"{client} workspace binding in {workspace_root} is {binding_state or 'invalid'}"
                            + (
                                f" (target={binding_status.get('hook_binding_target_root')})"
                                if binding_status.get("hook_binding_target_root")
                                else ""
                            )
                            + (
                                f": {binding_status.get('hook_binding_last_error')}"
                                if binding_status.get("hook_binding_last_error")
                                else ""
                            )
                        ),
                    }
                )
                add_agent_action(
                    code=f"rebind_{client}_workspace",
                    message=f"Rebind the {client} workspace in {workspace_root} to this Agent Context Engine instance.",
                    command=(
                        f"{agent_memory_cli_for_root(root)} repair-installation --apply "
                        f"--{client}-workspace-root {_quote_platform_path(workspace_root)}"
                        + (" --rewrite-workspace-hook-adapters" if requires_confirmation else "")
                    ),
                )

    for client in ("codex", "claude", "antigravity", "gemini"):
        status = integration_projects_status(client, memory_root=root)
        for item in list(status.get("activated_projects") or []):
            if str(item.get("registry_status") or "").strip().lower() != "active":
                continue
            project_path = str(item.get("path") or "").strip()
            if not project_path:
                continue
            hooks_state = str(item.get("hooks_state") or "unknown")
            if hooks_state == "enabled":
                continue
            findings.append(
                {
                    "severity": "error" if hooks_state in {"project_missing", "error"} else "notice",
                    "code": f"{client}_central_registry_drift",
                    "message": (
                        f"{client} central registry marks {project_path} as active but hook state is {hooks_state}"
                        + (f" ({item.get('registry_detail')})" if item.get("registry_detail") else "")
                    ),
                }
            )
            repair_actions.append(
                {
                    "code": f"{client}_central_registry_repair_{safe_slug(project_path)}",
                    "message": f"Reconcile the central registry state for {project_path} by re-enabling {client} hooks.",
                }
            )
            add_agent_action(
                code=f"repair_{client}_registry_{safe_slug(project_path)}",
                message=f"Reconcile central registry state for {project_path} by re-enabling {client} hooks.",
                command=(
                    f"{agent_memory_cli_for_root(root)} integration-hooks --client {client} "
                    f"--target {_quote_platform_path(project_path)} --action enable"
                ),
            )

    return {
        "root": str(root),
        "profile_path": str(installation_profile_path(root)),
        "storage": storage_status,
        "runtime": runtime,
        "frontend": frontend,
        "integrations": integrations,
        "profile": profile,
        "monitor_profile": {
            "host": monitor_host,
            "port": monitor_port,
            "port_available": bool(monitor_port_status["available"]),
            "port_active": bool(monitor_port_status["active"]),
            "port_status": str(monitor_port_status["status"]),
            "port_error": str(monitor_port_status["error"] or ""),
        },
        "launchagent_profile": {
            "label": launchagent_label,
            "path": launchagent_path,
            "env_file": launchagent_env_file,
            "runtime": launchagent_status,
        },
        "workflow_checks": workflow_checks,
        "findings": findings,
        "repair_actions": repair_actions,
        "manual_actions": manual_actions,
        "agent_actions": agent_actions,
    }


def _print_installation_check(payload: dict[str, object]) -> None:
    runtime = payload["runtime"]
    frontend = payload["frontend"]
    integrations = payload["integrations"]
    profile = payload["profile"]
    storage = payload["storage"]
    print(f"installation root: {payload['root']}")
    print(f"installation profile: {payload['profile_path']}")
    print(f"memory root: {storage['memory_root']}")
    print(f"storage schema version: {storage['schema_version']}")
    print(f"storage profile: {storage['profile_path']}")
    print(f"storage writable: {'yes' if storage['writable'] else 'no'}")
    print(f"storage mode: {'legacy-co-located' if storage['legacy_co_located'] else 'explicit'}")
    print(f"runtime python: {runtime['python_path']}")
    print(f"runtime python version: {runtime['python_version']} (required {runtime['python_version_required']})")
    print(f"runtime venv: {'ok' if runtime['venv_exists'] else 'missing'} {runtime['venv_path']}")
    print(f"PyYAML: {'ok' if runtime['yaml_available'] else 'missing'}")
    print(f"monitor frontend dist: {'ok' if frontend['dist_exists'] else 'missing'} {frontend['dist_index']}")
    print(f"monitor frontend build status: {'needs build' if frontend['needs_build'] else 'current'}")
    print(f"monitor frontend deps: {'ok' if frontend['node_modules_exists'] else 'missing'}")
    print(
        f"node: {(frontend['node_version'] or 'missing')} "
        + f"({'ok' if frontend['node_version_supported'] else 'unsupported'}) "
        + f"required={frontend['node_version_required']}"
    )
    print(
        f"npm: {(frontend['npm_version'] or 'missing')} "
        + f"({'ok' if frontend['npm_version_supported'] else 'unsupported'}) "
        + f"required={frontend['npm_version_required']}"
    )
    monitor_profile = payload.get("monitor_profile") or {}
    launchagent_profile = payload.get("launchagent_profile") or {}
    print(
        "monitor default: "
        + f"{monitor_profile.get('host') or DEFAULT_MONITOR_HOST}:{monitor_profile.get('port') or DEFAULT_MONITOR_PORT} "
        + f"({monitor_profile.get('port_status') or ('available' if monitor_profile.get('port_available') else 'conflict')})"
    )
    if monitor_profile.get("port_error"):
        print(f"monitor port detail: {monitor_profile['port_error']}")
    print(
        "launchagent default: "
        + f"label={launchagent_profile.get('label') or '-'} "
        + f"path={launchagent_profile.get('path') or '-'} "
        + f"env_file={launchagent_profile.get('env_file') or '-'}"
    )
    print("configured workflows:")
    for check in payload["workflow_checks"]:
        print(f"- {check['label']}: {check['runner']} ({'ready' if check['ready'] else check['status']})")
    workspace_roots = profile.get("workspace_roots") or {}
    print("configured GUI workspace roots:")
    for client in ("codex", "claude", "cursor"):
        roots = workspace_roots.get(client) or []
        if roots:
            print(f"- {client}:")
            for item in roots:
                print(f"  - {item}")
        else:
            print(f"- {client}: none recorded")
    print(f"integrations: {integrations['ready']}/{integrations['total']} ready")
    for item in integrations["items"]:
        print(
            f"- {item['label']}: {'ready' if item['ready'] else item['readiness_status']} "
            f"hooks={item.get('hooks_state') or '-'} prepared={'yes' if item.get('prepared') else 'no'}"
        )
        client = str(item.get("client") or "")
        if client in HEADLESS_INSTALL_GUIDANCE and not item.get("ready"):
            _print_headless_guidance(client)
    findings = payload["findings"]
    if findings:
        print("findings:")
        for finding in findings:
            print(f"- {finding['severity']}: {finding['message']}")
    else:
        print("findings: none")
    if payload["agent_actions"]:
        print("agent actions:")
        for action in payload["agent_actions"]:
            print(f"- {action['message']}")
            print(f"  {action['command']}")
    repair_actions = payload["repair_actions"]
    if repair_actions:
        print("repairable actions:")
        for action in repair_actions:
            print(f"- {action['message']}")
    manual_actions = payload["manual_actions"]
    if manual_actions:
        print("manual actions:")
        for action in manual_actions:
            print(f"- {action['message']}")
            print(f"  {action['command']}")


def detect_preferred_language(target: Path) -> str | None:
    path = target / "AGENTS.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"Preferred interaction language for future agents:\s*([A-Za-zÄÖÜäöüß]+)", text)
    if not match:
        return None
    label = match.group(1).strip().rstrip(".").lower()
    code = LANGUAGE_CODES_BY_LABEL.get(label)
    if code:
        return code
    try:
        return normalize_language(label)
    except ValueError:
        return None


def installation_language_for_target(*, target: Path, memory_root: Path | None = None, default: str = "en") -> str:
    return (
        detect_preferred_language(target)
        or (detect_preferred_language(memory_root) if memory_root else None)
        or default
    )


def agent_memory_script_for_root(memory_root: Path) -> str:
    if (memory_root / "scripts" / "agent_context_engine.py").exists():
        return "scripts/agent_context_engine.py"
    return "docs/skills/agent-context-engine/scripts/agent_context_engine.py"


def agent_memory_cli_for_root(memory_root: Path) -> str:
    if (memory_root / "scripts" / "agent-context-engine.cmd").exists():
        return "./scripts/agent-context-engine.cmd"
    if (memory_root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine.cmd").exists():
        return "./docs/skills/agent-context-engine/scripts/agent-context-engine.cmd"
    if (memory_root / "scripts" / "agent-context-engine").exists():
        return "./scripts/agent-context-engine"
    return "./docs/skills/agent-context-engine/scripts/agent-context-engine"


def agent_memory_cli_path_for_root(memory_root: Path) -> Path:
    if (memory_root / "scripts" / "agent-context-engine.cmd").exists():
        return memory_root / "scripts" / "agent-context-engine.cmd"
    nested_cmd = memory_root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine.cmd"
    if nested_cmd.exists():
        return nested_cmd
    if (memory_root / "scripts" / "agent-context-engine").exists():
        return memory_root / "scripts" / "agent-context-engine"
    nested = memory_root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine"
    if nested.exists():
        return nested
    return memory_root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine"


def agent_memory_command_prefix_for_target(target: Path, memory_root: Path) -> str:
    user_cli = user_cli_link_path()
    try:
        if target.resolve().is_relative_to(user_cli.parent.resolve()):
            return str(user_cli)
    except AttributeError:
        target_text = str(target.resolve())
        parent_text = str(user_cli.parent.resolve())
        if target_text == parent_text or target_text.startswith(parent_text + os.sep):
            return str(user_cli)
    cli_path = preferred_agent_memory_cli_for_root(memory_root)
    if target.resolve() == memory_root.resolve():
        return cli_path
    if os.name == "nt":
        return f'cd /d "{memory_root.resolve()}" && {cli_path}'
    return f"cd {_quote_platform_path(memory_root.resolve())} && {cli_path}"


def cursor_hook_wrapper(memory_root: Path) -> str:
    from ....application.hook_rendering import build_cursor_project_hook_wrapper_spec
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_hook_adapter_renderer

    return select_hook_adapter_renderer(current_platform_profile()).render_cursor_project_hook_wrapper(
        build_cursor_project_hook_wrapper_spec(
            agent_context_engine_root=memory_root,
            agent_memory_script=str((memory_root / agent_memory_script_for_root(memory_root)).resolve()),
        )
    )

def antigravity_hook_wrapper(memory_root: Path) -> str:
    from ....application.hook_rendering import build_shell_hook_adapter_spec
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_hook_adapter_renderer

    return select_hook_adapter_renderer(current_platform_profile()).render_shell_hook_adapter(
        build_shell_hook_adapter_spec(
            "antigravity",
            agent_context_engine_root=memory_root,
            agent_memory_script=str((memory_root / agent_memory_script_for_root(memory_root)).resolve()),
        )
    )


def managed_install_conflicts(target: Path) -> list[Path]:
    if _looks_like_agent_memory_checkout(target) and not installation_profile_path(target).exists():
        return []
    return [target / relative for relative in MANAGED_INSTALL_PATHS if (target / relative).exists()]


def _replace_hook_commands(value: object, command: str) -> object:
    if isinstance(value, dict):
        replaced: dict[str, object] = {}
        for key, item in value.items():
            if key == "command" and isinstance(item, str):
                existing = item.strip()
                if not existing:
                    replaced[key] = command
                else:
                    head, separator, tail = existing.partition(" ")
                    replaced[key] = f"{command}{separator}{tail}" if separator else command
            else:
                replaced[key] = _replace_hook_commands(item, command)
        return replaced
    if isinstance(value, list):
        return [_replace_hook_commands(item, command) for item in value]
    return value


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _render_shell_hook_config(template_path: Path, *, command: str) -> dict[str, object]:
    return _replace_hook_commands(json.loads(template_path.read_text(encoding="utf-8")), command)


def _replace_string_placeholder(value: object, placeholder: str, replacement: str) -> object:
    if isinstance(value, dict):
        return {key: _replace_string_placeholder(item, placeholder, replacement) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_string_placeholder(item, placeholder, replacement) for item in value]
    if isinstance(value, str):
        return value.replace(placeholder, replacement)
    return value


def _render_antigravity_hook_config(*, hook_script: Path) -> dict[str, object]:
    template = json.loads((SKILL_ROOT / "templates" / "antigravity-hooks" / "hooks.json").read_text(encoding="utf-8"))
    rendered = _replace_string_placeholder(template, "__ANTIGRAVITY_HOOK_SCRIPT__", _quote_platform_path(hook_script.resolve()))
    if not isinstance(rendered, dict):
        raise ValueError("invalid antigravity hook template")
    return rendered


def _write_platform_script(script_path: Path, script_text: str) -> list[Path]:
    if script_path.suffix == ".cmd":
        from ....application.platform import current_platform_profile
        from ....application.platform.runtime_selection import select_command_publisher

        companion_path = script_path.with_suffix(".ps1")
        companion_path.write_text(script_text, encoding="utf-8")
        actual_path = select_command_publisher(current_platform_profile()).create_symlink(script_path.with_suffix(""), companion_path, force=True)
        _mark_platform_executable(companion_path)
        _mark_platform_executable(actual_path)
        return [companion_path, actual_path]
    script_path.write_text(script_text, encoding="utf-8")
    _mark_platform_executable(script_path)
    return [script_path]


def _materialize_windows_cli_and_wrappers(*, script_root: Path, installation_root: Path) -> list[Path]:
    if os.name != "nt":
        return []
    from ....application.hook_rendering import build_wrapper_render_spec, supported_wrapper_names
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_command_publisher, select_wrapper_renderer

    publisher = select_command_publisher(current_platform_profile())
    renderer = select_wrapper_renderer(current_platform_profile())
    script_root.mkdir(parents=True, exist_ok=True)
    python_script = (installation_root / agent_memory_script_for_root(installation_root)).resolve()
    written: list[Path] = []
    for command_name in ("agent-context-engine", "ace"):
        written.append(publisher.create_symlink(script_root / command_name, python_script, force=True))
    for wrapper_name in sorted(supported_wrapper_names()):
        ps1_path = script_root / f"{wrapper_name}.ps1"
        ps1_path.write_text(
            renderer.render_wrapper(
                build_wrapper_render_spec(
                    wrapper_name,
                    installation_root=installation_root,
                    support_level="experimental",
                    evidence="static_contract_test",
                )
            ),
            encoding="utf-8",
        )
        written.append(ps1_path)
        _mark_platform_executable(ps1_path)
        written.append(publisher.create_symlink(script_root / wrapper_name, ps1_path, force=True))
    return written


def print_install_conflicts(target: Path, conflicts: list[Path]) -> int:
    cli_hint = agent_memory_cli_for_root(target)
    print(f"refusing to overwrite existing Agent Context Engine-managed files in {target}", file=sys.stderr)
    print("existing managed paths:", file=sys.stderr)
    for path in conflicts:
        print(f"- {path}", file=sys.stderr)
    print("", file=sys.stderr)
    print("next:", file=sys.stderr)
    print(f"- inspect the current target with {cli_hint} doctor if this is the active installation", file=sys.stderr)
    print("- use --instance-name for a second installation with prefixed global commands", file=sys.stderr)
    print("- use --force only when you intentionally want to refresh this installation in place", file=sys.stderr)
    print("- use cursor-enable for project activation, or antigravity-enable / gemini-enable / opencode-enable for central global-only bridges", file=sys.stderr)
    return 1


def _require_existing_workspace_target(target: Path, *, command_name: str, client_name: str) -> bool:
    if target.exists() and target.is_dir():
        return True
    print(f"error: {client_name} project target does not exist: {target}", file=sys.stderr)
    print(
        f"rerun `{command_name} --target /absolute/path/to/project` with the exact existing project folder; "
        "do not rely on a relative path that resolves under the installation root.",
        file=sys.stderr,
    )
    return False


def cmd_cursor_enable(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if args.target else ROOT
    installation_root = Path(str(getattr(args, "installation_root", None) or getattr(args, "memory_root", None) or ROOT)).expanduser().resolve()
    if not _require_existing_workspace_target(target, command_name="agent-context-engine cursor-enable", client_name="Cursor"):
        return 1
    background = cursor_background_runner_status(preferred_runner=getattr(args, "background_runner", None))
    if not background["headless_runner_ready"]:
        print("error: Cursor project activation requires a background headless LLM runner (`codex` or `claude`) that is actually ready for use.", file=sys.stderr)
        print("Cursor hooks alone are not sufficient for Agent Context Engine in Cursor.", file=sys.stderr)
        print("Firewall classification, dreaming, query expansion, and other background LLM workflows require `codex` or `claude` on the machine.", file=sys.stderr)
        if background["background_runner_status"] == "auth_required" and background["headless_runner"]:
            print(f"detected runner `{background['headless_runner']}`, but it is not authenticated for headless use yet.", file=sys.stderr)
            if background.get("background_runner_login_command"):
                print(f"run `{background['background_runner_login_command']}` first, then rerun `agent-context-engine cursor-enable --target <project-path>`", file=sys.stderr)
        elif background["background_runner_status"] == "missing_executable" and background["headless_runner"]:
            print(f"requested runner `{background['headless_runner']}` is not installed or not on PATH.", file=sys.stderr)
            print(f"install `{background['headless_runner']}` first, then rerun `agent-context-engine cursor-enable --target <project-path>`", file=sys.stderr)
        else:
            print("install one of them first, then rerun `agent-context-engine cursor-enable --target <project-path>`", file=sys.stderr)
        return 1
    command_prefix = agent_memory_command_prefix_for_target(target, installation_root)
    language = installation_language_for_target(target=target, memory_root=installation_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=installation_root)
    entrypoints = ensure_harness_entrypoints(target)
    script_path = target / ".cursor" / "hooks" / "hook_adapter.sh"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        script_path = script_path.with_suffix(".cmd")
    _write_platform_script(script_path, cursor_hook_wrapper(installation_root))
    result, target_item = _run_integration_hook_action(
        client="cursor",
        action="enable",
        target=target,
        memory_root=installation_root,
        background_runner=background["headless_runner"],
    )
    profile = load_installation_profile(installation_root)
    workspace_roots = {
        client: [Path(path).expanduser().resolve() for path in list((profile.get("workspace_roots") or {}).get(client) or [])]
        for client in ("codex", "claude", "cursor")
    }
    if target not in workspace_roots["cursor"]:
        workspace_roots["cursor"].append(target)
        merge_installation_profile(installation_root, workspace_roots=workspace_roots)
    print(f"enabled Cursor IDE memory hooks: {target_item.get('hook_config_path') or (target / '.cursor' / 'hooks.json')}")
    print(f"hook wrapper: {target_item.get('hook_script_path') or script_path}")
    print(f"installation root: {installation_root}")
    print(f"background runner: {background['headless_runner']}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='cursor', action='enable', target_root=target, root=installation_root)}")
    print("next: reload the Cursor window or reopen the project folder")
    print(f"background LLM workflows for this Cursor project will use `{background['headless_runner']}`")
    return 0


def cmd_antigravity_enable(args: argparse.Namespace) -> int:
    installation_root = Path(str(getattr(args, "installation_root", None) or getattr(args, "memory_root", None) or ROOT)).expanduser().resolve()
    install_root = ROOT
    if args.target:
        target = Path(args.target).expanduser().resolve()
        print(f"warning: project-specific Antigravity hooks are deprecated; use the global wrapper instead.")
        print(f"  global wrapper: {agent_memory_cli_for_root(installation_root)} global-wrapper-enable agy-ace")
        print(f"  run from anywhere: agy-ace")
        print(f"  requested target is unsupported in global-only mode: {target}")
    else:
        target = install_root

    if target.resolve() != install_root.resolve():
        print(f"error: refusing to create project-specific Antigravity hooks in {target}")
        print("Antigravity Agent Context Engine is now global-only. Use agy-ace to start Antigravity with hooks.")
        return 1

    command_prefix = agent_memory_command_prefix_for_target(target, installation_root)
    language = installation_language_for_target(target=target, memory_root=installation_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=installation_root)
    entrypoints = ensure_harness_entrypoints(target)
    paths = ensure_antigravity_project(target, memory_root=installation_root)
    script_path = paths["script_path"]
    script_path.parent.mkdir(parents=True, exist_ok=True)
    _write_platform_script(script_path, antigravity_hook_wrapper(installation_root))
    result, target_item = _run_integration_hook_action(client="antigravity", action="enable", target=target, memory_root=installation_root)
    print(f"enabled global Antigravity Agent Context Engine hooks: {paths['config_path']}")
    print(f"hook wrapper: {script_path}")
    print(f"installation root: {installation_root}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='antigravity', action='enable', target_root=target, root=installation_root)}")
    print("next: ensure agy-ace is linked globally and start Antigravity with `agy-ace`")
    return 0


def cmd_gemini_enable(args: argparse.Namespace) -> int:
    installation_root = Path(str(getattr(args, "installation_root", None) or getattr(args, "memory_root", None) or ROOT)).expanduser().resolve()
    install_root = ROOT
    if args.target:
        target = Path(args.target).expanduser().resolve()
        print(f"warning: project-specific Gemini hooks are deprecated; use the global wrapper instead.")
        print(f"  global wrapper: {agent_memory_cli_for_root(installation_root)} global-wrapper-enable gemini-ace")
        print(f"  run from anywhere: gemini-ace")
        print(f"  requested target is unsupported in global-only mode: {target}")
    else:
        target = install_root

    if target.resolve() != install_root.resolve():
        print(f"error: refusing to create project-specific Gemini hooks in {target}")
        print("Gemini Agent Context Engine is now global-only. Use gemini-ace to start Gemini with hooks.")
        return 1

    command_prefix = agent_memory_command_prefix_for_target(target, installation_root)
    language = installation_language_for_target(target=target, memory_root=installation_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=installation_root)
    entrypoints = ensure_harness_entrypoints(target)
    paths = ensure_gemini_project(target)
    result, _target_item = _run_integration_hook_action(client="gemini", action="enable", target=target, memory_root=installation_root)
    print(f"enabled global Gemini Agent Context Engine hooks: {paths['config_path']}")
    print(f"hook adapter: {paths['script_path']}")
    print(f"installation root: {installation_root}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='gemini', action='enable', target_root=target, root=installation_root)}")
    print("next: ensure gemini-ace is linked globally and start Gemini with `gemini-ace`")
    return 0


def cmd_cursor_disable(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if args.target else ROOT
    if not _require_existing_workspace_target(target, command_name="agent-context-engine cursor-disable", client_name="Cursor"):
        return 1
    result, target_item = _run_integration_hook_action(client="cursor", action="disable", target=target, memory_root=ROOT)
    print(f"disabled Cursor IDE memory hooks: {target_item.get('hook_config_path') or (target / '.cursor' / 'hooks.json')}")
    print(f"deactivated hook config: {target_item.get('hook_disabled_path') or (target / '.cursor' / 'hooks_deactivated.json')}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='cursor', action='disable', target_root=target, root=ROOT)}")
    print("next: reload the Cursor window or reopen the project folder")
    return 0


def cmd_cursor_status(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if args.target else None
    if target is not None and not _require_existing_workspace_target(target, command_name="agent-context-engine cursor-status", client_name="Cursor"):
        return 1
    lines, exit_code = run_cursor_status(target=target)
    for line in lines:
        print(line)
    return exit_code


def cmd_opencode_enable(args: argparse.Namespace) -> int:
    installation_root = Path(str(getattr(args, "installation_root", None) or getattr(args, "memory_root", None) or ROOT)).expanduser().resolve()
    install_root = ROOT
    if args.target:
        target = Path(args.target).expanduser().resolve()
        print(f"warning: project-specific OpenCode hooks are deprecated; use the global wrapper instead.")
        print(f"  global wrapper: {agent_memory_cli_for_root(installation_root)} global-wrapper-enable opencode-ace")
        print(f"  run from anywhere: opencode-ace [project]")
        print(f"  requested target is unsupported in global-only mode: {target}")
    else:
        target = install_root

    # For global-only mode, the only plugin that should exist is inside the
    # central installation root. Project-specific plugins are no longer created.
    if target.resolve() != install_root.resolve():
        print(f"error: refusing to create project-specific OpenCode plugin in {target}")
        print("OpenCode Agent Context Engine is now global-only. Use opencode-ace to start OpenCode with hooks.")
        return 1

    command_prefix = agent_memory_command_prefix_for_target(target, installation_root)
    language = installation_language_for_target(target=target, memory_root=installation_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=installation_root)
    entrypoints = ensure_harness_entrypoints(target)
    paths = ensure_opencode_project(
        target,
        memory_root=installation_root,
        model=getattr(args, "model", None) or None,
        small_model=getattr(args, "small_model", None) or None,
    )
    result, _target_item = _run_integration_hook_action(client="opencode", action="enable", target=target, memory_root=installation_root)
    print(f"enabled global OpenCode Agent Context Engine bridge: {paths['plugin_file']}")
    print(f"opencode config: {paths['config']}")
    print(f"installation root: {installation_root}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='opencode', action='enable', target_root=target, root=installation_root)}")
    print("next: ensure opencode-ace is linked globally and start OpenCode with `opencode-ace [project]`")
    return 0


def _integration_target_item(result: dict[str, object], target: Path) -> dict[str, object]:
    item = result.get("item")
    if not isinstance(item, dict):
        return {}
    activated = item.get("activated_projects")
    if isinstance(activated, list):
        for entry in activated:
            if isinstance(entry, dict) and str(entry.get("path") or "") == str(target):
                return entry
    return item


def _run_integration_hook_action(
    *,
    client: str,
    action: str,
    target: Path,
    memory_root: Path,
    background_runner: str | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    result = manage_integration_hooks(
        client=client,
        action=action,
        root=memory_root,
        target_root=target,
        background_runner=background_runner,
    )
    target_item = _integration_target_item(result, target)
    return result, target_item


def cmd_integration_hooks(args: argparse.Namespace) -> int:
    action: str
    if getattr(args, "action", None):
        action = str(args.action)
    elif getattr(args, "activate", False):
        action = "enable"
    else:
        print("error: --action or --activate is required", file=sys.stderr)
        return 2

    target = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    installation_root = Path(str(getattr(args, "installation_root", None) or getattr(args, "memory_root", None) or ROOT)).expanduser().resolve()
    if getattr(args, "target", None) and str(args.client) in {"codex", "claude", "cursor"}:
        if not _require_existing_workspace_target(
            target,
            command_name=f"agent-context-engine integration-hooks --client {args.client} --action {action}",
            client_name=str(args.client).capitalize(),
        ):
            return 1
    result, target_item = _run_integration_hook_action(
        client=str(args.client),
        action=action,
        target=target,
        memory_root=installation_root,
        background_runner=str(getattr(args, "background_runner", "") or "") or None,
    )
    print(f"client: {args.client}")
    print(f"action: {action}")
    print(f"target: {target}")
    print(f"hook config: {target_item.get('hook_config_path') or '-'}")
    print(f"hook disabled file: {target_item.get('hook_disabled_path') or '-'}")
    print(f"hooks state: {target_item.get('hooks_state') or '-'}")
    print(f"hook events: {', '.join(target_item.get('active_hook_events', [])) if isinstance(target_item.get('active_hook_events'), list) else '-'}")
    print(f"command: {result.get('command') or integration_hook_command(client=str(args.client), action=action, target_root=target, root=installation_root)}")
    return 0


def cmd_opencode_status(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if args.target else ROOT
    status = opencode_status(root)
    print(f"client: {status['label']}")
    print(f"ready: {'yes' if status['ready'] else 'no'}")
    print(f"readiness: {status['readiness_status']}")
    print(f"provider: {status['provider']}")
    print(f"selected model: {status['selected_model'] or '-'}")
    print(f"selected mini model: {status['selected_small_model'] or '-'}")
    print(f"dream model: {status['dream_model']}")
    print(f"dream readiness: {status['dream_readiness_status']}")
    print(f"plugin bridge: {'ok' if status['plugin_exists'] else 'missing'} {status['paths']['plugin_file']}")
    print(f"project config: {'ok' if status['project_config_exists'] else 'missing'} {status['paths']['config']}")
    print(f"provider models discovered: {len(status.get('provider_models', []))}")
    for model in status.get("provider_models", [])[:20]:
        print(f"  - {model['id']}")
    return 0 if status["ready"] and status.get("dream_model_ready") else 1


def cmd_gemini_status(args: argparse.Namespace) -> int:
    if getattr(args, "target", None):
        print("warning: --target is deprecated for gemini-status; Gemini Agent Context Engine is global-only.")
        print("use `gemini-ace` from any directory, or run `./scripts/agent-context-engine gemini-status` without --target.")
    root = ROOT
    status = gemini_status(root=root, probe=bool(getattr(args, "probe", False)))
    print(f"client: {status['label']}")
    print(f"ready: {'yes' if status['ready'] else 'no'}")
    print(f"readiness: {status['readiness_status']}")
    print(f"hooks: {status['hooks_state']}")
    print(f"hook config: {status['hook_config_path'] or '-'}")
    print(f"hook adapter: {status['hook_script_path'] or '-'}")
    print(f"selected model: {status['selected_model'] or '-'}")
    print(f"recommended mini model: {status['recommended_small_model']}")
    if status.get("models"):
        print("discovered models:")
        for model in status["models"]:
            print(f"  - {model['id']}")
    if status.get("errors"):
        print("probe notes:")
        for item in status["errors"][:10]:
            print(f"  - {item['id']}: {item['detail']}")
    return 0 if status["ready"] else 1


def cmd_antigravity_status(args: argparse.Namespace) -> int:
    if getattr(args, "target", None):
        print("warning: --target is deprecated for antigravity-status; Antigravity Agent Context Engine is global-only.")
        print("use `agy-ace` from any directory, or run `./scripts/agent-context-engine antigravity-status` without --target.")
    root = ROOT
    status = antigravity_status(root=root)
    print(f"client: {status['label']}")
    print(f"ready: {'yes' if status['ready'] else 'no'}")
    print(f"readiness: {status['readiness_status']}")
    print(f"hooks: {status['hooks_state']}")
    print(f"hook config: {status['hook_config_path'] or '-'}")
    print(f"hook adapter: {status['hook_script_path'] or '-'}")
    print(f"selected model: {status['selected_model'] or '-'}")
    print(f"resume command: {status['conversation_resume_command']}")
    return 0 if status["ready"] else 1


def cmd_integrations_status(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if args.target else ROOT
    summary = integration_summary(root=root, probe_gemini=bool(getattr(args, "probe_gemini", False)))
    print(f"integrations: {summary['ready']}/{summary['total']} ready")
    for item in summary["items"]:
        print(
            f"- {item['label']}: {'ready' if item['ready'] else item['readiness_status']} "
            f"runner={item['runner']} provider={item['provider']} model={item.get('selected_model') or '-'} "
            f"hooks={item.get('hooks_state') or '-'}"
        )
        client = str(item.get("client") or "")
        if client in {"codex", "claude"}:
            if item.get("hooks_enabled"):
                print("  gui hooks only: yes")
            if not item.get("ready"):
                print("  headless cli ready: no")
                _print_headless_guidance(client)
        elif client == "cursor" and not item.get("ready"):
            print("  headless cli ready: no")
            _print_headless_guidance(client)
    return 0 if summary["not_ready"] == 0 else 1


def _print_hooks_status(status: dict[str, object]) -> None:
    print(f"global: {'enabled' if status.get('enabled') else 'disabled'}")
    if status.get("disabled_at"):
        print(f"global disabled at: {status['disabled_at']}")
    if status.get("disabled_by"):
        print(f"global disabled by: {status['disabled_by']}")
    if status.get("reason"):
        print(f"reason: {status['reason']}")
    print("runners:")
    for item in status.get("runners", []):
        if not isinstance(item, dict):
            continue
        line = f"- {item.get('client')}: {'enabled' if item.get('enabled') else 'disabled'} ({item.get('source')})"
        if item.get("disabled_by"):
            line += f" by={item['disabled_by']}"
        if item.get("disabled_at"):
            line += f" at={item['disabled_at']}"
        print(line)


def cmd_hooks_disable(args: argparse.Namespace) -> int:
    status = set_hooks_enabled(
        enabled=False,
        runner=str(getattr(args, "runner", "all") or "all"),
        actor="cli",
        reason=str(getattr(args, "reason", "") or ""),
    )
    _print_hooks_status(status)
    return 0


def cmd_hooks_enable(args: argparse.Namespace) -> int:
    status = set_hooks_enabled(
        enabled=True,
        runner=str(getattr(args, "runner", "all") or "all"),
        actor="cli",
        reason=str(getattr(args, "reason", "") or ""),
    )
    _print_hooks_status(status)
    return 0


def cmd_hooks_status(args: argparse.Namespace) -> int:
    _print_hooks_status(hooks_control_status())
    return 0


def cmd_check_installation(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    payload = _installation_check_payload(root=root, args=args)
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    _print_installation_check(payload)
    return 0


def cmd_repair_installation(args: argparse.Namespace) -> int:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_hook_adapter_renderer

    root = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    current_storage_root = Path(str(resolve_storage_profile(root).get("memory_root") or (root / "memory"))).expanduser().resolve()
    runtime_memory_root = _default_storage_root_for_install(root, args)
    workspace_roots = _workspace_root_overrides(args)
    workflow_overrides = _workflow_runner_overrides(args)
    payload = _installation_check_payload(root=root, args=args)
    _print_installation_check(payload)
    if not getattr(args, "apply", False):
        if str(load_installation_profile(root).get("installation_mode") or "") == "ambiguous":
            print(
                "warning: legacy installation mode is ambiguous; review and pass "
                "--legacy-installation-mode shared|isolated with --apply"
            )
        print("next: rerun with --apply after reviewing the proposed actions")
        return 0

    applied: list[str] = []
    skipped: list[str] = []
    runtime_ready = True
    frontend_ready = True
    storage_rebound = bool(getattr(args, "memory_root", None))
    try:
        installation_profile = load_installation_profile(root)
        installation_mode = str(installation_profile.get("installation_mode") or "shared")
        selected_legacy_mode = str(getattr(args, "legacy_installation_mode", "") or "")
        if installation_mode == "ambiguous":
            if not selected_legacy_mode:
                raise RuntimeError(
                    "legacy installation mode is ambiguous; rerun with "
                    "--legacy-installation-mode shared or --legacy-installation-mode isolated"
                )
            merge_installation_profile(root, installation_mode=selected_legacy_mode)
            installation_mode = selected_legacy_mode
            applied.append(f"resolved legacy installation mode as {selected_legacy_mode}")
        for hub_action in _ensure_central_hub_and_active_root(
            root,
            metadata_root=runtime_memory_root,
            publish_shared_active_root=installation_mode != "isolated",
        ):
            applied.append(hub_action)
        if workflow_overrides or any(workspace_roots.values()) or getattr(args, "memory_root", None):
            applied.extend(_relocate_runtime_storage(current_storage_root, runtime_memory_root))
            ensure_storage_profile(runtime_memory_root, schema_version=int(resolve_storage_profile(root).get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION), storage_instance_id=str(load_installation_profile(root).get("instance_id") or root.name))
            current_profile = load_installation_profile(root)
            current_launchagent = normalize_launchagent_profile(dict(current_profile.get("launchagent") or {}))
            current_env_file = str(current_launchagent.get("env_file") or "")
            launchagent_updates: dict[str, str] | None = None
            if _should_rewrite_launchagent_env_file(current_env_file, old_memory_root=current_storage_root):
                launchagent_updates = {"env_file": _default_launchagent_env_file_for_storage(runtime_memory_root)}
            merge_installation_profile(
                root,
                workflows=workflow_overrides or None,
                workspace_roots=workspace_roots or None,
                storage={"memory_root": runtime_memory_root, "schema_version": int(resolve_storage_profile(root).get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION), "attached_at": _utc_timestamp()},
                launchagent=launchagent_updates,
            )
            applied.append(f"updated installation profile {installation_profile_path(root)}")
        runtime = payload["runtime"]
        if (not runtime["venv_exists"]) or (not runtime["yaml_available"]):
            try:
                applied.extend(ensure_runtime_venv(root, install_backend_dependencies=True))
            except (RuntimeError, subprocess.CalledProcessError) as exc:
                if storage_rebound or workflow_overrides or any(workspace_roots.values()):
                    runtime_ready = False
                    skipped.append(f"runtime bootstrap skipped after profile repair: {exc}")
                else:
                    raise
        frontend = payload["frontend"]
        if frontend["needs_build"]:
            try:
                applied.extend(
                    ensure_monitor_frontend_build(
                        root,
                        install_dependencies=bool(getattr(args, "install_frontend_deps", False)),
                        force=True,
                    )
                )
            except (RuntimeError, subprocess.CalledProcessError) as exc:
                if storage_rebound or workflow_overrides or any(workspace_roots.values()):
                    frontend_ready = False
                    skipped.append(f"monitor frontend repair skipped after profile repair: {exc}")
                else:
                    raise
        for client in getattr(args, "install_cli", []) or []:
            applied.extend(install_headless_cli(client))
        for workspace_root in workspace_roots["codex"]:
            requires_confirmation, adapter_status = _workspace_rewrite_requires_confirmation("codex", workspace_root, root)
            if requires_confirmation and not getattr(args, "rewrite_workspace_hook_adapters", False):
                skipped.append(
                    f"skipped codex workspace adapter rewrite in {workspace_root}; current adapter points to {adapter_status.get('detected_root') or 'unknown'}"
                )
                continue
            _enable_workspace_hooks(client="codex", target=workspace_root, memory_root=root)
            applied.append(f"enabled codex hooks in {workspace_root}")
        for workspace_root in workspace_roots["claude"]:
            requires_confirmation, adapter_status = _workspace_rewrite_requires_confirmation("claude", workspace_root, root)
            if requires_confirmation and not getattr(args, "rewrite_workspace_hook_adapters", False):
                skipped.append(
                    f"skipped claude workspace adapter rewrite in {workspace_root}; current adapter points to {adapter_status.get('detected_root') or 'unknown'}"
                )
                continue
            _enable_workspace_hooks(client="claude", target=workspace_root, memory_root=root)
            applied.append(f"enabled claude hooks in {workspace_root}")
        for workspace_root in workspace_roots["cursor"]:
            _enable_workspace_hooks(client="cursor", target=workspace_root, memory_root=root)
            applied.append(f"enabled cursor hooks in {workspace_root}")
        if runtime_ready and frontend_ready:
            activated = _activate_installation_hooks(
                target=root,
                runtime_memory_root=runtime_memory_root,
                script_abs=str((root / "scripts" / "agent_context_engine.py").resolve()),
                hook_renderer=select_hook_adapter_renderer(current_platform_profile()),
                workspace_roots={"codex": [], "claude": [], "cursor": []},
            )
            for path in activated:
                applied.append(f"finalized installation-root integration: {path}")
        else:
            skipped.append(
                "installation-root hook finalization skipped because runtime or frontend repair failed"
            )
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"repair failed: {exc}", file=sys.stderr)
        return 1

    if applied:
        print("applied actions:")
        for item in applied:
            print(f"- {item}")
    else:
        print("applied actions: none")
    if skipped:
        print("skipped actions:")
        for item in skipped:
            print(f"- {item}")
    if payload["manual_actions"]:
        print("remaining manual actions:")
        for action in payload["manual_actions"]:
            print(f"- {action['message']}")
    return 0


def copy_skill_package(target: Path) -> Path:
    if SKILL_ROOT.resolve() == target.resolve():
        return SKILL_ROOT
    dest = target / "docs" / "skills" / "agent-context-engine"
    if SKILL_ROOT.resolve() == dest.resolve():
        return dest
    shutil.copytree(
        SKILL_ROOT,
        dest,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            ".venv",
            "dist",
            "node_modules",
            ".git",
            ".codex",
            ".claude",
            ".cursor",
            ".opencode",
            "AGENTS.md",
            "CLAUDE.md",
            "docs",
            "memory",
            "videos",
        ),
    )
    legacy_alias = target / "docs" / "skills" / "agent-memory"
    if not legacy_alias.exists():
        try:
            legacy_alias.symlink_to(dest.name, target_is_directory=True)
        except OSError:
            shutil.copytree(dest, legacy_alias, dirs_exist_ok=True)
    return dest


def install_wrapper_prefix(args: argparse.Namespace) -> str:
    raw_prefix = args.wrapper_prefix
    if raw_prefix is None:
        raw_prefix = args.command_prefix
    if raw_prefix is not None:
        prefix = safe_slug(raw_prefix)
        if raw_prefix and raw_prefix[-1] in "-_." and not prefix.endswith(raw_prefix[-1]):
            prefix += raw_prefix[-1]
        return prefix
    if args.instance_name:
        return safe_slug(args.instance_name) + "-"
    return ""


def install_wrapper_suffix(args: argparse.Namespace) -> str:
    raw_suffix = getattr(args, "wrapper_suffix", None)
    if raw_suffix is None:
        return "-ace"
    if raw_suffix and raw_suffix[0] not in "-_.":
        raw_suffix = "-" + raw_suffix
    suffix = safe_slug(raw_suffix)
    if raw_suffix and raw_suffix[0] in "-_." and not suffix.startswith(raw_suffix[0]):
        suffix = raw_suffix[0] + suffix
    return suffix


def install_command_prefix(args: argparse.Namespace) -> str:
    return install_wrapper_prefix(args)


def link_command_name(base: str, prefix: str, suffix: str = "") -> str:
    from ....application.wrapper_publication import build_wrapper_command_name

    return build_wrapper_command_name(base, prefix, suffix)


def wrapper_script_path(root: Path, wrapper_name: str) -> Path:
    from ....application.wrapper_publication import resolve_wrapper_script_path

    return resolve_wrapper_script_path(root, wrapper_name)


def create_command_link(
    link_dir: Path,
    link_name: str,
    target: Path,
    *,
    force: bool,
    link_kind: str = "global_wrapper",
    installation_root: Path | None = None,
) -> Path:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_command_publisher

    link = link_dir / link_name
    actual_link = select_command_publisher(current_platform_profile()).create_symlink(link, target, force=force)
    record_link_registry_entry(
        logical_name=link_name,
        link_kind=link_kind,
        path=actual_link,
        target=target,
        status="linked",
        installation_root=installation_root,
        command_name=link_name,
    )
    return actual_link


def _path_contains(path_value: str, entry: Path) -> bool:
    expected = os.path.normcase(os.path.normpath(str(entry)))
    for part in path_value.split(os.pathsep):
        candidate = part.strip().strip('"')
        if not candidate:
            continue
        if os.path.normcase(os.path.normpath(candidate)) == expected:
            return True
    return False


def _prepend_process_path(entry: Path) -> None:
    current = os.environ.get("PATH") or os.environ.get("Path") or ""
    if _path_contains(current, entry):
        return
    os.environ["PATH"] = str(entry) + (os.pathsep + current if current else "")


def _ensure_windows_user_path_contains(entry: Path) -> str | None:
    if os.name != "nt":
        return None
    _prepend_process_path(entry)
    if os.environ.get("AGENT_MEMORY_TEST_SKIP_USER_PATH_UPDATE", "") in {"1", "true", "True", "yes"}:
        return f"updated current process PATH with {entry}"
    try:
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            value_name = "Path"
            try:
                current, value_type = winreg.QueryValueEx(key, value_name)
            except FileNotFoundError:
                try:
                    current, value_type = winreg.QueryValueEx(key, "PATH")
                    value_name = "PATH"
                except FileNotFoundError:
                    current, value_type = "", winreg.REG_EXPAND_SZ
            current_text = str(current or "")
            if _path_contains(current_text, entry):
                return f"Windows user PATH already contains {entry}"
            separator = ";" if current_text else ""
            winreg.SetValueEx(key, value_name, 0, value_type or winreg.REG_EXPAND_SZ, f"{entry}{separator}{current_text}")
        try:
            HWND_BROADCAST = 0xFFFF
            WM_SETTINGCHANGE = 0x001A
            SMTO_ABORTIFHUNG = 0x0002
            ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None)
        except Exception:
            pass
        return f"added {entry} to Windows user PATH"
    except Exception as exc:  # noqa: BLE001
        return f"warn: could not update Windows user PATH with {entry}: {exc}"


def remove_command_link(link_dir: Path, link_name: str, *, installation_root: Path | None = None) -> Path:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_command_publisher

    link = link_dir / link_name
    actual_link = select_command_publisher(current_platform_profile()).remove_symlink(link)
    record_link_registry_entry(
        logical_name=link_name,
        link_kind="global_wrapper",
        path=actual_link,
        target=None,
        status="removed",
        installation_root=installation_root,
        command_name=link_name,
    )
    return actual_link


def global_wrapper_command_name(wrapper_name: str, args: argparse.Namespace) -> str:
    return link_command_name(wrapper_name, install_wrapper_prefix(args), install_wrapper_suffix(args))


def ensure_global_wrapper_link(link_dir: Path, wrapper_name: str, target_root: Path, *, force: bool, prefix: str, suffix: str = "") -> Path:
    target = wrapper_script_path(target_root, wrapper_name)
    if not target.exists():
        raise FileNotFoundError(f"missing wrapper script: {target}")
    link_name = link_command_name(wrapper_name, prefix, suffix)
    return create_command_link(
        link_dir,
        link_name,
        target,
        force=force,
        link_kind="global_wrapper",
        installation_root=target_root,
    )


def ensure_global_cli_link(link_dir: Path, target_root: Path, *, force: bool) -> Path:
    return create_command_link(
        link_dir,
        GLOBAL_CLI_COMMAND_NAME,
        agent_memory_cli_path_for_root(target_root),
        force=force,
        link_kind="global_cli",
        installation_root=target_root,
    )


def cmd_install(args: argparse.Namespace) -> int:
    discovery_summary: dict[str, object] | None = None
    discovered_plan: dict[str, object] | None = None
    if getattr(args, "plan_json", None):
        try:
            discovered_plan = _load_install_plan(str(args.plan_json))
            _apply_install_plan(args, discovered_plan)
            args.no_interactive = True
            args._guided_target_inferred = False
        except (OSError, ValueError, TypeError) as exc:
            print(f"error: failed to load install plan {args.plan_json}: {exc}", file=sys.stderr)
            return 2
    if not args.target:
        summary = _discovery_summary(
            start=Path.cwd(),
            memory_root_hint=getattr(args, "memory_root", None),
            language_hint=getattr(args, "language", None),
        )
        if getattr(args, "isolated", False):
            summary = _apply_isolated_discovery_overrides(summary)
        discovery_summary = summary
        args._guided_target_inferred = True
        language = normalize_language(str(summary.get("reply_language") or "en"))
        if not sys.stdin.isatty() or getattr(args, "no_interactive", False):
            print(_render_install_discovery(summary, language=language))
            print("")
            print(
                _ui_text(
                    language,
                    en="Agent bootstrap: use the recommended command below, then run doctor and check-installation.",
                    de="Agent-Bootstrap: Nutze den empfohlenen Befehl unten und pruefe danach mit doctor und check-installation.",
                )
            )
            print("")
            print(_ui_text(language, en="recommended command:", de="empfohlener Befehl:"))
            print(_recommended_install_command(summary))
            return 2

        print(_render_install_discovery(summary, language=language))
        print("")
        args.target = str(summary["target_root"])
        if not args.language:
            try:
                args.language = ask_preferred_language(language, language=language)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                return 2
        if not getattr(args, "memory_root", None) and summary.get("recommended_memory_root") and not getattr(args, "isolated", False):
            suggested_source = _recommended_memory_root_source_text(str(summary.get("recommended_memory_root_source") or ""))
            use_memory_root = ask_yes_no(
                _ui_text(
                    normalize_language(args.language),
                    en=f"Use the suggested memory root {summary['recommended_memory_root']} ({suggested_source})?",
                    de=f"Den vorgeschlagenen Memory-Root {summary['recommended_memory_root']} ({suggested_source}) verwenden?",
                ),
                default=True,
            )
            if use_memory_root:
                args.memory_root = str(summary["recommended_memory_root"])
        if getattr(args, "monitor_port", None) is None and int(summary["recommended_monitor_port"]) != DEFAULT_MONITOR_PORT:
            use_port = ask_yes_no(
                _ui_text(
                    normalize_language(args.language),
                    en=f"Use monitor port {summary['recommended_monitor_port']} for this installation?",
                    de=f"Monitor-Port {summary['recommended_monitor_port']} fuer diese Installation verwenden?",
                ),
                default=True,
            )
            if use_port:
                args.monitor_port = int(summary["recommended_monitor_port"])
        if not getattr(args, "wrapper_suffix", None) and str(summary.get("recommended_wrapper_suffix") or "").strip():
            use_suffix = ask_yes_no(
                _ui_text(
                    normalize_language(args.language),
                    en=f"Use wrapper suffix {summary['recommended_wrapper_suffix']} to keep commands isolated?",
                    de=f"Wrapper-Suffix {summary['recommended_wrapper_suffix']} fuer isolierte Befehle verwenden?",
                ),
                default=True,
            )
            if use_suffix:
                args.wrapper_suffix = str(summary["recommended_wrapper_suffix"])
        if getattr(args, "install_launchagent", True) and not bool(summary.get("recommended_install_launchagent", True)):
            from ....application.platform import current_platform_profile

            scheduler_name = _scheduler_display_name(current_platform_profile())
            args.install_launchagent = ask_yes_no(
                _ui_text(
                    normalize_language(args.language),
                    en=f"Install and load the {scheduler_name} now?",
                    de=f"{scheduler_name} jetzt installieren und aktivieren?",
                ),
                default=False,
            )
    if discovery_summary is None:
        discovery_summary = _discovery_summary(
            start=Path.cwd(),
            target_hint=Path(args.target).expanduser().resolve() if getattr(args, "target", None) else None,
            memory_root_hint=getattr(args, "memory_root", None),
            language_hint=getattr(args, "language", None),
        )
        if getattr(args, "isolated", False):
            discovery_summary = _apply_isolated_discovery_overrides(discovery_summary)
    try:
        language = normalize_language(args.language)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not args.no_interactive and not args.language:
        try:
            language = ask_preferred_language(language, language=language)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    target = Path(args.target).expanduser().resolve()
    install_plan = discovered_plan or _guided_install_plan(discovery_summary, args)
    replace_existing_global_links = bool(install_plan.get("replace_existing_global_links"))
    isolated_install = bool(install_plan.get("isolated"))
    detected_source_checkout = str(install_plan.get("detected_source_checkout") or "")
    if str(install_plan.get("checkout_role") or "") == "public_checkout" and detected_source_checkout:
        if target.resolve() == Path(detected_source_checkout).expanduser().resolve() and not getattr(args, "force", False):
            print(
                _ui_text(
                    language,
                    en=(
                        "error: refusing to install into the detected source checkout from this public checkout. "
                        "Use the current public checkout as --target, or rerun with --force if this cross-checkout mutation is truly intended."
                    ),
                    de=(
                        "Fehler: Aus diesem Public-Checkout wird nicht stillschweigend in das erkannte Source-Checkout installiert. "
                        "Nutze das aktuelle Public-Checkout als --target oder starte bewusst mit --force neu, wenn diese Cross-Checkout-Mutation wirklich gewollt ist."
                    ),
                ),
                file=sys.stderr,
            )
            return 2
    try:
        workflow_settings = {key: _normalize_workflow_runner(key, getattr(args, key, None)) for key in WORKFLOW_RUNNER_DEFAULTS}
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not args.no_interactive:
        try:
            for key in WORKFLOW_RUNNER_DEFAULTS:
                if getattr(args, key, None) is None:
                    workflow_settings[key] = ask_workflow_runner(key, workflow_settings[key], language=language)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    workspace_roots = _workspace_root_overrides(args)
    conflicts = managed_install_conflicts(target)
    if conflicts and not args.force:
        if not args.no_interactive and sys.stdin.isatty():
            print("", file=sys.stderr)
            print_install_conflicts(target, conflicts)
            refresh_in_place = ask_yes_no(
                _ui_text(
                    language,
                    en="Refresh this existing installation in place?",
                    de="Diese bestehende Installation an Ort und Stelle aktualisieren?",
                ),
                default=False,
            )
            if not refresh_in_place:
                return 2
            args.force = True
        else:
            return print_install_conflicts(target, conflicts)
    if not args.no_interactive and sys.stdin.isatty():
        print("")
        print(_render_install_plan(discovery_summary, args, language=language))
        print("")
        proceed = ask_yes_no(
            _ui_text(
                language,
                en="Proceed with this installation plan? Agents: answer yes only after explicit user chat approval.",
                de="Diesen Installationsplan jetzt ausfuehren? Agenten: Ja nur nach ausdruecklicher Chat-Freigabe des Nutzers.",
            ),
            default=False,
        )
        if not proceed:
            print(
                _ui_text(
                    language,
                    en="installation cancelled before writing files",
                    de="Installation vor dem Schreiben von Dateien abgebrochen",
                ),
                file=sys.stderr,
            )
            return 2
    target.mkdir(parents=True, exist_ok=True)
    if isolated_install and not getattr(args, "memory_root", None):
        args.memory_root = str(_isolated_default_memory_root(target))
    if isolated_install and not getattr(args, "instance_name", None):
        args.instance_name = _isolated_instance_name_for_target(target)
    runtime_memory_root = _default_storage_root_for_install(target, args)
    installed_skill = copy_skill_package(target)
    cli_path = agent_memory_cli_path_for_root(target)
    script_rel = agent_memory_script_for_root(target)
    command_prefix = agent_memory_cli_for_root(target) if isolated_install else GLOBAL_CLI_COMMAND_NAME
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    monitor_host = str(getattr(args, "monitor_host", None) or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = int(getattr(args, "monitor_port", None) or DEFAULT_MONITOR_PORT)
    user_config = load_user_config()
    resolved_monitor_port, monitor_port_adjust_reason = _resolve_final_monitor_port(
        checkout_root=_checkout_root_from_path(Path.cwd()),
        target_root=target,
        target_memory_root=runtime_memory_root,
        host=monitor_host,
        requested_port=monitor_port,
        user_config=user_config,
    )
    if resolved_monitor_port != monitor_port:
        print(
            _ui_text(
                language,
                en=(
                    f"monitor port adjusted before install: {monitor_host}:{monitor_port} -> "
                    f"{monitor_host}:{resolved_monitor_port} ({monitor_port_adjust_reason})"
                ),
                de=(
                    f"Monitor-Port vor der Installation angepasst: {monitor_host}:{monitor_port} -> "
                    f"{monitor_host}:{resolved_monitor_port} ({monitor_port_adjust_reason})"
                ),
            )
        )
        monitor_port = resolved_monitor_port
    default_launchagent = _default_launchagent_profile_for_target(
        checkout_role="unknown_checkout",
        target_root=target,
        memory_root=runtime_memory_root,
    )
    launchagent_label = str(getattr(args, "launchagent_label", None) or default_launchagent["label"]).strip() or default_launchagent["label"]
    launchagent_path = (
        str(getattr(args, "launchagent_path", None) or _expected_launchagent_plist_path(launchagent_label)).strip()
        or _expected_launchagent_plist_path(launchagent_label)
    )
    launchagent_env_file = str(getattr(args, "launchagent_env_file", None) or default_launchagent["env_file"]).strip() or default_launchagent["env_file"]
    script_abs = str((target / script_rel).resolve())
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_hook_adapter_renderer
    hook_renderer = select_hook_adapter_renderer(current_platform_profile())
    agents_path = ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry_path = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=target)
    entrypoints = ensure_harness_entrypoints(target)
    _materialize_windows_cli_and_wrappers(script_root=cli_path.parent, installation_root=target)
    user_cli_link: Path | None = None
    if not isolated_install:
        try:
            user_cli_link = ensure_user_cli_link(target, force=bool(args.force or replace_existing_global_links))
        except FileExistsError as exc:
            print(str(exc), file=sys.stderr)
            return 1
    for path in [
        installed_skill / "scripts" / "agent-context-engine",
        installed_skill / "scripts" / "agent-context-engine.cmd",
        installed_skill / "scripts" / "codex-ace",
        installed_skill / "scripts" / "codex-ace.cmd",
        installed_skill / "scripts" / "claude-ace",
        installed_skill / "scripts" / "claude-ace.cmd",
        installed_skill / "scripts" / "cursor-ace",
        installed_skill / "scripts" / "cursor-ace.cmd",
        installed_skill / "scripts" / "agy-ace",
        installed_skill / "scripts" / "agy-ace.cmd",
        installed_skill / "scripts" / "antigravity-ace",
        installed_skill / "scripts" / "antigravity-ace.cmd",
        installed_skill / "scripts" / "gemini-ace",
        installed_skill / "scripts" / "gemini-ace.cmd",
        installed_skill / "scripts" / "opencode-ace",
        installed_skill / "scripts" / "opencode-ace.cmd",
    ]:
        if path.exists():
            _mark_platform_executable(path)
    runtime_bootstrap_ok = True
    skip_runtime_bootstrap = os.environ.get("AGENT_MEMORY_TEST_SKIP_RUNTIME_BOOTSTRAP", "") in {"1", "true", "True", "yes"}
    if getattr(args, "bootstrap_runtime", False) and not skip_runtime_bootstrap:
        try:
            for action in ensure_runtime_venv(target, install_backend_dependencies=True):
                print(f"runtime bootstrap: {action}")
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            runtime_bootstrap_ok = False
            print(
                f"warn: runtime bootstrap failed; run `{agent_memory_cli_for_root(target)} repair-installation --apply` later: {exc}"
                + _runtime_bootstrap_failure_hint(exc),
                file=sys.stderr,
            )
    frontend_build_ok = True
    if os.environ.get("AGENT_MEMORY_TEST_SKIP_FRONTEND_BUILD", "") not in {"1", "true", "True", "yes"}:
        try:
            for action in ensure_monitor_frontend_build(
                target,
                install_dependencies=True,
                force=False,
            ):
                print(f"monitor frontend: {action}")
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            frontend_build_ok = False
            print(
                f"warn: monitor frontend build failed; run `{agent_memory_cli_for_root(target)} repair-installation --apply --install-frontend-deps` later: {exc}"
                + _frontend_build_failure_hint(target),
                file=sys.stderr,
            )
    instance_id = _default_instance_id_for_target(target, args)
    ensure_storage_profile(runtime_memory_root, schema_version=int(getattr(args, "storage_schema_version", None) or DEFAULT_STORAGE_SCHEMA_VERSION), storage_instance_id=instance_id)
    merge_installation_profile(
        target,
        instance_id=instance_id,
        root_path=target,
        installation_mode="isolated" if isolated_install else "shared",
        storage={
            "memory_root": runtime_memory_root,
            "schema_version": int(getattr(args, "storage_schema_version", None) or DEFAULT_STORAGE_SCHEMA_VERSION),
            "managed_by_installation": True,
            "attached_at": _utc_timestamp(),
        },
        workflows=workflow_settings,
        workspace_roots=workspace_roots,
        wrapper_naming={"prefix": prefix, "suffix": suffix},
        monitor={"host": monitor_host, "port": monitor_port, "language": language},
        launchagent={"label": launchagent_label, "path": launchagent_path, "env_file": launchagent_env_file},
    )
    repos_index = ensure_repos_runtime_index(target, args.project or [], interactive=not args.no_interactive, language=language)
    merge_user_config(
        default_language=language,
        default_monitor_host=None if isolated_install else monitor_host,
        default_monitor_port=None if isolated_install else monitor_port,
        default_wrapper_prefix=None if isolated_install else prefix,
        default_wrapper_suffix=None if isolated_install else suffix,
        default_launchagent_enabled=None if isolated_install else bool(args.install_launchagent),
        default_memory_root=None if isolated_install else runtime_memory_root,
        last_used_installation_root=target,
        last_used_memory_root=runtime_memory_root,
    )
    instance_metadata = sync_instance_metadata(target)
    linked_wrapper_specs = _linked_wrapper_specs(args)
    link_dir = Path(args.link_dir).expanduser().resolve()
    link_dir.mkdir(parents=True, exist_ok=True)
    global_cli_link: Path | None = None
    if not isolated_install:
        try:
            global_cli_link = ensure_global_cli_link(link_dir, target, force=bool(args.force or replace_existing_global_links))
        except (FileExistsError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"linked {global_cli_link} -> {agent_memory_cli_path_for_root(target)}")
    for flag_name, wrapper_name in [
        ("link_codex_memory", "codex-ace"),
        ("link_claude_memory", "claude-ace"),
        ("link_cursor_memory", "cursor-ace"),
        ("link_agy_memory", "agy-ace"),
        ("link_antigravity_memory", "antigravity-ace"),
        ("link_gemini_memory", "gemini-ace"),
        ("link_opencode_memory", "opencode-ace"),
    ]:
        if not _link_flag_enabled(args, flag_name, default=wrapper_name != "antigravity-ace"):
            continue
        try:
            link = ensure_global_wrapper_link(
                link_dir,
                wrapper_name,
                installed_skill / "scripts" / "..",
                force=bool(args.force or replace_existing_global_links),
                prefix=prefix,
                suffix=suffix,
            )
        except (FileExistsError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"linked {link} -> {installed_skill / 'scripts' / wrapper_name}")
    path_update = _ensure_windows_user_path_contains(link_dir)
    if path_update:
        print(path_update)
    print(f"installed agent-context-engine into {target}")
    print(f"install mode: {install_plan['install_mode']}")
    if args.instance_name:
        print(f"instance: {safe_slug(args.instance_name)}")
    print(f"preferred interaction language: {LANGUAGE_LABELS.get(language, language)}")
    from ....application.platform import CapabilityStatus, current_platform_profile
    from ....application.platform.runtime_summary import runtime_selection_summary
    platform_profile = current_platform_profile()
    runtime_selection = runtime_selection_summary(platform_profile)
    scheduler_capability = platform_profile.capability("scheduler_backend")
    scheduler_name = _scheduler_display_name(platform_profile)
    print(
        "platform profile: "
        + f"{platform_profile.profile_id} support={platform_profile.support_level.value} evidence={platform_profile.evidence.value}"
    )
    print(
        "selected runtime adapters: "
        + f"instruction_renderer={((runtime_selection.get('instruction_renderer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"hook_renderer={((runtime_selection.get('hook_renderer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"wrapper_renderer={((runtime_selection.get('wrapper_renderer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"command_publisher={((runtime_selection.get('command_publisher') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"executable_permission_adapter={((runtime_selection.get('executable_permission_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"system_open_adapter={((runtime_selection.get('system_open_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"process_launch_adapter={((runtime_selection.get('process_launch_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"workspace_binding_adapter={((runtime_selection.get('workspace_binding_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"path_quoting_adapter={((runtime_selection.get('path_quoting_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"scheduler_installer={((runtime_selection.get('scheduler_installer') or {}).get('name') if isinstance(runtime_selection, dict) else '')}"
    )
    print("configured workflows:")
    for key in WORKFLOW_RUNNER_DEFAULTS:
        print(f"- {WORKFLOW_LABELS[key]}: {workflow_settings[key]}")
    print(f"wrapper naming: prefix={prefix or '-'} suffix={suffix or '-'}")
    print(f"monitor default: {monitor_host}:{monitor_port} language={language}")
    print(f"memory root: {runtime_memory_root}")
    print(f"storage schema version: {int(getattr(args, 'storage_schema_version', None) or DEFAULT_STORAGE_SCHEMA_VERSION)}")
    print(f"launchagent default: label={launchagent_label} path={launchagent_path} env_file={launchagent_env_file}")
    print(f"installation profile: {installation_profile_path(target)}")
    print(f"user config: {user_config_path()}")
    print(f"instance metadata: {instance_metadata_path_for_root(target)}")
    if str(instance_metadata.get("installed_at") or "").strip():
        print(
            "installed at: "
            + f"{instance_metadata.get('installed_at')} "
            + f"(version={instance_metadata.get('installed_by_version') or '-'})"
        )
    if str(instance_metadata.get("last_updated_at") or "").strip():
        print(
            "last updated at: "
            + f"{instance_metadata.get('last_updated_at')} "
            + f"(version={instance_metadata.get('last_updated_by_version') or '-'})"
        )
    print(f"link registry: {link_registry_path()}")
    print(f"global cli command: {global_cli_link or '-'}")
    print(f"user cli shortcut: {user_cli_link or '-'}")
    print(f"updated agent instructions: {agents_path}")
    print(f"updated hook entry: {hook_entry_path}")
    print(f"repo index: {repos_index}")
    repo_entries = _repo_index_entries_from_text(repos_index.read_text(encoding="utf-8", errors="replace")) if repos_index.exists() else []
    print(f"recognized repos/folders: {len(repo_entries)}")
    if repo_entries:
        print("repo examples: " + ", ".join(repo_entries[:5]))
    print(
        "monitor repo knowledge: "
        + _ui_text(language, en="Personal -> Repo-Index", de="Persoenlich -> Repo-Index")
    )
    print(
        "later repo/folder updates: "
        + _ui_text(
            language,
            en="agents can add or edit entries in the monitor Repo-Index panel; install also accepts repeated --project name=/absolute/path",
            de="Agents koennen Eintraege spaeter im Monitor-Panel Repo-Index ergaenzen oder bearbeiten; die Installation akzeptiert ausserdem wiederholte --project name=/absoluter/pfad",
        )
    )
    for path in entrypoints:
        print(f"updated harness entrypoint: {path}")
    scheduler_install_ok = True
    if args.install_launchagent and scheduler_capability is not None and scheduler_capability.status == CapabilityStatus.SUPPORTED:
        if not isolated_install and scheduler_capability.implementation == "launchagent":
            for action in _stop_superseded_launchagents_for_memory_root(target=target, memory_root=runtime_memory_root):
                print(action)
        scheduler_install = subprocess.run(
            [str(cli_path), *_scheduler_install_subcommand_args(
                profile=platform_profile,
                launchagent_label=launchagent_label,
                launchagent_path=launchagent_path,
                launchagent_env_file=launchagent_env_file,
            )],
            cwd=str(target),
            text=True,
            capture_output=True,
            check=False,
        )
        if scheduler_install.returncode == 0:
            print(f"installed and loaded {scheduler_name}")
        else:
            scheduler_install_ok = False
            message = scheduler_install.stderr.strip() or scheduler_install.stdout.strip()
            print(f"warn: {scheduler_name} install failed; run manually if needed: {message}", file=sys.stderr)
    elif args.install_launchagent:
        scheduler_install_ok = False
        print(
            f"warn: {scheduler_name} install skipped on this platform profile: "
            + f"profile={platform_profile.profile_id} status={scheduler_capability.status.value if scheduler_capability else 'unsupported'} "
            + f"support={scheduler_capability.support_level.value if scheduler_capability else platform_profile.support_level.value} "
            + f"evidence={scheduler_capability.evidence.value if scheduler_capability else platform_profile.evidence.value}",
            file=sys.stderr,
        )
    else:
        print(
            "next: run "
            + _scheduler_install_command(
                root=target,
                profile=platform_profile,
                launchagent_label=launchagent_label,
                launchagent_path=launchagent_path,
                launchagent_env_file=launchagent_env_file,
            )
        )
    installation_ready_for_activation = runtime_bootstrap_ok and frontend_build_ok and scheduler_install_ok
    monitor_start_status = "not_requested"
    if (
        getattr(args, "start_monitor", True)
        and installation_ready_for_activation
        and os.environ.get("AGENT_MEMORY_TEST_SKIP_MONITOR_START", "") not in {"1", "true", "True", "yes"}
    ):
        started, detail = _autostart_monitor_after_install(
            target,
            runner=workflow_settings["monitor_runner"],
            host=monitor_host,
            port=monitor_port,
            language=language,
            memory_root=runtime_memory_root,
        )
        if started:
            monitor_start_status = "verified"
            print(f"started monitor: {detail}")
            _open_monitor_howto(host=monitor_host, port=monitor_port, runner=workflow_settings["monitor_runner"], language=language)
        else:
            monitor_start_status = "failed"
            print(
                "warn: monitor start failed; run manually if needed: "
                + f"{detail}; command={monitor_restart_command(target, runner=workflow_settings['monitor_runner'])}",
                file=sys.stderr,
            )
            installation_ready_for_activation = False
    elif getattr(args, "start_monitor", True) and not installation_ready_for_activation:
        monitor_start_status = "skipped_incomplete_prerequisites"
        print(
            "warn: monitor start skipped because installation prerequisites are incomplete: "
            + f"runtime_bootstrap_ok={runtime_bootstrap_ok} frontend_build_ok={frontend_build_ok} "
            + f"scheduler_install_ok={scheduler_install_ok}",
            file=sys.stderr,
        )
    else:
        if getattr(args, "start_monitor", True):
            monitor_start_status = "skipped_by_test_environment"
        print("next: run " + monitor_restart_command(target, runner=workflow_settings["monitor_runner"]))
    if installation_ready_for_activation:
        for hub_action in _ensure_central_hub_and_active_root(
            target,
            metadata_root=runtime_memory_root,
            publish_shared_active_root=not isolated_install,
        ):
            print(f"- {hub_action}")
        try:
            activated_hook_paths = _activate_installation_hooks(
                target=target,
                runtime_memory_root=runtime_memory_root,
                script_abs=script_abs,
                hook_renderer=hook_renderer,
                workspace_roots=workspace_roots,
            )
        except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
            installation_ready_for_activation = False
            print(f"warn: installation hook/global bridge finalization failed: {exc}", file=sys.stderr)
        else:
            if activated_hook_paths:
                print(f"activated hooks as final install step: {len(activated_hook_paths)} files")
    else:
        print(
            "warn: hook activation skipped because installation is not complete; rerun install or repair-installation after fixing prerequisites",
            file=sys.stderr,
        )
    verification = _run_post_install_checks(
        target,
        language=language,
        include_doctor=installation_ready_for_activation,
    )
    print(f"next: run {agent_memory_cli_for_root(target)} doctor")
    wrapper_link_results = _verify_global_wrapper_links(args=args, prefix=prefix, suffix=suffix)
    if wrapper_link_results:
        print("global wrapper verification:")
        for item in wrapper_link_results:
            print(
                f"- {item['command_name']}: "
                + f"link_exists={item['link_exists']} "
                + f"link_path={item['link_path']} "
                + f"resolved={item['path_resolved'] or '-'}"
            )
            if item["link_exists"] == "yes" and not item["path_resolved"]:
                print(
                    f"warn: {item['command_name']} is linked but not currently resolvable from PATH; "
                    + f"ensure {Path(args.link_dir).expanduser().resolve()} is on PATH",
                    file=sys.stderr,
                )
    start_hints = _wrapper_start_hints(target, args)
    print("next: start " + ", ".join(start_hints))
    if installation_ready_for_activation:
        print("info: /hooks can be used inside Codex to inspect installed hooks; approve any Codex hook safety review if shown")
    print(
        _ui_text(
            language,
            en=(
                f"installation summary: target={target} memory_root={runtime_memory_root} "
                f"monitor_port={monitor_port} monitor_start={monitor_start_status} "
                f"wrapper_prefix={prefix or '-'} wrapper_suffix={suffix or '-'}"
            ),
            de=(
                f"Installationszusammenfassung: target={target} memory_root={runtime_memory_root} "
                f"monitor_port={monitor_port} monitor_start={monitor_start_status} "
                f"wrapper_prefix={prefix or '-'} wrapper_suffix={suffix or '-'}"
            ),
        )
    )
    installation_success = installation_ready_for_activation and all(
        int(value) == 0 for value in verification.values()
    )
    print(
        _ui_text(
            language,
            en=(
                "installation result: success"
                if installation_success
                else "installation result: completed with warnings; review the verification summary above"
            ),
            de=(
                "Installationsergebnis: erfolgreich"
                if installation_success
                else "Installationsergebnis: mit Warnungen abgeschlossen; Verifikationszusammenfassung oben pruefen"
            ),
        )
    )
    return 0 if installation_success else 2


def cmd_attach_memory_root(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    memory_root = Path(str(args.memory_root)).expanduser().resolve()
    profile = load_installation_profile(root)
    current_storage_root = Path(str(resolve_storage_profile(root).get("memory_root") or (root / "memory"))).expanduser().resolve()
    schema_version = int(getattr(args, "storage_schema_version", None) or resolve_storage_profile(root).get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION)
    migrated_actions = _relocate_runtime_storage(current_storage_root, memory_root)
    ensure_storage_profile(memory_root, schema_version=schema_version, storage_instance_id=str(profile.get("instance_id") or root.name))
    launchagent_profile = normalize_launchagent_profile(dict(profile.get("launchagent") or {}))
    launchagent_env_file = str(launchagent_profile.get("env_file") or "")
    if _should_rewrite_launchagent_env_file(launchagent_env_file, old_memory_root=current_storage_root):
        launchagent_env_file = _default_launchagent_env_file_for_storage(memory_root)
    merge_installation_profile(
        root,
        storage={
            "memory_root": memory_root,
            "schema_version": schema_version,
            "managed_by_installation": True,
            "attached_at": _utc_timestamp(),
        },
        launchagent={"env_file": launchagent_env_file},
    )
    merge_user_config(
        default_memory_root=memory_root,
        last_used_installation_root=root,
        last_used_memory_root=memory_root,
    )
    sync_instance_metadata(root)
    print(f"installation root: {root}")
    print(f"attached memory root: {memory_root}")
    print(f"storage schema version: {schema_version}")
    print(f"storage profile: {storage_profile_path(memory_root)}")
    for action in migrated_actions:
        print(f"storage migration: {action}")
    print(f"user config: {user_config_path()}")
    print(f"instance metadata: {instance_metadata_path_for_root(root)}")
    print(f"launchagent env file: {launchagent_env_file}")
    print(f"next: run {agent_memory_cli_for_root(root)} doctor")
    print(f"next: run {agent_memory_cli_for_root(root)} check-installation")
    return 0


def cmd_migrate_storage(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    storage = resolve_storage_profile(root)
    memory_root = Path(str(storage.get("memory_root") or (root / "memory"))).expanduser().resolve()
    schema_version = int(getattr(args, "storage_schema_version", None) or storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION)
    profile = ensure_storage_profile(memory_root, schema_version=schema_version, storage_instance_id=str(load_installation_profile(root).get("instance_id") or root.name))
    merge_installation_profile(root, storage={"memory_root": memory_root, "schema_version": schema_version, "attached_at": str(storage.get("attached_at") or _utc_timestamp())})
    merge_user_config(
        default_memory_root=memory_root,
        last_used_installation_root=root,
        last_used_memory_root=memory_root,
    )
    sync_instance_metadata(root)
    print(f"installation root: {root}")
    print(f"memory root: {memory_root}")
    print(f"storage profile: {storage_profile_path(memory_root)}")
    print(f"user config: {user_config_path()}")
    print(f"instance metadata: {instance_metadata_path_for_root(root)}")
    print(f"storage schema version: {profile['schema_version']}")
    print("migration status: no schema migration required; metadata synchronized")
    return 0


def cmd_global_wrapper_enable(args: argparse.Namespace) -> int:
    link_dir = Path(args.link_dir).expanduser().resolve()
    link_dir.mkdir(parents=True, exist_ok=True)
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    wrapper_name = _normalize_wrapper_script_name(args.wrapper)
    try:
        link = ensure_global_wrapper_link(link_dir, wrapper_name, ROOT, force=args.force, prefix=prefix, suffix=suffix)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"linked {link} -> {wrapper_script_path(ROOT, wrapper_name)}")
    print(f"global command: {link_command_name(wrapper_name, prefix, suffix)}")
    append_integration_history(
        client=wrapper_name,
        action="global_wrapper_enabled",
        root=ROOT,
        source="cli",
        actor="agent-memory-cli",
        details={"link": str(link), "command_name": link_command_name(wrapper_name, prefix, suffix)},
    )
    return 0


def cmd_global_wrapper_disable(args: argparse.Namespace) -> int:
    link_dir = Path(args.link_dir).expanduser().resolve()
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    wrapper_name = _normalize_wrapper_script_name(args.wrapper)
    link_name = link_command_name(wrapper_name, prefix, suffix)
    link = remove_command_link(link_dir, link_name, installation_root=ROOT)
    print(f"removed global wrapper link: {link}")
    append_integration_history(
        client=wrapper_name,
        action="global_wrapper_disabled",
        root=ROOT,
        source="cli",
        actor="agent-memory-cli",
        details={"link": str(link), "command_name": link_name},
    )
    return 0


def cmd_global_wrapper_status(args: argparse.Namespace) -> int:
    link_dir = Path(args.link_dir).expanduser().resolve()
    profile = load_installation_profile(ROOT)
    registry = dict((load_link_registry().get("entries") or {}))
    wrapper_naming = dict(profile.get("wrapper_naming") or {})
    prefix = str(wrapper_naming.get("prefix") or "")
    suffix = str(wrapper_naming.get("suffix") or "")
    for wrapper_name in GLOBAL_WRAPPERS:
        configured_name = link_command_name(wrapper_name, prefix, suffix)
        command = shutil.which(configured_name)
        local_link = link_dir / configured_name
        print(f"{configured_name}:")
        print(f"  wrapper_script: {wrapper_name}")
        print(f"  configured_command: {configured_name}")
        print(f"  path_linked: {'yes' if command else 'no'}")
        print(f"  resolved: {command or '-'}")
        print(f"  link_dir_entry: {local_link if local_link.exists() or local_link.is_symlink() else '-'}")
        print(f"  root_wrapper: {wrapper_script_path(ROOT, wrapper_name)}")
        metadata = dict(registry.get(configured_name) or {})
        print(f"  linked_at: {metadata.get('created_at') or '-'}")
        print(f"  last_changed_at: {metadata.get('updated_at') or '-'}")
        print(f"  last_changed_by_version: {metadata.get('changed_by_version') or '-'}")
        print(f"  registry_status: {metadata.get('status') or '-'}")
        print(f"  registry_target: {metadata.get('target') or '-'}")
    return 0
