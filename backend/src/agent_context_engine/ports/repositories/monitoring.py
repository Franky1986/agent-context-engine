from __future__ import annotations

from typing import Any, Protocol


class MonitorReadRepository(Protocol):
    def sessions(self, *, limit: int, offset: int = 0, query: str | None = None) -> dict[str, Any]:
        """Read session list data for monitor DTOs."""

    def session_detail(self, session_id: str, *, event_limit: int = 200, event_offset: int = 0) -> dict[str, Any]:
        """Read one session detail for monitor DTOs."""

    def risk_events(self, *, limit: int, status: str | None = None) -> dict[str, Any]:
        """Read risk event list data for monitor DTOs."""

    def risk_event(self, risk_event_id: str, *, include_raw: bool = False) -> dict[str, Any]:
        """Read one risk event detail for monitor DTOs."""
