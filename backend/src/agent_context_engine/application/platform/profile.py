from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum

from ...ports.platform import PlatformDetectorPort, RuntimeCapabilitiesPort


class PlatformFamily(str, Enum):
    MACOS = "macos"
    LINUX = "linux"
    WSL = "wsl"
    WINDOWS = "windows"
    POSIX_GENERIC = "posix_generic"
    UNKNOWN = "unknown"


class SupportLevel(str, Enum):
    UNSUPPORTED = "unsupported"
    SCAFFOLDED = "scaffolded"
    EXPERIMENTAL = "experimental"
    SMOKE_VALIDATED = "smoke_validated"
    OPERATOR_VALIDATED = "operator_validated"
    SUPPORTED = "supported"


class EvidenceLevel(str, Enum):
    TESTED = "tested"
    STATIC_CONTRACT_TEST = "static_contract_test"
    PUBLIC_DOCS = "public_docs"
    INFERRED = "inferred"


class CapabilityStatus(str, Enum):
    SUPPORTED = "supported"
    DEGRADED = "degraded"
    SCAFFOLDED = "scaffolded"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class PlatformCapability:
    name: str
    status: CapabilityStatus
    support_level: SupportLevel
    evidence: EvidenceLevel
    implementation: str = ""
    notes: str = ""


@dataclass(frozen=True)
class PlatformProfile:
    family: PlatformFamily
    profile_id: str
    support_level: SupportLevel
    evidence: EvidenceLevel
    capabilities: tuple[PlatformCapability, ...]
    notes: str = ""

    def capability(self, name: str) -> PlatformCapability | None:
        return next((item for item in self.capabilities if item.name == name), None)


def _legacy_platform_family(value: str) -> PlatformFamily:
    normalized = str(value or "").strip().lower()
    if normalized in {"mac", "macos", "darwin"}:
        return PlatformFamily.MACOS
    if normalized in {"linux"}:
        return PlatformFamily.LINUX
    if normalized in {"wsl"}:
        return PlatformFamily.WSL
    if normalized in {"windows", "win"}:
        return PlatformFamily.WINDOWS
    if normalized in {"posix", "posix_generic"}:
        return PlatformFamily.POSIX_GENERIC
    return PlatformFamily.UNKNOWN


def _capability(
    name: str,
    *,
    status: CapabilityStatus,
    support_level: SupportLevel,
    evidence: EvidenceLevel,
    implementation: str = "",
    notes: str = "",
) -> PlatformCapability:
    return PlatformCapability(
        name=name,
        status=status,
        support_level=support_level,
        evidence=evidence,
        implementation=implementation,
        notes=notes,
    )


def _macos_profile() -> PlatformProfile:
    return PlatformProfile(
        family=PlatformFamily.MACOS,
        profile_id="macos",
        support_level=SupportLevel.SUPPORTED,
        evidence=EvidenceLevel.TESTED,
        capabilities=(
            _capability(
                "scheduler_backend",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="launchagent",
            ),
            _capability(
                "global_command_publication",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="symlink",
            ),
            _capability(
                "wrapper_rendering",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="bash",
            ),
            _capability(
                "hook_adapter_runtime",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="bash",
            ),
            _capability(
                "agent_guidance_rendering",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="markdown",
            ),
            _capability(
                "shell_rendering_family",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="bash",
            ),
            _capability(
                "browser_file_open",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="system_open",
            ),
            _capability(
                "process_launch_behavior",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="subprocess",
            ),
            _capability(
                "workspace_binding_behavior",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="file_binding",
            ),
            _capability(
                "executable_permission_strategy",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="chmod",
            ),
            _capability(
                "symlink_shim_strategy",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="symlink",
            ),
            _capability(
                "path_quoting_strategy",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SUPPORTED,
                evidence=EvidenceLevel.TESTED,
                implementation="posix_shell",
            ),
        ),
        notes="Current production platform profile.",
    )


def _scaffolded_profile(family: PlatformFamily, profile_id: str, notes: str) -> PlatformProfile:
    return PlatformProfile(
        family=family,
        profile_id=profile_id,
        support_level=SupportLevel.SCAFFOLDED,
        evidence=EvidenceLevel.PUBLIC_DOCS,
        capabilities=(
            _capability(
                "scheduler_backend",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Runtime mutation disabled until a concrete adapter is validated.",
            ),
            _capability(
                "global_command_publication",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Publication strategy must be supplied by a platform adapter.",
            ),
            _capability(
                "wrapper_rendering",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Renderer must be selected by shell family.",
            ),
            _capability(
                "hook_adapter_runtime",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Hook runtime must be validated against actual client behavior.",
            ),
            _capability(
                "agent_guidance_rendering",
                status=CapabilityStatus.SUPPORTED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.STATIC_CONTRACT_TEST,
                implementation="markdown",
                notes="Guidance can be rendered, but platform-specific commands remain gated.",
            ),
            _capability(
                "shell_rendering_family",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Shell renderer family selection remains scaffolded.",
            ),
            _capability(
                "browser_file_open",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="System-open behavior must be validated on the real platform.",
            ),
            _capability(
                "process_launch_behavior",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Process launch behavior remains scaffolded until runtime validation exists.",
            ),
            _capability(
                "workspace_binding_behavior",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Workspace binding semantics may differ by platform and remain scaffolded.",
            ),
            _capability(
                "executable_permission_strategy",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Executable permission strategy remains scaffolded.",
            ),
            _capability(
                "symlink_shim_strategy",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Symlink or shim publication strategy remains scaffolded.",
            ),
            _capability(
                "path_quoting_strategy",
                status=CapabilityStatus.SCAFFOLDED,
                support_level=SupportLevel.SCAFFOLDED,
                evidence=EvidenceLevel.PUBLIC_DOCS,
                notes="Platform-specific path and quoting rules remain scaffolded.",
            ),
        ),
        notes=notes,
    )


def _unknown_profile() -> PlatformProfile:
    return PlatformProfile(
        family=PlatformFamily.UNKNOWN,
        profile_id="unknown",
        support_level=SupportLevel.UNSUPPORTED,
        evidence=EvidenceLevel.INFERRED,
        capabilities=(
            _capability(
                "scheduler_backend",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "global_command_publication",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "wrapper_rendering",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "hook_adapter_runtime",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "agent_guidance_rendering",
                status=CapabilityStatus.DEGRADED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
                implementation="markdown",
                notes="Only unsupported/degraded guidance should be rendered.",
            ),
            _capability(
                "shell_rendering_family",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "browser_file_open",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "process_launch_behavior",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "workspace_binding_behavior",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "executable_permission_strategy",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "symlink_shim_strategy",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
            _capability(
                "path_quoting_strategy",
                status=CapabilityStatus.UNSUPPORTED,
                support_level=SupportLevel.UNSUPPORTED,
                evidence=EvidenceLevel.INFERRED,
            ),
        ),
        notes="Unknown host platform.",
    )


def platform_profile_for_family(family: PlatformFamily | str) -> PlatformProfile:
    if isinstance(family, PlatformFamily):
        normalized = family
    else:
        value = str(family)
        normalized = PlatformFamily(value) if value in {item.value for item in PlatformFamily} else PlatformFamily.UNKNOWN
    if normalized == PlatformFamily.MACOS:
        return _macos_profile()
    if normalized == PlatformFamily.LINUX:
        return _scaffolded_profile(PlatformFamily.LINUX, "linux", "Linux profile scaffold; runtime adapters are not enabled yet.")
    if normalized == PlatformFamily.WSL:
        return _scaffolded_profile(PlatformFamily.WSL, "wsl", "WSL profile scaffold; native and Linux boundary behavior must be validated.")
    if normalized == PlatformFamily.WINDOWS:
        return _scaffolded_profile(PlatformFamily.WINDOWS, "windows", "Windows native profile scaffold; runtime adapters are not enabled yet.")
    if normalized == PlatformFamily.POSIX_GENERIC:
        return _scaffolded_profile(PlatformFamily.POSIX_GENERIC, "posix_generic", "Generic POSIX scaffold for future adapter work.")
    return _unknown_profile()


def current_platform_profile(detector: PlatformDetectorPort | None = None) -> PlatformProfile:
    platform_token = (detector or _StdlibPlatformDetector()).detect_platform_token()
    if platform_token == "darwin":
        return platform_profile_for_family(PlatformFamily.MACOS)
    if str(platform_token).startswith("linux"):
        return platform_profile_for_family(PlatformFamily.LINUX)
    if str(platform_token).startswith("win"):
        return platform_profile_for_family(PlatformFamily.WINDOWS)
    return platform_profile_for_family(PlatformFamily.UNKNOWN)


def current_platform_profile_from_capabilities(
    capabilities: RuntimeCapabilitiesPort | None = None,
) -> PlatformProfile:
    runtime_capabilities = capabilities or _StdlibRuntimeCapabilities()
    platform_token = runtime_capabilities.current_platform_token()
    return current_platform_profile(_TokenPlatformDetector(platform_token))


def legacy_platform_profile(value: str) -> PlatformProfile:
    return platform_profile_for_family(_legacy_platform_family(value))


def platform_profile_to_dict(profile: PlatformProfile) -> dict[str, object]:
    return {
        "family": profile.family.value,
        "profile_id": profile.profile_id,
        "support_level": profile.support_level.value,
        "evidence": profile.evidence.value,
        "notes": profile.notes,
        "capabilities": [
            {
                "name": capability.name,
                "status": capability.status.value,
                "support_level": capability.support_level.value,
                "evidence": capability.evidence.value,
                "implementation": capability.implementation,
                "notes": capability.notes,
            }
            for capability in profile.capabilities
        ],
    }


def platform_capability_matrix(profile: PlatformProfile) -> dict[str, dict[str, str]]:
    return {
        capability.name: {
            "status": capability.status.value,
            "support_level": capability.support_level.value,
            "evidence": capability.evidence.value,
            "implementation": capability.implementation,
            "notes": capability.notes,
        }
        for capability in profile.capabilities
    }


def _enum_or_default(enum_type, value: object, default):
    try:
        return enum_type(str(value))
    except Exception:
        return default


def platform_profile_from_payload(payload: dict[str, object] | None) -> PlatformProfile:
    if not isinstance(payload, dict):
        return platform_profile_for_family(PlatformFamily.UNKNOWN)
    family_token = str(payload.get("family") or payload.get("profile_id") or PlatformFamily.UNKNOWN.value)
    base = platform_profile_for_family(family_token)
    raw_capabilities = payload.get("capabilities")
    capabilities: tuple[PlatformCapability, ...]
    if isinstance(raw_capabilities, list):
        items: list[PlatformCapability] = []
        for item in raw_capabilities:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            items.append(
                PlatformCapability(
                    name=name,
                    status=_enum_or_default(CapabilityStatus, item.get("status"), CapabilityStatus.UNSUPPORTED),
                    support_level=_enum_or_default(SupportLevel, item.get("support_level"), base.support_level),
                    evidence=_enum_or_default(EvidenceLevel, item.get("evidence"), base.evidence),
                    implementation=str(item.get("implementation") or ""),
                    notes=str(item.get("notes") or ""),
                )
            )
        capabilities = tuple(items) if items else base.capabilities
    else:
        capabilities = base.capabilities
    return PlatformProfile(
        family=_enum_or_default(PlatformFamily, payload.get("family") or base.family.value, base.family),
        profile_id=str(payload.get("profile_id") or base.profile_id),
        support_level=_enum_or_default(SupportLevel, payload.get("support_level"), base.support_level),
        evidence=_enum_or_default(EvidenceLevel, payload.get("evidence"), base.evidence),
        capabilities=capabilities,
        notes=str(payload.get("notes") or base.notes),
    )


def current_platform_profile_payload() -> dict[str, object]:
    return platform_profile_to_dict(current_platform_profile())


def current_runtime_capabilities_payload(
    capabilities: RuntimeCapabilitiesPort | None = None,
) -> dict[str, object]:
    runtime_capabilities = capabilities or _StdlibRuntimeCapabilities()
    profile = current_platform_profile_from_capabilities(runtime_capabilities)
    return {
        "platform_token": runtime_capabilities.current_platform_token(),
        "profile_id": profile.profile_id,
        "support_level": profile.support_level.value,
        "evidence": profile.evidence.value,
        "capability_matrix": platform_capability_matrix(profile),
    }


def legacy_platform_profile_payload(value: str) -> dict[str, object]:
    return platform_profile_to_dict(legacy_platform_profile(value))


class _TokenPlatformDetector(PlatformDetectorPort):
    def __init__(self, token: str) -> None:
        self._token = str(token)

    def detect_platform_token(self) -> str:
        return self._token


class _StdlibPlatformDetector(PlatformDetectorPort):
    def detect_platform_token(self) -> str:
        return sys.platform


class _StdlibRuntimeCapabilities(RuntimeCapabilitiesPort):
    def __init__(self, detector: PlatformDetectorPort | None = None) -> None:
        self._detector = detector or _StdlibPlatformDetector()

    def current_platform_token(self) -> str:
        return self._detector.detect_platform_token()
