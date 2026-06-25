# Spec: Wrapper Publication Application Boundary

## Purpose

Represent wrapper command naming, wrapper script resolution, and symlink-based
command publication behind one application boundary so installation code no
longer hard-codes these publication rules inline.

## Scope

- Wrapper command name rendering from prefix/suffix policy.
- Wrapper script path resolution inside an installation root.
- Symlink-based command publication and removal for the current active path.

## Non-Scope

- Alternative publication mechanisms for non-symlink platforms.
- CLI install flow, approval flow, or registry persistence policy.
- Wrapper script content rendering itself.

## Responsibilities

- Keep naming and publication behavior deterministic.
- Preserve the current symlink-based publication strategy.
- Make unsupported wrapper names fail explicitly.

## Inputs / Outputs

- Inputs: base wrapper name, prefix/suffix, installation root, target link path.
- Outputs: resolved command names, resolved script paths, created/removed links.

## Dependencies / Ports

- May depend on filesystem symlink semantics for the active implementation.
- Must not decide platform support claims by itself.

## Failure Modes

- Unsupported wrapper names fail explicitly.
- Existing conflicting link paths fail unless replacement is allowed.
- Non-symlink directories are never replaced silently.

## Acceptance Criteria

- Installation and instance-profile naming use the same command-name renderer.
- Installation link creation uses the centralized symlink publisher.
- Current macOS-visible global wrapper behavior remains unchanged.

## Tests / Checks

- `python3 tests/test_agent_context_engine.py`

## Agent Guardrails

- Do not duplicate wrapper naming logic in separate modules when the centralized
  publisher boundary can provide it.
- Do not treat the current symlink-based publisher as proof of broader platform
  support.
