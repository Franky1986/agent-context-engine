# Windows Installation Flow

This guide documents the Windows-specific installation contract for Agent
Context Engine. It is intentionally generic and must not include local user
paths, private workspace names, transcripts, or runtime data.

## Goals

The Windows flow should feel like a normal first-run setup:

- discover the installation target and runtime storage before writing files
- install backend and frontend dependencies before starting runtime services
- publish `agent-context-engine`, `ace`, and `*-ace` commands as `.cmd` shims
- make the published command directory available through the user `PATH`
- install the Windows Task Scheduler job for periodic dreaming and catch-up
- start the monitor only after backend, frontend, scheduler, and verification
  checks are clean
- activate hooks only as the final successful installation step

If any prerequisite fails, the install should stop short of monitor startup and
hook activation so the operator can repair the setup without live hook traffic.

## Prerequisites

Windows installations need:

- Python 3.11 or newer, with `python` preferred on `PATH`
- a `node`/`npm` toolchain accepted by the checked-in monitor frontend
  lockfile; `install-discovery` and `check-installation` report the exact
  currently required versions for the active checkout
- the desired runner CLIs, such as `codex` or `claude`, installed and
  authenticated for headless workflows

The generated Windows launchers for Python entrypoints must prefer the active
runtime in this order:

1. `AGENT_CONTEXT_ENGINE_PYTHON`
2. `AGENT_MEMORY_PYTHON`
3. `<installation-root>\.venv\Scripts\python.exe`
4. `python` from `PATH`
5. `py -3` only as the final fallback

This keeps `agent-context-engine`, `ace`, and any global `.cmd` shim aligned
with the backend dependencies installed during runtime bootstrap. PowerShell is
used for hook and wrapper runtime behavior; POSIX shell semantics must not be
required on Windows.

## Install Order

The install command follows this order:

1. Resolve discovery defaults, target root, memory root, wrapper names, and
   monitor port.
2. Copy the package and materialize repo-local scripts, `.cmd` companions, and
   wrapper scripts.
3. Create or refresh global command shims in the configured link directory.
4. Add the link directory to the current process `PATH`; on Windows, also add
   it to the user `PATH` when it is not already present.
5. Bootstrap the Python runtime when requested.
6. Install frontend dependencies and build the monitor frontend.
7. Persist the installation profile, user config, storage profile, and instance
   metadata.
8. Install and load the platform scheduler. On Windows this is a Task Scheduler
   job whose action points to a generated short `windows-scheduler-run.cmd`
   script, avoiding `schtasks /TR` command-length limits.
9. Start the monitor only when the runtime, frontend build, and scheduler
   prerequisites are clean. On Windows, installer monitor autostart uses a
   root-specific Task Scheduler task and passes `AGENT_CONTEXT_ENGINE_ROOT`
   plus `AGENT_CONTEXT_ENGINE_STORAGE_ROOT` through its generated script.
   Detached `python.exe`, `Start-Process`, and command-host launches are not
   installation-owned and are not used for takeover.
10. Activate hook configs, GUI workspace hooks, and global-only integration
    hooks as the final step.
11. Run post-install verification after the final hook activation.

## Wrapper Behavior

Windows command publication uses `.cmd` shims instead of symlinks. For example,
`codex-ace` is published as `codex-ace.cmd`, and normal command resolution can
still find it as `codex-ace` when the link directory is on `PATH`.

Wrapper shims delegate to PowerShell wrapper scripts. The wrapper script:

- sets `AGENT_CONTEXT_ENGINE_ROOT`
- records the wrapper name and backing client
- preserves the original launch directory through `AGENT_MEMORY_LAUNCH_CWD`
- invokes the backing runner command, such as `codex`

The install verification must check the actual `.cmd` path on Windows and the
plain symlink path on POSIX systems.

For Python entrypoints, the `.cmd` shim is part of the runtime contract. It must
not accidentally use a different global Python than the one used to install
backend dependencies into `.venv`.

The installer uses a short per-user Windows Task Scheduler launcher rather than
an unowned detached command-host process. It writes a root-specific
`<memory-root>\local\windows-monitor-start-Monitor-<root>-<hash>.cmd`
with the resolved runtime command and storage-root environment, then runs it
outside the transient agent tool process tree. This keeps fresh Windows installs
agentic even when the agent's own process supervisor cleans up child processes
after a tool call.
The monitor is verified through `/api/status`, not just task creation or port
acceptance.

### Upgrading Older Windows Installs

Installations created before root-specific monitor tasks used the legacy task
name `AgentContextEngine\Monitor-<name>` and the shared launcher
`<memory-root>\local\windows-monitor-start.cmd`. Windows support is
experimental, so upgrades from that format require manual cleanup before
rerunning installation:

1. List scheduled tasks and identify the legacy monitor task with
   `schtasks /Query /FO LIST /V`.
2. Stop and remove only that legacy monitor task:
   `schtasks /End /TN "AgentContextEngine\Monitor-<name>"` followed by
   `schtasks /Delete /TN "AgentContextEngine\Monitor-<name>" /F`.
3. After confirming that no legacy monitor is running, remove or rename the
   old `windows-monitor-start.cmd` and run discovery/install again.

Do not remove the periodic Agent Context Engine scheduler task unless it is the
legacy monitor task being migrated. The new installation creates an owned,
root-specific task and launcher.

For manual recovery or diagnosis on Windows, run the helper from a normal
PowerShell or Command Prompt session:

```powershell
.\scripts\start-monitor-windows.ps1 -ReplaceExisting
```

or:

```cmd
scripts\start-monitor-windows.cmd -ReplaceExisting
```

The helper resolves the installation-local Python runtime, sets
`AGENT_CONTEXT_ENGINE_ROOT` and `AGENT_CONTEXT_ENGINE_STORAGE_ROOT`, writes logs
under `<memory-root>\logs`, waits for the listener, and requires both
`/api/status` and `/api/firewall-state` to answer before reporting success.
This avoids treating delayed Windows startup as either immediately healthy or
immediately failed.

If the runtime is started from a restrictive shell or sandbox where `%USERPROFILE%\.agent-context-engine`
is not writable, startup stays usable:

- `AGENT_CONTEXT_ENGINE_STORAGE_ROOT` is still required.
- The monitor writes runtime user-state under `<AGENT_CONTEXT_ENGINE_STORAGE_ROOT>\.agent-context-engine`
  when home-state writes are blocked.
- Verify with `http://127.0.0.1:8787/api/status` after launch; a running monitor is
  valid even if user-state writes fall back.

## Hooks And Monitor Safety

Hooks are intentionally late-bound. A partial install must not write active
hook configs or enable GUI workspace hooks before dependency installation,
frontend build, scheduler setup, verification, and requested monitor startup
have succeeded.

The monitor is also gated. Starting a frontend without a successful build, or
starting a monitor against an unusable backend, is treated as an incomplete
install. The operator should run `repair-installation --apply` or rerun
`install` after fixing prerequisites.
Both the command-host launch and Task Scheduler fallback must verify
`/api/status` against the selected installation and memory roots. A stable
listener alone is not a successful monitor start, and an incomplete requested
install returns a non-zero exit code.

Windows runtime probes must be defensive:

- PID checks such as `os.kill(pid, 0)` can raise Windows-specific
  `SystemError` / `WinError 87` for stale or inaccessible process IDs. Treat
  those as non-live process evidence instead of failing monitor status.
- User-state writes under `%USERPROFILE%\.agent-context-engine` can be blocked
  by filesystem ownership or sandbox rules. Monitor status and storage
  inspection should return usable payloads with a sync warning instead of
  failing the whole endpoint.
- External runtime storage roots require `AGENT_CONTEXT_ENGINE_STORAGE_ROOT`
  when invoking diagnostics, scheduler, dream, or monitor commands outside the
  installed wrapper context.
- The main monitor status response must not block on external runner
  authentication or model-discovery subprocesses. On Windows those probes can
  add several seconds to `/api/status`, so the dashboard uses a fast integration
  summary and leaves full readiness checks to explicit integration workflows.
- The frontend must render missing or still-loading firewall state as
  `loading`/`unknown`, never as `inactive`; `/api/firewall-state` remains the
  source of truth for actual firewall state.

## Lessons From Native Windows Smoke Runs

The first native Windows repair/install smoke surfaced these practical rules:

- Build-time Node may need to come from the installation-managed toolchain even
  when the system `node` is too old. Keep `PATH` explicit for build and repair
  commands.
- `pip install -e backend` can fail on corporate or local certificate stores
  before any project code runs. Treat SSL trust failures as prerequisite issues,
  not backend failures; use an approved mirror or explicit temporary trust
  override according to local policy.
- Do not infer Dream failure from an empty Dreams tab. Verify
  `dream --pending` and scheduler status against the active storage root; an
  empty queue with `No sessions to dream` means there is currently no pending
  dream work.
- Diagnostics that still say `LaunchAgent` on Windows are compatibility
  wording for the shared CLI surface. The active backend is Windows Task
  Scheduler, and documentation/UI should prefer scheduler-neutral or
  Task-Scheduler-specific wording when possible.

## macOS Impact

The Windows work is isolated behind the platform profile and adapter boundary:

- macOS keeps POSIX shell wrappers and symlink-style command publication.
- macOS keeps the LaunchAgent scheduler backend.
- The compatibility CLI flag names such as `install-launchagent` remain shared,
  but the active scheduler backend decides whether macOS LaunchAgent or Windows
  Task Scheduler is used.
- The final hook/monitor gating applies to all platforms because it protects
  incomplete installs, but the Windows-specific `.cmd`, PowerShell, registry
  `PATH`, and Task Scheduler behavior does not run on macOS.

## Validation Checklist

Use focused checks when changing this flow:

```sh
python -m unittest \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_install_copies_codex_and_claude_hooks \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_install_autostarts_monitor_by_default \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_install_skips_monitor_and_hooks_when_frontend_build_fails
```

On Windows, also verify:

```powershell
codex-ace --version
agent-context-engine hooks-status
agent-context-engine check-installation
agent-context-engine launchagent-status --verbose
```

For frontend changes, run the monitor build from the `frontend` directory:

```powershell
node --version
.\node_modules\.bin\tsc.cmd -b .\tsconfig.json
.\node_modules\.bin\vite.cmd build
```

For a clean runtime after interrupted setup, disable hooks through the user
control channel first, then stop any active scheduler run, clear or recover
stale dream state, and rerun installation or repair before re-enabling hooks.
