from __future__ import annotations

import sqlite3

from ...infrastructure.config import DB_PATH


class AutoClosingConnection(sqlite3.Connection):
    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


def open_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=15, factory=AutoClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma foreign_keys=on")
    conn.execute("pragma busy_timeout=15000")
    return conn

