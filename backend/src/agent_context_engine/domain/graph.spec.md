# Spec: Graph Domain Boundary

## Purpose
Define graph value objects, invariants, and quality/result shapes without
depending on persistence, runners, CLI, or HTTP.

## Scope
- Graph artifacts, entities, relations, evidence links, quality evaluations,
  curated context, and query assessments.
- Domain-level validation helpers that are independent of storage.

## Non-Scope
- SQLite materialization.
- LLM extraction.
- CLI/monitor output formatting.

## Responsibilities
- Keep graph confidence, relation, evidence, and status invariants explicit.
- Provide typed structures that application code can use instead of raw rows.
- Avoid importing project config or infrastructure.

## Inputs / Outputs
- Inputs: primitive data from application/adapters.
- Outputs: domain objects and derived quality/status values.

## Dependencies / Ports
- Standard library only, unless a small local domain dependency is justified.

## Failure Modes
- Invalid domain construction should fail early and close to the boundary.
- Ambiguous or incomplete graph evidence remains representable without being
  promoted to a confirmed fact.

## Acceptance Criteria
- Domain objects can be used in tests without a database.
- No infrastructure, interface, runner, or config imports appear here.
- Application graph use cases can serialize/format these objects explicitly.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not add persistence or transport behavior to domain modules.
- Do not hide graph quality uncertainty by coercing it into success.
