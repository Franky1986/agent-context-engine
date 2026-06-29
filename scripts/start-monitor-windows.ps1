param(
    [string]$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$MemoryRoot = "",
    [string]$Python = "",
    [string]$Runner = "codex",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8787,
    [ValidateSet("de", "en")]
    [string]$Language = "de",
    [switch]$ReplaceExisting,
    [int]$WaitSeconds = 45
)

$ErrorActionPreference = "Stop"

function Resolve-ExistingPython {
    param([string]$InstallRoot)
    if ($Python) { return $Python }
    if ($env:AGENT_CONTEXT_ENGINE_PYTHON) { return $env:AGENT_CONTEXT_ENGINE_PYTHON }
    if ($env:AGENT_MEMORY_PYTHON) { return $env:AGENT_MEMORY_PYTHON }
    $venvPython = Join-Path $InstallRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return $venvPython }
    return "python"
}

function Stop-ExistingListener {
    param([int]$TargetPort)
    $listener = Get-NetTCPConnection -LocalPort $TargetPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        Write-Host "stopping existing monitor listener pid=$($listener.OwningProcess) port=$TargetPort"
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }
}

function Test-MonitorEndpoint {
    param([string]$Uri)
    try {
        Invoke-WebRequest -Uri $Uri -TimeoutSec 5 -UseBasicParsing | Out-Null
        return $true
    } catch {
        return $false
    }
}

$Root = (Resolve-Path $Root).Path
if (-not $MemoryRoot) {
    if ($env:AGENT_CONTEXT_ENGINE_STORAGE_ROOT) {
        $MemoryRoot = $env:AGENT_CONTEXT_ENGINE_STORAGE_ROOT
    } else {
        $MemoryRoot = Join-Path $env:USERPROFILE ".agent-context-engine\memory"
    }
}
$MemoryRoot = [System.IO.Path]::GetFullPath($MemoryRoot)
$pythonExe = Resolve-ExistingPython -InstallRoot $Root
$script = Join-Path $Root "scripts\agent_context_engine.py"
$logDir = Join-Path $MemoryRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "monitor-windows.out.log"
$stderr = Join-Path $logDir "monitor-windows.err.log"

if ($ReplaceExisting) {
    Stop-ExistingListener -TargetPort $Port
}

$env:AGENT_CONTEXT_ENGINE_ROOT = $Root
$env:AGENT_CONTEXT_ENGINE_STORAGE_ROOT = $MemoryRoot

$arguments = @(
    $script,
    "monitor",
    "--runner", $Runner,
    "--host", $HostName,
    "--port", "$Port",
    "--language", $Language,
    "--no-open"
)
if ($ReplaceExisting) {
    $arguments += "--replace-existing"
}

Write-Host "starting monitor"
Write-Host "root=$Root"
Write-Host "memory_root=$MemoryRoot"
Write-Host "python=$pythonExe"
Write-Host "url=http://${HostName}:$Port/"
Write-Host "logs=$stdout ; $stderr"

$process = Start-Process `
    -FilePath $pythonExe `
    -ArgumentList $arguments `
    -WorkingDirectory $Root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$statusUri = "http://${HostName}:$Port/api/status"
$firewallUri = "http://${HostName}:$Port/api/firewall-state"
$statusOk = $false
$firewallOk = $false

while ((Get-Date) -lt $deadline) {
    $listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        $statusOk = Test-MonitorEndpoint -Uri $statusUri
        $firewallOk = Test-MonitorEndpoint -Uri $firewallUri
        if ($statusOk -and $firewallOk) {
            Write-Host "monitor ready pid=$($listener.OwningProcess) launcher_pid=$($process.Id)"
            Write-Host $statusUri
            exit 0
        }
    }
    if ($process.HasExited) {
        break
    }
    Start-Sleep -Milliseconds 750
}

$finalListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
Write-Host "monitor did not become ready"
Write-Host "launcher_pid=$($process.Id) exited=$($process.HasExited)"
if ($process.HasExited) { Write-Host "exit_code=$($process.ExitCode)" }
if ($finalListener) { Write-Host "listener_pid=$($finalListener.OwningProcess)" } else { Write-Host "listener_pid=" }
Write-Host "status_ok=$statusOk firewall_ok=$firewallOk"
if (Test-Path $stderr) {
    Write-Host "--- stderr tail ---"
    Get-Content $stderr -Tail 80
}
if (Test-Path $stdout) {
    Write-Host "--- stdout tail ---"
    Get-Content $stdout -Tail 40
}
exit 1
