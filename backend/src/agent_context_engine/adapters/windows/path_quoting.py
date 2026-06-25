from __future__ import annotations

import subprocess
from dataclasses import dataclass


def powershell_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def cmd_quote(value: str) -> str:
    return subprocess.list2cmdline([str(value)])


def render_cmd_argument_list(arguments: list[str] | tuple[str, ...]) -> str:
    return " ".join(cmd_quote(item) for item in arguments)


@dataclass(frozen=True)
class WindowsPathQuotingAdapter:
    adapter_name: str = "windows_powershell"
    support_level: str = "experimental"
    evidence: str = "static_contract_test"

    def quote(self, value: str) -> str:
        return powershell_single_quote(value)
