from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...infrastructure.config import SKILL_ROOT


HOOK_RENDER_SPEC_VERSION = "2026-06-25.1"
WRAPPER_RENDER_SPEC_VERSION = "2026-06-25.1"
HUB_RENDER_SPEC_VERSION = "2026-06-25.1"

_HOOK_TEMPLATE_PATHS = {
    "codex": SKILL_ROOT / "templates" / "codex-hooks" / "hook_adapter.sh",
    "claude": SKILL_ROOT / "templates" / "claude-hooks" / "hook_adapter.sh",
    "gemini": SKILL_ROOT / "templates" / "gemini-hooks" / "hook_adapter.sh",
    "antigravity": SKILL_ROOT / "templates" / "antigravity-hooks" / "hook_adapter.sh",
}

_HUB_TEMPLATE_PATHS = {
    "codex": SKILL_ROOT / "templates" / "codex-hooks" / "hook_hub.sh",
    "claude": SKILL_ROOT / "templates" / "claude-hooks" / "hook_hub.sh",
    "antigravity": SKILL_ROOT / "templates" / "antigravity-hooks" / "hook_hub.sh",
    "gemini": SKILL_ROOT / "templates" / "gemini-hooks" / "hook_hub.sh",
}

_CURSOR_TEMPLATE_PATH = SKILL_ROOT / "templates" / "cursor-hooks" / "hook_adapter.sh"
_CURSOR_ROOT_LINE = 'ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"'

_WRAPPER_CLIENT_COMMANDS = {
    "codex-ace": "codex",
    "claude-ace": "claude",
    "cursor-ace": "cursor",
    "agy-ace": "agy",
    "antigravity-ace": "agy",
    "gemini-ace": "gemini",
    "opencode-ace": "opencode",
}

_LEGACY_WRAPPER_NAMES = {
    "agent-memory",
    "agent-context-engine",
    "ace",
}


@dataclass(frozen=True)
class ShellHookAdapterSpec:
    client: str
    template_path: Path
    agent_context_engine_root: Path
    agent_memory_script: str
    support_level: str
    evidence: str
    spec_version: str = HOOK_RENDER_SPEC_VERSION


@dataclass(frozen=True)
class CursorProjectHookWrapperSpec:
    template_path: Path
    root_line: str
    agent_context_engine_root: Path
    support_level: str
    evidence: str
    agent_memory_script: str = ""
    spec_version: str = HOOK_RENDER_SPEC_VERSION


@dataclass(frozen=True)
class WrapperRenderSpec:
    wrapper_name: str
    backing_client_command: str
    installation_root: Path
    launch_cwd_passthrough: bool
    support_level: str
    evidence: str
    spec_version: str = WRAPPER_RENDER_SPEC_VERSION


def build_shell_hook_adapter_spec(
    client: str,
    *,
    agent_context_engine_root: Path,
    agent_memory_script: str,
    support_level: str = "supported",
    evidence: str = "tested",
) -> ShellHookAdapterSpec:
    normalized_client = str(client or "").strip().lower()
    template_path = _HOOK_TEMPLATE_PATHS.get(normalized_client)
    if template_path is None:
        raise ValueError(f"unsupported shell hook renderer client: {client}")
    return ShellHookAdapterSpec(
        client=normalized_client,
        template_path=template_path,
        agent_context_engine_root=agent_context_engine_root.resolve(),
        agent_memory_script=str(agent_memory_script),
        support_level=support_level,
        evidence=evidence,
    )


def build_cursor_project_hook_wrapper_spec(
    *,
    agent_context_engine_root: Path,
    agent_memory_script: str = "",
    support_level: str = "supported",
    evidence: str = "tested",
) -> CursorProjectHookWrapperSpec:
    return CursorProjectHookWrapperSpec(
        template_path=_CURSOR_TEMPLATE_PATH,
        root_line=_CURSOR_ROOT_LINE,
        agent_context_engine_root=agent_context_engine_root.resolve(),
        agent_memory_script=str(agent_memory_script),
        support_level=support_level,
        evidence=evidence,
    )


def build_wrapper_render_spec(
    wrapper_name: str,
    *,
    installation_root: Path,
    launch_cwd_passthrough: bool = True,
    support_level: str = "supported",
    evidence: str = "tested",
) -> WrapperRenderSpec:
    normalized_wrapper_name = str(wrapper_name or "").strip()
    backing_client_command = _WRAPPER_CLIENT_COMMANDS.get(normalized_wrapper_name)
    if not backing_client_command:
        raise ValueError(f"unsupported wrapper render spec: {wrapper_name}")
    return WrapperRenderSpec(
        wrapper_name=normalized_wrapper_name,
        backing_client_command=backing_client_command,
        installation_root=installation_root.resolve(),
        launch_cwd_passthrough=launch_cwd_passthrough,
        support_level=support_level,
        evidence=evidence,
    )


@dataclass(frozen=True)
class CentralHubSpec:
    runner: str
    template_path: Path
    support_level: str = "supported"
    evidence: str = "tested"
    spec_version: str = HUB_RENDER_SPEC_VERSION


def build_central_hub_spec(runner: str, *, support_level: str = "supported", evidence: str = "tested") -> CentralHubSpec:
    normalized_runner = str(runner or "").strip().lower()
    template_path = _HUB_TEMPLATE_PATHS.get(normalized_runner)
    if template_path is None:
        raise ValueError(f"unsupported central hub runner: {runner}")
    return CentralHubSpec(
        runner=normalized_runner,
        template_path=template_path,
        support_level=support_level,
        evidence=evidence,
    )

def supported_wrapper_names() -> set[str]:
    return set(_WRAPPER_CLIENT_COMMANDS.keys())


def legacy_wrapper_names() -> set[str]:
    return set(_LEGACY_WRAPPER_NAMES)
