from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
from pathlib import Path

from ..ports.scheduler_installation import SchedulerInstallerPort
from .platform import PlatformProfile, current_platform_profile
from .platform.runtime_selection import launchagent_plist_path, launchagent_service_domain, select_scheduler_installer
from .instance_profile import active_monitor_runtime_entries, installation_profile_path, load_installation_profile, load_link_registry, normalize_launchagent_profile


def resolve_platform_scheduler_installer(profile: PlatformProfile | None = None) -> SchedulerInstallerPort:
    profile = profile or current_platform_profile()
    return select_scheduler_installer(profile)


def install_platform_scheduler(args: argparse.Namespace) -> int:
    return resolve_platform_scheduler_installer().install(args)


def uninstall_platform_scheduler(args: argparse.Namespace) -> int:
    return resolve_platform_scheduler_installer().uninstall(args)


def platform_scheduler_status(args: argparse.Namespace) -> int:
    return resolve_platform_scheduler_installer().status(args)


def stop_superseded_platform_schedulers(*, target: Path, memory_root: Path) -> list[str]:
    profile = current_platform_profile()
    installer = resolve_platform_scheduler_installer(profile)
    if getattr(installer, "adapter_name", "") != "launchagent":
        return []

    normalized_target = str(target.resolve())
    normalized_memory_root = str(memory_root.resolve())
    candidate_roots: set[str] = set()
    candidate_plists: list[tuple[Path, str, str, str]] = []

    for entry in active_monitor_runtime_entries():
        if isinstance(entry, dict):
            root_text = str(entry.get("installation_root") or "").strip()
            if root_text:
                candidate_roots.add(root_text)

    for entry in dict(load_link_registry().get("entries") or {}).values():
        if isinstance(entry, dict):
            root_text = str(entry.get("installation_root") or "").strip()
            if root_text:
                candidate_roots.add(root_text)

    launchagents_dir = Path.home() / "Library" / "LaunchAgents"
    if launchagents_dir.exists():
        for plist_path in sorted(launchagents_dir.glob("com.agent-context-engine*.plist")):
            try:
                with plist_path.open("rb") as handle:
                    plist = plistlib.load(handle)
            except Exception:
                continue
            if not isinstance(plist, dict):
                continue
            label = str(plist.get("Label") or plist_path.stem).strip()
            working_directory = str(plist.get("WorkingDirectory") or "").strip()
            env = plist.get("EnvironmentVariables")
            env_map = env if isinstance(env, dict) else {}
            env_file_text = str(env_map.get("AGENT_MEMORY_ENV_FILE") or "").strip()
            if working_directory:
                candidate_roots.add(working_directory)
            candidate_plists.append((plist_path, label, working_directory, env_file_text))

    actions: list[str] = []
    stopped_plists: set[str] = set()

    for root_text in sorted(candidate_roots):
        if not root_text or root_text == normalized_target:
            continue
        other_root = Path(root_text).expanduser().resolve()
        if not installation_profile_path(other_root).exists():
            continue
        try:
            profile_payload = load_installation_profile(other_root)
        except Exception:
            continue
        storage = dict(profile_payload.get("storage") or {})
        if str(storage.get("memory_root") or "").strip() != normalized_memory_root:
            continue
        launchagent = normalize_launchagent_profile(dict(profile_payload.get("launchagent") or {}))
        label = str(launchagent.get("label") or f"com.agent-context-engine.{other_root.name}").strip()
        plist_path = str(launchagent.get("path") or launchagent_plist_path(label)).strip()
        if not label or not plist_path:
            continue
        proc = subprocess.run(
            ["launchctl", "bootout", launchagent_service_domain(), plist_path],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0:
            stopped_plists.add(str(Path(plist_path).expanduser().resolve()))
            actions.append(f"unloaded superseded LaunchAgent {label} root={other_root}")
            continue
        detail = (proc.stderr or proc.stdout or "").strip().lower()
        if "could not find service" in detail or "no such process" in detail or "not loaded" in detail:
            stopped_plists.add(str(Path(plist_path).expanduser().resolve()))
            actions.append(f"superseded LaunchAgent already inactive {label} root={other_root}")

    for plist_path, label, working_directory, env_file_text in candidate_plists:
        resolved_plist = str(plist_path.expanduser().resolve())
        if resolved_plist in stopped_plists:
            continue
        if working_directory and str(Path(working_directory).expanduser().resolve()) == normalized_target:
            continue
        same_memory_root = False
        if env_file_text:
            env_file_path = Path(env_file_text).expanduser()
            try:
                resolved_env_file = env_file_path.resolve()
            except OSError:
                resolved_env_file = env_file_path
            env_file_parent = str(resolved_env_file.parent.resolve()) if resolved_env_file.parent.exists() else str(resolved_env_file.parent)
            same_memory_root = env_file_parent == normalized_memory_root or env_file_parent.startswith(normalized_memory_root + os.sep)
        if not same_memory_root and working_directory:
            other_root = Path(working_directory).expanduser().resolve()
            if installation_profile_path(other_root).exists():
                try:
                    profile_payload = load_installation_profile(other_root)
                except Exception:
                    profile_payload = {}
                storage = dict(profile_payload.get("storage") or {})
                same_memory_root = str(storage.get("memory_root") or "").strip() == normalized_memory_root
        if not same_memory_root:
            continue
        proc = subprocess.run(
            ["launchctl", "bootout", launchagent_service_domain(), str(plist_path)],
            text=True,
            capture_output=True,
            check=False,
        )
        display_root = working_directory or "<unknown>"
        if proc.returncode == 0:
            actions.append(f"unloaded superseded LaunchAgent {label} root={display_root}")
            continue
        detail = (proc.stderr or proc.stdout or "").strip().lower()
        if "could not find service" in detail or "no such process" in detail or "not loaded" in detail:
            actions.append(f"superseded LaunchAgent already inactive {label} root={display_root}")

    return actions
