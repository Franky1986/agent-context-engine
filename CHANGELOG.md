# Changelog

All notable changes to Agent Context Engine are documented in this file.

This repository currently has one public baseline commit:

- `0.1.3` backend / product
- `0.5.7` monitor

The entries below document the changes added since that initial public release.

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
