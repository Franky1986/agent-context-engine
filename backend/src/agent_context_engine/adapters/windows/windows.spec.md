# Windows Adapter Boundary

## Purpose

This package contains Windows-specific runtime adapters for the experimental
Windows platform path.

## Rules

- Use `.cmd` shims for user-facing command publication by default.
- Python-entrypoint `.cmd` shims must prefer `AGENT_CONTEXT_ENGINE_PYTHON`,
  then `AGENT_MEMORY_PYTHON`, then the installation-local
  `.venv\Scripts\python.exe`, before falling back to PATH Python and finally
  `py -3`.
- Use PowerShell for wrapper and hook runtime behavior.
- Do not rely on POSIX shell semantics.
- Do not require symlink privileges or Developer Mode.
- Add the configured command link directory to the current process `PATH` and,
  during real installs, the Windows user `PATH` when it is missing so published
  `.cmd` shims resolve as commands such as `codex-ace`.
- Keep support level at `experimental` until real Windows runtime evidence
  exists.

## Responsibilities

- `command_publication.py`: `.cmd` shim generation
- `wrapper_rendering.py`: PowerShell wrapper generation
- `hook_rendering.py`: PowerShell hook generation
  - Cursor wrappers must preserve the Cursor allow/deny JSON contract, not just
    fire-and-forget logging
- `scheduler.py`: `schtasks` install/query/delete contract; created tasks run
  `scheduler-run` periodically so summaries, dreams, graph extraction, and
  catch-up work continue without depending on the monitor process. Because
  `schtasks /TR` has a short command-length limit, the task target is a
  generated `memory/local/windows-scheduler-run.cmd` script rather than the
  full scheduler command line.
- `system_scheduler.py`: suspension-time task status/disable/restore for only
  the installation-owned task. Status parses `schtasks /XML` instead of
  localized display text and treats unreadable installed-task state
  conservatively as active so suspension still attempts to disable it.
- `path_quoting.py`: Windows quoting helpers
- `process_launch.py`: process launch metadata
  - Installer monitor autostart on Windows must use a root-specific owned Task
    Scheduler launcher script under the active memory root, not an unowned
    detached Python or command-host process.
  - Startup success requires matching installation/memory identity from
    `/api/status`; task creation and port acceptance are insufficient.
- `workspace_binding.py`: workspace binding metadata
- `system_open.py`: local file open behavior
- `executable_permissions.py`: no-op executable permission strategy

## Runtime Lessons

- PID liveness checks may raise Windows-specific `SystemError` / `WinError 87`
  for stale process IDs. Treat that as non-live evidence, not a monitor status
  failure.
- Commands that need the external runtime storage root must receive
  `AGENT_CONTEXT_ENGINE_STORAGE_ROOT`; otherwise they may fall back to a
  co-located `memory/` path and fail under restricted permissions.
- `/api/status` must use a fast integration summary and avoid slow external
  auth/model subprocess probes, so a delayed `codex`, `claude`, `opencode`, or
  provider command cannot make the dashboard look unavailable.
- Frontend status surfaces must keep `unknown` distinct from `inactive`, notably
  for firewall state during startup or failed status fetches.
