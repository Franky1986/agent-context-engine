# Spec: Runner Adapter Boundary

## Purpose
Integrate external coding-agent runners such as Codex, Claude, Cursor,
Antigravity, Gemini, and Opencode for
Dream, classifier, and graph-related execution where configured.

## Scope
- Command construction, availability checks, timeout handling, environment
  mapping, and raw process execution wrappers.

## Non-Scope
- Deciding when a dream or classifier should run.
- Parsing business semantics from model output.
- CLI user-facing command behavior.

## Responsibilities
- Keep runner-specific behavior isolated by adapter.
- Surface timeout, missing runner, retry exhaustion, and invalid output causes
  distinctly to application services.
- Preserve deterministic fallback compatibility.
- Keep provider- and client-specific command contracts explicit when a runner is
  only best-effort validated locally, such as newly introduced CLI families.
- Support runner metadata contracts that depend on native resume/session
  semantics instead of leaving that to ad hoc client payload behavior.

## Inputs / Outputs
- Inputs: runner name, prompt/input payload, model/config options, timeout.
- Outputs: process result, stdout/stderr metadata, execution status.

## Dependencies / Ports
- Local runner executables and environment configuration.
- Infrastructure config.

## Failure Modes
- Missing executable returns a missing-runner status.
- Timeout returns timeout status without orphaning application state.
- Non-zero exit is passed back with enough metadata for audit.
- Weak or partially validated runner families must expose confidence gaps
  explicitly, for example:
  - `antigravity` headless prompt contract pending local runtime validation
  - `opencode` interactive/default model contract differing from dream model

## Observability / Audit
- Application services must be able to record runner, model, timeout, and
  failure class.
- Session management must be able to derive or preserve native resume commands
  where the runner family supports stable session continuation semantics.
- Session management may backfill token usage from native runner artifacts when
  the hook payload does not carry usage directly, but the source contract must
  stay explicit:
  - `opencode`: local message-store records with native token counters
  - `antigravity`: transcript-based estimate until a stable native usage record
    is decoded and validated
  - `cursor`: Dream-/graph-stage JSON envelopes may carry native usage under
    runner-specific field names; adapter/application parsing must treat this as
    a first-class source instead of silently degrading to fake zeros

## Acceptance Criteria
- Runner adapters remain swappable behind application policy.
- No runner adapter writes memory state directly.
- Same-as-session and deterministic modes remain distinguishable.
- Runtime confidence gaps for a runner must be documented explicitly instead of
  being hidden behind a generic "ready" claim.
- Runner families with different normal/dream model roles remain expressible
  without collapsing into one implicit model field.
- If a runner family cannot provide native token usage for normal sessions yet,
  Agent Memory must not silently persist misleading fake zeros as if they were
  measured usage.
- If a runner returns usage in a family-specific envelope or casing variant,
  the adapter boundary must normalize that explicitly and preserve whether
  usage was actually available.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not call these adapters directly from HTTP/CLI route handlers.
- Do not persist full raw model/tool output unless a contract explicitly allows it.
