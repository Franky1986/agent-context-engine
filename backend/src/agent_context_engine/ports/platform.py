from __future__ import annotations

from typing import Protocol


class PlatformDetectorPort(Protocol):
    def detect_platform_token(self) -> str:
        """Return the host platform token used for profile selection."""


class RuntimeCapabilitiesPort(Protocol):
    def current_platform_token(self) -> str:
        """Return the currently selected platform token for capability lookup."""
