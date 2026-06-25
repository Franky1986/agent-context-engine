from __future__ import annotations

from dataclasses import dataclass

from ..application.hook_rendering.specs import WrapperRenderSpec
from ..ports.wrapper_rendering import WrapperRendererPort


@dataclass(frozen=True)
class _ScaffoldedWrapperRenderer(WrapperRendererPort):
    renderer_name: str
    support_level: str
    evidence: str
    profile_id: str
    notes: str

    def render_wrapper(self, spec: WrapperRenderSpec) -> str:
        return (
            f"# scaffolded wrapper renderer only\n"
            f"# renderer={self.renderer_name}\n"
            f"# profile={self.profile_id}\n"
            f"# support={self.support_level}\n"
            f"# evidence={self.evidence}\n"
            f"# wrapper={spec.wrapper_name}\n"
            f"# backing_client_command={spec.backing_client_command}\n"
            f"# installation_root={spec.installation_root}\n"
            f"# launch_cwd_passthrough={'true' if spec.launch_cwd_passthrough else 'false'}\n"
            f"# spec_version={spec.spec_version}\n"
            f"# notes={self.notes}\n"
        )


@dataclass(frozen=True)
class BashWrapperRenderer(_ScaffoldedWrapperRenderer):
    renderer_name: str = "bash"
    support_level: str = "supported"
    evidence: str = "tested"
    profile_id: str = "macos"
    notes: str = "Current active wrapper renderer family."


@dataclass(frozen=True)
class PowerShellWrapperRenderer(_ScaffoldedWrapperRenderer):
    renderer_name: str = "powershell"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"
    profile_id: str = "windows"
    notes: str = "Future native Windows wrapper renderer."
