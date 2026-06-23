from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..adapters.launchagent import DEFAULT_ENV_FILE, DEFAULT_LABEL, launch_agent_path
from ..infrastructure.config import DEFAULT_STORAGE_SCHEMA_VERSION, MEMORY_DIR, ROOT
from ..interfaces.http.version import MONITOR_VERSION, PRODUCT_VERSION

INSTALLATION_PROFILE_RELATIVE_PATH = Path("memory") / "local" / "installation-profile.json"
STORAGE_PROFILE_RELATIVE_PATH = Path("local") / "storage-profile.json"
USER_STATE_ROOT_NAME = ".agent-context-engine"
USER_CONFIG_FILENAME = "config.json"
USER_INSTANCES_DIRNAME = "instances"
USER_ACTIVE_DIRNAME = "active"
USER_CLI_LINK_NAME = "ace"
MONITOR_RUNTIME_REGISTRY_FILENAME = "monitor-runtime.json"
LINK_REGISTRY_FILENAME = "link-registry.json"
USER_CONFIG_VERSION = 1
INSTANCE_METADATA_VERSION = 1
MONITOR_RUNTIME_REGISTRY_VERSION = 1
LINK_REGISTRY_VERSION = 1
WORKFLOW_RUNNER_DEFAULTS = {
    "monitor_runner": "codex",
    "dream_runner": "codex",
    "query_expansion_runner": "codex",
}
WORKSPACE_ROOT_CLIENTS = ("codex", "claude", "cursor")
WORKFLOW_LABELS = {
    "monitor_runner": "Monitor and monitor ask",
    "dream_runner": "Dreaming and headless analysis",
    "query_expansion_runner": "LLM query expansion",
}
DEFAULT_MONITOR_HOST = "127.0.0.1"
DEFAULT_MONITOR_PORT = 8787


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def user_state_root(home: Path | None = None) -> Path:
    return ((home or Path.home()).expanduser() / USER_STATE_ROOT_NAME).resolve()


def default_user_storage_root(home: Path | None = None) -> Path:
    return default_instance_memory_root(home=home)


def user_active_dir(home: Path | None = None) -> Path:
    return user_state_root(home) / USER_ACTIVE_DIRNAME


def user_config_path(home: Path | None = None) -> Path:
    return user_state_root(home) / USER_CONFIG_FILENAME


def user_cli_link_path(home: Path | None = None) -> Path:
    return user_state_root(home) / USER_CLI_LINK_NAME


def monitor_runtime_registry_path(home: Path | None = None) -> Path:
    return user_state_root(home) / MONITOR_RUNTIME_REGISTRY_FILENAME


def link_registry_path(home: Path | None = None) -> Path:
    return user_state_root(home) / LINK_REGISTRY_FILENAME


def user_instances_dir(home: Path | None = None) -> Path:
    return user_state_root(home) / USER_INSTANCES_DIRNAME


def instance_root(instance_id: str, home: Path | None = None) -> Path:
    return user_instances_dir(home) / safe_instance_id(instance_id)


def default_instance_install_root(*, instance_id: str = "default", home: Path | None = None) -> Path:
    if safe_instance_id(instance_id) == "default":
        return (user_state_root(home) / "install").resolve()
    return (instance_root(instance_id, home) / "install").resolve()


def default_instance_memory_root(*, instance_id: str = "default", home: Path | None = None) -> Path:
    if safe_instance_id(instance_id) == "default":
        return (user_state_root(home) / "memory").resolve()
    return (instance_root(instance_id, home) / "memory").resolve()


def instance_metadata_path(instance_id: str, home: Path | None = None) -> Path:
    return instance_root(instance_id, home) / "instance.json"


def active_instance_link_path(home: Path | None = None) -> Path:
    return user_active_dir(home) / "current"


def active_install_link_path(home: Path | None = None) -> Path:
    return user_active_dir(home) / "install"


def active_memory_link_path(home: Path | None = None) -> Path:
    return user_active_dir(home) / "memory"


def safe_instance_id(value: str) -> str:
    normalized = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in str(value or "").strip()).strip("-")
    return normalized or "default"


def agent_memory_cli_for_root(root: Path = ROOT) -> str:
    if (root / "scripts" / "agent-context-engine").exists():
        return "./scripts/agent-context-engine"
    return "./docs/skills/agent-context-engine/scripts/agent-context-engine"


def installation_profile_path(root: Path = ROOT) -> Path:
    return root / INSTALLATION_PROFILE_RELATIVE_PATH


def storage_profile_path(memory_root: Path = MEMORY_DIR) -> Path:
    return memory_root / STORAGE_PROFILE_RELATIVE_PATH


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
    return {
        "version": 4,
        "instance_id": ROOT.name,
        "root": str(ROOT.resolve()),
        "platform": "mac",
        "storage": {
            "memory_root": str((ROOT / "memory").resolve()),
            "schema_version": DEFAULT_STORAGE_SCHEMA_VERSION,
            "managed_by_installation": True,
            "created_at": "",
            "attached_at": "",
        },
        "workflows": dict(WORKFLOW_RUNNER_DEFAULTS),
        "workspace_roots": {client: [] for client in WORKSPACE_ROOT_CLIENTS},
        "wrapper_naming": {
            "prefix": "",
            "suffix": "-ace",
            "template": "{prefix}{base}{suffix}",
        },
        "monitor": {
            "host": DEFAULT_MONITOR_HOST,
            "port": DEFAULT_MONITOR_PORT,
            "language": "en",
            "last_started_at": "",
            "last_started_by": "",
            "last_stopped_at": "",
            "last_seen_at": "",
            "last_known_url": "",
            "last_known_pid": 0,
        },
        "launchagent": {
            "label": DEFAULT_LABEL,
            "path": str(launch_agent_path(DEFAULT_LABEL)),
            "env_file": DEFAULT_ENV_FILE,
        },
    }


def default_user_config(home: Path | None = None) -> dict[str, Any]:
    return {
        "version": USER_CONFIG_VERSION,
        "default_language": "en",
        "default_monitor_host": DEFAULT_MONITOR_HOST,
        "default_monitor_port": DEFAULT_MONITOR_PORT,
        "default_wrapper_prefix": "",
        "default_wrapper_suffix": "-ace",
        "default_launchagent_enabled": True,
        "default_memory_root": str(default_user_storage_root(home)),
        "last_used_installation_root": "",
        "last_used_memory_root": "",
        "updated_at": "",
    }


def load_user_config(home: Path | None = None) -> dict[str, Any]:
    defaults = default_user_config(home)
    path = user_config_path(home)
    if not path.exists():
        return defaults
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    normalized = dict(defaults)
    normalized["version"] = max(1, int(payload.get("version") or USER_CONFIG_VERSION))
    normalized["default_language"] = str(payload.get("default_language") or defaults["default_language"]).strip().lower() or "en"
    normalized["default_monitor_host"] = str(payload.get("default_monitor_host") or defaults["default_monitor_host"]).strip() or DEFAULT_MONITOR_HOST
    try:
        normalized["default_monitor_port"] = max(1, min(int(payload.get("default_monitor_port") or defaults["default_monitor_port"]), 65535))
    except (TypeError, ValueError):
        normalized["default_monitor_port"] = DEFAULT_MONITOR_PORT
    normalized["default_wrapper_prefix"] = str(payload.get("default_wrapper_prefix") or "").strip()
    normalized["default_wrapper_suffix"] = str(payload.get("default_wrapper_suffix") or defaults["default_wrapper_suffix"]).strip()
    normalized["default_launchagent_enabled"] = bool(payload.get("default_launchagent_enabled", defaults["default_launchagent_enabled"]))
    try:
        normalized["default_memory_root"] = str(Path(str(payload.get("default_memory_root") or defaults["default_memory_root"])).expanduser().resolve())
    except OSError:
        normalized["default_memory_root"] = str(defaults["default_memory_root"])
    normalized["last_used_installation_root"] = str(payload.get("last_used_installation_root") or "").strip()
    normalized["last_used_memory_root"] = str(payload.get("last_used_memory_root") or "").strip()
    normalized["updated_at"] = str(payload.get("updated_at") or "")
    if normalized["default_language"] not in {"en", "de"}:
        normalized["default_language"] = "en"
    return normalized


def save_user_config(payload: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    current = load_user_config(home)
    current.update(payload or {})
    current["updated_at"] = _utc_timestamp()
    path = user_config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return current


def merge_user_config(
    *,
    default_language: str | None = None,
    default_monitor_host: str | None = None,
    default_monitor_port: int | None = None,
    default_wrapper_prefix: str | None = None,
    default_wrapper_suffix: str | None = None,
    default_launchagent_enabled: bool | None = None,
    default_memory_root: Path | None = None,
    last_used_installation_root: Path | None = None,
    last_used_memory_root: Path | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if default_language is not None:
        payload["default_language"] = str(default_language).strip().lower() or "en"
    if default_monitor_host is not None:
        payload["default_monitor_host"] = str(default_monitor_host).strip() or DEFAULT_MONITOR_HOST
    if default_monitor_port is not None:
        payload["default_monitor_port"] = max(1, min(int(default_monitor_port), 65535))
    if default_wrapper_prefix is not None:
        payload["default_wrapper_prefix"] = str(default_wrapper_prefix).strip()
    if default_wrapper_suffix is not None:
        payload["default_wrapper_suffix"] = str(default_wrapper_suffix).strip()
    if default_launchagent_enabled is not None:
        payload["default_launchagent_enabled"] = bool(default_launchagent_enabled)
    if default_memory_root is not None:
        payload["default_memory_root"] = str(default_memory_root.expanduser().resolve())
    if last_used_installation_root is not None:
        payload["last_used_installation_root"] = str(last_used_installation_root.expanduser().resolve())
    if last_used_memory_root is not None:
        payload["last_used_memory_root"] = str(last_used_memory_root.expanduser().resolve())
    return save_user_config(payload, home=home)


def default_instance_metadata(
    *,
    instance_id: str,
    installation_root: Path,
    memory_root: Path,
) -> dict[str, Any]:
    return {
        "version": INSTANCE_METADATA_VERSION,
        "instance_id": safe_instance_id(instance_id),
        "installation_root": str(installation_root.resolve()),
        "memory_root": str(memory_root.resolve()),
        "product_version": PRODUCT_VERSION,
        "backend_version": PRODUCT_VERSION,
        "monitor_version": MONITOR_VERSION,
        "storage_schema_version": DEFAULT_STORAGE_SCHEMA_VERSION,
        "monitor_host": DEFAULT_MONITOR_HOST,
        "monitor_port": DEFAULT_MONITOR_PORT,
        "language": "en",
        "wrapper_prefix": "",
        "wrapper_suffix": "",
        "launchagent_label": DEFAULT_LABEL,
        "launchagent_path": str(launch_agent_path(DEFAULT_LABEL)),
        "launchagent_env_file": DEFAULT_ENV_FILE,
        "checkout_name": installation_root.name,
        "checkout_branch": "",
        "checkout_commit": "",
        "checkout_remote": "",
        "checkout_dirty": False,
        "checkout_detected_at": "",
        "installed_at": "",
        "installed_by_version": "",
        "last_updated_at": "",
        "last_updated_by_version": "",
        "last_seen_at": "",
        "last_successful_doctor_at": "",
        "last_successful_check_at": "",
    }


def load_instance_metadata(instance_id: str, home: Path | None = None) -> dict[str, Any]:
    path = instance_metadata_path(instance_id, home)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def save_instance_metadata(instance_id: str, payload: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    path = instance_metadata_path(instance_id, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def default_link_registry() -> dict[str, Any]:
    return {
        "version": LINK_REGISTRY_VERSION,
        "updated_at": "",
        "entries": {},
    }


def load_link_registry(home: Path | None = None) -> dict[str, Any]:
    defaults = default_link_registry()
    path = link_registry_path(home)
    if not path.exists():
        return defaults
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    entries = payload.get("entries")
    normalized = dict(defaults)
    normalized["version"] = max(1, int(payload.get("version") or LINK_REGISTRY_VERSION))
    normalized["updated_at"] = str(payload.get("updated_at") or "")
    normalized["entries"] = dict(entries) if isinstance(entries, dict) else {}
    return normalized


def save_link_registry(payload: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    current = load_link_registry(home)
    current.update(payload or {})
    current["version"] = max(1, int(current.get("version") or LINK_REGISTRY_VERSION))
    current["updated_at"] = _utc_timestamp()
    entries = current.get("entries")
    current["entries"] = dict(entries) if isinstance(entries, dict) else {}
    path = link_registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return current


def record_link_registry_entry(
    *,
    logical_name: str,
    link_kind: str,
    path: Path,
    target: Path | None,
    status: str,
    installation_root: Path | None = None,
    command_name: str | None = None,
    changed_by_version: str | None = None,
    home: Path | None = None,
) -> dict[str, Any]:
    registry = load_link_registry(home)
    entries = dict(registry.get("entries") or {})
    key = str(logical_name).strip()
    now = _utc_timestamp()
    existing = dict(entries.get(key) or {})
    created_at = str(existing.get("created_at") or now)
    entry = {
        "logical_name": key,
        "link_kind": str(link_kind).strip(),
        "status": str(status).strip(),
        "path": str(path.expanduser().resolve(strict=False)),
        "target": str(target.expanduser().resolve(strict=False)) if target is not None else "",
        "installation_root": str(installation_root.expanduser().resolve(strict=False)) if installation_root is not None else "",
        "command_name": str(command_name or key).strip(),
        "created_at": created_at,
        "updated_at": now,
        "last_verified_at": now,
        "changed_by_version": str(changed_by_version or PRODUCT_VERSION).strip() or PRODUCT_VERSION,
    }
    entries[key] = entry
    save_link_registry({"entries": entries}, home=home)
    return entry


def _write_symlink(path: Path, target: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.exists():
        try:
            if path.resolve() == target.resolve():
                return
        except OSError:
            pass
        if path.is_dir() and not path.is_symlink():
            raise OSError(f"cannot replace non-symlink directory: {path}")
        path.unlink()
    path.symlink_to(target)


def sync_active_instance(
    *,
    instance_id: str,
    installation_root: Path,
    memory_root: Path,
    home: Path | None = None,
) -> None:
    root_path = instance_root(instance_id, home)
    _write_symlink(active_instance_link_path(home), root_path)
    _write_symlink(active_install_link_path(home), installation_root.resolve())
    _write_symlink(active_memory_link_path(home), memory_root.resolve())


def _git_value(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _git_checkout_metadata(root: Path) -> dict[str, Any]:
    branch = _git_value(root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _git_value(root, "rev-parse", "HEAD")
    remote = _git_value(root, "config", "--get", "remote.origin.url")
    dirty = bool(_git_value(root, "status", "--short"))
    return {
        "checkout_name": root.name,
        "checkout_branch": branch,
        "checkout_commit": commit,
        "checkout_remote": remote,
        "checkout_dirty": dirty,
        "checkout_detected_at": _utc_timestamp(),
    }


def _normalize_installation_profile(payload: dict[str, Any] | None) -> dict[str, Any]:
    profile = default_installation_profile()
    if isinstance(payload, dict):
        profile["version"] = max(2, int(payload.get("version") or 4))
        profile["instance_id"] = str(payload.get("instance_id") or profile["instance_id"]).strip() or profile["instance_id"]
        profile["root"] = str(payload.get("root") or profile["root"]).strip() or profile["root"]
        profile["platform"] = str(payload.get("platform") or "mac")
        storage = payload.get("storage")
        legacy_memory_root = str(profile["storage"]["memory_root"])
        if isinstance(storage, dict):
            try:
                memory_root = Path(str(storage.get("memory_root") or legacy_memory_root)).expanduser()
                if not memory_root.is_absolute():
                    memory_root = Path(profile["root"]).expanduser().resolve() / memory_root
                memory_root_text = str(memory_root.resolve())
            except OSError:
                memory_root_text = legacy_memory_root
            try:
                schema_version = int(storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION)
            except (TypeError, ValueError):
                schema_version = DEFAULT_STORAGE_SCHEMA_VERSION
            profile["storage"] = {
                "memory_root": memory_root_text,
                "schema_version": max(1, schema_version),
                "managed_by_installation": bool(storage.get("managed_by_installation", True)),
                "created_at": str(storage.get("created_at") or ""),
                "attached_at": str(storage.get("attached_at") or ""),
            }
        else:
            profile["storage"] = {
                "memory_root": legacy_memory_root,
                "schema_version": DEFAULT_STORAGE_SCHEMA_VERSION,
                "managed_by_installation": True,
                "created_at": "",
                "attached_at": "",
            }
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
                "last_started_at": str(monitor.get("last_started_at") or ""),
                "last_started_by": str(monitor.get("last_started_by") or ""),
                "last_stopped_at": str(monitor.get("last_stopped_at") or ""),
                "last_seen_at": str(monitor.get("last_seen_at") or ""),
                "last_known_url": str(monitor.get("last_known_url") or ""),
                "last_known_pid": int(monitor.get("last_known_pid") or 0),
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
    path = installation_profile_path(root)
    if not path.exists():
        return default_installation_profile()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_installation_profile()
    if not isinstance(payload, dict):
        return default_installation_profile()
    return _normalize_installation_profile(payload)


def save_installation_profile(root: Path = ROOT, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = _normalize_installation_profile(profile)
    path = installation_profile_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return normalized


def merge_installation_profile(
    root: Path = ROOT,
    *,
    instance_id: str | None = None,
    root_path: Path | None = None,
    workflows: dict[str, str] | None = None,
    workspace_roots: dict[str, list[Path]] | None = None,
    storage: dict[str, Any] | None = None,
    wrapper_naming: dict[str, str] | None = None,
    monitor: dict[str, Any] | None = None,
    launchagent: dict[str, str] | None = None,
) -> dict[str, Any]:
    profile = load_installation_profile(root)
    if instance_id is not None and str(instance_id).strip():
        profile["instance_id"] = str(instance_id).strip()
    if root_path is not None:
        profile["root"] = str(root_path.resolve())
    if storage:
        current_storage = dict(profile.get("storage") or {})
        if "memory_root" in storage and storage.get("memory_root") is not None:
            current_storage["memory_root"] = str(Path(str(storage.get("memory_root"))).expanduser().resolve())
        if "schema_version" in storage and storage.get("schema_version") is not None:
            try:
                current_storage["schema_version"] = max(1, int(storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION))
            except (TypeError, ValueError):
                current_storage["schema_version"] = DEFAULT_STORAGE_SCHEMA_VERSION
        if "managed_by_installation" in storage:
            current_storage["managed_by_installation"] = bool(storage.get("managed_by_installation"))
        if "created_at" in storage:
            current_storage["created_at"] = str(storage.get("created_at") or current_storage.get("created_at") or "")
        if "attached_at" in storage:
            current_storage["attached_at"] = str(storage.get("attached_at") or "")
        profile["storage"] = current_storage
    if workflows:
        for key, value in workflows.items():
            if key in WORKFLOW_RUNNER_DEFAULTS and str(value or "").strip():
                profile["workflows"][key] = str(value).strip()
    if workspace_roots:
        for client in WORKSPACE_ROOT_CLIENTS:
            if client not in workspace_roots:
                continue
            profile["workspace_roots"][client] = _normalize_path_strings([str(path) for path in workspace_roots[client]])
    if wrapper_naming:
        current = dict(profile.get("wrapper_naming") or {})
        if "prefix" in wrapper_naming:
            current["prefix"] = str(wrapper_naming.get("prefix") or "").strip()
        if "suffix" in wrapper_naming:
            current["suffix"] = str(wrapper_naming.get("suffix") or "").strip()
        current["template"] = str(current.get("template") or "{prefix}{base}{suffix}")
        profile["wrapper_naming"] = current
    if monitor:
        current_monitor = dict(profile.get("monitor") or {})
        if "host" in monitor:
            current_monitor["host"] = str(monitor.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
        if "language" in monitor:
            language = str(monitor.get("language") or "en").strip().lower() or "en"
            current_monitor["language"] = language if language in {"en", "de"} else "en"
        if "port" in monitor:
            try:
                port = int(monitor.get("port") or DEFAULT_MONITOR_PORT)
            except (TypeError, ValueError):
                port = DEFAULT_MONITOR_PORT
            current_monitor["port"] = max(1, min(port, 65535))
        for key in ("last_started_at", "last_started_by", "last_stopped_at", "last_seen_at", "last_known_url"):
            if key in monitor:
                current_monitor[key] = str(monitor.get(key) or "")
        if "last_known_pid" in monitor:
            try:
                current_monitor["last_known_pid"] = max(0, int(monitor.get("last_known_pid") or 0))
            except (TypeError, ValueError):
                current_monitor["last_known_pid"] = 0
        profile["monitor"] = current_monitor
    if launchagent:
        current_launchagent = dict(profile.get("launchagent") or {})
        if "label" in launchagent:
            label = str(launchagent.get("label") or DEFAULT_LABEL).strip() or DEFAULT_LABEL
            current_launchagent["label"] = label
            current_launchagent.setdefault("path", str(launch_agent_path(label)))
        if "path" in launchagent:
            current_launchagent["path"] = str(launchagent.get("path") or current_launchagent.get("path") or "")
        if "env_file" in launchagent:
            current_launchagent["env_file"] = str(launchagent.get("env_file") or DEFAULT_ENV_FILE).strip() or DEFAULT_ENV_FILE
        profile["launchagent"] = current_launchagent
    return save_installation_profile(root, profile)


def resolve_storage_profile(root: Path = ROOT) -> dict[str, Any]:
    profile = load_installation_profile(root)
    storage = dict(profile.get("storage") or {})
    raw_path = installation_profile_path(root)
    raw_has_storage = False
    if raw_path.exists():
        try:
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
            raw_has_storage = isinstance(raw_payload, dict) and isinstance(raw_payload.get("storage"), dict)
        except (OSError, json.JSONDecodeError):
            raw_has_storage = False
    try:
        memory_root = Path(str(storage.get("memory_root") or (root / "memory"))).expanduser()
        if not memory_root.is_absolute():
            memory_root = root / memory_root
        resolved_memory_root = memory_root.resolve()
    except OSError:
        resolved_memory_root = (root / "memory").resolve()
    try:
        schema_version = max(1, int(storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION))
    except (TypeError, ValueError):
        schema_version = DEFAULT_STORAGE_SCHEMA_VERSION
    return {
        "memory_root": str(resolved_memory_root),
        "schema_version": schema_version,
        "managed_by_installation": bool(storage.get("managed_by_installation", True)),
        "created_at": str(storage.get("created_at") or ""),
        "attached_at": str(storage.get("attached_at") or ""),
        "legacy_co_located": resolved_memory_root == (root / "memory").resolve() and not raw_has_storage,
    }


def default_storage_profile(
    *,
    schema_version: int = DEFAULT_STORAGE_SCHEMA_VERSION,
    storage_instance_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": max(1, int(schema_version or DEFAULT_STORAGE_SCHEMA_VERSION)),
        "created_at": _utc_timestamp(),
        "last_migrated_at": _utc_timestamp(),
        "storage_instance_id": str(storage_instance_id or ""),
    }


def _blank_storage_profile(
    *,
    schema_version: int = DEFAULT_STORAGE_SCHEMA_VERSION,
    storage_instance_id: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": max(1, int(schema_version or DEFAULT_STORAGE_SCHEMA_VERSION)),
        "created_at": "",
        "last_migrated_at": "",
        "storage_instance_id": str(storage_instance_id or ""),
    }


def load_storage_profile(memory_root: Path = MEMORY_DIR) -> dict[str, Any]:
    path = storage_profile_path(memory_root)
    if not path.exists():
        return _blank_storage_profile()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blank_storage_profile()
    if not isinstance(payload, dict):
        return _blank_storage_profile()
    normalized = _blank_storage_profile(
        schema_version=int(payload.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION),
        storage_instance_id=str(payload.get("storage_instance_id") or ""),
    )
    normalized["created_at"] = str(payload.get("created_at") or normalized["created_at"])
    normalized["last_migrated_at"] = str(payload.get("last_migrated_at") or normalized["last_migrated_at"])
    return normalized


def ensure_storage_profile(
    memory_root: Path,
    *,
    schema_version: int = DEFAULT_STORAGE_SCHEMA_VERSION,
    storage_instance_id: str | None = None,
) -> dict[str, Any]:
    path = storage_profile_path(memory_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        profile = load_storage_profile(memory_root)
        profile["schema_version"] = max(1, int(schema_version or profile.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION))
        profile["storage_instance_id"] = str(storage_instance_id or profile.get("storage_instance_id") or "")
        profile["last_migrated_at"] = _utc_timestamp()
    else:
        profile = default_storage_profile(schema_version=schema_version, storage_instance_id=storage_instance_id)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return profile


def _blank_monitor_runtime_registry() -> dict[str, Any]:
    return {
        "version": MONITOR_RUNTIME_REGISTRY_VERSION,
        "updated_at": "",
        "entries": [],
    }


def _normalize_monitor_runtime_entry(payload: dict[str, Any] | None) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    try:
        configured_port = max(0, min(int(data.get("configured_port") or 0), 65535))
    except (TypeError, ValueError):
        configured_port = 0
    try:
        active_port = max(0, min(int(data.get("active_port") or 0), 65535))
    except (TypeError, ValueError):
        active_port = 0
    try:
        pid = max(0, int(data.get("pid") or 0))
    except (TypeError, ValueError):
        pid = 0
    return {
        "instance_id": str(data.get("instance_id") or "").strip(),
        "installation_root": str(data.get("installation_root") or "").strip(),
        "memory_root": str(data.get("memory_root") or "").strip(),
        "configured_host": str(data.get("configured_host") or "").strip(),
        "configured_port": configured_port,
        "active_host": str(data.get("active_host") or "").strip(),
        "active_port": active_port,
        "pid": pid,
        "status": str(data.get("status") or "").strip() or "unknown",
        "runner": str(data.get("runner") or "").strip(),
        "language": str(data.get("language") or "").strip(),
        "monitor_version": str(data.get("monitor_version") or ""),
        "product_version": str(data.get("product_version") or ""),
        "started_at": str(data.get("started_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "stopped_at": str(data.get("stopped_at") or ""),
        "last_known_url": str(data.get("last_known_url") or ""),
    }


def load_monitor_runtime_registry(home: Path | None = None) -> dict[str, Any]:
    path = monitor_runtime_registry_path(home)
    if not path.exists():
        return _blank_monitor_runtime_registry()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _blank_monitor_runtime_registry()
    if not isinstance(payload, dict):
        return _blank_monitor_runtime_registry()
    entries = payload.get("entries")
    normalized_entries: list[dict[str, Any]] = []
    if isinstance(entries, list):
        normalized_entries = [_normalize_monitor_runtime_entry(item) for item in entries if isinstance(item, dict)]
    return {
        "version": max(1, int(payload.get("version") or MONITOR_RUNTIME_REGISTRY_VERSION)),
        "updated_at": str(payload.get("updated_at") or ""),
        "entries": normalized_entries,
    }


def save_monitor_runtime_registry(payload: dict[str, Any], home: Path | None = None) -> dict[str, Any]:
    registry = load_monitor_runtime_registry(home)
    if isinstance(payload, dict):
        registry["version"] = max(1, int(payload.get("version") or registry.get("version") or MONITOR_RUNTIME_REGISTRY_VERSION))
        registry["updated_at"] = str(payload.get("updated_at") or registry.get("updated_at") or "")
        entries = payload.get("entries")
        if isinstance(entries, list):
            registry["entries"] = [_normalize_monitor_runtime_entry(item) for item in entries if isinstance(item, dict)]
    path = monitor_runtime_registry_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return registry


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def active_monitor_runtime_entries(home: Path | None = None, *, prune: bool = True) -> list[dict[str, Any]]:
    registry = load_monitor_runtime_registry(home)
    changed = False
    active_entries: list[dict[str, Any]] = []
    normalized_entries: list[dict[str, Any]] = []
    for entry in list(registry.get("entries") or []):
        normalized = _normalize_monitor_runtime_entry(entry)
        live = _pid_alive(int(normalized.get("pid") or 0))
        if normalized.get("status") in {"running", "starting"} and not live:
            normalized["status"] = "stale"
            normalized["pid"] = 0
            normalized["stopped_at"] = normalized.get("stopped_at") or _utc_timestamp()
            normalized["updated_at"] = _utc_timestamp()
            changed = True
        if normalized.get("status") in {"running", "starting"} and live:
            active_entries.append(normalized)
        normalized_entries.append(normalized)
    if prune and changed:
        save_monitor_runtime_registry(
            {
                "version": registry.get("version") or MONITOR_RUNTIME_REGISTRY_VERSION,
                "updated_at": _utc_timestamp(),
                "entries": normalized_entries,
            },
            home=home,
        )
    return active_entries


def mark_monitor_runtime_entries_stopped(
    *,
    installation_root: Path | None = None,
    memory_root: Path | None = None,
    exclude_installation_root: Path | None = None,
    reason_status: str = "stopped",
    home: Path | None = None,
) -> list[dict[str, Any]]:
    registry = load_monitor_runtime_registry(home)
    entries = list(registry.get("entries") or [])
    normalized_installation_root = str(installation_root.resolve()) if installation_root is not None else ""
    normalized_memory_root = str(memory_root.resolve()) if memory_root is not None else ""
    normalized_exclude_root = str(exclude_installation_root.resolve()) if exclude_installation_root is not None else ""
    if not normalized_installation_root and not normalized_memory_root:
        return []

    now = _utc_timestamp()
    changed_entries: list[dict[str, Any]] = []
    updated_entries: list[dict[str, Any]] = []
    for entry in entries:
        normalized = _normalize_monitor_runtime_entry(entry)
        entry_installation_root = str(normalized.get("installation_root") or "").strip()
        entry_memory_root = str(normalized.get("memory_root") or "").strip()
        matches_installation = bool(normalized_installation_root) and entry_installation_root == normalized_installation_root
        matches_memory = bool(normalized_memory_root) and entry_memory_root == normalized_memory_root
        excluded = bool(normalized_exclude_root) and entry_installation_root == normalized_exclude_root
        if excluded or not (matches_installation or matches_memory):
            updated_entries.append(normalized)
            continue
        if normalized.get("status") not in {"running", "starting"}:
            updated_entries.append(normalized)
            continue
        normalized["status"] = reason_status
        normalized["active_host"] = ""
        normalized["active_port"] = 0
        normalized["pid"] = 0
        normalized["stopped_at"] = now
        normalized["updated_at"] = now
        updated_entries.append(normalized)
        changed_entries.append(dict(normalized))

    if changed_entries:
        save_monitor_runtime_registry(
            {
                "version": registry.get("version") or MONITOR_RUNTIME_REGISTRY_VERSION,
                "updated_at": now,
                "entries": updated_entries,
            },
            home=home,
        )
    return changed_entries


def record_monitor_runtime(
    *,
    instance_id: str,
    installation_root: Path,
    memory_root: Path,
    configured_host: str,
    configured_port: int,
    active_host: str,
    active_port: int,
    pid: int,
    status: str,
    runner: str,
    language: str,
    monitor_version: str,
    product_version: str,
    started_at: str | None = None,
    stopped_at: str | None = None,
    last_known_url: str = "",
    home: Path | None = None,
) -> dict[str, Any]:
    registry = load_monitor_runtime_registry(home)
    entries = list(registry.get("entries") or [])
    now = _utc_timestamp()
    entry = _normalize_monitor_runtime_entry(
        {
            "instance_id": safe_instance_id(instance_id),
            "installation_root": str(installation_root.resolve()),
            "memory_root": str(memory_root.resolve()),
            "configured_host": configured_host,
            "configured_port": configured_port,
            "active_host": active_host,
            "active_port": active_port,
            "pid": pid,
            "status": status,
            "runner": runner,
            "language": language,
            "monitor_version": monitor_version,
            "product_version": product_version,
            "started_at": started_at or now,
            "updated_at": now,
            "stopped_at": stopped_at or "",
            "last_known_url": last_known_url,
        }
    )
    replaced = False
    for index, existing in enumerate(entries):
        normalized = _normalize_monitor_runtime_entry(existing)
        if normalized.get("instance_id") == entry["instance_id"] or normalized.get("installation_root") == entry["installation_root"]:
            entries[index] = {**normalized, **entry}
            replaced = True
            break
    if not replaced:
        entries.append(entry)
    save_monitor_runtime_registry(
        {
            "version": registry.get("version") or MONITOR_RUNTIME_REGISTRY_VERSION,
            "updated_at": now,
            "entries": entries,
        },
        home=home,
    )
    return entry


def resolve_wrapper_naming(root: Path = ROOT) -> dict[str, str]:
    naming = dict(load_installation_profile(root).get("wrapper_naming") or {})
    return {
        "prefix": str(naming.get("prefix") or ""),
        "suffix": str(naming.get("suffix") or "-ace"),
        "template": str(naming.get("template") or "{prefix}{base}{suffix}") or "{prefix}{base}{suffix}",
    }


def resolve_wrapper_command_name(base_name: str, *, root: Path = ROOT) -> str:
    naming = resolve_wrapper_naming(root)
    normalized_base = base_name
    if naming["prefix"] or naming["suffix"]:
        if base_name.endswith("-memory"):
            normalized_base = base_name[: -len("-memory")]
        elif base_name.endswith("-ace"):
            normalized_base = base_name[: -len("-ace")]
    template = naming["template"]
    try:
        rendered = template.format(prefix=naming["prefix"], base=normalized_base, suffix=naming["suffix"])
    except Exception:
        rendered = f"{naming['prefix']}{normalized_base}{naming['suffix']}"
    return rendered.strip() or normalized_base


def resolve_runner_wrapper_name(client: str, *, root: Path = ROOT) -> str:
    mapping = {
        "codex": "codex-ace",
        "claude": "claude-ace",
        "antigravity": "agy-ace",
        "gemini": "gemini-ace",
        "opencode": "opencode-ace",
    }
    base_name = mapping.get(str(client or "").strip().lower(), "")
    return resolve_wrapper_command_name(base_name, root=root) if base_name else ""


def resolve_monitor_profile(root: Path = ROOT) -> dict[str, Any]:
    monitor = dict(load_installation_profile(root).get("monitor") or {})
    host = str(monitor.get("host") or DEFAULT_MONITOR_HOST).strip() or DEFAULT_MONITOR_HOST
    language = str(monitor.get("language") or "en").strip().lower() or "en"
    try:
        port = int(monitor.get("port") or DEFAULT_MONITOR_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_MONITOR_PORT
    return {
        "host": host,
        "port": max(1, min(port, 65535)),
        "language": language if language in {"en", "de"} else "en",
    }


def instance_metadata_path_for_root(root: Path = ROOT) -> Path:
    profile = load_installation_profile(root)
    instance_id = str(profile.get("instance_id") or root.name)
    return instance_metadata_path(instance_id)


def sync_instance_metadata(
    root: Path = ROOT,
    *,
    doctor_succeeded: bool | None = None,
    check_succeeded: bool | None = None,
) -> dict[str, Any]:
    profile = load_installation_profile(root)
    storage = resolve_storage_profile(root)
    monitor = resolve_monitor_profile(root)
    wrapper = resolve_wrapper_naming(root)
    launchagent = dict(profile.get("launchagent") or {})
    instance_id = str(profile.get("instance_id") or root.name)
    now = _utc_timestamp()
    current = load_instance_metadata(instance_id)
    metadata = default_instance_metadata(
        instance_id=instance_id,
        installation_root=root,
        memory_root=Path(str(storage.get("memory_root") or default_user_storage_root())),
    )
    metadata.update(current)
    metadata.update(
        {
            "version": INSTANCE_METADATA_VERSION,
            "instance_id": safe_instance_id(instance_id),
            "installation_root": str(root.resolve()),
            "memory_root": str(Path(str(storage.get("memory_root") or default_user_storage_root())).expanduser().resolve()),
            "product_version": PRODUCT_VERSION,
            "backend_version": PRODUCT_VERSION,
            "monitor_version": MONITOR_VERSION,
            "storage_schema_version": int(storage.get("schema_version") or DEFAULT_STORAGE_SCHEMA_VERSION),
            "monitor_host": str(monitor.get("host") or DEFAULT_MONITOR_HOST),
            "monitor_port": int(monitor.get("port") or DEFAULT_MONITOR_PORT),
            "language": str(monitor.get("language") or "en"),
            "wrapper_prefix": str(wrapper.get("prefix") or ""),
            "wrapper_suffix": str(wrapper.get("suffix") or ""),
            "launchagent_label": str(launchagent.get("label") or DEFAULT_LABEL),
            "launchagent_path": str(launchagent.get("path") or launch_agent_path(str(launchagent.get("label") or DEFAULT_LABEL))),
            "launchagent_env_file": str(launchagent.get("env_file") or DEFAULT_ENV_FILE),
            "last_updated_at": now,
            "last_updated_by_version": PRODUCT_VERSION,
            "last_seen_at": now,
        }
    )
    metadata.update(_git_checkout_metadata(root))
    if not str(metadata.get("installed_at") or "").strip():
        metadata["installed_at"] = now
        metadata["installed_by_version"] = PRODUCT_VERSION
    if doctor_succeeded:
        metadata["last_successful_doctor_at"] = now
    if check_succeeded:
        metadata["last_successful_check_at"] = now
    saved = save_instance_metadata(instance_id, metadata)
    sync_active_instance(
        instance_id=instance_id,
        installation_root=root,
        memory_root=Path(str(storage.get("memory_root") or default_user_storage_root())).expanduser().resolve(),
    )
    return saved


def monitor_restart_command(
    root: Path = ROOT,
    *,
    runner: str | None = None,
    replace_existing: bool = True,
    no_open: bool = True,
) -> str:
    monitor = resolve_monitor_profile(root)
    workflow_runner = str(load_installation_profile(root).get("workflows", {}).get("monitor_runner") or WORKFLOW_RUNNER_DEFAULTS["monitor_runner"]).strip()
    selected_runner = str(runner or workflow_runner or WORKFLOW_RUNNER_DEFAULTS["monitor_runner"]).strip()
    command = (
        f"{agent_memory_cli_for_root(root)} monitor --runner {selected_runner} "
        f"--host {monitor['host']} --port {monitor['port']} --language {monitor['language']}"
    )
    if replace_existing:
        command += " --replace-existing"
    if no_open:
        command += " --no-open"
    return command
