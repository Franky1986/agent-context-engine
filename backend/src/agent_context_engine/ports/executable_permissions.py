from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ExecutablePermissionPort(Protocol):
    adapter_name: str
    support_level: str
    evidence: str

    def ensure_executable(self, path: Path) -> None: ...
