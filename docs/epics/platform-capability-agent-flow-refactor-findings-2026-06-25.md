# Findings: Platform Capability And Agent Flow Refactor Baseline

Date: 2026-06-25
Status: baseline findings before implementation work, with closeout addendum
Related epic: `docs/epics/platform-capability-agent-flow-refactor-plan.md`

## Scope Of This Note

This document records the current verified baseline before the next refactor
slice begins. It is intentionally limited to findings that were confirmed in the
repository, without speculative design work.

## Confirmed Product Direction

- `macOS` remains the only active production support path in the current code.
- `Windows` is a native future target, not a WSL-only substitute.
- Native Windows support is not implemented in this slice and must not be
  implied by scaffolding alone.
- `Linux`, `WSL`, and `posix_generic` remain scaffolded or future-facing until
  real runtime evidence exists.

## Verified Current State

### 1. Platform profiles exist, but are not yet wired into runtime policy

The new application boundary and profile model are present:

- `backend/src/agent_context_engine/application/platform/platform.spec.md`
- `backend/src/agent_context_engine/application/platform/profile.py`

The current platform model defines:

- `PlatformFamily`
- `SupportLevel`
- `EvidenceLevel`
- `CapabilityStatus`
- immutable `PlatformProfile` and `PlatformCapability`

Current support mapping is conservative:

- `macos` => `supported` with `tested` evidence
- `linux` => `scaffolded`
- `wsl` => `scaffolded`
- `windows` => `scaffolded`
- `posix_generic` => `scaffolded`
- `unknown` => `unsupported`

However, the new profile model is not yet the active policy layer. At the time
of this baseline, usage is limited to:

- the platform module itself
- characterization tests

No broader runtime path was verified to depend on `current_platform_profile()`
or `platform_profile_for_family()` yet.

### 2. Agent guidance is still rendered from multiple sources

The current agent-facing startup and instruction contract is duplicated across
multiple code paths.

Verified renderers and sources:

- `agents_memory_block(...)` in
  `backend/src/agent_context_engine/interfaces/cli/commands/installation.py`
- `render_session_start_hook_entry(...)` in the same module
- `CLAUDE_ENTRYPOINT` constant in the same module
- `CURSOR_EVERY_CHAT_RULE` constant in the same module
- `_default_startup_entry(...)` in
  `backend/src/agent_context_engine/interfaces/hooks/support/session_context.py`

This means the same conceptual contract is not yet driven by one structured
agent-flow source.

### 3. The current contract already shows drift between renderers

Confirmed differences between the currently rendered startup/instruction texts:

- repository context path differs:
  - install-time startup entry uses `./docs/knowledge/repos.md`
  - hook support default startup entry uses `./memory/knowledge/repos.md`
- monitor runner handling differs:
  - install-time startup entry reads the monitor runner from the installation
    profile
  - hook support default startup entry hard-codes `codex`

This is the clearest existing reason to centralize agent-flow rendering before
expanding platform support work.

### 4. Scheduler boundary exists architecturally, but not yet operationally

`backend/src/agent_context_engine/application/scheduler.spec.md` already says
that LaunchAgent implementation details should not leak into scheduler policy.

But the current application scheduler module still delegates directly to the
LaunchAgent adapter:

- `cmd_install_launchagent(...)`
- `cmd_uninstall_launchagent(...)`
- `cmd_launchagent_status(...)`

in `backend/src/agent_context_engine/application/scheduler.py`

This means the scheduler application boundary exists as intent, but the
macOS-specific scheduler integration is still effectively the active concrete
path.

### 5. LaunchAgent behavior is still a direct macOS implementation path

The LaunchAgent adapter remains explicitly macOS-specific and directly handles:

- plist rendering
- `~/Library/LaunchAgents`
- `launchctl` load/status operations
- launch environment wiring

Verified source:

- `backend/src/agent_context_engine/adapters/launchagent.py`

Additional direct LaunchAgent handling also exists in installation flow logic,
for example when stopping superseded LaunchAgents that share the same memory
root.

### 6. Wrapper and hook rendering are still Bash/POSIX-first

The current integration and installation paths still assume a Bash/POSIX shell
environment.

Verified characteristics:

- hook templates use `#!/usr/bin/env bash`
- generated wrappers use Bash shell scripts
- temporary files rely on `mktemp`
- executability is applied via `chmod(0o755)`
- several publication and active-instance flows rely on symlinks

Verified source areas:

- `templates/*/hook_adapter.sh`
- `backend/src/agent_context_engine/interfaces/cli/commands/installation.py`
- `backend/src/agent_context_engine/application/integrations.py`
- `backend/src/agent_context_engine/application/instance_profile.py`

This is compatible with the current macOS production path, but it is not yet a
generalized cross-platform contract.

### 7. Integration management includes a second rendering path

Platform- and shell-sensitive hook logic is not limited to installation code.

`backend/src/agent_context_engine/application/integrations.py` also renders and
manages integration scripts and hook state, including:

- shell hook adapter preparation for `codex`, `claude`, and `gemini`
- Cursor hook wrapper rendering
- Antigravity hook preparation
- status evaluation for prepared, disabled, and effective hook states

This is important because future renderer extraction must account for both:

- install-time generation
- integration-management generation

### 8. Installation profile still contains a legacy platform field

The installation profile default still contains:

- `"platform": "mac"`

Verified source:

- `backend/src/agent_context_engine/application/instance_profile.py`

That field does not yet reflect the new platform capability model and is a
likely migration point in a later slice.

### 9. Documentation and runbooks still describe the current runtime truth

The maintained docs are consistent with the codebase being production-active on
the current macOS-oriented path:

- `docs/setup/RUNNER_HARNESSES.md`
- `docs/runbooks/integration-management.md`

They also confirm important integration behavior that the refactor must
preserve, including:

- project activation requirements for Cursor
- global-only mode for Antigravity, Gemini, and OpenCode
- separation between GUI hook preparation and headless CLI readiness

### 10. Current tests protect only part of the intended contract

Verified characterization coverage currently exists for:

- `AGENTS.md` quick-path block
- `session-start-hook-entry.md`
- scaffolded future platform profiles

Verified tests:

- `test_agent_guidance_block_matches_current_contract`
- `test_session_start_entry_matches_current_contract`
- `test_platform_profiles_keep_future_platforms_scaffolded`

Not yet verified by equivalent golden or characterization coverage in this
baseline:

- `CLAUDE.md`
- Cursor `everyChat.mdc`
- hook adapter script output
- wrapper script output
- LaunchAgent plist output
- explicit degraded or unsupported platform diagnostics text

## Implications For The Next Refactor Slice

Based on the verified baseline, the safest next implementation order is:

1. Introduce one structured agent-flow contract and a single rendering path.
2. Move all instruction targets onto that contract while preserving current
   macOS-visible output.
3. Only then extract wrapper, hook-adapter, scheduler, and command-publication
   rendering behind explicit capability-aware boundaries.

Reason:

- the largest current source of drift is duplicated instruction rendering
- the new platform profile model is present but not yet the active policy layer
- the scheduler and wrapper paths are still strongly coupled to direct
  macOS/POSIX implementations

## Explicit Non-Claims

This note does not claim:

- native Linux runtime support
- native WSL runtime support
- native Windows runtime support

## Closeout Addendum: Verified Runtime Drift During Implementation

During implementation verification, one additional concrete drift was confirmed
outside the original baseline scope:

- the public `dream` CLI used `--runner same-as-session` by default, but
  separately defaulted `--graph-runner` to `codex`
- for deterministic dream runs, that mismatch caused the persistence stage to
  invoke Codex-backed graph materialization and wait for a deterministic-fallback
  path instead of staying fully deterministic end to end
- the visible symptom was an unnecessary ~30 second delay in
  `test_hook_summary_dream_context_flow`, even though the actual dream narrative,
  semantic extraction, and reconciliation stages stayed deterministic

This is another example of why renderer/runtime defaults need to be unified at
the command-contract boundary instead of being allowed to drift across adjacent
subsystems.
- support-level promotion beyond the currently scaffolded state

It also does not change the requirement that support claims above `scaffolded`
need real runtime evidence.

## Closeout Addendum After Implementation

The implementation work for this epic confirmed one additional runtime-policy
finding that was not yet enforced in the original baseline:

- scaffolded or unsupported non-macOS profiles must not silently fall through
  to active macOS/POSIX runtime adapters for publication, system-open, process
  launch, workspace binding, executable permission handling, or wrapper/hook
  activation

That rule is now enforced in the runtime-selection boundary:

- `backend/src/agent_context_engine/application/platform/runtime_selection.py`

This means the repository now distinguishes more clearly between:

- metadata/render visibility for future platforms
- real runtime activation for the current supported platform

The product direction remains unchanged:

- `macOS` is the active supported runtime path
- native `Windows` remains a real target, but not runtime-enabled in this slice
- `Linux`, `WSL`, and `posix_generic` remain scaffolded until real evidence
  exists
