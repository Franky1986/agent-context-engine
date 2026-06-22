# Spec: Retrieval Application Boundary

## Purpose
Provide traceable memory lookup for agents and humans across indexed sessions,
documents, summaries, and graph-conditioned context.

## Scope
- Query normalization, intent handling, optional expansion, retrieval assembly,
  risk-aware filtering, result ranking, and audit logging.
- CLI and HTTP callers may format output, but they must not make retrieval
  policy decisions.

## Non-Scope
- Raw transcript ingestion.
- Graph materialization.
- UI rendering.

## Responsibilities
- Preserve deterministic fallback behavior for `off` and `deterministic` query
  expansion modes.
- Expand semantic-entity matches into traceable session, dream, and relation
  context using canonical semantic projection data and mutation history.
- Record `retrieval_runs`, `retrieval_results`, and `memory_access_log`
  consistently.
- Keep provenance attached to every returned result where available.

## Inputs / Outputs
- Inputs: query string, limits, filters, expansion mode, caller context.
- Outputs: ranked retrieval results, run metadata, status/failure details.

## Dependencies / Ports
- SQLite retrieval/index repositories.
- Query expansion strategy.
- Risk/classifier checks for returned context.
- Graph conditioning where available.

## Failure Modes
- Empty query returns a controlled no-result response.
- LLM expansion failure falls back to deterministic behavior.
- Storage errors are surfaced as failed retrieval runs, not silent partial
  success.

## Observability / Audit
- Every interface retrieval should be attributable to a retrieval run id.
- Results must keep score and provenance data suitable for later review.

## Acceptance Criteria
- `retrieve`, `retrieval-runs`, and `retrieval-run` remain CLI-compatible.
- Standard deterministic retrieval works without network or LLM access.
- Risk-filtered results are explainable through stored metadata.
- Entity-centered retrieval can expose cross-session context for canonical
  semantic entities without duplicating the same entity result.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not add direct CLI, HTTP, or HTML dependencies to this boundary.
- Do not persist raw tool outputs as retrieval content.
