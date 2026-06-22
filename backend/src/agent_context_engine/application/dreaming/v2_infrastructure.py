from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
import sqlite3

from ...ports.clock import Clock
from ...ports.filesystem import FileSystem
from ...ports.repositories.sqlite import SQLiteConnectionProvider
from .v2_ports import CommandResult, CommandRunner, LockHandle, LockProvider, TextTools
from dataclasses import dataclass


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        from ...infrastructure.config import utc_now

        return utc_now()


class _DefaultFileSystem(FileSystem):
    def exists(self, path: Path) -> bool:
        return path.exists()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def write_text(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)


class _DefaultTextTools(TextTools):
    def read_text_limited(self, path: Path, limit: int) -> str:
        from ...infrastructure.text import read_text_limited

        return read_text_limited(path, limit)

    def redact_embedded_context_artifacts(self, value: str) -> str:
        from ...infrastructure.text import redact_embedded_context_artifacts

        return redact_embedded_context_artifacts(value)


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str


class _DefaultCommandRunner(CommandRunner):
    def run(
        self,
        command: list[str],
        *,
        input: str | None = None,
        timeout: int | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        proc = subprocess.run(
            command,
            input=input,
            text=True,
            capture_output=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        return _CommandResult(returncode=proc.returncode, stdout=proc.stdout or "", stderr=proc.stderr or "")


class _DefaultLockProvider(LockProvider):
    def acquire(self, name: str, *args: str):
        from ...infrastructure.locks import acquire_lock

        return acquire_lock(name, *args)

    def release(self, token: LockHandle) -> None:
        from ...infrastructure.locks import release_lock

        release_lock(token)


class _DreamV2DbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        from ...adapters.sqlite.request_db import connect

        return connect(*args, **kwargs)


def default_clock() -> Clock:
    return _DefaultClock()


def default_file_system() -> FileSystem:
    return _DefaultFileSystem()


def default_text_tools() -> TextTools:
    return _DefaultTextTools()


def default_command_runner() -> CommandRunner:
    return _DefaultCommandRunner()


def default_lock_provider() -> LockProvider:
    return _DefaultLockProvider()


def default_db_provider() -> SQLiteConnectionProvider:
    return _DreamV2DbProvider()


def json_dumps(value: Any) -> str:
    from ...infrastructure.config import json_dumps

    return json_dumps(value)


def safe_slug(value: str) -> str:
    from ...infrastructure.config import safe_slug

    return safe_slug(value)


def utc_now() -> str:
    from ...infrastructure.config import utc_now

    return utc_now()


def root_path() -> Path:
    from ...infrastructure.config import ROOT

    return ROOT


def dream_dir() -> Path:
    from ...infrastructure.config import DREAM_DIR

    return DREAM_DIR


def memory_dir() -> Path:
    from ...infrastructure.config import MEMORY_DIR

    return MEMORY_DIR
