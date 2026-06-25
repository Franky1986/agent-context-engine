from __future__ import annotations

from pathlib import Path
from typing import Protocol


class SystemOpenPort(Protocol):
    def open_local_path(self, path: Path) -> bool: ...
