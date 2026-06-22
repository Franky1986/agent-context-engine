# Spec: Graph Application Boundary

## Purpose
Expose stable graph use cases for extraction, validation, materialization,
query, quality checks, repair, and optional sync.

## Scope
- CLI-facing graph commands and internal graph application ports.
- Domain object use for graph artifacts, quality, query, and repair flows.

## Non-Scope
- Low-level SQLite schema implementation.
- Direct HTTP response shaping.
- LLM graph extraction internals owned by `application/graphing`.

## Responsibilities
- Keep graph commands behavior-compatible: exit codes, failure names, and
  required output fields.
- Convert graphing/storage outputs into application-level results.
- Isolate optional Neo4j sync behind application ports.

## Inputs / Outputs
- Inputs: session ids, dream run ids, graph patch paths, query text, type/limit
  options.
- Outputs: graph artifacts, materialization status, query rows, quality reports,
  repair status.

## Dependencies / Ports
- `application/graphing` for extraction/materialization internals.
- `domain/graph.py` for value objects.
- SQLite graph repositories.
- Optional Neo4j adapter through sync ports.

## Failure Modes
- Invalid patches fail as `invalid_graph_patch`.
- Missing query entities fail without tracebacks.
- Optional Neo4j failures must not corrupt core graph state.

## Observability / Audit
- Graph artifacts need status, entity/relation/evidence counts, and source
  correlation.
- Repair operations must be traceable back to the dream run or patch.

## Acceptance Criteria
- `graph-status`, `graph-quality`, and `graph-query` remain stable.
- Graph repair can create missing patches for v2 dream runs.
- No interface layer owns graph business decisions.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/agent-context-engine graph-status`
- `./scripts/agent-context-engine graph-quality`

## Agent Guardrails
- Do not import HTTP/CLI modules here.
- Keep direct adapter access behind graph application functions.
