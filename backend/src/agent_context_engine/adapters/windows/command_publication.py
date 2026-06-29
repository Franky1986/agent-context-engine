from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ...ports.publication import GlobalCommandPublisherPort


SHIM_MARKER = ":: agent-context-engine command shim v1"


def _cmd_path(path: Path) -> Path:
    if path.suffix.lower() == ".cmd":
        return path
    return Path(f"{path}.cmd")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _owned_by_agent_context_engine(path: Path) -> bool:
    return SHIM_MARKER in _read_text(path)


def _render_cmd_shim(target: Path) -> str:
    resolved_target = str(target.resolve())
    suffix = target.suffix.lower()
    if suffix == ".py":
        root = target.resolve().parent.parent
        venv_python = root / ".venv" / "Scripts" / "python.exe"
        invocation = (
            f'{SHIM_MARKER}\n'
            "@echo off\n"
            "setlocal\n"
            "set \"PYTHON_BIN=%AGENT_CONTEXT_ENGINE_PYTHON%\"\n"
            "if \"%PYTHON_BIN%\"==\"\" set \"PYTHON_BIN=%AGENT_MEMORY_PYTHON%\"\n"
            f'if "%PYTHON_BIN%"=="" if exist "{venv_python}" set "PYTHON_BIN={venv_python}"\n'
            "if \"%PYTHON_BIN%\"==\"\" set \"PYTHON_BIN=python\"\n"
            f'"%PYTHON_BIN%" "{resolved_target}" %*\n'
            "if not %ERRORLEVEL% EQU 9009 exit /b %ERRORLEVEL%\n"
            f'py -3 "{resolved_target}" %*\n'
            "exit /b %ERRORLEVEL%\n"
        )
    elif suffix == ".ps1":
        invocation = (
            f'{SHIM_MARKER}\n'
            "@echo off\n"
            "setlocal\n"
            f'powershell -NoProfile -ExecutionPolicy Bypass -File "{resolved_target}" %*\n'
            "exit /b %ERRORLEVEL%\n"
        )
    else:
        invocation = (
            f'{SHIM_MARKER}\n'
            "@echo off\n"
            "setlocal\n"
            f'"{resolved_target}" %*\n'
            "exit /b %ERRORLEVEL%\n"
        )
    return invocation


@dataclass(frozen=True)
class WindowsCmdShimPublisher(GlobalCommandPublisherPort):
    adapter_name: str = "cmd_shim"
    support_level: str = "experimental"
    evidence: str = "static_contract_test"

    def create_symlink(self, link: Path, target: Path, *, force: bool) -> Path:
        actual_link = _cmd_path(link)
        actual_link.parent.mkdir(parents=True, exist_ok=True)
        if actual_link.exists():
            owned = _owned_by_agent_context_engine(actual_link)
            if owned and actual_link.read_text(encoding="utf-8", errors="replace") == _render_cmd_shim(target):
                return actual_link
            if not force:
                raise FileExistsError(f"link exists, use --force or a different --command-prefix: {actual_link}")
            if actual_link.is_dir():
                raise FileExistsError(f"cannot replace directory link target: {actual_link}")
            if not owned and not force:
                raise FileExistsError(f"refusing to replace non-owned command shim: {actual_link}")
            actual_link.unlink()
        actual_link.write_text(_render_cmd_shim(target), encoding="utf-8")
        return actual_link

    def remove_symlink(self, link: Path) -> Path:
        actual_link = _cmd_path(link)
        if actual_link.exists():
            if not _owned_by_agent_context_engine(actual_link):
                raise FileExistsError(f"refusing to remove non-owned command shim: {actual_link}")
            actual_link.unlink()
        return actual_link
