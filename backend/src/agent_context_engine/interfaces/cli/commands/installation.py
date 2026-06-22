from __future__ import annotations

import argparse
import json
import os
import re
import socket
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

from ....infrastructure.config import DEFAULT_STORAGE_SCHEMA_VERSION, ROOT, SKILL_ROOT, safe_slug, sh_quote
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
    default_instance_install_root,
    default_user_storage_root,
    ensure_storage_profile,
    instance_metadata_path_for_root,
    installation_profile_path,
    load_installation_profile,
    load_user_config,
    load_storage_profile,
    merge_user_config,
    merge_installation_profile,
    monitor_restart_command,
    resolve_storage_profile,
    storage_profile_path,
    sync_instance_metadata,
    user_config_path,
)
from ....adapters.launchagent import DEFAULT_ENV_FILE, DEFAULT_LABEL, launch_agent_path, launchagent_runtime_status
from ....application.integrations import (
    antigravity_status,
    append_integration_history,
    ensure_antigravity_project,
    ensure_gemini_project,
    ensure_opencode_project,
    gemini_status,
    integration_hook_command,
    integration_summary,
    manage_integration_hooks,
    opencode_status,
    shell_hook_adapter_status,
    workspace_binding_status,
    write_workspace_binding,
)
from ....application.hooks_state import hooks_control_status, set_hooks_enabled


def copy_text(src: Path, dest: Path, replacements: dict[str, str] | None = None) -> None:
    text = src.read_text(encoding="utf-8")
    for key, value in (replacements or {}).items():
        text = text.replace(key, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")


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


GLOBAL_WRAPPERS = (
    "codex-memory",
    "claude-memory",
    "agy-memory",
    "gemini-memory",
    "opencode-memory",
)

LEGACY_GLOBAL_WRAPPERS = (
    "antigravity-memory",
)

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
    ".claude/settings.json",
    ".claude/hooks/hook_adapter.sh",
    ".agents/hooks.json",
    ".agents/hooks/hook_adapter.sh",
    ".gemini/settings.json",
    ".gemini/hooks/hook_adapter.sh",
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
    if normalized in {"agent-context-engine", "agent-memory-public"}:
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
    if lowered == "agent-context-engine":
        candidate = path.parent / "agent-memory"
        return candidate if candidate.exists() else None
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


def _known_monitor_ports(*, checkout_root: Path, target_root: Path, user_config: dict[str, object]) -> set[tuple[str, int]]:
    reserved: set[tuple[str, int]] = set()
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
        monitor = dict(load_installation_profile(root).get("monitor") or {})
        host = str(monitor.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
        try:
            port = max(1, min(int(monitor.get("port") or DEFAULT_MONITOR_PORT), 65535))
        except (TypeError, ValueError):
            continue
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
    return preferred


def _wrapper_conflicts(*, checkout_root: Path, prefix: str, suffix: str) -> list[dict[str, object]]:
    conflicts: list[dict[str, object]] = []
    for wrapper_name in GLOBAL_WRAPPERS:
        command_name = link_command_name(wrapper_name, prefix, suffix)
        resolved = shutil.which(command_name)
        if not resolved:
            continue
        resolved_path = Path(resolved).expanduser().resolve()
        candidate_target = wrapper_script_path(checkout_root, wrapper_name)
        expected_target = candidate_target.resolve() if candidate_target.exists() else None
        points_to_current = expected_target is not None and resolved_path == expected_target
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


def _launchagent_identity_status(*, label: str, env_file: str, plist_path: str) -> dict[str, object]:
    status = launchagent_runtime_status(label=label, env_file=env_file, plist_path=plist_path)
    return {
        "label": label,
        "plist_path": plist_path,
        "env_file": env_file,
        "installed": bool(status.get("installed")),
        "loaded": bool(status.get("loaded")),
        "drift_detected": bool((status.get("drift") or {}).get("detected")),
        "drift_reasons": list((status.get("drift") or {}).get("reasons") or []),
    }


def _discovery_summary(*, start: Path, target_hint: Path | None = None, memory_root_hint: str | None = None, language_hint: str | None = None) -> dict[str, object]:
    checkout_root = _checkout_root_from_path(start)
    role = _checkout_role(checkout_root)
    if target_hint is not None:
        target_root = target_hint.expanduser().resolve()
    elif role == "existing_installation":
        target_root = checkout_root
    else:
        target_root = _default_home_install_root()
    paired = _paired_checkout(checkout_root)
    memory_candidates = _discovered_memory_root_candidates(checkout_root)
    user_config = load_user_config()
    recommended_memory_root = str(memory_root_hint or "").strip()
    recommended_memory_root_source = "explicit"
    if not recommended_memory_root:
        configured_default_root = str(user_config.get("default_memory_root") or "").strip()
        default_home_root = _default_home_memory_root()
        if configured_default_root:
            recommended_memory_root = str(Path(configured_default_root).expanduser().resolve())
            recommended_memory_root_source = "user_config_default_memory_root"
        else:
            recommended_memory_root = str(default_home_root)
            if (default_home_root / "local" / "storage-profile.json").exists():
                recommended_memory_root_source = "default_home_root_profile"
            elif default_home_root.exists():
                recommended_memory_root_source = "default_home_root_existing"
            else:
                recommended_memory_root_source = "default_home_root"
    language = normalize_language(
        language_hint
        or str(user_config.get("default_language") or "").strip().lower()
        or installation_language_for_target(target=checkout_root, default=_environment_language("en"))
    )
    monitor_host = str(user_config.get("default_monitor_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    try:
        monitor_port = max(1, min(int(user_config.get("default_monitor_port") or DEFAULT_MONITOR_PORT), 65535))
    except (TypeError, ValueError):
        monitor_port = DEFAULT_MONITOR_PORT
    reserved_monitor_ports = _known_monitor_ports(checkout_root=checkout_root, target_root=target_root, user_config=user_config)
    recommended_port = _next_monitor_port(monitor_port, host=monitor_host, reserved_ports=reserved_monitor_ports)
    recommended_wrapper_prefix = str(user_config.get("default_wrapper_prefix") or "").strip()
    recommended_wrapper_suffix = str(user_config.get("default_wrapper_suffix") or "").strip()
    launchagent_recommended = bool(user_config.get("default_launchagent_enabled", True))
    if role == "public_checkout":
        if not recommended_wrapper_suffix:
            recommended_wrapper_suffix = _public_wrapper_suffix_for_checkout(checkout_root)
        if recommended_port == monitor_port:
            recommended_port = _next_monitor_port(
                monitor_port + 1,
                host=monitor_host,
                reserved_ports=reserved_monitor_ports,
            )
        launchagent_recommended = False
    current_installation_exists = installation_profile_path(target_root).exists()
    if current_installation_exists:
        recommended_install_mode = "repair_existing_installation"
    elif recommended_memory_root_source in {"default_home_root", "explicit"} and not Path(recommended_memory_root).exists():
        recommended_install_mode = "fresh_installation"
    elif recommended_memory_root:
        recommended_install_mode = "install_with_existing_memory_root"
    else:
        recommended_install_mode = "fresh_installation"
    launchagent_label = f"{DEFAULT_LABEL.rsplit('.', 1)[0]}.{safe_slug(target_root.name)}" if role in {"public_checkout", "fresh_installation_candidate", "unknown_checkout"} else DEFAULT_LABEL
    fallback_memory_root = Path(recommended_memory_root).expanduser().resolve() if recommended_memory_root else (target_root / "memory").resolve()
    launchagent_env_file = _default_launchagent_env_file_for_storage(fallback_memory_root)
    launchagent_path_text = str(launch_agent_path(launchagent_label))
    wrapper_conflicts = _wrapper_conflicts(checkout_root=checkout_root, prefix=recommended_wrapper_prefix, suffix=recommended_wrapper_suffix)
    launchagent_identity = _launchagent_identity_status(label=launchagent_label, env_file=launchagent_env_file, plist_path=launchagent_path_text)
    recommended_plan = {
        "target_root": str(target_root),
        "memory_root_mode": "attach_existing" if recommended_memory_root else "new",
        "memory_root": recommended_memory_root,
        "monitor_port": recommended_port,
        "wrapper_prefix": recommended_wrapper_prefix,
        "wrapper_suffix": recommended_wrapper_suffix,
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
        "memory_root_candidates": memory_candidates,
        "recommended_memory_root": recommended_memory_root,
        "recommended_memory_root_source": recommended_memory_root_source if recommended_memory_root else "",
        "user_config_path": str(user_config_path()),
        "recommended_monitor_host": monitor_host,
        "recommended_monitor_port": recommended_port,
        "default_monitor_port": monitor_port,
        "recommended_wrapper_prefix": recommended_wrapper_prefix,
        "recommended_wrapper_suffix": recommended_wrapper_suffix,
        "recommended_install_launchagent": launchagent_recommended,
        "wrapper_conflicts": wrapper_conflicts,
        "launchagent_identity": launchagent_identity,
        "recommended_plan": recommended_plan,
        "requires_user_confirmation": True,
    }


def _render_install_discovery(summary: dict[str, object], *, language: str | None = None) -> str:
    lang = normalize_language(language or str(summary.get("reply_language") or "en"))
    lines = [
        _ui_text(lang, en="Installation discovery", de="Installations-Discovery"),
        f"- {_ui_text(lang, en='checkout root', de='Checkout-Root')}: {summary['checkout_root']}",
        f"- {_ui_text(lang, en='checkout role', de='Checkout-Rolle')}: {summary['checkout_role']}",
        f"- {_ui_text(lang, en='recommended mode', de='Empfohlener Modus')}: {summary['recommended_install_mode']}",
        f"- {_ui_text(lang, en='suggested target', de='Vorgeschlagenes Ziel')}: {summary['target_root']}",
        f"- {_ui_text(lang, en='reply language', de='Antwortsprache')}: {summary['reply_language']}",
        f"- {_ui_text(lang, en='suggested monitor port', de='Vorgeschlagener Monitor-Port')}: {summary['recommended_monitor_host']}:{summary['recommended_monitor_port']}",
        f"- {_ui_text(lang, en='suggested wrapper prefix', de='Vorgeschlagenes Wrapper-Prefix')}: {summary['recommended_wrapper_prefix'] or '-'}",
        f"- {_ui_text(lang, en='suggested wrapper suffix', de='Vorgeschlagenes Wrapper-Suffix')}: {summary['recommended_wrapper_suffix'] or '-'}",
        f"- {_ui_text(lang, en='suggested launchagent install', de='Empfohlene LaunchAgent-Installation')}: "
        + _ui_text(lang, en="yes" if summary["recommended_install_launchagent"] else "later", de="ja" if summary["recommended_install_launchagent"] else "spaeter"),
        f"- {_ui_text(lang, en='user confirmation required', de='Nutzerfreigabe erforderlich')}: "
        + _ui_text(lang, en="yes", de="ja"),
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
        lines.append(_ui_text(lang, en="- wrapper conflicts:", de="- Wrapper-Konflikte:"))
        for item in wrapper_conflicts[:5]:
            lines.append(f"  - {item['command_name']} -> {item['resolved_path']}")
    lines.append("")
    lines.append(
        _ui_text(
            lang,
            en="Do not apply the suggested target, memory root, monitor port, wrapper naming, or refresh mode until the user confirms them.",
            de="Vorgeschlagenes Ziel, Memory-Root, Monitor-Port, Wrapper-Namensschema oder Refresh-Modus erst nach ausdruecklicher Nutzerfreigabe anwenden.",
        )
    )
    return "\n".join(lines)


def _guided_install_plan(summary: dict[str, object], args: argparse.Namespace) -> dict[str, object]:
    target_root = Path(str(args.target or summary["target_root"])).expanduser().resolve()
    inferred_target = bool(getattr(args, "_guided_target_inferred", False))
    explicit_memory_root = str(getattr(args, "memory_root", None) or "").strip()
    discovered_memory_root = str(summary.get("recommended_memory_root") or "").strip() if inferred_target else ""
    memory_root_text = explicit_memory_root or discovered_memory_root
    monitor_port = int(getattr(args, "monitor_port", None) or summary["recommended_monitor_port"])
    wrapper_prefix = str(getattr(args, "wrapper_prefix", None) or summary.get("recommended_wrapper_prefix") or "").strip()
    wrapper_suffix = str(getattr(args, "wrapper_suffix", None) or summary.get("recommended_wrapper_suffix") or "").strip()
    install_launchagent = bool(getattr(args, "install_launchagent", summary.get("recommended_install_launchagent", True)))
    language = normalize_language(str(getattr(args, "language", None) or summary.get("reply_language") or "en"))
    install_mode = str(summary.get("recommended_install_mode") or "fresh_installation")
    if installation_profile_path(target_root).exists():
        install_mode = "repair_existing_installation"
    elif memory_root_text:
        install_mode = "install_with_existing_memory_root"
    return {
        "target_root": str(target_root),
        "memory_root_mode": "attach_existing" if memory_root_text else "new",
        "memory_root": memory_root_text,
        "monitor_port": monitor_port,
        "wrapper_prefix": wrapper_prefix,
        "wrapper_suffix": wrapper_suffix,
        "install_launchagent": install_launchagent,
        "language": language,
        "install_mode": install_mode,
        "detected_source_checkout": str(summary.get("detected_source_checkout") or ""),
        "checkout_role": str(summary.get("checkout_role") or ""),
        "requires_user_confirmation": bool(summary.get("requires_user_confirmation", True)),
    }


def _effective_memory_root_for_plan(target_root: Path, args: argparse.Namespace, summary: dict[str, object]) -> Path:
    explicit = str(getattr(args, "memory_root", None) or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    recommended = str(summary.get("recommended_memory_root") or "").strip()
    if recommended:
        return Path(recommended).expanduser().resolve()
    return (target_root / "memory").resolve()


def _render_install_plan(summary: dict[str, object], args: argparse.Namespace, *, language: str) -> str:
    target_root = Path(str(args.target or summary["target_root"])).expanduser().resolve()
    memory_root = _effective_memory_root_for_plan(target_root, args, summary)
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    monitor_host = str(getattr(args, "monitor_host", None) or summary.get("recommended_monitor_host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = int(getattr(args, "monitor_port", None) or summary["recommended_monitor_port"])
    install_launchagent = bool(getattr(args, "install_launchagent", summary.get("recommended_install_launchagent", True)))
    install_mode = str(_guided_install_plan(summary, args).get("install_mode") or summary.get("recommended_install_mode") or "fresh_installation")
    lines = [
        _ui_text(language, en="Installation plan", de="Installationsplan"),
        f"- {_ui_text(language, en='mode', de='Modus')}: {install_mode}",
        f"- {_ui_text(language, en='target root', de='Ziel-Root')}: {target_root}",
        f"- {_ui_text(language, en='memory root', de='Memory-Root')}: {memory_root}",
        f"- {_ui_text(language, en='monitor', de='Monitor')}: {monitor_host}:{monitor_port}",
        f"- {_ui_text(language, en='wrapper naming', de='Wrapper-Namensschema')}: prefix={prefix or '-'} suffix={suffix or '-'}",
        f"- {_ui_text(language, en='install launchagent now', de='LaunchAgent jetzt installieren')}: "
        + _ui_text(language, en="yes" if install_launchagent else "later", de="ja" if install_launchagent else "spaeter"),
    ]
    return "\n".join(lines)


def _run_post_install_checks(target: Path, *, language: str) -> dict[str, int]:
    cli_path = agent_memory_cli_path_for_root(target)
    doctor = subprocess.run(
        [str(cli_path), "doctor"],
        cwd=str(target),
        env={**os.environ, "AGENT_MEMORY_ROOT": str(target)},
        text=True,
        capture_output=True,
        check=False,
    )
    doctor_output = "\n".join(part for part in [doctor.stdout.strip(), doctor.stderr.strip()] if part)
    if doctor_output:
        print(doctor_output)
    doctor_exit = int(doctor.returncode)
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
    _print_installation_check(check_payload)
    check_exit = 0
    print(
        _ui_text(
            language,
            en=f"verification summary: doctor={doctor_exit} check-installation={check_exit}",
            de=f"Verifikationszusammenfassung: doctor={doctor_exit} check-installation={check_exit}",
        )
    )
    return {"doctor_exit": doctor_exit, "check_installation_exit": check_exit}


def _recommended_install_command(summary: dict[str, object]) -> str:
    checkout_root = Path(str(summary["checkout_root"]))
    command = [
        _command_script_for_root(checkout_root),
        "install",
        "--target",
        sh_quote(str(summary["target_root"])),
        "--language",
        str(summary["reply_language"]),
        "--monitor-port",
        str(summary["recommended_monitor_port"]),
    ]
    memory_root = str(summary.get("recommended_memory_root") or "").strip()
    if memory_root:
        command.extend(["--memory-root", sh_quote(memory_root)])
    prefix = str(summary.get("recommended_wrapper_prefix") or "").strip()
    suffix = str(summary.get("recommended_wrapper_suffix") or "").strip()
    if prefix:
        command.extend(["--wrapper-prefix", prefix])
    if suffix:
        command.extend(["--wrapper-suffix", suffix.lstrip("-")])
    if not bool(summary.get("recommended_install_launchagent", True)):
        command.append("--no-install-launchagent")
    return " ".join(command)


def _linked_wrapper_specs(args: argparse.Namespace) -> list[str]:
    wrappers: list[str] = []
    for flag_name, wrapper_name in [
        ("link_codex_memory", "codex-memory"),
        ("link_claude_memory", "claude-memory"),
        ("link_agy_memory", "agy-memory"),
        ("link_antigravity_memory", "antigravity-memory"),
        ("link_gemini_memory", "gemini-memory"),
        ("link_opencode_memory", "opencode-memory"),
    ]:
        if getattr(args, flag_name):
            wrappers.append(wrapper_name)
    return wrappers


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


def _monitor_start_command(target: Path, *, runner: str, host: str, port: int, language: str) -> list[str]:
    cli_path = agent_memory_cli_path_for_root(target)
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
        "--replace-existing",
        "--no-open",
    ]


def _open_monitor_howto(*, host: str, port: int, runner: str, language: str) -> None:
    if os.environ.get("AGENT_MEMORY_TEST_SKIP_MONITOR_OPEN", "") in {"1", "true", "True", "yes"}:
        return
    url = f"http://{host}:{port}/?runner={quote(runner)}&lang={quote(language)}#howto"
    threading.Timer(0.35, lambda: webbrowser.open(url)).start()


def _autostart_monitor_after_install(
    target: Path,
    *,
    runner: str,
    host: str,
    port: int,
    language: str,
) -> tuple[bool, str]:
    command = _monitor_start_command(target, runner=runner, host=host, port=port, language=language)
    process = subprocess.Popen(
        command,
        cwd=str(target),
        env={**os.environ, "AGENT_MEMORY_ROOT": str(target)},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        close_fds=True,
    )
    time.sleep(0.75)
    if process.poll() is None:
        return True, f"pid={process.pid} command={monitor_restart_command(target, runner=runner)}"
    stdout, stderr = process.communicate(timeout=1)
    detail = (stderr or stdout).strip() or f"exit {process.returncode}"
    return False, detail


def cmd_install_discovery(args: argparse.Namespace) -> int:
    start = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else Path.cwd()
    summary = _discovery_summary(
        start=start,
        target_hint=Path(args.target).expanduser().resolve() if getattr(args, "target", None) else None,
        memory_root_hint=getattr(args, "memory_root", None),
        language_hint=getattr(args, "language", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(_render_install_discovery(summary))
    print("")
    print(_ui_text(summary["reply_language"], en="recommended command:", de="empfohlener Befehl:"))
    print(_recommended_install_command(summary))
    return 0


def agents_memory_block(language: str, *, command_prefix: str = "./scripts/agent-context-engine") -> str:
    label = LANGUAGE_LABELS.get(language, "English")
    return f"""## Agent Context Engine Quick Path
- Preferred interaction language for future agents: {label}.
- When asked about previous sessions, handovers, project context, "what happened last", "continue there", "we already analyzed this", or similar memory requests, use the local Agent Context Engine CLI first.
- Agent Context Engine command prefix: `{command_prefix}`
- Traceable retrieval: `{command_prefix} retrieve "<question or search terms>" --limit 10`
- Quick keyword search: `{command_prefix} search "<search terms>" --limit 5`
- Load a session handover: `{command_prefix} handover "<session|title|search terms>"`
- Recent sessions: `{command_prefix} last --limit 10`
- Status: `{command_prefix} doctor`
- For list/count/today questions about sessions, use `last` first and stop there unless the user explicitly asks for details about a specific session.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- Only after these commands should agents broaden the search with `rg` in the repository or memory tree.
"""


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
    resolved_memory_root = (memory_root or target).resolve()
    monitor_runner = str(
        load_installation_profile(resolved_memory_root).get("workflows", {}).get("monitor_runner") or WORKFLOW_RUNNER_DEFAULTS["monitor_runner"]
    ).strip()
    return f"""# Session Start

Agent Context Engine command prefix: `{command_prefix}`

- For session list/count/today questions, use `last --limit 10` first and answer from that result. Do not open session, summary, or dream files unless the user explicitly asks for details.
- For session list/count/today questions, use `last` first and stop there unless the user explicitly asks for deeper detail.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- If the user mentions a local repo/project/folder by name, or asks for side information about another project, resolve it via one of these — do not browse the filesystem:
  - `cat ./docs/knowledge/repos.md` — full repos context (fastest, no CLI needed)
  - `repo-context --list` — overview of known repos
  - `repo-context <identifier>` — targeted context for a specific repo
- Load personal context only on demand, e.g. for "my preferences", "as usual", writing style, language, or personal standards.

Start here for previous work:
- `{command_prefix} last --limit 10`
- `{command_prefix} use "<session|title|search terms>"`
- `{command_prefix} handover "<session|title|search terms>"`
- `{command_prefix} retrieve "<question or search terms>" --limit 10`
- `{command_prefix} search "<search terms>" --limit 5`

Load extra context when needed:
- `{command_prefix} session-start-context`
- `{command_prefix} personal-context --list`
- `{command_prefix} personal-context <identifier>`
- `{command_prefix} repo-context --list`
- `{command_prefix} repo-context <identifier>`
- `{command_prefix} retrieval-runs --limit 10`
- `{command_prefix} retrieval-run <retrieval_run_id>`

User-only controls:
- `approve ...`
- `reset taint`
- `firewall add ...`
- `firewall disable session`
- `firewall enable session`
- `hooks-disable [--runner <runner>]`
- `hooks-enable [--runner <runner>]`
- `hooks-status`

Monitor:
- `{monitor_restart_command(resolved_memory_root, runner=monitor_runner)}`
"""


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
    if not claude_path.exists() or "AGENTS.md" not in claude_path.read_text(encoding="utf-8", errors="replace"):
        claude_path.write_text(CLAUDE_ENTRYPOINT, encoding="utf-8")
        written.append(claude_path)
    cursor_rule = target / ".cursor" / "rules" / "everyChat.mdc"
    if not cursor_rule.exists() or "AGENTS.md" not in cursor_rule.read_text(encoding="utf-8", errors="replace"):
        cursor_rule.parent.mkdir(parents=True, exist_ok=True)
        cursor_rule.write_text(CURSOR_EVERY_CHAT_RULE, encoding="utf-8")
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


def ask_project_entries(*, language: str = "en") -> list[tuple[str, Path]]:
    if not sys.stdin.isatty():
        return []
    print("")
    print(_ui_text(language, en="Initial repo index", de="Initialer Repo-Index"))
    print(
        _ui_text(
            language,
            en="Add projects Agent Context Engine should recognize. Press Enter on an empty name to finish.",
            de="Fuege Projekte hinzu, die Agent Context Engine erkennen soll. Leerer Name beendet die Eingabe.",
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


def ensure_repos_index(target: Path, project_specs: list[str], *, interactive: bool, language: str = "en") -> Path:
    repos_index = target / "docs" / "knowledge" / "repos.md"
    if repos_index.exists():
        return repos_index
    entries: list[tuple[str, Path]] = []
    for spec in project_specs:
        entries.append(project_spec_entry(spec))
    if interactive and not entries:
        entries = ask_project_entries(language=language)
    repos_index.parent.mkdir(parents=True, exist_ok=True)
    repos_index.write_text(render_repos_index(entries), encoding="utf-8")
    return repos_index


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


def _default_storage_root_for_install(target: Path, args: argparse.Namespace) -> Path:
    memory_root_arg = getattr(args, "memory_root", None)
    if memory_root_arg:
        return Path(str(memory_root_arg)).expanduser().resolve()
    return _default_home_memory_root()


def _default_launchagent_env_file_for_storage(memory_root: Path) -> str:
    return str((memory_root / "local" / "agent-context-engine.env").resolve())


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
    if not text or text in {DEFAULT_ENV_FILE, "memory/local/agent-memory.env"}:
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


def _print_headless_guidance(client: str) -> None:
    guidance = HEADLESS_INSTALL_GUIDANCE.get(client)
    if not guidance:
        return
    print(f"  headless requirement: {guidance['detail']}")
    print(f"  install hint: {guidance['install_command']}")
    if guidance.get("login_command"):
        print(f"  login hint: {guidance['login_command']}")

def _installation_check_payload(*, root: Path, args: argparse.Namespace) -> dict[str, object]:
    runtime = python_runtime_status(root)
    frontend = frontend_build_status(root)
    integrations = integration_summary(root=root, probe_gemini=False)
    profile = _resolved_installation_profile(root, args)
    storage_status = _storage_status(root=root, profile=profile)
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

    if not runtime["venv_exists"]:
        findings.append({"severity": "warn", "code": "missing_venv", "message": f"Local runtime virtualenv is missing: {runtime['venv_path']}"})
        repair_actions.append({"code": "create_venv", "message": "Create `.venv` and install backend dependencies."})
        add_agent_action(
            code="create_venv",
            message="Create `.venv` and install backend dependencies.",
            command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
        )
    if not runtime["yaml_available"]:
        findings.append({"severity": "error", "code": "missing_pyyaml", "message": f"PyYAML is missing for the selected runtime python: {runtime['python_path']}"})
        repair_actions.append({"code": "install_backend_dependencies", "message": "Install backend dependencies into `.venv` so monitor/OpenAPI imports work."})
        add_agent_action(
            code="install_backend_dependencies",
            message="Install backend dependencies into `.venv` so monitor/OpenAPI imports work.",
            command=f"{agent_memory_cli_for_root(root)} repair-installation --apply",
        )
    if frontend["needs_build"]:
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
        add_agent_action(
            code="build_frontend",
            message="Build the monitor frontend before restart.",
            command=f"{agent_memory_cli_for_root(root)} repair-installation --apply --install-frontend-deps",
        )
        if not frontend["node_modules_exists"]:
            repair_actions.append({"code": "install_frontend_dependencies", "message": "Install frontend dependencies before building the monitor UI."})
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

    monitor_profile = dict(profile.get("monitor") or {})
    monitor_host = str(monitor_profile.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = int(monitor_profile.get("port") or DEFAULT_MONITOR_PORT)
    monitor_port_status = _port_conflict_status(monitor_host, monitor_port)
    if not bool(monitor_port_status["available"]):
        findings.append(
            {
                "severity": "warn",
                "code": "monitor_port_conflict",
                "message": f"Configured monitor default {monitor_host}:{monitor_port} is not currently bindable: {monitor_port_status['error']}",
            }
        )

    launchagent_profile = dict(profile.get("launchagent") or {})
    launchagent_label = str(launchagent_profile.get("label") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
    launchagent_path = str(launchagent_profile.get("path") or launch_agent_path(launchagent_label)).strip() or str(launch_agent_path(launchagent_label))
    launchagent_env_file = str(launchagent_profile.get("env_file") or DEFAULT_ENV_FILE).strip() or DEFAULT_ENV_FILE
    launchagent_status = launchagent_runtime_status(label=launchagent_label, env_file=launchagent_env_file, plist_path=launchagent_path)
    expected_launchagent_path = str(launch_agent_path(launchagent_label))
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
                        f"--rewrite-workspace-hook-adapters --{client}-workspace-root {sh_quote(str(workspace_root))}"
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
                        f"--{client}-workspace-root {sh_quote(str(workspace_root))}"
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
                        f"--{client}-workspace-root {sh_quote(str(workspace_root))}"
                        + (" --rewrite-workspace-hook-adapters" if requires_confirmation else "")
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
    print(f"runtime venv: {'ok' if runtime['venv_exists'] else 'missing'} {runtime['venv_path']}")
    print(f"PyYAML: {'ok' if runtime['yaml_available'] else 'missing'}")
    print(f"monitor frontend dist: {'ok' if frontend['dist_exists'] else 'missing'} {frontend['dist_index']}")
    print(f"monitor frontend build status: {'needs build' if frontend['needs_build'] else 'current'}")
    print(f"monitor frontend deps: {'ok' if frontend['node_modules_exists'] else 'missing'}")
    monitor_profile = payload.get("monitor_profile") or {}
    launchagent_profile = payload.get("launchagent_profile") or {}
    print(
        "monitor default: "
        + f"{monitor_profile.get('host') or DEFAULT_MONITOR_HOST}:{monitor_profile.get('port') or DEFAULT_MONITOR_PORT} "
        + f"({'available' if monitor_profile.get('port_available') else 'conflict'})"
    )
    if monitor_profile.get("port_error"):
        print(f"monitor port detail: {monitor_profile['port_error']}")
    print(
        "launchagent default: "
        + f"label={launchagent_profile.get('label') or DEFAULT_LABEL} "
        + f"path={launchagent_profile.get('path') or '-'} "
        + f"env_file={launchagent_profile.get('env_file') or DEFAULT_ENV_FILE}"
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
    if (memory_root / "scripts" / "agent_memory.py").exists():
        return "scripts/agent_memory.py"
    return "docs/skills/agent-context-engine/scripts/agent_context_engine.py"


def agent_memory_cli_for_root(memory_root: Path) -> str:
    if (memory_root / "scripts" / "agent-context-engine").exists():
        return "./scripts/agent-context-engine"
    if (memory_root / "scripts" / "agent-memory").exists():
        return "./scripts/agent-memory"
    return "./docs/skills/agent-context-engine/scripts/agent-context-engine"


def agent_memory_cli_path_for_root(memory_root: Path) -> Path:
    if (memory_root / "scripts" / "agent-context-engine").exists():
        return memory_root / "scripts" / "agent-context-engine"
    if (memory_root / "scripts" / "agent-memory").exists():
        return memory_root / "scripts" / "agent-memory"
    nested = memory_root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine"
    if nested.exists():
        return nested
    return memory_root / "docs" / "skills" / "agent-memory" / "scripts" / "agent-memory"


def agent_memory_command_prefix_for_target(target: Path, memory_root: Path) -> str:
    cli_path = agent_memory_cli_for_root(memory_root)
    if target.resolve() == memory_root.resolve():
        return cli_path
    return f"cd {sh_quote(str(memory_root.resolve()))} && {cli_path}"


def cursor_hook_wrapper(memory_root: Path) -> str:
    quoted_root = sh_quote(str(memory_root.resolve()))
    script_rel = agent_memory_script_for_root(memory_root)
    return f"""#!/usr/bin/env bash
set -euo pipefail

# Cursor hooks must never break the editor workflow. This wrapper logs the
# payload to the central Agent Memory root and then returns the allow/continue
# JSON expected by before-hooks.
if [ "${{AGENT_MEMORY_DREAM:-0}}" = "1" ]; then
  printf '{{}}\\n'
  exit 0
fi

MEMORY_ROOT={quoted_root}
LOG="$MEMORY_ROOT/memory/logs/cursor-hook.err.log"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
mkdir -p "$(dirname "$LOG")"
TMP="$(mktemp)"
OUT="$(mktemp)"
ERR="$(mktemp)"
trap 'rm -f "$TMP" "$OUT" "$ERR"' EXIT
cat > "$TMP"

set +e
env AGENT_MEMORY_ROOT="$MEMORY_ROOT" AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC="${{AGENT_MEMORY_CLASSIFIER_TOOL_OUTPUT_ASYNC:-1}}" python3 "$MEMORY_ROOT/{script_rel}" log-hook --client cursor \\
  < "$TMP" \\
  > "$OUT" \\
  2> "$ERR"
CODE=$?
set -e
cat "$ERR" >> "$LOG"

if [ "$CODE" != "0" ] && [ "$CODE" != "2" ]; then
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cursor hook log failed code=$CODE" >> "$LOG"
fi

python3 - "$TMP" "$OUT" "$ERR" "$CODE" <<'PY'
import json, sys
payload_path, stdout_path, stderr_path, code_text = sys.argv[1:5]
try:
    with open(payload_path, "r", encoding="utf-8", errors="replace") as handle:
        payload = json.load(handle)
except Exception:
    payload = {{}}
try:
    stdout = open(stdout_path, "r", encoding="utf-8", errors="replace").read()
except Exception:
    stdout = ""
try:
    stderr = open(stderr_path, "r", encoding="utf-8", errors="replace").read()
except Exception:
    stderr = ""
event = ""
for key in ("hook_event_name", "event_name", "hookName", "hook_name", "event", "type"):
    if payload.get(key):
        event = str(payload[key])
        break
code = int(code_text or "0")

def context_message() -> str:
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except Exception:
            continue
        context = (
            value.get("hookSpecificOutput", {{}})
            .get("additionalContext", "")
        )
        if context:
            return str(context)
    return ""

def block_message() -> str:
    text = stderr.strip()
    if text:
        return text[-6000:]
    return "Agent Context Engine blocked this tool use by policy. Open agent-monitor or run `./scripts/agent-context-engine risk list --limit 10` for details."

def with_message(response: dict, message: str, *, for_agent: bool = True) -> dict:
    if not message:
        return response
    # Cursor hook fields have varied across releases. Emit the known aliases so
    # the user sees blocks while the agent can also receive health notices.
    response["message"] = message
    response["user_message"] = message
    response["userMessage"] = message
    if for_agent:
        response["agent_message"] = message
        response["agentMessage"] = message
        response["followup_message"] = message
    return response

if event == "beforeSubmitPrompt":
    if code == 2:
        print(json.dumps(with_message({{"continue": False}}, block_message()), ensure_ascii=False))
        sys.exit(2)
    else:
        message = context_message()
        if message:
            print(json.dumps(with_message({{"continue": True}}, message), ensure_ascii=False))
        else:
            print(json.dumps({{"continue": True}}, ensure_ascii=False))
elif event in {{"beforeShellExecution", "beforeMCPExecution", "beforeReadFile"}}:
    if code == 2:
        print(json.dumps(with_message({{"permission": "deny"}}, block_message()), ensure_ascii=False))
        sys.exit(2)
    else:
        print(json.dumps({{"permission": "allow"}}, ensure_ascii=False))
else:
    if code == 2:
        print(json.dumps(with_message({{}}, block_message()), ensure_ascii=False))
    else:
        message = context_message()
        print(json.dumps(with_message({{}}, message), ensure_ascii=False) if message else "{{}}")
PY
"""


def antigravity_hook_wrapper(memory_root: Path) -> str:
    script_rel = agent_memory_script_for_root(memory_root)
    template = (SKILL_ROOT / "templates" / "antigravity-hooks" / "hook_adapter.sh").read_text(encoding="utf-8")
    return (
        template
        .replace("__AGENT_MEMORY_SCRIPT__", script_rel)
        .replace("__AGENT_MEMORY_ROOT__", str(memory_root.resolve()))
    )


def managed_install_conflicts(target: Path) -> list[Path]:
    return [target / relative for relative in MANAGED_INSTALL_PATHS if (target / relative).exists()]


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


def cmd_cursor_enable(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if args.target else ROOT
    memory_root = Path(args.memory_root).expanduser().resolve() if args.memory_root else ROOT
    command_prefix = agent_memory_command_prefix_for_target(target, memory_root)
    language = installation_language_for_target(target=target, memory_root=memory_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=memory_root)
    entrypoints = ensure_harness_entrypoints(target)
    script_path = target / ".cursor" / "hooks" / "hook_adapter.sh"
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(cursor_hook_wrapper(memory_root), encoding="utf-8")
    script_path.chmod(0o755)
    result, target_item = _run_integration_hook_action(client="cursor", action="enable", target=target, memory_root=memory_root)
    print(f"enabled Cursor IDE memory hooks: {target_item.get('hook_config_path') or (target / '.cursor' / 'hooks.json')}")
    print(f"hook wrapper: {target_item.get('hook_script_path') or script_path}")
    print(f"memory root: {memory_root}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='cursor', action='enable', target_root=target, root=memory_root)}")
    print("next: reload the Cursor window or reopen the project folder")
    return 0


def cmd_antigravity_enable(args: argparse.Namespace) -> int:
    memory_root = Path(args.memory_root).expanduser().resolve() if args.memory_root else ROOT
    if args.target:
        target = Path(args.target).expanduser().resolve()
        print(f"warning: project-specific Antigravity hooks are deprecated; use the global wrapper instead.")
        print(f"  global wrapper: {agent_memory_cli_for_root(memory_root)} global-wrapper-enable agy-memory")
        print(f"  run from anywhere: agy-memory")
        print(f"  requested target is unsupported in global-only mode: {target}")
    else:
        target = memory_root

    if target.resolve() != memory_root.resolve():
        print(f"error: refusing to create project-specific Antigravity hooks in {target}")
        print("Antigravity Agent Context Engine is now global-only. Use agy-memory to start Antigravity with hooks.")
        return 1

    command_prefix = agent_memory_command_prefix_for_target(target, memory_root)
    language = installation_language_for_target(target=target, memory_root=memory_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=memory_root)
    entrypoints = ensure_harness_entrypoints(target)
    paths = ensure_antigravity_project(target, memory_root=memory_root)
    script_path = paths["script_path"]
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(antigravity_hook_wrapper(memory_root), encoding="utf-8")
    script_path.chmod(0o755)
    result, target_item = _run_integration_hook_action(client="antigravity", action="enable", target=target, memory_root=memory_root)
    print(f"enabled global Antigravity Agent Context Engine hooks: {paths['config_path']}")
    print(f"hook wrapper: {script_path}")
    print(f"memory root: {memory_root}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='antigravity', action='enable', target_root=target, root=memory_root)}")
    print("next: ensure agy-memory is linked globally and start Antigravity with `agy-memory`")
    return 0


def cmd_gemini_enable(args: argparse.Namespace) -> int:
    memory_root = Path(args.memory_root).expanduser().resolve() if getattr(args, "memory_root", None) else ROOT
    if args.target:
        target = Path(args.target).expanduser().resolve()
        print(f"warning: project-specific Gemini hooks are deprecated; use the global wrapper instead.")
        print(f"  global wrapper: {agent_memory_cli_for_root(memory_root)} global-wrapper-enable gemini-memory")
        print(f"  run from anywhere: gemini-memory")
        print(f"  requested target is unsupported in global-only mode: {target}")
    else:
        target = memory_root

    if target.resolve() != memory_root.resolve():
        print(f"error: refusing to create project-specific Gemini hooks in {target}")
        print("Gemini Agent Context Engine is now global-only. Use gemini-memory to start Gemini with hooks.")
        return 1

    command_prefix = agent_memory_command_prefix_for_target(target, memory_root)
    language = installation_language_for_target(target=target, memory_root=memory_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=memory_root)
    entrypoints = ensure_harness_entrypoints(target)
    paths = ensure_gemini_project(target)
    result, _target_item = _run_integration_hook_action(client="gemini", action="enable", target=target, memory_root=target)
    print(f"enabled global Gemini Agent Context Engine hooks: {paths['config_path']}")
    print(f"hook adapter: {paths['script_path']}")
    print(f"memory root: {target}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='gemini', action='enable', target_root=target, root=target)}")
    print("next: ensure gemini-memory is linked globally and start Gemini with `gemini-memory`")
    return 0


def cmd_cursor_disable(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if args.target else ROOT
    result, target_item = _run_integration_hook_action(client="cursor", action="disable", target=target, memory_root=ROOT)
    print(f"disabled Cursor IDE memory hooks: {target_item.get('hook_config_path') or (target / '.cursor' / 'hooks.json')}")
    print(f"deactivated hook config: {target_item.get('hook_disabled_path') or (target / '.cursor' / 'hooks_deactivated.json')}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='cursor', action='disable', target_root=target, root=ROOT)}")
    print("next: reload the Cursor window or reopen the project folder")
    return 0


def cmd_cursor_status(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if args.target else None
    lines, exit_code = run_cursor_status(target=target)
    for line in lines:
        print(line)
    return exit_code


def cmd_opencode_enable(args: argparse.Namespace) -> int:
    memory_root = Path(args.memory_root).expanduser().resolve() if args.memory_root else ROOT
    if args.target:
        target = Path(args.target).expanduser().resolve()
        print(f"warning: project-specific OpenCode hooks are deprecated; use the global wrapper instead.")
        print(f"  global wrapper: {agent_memory_cli_for_root(memory_root)} global-wrapper-enable opencode-memory")
        print(f"  run from anywhere: opencode-memory [project]")
        print(f"  requested target is unsupported in global-only mode: {target}")
    else:
        target = memory_root

    # For global-only mode, the only plugin that should exist is inside the
    # central Agent Memory root. Project-specific plugins are no longer created.
    if target.resolve() != memory_root.resolve():
        print(f"error: refusing to create project-specific OpenCode plugin in {target}")
        print("OpenCode Agent Context Engine is now global-only. Use opencode-memory to start OpenCode with hooks.")
        return 1

    command_prefix = agent_memory_command_prefix_for_target(target, memory_root)
    language = installation_language_for_target(target=target, memory_root=memory_root)
    ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=memory_root)
    entrypoints = ensure_harness_entrypoints(target)
    paths = ensure_opencode_project(
        target,
        memory_root=memory_root,
        model=getattr(args, "model", None) or None,
        small_model=getattr(args, "small_model", None) or None,
    )
    result, _target_item = _run_integration_hook_action(client="opencode", action="enable", target=target, memory_root=memory_root)
    print(f"enabled global OpenCode Agent Context Engine bridge: {paths['plugin_file']}")
    print(f"opencode config: {paths['config']}")
    print(f"memory root: {memory_root}")
    print(f"hook entry: {hook_entry}")
    for path in entrypoints:
        print(f"updated entrypoint: {path}")
    print(f"toggle command: {result.get('command') or integration_hook_command(client='opencode', action='enable', target_root=target, root=memory_root)}")
    print("next: ensure opencode-memory is linked globally and start OpenCode with `opencode-memory [project]`")
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


def _run_integration_hook_action(*, client: str, action: str, target: Path, memory_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    result = manage_integration_hooks(client=client, action=action, root=memory_root, target_root=target)
    target_item = _integration_target_item(result, target)
    return result, target_item


def cmd_integration_hooks(args: argparse.Namespace) -> int:
    target = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    memory_root = Path(args.memory_root).expanduser().resolve() if getattr(args, "memory_root", None) else ROOT
    result, target_item = _run_integration_hook_action(client=str(args.client), action=str(args.action), target=target, memory_root=memory_root)
    print(f"client: {args.client}")
    print(f"action: {args.action}")
    print(f"target: {target}")
    print(f"hook config: {target_item.get('hook_config_path') or '-'}")
    print(f"hook disabled file: {target_item.get('hook_disabled_path') or '-'}")
    print(f"hooks state: {target_item.get('hooks_state') or '-'}")
    print(f"hook events: {', '.join(target_item.get('active_hook_events', [])) if isinstance(target_item.get('active_hook_events'), list) else '-'}")
    print(f"command: {result.get('command') or integration_hook_command(client=str(args.client), action=str(args.action), target_root=target, root=memory_root)}")
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
        print("use `gemini-memory` from any directory, or run `./scripts/agent-context-engine gemini-status` without --target.")
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
        print("use `agy-memory` from any directory, or run `./scripts/agent-context-engine antigravity-status` without --target.")
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
    _print_installation_check(payload)
    return 0


def cmd_repair_installation(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    current_storage_root = Path(str(resolve_storage_profile(root).get("memory_root") or (root / "memory"))).expanduser().resolve()
    runtime_memory_root = _default_storage_root_for_install(root, args)
    workspace_roots = _workspace_root_overrides(args)
    workflow_overrides = _workflow_runner_overrides(args)
    payload = _installation_check_payload(root=root, args=args)
    _print_installation_check(payload)
    if not getattr(args, "apply", False):
        print("next: rerun with --apply after reviewing the proposed actions")
        return 0

    applied: list[str] = []
    skipped: list[str] = []
    storage_rebound = bool(getattr(args, "memory_root", None))
    try:
        if workflow_overrides or any(workspace_roots.values()) or getattr(args, "memory_root", None):
            applied.extend(_relocate_runtime_storage(current_storage_root, runtime_memory_root))
            ensure_storage_profile(runtime_memory_root, schema_version=int(resolve_storage_profile(root).get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION), storage_instance_id=str(load_installation_profile(root).get("instance_id") or root.name))
            current_profile = load_installation_profile(root)
            current_launchagent = dict(current_profile.get("launchagent") or {})
            current_env_file = str(current_launchagent.get("env_file") or DEFAULT_ENV_FILE)
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
    except (RuntimeError, subprocess.CalledProcessError) as exc:
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
            ".git",
            ".codex",
            ".claude",
            ".cursor",
            "AGENTS.md",
            "CLAUDE.md",
            "docs",
            "memory",
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
        return ""
    if raw_suffix and raw_suffix[0] not in "-_.":
        raw_suffix = "-" + raw_suffix
    suffix = safe_slug(raw_suffix)
    if raw_suffix and raw_suffix[0] in "-_." and not suffix.startswith(raw_suffix[0]):
        suffix = raw_suffix[0] + suffix
    return suffix


def install_command_prefix(args: argparse.Namespace) -> str:
    return install_wrapper_prefix(args)


def link_command_name(base: str, prefix: str, suffix: str = "") -> str:
    return safe_slug(f"{prefix}{base}{suffix}")


def wrapper_script_path(root: Path, wrapper_name: str) -> Path:
    if wrapper_name not in GLOBAL_WRAPPERS and wrapper_name not in LEGACY_GLOBAL_WRAPPERS:
        raise ValueError(f"unsupported wrapper: {wrapper_name}")
    direct = root / "scripts" / wrapper_name
    if direct.exists():
        return direct
    installed = root / "docs" / "skills" / "agent-context-engine" / "scripts" / wrapper_name
    if installed.exists():
        return installed
    return root / "docs" / "skills" / "agent-memory" / "scripts" / wrapper_name


def create_command_link(link_dir: Path, link_name: str, target: Path, *, force: bool) -> Path:
    link = link_dir / link_name
    if link.exists() or link.is_symlink():
        if not force:
            raise FileExistsError(f"link exists, use --force or a different --command-prefix: {link}")
        link.unlink()
    link.symlink_to(target)
    return link


def remove_command_link(link_dir: Path, link_name: str) -> Path:
    link = link_dir / link_name
    if link.exists() or link.is_symlink():
        link.unlink()
    return link


def global_wrapper_command_name(wrapper_name: str, args: argparse.Namespace) -> str:
    return link_command_name(wrapper_name, install_wrapper_prefix(args), install_wrapper_suffix(args))


def ensure_global_wrapper_link(link_dir: Path, wrapper_name: str, target_root: Path, *, force: bool, prefix: str, suffix: str = "") -> Path:
    target = wrapper_script_path(target_root, wrapper_name)
    if not target.exists():
        raise FileNotFoundError(f"missing wrapper script: {target}")
    link_name = link_command_name(wrapper_name, prefix, suffix)
    return create_command_link(link_dir, link_name, target, force=force)


def cmd_install(args: argparse.Namespace) -> int:
    discovery_summary: dict[str, object] | None = None
    if not args.target:
        summary = _discovery_summary(
            start=Path.cwd(),
            memory_root_hint=getattr(args, "memory_root", None),
            language_hint=getattr(args, "language", None),
        )
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
        if not getattr(args, "memory_root", None) and summary.get("recommended_memory_root"):
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
            args.install_launchagent = ask_yes_no(
                _ui_text(
                    normalize_language(args.language),
                    en="Install and load the LaunchAgent now?",
                    de="LaunchAgent jetzt installieren und laden?",
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
    install_plan = _guided_install_plan(discovery_summary, args)
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
                en="Proceed with this installation plan?",
                de="Diesen Installationsplan jetzt ausfuehren?",
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
    runtime_memory_root = _default_storage_root_for_install(target, args)
    installed_skill = copy_skill_package(target)
    cli_path = agent_memory_cli_path_for_root(target)
    script_rel = agent_memory_script_for_root(target)
    command_prefix = agent_memory_command_prefix_for_target(target, target)
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    monitor_host = str(getattr(args, "monitor_host", None) or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    monitor_port = int(getattr(args, "monitor_port", None) or DEFAULT_MONITOR_PORT)
    launchagent_label = str(getattr(args, "launchagent_label", None) or DEFAULT_LABEL).strip() or DEFAULT_LABEL
    launchagent_path = str(getattr(args, "launchagent_path", None) or launch_agent_path(launchagent_label)).strip() or str(launch_agent_path(launchagent_label))
    launchagent_env_file = str(getattr(args, "launchagent_env_file", None) or _default_launchagent_env_file_for_storage(runtime_memory_root)).strip() or _default_launchagent_env_file_for_storage(runtime_memory_root)
    codex_templates = SKILL_ROOT / "templates" / "codex-hooks"
    script_abs = str((target / script_rel).resolve())
    root_abs = str(target.resolve())
    copy_text(codex_templates / "hooks.json", target / ".codex" / "hooks.json")
    copy_text(
        codex_templates / "hook_adapter.sh",
        target / ".codex" / "hooks" / "hook_adapter.sh",
        {"__AGENT_MEMORY_SCRIPT__": script_abs, "__AGENT_MEMORY_ROOT__": root_abs},
    )
    claude_templates = SKILL_ROOT / "templates" / "claude-hooks"
    copy_text(claude_templates / "settings.json", target / ".claude" / "settings.json")
    copy_text(
        claude_templates / "hook_adapter.sh",
        target / ".claude" / "hooks" / "hook_adapter.sh",
        {"__AGENT_MEMORY_SCRIPT__": script_abs, "__AGENT_MEMORY_ROOT__": root_abs},
    )
    antigravity_templates = SKILL_ROOT / "templates" / "antigravity-hooks"
    copy_text(
        antigravity_templates / "hooks.json",
        target / ".agents" / "hooks.json",
        {"__ANTIGRAVITY_HOOK_SCRIPT__": str((target / ".agents" / "hooks" / "hook_adapter.sh").resolve())},
    )
    copy_text(
        antigravity_templates / "hook_adapter.sh",
        target / ".agents" / "hooks" / "hook_adapter.sh",
        {
            "__AGENT_MEMORY_SCRIPT__": script_rel,
            "__AGENT_MEMORY_ROOT__": str(target.resolve()),
        },
    )
    gemini_templates = SKILL_ROOT / "templates" / "gemini-hooks"
    copy_text(gemini_templates / "settings.json", target / ".gemini" / "settings.json")
    copy_text(
        gemini_templates / "hook_adapter.sh",
        target / ".gemini" / "hooks" / "hook_adapter.sh",
        {"__AGENT_MEMORY_SCRIPT__": script_abs, "__AGENT_MEMORY_ROOT__": root_abs},
    )
    write_workspace_binding("codex", root=target, memory_root=target, written_by="install")
    write_workspace_binding("claude", root=target, memory_root=target, written_by="install")
    repos_index = ensure_repos_index(target, args.project or [], interactive=not args.no_interactive, language=language)
    agents_path = ensure_agents_memory_block(target, language=language, command_prefix=command_prefix)
    hook_entry_path = ensure_session_start_hook_entry(target, command_prefix=command_prefix, language=language, memory_root=target)
    entrypoints = ensure_harness_entrypoints(target)
    for path in [
        installed_skill / "scripts" / "agent-memory",
        installed_skill / "scripts" / "codex-memory",
        installed_skill / "scripts" / "claude-memory",
        installed_skill / "scripts" / "agy-memory",
        installed_skill / "scripts" / "antigravity-memory",
        installed_skill / "scripts" / "gemini-memory",
        installed_skill / "scripts" / "opencode-memory",
        target / ".codex" / "hooks" / "hook_adapter.sh",
        target / ".claude" / "hooks" / "hook_adapter.sh",
        target / ".agents" / "hooks" / "hook_adapter.sh",
        target / ".gemini" / "hooks" / "hook_adapter.sh",
    ]:
        path.chmod(0o755)
    if getattr(args, "bootstrap_runtime", False):
        try:
            for action in ensure_runtime_venv(target, install_backend_dependencies=True):
                print(f"runtime bootstrap: {action}")
        except (RuntimeError, subprocess.CalledProcessError) as exc:
            print(
                f"warn: runtime bootstrap failed; run `{agent_memory_cli_for_root(target)} repair-installation --apply` later: {exc}",
                file=sys.stderr,
            )
    instance_id = _default_instance_id_for_target(target, args)
    ensure_storage_profile(runtime_memory_root, schema_version=int(getattr(args, "storage_schema_version", None) or DEFAULT_STORAGE_SCHEMA_VERSION), storage_instance_id=instance_id)
    merge_installation_profile(
        target,
        instance_id=instance_id,
        root_path=target,
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
    merge_user_config(
        default_language=language,
        default_monitor_host=monitor_host,
        default_monitor_port=monitor_port,
        default_wrapper_prefix=prefix,
        default_wrapper_suffix=suffix,
        default_launchagent_enabled=bool(args.install_launchagent),
        default_memory_root=runtime_memory_root,
        last_used_installation_root=target,
        last_used_memory_root=runtime_memory_root,
    )
    sync_instance_metadata(target)
    if args.link_codex_memory or args.link_claude_memory or args.link_agy_memory or args.link_antigravity_memory or args.link_gemini_memory or args.link_opencode_memory:
        link_dir = Path(args.link_dir).expanduser().resolve()
        link_dir.mkdir(parents=True, exist_ok=True)
    for flag_name, wrapper_name in [
        ("link_codex_memory", "codex-memory"),
        ("link_claude_memory", "claude-memory"),
        ("link_agy_memory", "agy-memory"),
        ("link_antigravity_memory", "antigravity-memory"),
        ("link_gemini_memory", "gemini-memory"),
        ("link_opencode_memory", "opencode-memory"),
    ]:
        if not getattr(args, flag_name):
            continue
        try:
            link = ensure_global_wrapper_link(
                link_dir,
                wrapper_name,
                installed_skill / "scripts" / "..",
                force=args.force,
                prefix=prefix,
                suffix=suffix,
            )
        except (FileExistsError, FileNotFoundError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"linked {link} -> {installed_skill / 'scripts' / wrapper_name}")
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
    print(f"installed agent-context-engine into {target}")
    print(f"install mode: {install_plan['install_mode']}")
    if args.instance_name:
        print(f"instance: {safe_slug(args.instance_name)}")
    print(f"preferred interaction language: {LANGUAGE_LABELS.get(language, language)}")
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
    print(f"updated agent instructions: {agents_path}")
    print(f"updated hook entry: {hook_entry_path}")
    print(f"repo index: {repos_index}")
    for path in entrypoints:
        print(f"updated harness entrypoint: {path}")
    if args.install_launchagent:
        launchagent = subprocess.run(
            [
                str(cli_path),
                "install-launchagent",
                "--label",
                launchagent_label,
                "--plist-path",
                launchagent_path,
                "--env-file",
                launchagent_env_file,
                "--load",
            ],
            cwd=str(target),
            text=True,
            capture_output=True,
            check=False,
        )
        if launchagent.returncode == 0:
            print("installed and loaded LaunchAgent")
        else:
            message = launchagent.stderr.strip() or launchagent.stdout.strip()
            print(f"warn: LaunchAgent install failed; run manually if needed: {message}", file=sys.stderr)
    else:
        print(
            "next: run "
            + f"{agent_memory_cli_for_root(target)} install-launchagent --label {launchagent_label} "
            + f"--plist-path {sh_quote(launchagent_path)} --env-file {sh_quote(launchagent_env_file)} --load"
        )
    verification = _run_post_install_checks(target, language=language)
    if getattr(args, "start_monitor", True) and os.environ.get("AGENT_MEMORY_TEST_SKIP_MONITOR_START", "") not in {"1", "true", "True", "yes"}:
        started, detail = _autostart_monitor_after_install(
            target,
            runner=workflow_settings["monitor_runner"],
            host=monitor_host,
            port=monitor_port,
            language=language,
        )
        if started:
            print(f"started monitor: {detail}")
            _open_monitor_howto(host=monitor_host, port=monitor_port, runner=workflow_settings["monitor_runner"], language=language)
        else:
            print(
                "warn: monitor start failed; run manually if needed: "
                + f"{detail}; command={monitor_restart_command(target, runner=workflow_settings['monitor_runner'])}",
                file=sys.stderr,
            )
    else:
        print("next: run " + monitor_restart_command(target, runner=workflow_settings["monitor_runner"]))
    print(f"next: run {agent_memory_cli_for_root(target)} doctor")
    start_hints = _wrapper_start_hints(target, args)
    print("next: start " + ", ".join(start_hints))
    print("info: /hooks can be used inside Codex to inspect installed hooks; approve any Codex hook safety review if shown")
    print(
        _ui_text(
            language,
            en=(
                f"installation summary: target={target} memory_root={runtime_memory_root} "
                f"monitor_port={monitor_port} wrapper_prefix={prefix or '-'} wrapper_suffix={suffix or '-'}"
            ),
            de=(
                f"Installationszusammenfassung: target={target} memory_root={runtime_memory_root} "
                f"monitor_port={monitor_port} wrapper_prefix={prefix or '-'} wrapper_suffix={suffix or '-'}"
            ),
        )
    )
    return 0


def cmd_attach_memory_root(args: argparse.Namespace) -> int:
    root = Path(args.target).expanduser().resolve() if getattr(args, "target", None) else ROOT
    memory_root = Path(str(args.memory_root)).expanduser().resolve()
    profile = load_installation_profile(root)
    current_storage_root = Path(str(resolve_storage_profile(root).get("memory_root") or (root / "memory"))).expanduser().resolve()
    schema_version = int(getattr(args, "storage_schema_version", None) or resolve_storage_profile(root).get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION)
    migrated_actions = _relocate_runtime_storage(current_storage_root, memory_root)
    ensure_storage_profile(memory_root, schema_version=schema_version, storage_instance_id=str(profile.get("instance_id") or root.name))
    launchagent_profile = dict(profile.get("launchagent") or {})
    launchagent_env_file = str(launchagent_profile.get("env_file") or DEFAULT_ENV_FILE)
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
    try:
        link = ensure_global_wrapper_link(link_dir, args.wrapper, ROOT, force=args.force, prefix=prefix, suffix=suffix)
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"linked {link} -> {wrapper_script_path(ROOT, args.wrapper)}")
    print(f"global command: {link_command_name(args.wrapper, prefix, suffix)}")
    append_integration_history(
        client=args.wrapper,
        action="global_wrapper_enabled",
        root=ROOT,
        source="cli",
        actor="agent-memory-cli",
        details={"link": str(link), "command_name": link_command_name(args.wrapper, prefix, suffix)},
    )
    return 0


def cmd_global_wrapper_disable(args: argparse.Namespace) -> int:
    link_dir = Path(args.link_dir).expanduser().resolve()
    prefix = install_wrapper_prefix(args)
    suffix = install_wrapper_suffix(args)
    link_name = link_command_name(args.wrapper, prefix, suffix)
    link = remove_command_link(link_dir, link_name)
    print(f"removed global wrapper link: {link}")
    append_integration_history(
        client=args.wrapper,
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
    wrapper_naming = dict(profile.get("wrapper_naming") or {})
    prefix = str(wrapper_naming.get("prefix") or "")
    suffix = str(wrapper_naming.get("suffix") or "")
    for wrapper_name in GLOBAL_WRAPPERS:
        configured_name = link_command_name(wrapper_name, prefix, suffix)
        command = shutil.which(configured_name)
        local_link = link_dir / configured_name
        print(f"{wrapper_name}:")
        print(f"  configured_command: {configured_name}")
        print(f"  path_linked: {'yes' if command else 'no'}")
        print(f"  resolved: {command or '-'}")
        print(f"  link_dir_entry: {local_link if local_link.exists() or local_link.is_symlink() else '-'}")
        print(f"  root_wrapper: {wrapper_script_path(ROOT, wrapper_name)}")
    return 0
