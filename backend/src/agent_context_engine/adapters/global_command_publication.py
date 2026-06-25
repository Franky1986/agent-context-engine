from __future__ import annotations

from pathlib import Path

from ..ports.publication import GlobalCommandPublisherPort


class SymlinkGlobalCommandPublisher(GlobalCommandPublisherPort):
    adapter_name = "symlink"
    support_level = "supported"
    evidence = "tested"

    def create_symlink(self, link: Path, target: Path, *, force: bool) -> Path:
        if link.exists() or link.is_symlink():
            try:
                existing = link.resolve(strict=False)
            except OSError:
                existing = None
            if existing == target.resolve():
                return link
            if not force:
                raise FileExistsError(f"link exists, use --force or a different --command-prefix: {link}")
            if link.is_dir() and not link.is_symlink():
                raise FileExistsError(f"cannot replace directory link target: {link}")
            link.unlink()
        link.symlink_to(target)
        return link

    def remove_symlink(self, link: Path) -> Path:
        if link.exists() or link.is_symlink():
            link.unlink()
        return link
