from __future__ import annotations

import threading
import time
import sqlite3
from typing import Any

from ...infrastructure.db import connect as db_connect


_REQUEST_LOCAL = threading.local()
_LOCK_RETRY_ERRORS = ("database is locked", "database table is locked", "database is busy", "locked")
_LOCK_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)


def _is_transient_sqlite_lock(exc: BaseException) -> bool:
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    message = str(exc).lower()
    return any(marker in message for marker in _LOCK_RETRY_ERRORS)


class RetryingConnection:
    def __init__(self, conn: Any):
        self._conn = conn

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._retry(self._conn.execute, *args, **kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> Any:
        return self._retry(self._conn.executemany, *args, **kwargs)

    def executescript(self, *args: Any, **kwargs: Any) -> Any:
        return self._retry(self._conn.executescript, *args, **kwargs)

    def close(self) -> Any:
        return self._conn.close()

    def __enter__(self) -> Any:
        self._conn.__enter__()
        return self

    def __exit__(self, *args: Any) -> Any:
        return self._conn.__exit__(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def _retry(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        last_exc: sqlite3.OperationalError | None = None
        for index, delay in enumerate((0.0, *_LOCK_RETRY_DELAYS)):
            if delay:
                time.sleep(delay)
            try:
                return func(*args, **kwargs)
            except sqlite3.OperationalError as exc:
                if not _is_transient_sqlite_lock(exc):
                    raise
                last_exc = exc
                if index == len(_LOCK_RETRY_DELAYS):
                    raise
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("unreachable sqlite retry state")


def begin_request() -> None:
    _REQUEST_LOCAL.connections = []


def connect(*args: Any, **kwargs: Any) -> Any:
    kwargs.setdefault("init", False)
    conn = RetryingConnection(db_connect(*args, **kwargs))
    conns = getattr(_REQUEST_LOCAL, "connections", None)
    if conns is not None:
        conns.append(conn)
    return conn


def close_request() -> None:
    for conn in getattr(_REQUEST_LOCAL, "connections", []):
        try:
            conn.close()
        except Exception:
            pass
    _REQUEST_LOCAL.connections = []
