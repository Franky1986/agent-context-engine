from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

from ..adapters.launchagent import launchagent_runtime_status, reconcile_launchagent
from .firewall import firewall_status
from .hooks_state import hooks_control_status
from .instance_profile import (
    active_monitor_runtime_entries,
    normalize_launchagent_profile,
    instance_metadata_path_for_root,
    link_registry_path,
    load_link_registry,
    load_installation_profile,
    load_instance_metadata,
    load_storage_profile,
    monitor_restart_command,
    resolve_storage_profile,
    storage_profile_path,
    sync_instance_metadata,
    user_config_path,
    user_state_root,
)
from .integrations import integration_summary, manage_integration_hooks
from .platform import current_runtime_capabilities_payload, platform_profile_for_family, platform_profile_from_payload
from .platform.runtime_summary import runtime_selection_summary
from ..interfaces.hooks.support.queue import hook_queue_status
from .personal import PERSONAL_ROOT, parse_frontmatter, personal_files
from .retrieval import index_memory_document, retrieve_memory_with_safety, search_memory_chunks
from ..infrastructure.config import REPOS_INDEX, ensure_repos_index, env_file_path, read_repos_index_text, write_repos_index_text
from ..infrastructure.db import connect
from ..interfaces.http.version import MONITOR_VERSION, PRODUCT_VERSION


def _row_as_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _watched_runtime_paths(root: Path) -> list[Path]:
    return [
        root / "backend" / "src" / "agent_memory" / "interfaces" / "http" / "server.py",
        root / "backend" / "src" / "agent_memory" / "interfaces" / "http" / "version.py",
        root / "backend" / "src" / "agent_memory" / "adapters" / "launchagent.py",
        root / "backend" / "src" / "agent_memory" / "interfaces" / "cli" / "main.py",
        root / "scripts" / "ace",
        root / "scripts" / "agent-memory",
        env_file_path(root),
    ]


def _latest_runtime_change_epoch(root: Path) -> float:
    latest = 0.0
    for path in _watched_runtime_paths(root):
        try:
            latest = max(latest, path.stat().st_mtime)
        except OSError:
            continue
    return latest


def _monitor_process_status(
    *,
    runner: str,
    root: Path,
    monitor_version: str,
    monitor_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at_epoch = float(monitor_context.get("started_at_epoch") or time.time()) if monitor_context else time.time()
    latest_runtime_change_epoch = _latest_runtime_change_epoch(root)
    stale = latest_runtime_change_epoch > started_at_epoch
    profile = load_installation_profile(root)
    launchagent_profile = normalize_launchagent_profile(dict(profile.get("launchagent") or {}))
    platform_profile = dict(profile.get("platform_profile") or {})
    selected_platform_profile = platform_profile_from_payload(platform_profile)
    runtime_selection = runtime_selection_summary(selected_platform_profile)
    runtime_capabilities = current_runtime_capabilities_payload()
    storage = resolve_storage_profile(root)
    return {
        "pid": int(monitor_context.get("pid") or os.getpid()) if monitor_context else os.getpid(),
        "runner": runner,
        "version": monitor_version,
        "root": str(root),
        "cwd": str(Path.cwd()),
        "python_executable": sys.executable,
        "argv": list(monitor_context.get("argv") or sys.argv) if monitor_context else list(sys.argv),
        "started_at_epoch": started_at_epoch,
        "port": int(monitor_context.get("port") or 0) if monitor_context else 0,
        "host": str(monitor_context.get("host") or ""),
        "language": str(monitor_context.get("language") or ""),
        "latest_runtime_change_epoch": latest_runtime_change_epoch,
        "stale": stale,
        "restart_command": monitor_restart_command(root, runner=runner),
        "stale_reason": "repo runtime files changed after monitor start" if stale else "",
        "configured_launchagent_label": launchagent_profile["label"],
        "configured_launchagent_path": launchagent_profile["path"],
        "configured_launchagent_env_file": launchagent_profile["env_file"],
        "configured_platform_profile": platform_profile,
        "configured_runtime_capabilities": runtime_capabilities,
        "configured_runtime_selection": runtime_selection,
        "configured_memory_root": str(storage.get("memory_root") or ""),
        "configured_storage_schema_version": int(storage.get("schema_version") or 1),
    }


def monitor_status(
    conn: Any,
    runner: str,
    root: Path,
    *,
    monitor_version: str,
    monitor_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hook_queue = hook_queue_status()
    queued = int(hook_queue.get("queued_events") or 0)
    pending_dreams = conn.execute(
        """
        select count(*) as c
        from sessions
        where last_event_seq > last_dream_event_seq
           or dream_status = 'dream_pending'
        """
    ).fetchone()["c"]

    profile = load_installation_profile(root)
    launchagent_profile = normalize_launchagent_profile(dict(profile.get("launchagent") or {}))
    platform_profile = dict(profile.get("platform_profile") or {})
    selected_platform_profile = platform_profile_from_payload(platform_profile)
    runtime_selection = runtime_selection_summary(selected_platform_profile)
    runtime_capabilities = current_runtime_capabilities_payload()
    launchagent_label = launchagent_profile["label"]
    launchagent_path = launchagent_profile["path"]
    launchagent_env_file = launchagent_profile["env_file"]
    storage = resolve_storage_profile(root)
    runtime_storage_profile = load_storage_profile(Path(str(storage.get("memory_root") or root / "memory")))
    instance_metadata = sync_instance_metadata(root)
    active_monitor_entries = active_monitor_runtime_entries()
    current_monitor_entry = next(
        (
            entry
            for entry in active_monitor_entries
            if str(entry.get("installation_root") or "") == str(root.resolve())
        ),
        {},
    )

    return {
        "runner": runner,
        "monitor_version": monitor_version,
        "project_version": PRODUCT_VERSION,
        "backend_version": PRODUCT_VERSION,
        "root": str(root),
        "install_root": str(root),
        "platform": str(profile.get("platform") or ""),
        "platform_profile": platform_profile,
        "runtime_capabilities": runtime_capabilities,
        "runtime_selection": runtime_selection,
        "memory_root": str(storage.get("memory_root") or ""),
        "storage_schema_version": int(storage.get("schema_version") or 1),
        "storage_attached_at": str(storage.get("attached_at") or ""),
        "storage_profile_path": str(storage_profile_path(Path(str(storage.get("memory_root") or root / "memory")))),
        "storage_instance_id": str(runtime_storage_profile.get("storage_instance_id") or ""),
        "user_state_root": str(user_state_root()),
        "user_config_path": str(user_config_path()),
        "instance_metadata_path": str(instance_metadata_path_for_root(root)),
        "instance_metadata": instance_metadata,
        "installed_at": str(instance_metadata.get("installed_at") or ""),
        "installed_by_version": str(instance_metadata.get("installed_by_version") or ""),
        "last_updated_at": str(instance_metadata.get("last_updated_at") or ""),
        "last_updated_by_version": str(instance_metadata.get("last_updated_by_version") or ""),
        "sessions": conn.execute("select count(*) as c from sessions").fetchone()["c"],
        "events": conn.execute("select count(*) as c from events").fetchone()["c"],
        "pending_summaries": conn.execute(
            "select count(*) as c from sessions where last_event_seq > last_summary_event_seq or summary_status = 'summary_pending'"
        ).fetchone()["c"],
        "pending_dreams": pending_dreams,
        "pending_dreams_mode": "cheap",
        "running_dreams": conn.execute("select count(*) as c from dream_runs where status = 'running'").fetchone()["c"],
        "queued_events": queued,
        "hook_queue": hook_queue,
        "neo4j_configured": bool(
            os.environ.get("AGENT_MEMORY_NEO4J_PASSWORD")
            or env_file_path(root).exists()
        ),
        "firewall": firewall_status(conn),
        "hooks": hooks_control_status(root=root),
        "integrations": integration_summary(root=root, probe_gemini=False),
        "monitor_process": _monitor_process_status(runner=runner, root=root, monitor_version=monitor_version, monitor_context=monitor_context),
        "monitor_runtime_registry": {
            "current": current_monitor_entry,
            "active_entries": active_monitor_entries,
        },
        "link_registry_path": str(link_registry_path()),
        "link_registry": load_link_registry(),
        "launchagent": launchagent_runtime_status(label=launchagent_label, env_file=launchagent_env_file, plist_path=launchagent_path, root=root),
    }


def monitor_reconcile_runtime(*, root: Path) -> dict[str, Any]:
    profile = load_installation_profile(root)
    launchagent_profile = normalize_launchagent_profile(dict(profile.get("launchagent") or {}))
    platform_profile = dict(profile.get("platform_profile") or {})
    selected_platform_profile = platform_profile_from_payload(platform_profile)
    runtime_selection = runtime_selection_summary(selected_platform_profile)
    runtime_capabilities = current_runtime_capabilities_payload()
    launchagent_label = launchagent_profile["label"]
    launchagent_path = launchagent_profile["path"]
    launchagent_env_file = launchagent_profile["env_file"]
    return {
        "platform_profile": platform_profile,
        "runtime_capabilities": runtime_capabilities,
        "runtime_selection": runtime_selection,
        "launchagent": reconcile_launchagent(label=launchagent_label, env_file=launchagent_env_file, plist_path=launchagent_path, root=root),
        "monitor_restart_command": monitor_restart_command(root),
        "root": str(root),
    }


def monitor_integrations(root: Path) -> dict[str, Any]:
    return integration_summary(root=root, probe_gemini=False)


def monitor_manage_integration_hooks(root: Path, client: str, action: str, project_path: str | None = None) -> dict[str, Any]:
    target_root = Path(project_path).expanduser().resolve() if project_path else None
    return manage_integration_hooks(client=client, action=action, root=root, target_root=target_root)


def monitor_search(conn: Any, query: str, limit: int) -> dict[str, Any]:
    rows = search_memory_chunks(conn, query, limit=limit)
    return {"results": [_row_as_dict(row) for row in rows]}


def monitor_retrieve(
    conn: Any,
    query: str,
    limit: int,
    kind: str | None = None,
    include_risky: bool = False,
    expansion_mode: str = "auto",
    runner: str | None = None,
    runner_model_value: str | None = None,
    runner_timeout: int = 20,
) -> dict[str, Any]:
    return retrieve_memory_with_safety(
        conn,
        query,
        kind=kind,
        include_risky=include_risky,
        limit=max(1, min(limit, 50)),
        runner="monitor",
        log=False,
        query_expansion_mode=expansion_mode,
        query_expander_runner=runner,
        query_expander_model=runner_model_value,
        query_expander_timeout=min(runner_timeout, 30),
        safety_scan=False,
    )


def monitor_retrieval_runs(conn: Any, limit: int = 30) -> dict[str, Any]:
    rows = [
        _row_as_dict(row)
        for row in conn.execute(
            """
            select *
            from retrieval_runs
            order by started_at desc
            limit ?
            """,
            (max(1, min(limit, 200)),),
        )
    ]
    return {"runs": rows}


def monitor_retrieval_run(conn: Any, retrieval_run_id: str) -> dict[str, Any]:
    run = conn.execute("select * from retrieval_runs where retrieval_run_id = ?", (retrieval_run_id,)).fetchone()
    if run is None:
        raise ValueError(f"retrieval run not found: {retrieval_run_id}")
    results = [
        _row_as_dict(row)
        for row in conn.execute(
            """
            select *
            from retrieval_results
            where retrieval_run_id = ?
            order by rank
            """,
            (retrieval_run_id,),
        )
    ]
    access = [
        _row_as_dict(row)
        for row in conn.execute(
            """
            select *
            from memory_access_log
            where retrieval_run_id = ?
            order by accessed_at, target_kind, target_id
            """,
            (retrieval_run_id,),
        )
    ]
    return {"run": _row_as_dict(run), "results": results, "access": access}


def monitor_personal_files() -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    startup_safe = 0
    private_count = 0
    for path in personal_files():
        meta = parse_frontmatter(path)
        body = path.read_text(encoding="utf-8", errors="replace")
        if body.startswith("---\n"):
            end = body.find("\n---", 4)
            if end >= 0:
                body = body[end + len("\n---") :].lstrip()
        rel = str(path.relative_to(PERSONAL_ROOT))
        if meta.get("injection_policy") == "startup_safe" and meta.get("sensitivity") == "normal":
            startup_safe += 1
        if meta.get("sensitivity") in {"private", "secret"}:
            private_count += 1
        files.append(
            {
                "path": rel,
                "title": meta.get("title") or rel,
                "memory_kind": meta.get("memory_kind"),
                "source_kind": meta.get("source_kind"),
                "confidence": meta.get("confidence"),
                "risk_level": meta.get("risk_level"),
                "sensitivity": meta.get("sensitivity"),
                "injection_policy": meta.get("injection_policy"),
                "preview": " ".join(body.split())[:420],
            }
        )
    files.sort(key=lambda item: str(item["path"]))
    return {"files": files, "total": len(files), "startup_safe": startup_safe, "private_count": private_count}


def monitor_personal_file(path_value: str) -> dict[str, Any]:
    candidate = (PERSONAL_ROOT / path_value).resolve()
    root = PERSONAL_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("path escapes personal memory root")
    if candidate.suffix != ".md" or not candidate.exists():
        raise ValueError(f"personal memory file not found: {path_value}")
    meta = parse_frontmatter(candidate)
    return {
        "path": str(candidate.relative_to(PERSONAL_ROOT)),
        "frontmatter": meta,
        "content": candidate.read_text(encoding="utf-8", errors="replace"),
    }


def monitor_save_personal_file(path_value: str, content: str) -> dict[str, Any]:
    candidate = (PERSONAL_ROOT / path_value).resolve()
    root = PERSONAL_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("path escapes personal memory root")
    if candidate.suffix != ".md":
        raise ValueError("personal memory files must be markdown")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    meta = parse_frontmatter(candidate)
    try:
        confidence = float(meta.get("confidence", "0.5"))
    except ValueError:
        confidence = 0.5
    try:
        conn = connect()
        with conn:
            index_memory_document(
                conn,
                candidate,
                kind="personal_memory",
                project_id="personal",
                title=str(candidate.relative_to(PERSONAL_ROOT)),
                memory_kind=meta.get("memory_kind") or "personal_operating",
                source_kind=meta.get("source_kind") or "manual",
                confidence=confidence,
                risk_level=meta.get("risk_level") or "low",
                sensitivity=meta.get("sensitivity") or "normal",
                injection_policy=meta.get("injection_policy") or "on_demand",
                evidence=meta.get("evidence") or [],
            )
    except Exception:
        pass
    return {
        "path": str(candidate.relative_to(PERSONAL_ROOT)),
        "frontmatter": meta,
        "content": candidate.read_text(encoding="utf-8", errors="replace"),
        "saved": True,
    }


def monitor_repo_index() -> dict[str, Any]:
    path = ensure_repos_index(ROOT)
    content = read_repos_index_text(ROOT)
    return {
        "path": str(path.relative_to(path.parents[2])) if path.exists() else str(REPOS_INDEX.relative_to(REPOS_INDEX.parents[2])),
        "exists": bool(content) or path.exists(),
        "content": content,
        "privacy_note": "Local repository index; may contain private filesystem paths and project notes.",
    }


def monitor_save_repo_index(content: str) -> dict[str, Any]:
    path = write_repos_index_text(content, ROOT)
    try:
        conn = connect()
        with conn:
            index_memory_document(
                conn,
                path,
                kind="repo_index",
                project_id="personal",
                title="repository-index",
                memory_kind="repo_index",
                source_kind="runtime_repo_index",
                confidence=0.9,
                risk_level="low",
                sensitivity="normal",
                injection_policy="on_demand",
                evidence=[],
            )
    except Exception:
        pass
    return {
        "path": str(path.relative_to(path.parents[2])),
        "exists": True,
        "content": path.read_text(encoding="utf-8", errors="replace"),
        "saved": True,
        "privacy_note": "Local repository index; may contain private filesystem paths and project notes.",
    }
