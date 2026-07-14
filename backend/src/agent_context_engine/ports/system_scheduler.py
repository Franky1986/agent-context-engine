from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class SystemSchedulerPort(Protocol):
    def status(self, installation_root: Path) -> dict[str, Any]: ...

    def disable(self, installation_root: Path, previous_state: dict[str, Any]) -> dict[str, Any]: ...

    def restore(self, installation_root: Path, previous_state: dict[str, Any]) -> dict[str, Any]: ...
