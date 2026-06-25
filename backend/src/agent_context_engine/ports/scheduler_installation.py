from __future__ import annotations

import argparse
from typing import Protocol


class SchedulerInstallerPort(Protocol):
    adapter_name: str
    support_level: str
    evidence: str

    def install(self, args: argparse.Namespace) -> int: ...

    def uninstall(self, args: argparse.Namespace) -> int: ...

    def status(self, args: argparse.Namespace) -> int: ...
