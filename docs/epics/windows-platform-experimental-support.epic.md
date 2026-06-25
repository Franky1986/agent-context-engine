# Epic: Windows Platform Experimental Support

## Date

2026-06-25

## Status

Planned

## Objective

Add a Windows platform layer to Agent Context Engine without weakening the
existing macOS support path.

The first target is **Windows experimental support**, not full production
support. The implementation should make Windows behavior explicit through the
existing platform profile, runtime-selection, port, and adapter boundaries.
Windows support must not be marked `supported` until real Windows CI and runtime
smoke evidence exist.

## Executive Summary For Agent Developers

The platform refactor already created the right shape:

- platform profiles describe support level and capability status,
- runtime selection chooses adapters instead of application code importing
  operating-system behavior directly,
- scaffolded Windows adapters already exist for some capabilities,
- diagnostics expose scaffolded or unsupported states.

This epic upgrades the Windows path from passive scaffold toward an explicitly
opt-in experimental layer. The work is mainly adapter implementation and
contract testing. The hard parts are not domain logic; they are Windows shell
quoting, task scheduling, command shims, venv paths, filesystem naming, and
client hook behavior.

## Support-Level Target

Initial implementation target:

- `platform=windows`
- `support_level=experimental`
- `evidence=public_docs` plus `static_contract_test`
- no default production claim
- no `supported` status without real Windows CI and smoke evidence

Recommended status progression:

1. `scaffolded`: structure exists, no runtime mutation by default.
2. `experimental`: adapters can run through explicit opt-in or Windows runtime
   detection, with static contracts and documented caveats.
3. `smoke_validated`: Windows CI and at least one real install/monitor/wrapper
   smoke pass.
4. `supported`: maintained production path with repeated runtime evidence.

## Non-Goals

- Do not claim full Windows support in this epic.
- Do not rewrite macOS LaunchAgent behavior.
- Do not route Windows through POSIX/Bash assumptions.
- Do not require symlink privileges or Developer Mode for command publication.
- Do not make Windows scheduler installation destructive without explicit
  operator intent.
- Do not bypass the existing platform extension protocol.

## Public Documentation Anchors

Agent developers should verify implementation details against official docs
before changing runtime behavior:

- Windows automation model and shell split:
  <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/windows-commands>
- Windows Task Scheduler CLI:
  <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/schtasks-create>
- PowerShell quoting rules:
  <https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_quoting_rules>
- PowerShell process launching:
  <https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/start-process>
- Windows file/path naming:
  <https://learn.microsoft.com/en-us/windows/win32/fileio/naming-a-file>
- Windows symbolic links:
  <https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/mklink>
- Python virtual environments on Windows:
  <https://docs.python.org/3/library/venv.html>

## Current Baseline

Existing relevant areas:

- `backend/src/agent_context_engine/application/platform/profile.py`
- `backend/src/agent_context_engine/application/platform/runtime_selection.py`
- `backend/src/agent_context_engine/application/platform/runtime_summary.py`
- `backend/src/agent_context_engine/application/platform/platform.spec.md`
- `backend/src/agent_context_engine/adapters/command_publishers.py`
- `backend/src/agent_context_engine/adapters/wrapper_renderers.py`
- `backend/src/agent_context_engine/adapters/hook_adapter_rendering.py`
- `backend/src/agent_context_engine/adapters/path_quoting.py`
- `backend/src/agent_context_engine/adapters/process_launch.py`
- `backend/src/agent_context_engine/adapters/workspace_binding.py`
- `backend/src/agent_context_engine/adapters/system_open.py`
- `backend/src/agent_context_engine/adapters/executable_permissions.py`
- `backend/src/agent_context_engine/adapters/scheduler_installers.py`
- `backend/src/agent_context_engine/application/scheduler_installation.py`
- `docs/runbooks/platform-extension-protocol.md`

Current Windows posture:

- Windows profile exists as scaffolded.
- Runtime selection surfaces scaffolded Windows choices.
- Some adapter placeholders exist.
- Tests assert that Windows scaffolded paths remain visible and non-accidental.

## Proposed New Files

Create a dedicated Windows adapter package instead of growing mixed generic
adapter modules indefinitely:

```text
backend/src/agent_context_engine/adapters/windows/__init__.py
backend/src/agent_context_engine/adapters/windows/command_publication.py
backend/src/agent_context_engine/adapters/windows/scheduler.py
backend/src/agent_context_engine/adapters/windows/wrapper_rendering.py
backend/src/agent_context_engine/adapters/windows/hook_rendering.py
backend/src/agent_context_engine/adapters/windows/path_quoting.py
backend/src/agent_context_engine/adapters/windows/process_launch.py
backend/src/agent_context_engine/adapters/windows/workspace_binding.py
backend/src/agent_context_engine/adapters/windows/system_open.py
backend/src/agent_context_engine/adapters/windows/executable_permissions.py
backend/src/agent_context_engine/adapters/windows/windows.spec.md
```

Optional later split if the files grow:

```text
backend/src/agent_context_engine/adapters/windows/schtasks_xml.py
backend/src/agent_context_engine/adapters/windows/powershell_quoting.py
backend/src/agent_context_engine/adapters/windows/cmd_quoting.py
```

## Existing Files To Update

Update these files as the implementation progresses:

```text
backend/src/agent_context_engine/application/platform/profile.py
backend/src/agent_context_engine/application/platform/runtime_selection.py
backend/src/agent_context_engine/application/platform/runtime_summary.py
backend/src/agent_context_engine/application/platform/platform.spec.md
backend/src/agent_context_engine/application/scheduler_installation.py
backend/src/agent_context_engine/ports/platform.py
backend/src/agent_context_engine/ports/scheduler_installation.py
docs/runbooks/platform-extension-protocol.md
docs/runbooks/integration-management.md
docs/setup/RUNNER_HARNESSES.md
tests/test_agent_context_engine.py
```

Only update `AGENT_BOOTSTRAP.md`, `session-start-hook-entry.md`, and runner
entrypoint docs if the user-facing installation or hook contract changes.

## Adapter Responsibilities

### Command Publication

File:

- `backend/src/agent_context_engine/adapters/windows/command_publication.py`

Implement:

- `.cmd` shims for public commands such as `agent-context-engine`, `codex-ace`,
  `claude-ace`, `agy-ace`, `gemini-ace`, and `opencode-ace`
- optional `.ps1` companion scripts if PowerShell is needed for robust launch
- remove/update behavior for existing generated shims
- registry metadata compatible with the existing link registry

Avoid:

- depending on `mklink` for the default path
- requiring Administrator privileges or Developer Mode
- writing user PATH changes without explicit installation flow approval

Minimum contract tests:

- generated `.cmd` file calls the expected Python/script target
- arguments are forwarded correctly
- paths with spaces are quoted
- generated file contains a stable marker/version for safe replacement
- non-owned files are not overwritten without explicit replace intent

### Wrapper Rendering

File:

- `backend/src/agent_context_engine/adapters/windows/wrapper_rendering.py`

Implement:

- PowerShell-first wrapper rendering
- optional `.cmd` entrypoint that delegates to PowerShell with safe flags
- environment variable export strategy
- launch cwd preservation
- recursion guard variables
- argument pass-through

Important details:

- PowerShell single-quoted strings are literal; double-quoted strings expand
  variables.
- Avoid ad hoc string concatenation where a structured argument list can be
  rendered deterministically.
- Treat paths with spaces as normal, not edge cases.

Minimum contract tests:

- wrapper includes expected environment variables
- wrapper preserves launch cwd
- wrapper forwards all arguments
- wrapper avoids Bash/POSIX commands
- wrapper output is deterministic for golden fixture comparison

### Hook Rendering

File:

- `backend/src/agent_context_engine/adapters/windows/hook_rendering.py`

Implement:

- Windows hook adapter scripts or command lines for supported runner clients
- PowerShell-safe JSON/stdin handling
- tool output async guard equivalents where currently required
- clear scaffolded/experimental support metadata per runner

Minimum contract tests:

- generated hook config uses Windows path separators safely
- hook command points at the correct Python executable or script
- stdin/stdout behavior remains compatible with existing hook contracts
- unsupported runner/platform combinations remain explicit

### Scheduler

File:

- `backend/src/agent_context_engine/adapters/windows/scheduler.py`

Implement:

- Windows Task Scheduler adapter based on `schtasks`
- install/load/update command construction
- status/query command construction
- unload/delete command construction
- dry-run payloads for diagnostics and tests

Preferred initial shape:

- generate commands but gate real mutation behind explicit install action
- use a dedicated task folder/name such as `AgentContextEngine\\<instance>`
- prefer least privilege and current-user behavior for local installs

Open design choice:

- whether to use direct `schtasks /create` command arguments or generate a Task
  Scheduler XML definition. XML may be more robust for complex quoting but adds
  more surface area.

Minimum contract tests:

- command construction quotes `/tn` and `/tr` correctly
- status parser handles missing task and existing task
- delete command includes force/non-interactive behavior where appropriate
- diagnostics show `windows_task_scheduler` as experimental or scaffolded

### Path Quoting

File:

- `backend/src/agent_context_engine/adapters/windows/path_quoting.py`

Implement:

- PowerShell single-quote escaping
- cmd.exe argument escaping where `.cmd` shims are generated
- path normalization without losing drive letters or UNC prefixes
- explicit handling for reserved Windows device names and invalid characters

Minimum contract tests:

- `C:\Users\Name With Spaces\project`
- UNC path like `\\server\share\project`
- paths containing apostrophes
- path components such as `CON`, `NUL`, `COM1` are rejected or safely reported
- no POSIX-only assumption such as leading `/` required

### Process Launch

File:

- `backend/src/agent_context_engine/adapters/windows/process_launch.py`

Implement:

- Windows subprocess launch model
- monitor launch command construction
- explicit shell/no-shell behavior
- environment merge behavior
- optional PowerShell `Start-Process` support only where shell execution is
  actually required

Minimum contract tests:

- launches are represented as argv where possible
- working directory is preserved
- environment values are injected deterministically
- no Bash-specific command construction leaks into Windows path

### Workspace Binding

File:

- `backend/src/agent_context_engine/adapters/windows/workspace_binding.py`

Implement:

- workspace root normalization for Windows paths
- storage of workspace bindings with platform-neutral internal identity
- drive-letter and UNC path support
- no accidental conversion of Windows paths into POSIX-like paths

Minimum contract tests:

- same path with case differences normalizes predictably
- drive-letter paths and UNC paths remain distinguishable
- relative launch cwd is resolved consistently

### System Open

File:

- `backend/src/agent_context_engine/adapters/windows/system_open.py`

Implement:

- browser/file open behavior using Windows shell semantics
- clear fallback when no browser/open target is available
- no use of macOS `open` or POSIX `xdg-open`

Minimum contract tests:

- monitor URL open command is constructed correctly
- file path open command is constructed correctly
- headless/no-open mode remains a no-op

### Executable Permissions

File:

- `backend/src/agent_context_engine/adapters/windows/executable_permissions.py`

Implement:

- no-op executable permission strategy for generated `.cmd` and `.ps1` files
- optional validation of generated file suffixes
- explicit support metadata

Minimum contract tests:

- no `chmod` is emitted
- generated scripts are still considered runnable by extension

## Implementation Phases

### Phase 0: Guardrails And Inventory

Deliverables:

- confirm current macOS full test suite is green before Windows work
- add a short inventory of remaining POSIX assumptions found by `rg`
- decide status label for first slice: `scaffolded` or `experimental`

Suggested searches:

```sh
rg -n "chmod|ln -s|launchctl|open |xdg-open|/bin/|\\.venv/bin|readlink|mktemp|bash|shlex|Path\\('/|Path\\(\"/" backend scripts tests
```

Acceptance:

- no code changes needed yet
- list of Windows-relevant assumptions is captured in this epic or a follow-up
  implementation note

### Phase 1: Adapter Package And Static Contracts

Deliverables:

- create `adapters/windows/`
- move or wrap current Windows scaffold classes into dedicated Windows files
- keep existing public imports stable where practical
- add unit/contract tests for adapter metadata and generated script text

Acceptance:

- all Windows adapters expose:
  - `adapter_name`
  - `support_level`
  - `evidence`
- scaffolded adapters remain non-mutating
- contract tests pass on macOS without a Windows runtime
- macOS runtime selection remains unchanged

### Phase 2: Windows Command And Wrapper Output

Deliverables:

- implement `.cmd` command publisher
- implement PowerShell wrapper renderer
- implement path quoting helpers
- add golden fixtures for generated Windows scripts

Acceptance:

- Windows command publication can generate files in a temp directory
- generated files include owned markers
- paths with spaces and apostrophes pass contract tests
- no symlink privilege is required

### Phase 3: Hook And Client Integration Shape

Deliverables:

- implement Windows hook rendering for the supported client families where the
  hook contract is known
- keep unsupported clients explicit
- update runtime summary and doctor output

Acceptance:

- hook command strings are deterministic
- hook paths point to Windows-compatible script locations
- startup guidance does not mention POSIX-only commands for Windows
- tests cover Codex, Claude, Cursor, and global-only runner decisions as
  appropriate

### Phase 4: Scheduler Experimental Adapter

Deliverables:

- implement Windows Task Scheduler command construction
- decide direct `schtasks` arguments versus XML task definition
- add dry-run/status parser tests
- keep real mutation behind explicit install action

Acceptance:

- scheduler installer selection returns Windows adapter for Windows profile
- install/status/uninstall command construction is tested
- diagnostics state support level and evidence
- no scheduler mutation runs during scaffolded/static tests

### Phase 5: Windows CI

Deliverables:

- add GitHub Actions Windows job
- run Python unit tests and selected integration-style tests
- avoid tests that require privileged Task Scheduler mutation unless explicitly
  isolated

Acceptance:

- Windows CI installs dependencies
- Windows CI runs contract tests
- Windows CI runs a smoke subset for install discovery, wrapper rendering,
  command publication, and runtime summary
- status may move from `scaffolded` to `experimental` if CI is stable

### Phase 6: Runtime Smoke Validation

Deliverables:

- real Windows install smoke
- monitor start smoke
- wrapper invocation smoke
- scheduler dry-run or real task smoke, depending on permissions
- one client hook flow smoke where a supported client is available

Acceptance:

- smoke evidence is documented
- diagnostics and runbooks are updated
- capability evidence can move to `smoke_validated` only for proven pieces

## Testing Strategy

Required targeted tests:

```sh
python3 -m unittest \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_platform_profiles_keep_future_platforms_scaffolded \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_platform_runtime_selection_keeps_windows_publication_scaffolded \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_runtime_selection_summary_surfaces_windows_scaffolded_stack \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_runtime_selection_summary_surfaces_windows_process_launch_scaffolded \
  tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_doctor_reports_scaffolded_platform_runtime_selection \
  -v
```

Add new tests for:

- Windows `.cmd` shim generation
- PowerShell wrapper rendering
- PowerShell quoting helper
- cmd argument forwarding
- Windows Task Scheduler command construction
- Windows venv Python path selection
- Windows runtime summary and doctor text
- macOS runtime selection preservation

Required gates before completion:

```sh
python3 -m py_compile <changed-python-files>
python3 scripts/update_docs_index.py --check
./scripts/check --skip-runtime-db --skip-tests
python3 tests/test_agent_context_engine.py
```

For Windows CI:

```powershell
python -m unittest discover -s tests -v
python scripts/update_docs_index.py --check
```

## Acceptance Criteria

The epic is complete for Windows experimental support when:

- Windows adapters live behind runtime selection.
- No Windows behavior is implemented in macOS-specific adapters.
- macOS tests remain green.
- Windows contract tests are deterministic and pass on non-Windows hosts.
- Windows CI runs at least the non-mutating smoke subset.
- generated `.cmd` and PowerShell outputs are covered by golden or structural
  tests.
- scheduler behavior is either dry-run only or explicitly operator-triggered.
- diagnostics clearly report Windows support level and evidence.
- docs state that Windows is experimental, not supported.

The epic is not complete if:

- Windows code relies on Bash, `chmod`, `ln -s`, `launchctl`, or macOS `open`.
- scaffolded code mutates OS state by default.
- support metadata says `supported` without real Windows evidence.
- command shims overwrite non-owned files.
- macOS runtime behavior changes without intentional tests.

## Risk Register

### PowerShell and cmd quoting

Risk: generated wrappers work for simple paths but fail for spaces, quotes, or
special characters.

Mitigation:

- centralize quoting helpers
- add fixture coverage for difficult paths
- prefer argv/subprocess where shell execution is not required

### Task Scheduler command complexity

Risk: `schtasks /create` accepts simple cases but fails for complex command
lines or localized date/time behavior.

Mitigation:

- start with conservative schedules
- consider XML task definition for complex cases
- keep real mutation behind explicit operator action

### Symlink privileges

Risk: symlink-based publication fails without Administrator privileges or
Developer Mode.

Mitigation:

- default to generated `.cmd`/`.ps1` shims
- treat symlinks as optional diagnostics only

### Python venv layout

Risk: code assumes `.venv/bin/python`; Windows uses `.venv\Scripts\python.exe`.

Mitigation:

- introduce a platform-aware Python executable resolver
- test both POSIX and Windows layouts

### File locking and path semantics

Risk: SQLite and file operations behave differently under Windows locks and
case-insensitive paths.

Mitigation:

- add retry coverage where applicable
- normalize workspace identities carefully
- do not collapse UNC and drive-letter paths into the same form

### Client hook behavior

Risk: Codex, Claude, Cursor, and global-only runner hooks may differ on Windows.

Mitigation:

- keep each runner integration capability-scoped
- mark unverified runners as scaffolded or unsupported
- validate with real client smoke runs before raising support level

## Realistic Effort Estimate

For a fast agent developer:

- scaffold cleanup and dedicated Windows package: 2-4 hours
- command publication and quoting helpers: 3-6 hours
- PowerShell wrapper/hook rendering contracts: 4-8 hours
- scheduler command construction and diagnostics: 4-8 hours
- Windows CI smoke subset: 4-8 hours
- real Windows runtime smoke fixes: 1-3 days depending on environment and
  client availability

Expected total:

- experimental static layer: 1-2 focused days
- Windows CI-backed experimental layer: 2-3 focused days
- smoke-validated beta: 3-6 focused days
- supported production path: only after repeated runtime evidence

## Agent Developer Operating Instructions

1. Read `AGENTS.md`, `docs/runbooks/platform-extension-protocol.md`, and this
   epic first.
2. Preserve current macOS behavior. Run macOS-focused tests before and after.
3. Implement Windows behavior only through ports and adapters.
4. Keep scaffolded/experimental metadata honest.
5. Use public official docs for Windows behavior and record assumptions in code
   comments only where they prevent misuse.
6. Add or update nearest `*.spec.md` files when a boundary changes.
7. Run `python3 scripts/update_docs_index.py --check` after adding this or any
   durable doc.
8. Do not mark Windows as `supported` unless real Windows runtime evidence is
   included in the same change.

## Recommended First Pull Request Scope

Keep the first PR narrow:

- add `adapters/windows/`
- move current Windows scaffolds into dedicated modules
- implement command shim generation and path quoting
- add contract tests and golden outputs
- update runtime summary/doctor text
- keep scheduler as scaffolded if not implemented yet

This first PR should make Windows easier to reason about without claiming that
Windows is ready for normal users.
