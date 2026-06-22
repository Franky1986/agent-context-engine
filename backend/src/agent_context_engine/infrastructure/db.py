from __future__ import annotations

import sqlite3

from ..adapters.runners.session_metadata import refresh_session_row_metadata
from ..adapters.sqlite.connection import AutoClosingConnection, open_connection
from ..adapters.sqlite.repositories import dreamable_sessions as _dreamable_sessions
from ..adapters.sqlite.repositories import fetch_session as _fetch_session
from ..adapters.sqlite.repositories import resolve_session as _resolve_session
from ..adapters.sqlite.repositories import session_events as _session_events
from ..adapters.sqlite.repositories import summarizable_sessions as _summarizable_sessions
from ..adapters.sqlite.schema import ensure_column as _ensure_column
from ..adapters.sqlite.schema import init_schema as _init_schema
from .config import DB_PATH


def connect(init: bool = True) -> sqlite3.Connection:
    conn = open_connection()
    if init:
        init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    return _init_schema(conn)


def ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    return _ensure_column(conn, table, column, definition)


def fetch_session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row | None:
    return _fetch_session(conn, session_id)


def session_events(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return _session_events(conn, session_id)


def summarizable_sessions(conn: sqlite3.Connection, pending_only: bool) -> list[sqlite3.Row]:
    return _summarizable_sessions(conn, pending_only)


def dreamable_sessions(conn: sqlite3.Connection, pending_only: bool) -> list[sqlite3.Row]:
    return _dreamable_sessions(conn, pending_only)


def resolve_session(conn: sqlite3.Connection, selector: str) -> sqlite3.Row | None:
    row = _resolve_session(conn, selector)
    if row is not None:
        refresh_session_row_metadata(conn, row)
        row = _resolve_session(conn, selector)
    return row
