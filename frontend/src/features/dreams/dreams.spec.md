# Spec: Monitor Dreams Feature

## Purpose
Expose Dream v2 runs, stages, artifacts, failures, and graph repair context for
operator inspection.

## Scope
- Dream run list.
- Dream artifacts/evaluation panel.
- Stage and failure presentation for v2 runs.

## Non-Scope
- Running dream jobs directly.
- Legacy v1 runtime behavior.
- Graph materialization rules.

## Responsibilities
- Render v2 stage state clearly and compactly.
- Keep failed/invalid artifacts visible for audit.
- Use shared API client/types.
- Keep operator-facing summary, pending, and drilldown copy in the shared
  frontend i18n catalog.
- Present each selected dream with a compact executive summary before deeper
  artifact inspection.
- Expose deterministic versus semantic outcomes distinctly enough that an
  operator can understand the effect of a dream run in seconds.

## Inputs / Outputs
- Inputs: `/api/dreams`, `/api/dream-v2-evaluate`, `/api/dream-graph`.
- Outputs: dream list/detail UI state, artifact summaries, failure messages.

## Failure Modes
- Missing artifacts show an empty/recoverable state.
- Invalid outputs are displayed as audit evidence, not hidden.
- Dream artifacts stored under an external runtime memory root must still load
  when persisted paths are absolute rather than repo-relative.
- Handover detection in the dream detail follows the current v2 prompt contract,
  including `## Current Deterministic Handover`.

## Acceptance Criteria
- Stories cover successful, failed, and artifact-heavy states.
- Build passes with generated API types.
- UI labels do not mix v1 and v2 semantics.
- A selected dream exposes status, short outcome summary, deterministic and
  semantic counts, and quick navigation to session/knowledge/control before raw
  artifacts dominate the screen.
- Dream inspect continues to show narrative, prompt, audit, and stage artifact
  content when the active installation stores runtime memory outside the repo
  checkout.
- The dream detail handover badge reflects current v2 prompt headings instead of
  assuming the older `Current Session Handover` label only.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/dreams`.

## Agent Guardrails
- Do not add UI controls that mutate dream state unless backend contracts exist.
