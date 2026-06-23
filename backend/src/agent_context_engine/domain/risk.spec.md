# Spec: Risk Domain Boundary

## Purpose
Define risk decisions, events, policies, and override concepts used by the
firewall, retrieval safety, classifier, and review flows.

## Scope
- Risk domain types and deterministic policy merge/validation behavior.
- Representation of classifier output validity and policy outcome semantics.

## Non-Scope
- Risk event persistence.
- CLI/HTTP review actions.
- Runner execution and retry policy.

## Responsibilities
- Keep risk decision semantics stable and auditable.
- Distinguish invalid classifier output from runner errors or deterministic
  fallback decisions.
- Avoid direct runtime database access.
- Normalize structured tool-input variants consistently enough that CLI
  allowlists and local-read heuristics continue to apply across casing and
  payload-shape differences.

## Inputs / Outputs
- Inputs: normalized classifier/policy payloads and risk metadata.
- Outputs: risk decisions, policy classifications, validation results.

## Dependencies / Ports
- Standard library and pure local domain helpers only.

## Failure Modes
- Invalid classifier JSON remains explicitly invalid.
- Missing or malformed risk metadata should not silently become allow.

## Acceptance Criteria
- Domain behavior can be unit-tested without runtime state.
- Active firewall/risk APIs can explain every block/review/allow decision.
- Legacy v1-only risk state is not mixed into active domain decisions.
- Structured tool payloads such as `CommandLine` and `AbsolutePath` are mapped
  consistently so equivalent operations do not bypass or miss the intended risk
  policy path.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not write risk audit rows from domain code.
- Do not loosen default safety behavior without updating contracts and tests.
