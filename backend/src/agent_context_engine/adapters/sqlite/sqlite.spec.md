# Spec: SQLite Adapter Boundary

## Purpose
Own SQLite persistence details for operational memory, scheduler state, risk,
firewall, dream queue, summaries, graph data, and request-local monitor reads.

## Scope
- SQL statements, row mapping, schema migration helpers, and repository-like
  adapter functions.

## Non-Scope
- Domain policy decisions.
- CLI/HTTP formatting.
- Runner invocation.

## Responsibilities
- Keep SQL localized and explicit.
- Return stable data shapes to application services.
- Preserve migration compatibility for existing local databases.

## Inputs / Outputs
- Inputs: application-level persistence requests and connection/context data.
- Outputs: rows, ids, counts, status updates, mapped records.

## Dependencies / Ports
- SQLite database under the local `memory/` runtime tree.
- Infrastructure DB connection helpers.

## Failure Modes
- Busy/locked errors must remain distinguishable for retry policy.
- Missing/old schema is handled through migrations where supported.
- Partial writes should be avoided or transaction-bound.

## Observability / Audit
- Mutating risk, firewall, dream, scheduler, and retrieval operations must keep
  audit-ready fields.

## Acceptance Criteria
- Application modules do not need inline SQL for migrated concerns.
- Existing databases remain readable after schema updates.
- Adapter failures do not masquerade as successful application actions.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not import interface modules from adapters.
- Do not encode business policy in SQL helpers.
