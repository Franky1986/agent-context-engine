from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..platform import CapabilityStatus, PlatformFamily, PlatformProfile
from ...adapters.executable_permissions import ChmodExecutablePermissionAdapter
from ...adapters.platform_detection import SystemPlatformDetector
from ...adapters.global_command_publication import SymlinkGlobalCommandPublisher
from ...adapters.hook_adapter_rendering import BashHookAdapterRenderer
from ...adapters.instruction_rendering import MarkdownInstructionRenderer
from ...adapters.path_quoting import PosixShellPathQuotingAdapter
from ...adapters.process_launch import SubprocessLaunchAdapter
from ...adapters.scheduler_installers import (
    CronSchedulerInstaller,
    MacOSLaunchAgentSchedulerInstaller,
    SystemdUserSchedulerInstaller,
    UnsupportedSchedulerInstaller,
    WslSchedulerInstaller,
)
from ...adapters.system_open import DefaultSystemOpenAdapter
from ...adapters.workspace_binding import FileWorkspaceBindingAdapter
from ...adapters.wrapper_renderers import BashWrapperRenderer
from ...adapters.launchagent import launch_agent_path, launchctl_domain
from ...adapters.windows import (
    PowerShellHookAdapterRenderer,
    PowerShellWrapperRenderer,
    WindowsCmdShimPublisher,
    WindowsExecutablePermissionAdapter,
    WindowsPathQuotingAdapter,
    WindowsProcessLaunchAdapter,
    WindowsSystemOpenAdapter,
    WindowsTaskSchedulerInstaller,
    WindowsWorkspaceBindingAdapter,
)


class _ScaffoldedMarkdownInstructionRenderer(MarkdownInstructionRenderer):
    support_level = "scaffolded"
    evidence = "static_contract_test"


class _UnsupportedMarkdownInstructionRenderer(MarkdownInstructionRenderer):
    support_level = "unsupported"
    evidence = "inferred"


class _ExperimentalMarkdownInstructionRenderer(MarkdownInstructionRenderer):
    support_level = "experimental"
    evidence = "static_contract_test"


class _ScaffoldedBashHookAdapterRenderer:
    renderer_name = "bash"
    support_level = "scaffolded"
    evidence = "public_docs"

    def render_shell_hook_adapter(self, spec) -> str:
        return (
            "# scaffolded hook renderer only\n"
            f"# renderer={self.renderer_name}\n"
            f"# support={self.support_level}\n"
            f"# evidence={self.evidence}\n"
            f"# client={spec.client}\n"
            f"# root={spec.agent_context_engine_root}\n"
            f"# script={spec.agent_memory_script}\n"
            f"# spec_version={spec.spec_version}\n"
        )

    def render_cursor_project_hook_wrapper(self, spec) -> str:
        return (
            "# scaffolded cursor hook wrapper only\n"
            f"# renderer={self.renderer_name}\n"
            f"# support={self.support_level}\n"
            f"# evidence={self.evidence}\n"
            f"# root={spec.agent_context_engine_root}\n"
            f"# spec_version={spec.spec_version}\n"
        )


class _UnsupportedHookAdapterRenderer(_ScaffoldedBashHookAdapterRenderer):
    support_level = "unsupported"
    evidence = "inferred"


@dataclass(frozen=True)
class _ScaffoldedBashWrapperRenderer:
    renderer_name: str = "bash"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"
    profile_id: str = "posix_scaffolded"
    notes: str = "Scaffolded POSIX wrapper renderer; runtime activation remains disabled."

    def render_wrapper(self, spec) -> str:
        return (
            "# scaffolded wrapper renderer only\n"
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
class _UnsupportedWrapperRenderer(_ScaffoldedBashWrapperRenderer):
    support_level: str = "unsupported"
    evidence: str = "inferred"
    profile_id: str = "unknown"
    notes: str = "Unsupported wrapper renderer; runtime activation remains disabled."


@dataclass(frozen=True)
class _DisabledGlobalCommandPublisher:
    adapter_name: str
    support_level: str
    evidence: str
    failure_message: str

    def create_symlink(self, link: Path, target: Path, *, force: bool) -> Path:
        raise NotImplementedError(self.failure_message)

    def remove_symlink(self, link: Path) -> Path:
        raise NotImplementedError(self.failure_message)


@dataclass(frozen=True)
class _MetadataPathQuotingAdapter:
    adapter_name: str
    support_level: str
    evidence: str

    def quote(self, value: str) -> str:
        return PosixShellPathQuotingAdapter().quote(value)


@dataclass(frozen=True)
class _DisabledExecutablePermissionAdapter:
    adapter_name: str
    support_level: str
    evidence: str

    def ensure_executable(self, path: Path) -> None:
        return None


@dataclass(frozen=True)
class _DisabledSystemOpenAdapter:
    adapter_name: str
    support_level: str
    evidence: str

    def open_local_path(self, path: Path) -> bool:
        return False


@dataclass(frozen=True)
class _MetadataProcessLaunchAdapter:
    adapter_name: str
    support_level: str
    evidence: str

    def launch_kind(self) -> str:
        return self.adapter_name


@dataclass(frozen=True)
class _MetadataWorkspaceBindingAdapter:
    adapter_name: str
    support_level: str
    evidence: str

    def binding_kind(self) -> str:
        return self.adapter_name


def _is_scaffolded_profile(profile: PlatformProfile) -> bool:
    return profile.support_level.value == "scaffolded"


def _is_unsupported_profile(profile: PlatformProfile) -> bool:
    return profile.support_level.value == "unsupported"


def select_wrapper_renderer(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _UnsupportedWrapperRenderer()
    if profile.family == PlatformFamily.WINDOWS:
        return PowerShellWrapperRenderer()
    if _is_scaffolded_profile(profile):
        return _ScaffoldedBashWrapperRenderer(profile_id=profile.profile_id)
    return BashWrapperRenderer()


def select_command_publisher(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _DisabledGlobalCommandPublisher(
            adapter_name="unsupported_publication",
            support_level="unsupported",
            evidence="inferred",
            failure_message="Command publication is unsupported for this platform profile.",
        )
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsCmdShimPublisher()
    if _is_scaffolded_profile(profile):
        return _DisabledGlobalCommandPublisher(
            adapter_name="scaffolded_publication",
            support_level="scaffolded",
            evidence="public_docs",
            failure_message="Command publication is scaffolded only and not active for this platform profile.",
        )
    return SymlinkGlobalCommandPublisher()


def select_scheduler_installer(profile: PlatformProfile):
    capability = profile.capability("scheduler_backend")
    if capability is not None and capability.status == CapabilityStatus.SUPPORTED and capability.implementation == "launchagent":
        return MacOSLaunchAgentSchedulerInstaller()
    if profile.family == PlatformFamily.LINUX:
        return SystemdUserSchedulerInstaller(profile_id=profile.profile_id)
    if profile.family == PlatformFamily.WSL:
        return WslSchedulerInstaller(profile_id=profile.profile_id)
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsTaskSchedulerInstaller()
    if profile.family == PlatformFamily.POSIX_GENERIC:
        return CronSchedulerInstaller(profile_id=profile.profile_id)
    return UnsupportedSchedulerInstaller(
        profile_id=profile.profile_id,
        support_level=profile.support_level.value,
        evidence=profile.evidence.value,
    )


def launchagent_plist_path(label: str) -> Path:
    return launch_agent_path(label)


def launchagent_service_domain() -> str:
    return launchctl_domain()


def select_instruction_renderer(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _UnsupportedMarkdownInstructionRenderer()
    if profile.support_level.value == "experimental":
        return _ExperimentalMarkdownInstructionRenderer()
    if _is_scaffolded_profile(profile):
        return _ScaffoldedMarkdownInstructionRenderer()
    return MarkdownInstructionRenderer()


def select_hook_adapter_renderer(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _UnsupportedHookAdapterRenderer()
    if profile.family == PlatformFamily.WINDOWS:
        return PowerShellHookAdapterRenderer()
    if _is_scaffolded_profile(profile):
        return _ScaffoldedBashHookAdapterRenderer()
    return BashHookAdapterRenderer()


def select_system_open_adapter(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _DisabledSystemOpenAdapter(
            adapter_name="unsupported_system_open",
            support_level="unsupported",
            evidence="inferred",
        )
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsSystemOpenAdapter()
    if _is_scaffolded_profile(profile):
        return _DisabledSystemOpenAdapter(
            adapter_name="scaffolded_system_open",
            support_level="scaffolded",
            evidence="public_docs",
        )
    if profile.family in {PlatformFamily.LINUX, PlatformFamily.WSL, PlatformFamily.POSIX_GENERIC}:
        return DefaultSystemOpenAdapter("linux")
    if profile.family == PlatformFamily.MACOS:
        return DefaultSystemOpenAdapter("darwin")
    return DefaultSystemOpenAdapter(SystemPlatformDetector().detect_platform_token())


def select_process_launch_adapter(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _MetadataProcessLaunchAdapter(
            adapter_name="unsupported_process",
            support_level="unsupported",
            evidence="inferred",
        )
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsProcessLaunchAdapter()
    if _is_scaffolded_profile(profile):
        return _MetadataProcessLaunchAdapter(
            adapter_name="scaffolded_process",
            support_level="scaffolded",
            evidence="public_docs",
        )
    return SubprocessLaunchAdapter()


def select_workspace_binding_adapter(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _MetadataWorkspaceBindingAdapter(
            adapter_name="unsupported_binding",
            support_level="unsupported",
            evidence="inferred",
        )
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsWorkspaceBindingAdapter()
    if _is_scaffolded_profile(profile):
        return _MetadataWorkspaceBindingAdapter(
            adapter_name="scaffolded_binding",
            support_level="scaffolded",
            evidence="public_docs",
        )
    return FileWorkspaceBindingAdapter()


def select_executable_permission_adapter(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _DisabledExecutablePermissionAdapter(
            adapter_name="unsupported_noop",
            support_level="unsupported",
            evidence="inferred",
        )
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsExecutablePermissionAdapter()
    if _is_scaffolded_profile(profile):
        return _DisabledExecutablePermissionAdapter(
            adapter_name="scaffolded_noop",
            support_level="scaffolded",
            evidence="public_docs",
        )
    return ChmodExecutablePermissionAdapter()


def select_path_quoting_adapter(profile: PlatformProfile):
    if _is_unsupported_profile(profile):
        return _MetadataPathQuotingAdapter(
            adapter_name="unsupported_quoting",
            support_level="unsupported",
            evidence="inferred",
        )
    if profile.family == PlatformFamily.WINDOWS:
        return WindowsPathQuotingAdapter()
    if _is_scaffolded_profile(profile):
        return _MetadataPathQuotingAdapter(
            adapter_name="posix_shell_scaffolded",
            support_level="scaffolded",
            evidence="public_docs",
        )
    return PosixShellPathQuotingAdapter()
