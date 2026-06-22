from __future__ import annotations

from sqlite3 import Connection
from typing import Any, Protocol


class SQLiteConnectionProvider(Protocol):
    def connect(self) -> Connection:
        """Open a SQLite connection for repository adapters."""


class RowMapper(Protocol):
    def row_dict(self, row: Any) -> dict[str, Any]:
        """Convert adapter-specific rows into plain DTO dictionaries."""
