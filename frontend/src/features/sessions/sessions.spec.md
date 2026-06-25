# Spec: Monitor Sessions Feature

## Purpose
Show recent sessions and selected session detail so operators can inspect agent
activity, status, and handover context.

## Scope
- Session list panel.
- Session detail panel.
- Loading, empty, and error states.
- Session-level risk/block visibility for operator triage.

## Non-Scope
- Transcript ingestion.
- Session summarization logic.
- Risk or graph policy decisions themselves.

## Responsibilities
- Use shared API functions and generated/shared types.
- Keep detail selection stable while list data refreshes.
- Preserve identifiers and status fields needed for CLI cross-checking.
- Route list/detail copy through the shared frontend i18n catalog instead of
  panel-local bilingual helpers.
- Present sessions as the primary daily operator entry point.
- Prefer a summary-first detail view with drilldown into dreams, semantically
  derived results, timeline, and raw payloads.
- Surface a short last-activity description in the list without requiring a
  detail click.
- Surface session-local risk posture in list and detail views: open blocked
  items, pending approvals, taint state, recent risk reason, and drilldown into
  the related risk-event chain.
- Refresh selected-session base data in the background so new blocked actions
  and approvals become visible without a full monitor reload.
- Split token presentation consistently between normal session usage and dream
  usage instead of collapsing everything into one aggregate monitor cell.

## Inputs / Outputs
- Inputs: `/api/sessions`, `/api/session`.
- Outputs: session list, selected session details, visible errors/loading
  state, structured risk/block summaries suitable for operator action, and
  explicit session-vs-dream token totals in list and detail.

## Failure Modes
- Unknown or missing session id renders a controlled not-found/error state.
- Empty session list renders an empty state.

## Acceptance Criteria
- Session list/detail stories cover common states.
- Build passes with generated API types.
- UI does not infer hidden backend status from presentation-only labels.
- The upper detail area exposes current handover/summary, latest dream summary,
  and compact deterministic/semantic counts before deeper raw inspection.
- Primary session navigation actions for dreams, knowledge, and control are
  placed in the upper detail area before deeper inspection blocks so operators
  can pivot out of the session quickly without scrolling through raw detail.
- The session list shows compact risk posture without requiring a detail click.
- The session detail view contains a dedicated Risk & Blocks section with open
  items, taint sources, and copyable control-line references from backend data.
- Newly created blocked actions appear in session detail shortly after they are
  written, without requiring a hard page reload.
- The session table shows separate `Session` and `Dream` token columns.
- The session list shows the origin client as a visible badge and also shows a
  separate dream-runner badge when background dreaming is routed through a
  different runner than the originating client.
- The session list prefers the effective session workdir (`last_workdir`)
  over the installation/root cwd so project-local runs remain visible without
  opening session detail.
- The compact session meta line renders the originating client as a badge in
  place, instead of burying it as plain delimiter text.
- The session detail surface shows explicit session token totals and dream
  token totals without requiring the operator to infer dream totals from the
  currently loaded dream list.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/sessions`.

## Agent Guardrails
- Do not implement session mutation here unless backend contracts exist.
- Do not hardcode local private paths in stories.
