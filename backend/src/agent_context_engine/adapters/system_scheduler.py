from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from ..application.instance_profile import load_installation_profile, normalize_launchagent_profile
from ..application.platform import current_platform_profile
from ..ports.system_scheduler import SystemSchedulerPort
from .launchagent import launchagent_loaded, launchctl_domain, resolve_launch_agent_plist_path


def _windows_scheduler_available() -> bool:
    return os.name == "nt" and shutil.which("schtasks") is not None


class PlatformSystemScheduler(SystemSchedulerPort):
    def _profile(self, installation_root: Path) -> tuple[str, dict[str, str]]:
        installation = load_installation_profile(installation_root)
        platform_id = str((installation.get("platform_profile") or {}).get("profile_id") or "")
        if not platform_id:
            platform_id = current_platform_profile().profile_id
        return platform_id, normalize_launchagent_profile(installation.get("launchagent"))

    def status(self, installation_root: Path) -> dict[str, Any]:
        platform_id, launchagent = self._profile(installation_root)
        if platform_id == "macos":
            path = resolve_launch_agent_plist_path(
                launchagent["label"], launchagent["path"], root=installation_root
            )
            return {
                "implementation": "launchagent",
                "supported": shutil.which("launchctl") is not None,
                "label": launchagent["label"],
                "path": str(path),
                "installed": path.exists(),
                "loaded": launchagent_loaded(launchagent["label"]),
            }
        if platform_id == "windows":
            supported = _windows_scheduler_available()
            if supported:
                proc = subprocess.run(
                    ["schtasks", "/Query", "/TN", launchagent["label"], "/XML"],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                enabled = False
                enabled_known = False
                detail = (proc.stderr or "").strip()
                if proc.returncode == 0:
                    try:
                        task = ET.fromstring(proc.stdout)
                        enabled_node = task.find(".//{*}Settings/{*}Enabled")
                        enabled = enabled_node is None or str(enabled_node.text or "").strip().lower() == "true"
                        enabled_known = enabled_node is not None
                    except ET.ParseError as exc:
                        # Fail safely: an installed task with unreadable state must still be disabled.
                        enabled = True
                        detail = f"Task XML could not be parsed: {exc}"
                return {
                    "implementation": "windows_task_scheduler",
                    "supported": True,
                    "label": launchagent["label"],
                    "installed": proc.returncode == 0,
                    "loaded": enabled,
                    "enabled_known": enabled_known,
                    "detail": detail,
                }
            return {
                "implementation": "windows_task_scheduler",
                "supported": False,
                "label": launchagent["label"],
                "installed": False,
                "loaded": False,
                "detail": "Windows Task Scheduler lifecycle is not active in this installation profile.",
            }
        return {
            "implementation": platform_id or "unsupported",
            "supported": False,
            "installed": False,
            "loaded": False,
            "detail": "No supported scheduler lifecycle adapter is active on this platform.",
        }

    def disable(self, installation_root: Path, previous_state: dict[str, Any]) -> dict[str, Any]:
        if previous_state.get("implementation") == "windows_task_scheduler":
            if not previous_state.get("loaded"):
                return {"ok": True, "action": "already_inactive", "detail": "task was not enabled"}
            proc = subprocess.run(
                ["schtasks", "/Change", "/TN", str(previous_state.get("label") or ""), "/Disable"],
                text=True,
                capture_output=True,
                check=False,
            )
            return {"ok": proc.returncode == 0, "action": "disabled", "exit_code": proc.returncode, "detail": (proc.stderr or proc.stdout or "").strip()}
        if previous_state.get("implementation") != "launchagent":
            return {
                "ok": not bool(previous_state.get("loaded")),
                "action": "already_inactive" if not previous_state.get("loaded") else "unsupported",
                "detail": str(previous_state.get("detail") or "unsupported scheduler implementation"),
            }
        if not previous_state.get("loaded"):
            return {"ok": True, "action": "already_inactive", "detail": "scheduler was not loaded"}
        if launchagent_loaded(str(previous_state.get("label") or "")) is False:
            return {"ok": True, "action": "already_inactive", "detail": "scheduler is already unloaded"}
        path = str(previous_state.get("path") or "")
        proc = subprocess.run(
            ["launchctl", "bootout", launchctl_domain(), path],
            text=True,
            capture_output=True,
            check=False,
        )
        detail = (proc.stderr or proc.stdout or "").strip()
        already_inactive = any(marker in detail.lower() for marker in ("could not find service", "no such process", "not loaded"))
        return {"ok": proc.returncode == 0 or already_inactive, "action": "unloaded", "exit_code": proc.returncode, "detail": detail}

    def restore(self, installation_root: Path, previous_state: dict[str, Any]) -> dict[str, Any]:
        if not previous_state.get("loaded"):
            return {"ok": True, "action": "preserved_inactive", "detail": "scheduler was inactive before suspension"}
        if previous_state.get("implementation") == "windows_task_scheduler":
            proc = subprocess.run(
                ["schtasks", "/Change", "/TN", str(previous_state.get("label") or ""), "/Enable"],
                text=True,
                capture_output=True,
                check=False,
            )
            return {"ok": proc.returncode == 0, "action": "restored", "exit_code": proc.returncode, "detail": (proc.stderr or proc.stdout or "").strip()}
        if previous_state.get("implementation") != "launchagent":
            return {"ok": False, "action": "unsupported", "detail": "scheduler restore is unsupported"}
        if launchagent_loaded(str(previous_state.get("label") or "")) is True:
            return {"ok": True, "action": "already_restored", "detail": "scheduler is already loaded"}
        path = str(previous_state.get("path") or "")
        label = str(previous_state.get("label") or "")
        proc = subprocess.run(
            ["launchctl", "bootstrap", launchctl_domain(), path],
            text=True,
            capture_output=True,
            check=False,
        )
        detail = (proc.stderr or proc.stdout or "").strip()
        if proc.returncode == 0 and label:
            subprocess.run(
                ["launchctl", "enable", f"{launchctl_domain()}/{label}"],
                text=True,
                capture_output=True,
                check=False,
            )
        return {"ok": proc.returncode == 0, "action": "restored", "exit_code": proc.returncode, "detail": detail}
