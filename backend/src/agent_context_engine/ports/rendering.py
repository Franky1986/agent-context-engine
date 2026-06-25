from __future__ import annotations

from typing import Protocol

from ..application.agent_flow import AgentFlowContract
from ..application.hook_rendering.specs import CursorProjectHookWrapperSpec, ShellHookAdapterSpec


class InstructionRendererPort(Protocol):
    def render_agents_quick_path(self, contract: AgentFlowContract) -> str: ...

    def render_session_start_hook_entry(self, contract: AgentFlowContract) -> str: ...

    def render_claude_entrypoint(self) -> str: ...

    def render_cursor_every_chat_rule(self) -> str: ...


class HookAdapterRendererPort(Protocol):
    def render_shell_hook_adapter(self, spec: ShellHookAdapterSpec) -> str: ...

    def render_cursor_project_hook_wrapper(self, spec: CursorProjectHookWrapperSpec) -> str: ...
