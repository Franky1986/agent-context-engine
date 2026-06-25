from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..ports.publication import GlobalCommandPublisherPort


@dataclass(frozen=True)
class CmdShimPublisher(GlobalCommandPublisherPort):
    adapter_name: str = "cmd_shim"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"

    def create_symlink(self, link: Path, target: Path, *, force: bool) -> Path:
        raise NotImplementedError("Cmd shim publication is scaffolded only and not active yet.")

    def remove_symlink(self, link: Path) -> Path:
        raise NotImplementedError("Cmd shim publication is scaffolded only and not active yet.")
