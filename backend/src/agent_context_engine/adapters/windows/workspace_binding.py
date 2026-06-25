from __future__ import annotations

from dataclasses import dataclass

from ...ports.workspace_binding import WorkspaceBindingPort


@dataclass(frozen=True)
class WindowsWorkspaceBindingAdapter(WorkspaceBindingPort):
    adapter_name: str = "windows_file_binding"
    support_level: str = "experimental"
    evidence: str = "public_docs"

    def binding_kind(self) -> str:
        return self.adapter_name
