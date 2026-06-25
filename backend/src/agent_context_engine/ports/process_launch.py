from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProcessLaunchPort(Protocol):
    adapter_name: str
    support_level: str
    evidence: str

    def launch_kind(self) -> str: ...
