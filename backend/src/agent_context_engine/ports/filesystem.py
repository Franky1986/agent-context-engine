from __future__ import annotations

from pathlib import Path
from typing import Protocol


class FileSystem(Protocol):
    def exists(self, path: Path) -> bool:
        """Return whether a path exists."""

    def read_text(self, path: Path) -> str:
        """Read a UTF-8 text file."""

    def write_text(self, path: Path, value: str) -> None:
        """Write a UTF-8 text file, creating parents when needed."""

    def read_bytes(self, path: Path) -> bytes:
        """Read a binary file."""

    def write_bytes(self, path: Path, value: bytes) -> None:
        """Write a binary file, creating parents when needed."""
