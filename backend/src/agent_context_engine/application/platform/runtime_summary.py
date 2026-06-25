from __future__ import annotations

from .profile import PlatformProfile, platform_capability_matrix
from .runtime_selection import (
    select_command_publisher,
    select_executable_permission_adapter,
    select_hook_adapter_renderer,
    select_instruction_renderer,
    select_path_quoting_adapter,
    select_process_launch_adapter,
    select_system_open_adapter,
    select_workspace_binding_adapter,
    select_wrapper_renderer,
)
from ..scheduler_installation import resolve_platform_scheduler_installer


def runtime_selection_summary(profile: PlatformProfile) -> dict[str, object]:
    instruction_renderer = select_instruction_renderer(profile)
    hook_renderer = select_hook_adapter_renderer(profile)
    wrapper_renderer = select_wrapper_renderer(profile)
    command_publisher = select_command_publisher(profile)
    executable_permission_adapter = select_executable_permission_adapter(profile)
    process_launch_adapter = select_process_launch_adapter(profile)
    path_quoting_adapter = select_path_quoting_adapter(profile)
    system_open_adapter = select_system_open_adapter(profile)
    workspace_binding_adapter = select_workspace_binding_adapter(profile)
    scheduler_installer = resolve_platform_scheduler_installer(profile)
    return {
        "capability_matrix": platform_capability_matrix(profile),
        "instruction_renderer": {
            "name": getattr(instruction_renderer, "renderer_name", ""),
            "support_level": getattr(instruction_renderer, "support_level", ""),
            "evidence": getattr(instruction_renderer, "evidence", ""),
        },
        "hook_renderer": {
            "name": getattr(hook_renderer, "renderer_name", ""),
            "support_level": getattr(hook_renderer, "support_level", ""),
            "evidence": getattr(hook_renderer, "evidence", ""),
        },
        "wrapper_renderer": {
            "name": getattr(wrapper_renderer, "renderer_name", ""),
            "support_level": getattr(wrapper_renderer, "support_level", ""),
            "evidence": getattr(wrapper_renderer, "evidence", ""),
        },
        "command_publisher": {
            "name": type(command_publisher).__name__,
            "adapter_name": getattr(command_publisher, "adapter_name", ""),
            "support_level": getattr(command_publisher, "support_level", ""),
            "evidence": getattr(command_publisher, "evidence", ""),
        },
        "executable_permission_adapter": {
            "name": type(executable_permission_adapter).__name__,
            "adapter_name": getattr(executable_permission_adapter, "adapter_name", ""),
            "support_level": getattr(executable_permission_adapter, "support_level", ""),
            "evidence": getattr(executable_permission_adapter, "evidence", ""),
        },
        "system_open_adapter": {
            "name": type(system_open_adapter).__name__,
            "adapter_name": getattr(system_open_adapter, "adapter_name", ""),
            "support_level": getattr(system_open_adapter, "support_level", ""),
            "evidence": getattr(system_open_adapter, "evidence", ""),
        },
        "process_launch_adapter": {
            "name": type(process_launch_adapter).__name__,
            "adapter_name": getattr(process_launch_adapter, "adapter_name", ""),
            "support_level": getattr(process_launch_adapter, "support_level", ""),
            "evidence": getattr(process_launch_adapter, "evidence", ""),
        },
        "workspace_binding_adapter": {
            "name": type(workspace_binding_adapter).__name__,
            "adapter_name": getattr(workspace_binding_adapter, "adapter_name", ""),
            "support_level": getattr(workspace_binding_adapter, "support_level", ""),
            "evidence": getattr(workspace_binding_adapter, "evidence", ""),
        },
        "path_quoting_adapter": {
            "name": type(path_quoting_adapter).__name__,
            "adapter_name": getattr(path_quoting_adapter, "adapter_name", ""),
            "support_level": getattr(path_quoting_adapter, "support_level", ""),
            "evidence": getattr(path_quoting_adapter, "evidence", ""),
        },
        "scheduler_installer": {
            "name": getattr(scheduler_installer, "adapter_name", ""),
            "support_level": getattr(scheduler_installer, "support_level", ""),
            "evidence": getattr(scheduler_installer, "evidence", ""),
        },
    }
