from __future__ import annotations

import subprocess
from dataclasses import dataclass

from ..infrastructure.config import sh_quote
from ..ports.path_quoting import PathQuotingPort


@dataclass(frozen=True)
class PosixShellPathQuotingAdapter(PathQuotingPort):
    adapter_name: str = "posix_shell"
    support_level: str = "supported"
    evidence: str = "tested"

    def quote(self, value: str) -> str:
        return sh_quote(value)


@dataclass(frozen=True)
class WindowsPathQuotingAdapter(PathQuotingPort):
    adapter_name: str = "windows_cmd"
    support_level: str = "scaffolded"
    evidence: str = "public_docs"

    def quote(self, value: str) -> str:
        return subprocess.list2cmdline([value])
