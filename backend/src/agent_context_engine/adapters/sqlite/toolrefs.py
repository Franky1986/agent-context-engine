from __future__ import annotations

import sqlite3
from typing import Any


def tool_response_ref(conn: sqlite3.Connection, session_id: str, seq: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        select tc.tool_call_id, tc.tool_name, tc.tool_use_id, tc.status as call_status,
               out.tool_output_id, out.storage_kind, out.path, out.sha256,
               out.byte_count, out.char_count, out.line_count, out.status as output_status
        from tool_calls tc
        left join tool_outputs out on out.tool_output_id = tc.output_id
        where tc.session_id = ? and tc.seq = ?
        """,
        (session_id, seq),
    ).fetchone()
    return {key: row[key] for key in row.keys()} if row else None
