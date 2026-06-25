from __future__ import annotations

from typing import Protocol


class WorkspaceBindingPort(Protocol):
    adapter_name: str
    support_level: str
    evidence: str

    def binding_kind(self) -> str: ...
