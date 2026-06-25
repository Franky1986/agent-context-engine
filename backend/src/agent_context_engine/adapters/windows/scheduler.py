from __future__ import annotations

import argparse
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ...application.instance_profile import load_installation_profile
from ...ports.scheduler_installation import SchedulerInstallerPort


def _task_name(root: Path) -> str:
    profile = load_installation_profile(root)
    instance_id = str(profile.get("instance_id") or root.name).strip() or root.name
    return f"AgentContextEngine\\{instance_id}"


def _monitor_command(root: Path) -> str:
    profile = load_installation_profile(root)
    monitor = dict(profile.get("monitor") or {})
    workflows = dict(profile.get("workflows") or {})
    runner = str(workflows.get("monitor_runner") or "codex").strip() or "codex"
    host = str(monitor.get("host") or "127.0.0.1").strip() or "127.0.0.1"
    port = int(monitor.get("port") or 8787)
    language = str(monitor.get("language") or "en").strip() or "en"
    candidates = [
        root / "scripts" / "agent-context-engine.cmd",
        root / "scripts" / "agent-context-engine",
        root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine.cmd",
        root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine",
    ]
    cli_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    return f'"{cli_path.resolve()}" monitor --runner {runner} --host {host} --port {port} --language {language} --replace-existing --no-open'


def _run(command: list[str]) -> int:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


@dataclass(frozen=True)
class WindowsTaskSchedulerInstaller(SchedulerInstallerPort):
    adapter_name: str = "windows_task_scheduler"
    support_level: str = "experimental"
    evidence: str = "public_docs"
    profile_id: str = "windows"

    def install(self, args: argparse.Namespace) -> int:
        root = Path(str(getattr(args, "target", None) or getattr(args, "installation_root", None) or Path.cwd())).expanduser().resolve()
        command = [
            "schtasks",
            "/Create",
            "/TN",
            _task_name(root),
            "/SC",
            "ONLOGON",
            "/RL",
            "LIMITED",
            "/TR",
            _monitor_command(root),
            "/F",
        ]
        if getattr(args, "dry_run", False):
            print(" ".join(command))
            return 0
        return _run(command)

    def uninstall(self, args: argparse.Namespace) -> int:
        root = Path(str(getattr(args, "target", None) or getattr(args, "installation_root", None) or Path.cwd())).expanduser().resolve()
        command = ["schtasks", "/Delete", "/TN", _task_name(root), "/F"]
        if getattr(args, "dry_run", False):
            print(" ".join(command))
            return 0
        return _run(command)

    def status(self, args: argparse.Namespace) -> int:
        root = Path(str(getattr(args, "target", None) or getattr(args, "installation_root", None) or Path.cwd())).expanduser().resolve()
        command = ["schtasks", "/Query", "/TN", _task_name(root), "/V", "/FO", "LIST"]
        if getattr(args, "dry_run", False):
            print(" ".join(command))
            return 0
        return _run(command)
