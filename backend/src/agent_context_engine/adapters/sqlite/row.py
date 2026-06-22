from __future__ import annotations

from typing import Any


def row_dict(row: Any) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}
