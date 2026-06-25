from __future__ import annotations

from dataclasses import dataclass

from ..ports.workspace_binding import WorkspaceBindingPort


@dataclass(frozen=True)
class FileWorkspaceBindingAdapter(WorkspaceBindingPort):
    adapter_name: str = "file_binding"
    support_level: str = "supported"
    evidence: str = "tested"

    def binding_kind(self) -> str:
        return "file_binding"


@dataclass(frozen=True)
class WindowsWorkspaceBindingAdapter(WorkspaceBindingPort):
    adapter_name: str = "windows_file_binding"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"

    def binding_kind(self) -> str:
        return "windows_file_binding"
