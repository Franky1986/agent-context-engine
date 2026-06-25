from __future__ import annotations

from ..application.agent_flow import AgentFlowContract
from ..application.agent_flow import (
    render_agents_quick_path,
    render_claude_entrypoint,
    render_cursor_every_chat_rule,
    render_session_start_hook_entry,
)
from ..ports.rendering import InstructionRendererPort


class MarkdownInstructionRenderer(InstructionRendererPort):
    renderer_name = "markdown"
    support_level = "supported"
    evidence = "tested"

    def render_agents_quick_path(self, contract: AgentFlowContract) -> str:
        return render_agents_quick_path(contract)

    def render_session_start_hook_entry(self, contract: AgentFlowContract) -> str:
        return render_session_start_hook_entry(contract)

    def render_claude_entrypoint(self) -> str:
        return render_claude_entrypoint()

    def render_cursor_every_chat_rule(self) -> str:
        return render_cursor_every_chat_rule()
