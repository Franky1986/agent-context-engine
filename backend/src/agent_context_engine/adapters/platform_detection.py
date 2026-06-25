from __future__ import annotations

import sys

from ..ports.platform import PlatformDetectorPort, RuntimeCapabilitiesPort


class SystemPlatformDetector(PlatformDetectorPort):
    def detect_platform_token(self) -> str:
        return sys.platform


class SystemRuntimeCapabilities(RuntimeCapabilitiesPort):
    def __init__(self, detector: PlatformDetectorPort | None = None) -> None:
        self._detector = detector or SystemPlatformDetector()

    def current_platform_token(self) -> str:
        return self._detector.detect_platform_token()
