from __future__ import annotations

from dataclasses import dataclass

from ...application.hook_rendering.specs import WrapperRenderSpec
from ...ports.wrapper_rendering import WrapperRendererPort
from .path_quoting import powershell_single_quote


def render_cmd_powershell_launcher(script_name: str) -> str:
    return (
        "@echo off\n"
        "setlocal\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0{script_name}" %*\n'
        "exit /b %ERRORLEVEL%\n"
    )


@dataclass(frozen=True)
class PowerShellWrapperRenderer(WrapperRendererPort):
    renderer_name: str = "powershell"
    support_level: str = "experimental"
    evidence: str = "static_contract_test"

    def render_wrapper(self, spec: WrapperRenderSpec) -> str:
        root = powershell_single_quote(str(spec.installation_root.resolve()))
        client = powershell_single_quote(spec.backing_client_command)
        wrapper = powershell_single_quote(spec.wrapper_name)
        launch_passthrough = "$true" if spec.launch_cwd_passthrough else "$false"
        return (
            "# agent-context-engine windows wrapper v1\n"
            f"# renderer={self.renderer_name}\n"
            f"# support={self.support_level}\n"
            f"# evidence={self.evidence}\n"
            f"# wrapper={spec.wrapper_name}\n"
            f"# backing_client_command={spec.backing_client_command}\n"
            f"# installation_root={spec.installation_root.resolve()}\n"
            f"# launch_cwd_passthrough={'true' if spec.launch_cwd_passthrough else 'false'}\n"
            f"# spec_version={spec.spec_version}\n"
            "$ErrorActionPreference = 'Stop'\n"
            f"$ROOT = {root}\n"
            f"$CLIENT = {client}\n"
            f"$WRAPPER = {wrapper}\n"
            f"$LaunchCwdPassthrough = {launch_passthrough}\n"
            "$env:AGENT_CONTEXT_ENGINE_ROOT = $ROOT\n"
            "$env:AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT = $CLIENT\n"
            "$env:AGENT_CONTEXT_ENGINE_WRAPPER_NAME = $WRAPPER\n"
            "if ($LaunchCwdPassthrough -and -not $env:AGENT_MEMORY_LAUNCH_CWD) {\n"
            "  $env:AGENT_MEMORY_LAUNCH_CWD = (Get-Location).Path\n"
            "}\n"
            "& $CLIENT @args\n"
            "if ($LASTEXITCODE -ne $null) {\n"
            "  exit $LASTEXITCODE\n"
            "}\n"
            "exit 0\n"
        )
