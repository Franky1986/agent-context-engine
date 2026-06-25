from __future__ import annotations

from pathlib import Path

from ..hook_rendering import legacy_wrapper_names, supported_wrapper_names
from ...infrastructure.config import safe_slug


def normalize_wrapper_base_name(base: str) -> str:
    rendered_base = base
    if base.endswith("-memory"):
        rendered_base = base[: -len("-memory")]
    elif base.endswith("-ace"):
        rendered_base = base[: -len("-ace")]
    return rendered_base


def build_wrapper_command_name(base: str, prefix: str, suffix: str = "") -> str:
    rendered_base = normalize_wrapper_base_name(base) if (prefix or suffix) else base
    return safe_slug(f"{prefix}{rendered_base}{suffix}")


def resolve_wrapper_script_path(
    root: Path,
    wrapper_name: str,
) -> Path:
    supported_wrappers = supported_wrapper_names()
    legacy_wrappers = legacy_wrapper_names()
    if wrapper_name not in supported_wrappers and wrapper_name not in legacy_wrappers:
        raise ValueError(f"unsupported wrapper: {wrapper_name}")
    direct = root / "scripts" / wrapper_name
    if direct.exists():
        return direct
    installed = root / "docs" / "skills" / "agent-context-engine" / "scripts" / wrapper_name
    if installed.exists():
        return installed
    return root / "docs" / "skills" / "agent-memory" / "scripts" / wrapper_name


def create_command_symlink(link: Path, target: Path, *, force: bool) -> Path:
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


def remove_command_symlink(link: Path) -> Path:
    if link.exists() or link.is_symlink():
        link.unlink()
    return link
