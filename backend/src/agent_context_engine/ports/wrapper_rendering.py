from __future__ import annotations

from typing import Protocol

from ..application.hook_rendering.specs import WrapperRenderSpec


class WrapperRendererPort(Protocol):
    renderer_name: str
    support_level: str
    evidence: str

    def render_wrapper(self, spec: WrapperRenderSpec) -> str: ...
