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
- Node.js `>=20.19.0` or `>=22.12.0`
- npm `>=9.5.0`
- the desired runner CLIs, such as `codex` or `claude`, installed and
  authenticated for headless workflows

The generated Windows launchers prefer `python` and fall back to `py -3`.
PowerShell is used for hook and wrapper runtime behavior; POSIX shell semantics
must not be required on Windows.

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
9. Run post-install verification.
10. Start the monitor only when verification and prerequisites are clean.
11. Activate hook configs, GUI workspace hooks, and global-only integration
    hooks as the final step.

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

## Hooks And Monitor Safety

Hooks are intentionally late-bound. A partial install must not write active
hook configs or enable GUI workspace hooks before dependency installation,
frontend build, scheduler setup, verification, and requested monitor startup
have succeeded.

The monitor is also gated. Starting a frontend without a successful build, or
starting a monitor against an unusable backend, is treated as an incomplete
install. The operator should run `repair-installation --apply` or rerun
`install` after fixing prerequisites.

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
