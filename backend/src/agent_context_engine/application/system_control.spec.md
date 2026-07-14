# Spec: Direct-User System Suspension

## Purpose

Provide an installation-specific, reversible suspension boundary for normal
hook processing, new background work, scheduler launches, and monitor
mutations without deleting wrappers, project hook configuration, or memory.

## Direct-User Contract

- The accepted chat lines are `system-disable --scope all --reason <reason>`,
  `system-enable --scope all --reason <reason>`, `system-status`, and the
  fail-closed `system-recover --scope all --reason <reason> --confirm
  rebuild-disabled-state` form.
- Mutations are accepted only on the instrumented runner-native user-prompt
  path. Inherited descriptor 3 is a path marker, not authenticated user
  presence or a security capability against arbitrary same-user code.
- A `log-hook` call outside that instrumented path reports a rejection and
  does not write state. This is defense in depth for supported agent/tool
  paths, not an OS security boundary.
- Agent tool attempts that mention the mutating controls or invoke `log-hook`
  are blocked with `system_control_mutation_attempt`. Shell writes and any
  known or unknown non-read tool with structured file targets are blocked when
  they target the control state, anchor, audit path, or their `memory/local`
  parent. This is a best-effort Defense-in-Depth matcher for recognized
  structured file-tool mutations, not a complete filesystem policy or shell/path
  semantic analyzer. It is not a same-user sandbox.
- Agent-facing feedback for a self-control block offers neither one-time
  approval nor firewall exceptions and explicitly forbids retrying help forms
  or alternate mutations. Natural-language deactivation requests distinguish
  hook-only disable from full-system suspension and return the exact copyable
  direct-user form for the selected scope. Wrappers and hook files remain in
  place for status, enable, and recovery.
- `agent-context-engine system-status [--json]` is read-only. There are no
  public mutating system-control CLI verbs or HTTP endpoints.

## State And Admission

- State lives at `<resolved-memory-root>/local/system-control.json`; its
  initialization/hash anchor lives beside it as `system-control.anchor.json`;
  locking lives at `<resolved-memory-root>/status/locks/system-control.lock`.
- Missing state means `enabled` only before an anchor has ever been created.
  Missing or changed state after initialization is fail-closed `partial`.
  The anchor detects accidental or instrumented-path state mutation; a process
  with arbitrary same-user filesystem access can replace both files.
- Valid modes are `enabled`, `disabling`, `disabled`, `enabling`, and
  `partial`. Admission is open only for valid `enabled` state.
- Writes are atomic and status-changing attempts append bounded records to
  `<resolved-memory-root>/logs/system-control-audit.jsonl`.
- Rejected mutating direct-user attempts append only the parsed command name,
  event name, rejection reason, and bounded provenance metadata; raw prompts
  and surrounding transcript text are not retained.
- Disable writes `disabling` before scheduler side effects and writes
  `disabled` only after the scheduler is inactive. A failure becomes
  `partial`; admission remains closed.
- Enable restores only a scheduler proven active in the preserved snapshot,
  verifies that hook-control bytes did not drift, and writes `enabled` last.
- Invalid-state recovery preserves the invalid file, closes admission,
  disables the scheduler, and rebuilds a conservative disabled snapshot. A
  later enable does not restore an unproven scheduler state.

## Runtime Boundaries

- Direct system controls run before hook-state and system-admission checks.
- Normal hook events return success without capture or background work while
  suspended. `hooks-status` remains readable; hook mutations are rejected.
- Scheduler runs and mutating/background CLI commands are rejected before
  work starts. Suspended CLI admission uses an explicit safe-while-suspended
  allowlist per top-level command and nested subcommand; unknown commands
  default to denied. Inspection commands may perform bounded SQLite/audit or
  metadata refreshes, but explicit output-writing options such as
  `install-discovery --plan-json` remain denied.
- Long scheduler runs re-check admission before every step. Hook replay and
  Dream queue workers re-check immediately before each queued item or job is
  claimed, so a disable racing an already-started worker holds unstarted work.
- The monitor remains live. `/api/status` includes `system_control`; monitor
  POST/DELETE requests and LLM-backed retrieval return HTTP 423 with
  `error_code=system_suspended` while admission is closed.
- Wrappers report the installation-specific mode, skip activation/repair, and
  launch the underlying runner where applicable. `cursor-ace` reports status
  and exits.
- Running dream/summary work is not killed. Status reports live running and
  queued counts where the runtime database is available.

## Scheduler Port

- macOS preserves the LaunchAgent plist, unloads the owned label, and reloads
  it only when the snapshot says it was loaded.
- Windows queries, disables, and re-enables only the installation-owned Task
  Scheduler task through `schtasks`; task-enabled state is parsed from XML so
  localized command output cannot bypass suspension.
- Unsupported platforms return an explicit unsupported state; they do not
  report false success for an active scheduler.

## Checks

- `python3 -m unittest tests.test_system_control -v`
- `./scripts/check --skip-runtime-db`
- `./scripts/check --skip-runtime-db --include-install-integration-tests`
