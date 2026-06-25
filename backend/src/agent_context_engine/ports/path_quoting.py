from __future__ import annotations

from typing import Protocol


class PathQuotingPort(Protocol):
    adapter_name: str
    support_level: str
    evidence: str

    def quote(self, value: str) -> str: ...
