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


def _scheduler_command(root: Path, args: argparse.Namespace) -> str:
    profile = load_installation_profile(root)
    workflows = dict(profile.get("workflows") or {})
    runner = str(getattr(args, "runner", None) or workflows.get("dream_runner") or "same-as-session").strip() or "same-as-session"
    candidates = [
        root / "scripts" / "agent-context-engine.cmd",
        root / "scripts" / "agent-context-engine",
        root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine.cmd",
        root / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine",
    ]
    cli_path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
    parts = [
        f'"{cli_path.resolve()}"',
        "scheduler-run",
        "--grace-minutes",
        str(getattr(args, "grace_minutes", 5)),
        "--runner",
        runner,
        "--runner-timeout",
        str(getattr(args, "runner_timeout", 1800)),
        "--graph-runner",
        str(getattr(args, "graph_runner", None) or "same-as-session"),
        "--repair-missing-graph-patches-limit",
        str(getattr(args, "repair_missing_graph_patches_limit", 0)),
        "--dream-enqueue-limit",
        str(getattr(args, "dream_enqueue_limit", 25)),
        "--dream-queue-limit",
        str(getattr(args, "dream_queue_limit", 5)),
        "--neo4j-sync-limit",
        str(getattr(args, "neo4j_sync_limit", 5)),
        "--neo4j-batch-size",
        str(getattr(args, "neo4j_batch_size", 500)),
        "--neo4j-timeout",
        str(getattr(args, "neo4j_timeout", 60)),
    ]
    runner_model = str(getattr(args, "runner_model", None) or "").strip()
    if runner_model:
        parts.extend(["--runner-model", runner_model])
    graph_runner_model = str(getattr(args, "graph_runner_model", None) or "").strip()
    if graph_runner_model:
        parts.extend(["--graph-runner-model", graph_runner_model])
    parts.append("--sync-neo4j" if getattr(args, "sync_neo4j", False) else "--no-sync-neo4j")
    return " ".join(parts)


def _scheduler_script_path(root: Path) -> Path:
    profile = load_installation_profile(root)
    storage = dict(profile.get("storage") or {})
    memory_root = Path(str(storage.get("memory_root") or root / "memory")).expanduser().resolve()
    return memory_root / "local" / "windows-scheduler-run.cmd"


def _write_scheduler_script(root: Path, args: argparse.Namespace) -> Path:
    script_path = _scheduler_script_path(root)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.write_text(
        "\r\n".join(
            [
                "@echo off",
                "setlocal",
                f"cd /d \"{root}\"",
                f"set AGENT_CONTEXT_ENGINE_ROOT={root}",
                _scheduler_command(root, args),
                "exit /b %ERRORLEVEL%",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return script_path


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
        interval_minutes = max(1, int(getattr(args, "interval", 900)) // 60)
        script_path = _write_scheduler_script(root, args)
        command = [
            "schtasks",
            "/Create",
            "/TN",
            _task_name(root),
            "/SC",
            "MINUTE",
            "/MO",
            str(interval_minutes),
            "/RL",
            "LIMITED",
            "/TR",
            f'"{script_path}"',
            "/F",
        ]
        if getattr(args, "dry_run", False):
            print(" ".join(command))
            print(f"script: {script_path}")
            print(_scheduler_command(root, args))
            return 0
        exit_code = _run(command)
        if exit_code != 0 or not getattr(args, "load", False):
            return exit_code
        return _run(["schtasks", "/Run", "/TN", _task_name(root)])

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
