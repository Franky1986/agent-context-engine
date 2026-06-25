# Spec: Graphing Engine Boundary

## Purpose
Implement graph extraction, LLM structuring, schema validation, materialization,
and candidate matching behind graph application adapters.

## Scope
- Prompt/schema handling for semantic graph proposals.
- Materialization of graph entities, relations, evidence, and artifacts.
- Candidate extraction and reconciliation support.

## Non-Scope
- CLI command parsing.
- HTTP route handling.
- Product decisions about when a graph run should execute.

## Responsibilities
- Validate generated graph patches before persistence.
- Tolerate fenced, prefixed, or trailing-text JSON responses from runners as
  long as a single valid JSON object can be extracted deterministically.
- Keep deterministic fallback paths available for graph extraction.
- Preserve evidence links and confidence data.

## Inputs / Outputs
- Inputs: session content, dream artifacts, schema definitions, runner output.
- Outputs: graph patches, materialized rows, artifact metadata, candidate rows.

## Dependencies / Ports
- SQLite graph storage via adapters/infrastructure.
- Runner output supplied by application orchestration.
- Graph schema and domain constraints.

## Failure Modes
- Blank or structurally invalid LLM output returns an invalid-output status with
  a reviewable parser error instead of silently materializing partial data.
- Schema violations produce reviewable errors instead of partial writes.
- Duplicate/ambiguous candidates remain candidates until reconciled.

## Observability / Audit
- Every materialized artifact must retain source path or run correlation.
- Invalid outputs should be inspectable after failure.

## Acceptance Criteria
- Materialization is idempotent where practical.
- Evidence and confidence fields survive extraction and persistence.
- Candidate queries do not directly depend on Neo4j implementation details.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not put CLI/HTTP behavior here.
- Do not bypass graph application ports for user-facing commands.
