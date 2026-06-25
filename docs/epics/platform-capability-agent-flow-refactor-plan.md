# Epic / Refactor Plan: Platform Capability And Agent Flow Boundaries

> Status 2026-06-25: **in progress**.
> Agent Context Engine is currently developed and validated primarily for
> macOS. This epic prepares the codebase for future Linux, Windows, WSL, and
> other platform support without claiming support before real runtime evidence
> exists. The first implementation target is a behavior-preserving macOS
> refactor.
>
> Implementation note 2026-06-25: committed golden fixtures now live under
> `tests/fixtures/platform_capability_agent_flow_refactor/`, and static
> contract assertions cover scaffolded platform profiles plus scaffolded
> hook/wrapper renderer outputs.
> Runtime selection now keeps scaffolded and unsupported non-macOS profiles on
> non-active adapter paths instead of silently falling through to mutation-
> capable macOS/POSIX behavior.

## Goal

Make operating-system, shell, wrapper, scheduler, and agent-instruction
behavior explicit and replaceable while keeping the current macOS behavior
functionally unchanged.

The target shape is:

- application code reasons about capabilities, not `launchctl`, Bash, symlinks,
  or platform-specific file layouts,
- generated agent instructions come from one structured contract,
- wrappers and hook adapters are generated from declarative specs,
- diagnostics report supported, degraded, scaffolded, and unsupported states
  accurately,
- future platform additions can be scaffolded by developer agents without
  claiming runtime support before validation.

## Non-Goals

- Do not add Linux, Windows, or WSL production support in the first slice.
- Do not rewrite the runtime from scratch.
- Do not replace the current macOS LaunchAgent behavior until the adapter path
  is verified to preserve it.
- Do not let scaffolded platform code execute privileged or destructive OS
  actions by default.
- Do not duplicate backup files in the repository such as `*.bak` or old module
  copies.

## Current Pressure Points

### macOS Scheduler Coupling

The current scheduler installation path is centered on LaunchAgent, plist, and
`launchctl` behavior. That is valid for macOS but should be represented as one
scheduler backend, not as the generic runtime model.

### POSIX Wrapper And Hook Assumptions

Global wrappers and hook adapters are Bash-first and assume POSIX utilities such
as `readlink`, `mktemp`, `env`, executable bits, and symlinks. Those assumptions
are acceptable for macOS and many Linux environments, but they are not a general
platform contract.

### Agent Guidance Drift

`AGENTS.md`, `session-start-hook-entry.md`, Cursor rules, Claude entrypoints,
and monitor guidance are generated from text blocks near installation code.
Those instructions must instead be rendered from a structured agent-flow
contract so command prefixes, control-plane lines, monitor commands, and
platform caveats stay aligned.

### Binary Support Language

Future platforms must not be treated as either fully supported or absent. A
platform can be scaffolded, statically validated, experimental, smoke-validated,
or supported.

## Target Concepts

### Platform Profile

Represents the host/platform family and the selected implementation profile.

Initial profiles:

- `macos`: active production profile
- `posix_generic`: scaffold target, disabled by default
- `linux`: scaffold target, disabled by default
- `wsl`: scaffold target, disabled by default
- `windows`: scaffold target, disabled by default
- `unknown`: explicit unsupported fallback

### Runtime Capabilities

Capabilities describe what the installation can actually do on the current
machine. They must not be inferred from OS name alone.

Core capabilities:

- scheduler backend
- global command publication
- shell rendering family
- hook adapter runtime
- wrapper rendering family
- browser/file open behavior
- process launch and resume behavior
- workspace binding behavior
- executable permission strategy
- symlink or shim strategy
- path and quoting strategy

### Support Level

Every platform profile and platform-specific capability must carry a support
level:

- `unsupported`: known unavailable
- `scaffolded`: structure exists, not intended for runtime use
- `experimental`: can be explicitly opted into, not production-supported
- `smoke_validated`: a minimal real runtime pass exists
- `operator_validated`: real user workflow evidence exists
- `supported`: maintained and documented production path

### Evidence Level

Support claims must state their evidence:

- `tested`: verified on the real platform
- `static_contract_test`: verified by adapter/renderer contracts only
- `public_docs`: based on public OS/tool behavior
- `inferred`: reasonable but unverified engineering inference

Agents may add scaffolded or experimental support from public knowledge, but
must not mark a platform as smoke-validated or supported without runtime
evidence.

### Agent Flow Contract

One structured contract should feed every generated agent-facing instruction.

Required fields:

- preferred language
- canonical command prefix
- session lookup commands
- handover and retrieval commands
- repo-context commands
- personal-context rules
- monitor command
- user-only control-plane lines
- runtime caveats
- platform support status
- safe fallback commands
- contract version

Render targets:

- `AGENTS.md`
- `session-start-hook-entry.md`
- `CLAUDE.md`
- Cursor always-apply rule
- hook-injected startup/context guidance
- monitor how-to text where applicable

### Wrapper And Hook Specs

Wrappers and hook adapters should be represented as declarative specs before
they are rendered to Bash, PowerShell, cmd, or another runtime.

Spec fields:

- wrapper name
- backing client command
- required hook/config paths
- installation root
- launch cwd preservation
- exported environment variables
- working directory behavior
- arguments passed through or rewritten
- recursion guard variables
- support level and evidence
- spec version

The first renderer remains Bash and must preserve macOS behavior.

## Target Ports And Adapters

### New Or Formalized Ports

- `PlatformDetectorPort`
- `RuntimeCapabilitiesPort`
- `SchedulerInstallerPort`
- `GlobalCommandPublisherPort`
- `WrapperRendererPort`
- `HookAdapterRendererPort`
- `InstructionRendererPort`
- `ProcessLaunchPort`
- `SystemOpenPort`

### Initial Adapters

- `MacOSPlatformProfile`
- `MacOSLaunchAgentSchedulerInstaller`
- `SymlinkGlobalCommandPublisher`
- `BashWrapperRenderer`
- `BashHookAdapterRenderer`
- `MarkdownInstructionRenderer`
- `DefaultSystemOpenAdapter`

### Future Scaffold Adapters

These may be introduced later as scaffolded or experimental adapters:

- `SystemdUserSchedulerInstaller`
- `CronSchedulerInstaller`
- `WindowsTaskSchedulerInstaller`
- `PowerShellWrapperRenderer`
- `CmdShimPublisher`
- `WslPlatformProfile`

No future adapter should be runtime-enabled without explicit support-level and
evidence metadata.

## macOS Compatibility Invariants

The refactor is successful only if these macOS behaviors remain materially
unchanged:

1. `install` still writes the expected installation profile, wrapper metadata,
   monitor defaults, memory-root configuration, and LaunchAgent defaults.
2. `install` still links the configured global commands when requested.
3. `install-launchagent --load` still writes and loads the same effective
   LaunchAgent job.
4. `launchagent-status --verbose` still reports the installed and loaded state.
5. `doctor` and `check-installation` still surface LaunchAgent, wrapper,
   binding, monitor, and storage drift.
6. `monitor --runner <runner> --replace-existing` still starts the local
   monitor with the same default behavior.
7. `cursor-enable` still writes the expected Cursor hook adapter, binding,
   agent instructions, and startup entry.
8. `AGENTS.md` and `session-start-hook-entry.md` still point at the active
   command prefix and valid startup commands.
9. `resume` and `handover` still render the same effective resume commands for
   supported clients.
10. Internal Agent Context Engine subprocesses still bypass hook capture.

## Test Strategy

### Baseline Before Refactor

Before changing behavior, add characterization and golden tests for the current
macOS output shape.

Initial golden targets:

- generated Agent Context Engine block in `AGENTS.md`
- generated `session-start-hook-entry.md`
- generated `CLAUDE.md`
- generated Cursor always-apply rule
- generated Cursor hook adapter
- generated or installed wrapper scripts where feasible

Initial characterization targets:

- installation plan rendering
- command prefix resolution
- wrapper naming
- LaunchAgent plist rendering
- session resume command rendering
- platform capability rendering for macOS

### Adapter Contract Tests

Each adapter must satisfy a shared contract suite for:

- idempotent output,
- expected failure classes,
- support-level reporting,
- evidence-level reporting,
- degraded/unsupported behavior,
- no unexpected runtime mutation in scaffolded profiles.

### Real Runtime Smoke Tests

Real platform smoke tests remain separate from static tests.

macOS smoke targets:

- `agent-context-engine install-discovery`
- temp-root install with LaunchAgent disabled where appropriate
- `agent-context-engine monitor --no-open --replace-existing`
- `agent-context-engine install-launchagent --load` in approved local runs
- `agent-context-engine launchagent-status --verbose`

Linux, Windows, and WSL cannot be promoted beyond `scaffolded` or
`experimental` without real runtime evidence.

## Backup And Fallback Strategy

Git is the primary rollback mechanism. The refactor should proceed in small
slices with clean diffs.

Allowed fallback artifacts:

- golden test fixtures committed to the repository,
- temporary patches under `/tmp` or `/private/tmp` during risky mechanical
  refactors,
- documented characterization outputs used as tests.

Disallowed fallback artifacts:

- `*.bak` copies in source directories,
- duplicated legacy modules kept beside new modules,
- untracked repo-local backup folders.

## Implementation Plan

### Phase 0: Baseline And Evidence

- Record the current macOS behavior matrix.
- Add golden tests for generated agent instruction artifacts.
- Add characterization tests for LaunchAgent plist rendering and resume command
  rendering.
- Add a short implementation note explaining that future OS support starts as
  scaffolded until runtime evidence exists.

### Phase 1: Platform And Capability Model

- Add platform profile and runtime capability DTOs.
- Add support-level and evidence-level enums.
- Resolve the active macOS profile from current behavior.
- Represent non-macOS platforms as explicit unsupported/scaffolded profiles
  without runtime mutation.

### Phase 2: Agent Flow Contract

- Add `AgentFlowContract`.
- Move agent instruction data out of ad hoc text assembly.
- Render `AGENTS.md`, `session-start-hook-entry.md`, `CLAUDE.md`, and Cursor
  rules from the contract.
- Keep rendered macOS output equivalent to the current output.

### Phase 3: Wrapper And Hook Specs

- Add wrapper and hook adapter specs.
- Render current Bash wrappers and hook adapters from those specs.
- Keep current macOS/POSIX script output equivalent unless a documented
  intentional cleanup is approved.

Implementation status note:

- structured hook and wrapper render specs are now present in the application
  boundary and the active hook render paths use them
- runtime verification of macOS-visible output is still pending

### Phase 4: Publishing And Scheduler Ports

- Introduce `GlobalCommandPublisherPort`.
- Move symlink/global command logic behind the publisher adapter.
- Introduce `SchedulerInstallerPort`.
- Move LaunchAgent write/load/status behavior behind the macOS scheduler
  adapter.
- Keep CLI commands behavior-compatible.

### Phase 5: Diagnostics And Monitor Capability Reporting

- Change diagnostics to report capabilities instead of assuming LaunchAgent as
  the universal scheduler concept.
- Keep macOS output understandable and behavior-compatible.
- Surface scaffolded and unsupported platform states explicitly.

### Phase 6: Platform Extension Protocol

- Document the required files, fields, tests, and support-level rules for adding
  another platform.
- Add a template checklist for developer-agent contributions.
- Require every new platform contribution to include capability metadata,
  golden tests, contract tests, support-level evidence, and explicit runtime
  gates.

Implementation status note:

- the protocol now exists as `docs/runbooks/platform-extension-protocol.md`
- runtime promotion still requires real verification evidence, not only docs

## Platform Extension Protocol

A future developer-agent contribution for a new platform must include:

1. a platform profile,
2. a runtime capability matrix,
3. support-level and evidence-level values,
4. adapter stubs or implementations behind existing ports,
5. golden outputs for generated instructions and wrapper/hook artifacts,
6. contract tests for each implemented adapter,
7. disabled-by-default runtime behavior unless smoke-validated,
8. explicit diagnostics text for unsupported and degraded flows,
9. documentation of public OS assumptions,
10. a promotion checklist for moving from `scaffolded` to `experimental` or
    higher.

## Acceptance Criteria

This epic is materially complete when:

1. macOS behavior is covered by golden and characterization tests.
2. Platform profile, runtime capabilities, support level, and evidence level
   are represented in application-level models.
3. Agent-facing instruction files are rendered from a structured
   `AgentFlowContract`.
4. Wrapper and hook adapter generation flows through declarative specs.
5. LaunchAgent behavior is reachable through a macOS scheduler adapter instead
   of being the generic scheduler concept.
6. Global command publishing is reachable through a publisher adapter.
7. Diagnostics can distinguish supported, scaffolded, experimental, degraded,
   and unsupported platform flows.
8. No non-macOS platform is claimed as supported without real runtime evidence.
9. Existing macOS installation, monitor, LaunchAgent, wrapper, hook, and
   handover flows remain behavior-compatible.

## Open Decisions

- Whether WSL should be treated as a Linux profile variant or a separate
  platform profile from the beginning.
- Whether scaffolded Linux support should use `systemd --user` or a manual
  scheduler-first model as the first future adapter.
- Native Windows remains a real target platform. WSL may still need its own
  profile and adapter path, but it is not the substitute support answer for
  Windows native runtime support.
- How strict golden tests should be for generated shell scripts: byte-exact or
  normalized for whitespace and generated absolute paths.
- Whether platform support-level metadata should be persisted in the
  installation profile or computed from current runtime discovery each time.

## First Safe Slice

The first implementation slice should not touch runtime OS behavior. It should:

1. add golden tests around current generated agent guidance,
2. add `AgentFlowContract` data structures,
3. render the current `AGENTS.md` quick path and session-start entry from that
   contract,
4. prove the rendered output is equivalent to the current output,
5. leave installation, LaunchAgent, monitor, wrappers, and hook execution
   behavior unchanged.
