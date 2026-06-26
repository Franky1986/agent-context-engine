# Windows Adapter Boundary

## Purpose

This package contains Windows-specific runtime adapters for the experimental
Windows platform path.

## Rules

- Use `.cmd` shims for user-facing command publication by default.
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
- `path_quoting.py`: Windows quoting helpers
- `process_launch.py`: process launch metadata
- `workspace_binding.py`: workspace binding metadata
- `system_open.py`: local file open behavior
- `executable_permissions.py`: no-op executable permission strategy
