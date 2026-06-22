from __future__ import annotations

from typing import Protocol


class Clock(Protocol):
    def utc_now(self) -> str:
        """Return the current UTC timestamp as an ISO string."""
