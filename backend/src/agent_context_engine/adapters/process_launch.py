from __future__ import annotations

from dataclasses import dataclass

from ..ports.process_launch import ProcessLaunchPort


@dataclass(frozen=True)
class SubprocessLaunchAdapter(ProcessLaunchPort):
    adapter_name: str = "subprocess"
    support_level: str = "supported"
    evidence: str = "tested"

    def launch_kind(self) -> str:
        return "subprocess"


@dataclass(frozen=True)
class WindowsProcessLaunchAdapter(ProcessLaunchPort):
    adapter_name: str = "windows_process"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"

    def launch_kind(self) -> str:
        return "windows_process"
