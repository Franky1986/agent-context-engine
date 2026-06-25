from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..ports.system_open import SystemOpenPort


class DefaultSystemOpenAdapter(SystemOpenPort):
    def __init__(self, platform_token: str) -> None:
        self._platform_token = str(platform_token)
        self.adapter_name = "system_open"
        self.support_level = "supported"
        self.evidence = "tested" if self._platform_token.startswith(("darwin", "linux", "win")) else "inferred"

    def open_local_path(self, path: Path) -> bool:
        uri = path.as_uri()
        command_candidates: list[list[str]] = []

        if self._platform_token.startswith("darwin"):
            if shutil.which("open") is not None:
                command_candidates.append(["open", str(path)])
        elif self._platform_token.startswith("linux"):
            if shutil.which("xdg-open") is not None:
                command_candidates.append(["xdg-open", uri])
            elif shutil.which("gio") is not None:
                command_candidates.append(["gio", "open", uri])
        elif self._platform_token.startswith("win"):
            command_candidates.append(["cmd", "/c", f'start "" "{uri}"'])

        for command in command_candidates:
            executable = command[0].split(" ")[0]
            if executable and " " in executable:
                executable = "cmd"
            if executable and shutil.which(executable) is None and executable != "cmd":
                continue
            try:
                result = subprocess.run(
                    command,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=3,
                )
                if result.returncode == 0:
                    return True
            except Exception:
                continue
        return False
