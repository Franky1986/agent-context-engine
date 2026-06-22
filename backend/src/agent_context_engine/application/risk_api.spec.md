# Spec: Risk Review Application Boundary

## Purpose
Provide shared application behavior for reviewing, approving, rejecting, and
explaining risk events from CLI and HTTP interfaces.

## Scope
- Risk review actions.
- Risk detail/list read models needed by interfaces.
- Consistent status transitions and audit output.

## Non-Scope
- Classifier model execution internals.
- Frontend layout.
- Raw tool output persistence.

## Responsibilities
- Keep CLI and HTTP risk review behavior equivalent.
- Preserve invalid classifier output as auditable evidence.
- Avoid policy drift between list/detail/review paths.

## Inputs / Outputs
- Inputs: risk event ids, review action, reviewer context, optional notes.
- Outputs: updated risk status, audit record, read-model payload.

## Dependencies / Ports
- Risk domain models.
- SQLite risk/firewall repositories.
- Classifier result metadata.

## Failure Modes
- Unknown risk ids return controlled not-found failures.
- Invalid review actions fail without state mutation.
- Storage failures do not report successful review.

## Observability / Audit
- Review actions must produce durable audit records.
- Invalid classifier output remains distinguishable from runner errors.

## Acceptance Criteria
- CLI `risk review` and monitor review paths use the same application behavior.
- Risk list/detail outputs keep required fields.
- Rejected/approved events do not disappear from audit history.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not fork CLI and HTTP review rules.
- Do not rewrite historical risk evidence.
