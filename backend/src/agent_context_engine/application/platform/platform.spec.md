# Spec: Platform Capability Application Boundary

## Purpose

Represent host-platform support, runtime capabilities, and evidence levels in
application terms so installation, wrappers, scheduler setup, diagnostics, and
agent guidance can depend on explicit capabilities instead of hard-coded OS
assumptions.

## Scope

- Platform family classification.
- Support-level and evidence-level metadata.
- Runtime capability descriptors.
- Runtime capability matrix materialization for the current host token.
- Scaffolded, experimental, and unsupported platform profiles for future adapters.
- Runtime selection for renderer, publisher, executable-permission, and
  path-quoting strategies.

## Non-Scope

- Concrete LaunchAgent, systemd, cron, Windows Task Scheduler, shell, or symlink
  implementation details.
- Production support claims for non-macOS platforms without runtime evidence.
- Automatic enablement of scaffolded platform adapters.

## Responsibilities

- Keep platform support claims explicit and conservative.
- Distinguish operating-system identity from runtime capability availability.
- Make scaffolded platform work visible without claiming production support.
- Provide stable data for diagnostics and future instruction renderers.
- Keep runtime selection conservative so scaffolded or unsupported profiles pick
  scaffolded/non-mutating adapters instead of silently falling through to the
  active macOS/POSIX runtime path.

## Inputs / Outputs

- Inputs: current host platform or an explicitly requested platform family.
- Outputs: immutable platform profile with support/evidence metadata and named
  capability statuses.
- Outputs may also include a runtime capability matrix payload for diagnostics
  and monitor visibility.

## Dependencies / Ports

- May use Python host-platform detection for initial classification.
- Must not import concrete OS adapters outside the runtime-selection boundary.

## Failure Modes

- Unknown platforms resolve to an explicit unsupported profile.
- Scaffolded profiles must report disabled runtime capabilities.
- Capabilities based on static knowledge must not report `tested` evidence.
- Scaffolded or unsupported profiles must not select mutation-capable command
  publication, scheduler, or shell-runtime adapters as if they were active.
- Host-specific PID probing failures, including Windows `os.kill(pid, 0)`
  `SystemError` cases, must be treated as non-live process evidence instead of
  breaking monitor status payload generation.
- Monitor status must not block on external runner authentication or model
  discovery. The fast status path may report installed-but-not-probed readiness;
  explicit integration checks can still run full external probes.

## Acceptance Criteria

- macOS resolves to the current production profile.
- Linux, WSL, Windows, and generic POSIX can be represented without falling
  through to macOS behavior.
- Windows may expose an explicit `experimental` runtime path through dedicated
  adapters without being marked `supported`.
- Future adapters can attach to these profiles through ports instead of changing
  application policy code.
- Shell-path quoting and executable-permission behavior are selected through
  explicit platform adapters instead of inline `sh_quote` / `chmod` policy.
- Windows `.cmd` command shims for Python entrypoints prefer
  `AGENT_CONTEXT_ENGINE_PYTHON`, then `AGENT_MEMORY_PYTHON`, then the
  installation-local `.venv\Scripts\python.exe`, before falling back to PATH
  Python. This keeps global commands aligned with the runtime bootstrap used by
  the monitor and diagnostics.
- Runtime selection for scaffolded/unsupported profiles stays explicit about
  support/evidence and defaults to non-active adapter behavior.

## Tests / Checks

- `python3 tests/test_agent_context_engine.py`
- `python3 scripts/update_docs_index.py --check`

## Agent Guardrails

- Do not mark a platform as `supported` without real runtime evidence.
- Do not let scaffolded profiles run scheduler or command-publication mutation
  paths by default.
- Do not mark Windows as `supported` until real Windows runtime evidence exists.
