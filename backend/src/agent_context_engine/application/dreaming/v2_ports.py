from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class LockHandle(Protocol):
    pass


class LockProvider(Protocol):
    def acquire(self, name: str, *args: str) -> LockHandle:
        ...

    def release(self, token: LockHandle) -> None:
        ...


class TextTools(Protocol):
    def read_text_limited(self, path: Path, limit: int) -> str:
        ...

    def redact_embedded_context_artifacts(self, value: str) -> str:
        ...


class CommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(
        self,
        command: list[str],
        *,
        input: str | None = None,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        ...
