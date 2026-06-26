from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote
from typing import Any

from ..adapters.launchagent import launchagent_loaded, launchagent_runtime_status, load_env_file
from .instance_profile import (
    instance_metadata_path_for_root,
    link_registry_path,
    load_link_registry,
    load_installation_profile,
    load_instance_metadata,
    load_storage_profile,
    normalize_launchagent_profile,
    resolve_monitor_profile,
    resolve_storage_profile,
    resolve_wrapper_naming,
    storage_profile_path,
    sync_instance_metadata,
    user_cli_link_path,
    user_config_path,
)
from .installation import frontend_build_status, python_runtime_status
from .integrations import workspace_binding_status
from .platform import current_runtime_capabilities_payload, platform_profile_for_family, platform_profile_from_payload
from .platform.runtime_summary import runtime_selection_summary
from ..infrastructure.config import DB_PATH, ENV_FILE_PATH, MEMORY_DIR, REPOS_INDEX, ROOT, SKILL_ROOT
from ..infrastructure.db import connect, dreamable_sessions


def is_under_root(value: str | None) -> bool:
    if not value:
        return True
    try:
        path = Path(value).expanduser()
        if not path.is_absolute():
            return True
        path.resolve().relative_to(ROOT.resolve())
        return True
    except (OSError, ValueError):
        return False


def repo_index_external_paths() -> list[str]:
    if not REPOS_INDEX.exists():
        return []
    paths: list[str] = []
    for line in REPOS_INDEX.read_text(encoding="utf-8", errors="replace").splitlines():
        if "file://" not in line:
            continue
        raw = line.split("file://", 1)[1].split(")", 1)[0]
        path = unquote(raw)
        if not is_under_root(path):
            paths.append(path)
    return paths


def relocation_report(conn) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    details: list[str] = []
    root = str(ROOT.resolve())
    rows = conn.execute(
        """
        select
          sum(case when cwd is not null and cwd != '' and cwd not like ? then 1 else 0 end) as cwd_count,
          sum(case when last_workdir is not null and last_workdir != '' and last_workdir not like ? then 1 else 0 end) as workdir_count,
          sum(case when transcript_path is not null and transcript_path != '' and transcript_path not like ? then 1 else 0 end) as transcript_count
        from sessions
        """,
        (root + "%", root + "%", root + "%"),
    ).fetchone()
    counts = {key: int(rows[key] or 0) for key in rows.keys()} if rows else {}
    if any(counts.values()):
        warnings.append(
            "stored session paths outside this root "
            f"(cwd={counts.get('cwd_count', 0)}, last_workdir={counts.get('workdir_count', 0)}, "
            f"transcript={counts.get('transcript_count', 0)})"
        )
        sample = conn.execute(
            """
            select session_id, cwd, last_workdir, transcript_path
            from sessions
            where (cwd is not null and cwd != '' and cwd not like ?)
               or (last_workdir is not null and last_workdir != '' and last_workdir not like ?)
               or (transcript_path is not null and transcript_path != '' and transcript_path not like ?)
            order by coalesce(last_event_at, started_at) desc
            limit 3
            """,
            (root + "%", root + "%", root + "%"),
        ).fetchall()
        for row in sample:
            details.append(
                f"  - {row['session_id']}: cwd={row['cwd'] or '-'} workdir={row['last_workdir'] or '-'} "
                f"transcript={row['transcript_path'] or '-'}"
            )
    external_repos = repo_index_external_paths()
    if external_repos:
        warnings.append(f"repo index references {len(external_repos)} path(s) outside this root")
        details.extend(f"  - repo: {path}" for path in external_repos[:3])
    return warnings, details


def local_env_values() -> dict[str, str]:
    return load_env_file(ENV_FILE_PATH)


def runtime_setting(env_values: dict[str, str], key: str, default: str = "-") -> str:
    value = os.environ.get(key)
    if value is not None and value != "":
        return value
    value = env_values.get(key)
    if value is not None and value != "":
        return value
    return default


def run_doctor_checks(
    *,
    check_codex_features: bool,
    relocation_report_requested: bool,
) -> tuple[list[str], int]:
    lines: list[str] = []
    failures = 0

    env_values = local_env_values()
    pipeline_version = runtime_setting(env_values, "AGENT_MEMORY_PIPELINE_VERSION", "")
    runtime = python_runtime_status(ROOT)
    frontend = frontend_build_status(ROOT)
    profile = load_installation_profile(ROOT)
    wrapper_naming = resolve_wrapper_naming(ROOT)
    monitor_profile = resolve_monitor_profile(ROOT)
    storage_profile = resolve_storage_profile(ROOT)
    launchagent_profile = normalize_launchagent_profile(dict(profile.get("launchagent") or {}))
    instance_id = str(profile.get("instance_id") or ROOT.name)
    runtime_storage_profile = load_storage_profile(Path(storage_profile["memory_root"]))
    lines.append(f"ok  instance id: {instance_id}")
    lines.append(f"ok  install root: {profile.get('root') or str(ROOT.resolve())}")
    lines.append(f"ok  memory root: {storage_profile.get('memory_root')}")
    lines.append(f"ok  storage schema version: {storage_profile.get('schema_version')}")
    lines.append(f"ok  storage profile: {storage_profile_path(Path(storage_profile['memory_root']))}")
    lines.append(f"ok  user config: {user_config_path()}")
    lines.append(f"ok  instance metadata: {instance_metadata_path_for_root(ROOT)}")
    lines.append(f"ok  link registry: {link_registry_path()}")
    lines.append(f"ok  user cli shortcut: {user_cli_link_path()}")
    instance_metadata = load_instance_metadata(instance_id)
    link_registry = load_link_registry()
    if instance_metadata:
        if str(instance_metadata.get("installed_at") or "").strip():
            lines.append(
                "ok  installed at: "
                + f"{instance_metadata.get('installed_at')} "
                + f"(version={instance_metadata.get('installed_by_version') or '-'})"
            )
        if str(instance_metadata.get("last_updated_at") or "").strip():
            lines.append(
                "ok  last updated at: "
                + f"{instance_metadata.get('last_updated_at')} "
                + f"(version={instance_metadata.get('last_updated_by_version') or '-'})"
            )
    ace_entry = dict((link_registry.get("entries") or {}).get("ace") or {})
    if ace_entry:
        lines.append(
            "ok  user cli target: "
            + f"{ace_entry.get('target') or '-'} "
            + f"(updated={ace_entry.get('updated_at') or '-'})"
        )
    lines.append(
        "ok  storage mode: "
        + ("legacy-co-located" if str(storage_profile.get("memory_root")) == str((ROOT / "memory").resolve()) else "external-or-explicit")
    )
    if runtime_storage_profile.get("storage_instance_id"):
        lines.append(f"ok  storage instance id: {runtime_storage_profile.get('storage_instance_id')}")
    lines.append(
        "ok  wrapper naming: "
        + f"prefix={wrapper_naming.get('prefix') or '-'} suffix={wrapper_naming.get('suffix') or '-'}"
    )
    lines.append(
        "ok  monitor default: "
        + f"{monitor_profile.get('host')}:{monitor_profile.get('port')} language={monitor_profile.get('language')}"
    )
    lines.append(
        "ok  launchagent profile: "
        + f"label={launchagent_profile.get('label') or '-'} "
        + f"path={launchagent_profile.get('path') or '-'} "
        + f"env_file={launchagent_profile.get('env_file') or '-'}"
    )
    platform_profile = dict(profile.get("platform_profile") or {})
    platform_profile_id = str(platform_profile.get("profile_id") or profile.get("platform") or "unknown")
    platform_support_level = str(platform_profile.get("support_level") or "unsupported")
    platform_evidence = str(platform_profile.get("evidence") or "inferred")
    platform_notes = str(platform_profile.get("notes") or "").strip()
    selected_platform_profile = platform_profile_from_payload(platform_profile)
    platform_family = str(selected_platform_profile.family.value if getattr(selected_platform_profile, "family", None) is not None else "")
    runtime_selection = runtime_selection_summary(selected_platform_profile)
    runtime_capabilities = current_runtime_capabilities_payload()
    platform_label = "ok" if platform_support_level == "supported" else "warn"
    lines.append(
        f"{platform_label}  platform profile: "
        + f"{platform_profile_id} support={platform_support_level} evidence={platform_evidence}"
    )
    if platform_notes:
        lines.append(f"{platform_label}  platform notes: {platform_notes}")
    lines.append(
        "ok  runtime capabilities: "
        + f"platform_token={runtime_capabilities.get('platform_token') or ''} "
        + f"profile={runtime_capabilities.get('profile_id') or ''} "
        + f"entries={len(dict(runtime_capabilities.get('capability_matrix') or {}))}"
    )
    lines.append(
        f"{platform_label}  instruction renderer: "
        + f"{((runtime_selection.get('instruction_renderer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('instruction_renderer') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('instruction_renderer') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  hook renderer: "
        + f"{((runtime_selection.get('hook_renderer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('hook_renderer') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('hook_renderer') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  wrapper renderer: "
        + f"{((runtime_selection.get('wrapper_renderer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('wrapper_renderer') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('wrapper_renderer') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  command publisher: "
        + f"{((runtime_selection.get('command_publisher') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('command_publisher') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('command_publisher') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  executable permission adapter: "
        + f"{((runtime_selection.get('executable_permission_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('executable_permission_adapter') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('executable_permission_adapter') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  system open adapter: "
        + f"{((runtime_selection.get('system_open_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('system_open_adapter') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('system_open_adapter') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  process launch adapter: "
        + f"{((runtime_selection.get('process_launch_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('process_launch_adapter') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('process_launch_adapter') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  workspace binding adapter: "
        + f"{((runtime_selection.get('workspace_binding_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('workspace_binding_adapter') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('workspace_binding_adapter') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    lines.append(
        f"{platform_label}  path quoting adapter: "
        + f"{((runtime_selection.get('path_quoting_adapter') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
        + f"support={((runtime_selection.get('path_quoting_adapter') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
        + f"evidence={((runtime_selection.get('path_quoting_adapter') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
    )
    scheduler_capability = next(
        (
            capability
            for capability in list(platform_profile.get("capabilities") or [])
            if isinstance(capability, dict) and str(capability.get("name") or "") == "scheduler_backend"
        ),
        None,
    )
    if isinstance(scheduler_capability, dict):
        scheduler_status = str(scheduler_capability.get("status") or "unsupported")
        scheduler_support = str(scheduler_capability.get("support_level") or platform_support_level)
        scheduler_evidence = str(scheduler_capability.get("evidence") or platform_evidence)
        scheduler_implementation = str(scheduler_capability.get("implementation") or "").strip() or "-"
        scheduler_label = "ok" if scheduler_status == "supported" else "warn"
        lines.append(
            f"{scheduler_label}  scheduler capability: "
            + f"status={scheduler_status} support={scheduler_support} evidence={scheduler_evidence} implementation={scheduler_implementation}"
        )
        lines.append(
            f"{scheduler_label}  scheduler installer: "
            + f"{((runtime_selection.get('scheduler_installer') or {}).get('name') if isinstance(runtime_selection, dict) else '')} "
            + f"support={((runtime_selection.get('scheduler_installer') or {}).get('support_level') if isinstance(runtime_selection, dict) else '')} "
            + f"evidence={((runtime_selection.get('scheduler_installer') or {}).get('evidence') if isinstance(runtime_selection, dict) else '')}"
        )

    hook_script_suffix = ".cmd" if platform_family == "windows" else ".sh"
    checks = [
        ([ROOT / ".codex" / "hooks.json"], "Codex hooks config", True),
        ([ROOT / ".codex" / "hooks" / f"hook_adapter{hook_script_suffix}", ROOT / ".codex" / "hooks" / "hook_adapter.sh", ROOT / ".codex" / "hooks" / "hook_adapter.cmd"], "Codex hook adapter", True),
        ([ROOT / ".claude" / "settings.json"], "Claude Code hooks config", True),
        ([ROOT / ".claude" / "hooks" / f"hook_adapter{hook_script_suffix}", ROOT / ".claude" / "hooks" / "hook_adapter.sh", ROOT / ".claude" / "hooks" / "hook_adapter.cmd"], "Claude Code hook adapter", True),
        ([ROOT / ".agents" / "hooks.json"], "Antigravity CLI hooks config", False),
        ([ROOT / ".agents" / "hooks" / f"hook_adapter{hook_script_suffix}", ROOT / ".agents" / "hooks" / "hook_adapter.sh", ROOT / ".agents" / "hooks" / "hook_adapter.cmd"], "Antigravity CLI hook adapter", False),
        ([ROOT / ".gemini" / "settings.json"], "Gemini CLI hooks config", False),
        ([ROOT / ".gemini" / "hooks" / f"hook_adapter{hook_script_suffix}", ROOT / ".gemini" / "hooks" / "hook_adapter.sh", ROOT / ".gemini" / "hooks" / "hook_adapter.cmd"], "Gemini CLI hook adapter", False),
        ([SKILL_ROOT / "scripts" / "agent_context_engine.py"], "agent memory CLI", True),
        ([REPOS_INDEX], "repo index", True),
    ]
    for candidates, label, required in checks:
        path = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        ok = path.exists()
        intentionally_disabled = (
            not ok
            and pipeline_version == "2"
            and label.startswith("Codex ")
        )
        if intentionally_disabled:
            lines.append(f"warn  {label}: intentionally disabled for pipeline v2 development: {path}")
            continue
        status = "ok" if ok else "missing" if required else "warn"
        lines.append(f"{status}  {label}: {path}")
        failures += 0 if ok or not required else 1

    version = pipeline_version or runtime_setting(env_values, "AGENT_MEMORY_PIPELINE_VERSION", "1")
    lines.append(f"ok  runtime pipeline version: {version}")
    interval = runtime_setting(env_values, "AGENT_MEMORY_DREAM_INTERVAL_SECONDS", "900")
    lines.append(f"ok  runtime dream interval seconds: {interval}")
    neo4j_database = runtime_setting(env_values, "AGENT_MEMORY_NEO4J_DATABASE", "-")
    neo4j_uri = runtime_setting(env_values, "AGENT_MEMORY_NEO4J_URI", "-")
    lines.append(f"ok  runtime neo4j database: {neo4j_database}")
    lines.append(f"ok  runtime neo4j uri configured: {'yes' if neo4j_uri != '-' else 'no'}")

    launch_label = str(launchagent_profile.get("label") or "")
    launch_path = Path(str(launchagent_profile.get("path") or ""))
    installed = launch_path.exists()
    loaded = launchagent_loaded(launch_label)
    if version == "2" and not installed:
        lines.append(f"warn  LaunchAgent: intentionally not installed during pipeline v2 development: {launch_path}")
    else:
        lines.append(f"{'ok' if installed else 'missing'}  LaunchAgent plist: {launch_path}")
    if loaded is None:
        lines.append("warn  LaunchAgent load state: unavailable")
    elif version == "2" and not loaded:
        lines.append("warn  LaunchAgent load state: intentionally unloaded during pipeline v2 development")
    else:
        lines.append(f"{'ok' if loaded else 'missing'}  LaunchAgent loaded: {'yes' if loaded else 'no'}")

    conn = connect()
    lines.append(f"ok  sqlite db: {DB_PATH}")
    codex = shutil.which("codex")
    lines.append(f"{'ok' if codex else 'missing'}  codex executable: {codex or '-'}")
    claude = shutil.which("claude")
    lines.append(f"{'ok' if claude else 'missing'}  claude executable: {claude or '-'}")
    antigravity = shutil.which("agy")
    lines.append(f"{'ok' if antigravity else 'missing'}  agy executable: {antigravity or '-'}")
    gemini = shutil.which("gemini")
    lines.append(f"{'ok' if gemini else 'missing'}  gemini executable: {gemini or '-'}")
    cursor_agent = shutil.which("cursor-agent")
    lines.append(f"{'ok' if cursor_agent else 'missing'}  cursor-agent executable: {cursor_agent or '-'}")

    if codex and check_codex_features:
        try:
            proc = subprocess.run(["codex", "features", "list"], text=True, capture_output=True, timeout=10)
            has_hooks = "hooks" in (proc.stdout + proc.stderr)
            lines.append(f"{'ok' if has_hooks else 'warn'}  codex feature hooks visible")
        except (OSError, subprocess.SubprocessError) as exc:
            lines.append(f"warn  codex features list failed: {exc}")

    row = conn.execute("select count(*) as c from sessions").fetchone()
    lines.append(f"ok  recorded sessions: {row['c']}")
    pending_summary = conn.execute(
        "select count(*) as c from sessions where last_event_seq > last_summary_event_seq or summary_status = 'summary_pending'"
    ).fetchone()
    pending_dream_count = len(dreamable_sessions(conn, True))
    running_dream = conn.execute("select count(*) as c from dream_runs where status = 'running'").fetchone()
    lines.append(f"ok  pending summaries: {pending_summary['c']}")
    lines.append(f"ok  pending dreams: {pending_dream_count}")
    lines.append(f"ok  running dreams: {running_dream['c']}")

    warnings, details = relocation_report(conn)
    if warnings:
        for warning in warnings:
            lines.append(f"warn  relocation: {warning}")
        if relocation_report_requested:
            lines.extend(details)
    else:
        lines.append("ok  relocation: stored paths fit this root")
    lines.append(f"{'ok' if runtime['venv_exists'] else 'warn'}  runtime venv: {runtime['venv_path']}")
    lines.append(f"{'ok' if runtime['yaml_available'] else 'missing'}  PyYAML import in runtime python: {runtime['python_path']}")
    frontend_label = "ok"
    frontend_state = "current"
    if not frontend["dist_exists"]:
        frontend_label = "missing"
        frontend_state = "dist missing"
    elif frontend["needs_build"]:
        frontend_label = "warn"
        frontend_state = "build stale"
    lines.append(f"{frontend_label}  monitor frontend build: {frontend_state} {frontend['dist_index']}")
    lines.append(f"{'ok' if frontend['node_modules_exists'] else 'warn'}  monitor frontend deps: {frontend['project_root']}/node_modules")
    launchagent_status = launchagent_runtime_status(
        label=launch_label,
        env_file=str(launchagent_profile.get("env_file") or ""),
        plist_path=launch_path,
        root=ROOT,
    )
    if bool((launchagent_status.get("drift") or {}).get("detected")):
        lines.append("warn  LaunchAgent drift: " + "; ".join((launchagent_status.get("drift") or {}).get("reasons") or []))
    workspace_roots = dict(profile.get("workspace_roots") or {})
    for client in ("codex", "claude", "cursor"):
        paths = [Path(path).expanduser().resolve() for path in list(workspace_roots.get(client) or [])]
        if not paths:
            lines.append(f"ok  {client} workspaces: none configured")
            continue
        lines.append(f"ok  {client} workspaces: {len(paths)} configured")
        for workspace_root in paths:
            binding = workspace_binding_status(client, root=workspace_root, expected_memory_root=ROOT)
            lines.append(
                f"{'ok' if binding.get('hook_binding_state') == 'bound' else 'warn'}  "
                + f"{client} workspace binding: {workspace_root} -> "
                + f"{binding.get('hook_binding_state')}"
                + (
                    f" target={binding.get('hook_binding_target_root')}"
                    if binding.get("hook_binding_target_root")
                    else ""
                )
            )
    exit_code = 1 if failures else 0
    try:
        sync_instance_metadata(ROOT, doctor_succeeded=exit_code == 0)
    except OSError as exc:
        lines.append(f"warn  instance metadata sync skipped: {exc}")
    return lines, exit_code
