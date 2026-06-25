from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..system_open import DefaultSystemOpenAdapter
from ...ports.system_open import SystemOpenPort


@dataclass(frozen=True)
class WindowsSystemOpenAdapter(SystemOpenPort):
    adapter_name: str = "windows_system_open"
    support_level: str = "experimental"
    evidence: str = "public_docs"

    def open_local_path(self, path: Path) -> bool:
        return DefaultSystemOpenAdapter("win32").open_local_path(path)
