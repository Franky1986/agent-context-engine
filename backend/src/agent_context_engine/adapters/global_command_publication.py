from __future__ import annotations

from pathlib import Path

from ..application.wrapper_publication import create_command_symlink, remove_command_symlink
from ..ports.publication import GlobalCommandPublisherPort


class SymlinkGlobalCommandPublisher(GlobalCommandPublisherPort):
    adapter_name = "symlink"
    support_level = "supported"
    evidence = "tested"

    def create_symlink(self, link: Path, target: Path, *, force: bool) -> Path:
        return create_command_symlink(link, target, force=force)

    def remove_symlink(self, link: Path) -> Path:
        return remove_command_symlink(link)
