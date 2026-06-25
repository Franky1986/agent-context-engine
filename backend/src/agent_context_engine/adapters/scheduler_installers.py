from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from ..adapters.launchagent import (
    cmd_install_launchagent as adapter_cmd_install_launchagent,
)
from ..adapters.launchagent import (
    cmd_launchagent_status as adapter_cmd_launchagent_status,
)
from ..adapters.launchagent import (
    cmd_uninstall_launchagent as adapter_cmd_uninstall_launchagent,
)
from ..ports.scheduler_installation import SchedulerInstallerPort


@dataclass(frozen=True)
class MacOSLaunchAgentSchedulerInstaller(SchedulerInstallerPort):
    adapter_name: str = "launchagent"
    support_level: str = "supported"
    evidence: str = "tested"

    def install(self, args: argparse.Namespace) -> int:
        return adapter_cmd_install_launchagent(args)

    def uninstall(self, args: argparse.Namespace) -> int:
        return adapter_cmd_uninstall_launchagent(args)

    def status(self, args: argparse.Namespace) -> int:
        return adapter_cmd_launchagent_status(args)


@dataclass(frozen=True)
class _ScaffoldedSchedulerInstaller(SchedulerInstallerPort):
    adapter_name: str
    support_level: str
    evidence: str
    profile_id: str
    install_message: str

    def install(self, args: argparse.Namespace) -> int:
        print(self.install_message, file=sys.stderr)
        return 2

    def uninstall(self, args: argparse.Namespace) -> int:
        print(self.install_message, file=sys.stderr)
        return 2

    def status(self, args: argparse.Namespace) -> int:
        print(
            "warn  scheduler installer is scaffolded on this platform profile: "
            + f"profile={self.profile_id} adapter={self.adapter_name} "
            + f"support={self.support_level} evidence={self.evidence}"
        )
        return 0


@dataclass(frozen=True)
class SystemdUserSchedulerInstaller(_ScaffoldedSchedulerInstaller):
    adapter_name: str = "systemd_user"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"
    profile_id: str = "linux"
    install_message: str = "error: systemd --user scheduler support is scaffolded only and not active yet."


@dataclass(frozen=True)
class CronSchedulerInstaller(_ScaffoldedSchedulerInstaller):
    adapter_name: str = "cron"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"
    profile_id: str = "posix_generic"
    install_message: str = "error: cron scheduler support is scaffolded only and not active yet."


@dataclass(frozen=True)
class WindowsTaskSchedulerInstaller(_ScaffoldedSchedulerInstaller):
    adapter_name: str = "windows_task_scheduler"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"
    profile_id: str = "windows"
    install_message: str = "error: Windows Task Scheduler support is scaffolded only and not active yet."


@dataclass(frozen=True)
class WslSchedulerInstaller(_ScaffoldedSchedulerInstaller):
    adapter_name: str = "wsl_scheduler"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"
    profile_id: str = "wsl"
    install_message: str = "error: WSL scheduler support is scaffolded only and not active yet."


@dataclass(frozen=True)
class UnsupportedSchedulerInstaller(_ScaffoldedSchedulerInstaller):
    adapter_name: str = "unsupported"
    support_level: str = "unsupported"
    evidence: str = "inferred"
    profile_id: str = "unknown"
    install_message: str = "error: no supported scheduler installer exists for this platform profile."
