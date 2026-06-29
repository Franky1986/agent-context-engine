# Spec: Session Handover Application Boundary

## Purpose
Render a continuation-ready handover for a recorded session so a fresh agent can
resume work with the best available local context.

## Scope
- `handover`, `context`, and resume-oriented session rendering.
- Selection and display of session summary, dream brief, project memory, and
  recent timeline context.
- Runtime-path resolution for summary and dream artifacts stored under the
  active memory root.

## Non-Scope
- Dream generation itself.
- Monitor UI rendering.
- Retrieval indexing internals.

## Responsibilities
- Prefer the best locally available short brief for session continuation.
- Make the active summary source explicit instead of implying a fixed
  deterministic-only source.
- Keep handover output usable when runtime memory is stored outside the repo
  checkout.
- Avoid redundant artifact dumps when the same file is exposed through multiple
  handover paths.

## Inputs / Outputs
- Inputs: session id/selector, summary rows, dream runs, AGENTS.md, retrieval
  results, and timeline events.
- Outputs: markdown handover text for CLI continuation flows.

## Failure Modes
- Missing summary files fall back to dream-derived summary resolution when
  possible.
- Missing dream memory should not suppress a valid current session summary.
- External-memory absolute paths must not be rejected just because they live
  outside the repo root.

## Acceptance Criteria
- `agent-context-engine handover` surfaces a concise session brief when dream
  memory contains `Startup Brief` or `Compact Summary`.
- The handover output exposes the active `summary_kind`.
- Current session summary and latest dream memory remain separately readable
  when they are distinct artifacts.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `python3 scripts/update_docs_index.py --check`
