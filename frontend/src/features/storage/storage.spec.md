# Spec: Monitor Storage Feature

## Purpose
Show storage/runtime footprint information so operators can understand local
memory, graph, database, and artifact state.

## Scope
- Storage panel.
- Runtime storage summaries and relevant warnings.
- Loading, empty, and error states.

## Non-Scope
- Prune/purge execution.
- Raw database browsing.
- File-system mutations.

## Responsibilities
- Present storage status from backend read models.
- Keep potentially large values scannable.
- Avoid adding client-side cleanup behavior.
- Prefer an operations-oriented reading order: warnings and key footprint first,
  deeper runtime/file details second.

## Inputs / Outputs
- Inputs: `/api/storage`.
- Outputs: storage status UI, warning indicators, errors.

## Failure Modes
- Missing storage sections render as unknown/empty.
- API failure does not hide the panel silently.

## Acceptance Criteria
- Storage stories cover populated and degraded states.
- Build passes with generated API types.
- No destructive action appears without explicit backend contract and audit path.
- The top of the panel provides a quick operational read on warnings, category
  count, database footprint, and major runtime paths.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/storage`.

## Agent Guardrails
- Do not add direct filesystem access to frontend code.
- Do not add cleanup buttons without risk/audit design.
