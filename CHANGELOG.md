# Changelog

All notable changes to Agent Context Engine are documented in this file.

This repository currently has one public baseline commit:

- `0.1.3` backend / product
- `0.5.7` monitor

The entries below document the changes added since that initial public release.

## Unreleased

- no unreleased entries currently

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

- Antigravity dreaming now uses the current non-interactive `agy --print`
  contract instead of stale prompt flags.
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
