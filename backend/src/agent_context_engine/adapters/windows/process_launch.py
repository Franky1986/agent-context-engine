from __future__ import annotations

from dataclasses import dataclass

from ...ports.process_launch import ProcessLaunchPort


@dataclass(frozen=True)
class WindowsProcessLaunchAdapter(ProcessLaunchPort):
    adapter_name: str = "windows_process"
    support_level: str = "experimental"
    evidence: str = "public_docs"

    def launch_kind(self) -> str:
        return self.adapter_name
