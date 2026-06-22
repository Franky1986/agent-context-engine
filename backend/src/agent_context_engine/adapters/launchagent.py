from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ..infrastructure.config import CANONICAL_ENV_FILENAME, MEMORY_DIR, ROOT, SKILL_ROOT, safe_slug


DEFAULT_LABEL = f"com.agent-context-engine.{safe_slug(ROOT.name).lower()}"
DEFAULT_LAUNCHD_PATH = (
    str(Path.home() / ".local" / "bin") + ":"
    "/opt/homebrew/bin:"
    "/opt/homebrew/sbin:"
    "/usr/local/bin:"
    "/usr/bin:"
    "/bin:"
    "/usr/sbin:"
    "/sbin"
)
DEFAULT_ENV_FILE = f"memory/local/{CANONICAL_ENV_FILENAME}"
SECRET_ENV_RE = "PASSWORD"
LAUNCHAGENT_SPEC_VERSION = "2026-06-11.1"
MANAGED_RUNNER_ENV_KEYS = (
    "AGENT_MEMORY_INITIAL_DREAM_RUNNER",
    "AGENT_MEMORY_STOP_DREAM_RUNNER",
    "AGENT_MEMORY_WORKER_RUNNER",
    "AGENT_MEMORY_DREAM_GRAPH_RUNNER",
    "AGENT_MEMORY_PIPELINE_VERSION",
    "AGENT_MEMORY_ROOT",
    "AGENT_MEMORY_LAUNCHAGENT_LABEL",
    "AGENT_MEMORY_LAUNCHAGENT_SPEC_VERSION",
    "AGENT_MEMORY_ENV_FILE",
)
MANAGED_SECRET_ENV_KEYS = (
    "AGENT_MEMORY_NEO4J_PASSWORD",
)


def launch_agent_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def resolve_launch_agent_plist_path(label: str, path_spec: str | Path | None = None) -> Path:
    if path_spec in {None, ""}:
        return launch_agent_path(label)
    path = Path(path_spec).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def agent_memory_executable() -> Path:
    return SKILL_ROOT / "scripts" / "agent-context-engine"


def resolve_env_file(path_spec: str = DEFAULT_ENV_FILE) -> Path:
    env_file = Path(path_spec).expanduser()
    if not env_file.is_absolute():
        env_file = ROOT / env_file
    return env_file


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def redact_launchctl_output(text: str) -> str:
    redacted_lines = []
    for line in text.splitlines():
        if SECRET_ENV_RE in line.upper():
            prefix = line.split("=>", 1)[0].rstrip()
            redacted_lines.append(f"{prefix} => <redacted>")
        else:
            redacted_lines.append(line)
    return "\n".join(redacted_lines)


def _managed_env_for_signature(env: dict[str, str]) -> dict[str, str]:
    managed: dict[str, str] = {}
    for key in MANAGED_RUNNER_ENV_KEYS:
        value = env.get(key)
        if value:
            managed[key] = value
    return managed


def _secret_presence(env: dict[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in MANAGED_SECRET_ENV_KEYS}


def compute_launchagent_fingerprint(
    *,
    label: str,
    program_arguments: list[str],
    working_directory: str,
    env: dict[str, str],
    interval: int,
) -> str:
    payload = {
        "label": label,
        "program_arguments": program_arguments,
        "working_directory": working_directory,
        "interval": int(interval),
        "managed_env": _managed_env_for_signature(env),
        "secret_presence": _secret_presence(env),
        "spec_version": LAUNCHAGENT_SPEC_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def build_launch_agent_plist(args: argparse.Namespace) -> dict:
    log_dir = MEMORY_DIR / "logs"
    program = agent_memory_executable()
    env_file = resolve_env_file(args.env_file)
    env = {
        "AGENT_MEMORY_ROOT": str(ROOT),
        "PATH": args.path,
        "AGENT_MEMORY_ENV_FILE": str(env_file),
        "AGENT_MEMORY_LAUNCHAGENT_LABEL": args.label,
        "AGENT_MEMORY_LAUNCHAGENT_SPEC_VERSION": LAUNCHAGENT_SPEC_VERSION,
    }
    for key, value in load_env_file(env_file).items():
        if key.startswith("AGENT_MEMORY_"):
            env[key] = value
    program_arguments = [
        str(program),
        "scheduler-run",
        "--grace-minutes",
        str(args.grace_minutes),
        "--runner",
        args.runner,
        *(
            [
                "--runner-model",
                args.runner_model,
            ]
            if args.runner_model
            else []
        ),
        "--runner-timeout",
        str(args.runner_timeout),
        *(
            [
                "--graph-runner",
                args.graph_runner,
            ]
            if getattr(args, "graph_runner", None)
            else []
        ),
        *(
            [
                "--graph-runner-model",
                args.graph_runner_model,
            ]
            if getattr(args, "graph_runner_model", None)
            else []
        ),
        "--repair-missing-graph-patches-limit",
        str(getattr(args, "repair_missing_graph_patches_limit", 0)),
        "--dream-enqueue-limit",
        str(getattr(args, "dream_enqueue_limit", 25)),
        "--dream-queue-limit",
        str(getattr(args, "dream_queue_limit", 5)),
        "--sync-neo4j" if getattr(args, "sync_neo4j", False) else "--no-sync-neo4j",
        "--neo4j-sync-limit",
        str(args.neo4j_sync_limit),
        "--neo4j-batch-size",
        str(args.neo4j_batch_size),
        "--neo4j-timeout",
        str(args.neo4j_timeout),
    ]
    env["AGENT_MEMORY_LAUNCHAGENT_FINGERPRINT"] = compute_launchagent_fingerprint(
        label=args.label,
        program_arguments=program_arguments,
        working_directory=str(ROOT),
        env=env,
        interval=int(args.interval),
    )
    return {
        "Label": args.label,
        "ProgramArguments": program_arguments,
        "WorkingDirectory": str(ROOT),
        "EnvironmentVariables": env,
        "StartInterval": args.interval,
        "RunAtLoad": bool(args.run_at_load),
        "StandardOutPath": str(log_dir / "launchagent.out.log"),
        "StandardErrorPath": str(log_dir / "launchagent.err.log"),
    }


def launchctl_domain() -> str:
    return f"gui/{os.getuid()}"


def default_launchagent_args(
    *,
    label: str = DEFAULT_LABEL,
    env_file: str = DEFAULT_ENV_FILE,
) -> argparse.Namespace:
    return argparse.Namespace(
        label=label,
        plist_path=str(resolve_launch_agent_plist_path(label)),
        interval=900,
        grace_minutes=5,
        runner="same-as-session",
        runner_model=None,
        runner_timeout=1800,
        graph_runner="codex",
        graph_runner_model=None,
        sync_neo4j=False,
        neo4j_sync_limit=5,
        neo4j_batch_size=500,
        neo4j_timeout=60,
        repair_missing_graph_patches_limit=0,
        dream_enqueue_limit=25,
        dream_queue_limit=5,
        path=DEFAULT_LAUNCHD_PATH,
        env_file=env_file,
        run_at_load=False,
        load=False,
    )


def read_launchagent_plist(label: str = DEFAULT_LABEL, *, plist_path: str | Path | None = None) -> dict[str, Any] | None:
    path = resolve_launch_agent_plist_path(label, plist_path)
    if not path.exists():
        return None
    with path.open("rb") as handle:
        return plistlib.load(handle)


def _plist_snapshot(plist: dict[str, Any], *, path: Path) -> dict[str, Any]:
    env = dict(plist.get("EnvironmentVariables") or {})
    program_arguments = [str(item) for item in list(plist.get("ProgramArguments") or [])]
    return {
        "label": str(plist.get("Label") or path.stem),
        "plist_path": str(path),
        "program": program_arguments[0] if program_arguments else "",
        "program_arguments": program_arguments,
        "working_directory": str(plist.get("WorkingDirectory") or ""),
        "interval_seconds": int(plist.get("StartInterval") or 0),
        "stdout_path": str(plist.get("StandardOutPath") or ""),
        "stderr_path": str(plist.get("StandardErrorPath") or ""),
        "env_file": str(env.get("AGENT_MEMORY_ENV_FILE") or ""),
        "managed_env": _managed_env_for_signature(env),
        "secret_presence": _secret_presence(env),
        "fingerprint": str(env.get("AGENT_MEMORY_LAUNCHAGENT_FINGERPRINT") or ""),
        "spec_version": str(env.get("AGENT_MEMORY_LAUNCHAGENT_SPEC_VERSION") or ""),
    }


def expected_launchagent_snapshot(
    *,
    label: str = DEFAULT_LABEL,
    env_file: str = DEFAULT_ENV_FILE,
    plist_path: str | Path | None = None,
) -> dict[str, Any]:
    args = default_launchagent_args(label=label, env_file=env_file)
    plist = build_launch_agent_plist(args)
    return _plist_snapshot(plist, path=resolve_launch_agent_plist_path(label, plist_path))


def _launchctl_print(label: str) -> str:
    proc = subprocess.run(
        ["launchctl", "print", f"{launchctl_domain()}/{label}"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _parse_launchctl_runtime(text: str) -> dict[str, Any]:
    if not text:
        return {}
    state_match = re.search(r"^\s*state = (.+)$", text, re.MULTILINE)
    runs_match = re.search(r"^\s*runs = ([0-9]+)$", text, re.MULTILINE)
    exit_match = re.search(r"^\s*last exit code = (.+)$", text, re.MULTILINE)
    pid_match = re.search(r"pid = ([0-9]+)", text)
    return {
        "state": state_match.group(1).strip() if state_match else "",
        "runs": int(runs_match.group(1)) if runs_match else 0,
        "last_exit_code": exit_match.group(1).strip() if exit_match else "",
        "pid": int(pid_match.group(1)) if pid_match else None,
    }


def launchagent_runtime_status(
    *,
    label: str = DEFAULT_LABEL,
    env_file: str = DEFAULT_ENV_FILE,
    plist_path: str | Path | None = None,
) -> dict[str, Any]:
    expected = expected_launchagent_snapshot(label=label, env_file=env_file, plist_path=plist_path)
    path = resolve_launch_agent_plist_path(label, plist_path)
    installed_plist = read_launchagent_plist(label, plist_path=plist_path)
    installed = _plist_snapshot(installed_plist, path=path) if installed_plist else None
    loaded = launchagent_loaded(label)
    runtime = _parse_launchctl_runtime(_launchctl_print(label)) if loaded else {}

    drift_reasons: list[str] = []
    if installed is None:
        drift_reasons.append("launchagent not installed")
    else:
        if installed.get("program") != expected.get("program"):
            drift_reasons.append("program path differs from current install root")
        if installed.get("working_directory") != expected.get("working_directory"):
            drift_reasons.append("working directory differs from current install root")
        if installed.get("program_arguments") != expected.get("program_arguments"):
            drift_reasons.append("scheduler arguments differ from expected defaults")
        if installed.get("managed_env") != expected.get("managed_env"):
            drift_reasons.append("managed AGENT_MEMORY runtime env differs from expected values")
        if installed.get("fingerprint") != expected.get("fingerprint"):
            drift_reasons.append("launchagent fingerprint differs from expected configuration")
        if installed.get("spec_version") != expected.get("spec_version"):
            drift_reasons.append("launchagent spec version is outdated")
    if loaded is False:
        drift_reasons.append("launchagent is installed but not loaded")

    return {
        "supported": shutil.which("launchctl") is not None,
        "label": label,
        "expected": expected,
        "installed": installed,
        "loaded": loaded,
        "runtime": runtime,
        "drift": {
            "detected": bool(drift_reasons),
            "reasons": drift_reasons,
        },
        "recommended_command": f"./scripts/agent-context-engine install-launchagent --label {label} --plist-path {path} --env-file {env_file} --load",
    }


def reconcile_launchagent(
    *,
    label: str = DEFAULT_LABEL,
    env_file: str = DEFAULT_ENV_FILE,
    plist_path: str | Path | None = None,
) -> dict[str, Any]:
    before = launchagent_runtime_status(label=label, env_file=env_file, plist_path=plist_path)
    args = default_launchagent_args(label=label, env_file=env_file)
    args.plist_path = str(resolve_launch_agent_plist_path(label, plist_path))
    args.load = True
    started_at = time.time()
    exit_code = cmd_install_launchagent(args)
    after = launchagent_runtime_status(label=label, env_file=env_file, plist_path=plist_path)
    return {
        "ok": exit_code == 0,
        "action": "reloaded" if exit_code == 0 else "failed",
        "label": label,
        "started_at_epoch": started_at,
        "finished_at_epoch": time.time(),
        "command": "./scripts/agent-context-engine install-launchagent --load",
        "before": before,
        "after": after,
    }


def cmd_install_launchagent(args: argparse.Namespace) -> int:
    path = resolve_launch_agent_plist_path(args.label, getattr(args, "plist_path", None))
    path.parent.mkdir(parents=True, exist_ok=True)
    (MEMORY_DIR / "logs").mkdir(parents=True, exist_ok=True)
    plist = build_launch_agent_plist(args)
    with path.open("wb") as handle:
        plistlib.dump(plist, handle, sort_keys=False)
    print(f"wrote {path}")
    if args.load:
        subprocess.run(["launchctl", "bootout", launchctl_domain(), str(path)], check=False, capture_output=True)
        proc = subprocess.run(["launchctl", "bootstrap", launchctl_domain(), str(path)], text=True, capture_output=True)
        if proc.returncode != 0:
            print(proc.stderr.strip() or proc.stdout.strip(), file=sys.stderr)
            return proc.returncode
        subprocess.run(["launchctl", "enable", f"{launchctl_domain()}/{args.label}"], check=False)
        print(f"loaded {args.label}")
    else:
        print(f"not loaded; run: launchctl bootstrap {launchctl_domain()} {path}")
    return 0


def cmd_uninstall_launchagent(args: argparse.Namespace) -> int:
    path = resolve_launch_agent_plist_path(args.label, getattr(args, "plist_path", None))
    if args.unload:
        subprocess.run(["launchctl", "bootout", launchctl_domain(), str(path)], check=False)
        print(f"unloaded {args.label}")
    if path.exists():
        path.unlink()
        print(f"removed {path}")
    else:
        print(f"not installed: {path}")
    return 0


def cmd_launchagent_status(args: argparse.Namespace) -> int:
    path = resolve_launch_agent_plist_path(args.label, getattr(args, "plist_path", None))
    print(f"plist: {path}")
    print(f"installed: {'yes' if path.exists() else 'no'}")
    proc = subprocess.run(["launchctl", "print", f"{launchctl_domain()}/{args.label}"], text=True, capture_output=True)
    print(f"loaded: {'yes' if proc.returncode == 0 else 'no'}")
    if proc.returncode == 0 and args.verbose:
        print(redact_launchctl_output(proc.stdout))
    return 0


def launchagent_loaded(label: str = DEFAULT_LABEL) -> bool | None:
    if shutil.which("launchctl") is None:
        return None
    try:
        proc = subprocess.run(
            ["launchctl", "print", f"{launchctl_domain()}/{label}"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.returncode == 0
