# Spec: Ports Boundary

## Purpose
Define explicit protocol-style boundaries that let application services depend
on stable capabilities instead of concrete infrastructure details.

## Scope
- Clock, filesystem, repository, and runner command protocols.
- Small shared abstractions used by application services.
- Platform-adjacent capability ports such as process launch, workspace binding,
  executable permissions, and path quoting.
- Platform-detection and runtime-capability ports used to materialize the
  current host capability matrix.

## Non-Scope
- Concrete SQLite, LaunchAgent, Neo4j, or runner implementations.
- Business orchestration.
- CLI/HTTP formatting.

## Responsibilities
- Keep port interfaces small and named after capabilities.
- Avoid leaking implementation-specific details into application code.
- Make future adapter swaps testable.

## Inputs / Outputs
- Inputs: application-level requests expressed as protocol calls.
- Outputs: typed or simple results suitable for application decisions.

## Dependencies / Ports
- Protocol/type definitions may reference domain or application DTOs only when
  that improves clarity and avoids adapter leakage.

## Failure Modes
- Port contracts should make retryable vs hard failures representable where the
  application must decide.

## Acceptance Criteria
- New infrastructure dependencies get a port when used by shared application
  behavior.
- Ports do not import concrete adapter modules.
- Tests can provide in-memory or fake implementations.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not turn ports into service locators.
- Do not add wide protocols for one-off helper calls.
