# Spec: Wrapper Publication Application Boundary

## Purpose

Represent wrapper command naming and wrapper script resolution behind one
application boundary so installation code no longer hard-codes these rules
inline.

## Scope

- Wrapper command name rendering from prefix/suffix policy.
- Wrapper script path resolution inside an installation root.
- Wrapper publication policy inputs for the current active path.
- Wrapper root ownership after publication: canonical shared symlinks follow
  shared takeover state, while direct and instance-named wrappers stay pinned
  to their owning installation.

## Non-Scope

- Alternative publication mechanisms for non-symlink platforms.
- CLI install flow, approval flow, or registry persistence policy.
- Wrapper script content rendering itself.

## Responsibilities

- Keep naming and wrapper-path resolution deterministic.
- Leave concrete filesystem publication mutation to adapters.
- Make unsupported wrapper names fail explicitly.

## Inputs / Outputs

- Inputs: base wrapper name, prefix/suffix, installation root, target wrapper name.
- Outputs: resolved command names and resolved script paths.

## Dependencies / Ports

- Must not mutate filesystem publication targets directly.
- Must not decide platform support claims by itself.

## Failure Modes

- Unsupported wrapper names fail explicitly.
- Unsupported wrapper names fail explicitly and deterministically.

## Acceptance Criteria

- Installation and instance-profile naming use the same command-name renderer.
- Installation link creation uses a dedicated publication adapter.
- Canonical shared macOS wrapper symlinks continue to follow the shared
  `active-root`; instance-named symlinks execute their own installation even
  when a different shared installation is active.

## Tests / Checks

- `python3 tests/test_agent_context_engine.py`

## Agent Guardrails

- Do not duplicate wrapper naming logic in separate modules when the centralized
  publisher boundary can provide it.
- Do not treat the current symlink-based publisher as proof of broader platform
  support.
