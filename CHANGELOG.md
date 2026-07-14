# Changelog

All notable changes to Agent Context Engine are documented in this file.

This repository currently has one public baseline commit:

- `0.1.3` backend / product
- `0.5.7` monitor

The entries below document the changes added since that initial public release.

## Unreleased (target: Backend 0.2.14)

### Changed

- Direct-user hook controls now support `--project` for the exact current
  workspace and may combine it with `--runner`. Project disable keeps the
  minimal hook connection installed, so status and direct-user re-enable remain
  available while normal project events no-op. Enable responses now report the
  effective state when a global or broader runner disable still wins. Agent
  tool attempts and direct edits of `hooks-state.json` remain non-overridable
  control-plane blocks.
- Installer monitor takeover no longer sends signals to registry- or
  status-derived PIDs and no longer starts with `--replace-existing`.
  Superseded monitors stop through a token-authenticated loopback shutdown or a
  verified ACE-owned platform launcher, followed by an eight-second stability
  check before and after startup. Registered monitors that are temporarily
  unreachable now fail takeover closed. Windows uses only a root-specific owned
  Task Scheduler launcher for installer autostart.
- Windows setup documentation now describes manual migration from legacy
  unhashed monitor tasks and `windows-monitor-start.cmd` to root-specific
  experimental monitor launchers.
- Bare `agent-context-engine` now prints the public command help and direct-user
  system-control guidance. Agent-driven installs now require a persisted,
  unchanged discovery plan for approval and execution, and restricted auth
  probes are documented as inconclusive until rerun with adequate access.
- Installation now verifies required root hook artifacts, including the
  OpenCode plugin bridge. `repair-installation --apply` repeats root hook and
  global bridge finalization after its prerequisites are healthy.
- The canonical development check now forces monitor browser opening off for
  every subprocess, so install and monitor smoke tests cannot create visible
  How-to tabs.
- Natural-language deactivation guidance now distinguishes exact-project,
  project-runner, installation-runner, all-hooks, and full-system scope,
  returns the exact direct-user control line, and forbids probing
  mutation/help variants or suggesting firewall bypasses.
- Added direct-user full-system suspension through exact runner-native chat
  controls. Suspension persists installation-specific state, closes normal hook
  and background admission, disables only the owned scheduler, keeps the
  monitor available read-only, preserves hook configuration, and restores only
  scheduler state captured as active before suspension.
- Added read-only `agent-context-engine system-status [--json]`, monitor status
  visibility, fail-closed partial/invalid-state recovery guidance, bounded
  operation audit records, suspended wrapper behavior, and deterministic
  blocking of recognizable agent/tool attempts to invoke mutating system
  controls. The monitor now labels control provenance as an instrumented,
  unverified runner event rather than authenticated user presence.
- Suspended CLI admission now uses an explicit safe-while-suspended
  command/subcommand allowlist, so mutating and unknown future commands default
  to denied. Bounded inspection metadata refreshes remain available, while
  explicit output writes such as `install-discovery --plan-json` are blocked.
- Documented native Windows smoke-run learnings for `.cmd` shim Python
  selection, monitor process hosting, external storage-root environment, PID
  probing, scheduler wording, and Dream queue interpretation.
- `codex-ace`, `claude-ace`, `agy-ace`, and `gemini-ace` activation prompts
  now use the installed Agent Context Engine language before falling back to
  terminal locale settings.
- Monitor status now uses a fast integration summary for the dashboard path
  instead of blocking on external runner auth or model-discovery probes.
- Added Windows monitor start helpers that resolve the local runtime, set the
  storage root, write logs, and wait for both status and firewall endpoints.
- Windows installer monitor autostart now uses a root-specific Task Scheduler
  launcher instead of an unowned command-host process.

### Fixed

- Installer monitor takeover now treats registry and status PIDs as diagnostics
  only. Tokenless unmanaged or identity-mismatched listeners fail safely with a
  manual-stop instruction instead of risking PID reuse, and corrupted registry
  ports are skipped rather than aborting installation. Windows monitor startup
  verifies the same `/api/status` identity as POSIX instead of accepting any
  stable listener.
- Incomplete requested installs now return a non-zero exit code. POSIX monitor
  startup rolls back the new process when superseded-monitor cleanup cannot be
  verified instead of reporting failure while leaving it running.
- System-control state, anchor, audit paths, and their `memory/local` parent are
  now protected from unknown structured write tools as well as known
  patch/edit/write tools and shell mutation attempts. This remains defense in
  depth for instrumented runner paths, not same-user authentication.
- POSIX install monitor takeover now verifies the new monitor's installation
  and memory-root identity, detects verified unregistered old monitors, and
  fails finalization if a superseded monitor reappears. Verified legacy macOS
  `com.agent-context-engine.monitor-<port>` submitted KeepAlive jobs are
  unloaded before their superseded process is terminated. Post-install output
  reports authoritative Codex/Claude readiness and separates historical
  project-binding maintenance notices from current installation warnings.
- Post-install verification now recognizes a monitor already running for the
  same installation as active instead of reporting a false port conflict,
  normalizes default-home metadata consistently across install/check/repair,
  migrates stale nested `active-root` files, and ends with a compact localized
  success-or-warning result instead of burying completion in full diagnostics.
- Central hubs now derive their metadata root from their own resolved path when
  no explicit storage override is present, so direct runner and IDE hook calls
  stay bound to an isolated installation instead of falling back to the shared
  home installation.
- Claude, Gemini, and Antigravity hubs now use the same self-derived metadata
  root contract as Codex, so all central shell-hook runners stay bound to an
  isolated installation during direct IDE or runner calls.
- Legacy isolated profiles with a custom wrapper prefix remain classified as
  ambiguous during repair instead of guessing shared or isolated takeover
  behavior; repair now requires an explicit `--legacy-installation-mode`.
- Initialized system-control state is now hash-anchored. Missing or changed
  state fails closed, recovery revalidates under the operation lock, and risk
  scanning protects recognizable state/anchor mutation while allowing static
  read-only review searches.
- Runner classifier JSON extraction now accepts only known assistant-output
  fields for Gemini and Claude and rejects prompt echoes or multiple matching
  policy objects as ambiguous.
- Direct repo-local and instance-named wrapper commands now stay pinned to the
  installation that owns the wrapper, while canonical shared wrapper symlinks
  continue to follow the shared home `active-root` takeover contract.
- Shared installs with an external memory root now update both that root's hub
  metadata and the shared home `active-root`; isolated installs update only
  their installation-local metadata.
- Project hook backups now resolve their backup directory from the activating
  installation profile instead of process-global storage environment.
- Isolated central-hub installs no longer overwrite
  `$HOME/.agent-context-engine/active-root`; isolated metadata roots keep their
  own `active-root` and hub state.
- Windows project hook activation now writes native `.cmd`/PowerShell adapters
  instead of symlinking project-local `hook_adapter.cmd` files to POSIX
  `hook_adapter.sh` hubs.
- Fresh install and project activation now write workspace bindings for
  Antigravity and Gemini projects, matching the wrapper validation contract.
- `codex-ace` now verifies project-local Codex hook JSON content and the
  central hub executable before treating an existing `.codex/hooks.json` as
  active.
- `claude-ace` now verifies project-local Claude hook JSON content, repairs
  stale workspace bindings, migrates legacy relative and
  `${CLAUDE_PROJECT_DIR}` ACE hook commands to shell-quoted absolute
  project-local adapter commands, and the default home storage layout now
  writes central `active-root` metadata under `$HOME/.agent-context-engine`
  instead of below the memory directory.
- `agy-ace` and `gemini-ace` now validate runner-native hook config content,
  workspace bindings, and central hub executability before treating a project
  as active. `opencode-ace` now resolves the active installation via
  `active-root` and refuses to start without the OpenCode plugin bridge.
- Added `cursor-ace` as a current-project Cursor activation helper. It verifies
  Cursor hook status, can activate the current folder with `--activate-here`,
  and reminds users to restart or reload Cursor if newly written hooks are not
  picked up immediately.
- Wrapper activation prompts now accept both English and German yes aliases
  (`y`, `Y`, `j`, `J`) and explicit no aliases (`n`, `N`), with Enter kept as
  the default no response.
- Central shell wrappers now normalize the default
  `$HOME/.agent-context-engine/memory` storage path to the metadata root before
  validating hub symlinks, so a successful activation no longer gets rejected
  as inactive immediately afterwards.
- Codex, Claude, Gemini, and Antigravity hook activation now write and validate
  shell-quoted absolute commands to the project-local adapter symlink, and
  migrate legacy relative or runner-variable hook commands during activation so
  wrapper launches from nested folders and project paths with spaces can still
  execute hooks.
- Windows `.cmd` shims for Python entrypoints now prefer the installation
  runtime Python before falling back to global Python.
- Windows monitor autostart now uses a command-host launch path and verifies the
  bound monitor port instead of assuming a detached Python process stayed alive.
- Monitor status and storage inspection now tolerate Windows/user-state metadata
  write failures and stale PID probe errors.
- Direct monitor status calls without HTTP monitor context no longer fail while
  building monitor process metadata.
- The monitor status pilot no longer renders missing or still-loading firewall
  state as inactive.

### Validation

- The 2026-07-14 canonical macOS validation completed with compile, import,
  OpenAPI, docs-index, fresh-install, Doctor, CLI runtime, and install-integration
  checks green. The unit bucket ran 384 tests with 88 expected skips.
- Direct validation confirmed that `codex-ace`, `claude-ace`, `cursor-ace`,
  `agy-ace`, `gemini-ace`, and `opencode-ace` start successfully on the latest
  validation checkout. Windows remains experimental.

## Backend 0.2.13

### Fixed

- PreTool LLM classifier calls now extract risk JSON from event-wrapped runner
  output, use structured-output flags where supported, and retry text-only
  runner responses once with a schema-repair prompt before failing closed.
- Antigravity classifier and headless runner calls now use the `agy -p <prompt>`
  contract, and the Antigravity classifier default uses
  `Gemini 3.5 Flash (Minimal)`.
- OpenCode runner commands now use the current `--auto` flag instead of the
  removed `--dangerously-skip-permissions` option.

## Monitor 0.6.10

### Fixed

- Session risk summaries now present classifier-output failures as explicit
  firewall fail-closed events instead of generic tainted-context or policy
  blocks.

## Backend 0.2.12

### Fixed

- Hook blocking messages now call out invalid firewall classifier output and
  classifier-tainted follow-up blocks directly, including the relevant
  classifier flags in the taint-source details.

## Monitor 0.6.9

### Changed

- Firewall panel loading now uses bounded API requests and partial-failure
  handling so unavailable rule, suggestion, or risk endpoints no longer blank
  the whole panel.
- Session list rows now use the session id as the primary identifier and show a
  custom thread name separately when one exists.

## Backend 0.2.11

### Changed

- Added project-local central hook-adapter hubs for Codex, Claude, Gemini, and
  Antigravity, with wrapper startup staying in the current project directory
  and delegating through installation-owned hub symlinks.
- `integration-hooks`, install, and repair flows now keep central hubs,
  `active-root`, and `activated-projects.json` scoped to the concrete
  installation metadata root, including isolated storage-root installations.
- Updated runner harness documentation, activation guidance, and milestone
  handoff notes for the central hub model.

### Fixed

- `codex-ace` and `claude-ace` language detection now avoids Bash 4-only
  lowercase expansion so the wrappers work with the older Bash shipped on
  macOS.
- Global runner wrappers now tolerate an empty passthrough argument list under
  `set -u` and re-check hook activation before starting the underlying runner.
- Isolated activation no longer writes or validates central hook hubs through a
  global metadata path when the active installation uses its own metadata root.
- Project activation status now treats central registry entries without an
  explicit `installation_root` as belonging to the current installation instead
  of reporting a false hook-adapter mismatch.
- Global runner wrappers now derive the central hook hub from the installation
  profile memory root, so installations using an external memory root do not
  re-prompt after a successful project activation.
- `agy-ace` and `gemini-ace` now match the Codex/Claude wrapper flow by asking
  interactively before activating project hooks and then continuing to the
  runner after a successful activation.
- Shell hook activation now handles fresh projects without an existing runner
  config file, including `.claude/settings.json`, instead of crashing while
  checking for merge conflicts.
- Gemini and Antigravity central hook adapters now resolve the active
  installation script at runtime instead of leaving legacy renderer
  placeholders in the central-hub execution path.

## Monitor 0.6.8

### Fixed

- Dream inspect now keeps external runtime-memory audit and stage artifacts
  readable in the monitor, deduplicates repeated artifact rows, and recognizes
  the current deterministic-handover prompt heading in Dream-v2 detail views

## Backend 0.2.10

### Changed

- `agent-context-engine handover` now surfaces a concise dream-first session
  brief, shows the active summary kind explicitly, and keeps current session
  summary vs. latest dream memory distinct for fresh-session continuation

### Fixed

- session handover fallback and Dream-v2 summary/audit resolution now preserve
  absolute external runtime-memory paths instead of rewriting them under the
  repo root
- external runtime-memory project memory no longer crashes CLI handover output

## Monitor 0.6.7

### Changed

- install discovery, install summaries, and release docs now surface the
  canonical runtime repo index, recognized repo/folder entries, and the
  monitor path for reviewing that knowledge under `Personal -> Repo-Index`

## Backend 0.2.9

### Changed

- canonical repo knowledge now lives in `memory/knowledge/repos.md`, with
  legacy `docs/knowledge/repos.md` content imported as a fallback instead of
  remaining the primary runtime source
- install discovery and install summaries now report recognized repo/folder
  entries, the runtime repo-index location, and the supported follow-up path
  for adding more repos through the monitor or CLI-bound project flows

### Fixed

- repo-index retrieval, startup context loading, diagnostics, and index rebuilds
  now stay aligned on the same runtime repo-index path instead of mixing docs
  and runtime storage locations

## Monitor 0.6.6

### Changed

- documented the Windows installation surface alongside the public monitor
  release snapshot and aligned versioned status docs with the new install flow

## Backend 0.2.8

### Changed

- install and install-discovery now keep the platform scheduler enabled by
  default across the documented Windows/macOS flow, with prerequisite guidance
  surfaced for unsupported Python/Node/npm environments
- external Cursor project activation now records the target in install-wide
  `workspace_roots.cursor`, keeping `doctor`, `check-installation`, and monitor
  installation summaries aligned with `cursor-status --target ...`
- added bilingual top-level README entrypoints (`README.md`, `README_de.md`)
  plus project badges for Python, Node.js, license, and macOS runtime scope

### Fixed

- fresh-checkout installs no longer run the full `doctor` before final hook
  activation, so hook files stay late in the flow without forcing a manual
  `integration-hooks` repair before monitor startup
- fresh-install discovery no longer inherits a stale saved launchagent opt-out
  silently; new installs recommend the scheduler by default again and show the
  recommendation source explicitly
- Windows Antigravity hook config rendering now escapes command paths through
  structured JSON replacement instead of raw string interpolation
- Windows runtime bootstrap now resolves the venv Python path correctly and
  keeps wrapper publication and scheduler guidance aligned with the platform
- queued hook reservations now revert previously covered sessions back to
  `summary_pending` / `dream_pending` as soon as new work is reserved, instead
  of leaving stale fully-covered states visible until later replay

## Monitor 0.6.5

### Changed

- updated session visibility and integration metadata runbook docs for operator workflows

## Backend 0.2.7

### Changed

- added agentic documentation/version/changelog maintenance workflow with the `/docsupdate` editor entrypoint

## Backend 0.2.6

### Changed

- Added explicit persistence of Cursor background-runner choice in project bindings during
  activation and reuses that configured runner for dream routing and status reporting.
- Cursor hook wrapper generation now writes stable launch context (`AGENT_MEMORY_LAUNCH_CWD`)
  so project-aware behavior no longer regresses to installation-root context.
- Dream runner readiness checks now distinguish between CLI availability and usable auth for
  `claude` and `codex`, including explicit guidance for the correct auth checks.
- Query-expansion fallback now emits deterministic plan metadata even when the normal classifier
  path is blocked.

### Fixed

- Resolved `NameError` in generated Cursor hook adapters caused by shell variable interpolation
  in the shared template (`AGENT_MEMORY_DREAM`/`AGENT_MEMORY_INTERNAL_RUN`).
- Hardened dream stage parsing to include structured parse-failure metadata and stable fallback
  behavior instead of failing silently.

## Backend 0.2.5

### Changed

- Cursor project activation now stores a stable workspace launch hint in generated hook
  environments to keep origin-client and headless-runner resolution aligned with the
  real project path.
- Cursor binding persistence now keeps the requested background runner (`codex` or
  `claude`) in the project record and surfaces it through activation, status, and dream
  routing.

### Fixed

- Cursor dream sessions no longer drift to the default runner when a project-specific
  binding exists, including repeated start events from the same project path.
- Cursor activation now rejects headless workflows only when runner CLI auth state is missing,
  and the status reporting now reflects that readiness gate consistently.

## Monitor 0.6.4

### Changed

- Session list now visually separates origin client and background dream runner, and it renders
  the explicit effective workdir (`last_workdir`) to show where the session actually ran.
- Session detail now exposes richer deterministic/semantic quickpeek sections and explicit
  workdir metadata for follow-up debugging.

### Fixed

- Session table no longer hides runner provenance when background and origin differ.
- Hook/monitor session surfaces keep project workdir and runner badges aligned after repeated
  project activation and status refresh.

## Monitor 0.6.3

### Changed

- Session list metadata now renders the originating client as an inline badge and adds a
  separate dream-runner badge when the background runner differs from the session origin.
- Session list now prefers `last_workdir` over root install `cwd` for started-path display so
  operators can immediately see the actual project context.

### Fixed

- Session list no longer suppresses active-origin context for Cursor sessions that run with
  a project-bound background runner.

## Backend 0.2.4

### Changed

- Cursor project activation now supports explicit background-runner pinning via
  `cursor-enable --background-runner <codex|claude>` instead of only using
  best-available auto-selection.

### Fixed

- Cursor workspace bindings now persist the selected background runner so
  hook-time session capture, status reporting, and later dream-runner
  resolution all use the same pinned runner.
- Cursor activation now treats a logged-out `codex` or `claude` CLI as not
  ready instead of accepting mere binary presence and failing later during
  dreams or firewall-driven background work.

## Backend 0.2.3

### Changed

- Cursor project activation now requires a separate headless LLM runner
  (`codex` or `claude`) for firewall classification, dreaming, query
  expansion, and other background workflows. Cursor is treated as IDE-side
  hook/session capture rather than the default headless backend.
- Cursor session startup now prefers the available Codex/Claude headless runner
  for dream processing instead of defaulting same-runner background work to
  `cursor`.

### Fixed

- Cursor project activation no longer reports a misleading ready state on
  machines that have Cursor hooks but no valid headless LLM runner.

## Backend 0.2.2

### Added

- Deterministic `--isolated` install mode with target-local runtime storage by
  default, instance-specific wrapper naming, and no takeover of shared
  `agent-context-engine` / `ace` commands.
- Auditable Dream-v2 JSON parse diagnostics including explicit
  `json_parse_error_code` metadata on deterministic semantic and
  reconciliation fallbacks.

### Changed

- Project activation commands now use `--installation-root` as the public flag
  for selecting the owning Agent Context Engine checkout. The older
  `--memory-root` spelling remains accepted there as a compatibility alias but
  is no longer documented as the primary interface.
- Install discovery now ignores foreign repo-local defaults from another
  checkout when proposing runtime storage and wrapper naming for a fresh or
  isolated installation.
- Integration runbooks now require agents to verify project activation with
  real status commands instead of treating `--help` output as verification.

### Fixed

- Cursor workspace bindings now retain the activating installation root, so
  project status checks validate against the correct ACE instance instead of
  incorrectly treating enabled projects as `inactive_missing_target`.
- Cursor project activation status now resolves the bound CLI path more
  defensively across installed and repo-local layouts.
- Structured JSON stages in Dream-v2, monitor query planning, and LLM graph
  parsing now tolerate blank, fenced, and mixed-text outputs more safely and
  fall back conservatively when parsing fails.

## Monitor 0.6.2

### Changed

- Integration cards now count activated project hooks by effective
  `hooks_enabled` state instead of only by a narrow string comparison on
  `hooks_state`.
- Monitor-facing integration semantics and operator guidance now align with the
  new `--installation-root` activation contract and the isolated-install
  workflow.

### Fixed

- Cursor project cards no longer show false `0 of 1 enabled` summaries when
  the project binding points at the correct isolated installation.

## Backend 0.2.1

### Changed

- The public CLI contract now points agents and generated hook guidance to
  `agent-context-engine` from `PATH` instead of repo-local shortcut paths.
- Install discovery and install-plan guidance now treat relinking the shared
  public commands (`agent-context-engine`, `ace`, and `*-ace`) to the chosen
  installation as the default behavior, with isolated naming reserved for
  explicit multi-install setups.

### Fixed

- Antigravity dreaming now uses the current non-interactive
  `agy --model "<model>" -p "<prompt>"` contract instead of stale prompt flags.
- Risk classification now recognizes structured `CommandLine` and
  `AbsolutePath` payloads correctly, so Agent Context Engine CLI calls and
  local reads are classified against the intended allowlist/read heuristics.
- Hook/session command rendering now resolves the active installation more
  deterministically when deciding whether the global `agent-context-engine`
  command can be used directly.

## Monitor 0.6.1

### Changed

- Monitor-facing version metadata now aligns with the new public CLI and
  installation contract release.
- Installation and integration documentation now consistently describe the
  shared global command takeover model and the global `agent-context-engine`
  management path.

## Backend 0.2.0

### Added

- Guided installation that starts with a read-only discovery pass, proposes
  defaults, and requires explicit confirmation before writing files.
- Central per-user installation state under `~/.agent-context-engine/`,
  including user config, instance metadata, monitor runtime registry, and link
  registry.
- Stable default wrapper suffix `-ace` and user shortcut `~/.agent-context-engine/ace`.
- Global-only wrapper support for Codex, Claude, Antigravity, Gemini, and
  OpenCode with install-time linking and explicit conflict handling.
- Installation metadata persistence for install root, memory root, versions,
  launchagent identity, timestamps, and wrapper naming.
- Hook runtime queue visibility and worker status surfaced through monitor/API
  payloads.
- Hook control-plane support for global and per-runner enable/disable state.
- OpenCode plugin bridge hardening for mixed `sessionID` / `sessionId` event
  payloads and more defensive cwd/title/session extraction.

### Changed

- Installation discovery now keeps the current monitor port when the same
  installation is already active, instead of drifting to a higher port.
- Monitor port selection now excludes active entries that share the same memory
  root, while still avoiding real conflicts with other installations.
- Global wrapper conflict detection now accepts installed wrapper targets under
  `docs/skills/agent-context-engine/scripts/` when they belong to the current
  checkout.
- Global-only `opencode-enable`, `gemini-enable`, and `antigravity-enable`
  flows now prepare hooks and bridge files in the installation root rather than
  incorrectly writing them into the shared memory root.
- Standard install now prepares the OpenCode bridge automatically instead of
  only creating the wrapper link.
- Semantic normalization no longer relies on deterministic language mappings
  for German-to-English canonicalization. The LLM prompt now instructs the
  semantic stage to prefer stable English canonical entity names while keeping
  original-language aliases.

### Fixed

- Live installation refreshes that use installed wrapper paths no longer report
  false wrapper conflicts.
- Existing installations no longer propose a wrong monitor port in
  `install-discovery` when the active monitor already belongs to the same
  installation.
- OpenCode wrappers no longer appear ready while the actual plugin bridge file
  is missing from the installation root.
- Stray global-only bridge artifacts written into the shared memory root are no
  longer part of the intended installation model.

## Monitor 0.6.0

### Added

- Persistent `Howto` top-level tab for first-use orientation and install
  deep-linking.
- Visual first-run explanation path for hooks, runners, monitor, memory,
  dreams, and control-plane boundaries.
- Installation/runtime metadata display for install timestamps, update
  timestamps, monitor version, backend version, memory root, runtime registry,
  and link registry.
- Hook queue and worker health visibility in monitor status.

### Changed

- Integrations status now distinguishes runtime readiness, wrapper readiness,
  hook readiness, activation mode, and global command availability more
  explicitly.
- OpenCode, Gemini, and Antigravity are represented as global-only flows with
  clearer wrapper semantics.
- Monitor status payloads now carry richer instance metadata and runtime
  bookkeeping needed to reason about installation drift.

### Fixed

- OpenCode readiness now reflects the actual presence of the plugin bridge in
  the installation root.
- Monitor state now aligns with the active installation when the same monitor
  process is already bound to the configured port.
