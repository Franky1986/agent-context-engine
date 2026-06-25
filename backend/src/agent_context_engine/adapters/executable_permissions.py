from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ports.executable_permissions import ExecutablePermissionPort


@dataclass(frozen=True)
class ChmodExecutablePermissionAdapter(ExecutablePermissionPort):
    adapter_name: str = "chmod"
    support_level: str = "supported"
    evidence: str = "tested"

    def ensure_executable(self, path: Path) -> None:
        path.chmod(0o755)


@dataclass(frozen=True)
class WindowsExecutablePermissionAdapter(ExecutablePermissionPort):
    adapter_name: str = "windows_noop"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"

    def ensure_executable(self, path: Path) -> None:
        return None
