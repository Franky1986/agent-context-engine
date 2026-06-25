from __future__ import annotations

from ..application.hook_rendering import (
    render_cursor_project_hook_wrapper,
    render_shell_hook_adapter_script,
)
from ..application.hook_rendering.specs import CursorProjectHookWrapperSpec, ShellHookAdapterSpec
from ..ports.rendering import HookAdapterRendererPort


class BashHookAdapterRenderer(HookAdapterRendererPort):
    renderer_name = "bash"
    support_level = "supported"
    evidence = "tested"

    def render_shell_hook_adapter(self, spec: ShellHookAdapterSpec) -> str:
        return render_shell_hook_adapter_script(spec)

    def render_cursor_project_hook_wrapper(self, spec: CursorProjectHookWrapperSpec) -> str:
        return render_cursor_project_hook_wrapper(spec)


class PowerShellHookAdapterRenderer(HookAdapterRendererPort):
    renderer_name = "powershell"
    support_level = "scaffolded"
    evidence = "public_docs"

    def render_shell_hook_adapter(self, spec: ShellHookAdapterSpec) -> str:
        return (
            f"# scaffolded hook renderer only\n"
            f"# renderer={self.renderer_name}\n"
            f"# support={self.support_level}\n"
            f"# evidence={self.evidence}\n"
            f"# client={spec.client}\n"
            f"# root={spec.agent_context_engine_root}\n"
            f"# script={spec.agent_memory_script}\n"
            f"# spec_version={spec.spec_version}\n"
        )

    def render_cursor_project_hook_wrapper(self, spec: CursorProjectHookWrapperSpec) -> str:
        return (
            f"# scaffolded cursor hook wrapper only\n"
            f"# renderer={self.renderer_name}\n"
            f"# support={self.support_level}\n"
            f"# evidence={self.evidence}\n"
            f"# root={spec.agent_context_engine_root}\n"
            f"# spec_version={spec.spec_version}\n"
        )
