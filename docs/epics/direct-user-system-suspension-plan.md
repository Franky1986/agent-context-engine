# Epic / Implementation Plan: Direct-User Full-System Suspension

> Status: Experimental; security-boundary correction and real-runner/Windows
> validation in progress
>
> Scope: Agent Context Engine runtime control plane, hooks, scheduler,
> background-work admission, monitor read-only behavior, wrappers, audit,
> status, tests, and operator documentation.
>
> Instrumented-path invariant: mutating system-control commands are accepted
> only from a current runner-native user-prompt event on the supported hook
> path. Recognizable agent, CLI, monitor, retrieved-context, and forged-hook
> paths are blocked. Current runner protocols do not provide signed user
> presence, so this is not protection against arbitrary same-user code.

## Objective

Add one reversible, auditable control that lets a user pause or resume the
effective Agent Context Engine runtime from chat without uninstalling the
product or deleting memory.

The first release must support these exact direct-user control lines:

```text
system-disable --scope all --reason "<reason>"
system-enable --scope all --reason "<reason>"
system-status
```

`system-disable` must stop admission of new background execution and normal
hook processing. Work that was already running at the disable cutoff may finish
cleanly, but queued or newly planned work must not start.
`system-enable` must restore only the components that were active before the
disable operation. `system-status` must report the effective state and any
partial failures.

An emergency recovery control is also required for structurally invalid or
unreadable system-control state:

```text
system-recover --scope all --reason "<reason>" --confirm "rebuild-disabled-state"
```

Recovery is deliberately conservative: it rebuilds a valid **disabled** state,
keeps the scheduler disabled, preserves the existing hook-control
configuration behind the closed system gate, and never enables normal runtime
work by itself.

## Current State And Gap

| Area | Current control | Gap |
|---|---|---|
| Hook control plane | Direct-user `hooks-disable`, `hooks-enable`, `hooks-status` | Does not unload the scheduler, close background-work admission, or put the monitor/API into read-only suspended mode |
| Scheduler | `agent-context-engine uninstall-launchagent` | Mutating CLI command; not part of a direct-user atomic control |
| Global wrapper links | Per-wrapper `global-wrapper-disable` | Destructive to recovery path, no bulk transaction |
| Project hook configs | Per-project `integration-hooks --action disable` | No bulk operation and unnecessary for a reversible pause |
| Monitor | Process lifecycle and installation-specific restart commands | No read-only suspended mode or shared system status |
| Audit/status | Separate hook, scheduler, monitor, and integration status | No single effective system state or partial-failure record |

The existing pieces can be operated manually, but they do not form a single
security boundary or a fail-safe transaction.

## Product Decisions

1. Suspension is reversible and is not an uninstall.
2. Version 1 supports only `--scope all` for mutating system commands.
3. A reason is mandatory for `system-disable`, `system-enable`, and
   `system-recover`.
4. Missing system-control state means `enabled` only before the installation
   has created its integrity anchor. Once initialized, a missing or hash-
   mismatched state fails closed as `partial`.
5. System suspension is an admission gate orthogonal to the existing global
   and per-runner hook-control state. Entering `disabling`, `disabled`,
   `enabling`, or fail-closed `partial` closes normal hook and background-work
   admission without rewriting `hooks-state.json`. Returning to `enabled`
   opens this gate last, so the exact existing hook-control state becomes
   effective again automatically.
6. A disable operation never automatically rolls hooks back to enabled after a
   later step fails.
7. Enable restores the pre-disable scheduler state. It must not enable a
   scheduler that was already disabled beforehand, and it must not rewrite or
   broaden the preserved global or per-runner hook-control state.
8. Global wrapper links and project-local hook files remain installed.
9. Wrappers remain available as recovery entrypoints while the system is
   suspended.
10. Normal ACE hook work is skipped while suspended, but the minimal direct
    user control path remains active so `system-enable`, `system-status`, and
    fail-closed `system-recover` can still be processed.
11. The monitor remains running during suspension as a read-only status and
    inspection surface. It exposes no system enable/disable/recover mutation,
    does not start LLM/background work, and rejects other mutating monitor/API
    actions while the system gate is closed.
12. Platform scheduler operations use the scheduler/platform adapter boundary,
    not direct `launchctl`, Task Scheduler, or future cron calls from the
    application service.
13. Isolated installations mutate only their own resolved memory root. They
    must not write or mirror system state into the default installation's
    memory or control state.
14. Removing wrapper links, deleting project hook configuration, deleting
    memory, or uninstalling ACE requires a separate future destructive control.
15. Work already running when suspension closes admission is allowed to finish
    cleanly. Queued, leased-but-not-started, newly planned, or newly enqueued
    dreams, graph work, transcript sync, and maintenance must not start until
    the system returns to `enabled`.
16. Existing lifecycle mutations that could invalidate the suspension snapshot
    are rejected while mode is `disabling`, `disabled`, `enabling`, or
    fail-closed `partial`. Read-only status operations remain available.
17. Version 1 treats the current managed-hook layout as its initial baseline.
    It does not add a legacy recovery bridge for missing or broken project hook
    configuration. In-chat recovery is guaranteed from an already activated
    project; other locations must direct the user to such a project and to the
    read-only CLI status command.
18. The security boundary prevents mutation through the monitor/API, public
    CLI, and instrumented agent tool paths. It is not an operating-system
    sandbox against arbitrary code already running with the user's filesystem
    and process privileges.

## Direct-User Command Contract

### Accepted Lines

Disable:

```text
system-disable --scope all --reason "Maintenance"
```

Enable:

```text
system-enable --scope all --reason "Maintenance complete"
```

Status:

```text
system-status
```

Emergency recovery for unreadable or structurally invalid state:

```text
system-recover --scope all --reason "State file recovery" --confirm "rebuild-disabled-state"
```

### Grammar

- The trimmed direct user message must contain exactly one non-empty line.
- The line must start with exactly `system-disable`, `system-enable`,
  `system-status`, or `system-recover`.
- Mutating commands require `--scope all` and a non-empty `--reason` value.
- `system-recover` additionally requires the exact confirmation value
  `--confirm "rebuild-disabled-state"` and is accepted only when status is
  unreadable, structurally invalid, or lacks a safe restoration snapshot.
- Unknown flags, repeated flags, missing values, trailing prose, shell control
  operators, substitutions, redirects, and additional lines are rejected.
- `system-status` accepts no arguments in version 1.
- Parsing should use a constrained argument parser or `shlex.split`; parsed
  values must never be evaluated by a shell.
- The command is not accepted from a Markdown code fence or from text quoted by
  the assistant.
- Natural-language requests such as "please disable ACE" do not mutate state.
  The agent may explain the required exact user control line and must then wait.

### Provenance Rules

The command may be applied only when all of these conditions are true:

- The source event is the current runner-native direct user prompt event.
- The raw user message itself matches the command grammar.
- The command was not reconstructed from the conversation transcript.
- The command did not come from tool input, tool output, MCP output, browser
  output, retrieved memory, startup injection, a handover, or an assistant
  message.
- The active agent is not calling the CLI or application service through a tool.

The parser must inspect only the current normalized direct user payload. It
must not scan the concatenated prompt, transcript, startup context, or session
summary for system-control lines.

Runner adapters must consume a valid system-control prompt where the native
hook protocol supports consumption, return a deterministic control result, and
avoid an unnecessary LLM request. Where a runner cannot suppress submission,
the adapter must redact or replace the command before normal model handling and
inject a deterministic statement that the control was already handled. The
raw control line must not be persisted as ordinary prompt content.

### Risk And Taint Behavior

- `system-disable`, `system-status`, and fail-closed `system-recover` remain
  available in tainted sessions.
- `system-enable` also requires a direct user line and must not be synthesized
  by an agent after a disable operation.
- Direct system controls bypass ordinary tool approval because they are not
  tool calls, but they remain fully audited.
- Any agentic attempt to invoke a mutating system-control CLI, monitor/API
  operation, forged `log-hook` payload, or internal service is blocked by the
  firewall and recorded with a dedicated
  `system_control_mutation_attempt` flag. It may additionally carry the
  existing `agent_self_approval_attempt` flag for compatibility.
- Existing `hooks-disable`, `hooks-enable`, and `hooks-status` controls remain
  supported, but hook mutations are rejected while the system gate is closed
  so they cannot invalidate the suspension snapshot. `hooks-status` remains
  available.

### Security Boundary

Version 1 has no public mutating CLI command and no monitor or HTTP mutation
endpoint for system control. The runner-native handler checks the current
user-prompt event and an inherited hook-path marker before calling private
application mutators. A plain caller-provided `source_kind`, boolean, or
provenance dictionary is insufficient on normal supported paths.

The marker is intentionally described as instrumentation, not a capability:
Python objects and file-descriptor state are reproducible by arbitrary code
running with the same user privileges. PreTool and equivalent firewall paths
hard-block recognizable attempts to call or synthesize
`system-disable`, `system-enable`, `system-recover`, their internal mutators,
or a forged direct-user `log-hook` invocation.

This prevents normal agent and monitor control paths from suspending or
resuming ACE. Recognized shell and file-edit tools also reject writes targeting
the control state, anchor, or audit path. It does not claim to stop arbitrary
same-user code from editing files or controlling processes outside the
instrumented ACE boundary; the broader runtime safety model remains defense in
depth rather than an OS sandbox.

## Effective Suspension Semantics

### Components Included In `--scope all`

| Component | Disable behavior | Enable behavior |
|---|---|---|
| System admission gate | Close normal hook and background-work admission before other side effects | Open admission last, after scheduler restoration and verification |
| Hook control | Leave the existing global and per-runner hook-control document unchanged behind the closed system gate | Do not rewrite hook state; its exact preserved state becomes effective when the system gate opens |
| Scheduler | Unload/disable the installation scheduler | Restore it only if it was loaded/enabled before suspension |
| Monitor | Keep the managed monitor running in read-only/status mode; reject mutation and LLM/background-triggering actions | Return monitor endpoints to their normal enabled behavior when the system gate opens |
| Wrapper behavior | Keep links; warn that ACE is suspended; allow runner launch and minimal control handling | Return to normal wrapper behavior |
| Project hook config | Keep files and hub symlinks unchanged | No rewrite required |
| Background work | Let already-running jobs finish; pending work may remain recorded, but queued, leased-but-not-started, or newly planned dreams, graph extraction, transcript sync, or maintenance must not be claimed or started | Resume only after the system gate opens, through the restored scheduler or explicit post-enable actions |

### Wrapper Recovery Behavior

Wrapper links must not be removed by `system-disable`. Removing them would make
recovery harder and would turn a reversible pause into installation mutation.

While suspended, `codex-ace`, `claude-ace`, `cursor-ace`, `agy-ace`,
`gemini-ace`, and `opencode-ace` must:

1. Resolve the installation-specific system state.
2. Print one concise warning that ACE background and normal hook processing are
   suspended.
3. Avoid activation or repair prompts.
4. Start the underlying runner when applicable so the user can send
   `system-enable` or `system-status` as a direct chat message.
5. Keep only the minimal direct-control hook path active.

Version 1 assumes that this minimal path already exists in the selected
project. When a wrapper detects missing, broken, or untrusted managed hook
configuration while suspended, it must not repair or activate the project and
must not claim that an in-chat recovery command will work there. It should
identify the installation as suspended, point to an already activated project,
and show `agent-context-engine system-status` as the read-only diagnostic path.
The underlying runner may still be launched unmanaged when that is the
wrapper's established behavior.

`cursor-ace` has no underlying chat runner. It should print status and the
recovery instruction without mutating Cursor hooks while suspended.

### Hook Adapter Behavior

The direct control check must run before the ordinary hooks-enabled and
system-enabled short-circuits.

Processing order for a direct user prompt event:

1. Normalize and validate instrumented event provenance.
2. Check for an exact system-control line.
3. Apply or report the system control when matched.
4. Check the orthogonal system admission gate without mutating the preserved
   global or per-runner hook-control document.
5. If suspended, exit successfully without normal capture, retrieval,
   classifier, graph, dream, or memory work.
6. If enabled, continue through the existing hook pipeline.

Non-user hook events skip directly to the suspension check and exit successfully
while suspended.

Every background worker, queue consumer, manual dream/graph entrypoint, monitor
action, and scheduler-launched command must perform the same admission check
immediately before claiming or starting new work. A job already marked running
before the disable cutoff may complete and persist its bounded result. A queued
or merely leased job must release or retain its queue state without starting
when the gate is closed.

## Persistent State

Store installation-specific state at:

```text
<resolved-memory-root>/local/system-control.json
```

Store its installation-specific lock at:

```text
<resolved-memory-root>/status/locks/system-control.lock
```

`<resolved-memory-root>` means the result of the canonical
`memory_root(installation_root)` resolver. This makes the default central path
`~/.agent-context-engine/memory/local/system-control.json`, keeps isolated
installations under their own memory root, and keeps external memory roots
authoritative. Do not derive the path independently from `Path.home()` or the
central hook-hub metadata root, and do not mirror the state or lock between
installations.

Suggested schema:

```json
{
  "schema_version": 1,
  "mode": "disabled",
  "operation_id": "uuid",
  "scope": "all",
  "reason": "Maintenance",
  "actor": "direct_user",
  "disabled_at": "2026-07-13T12:00:00+00:00",
  "updated_at": "2026-07-13T12:00:02+00:00",
  "previous": {
    "hooks": {
      "state_sha256": "sha256-of-preserved-hooks-state",
      "global_enabled": true,
      "disabled_runners": ["claude"]
    },
    "scheduler": {
      "implementation": "launchagent",
      "installed": true,
      "loaded": true
    },
    "monitor": {
      "managed": true,
      "running": true,
      "pid": 12345,
      "port": 8787,
      "suspended_behavior": "read_only"
    }
  },
  "background_drain": {
    "cutoff_at": "2026-07-13T12:00:00+00:00",
    "running_at_cutoff": 1,
    "currently_running": 1,
    "queued_not_started": 4,
    "last_checked_at": "2026-07-13T12:00:02+00:00"
  },
  "steps": [
    {
      "name": "close_admission_gate",
      "status": "completed",
      "detail": "normal hook and background-work admission closed"
    }
  ],
  "last_error": ""
}
```

Valid `mode` values:

- `enabled`
- `disabling`
- `disabled`
- `enabling`
- `partial`

Requirements:

- Use an installation-specific interprocess lock.
- Write state atomically through a same-directory temporary file and rename.
- Preserve the original pre-disable snapshot across repeated disable calls.
- Make repeated disable, enable, and status operations idempotent.
- Record every attempted step, result, timestamp, and error.
- Treat unreadable or structurally invalid state as `partial` and keep normal
  hook and background admission closed until the user performs the explicit
  recovery flow.
- Installation and repair must preserve an existing disabled or partial state.
- Upgrade from a version without this file defaults to enabled without writing
  state until the first status or mutation requires it.
- Keep the existing hook-control document unchanged. Its hash and effective
  summary in `previous.hooks` are audit/drift evidence, not a second mutable
  copy to restore.
- Report background draining separately from the top-level mode. `disabled`
  means new work admission is closed and the scheduler is disabled; it may
  temporarily include already-running jobs that are finishing cleanly.

### Invalid-State Recovery

`system-status` remains read-only when the state file is unreadable, invalid,
or missing a safe scheduler snapshot. It reports fail-closed `partial` and the
exact direct user recovery line.

`system-recover --scope all --reason "<reason>" --confirm
"rebuild-disabled-state"` must:

1. Validate the current event through the same instrumented runner-hook path as
   the normal mutating controls.
2. Preserve the invalid file as a bounded audit artifact without persisting raw
   surrounding prompt content.
3. Close normal hook and background admission.
4. Disable/unload the installation scheduler and allow already-running work to
   drain.
5. Preserve the current hook-control document unchanged behind the closed
   system gate.
6. Write a fresh valid `disabled` state whose previous scheduler state is
   conservatively `disabled`.
7. Leave the monitor running in read-only/status mode.

Recovery never opens admission. A subsequent exact `system-enable` may return
the system to `enabled`, but it leaves the scheduler disabled because its prior
state could not be proven. Scheduler reinstallation or loading is then a
separate explicit operator action after the system is enabled.

## Application Service

Create an application-level orchestration service, for example:

```text
backend/src/agent_context_engine/application/system_control.py
```

Suggested API:

```python
parse_direct_user_system_command(raw_message, *, source_kind, event_name)
system_control_status(*, installation_root)
apply_direct_user_system_command(raw_message, *, event_name, installation_root)
```

The concrete scheduler-mutating functions remain private implementation
details behind the instrumented hook entry. This reduces accidental exposure;
it does not turn Python module privacy or descriptor state into same-user
authentication.

The application service must call Python ports/adapters directly. It must not
spawn `agent-context-engine uninstall-launchagent`, wrapper commands, or shell
scripts as orchestration shortcuts.

Add or extend ports for:

- Hook-control read/hash inspection without mutation.
- Scheduler status, disable/unload, and restore.
- Monitor suspended-mode status and API admission guard.
- Audit persistence.
- System-control state storage and locking.
- Background-work admission and running-work observation.

Keep CLI rendering and runner-specific payload formatting outside the
application service.

## Disable Transaction

Execute these steps in order:

1. Validate the instrumented runner event and parse the direct user command.
2. Acquire the system-control lock.
3. Return the current disabled result when the operation is already complete.
4. Capture the pre-disable hook-control hash and summary, scheduler state, and
   monitor observation.
5. Persist `mode=disabling` before external side effects. This closes normal
   hook and background-work admission immediately without rewriting the
   existing hook-control document.
6. Persist completion of the admission-gate step and the immutable hook-state
   hash used for drift detection.
7. Disable/unload the installation scheduler through the platform adapter.
8. Persist completion or failure of the scheduler step.
9. Record work that was already running at the cutoff and allow it to finish;
    do not claim or start queued or newly planned work.
10. Confirm that the monitor remains reachable in read-only/status mode. A
    monitor availability failure is reported but never triggers process kill
    or replacement during disable.
11. Write `mode=disabled` when admission is closed and the scheduler operation
    completed. Report remaining pre-cutoff work through `background_drain`.
12. Write `mode=partial` when any later step failed.
13. Emit a direct user response containing effective state and failed steps.
14. Release the lock.

Fail-safe rule: once step 5 closes admission, a later failure must not
automatically reopen it.

## Enable Transaction

Execute these steps in order:

1. Validate the instrumented runner event and parse the direct user command.
2. Acquire the system-control lock.
3. Load and validate the original pre-disable snapshot.
4. Persist `mode=enabling` while keeping normal hook and background admission
   closed.
5. Restore the scheduler only when the snapshot says it was previously active.
6. Confirm that the monitor remains reachable in its installation-profile
   configuration and is ready to leave read-only suspended behavior.
7. Confirm restored scheduler status and verify that the preserved hook-state
   hash has not drifted through a conflicting lifecycle mutation.
8. Write `mode=enabled` last. This opens the system admission gate and makes
   the unchanged global and per-runner hook-control state effective again and
   records the completed step results.
9. On failure, best-effort return the scheduler to the suspended state, keep
    admission closed, and write `mode=partial`.
10. Emit a direct user response containing effective state and failed steps.
11. Release the lock.

Do not use current installation defaults as a substitute for a valid previous
snapshot. If no safe restore snapshot exists, keep normal admission closed and
report a direct-user `system-recover` action.

### Interrupted Transaction Recovery

- `system-status` is always read-only. It reports stale `disabling` or
  `enabling` operations and does not continue side effects.
- Repeating `system-disable` through a valid instrumented user-prompt event
  resumes an interrupted disable transaction idempotently from the recorded
  completed steps.
- Repeating `system-enable` resumes an interrupted enable transaction only
  while admission remains closed and the original snapshot is valid.
- If safe continuation cannot be proven, the mutating operation best-effort
  disables the scheduler, keeps admission closed, writes `partial`, and points
  to `system-recover`.
- A user may always send a fresh `system-disable` from `partial` to converge on
  a clean disabled state when the snapshot remains structurally valid.

## Scheduler Boundary

Refactor scheduler lifecycle operations currently owned by CLI commands into a
platform-neutral application port and adapters.

Required operations:

```python
status(installation_root) -> SchedulerState
disable(installation_root, previous_state) -> StepResult
restore(installation_root, previous_state) -> StepResult
```

Platform expectations:

| Platform | Disable | Restore |
|---|---|---|
| macOS | Unload the correct LaunchAgent label; preserve enough configuration for restoration | Load only when previously loaded |
| Windows | Disable/stop the installation-owned Task Scheduler task | Restore its previous enabled/running-ready state |
| Future cron | Remove or comment only the installation-owned entry using a stable ownership marker | Restore only the captured owned entry |
| Unsupported | Return an explicit unsupported/no-op state, not a false success |

The existing `install-launchagent`, `uninstall-launchagent`, and status commands
should delegate to the same adapter methods after refactoring.

## Monitor Suspended-Mode Boundary

The monitor remains running during suspension. Its system status and existing
safe inspection surfaces remain available, including sessions, risks, dream
state, integrations, storage, and audit views where those reads do not start
background work. CLI inspection may perform bounded local metadata, audit, or
SQLite housekeeping; this is not an immutable-filesystem mode. Explicit output
writes such as `install-discovery --plan-json` remain blocked.

While the system gate is closed, the monitor/API must reject:

- integration, hook, scheduler, or installation mutations
- dream reruns, apply operations, review decisions, or queue mutations
- monitor ask, query expansion, or other LLM-triggering requests
- maintenance, rebuild, sync, or graph mutations
- any system disable, enable, or recovery attempt

Use one consistent suspended response, preferably HTTP `423 Locked`, with a
machine-readable `system_suspended` error and the read-only status path. The
monitor UI must disable or hide affected controls and explain that only an
exact control received through the instrumented runner-hook path can change
system state through supported ACE surfaces.

The monitor process must not be stopped, replaced, or restarted as part of the
disable/enable transaction. Existing installation ownership checks remain
relevant to normal monitor lifecycle commands, but they are no longer part of
this epic's suspension transaction.

## CLI And Monitor Surfaces

### CLI

Add a read-only command:

```sh
agent-context-engine system-status [--json]
```

Do not add public mutating `agent-context-engine system-disable`,
`agent-context-engine system-enable`, or
`agent-context-engine system-recover` commands in version 1. Mutation must
stay inside the direct-user hook control boundary.

The status output must include:

- Effective mode.
- Scope and reason.
- Operation ID and timestamps.
- Effective normal-hook state.
- Scheduler implementation and effective state.
- Monitor availability and suspended/read-only behavior.
- Partial or failed steps.
- Exact direct user recovery line when action is required.

### Monitor API And UI

Expose system-control status through the existing status API or a dedicated
read-only endpoint. The monitor must never provide a one-click enable or
disable action.

The monitor status card should show:

- `Enabled`, `Disabling`, `Disabled`, `Enabling`, or `Partial`.
- Disable reason and timestamp.
- Hook, scheduler, and monitor component states.
- Failed steps.
- Copyable direct user chat control lines.
- A clear statement that the commands must be sent by the user in chat and
  must not be executed by an agent as tools.
- Running-at-cutoff work that is still draining and queued work that is being
  held without starting.

The card remains visible while suspended because the monitor continues in
read-only mode. It must not expose one-click, form, URL, or API mutations for
`system-disable`, `system-enable`, or `system-recover`.

## Audit Contract

Every status-changing request must write an audit event even when it is
rejected, already satisfied, or partially fails.

Minimum fields:

- Operation ID.
- Direct user session ID and event sequence when available.
- Command name and scope.
- Reason.
- Provenance decision.
- Previous effective state.
- Step results.
- Final effective state.
- Error category and safe detail.
- Installation instance ID and resolved memory root.

Do not persist raw surrounding prompt or transcript text. Store only the parsed
control and bounded provenance metadata.

## Implementation Work Packages

### WP1: Contract And State Model

- [x] Add the application system-control module and typed state/result models.
- [x] Add atomic JSON state persistence and installation-specific locking.
- [x] Define missing, invalid, partial, and migration semantics.
- [x] Update the nearest application, hook, scheduler, platform, CLI, HTTP, and
      frontend specs before or with behavior changes.

### WP2: Direct User Security Boundary

- [x] Add strict one-line parsing for the three normal system controls and the
      fail-closed emergency recovery control.
- [x] Add normalized direct-user provenance checks for every supported runner.
- [x] Integrate the control before ordinary disabled-state short-circuits.
- [x] Add the process-local instrumented hook-entry marker and document that it
      is not authenticated user presence.
- [x] Block monitor/API, CLI, forged hook, and agent/tool invocation paths and
      record `system_control_mutation_attempt`.
- [x] Ensure taint and firewall state cannot prevent a matching instrumented
      user-prompt event from disabling the system or reading status.
- [x] Consume or safely replace handled control prompts so they do not become
      ordinary LLM instructions.

### WP3: Admission Gate, Hooks, And Wrappers

- [x] Add an orthogonal fail-closed system admission gate without rewriting
      existing global or per-runner hook-control state.
- [x] Snapshot the existing hook-control hash and summary for drift/audit.
- [x] Make normal hook events no-op successfully while suspended.
- [x] Keep direct control handling available while suspended.
- [x] Add suspended wrapper warnings and suppress activation/repair prompts.
- [x] Preserve project configs, hubs, bindings, and wrapper links.
- [x] Document the version-1 recovery requirement for already activated
      projects.

### WP4: Scheduler And Background Drain

- [x] Extract scheduler lifecycle APIs from CLI-specific functions.
- [x] Implement macOS LaunchAgent disable/restore.
- [x] Implement Windows Task Scheduler disable/restore.
- [x] Keep future cron behavior behind the platform adapter contract.
- [x] Add admission checks immediately before queue claim and job start across
      dreams, graphing, sync, and maintenance.
- [x] Let work running at the cutoff finish and surface live drain status.
- [x] Hold queued and newly planned work without starting it.

### WP5: Status, Audit, And UI

- [x] Add read-only `system-status` CLI output and JSON mode.
- [x] Add API status fields or endpoint.
- [x] Add the monitor status card and suspended-mode API guard without system
      mutation buttons or endpoints.
- [x] Persist operation and provenance audit records.
- [x] Surface partial failures and exact recovery guidance.
- [x] Implement conservative `system-recover` handling for invalid state.

### WP6: Documentation And Release Integration

- [x] Update `AGENTS.md` user-only control rules.
- [x] Update `session-start-hook-entry.md` with the new available controls.
- [x] Update `AGENT_BOOTSTRAP.md` and `docs/setup/RUNNER_HARNESSES.md`.
- [x] Update `docs/runbooks/integration-management.md`.
- [x] Update scheduler, hooks, CLI, HTTP, and monitor specs.
- [x] Update English and German user-facing README content together if the
      controls are mentioned there.
- [x] Keep changelog entries under `Unreleased` and the product version at
      `0.2.14.dev0` until validation is complete.
- [x] Run the `/docsupdate` workflow and align its documentation result.
- [x] Commit the aligned result.

## Required Tests

### Parser And Provenance Tests

- Exact valid disable, enable, and status lines.
- Exact valid emergency recovery line, required confirmation, and invalid-state
  precondition.
- Missing reason, empty reason, wrong scope, repeated flags, unknown flags,
  multiline input, trailing prose, shell operators, redirects, substitutions,
  and code fences are rejected.
- Identical text from assistant output, tool input/output, MCP/browser output,
  startup context, retrieval, transcript, and handover does not mutate state.
- A direct user command still works in a tainted session.
- Agentic CLI/tool, monitor/API, internal-service, and forged `log-hook`
  attempts are blocked and audited as `system_control_mutation_attempt`.
- Handled controls are consumed or safely replaced instead of reaching the LLM
  as ordinary instructions.

### State And Transaction Tests

- Missing state defaults to enabled.
- Disable and enable are idempotent.
- Original hook runner states remain byte-for-byte unchanged behind the system
  admission gate.
- Admission closes before scheduler operations.
- Admission opens only after scheduler verification.
- Scheduler failure produces partial state with admission still closed.
- The monitor remains available in read-only mode throughout disable and
  enable.
- Monitor/API mutations and LLM-triggering actions return the suspended error.
- Enable failure returns to or remains in a safe suspended state.
- Concurrent operations serialize through the installation lock.
- Interrupted `disabling` and `enabling` states recover deterministically.
- Invalid state JSON fails closed for normal hook processing.
- Invalid state recovery rebuilds only a disabled state, preserves hook
  configuration, leaves the scheduler disabled, and requires a later explicit
  enable.
- Running-at-cutoff jobs finish; queued, leased-but-not-started, and newly
  planned jobs do not start.

### Isolation Tests

- Default and isolated installations keep separate state files and locks.
- Disabling an isolated installation does not mutate the default user's state,
  active root, hooks state, scheduler, monitor, or audit data.
- Two isolated installations can be disabled and enabled independently.
- External memory roots resolve to the correct runtime-state and lock paths.

### Runner And Wrapper Tests

- Codex, Claude, Gemini, and Antigravity direct user events apply controls.
- Cursor behavior reports recovery guidance without mutating hooks.
- OpenCode behavior preserves its plugin-root constraint.
- Every wrapper suppresses activation/repair while suspended.
- Every applicable wrapper with an already active minimal control hook still
  launches its underlying runner for recovery; other projects show the bounded
  version-1 recovery guidance without activation or repair.
- Non-user hook events exit successfully without persistence or background
  work while suspended.

### Platform Tests

- macOS LaunchAgent installed/loaded state is captured and restored.
- Windows Task Scheduler state is captured and restored.
- Unsupported scheduler implementations return explicit status.
- The monitor remains live and read-only while suspended on both supported
  scheduler platforms.

## Validation Commands

Add focused tests and run them before broader validation:

```sh
python3 -m unittest tests.test_system_control -v
python3 tests/test_agent_context_engine.py
./scripts/check --skip-runtime-db
./scripts/check --skip-runtime-db --include-install-integration-tests
```

Run platform-specific scheduler tests explicitly. Perform real direct-chat
smoke runs for each supported runner rather than relying only on synthetic
payloads.

Minimum manual end-to-end sequence:

1. Confirm enabled state through CLI and monitor.
2. Send the exact direct user disable line from a runner session.
3. Confirm normal hooks no longer persist events.
4. Confirm scheduler work does not start.
5. Confirm work already running at the cutoff can finish and no queued or newly
   planned work starts.
6. Start a wrapper and confirm the suspended warning and recovery path.
7. Send `system-status` as the direct user.
8. Send the exact direct user enable line.
9. Confirm the preserved hook-control state became effective again, only a
   previously active scheduler was restored, and the monitor left suspended
   read-only behavior without being restarted.
10. Repeat with an isolated installation and verify the default installation
    remained unchanged.
11. Confirm the monitor stayed available throughout, exposed read-only status,
    and rejected mutation and LLM-triggering endpoints while suspended.

After implementation affects monitor/API/UI code, restart the local monitor as
required by repository policy. After scheduler or LaunchAgent changes, reload
the LaunchAgent and verify `launchagent-status --verbose` plus `/api/status`.

## Acceptance Criteria

- [ ] A user can suspend the full effective ACE runtime with one exact direct
      chat control line.
- [ ] Supported instrumented agent-tool paths reject the same mutation; real
      runner validation is still required, and arbitrary same-user code is
      outside this boundary.
- [ ] Normal hook and background admission close before scheduler shutdown work
      begins.
- [ ] The scheduler stops launching work for the target installation.
- [ ] Work running at the cutoff finishes cleanly while queued and newly
      planned work remains unstarted.
- [ ] The monitor remains available as a read-only status surface and rejects
      mutation and LLM-triggering operations.
- [ ] Wrapper links and project configuration remain recoverable.
- [ ] Direct status, enable, and fail-closed recovery controls remain available
      while suspended.
- [ ] Enable restores only the previously active scheduler state and exposes
      the unchanged existing hook-control state when admission opens.
- [ ] Any partial failure leaves normal admission closed and is visible in CLI,
      monitor, and audit output.
- [ ] Isolated installations do not mutate global/default installation state.
- [ ] No monitor or unrelated process is stopped by the suspension transaction.
- [x] Specs, runbooks, bootstrap docs, README translations when applicable,
      changelog, and version metadata are aligned.
- [ ] Focused, full, installation-integration, platform, and real-runner smoke
      validation are green.

## Non-Goals

- Deleting session memory, graph data, summaries, logs, or audit records.
- Removing project hook files or central hub symlinks.
- Removing global wrapper links.
- Uninstalling Agent Context Engine.
- Disabling the underlying Codex, Claude, Cursor, Gemini, Antigravity, or
  OpenCode products.
- Stopping the monitor process; suspension keeps it available in read-only
  mode.
- Killing or force-cancelling work that was already running at the suspension
  cutoff.
- Adding partial scopes before the full `all` transaction is reliable.
- Providing an OS-level sandbox against arbitrary same-user code outside ACE's
  instrumented monitor, CLI, hook, and tool boundaries.

## Definition Of Done

The feature is complete only when the instrumented runner-event boundary, the
fail-safe admission gate and transaction, clean background draining, platform
scheduler adapters, monitor read-only mode, conservative invalid-state recovery,
audit/status surfaces, isolation behavior, specs, documentation, and required
validation for every supported runner on macOS and Windows all land in the same
release. A hooks-only implementation or a convenience shell script that chains
existing CLI commands does not satisfy this epic.
