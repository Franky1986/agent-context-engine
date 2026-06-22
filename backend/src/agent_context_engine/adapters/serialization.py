from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


TIME_FIELD_SUFFIXES = ("_at", "_until")


def local_time_text(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    try:
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except (OverflowError, OSError, ValueError):
        return text


def add_local_time_fields(value: Any) -> Any:
    if isinstance(value, dict):
        enriched: dict[str, Any] = {}
        for key, item in value.items():
            enriched[key] = add_local_time_fields(item)
            if isinstance(item, str) and key.endswith(TIME_FIELD_SUFFIXES):
                enriched[f"{key}_local"] = local_time_text(item)
        return enriched
    if isinstance(value, list):
        return [add_local_time_fields(item) for item in value]
    return value
