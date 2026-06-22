from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RunnerResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, argv: list[str], *, timeout: int | None = None, cwd: str | None = None) -> RunnerResult:
        """Run an external command through an infrastructure adapter."""
