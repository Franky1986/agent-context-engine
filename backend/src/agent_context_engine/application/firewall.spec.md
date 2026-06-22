# Spec: Firewall Application Boundary

## Purpose
Apply local safety policy, overrides, taint state, and audit rules before risky
memory or tool actions proceed.

## Scope
- Firewall state evaluation.
- Override matching and expiration.
- Audit event creation for policy decisions.

## Non-Scope
- Classifier prompt implementation.
- User-only chat control execution.
- UI-specific presentation.

## Responsibilities
- Keep user-only controls explicit and auditable.
- Prevent stale legacy v1 firewall data from changing active policy.
- Separate policy decisions from transport formatting.

## Inputs / Outputs
- Inputs: action metadata, risk events, override requests, current time.
- Outputs: allow/block/review decisions, audit rows, override state.

## Dependencies / Ports
- SQLite firewall adapter.
- Risk application/domain models.
- Clock/time source.

## Failure Modes
- Expired overrides are ignored and auditable.
- Invalid override requests fail closed.
- Missing state defaults to safe policy behavior.

## Observability / Audit
- Every override create/revoke path writes audit evidence.
- Blocked or tainted decisions must be explainable through risk ids.

## Acceptance Criteria
- Existing risk/firewall CLI behavior remains stable.
- Overrides cannot silently bypass audit.
- Active policy excludes archived v1-only state.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not execute user-only control messages as tools.
- Do not weaken block behavior without contract and test updates.
