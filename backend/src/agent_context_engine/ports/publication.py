from __future__ import annotations

from pathlib import Path
from typing import Protocol


class GlobalCommandPublisherPort(Protocol):
    def create_symlink(self, link: Path, target: Path, *, force: bool) -> Path: ...

    def remove_symlink(self, link: Path) -> Path: ...
