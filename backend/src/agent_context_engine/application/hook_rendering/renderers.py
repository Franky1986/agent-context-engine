from __future__ import annotations

from pathlib import Path

from .specs import CursorProjectHookWrapperSpec, ShellHookAdapterSpec



def _quote_platform_value(value: str | Path) -> str:
    from ..platform import current_platform_profile
    from ..platform.runtime_selection import select_path_quoting_adapter

    return select_path_quoting_adapter(current_platform_profile()).quote(str(value))


def render_shell_hook_adapter_script(spec: ShellHookAdapterSpec) -> str:
    template = spec.template_path.read_text(encoding="utf-8")
    rendered = template.replace("__AGENT_MEMORY_SCRIPT__", str(spec.agent_memory_script))
    rendered = rendered.replace("__AGENT_CONTEXT_ENGINE_ROOT__", str(spec.agent_context_engine_root.resolve()))
    if "__AGENT_MEMORY_SCRIPT__" in rendered or "__AGENT_CONTEXT_ENGINE_ROOT__" in rendered:
        raise ValueError(f"unresolved hook renderer placeholders for client: {spec.client}")
    return rendered


def render_cursor_project_hook_wrapper(spec: CursorProjectHookWrapperSpec) -> str:
    template = spec.template_path.read_text(encoding="utf-8")
    rendered = template.replace(spec.root_line, f"ROOT={_quote_platform_value(spec.agent_context_engine_root.resolve())}", 1)
    if spec.root_line in rendered:
        raise ValueError("cursor hook wrapper root replacement failed")
    return rendered
