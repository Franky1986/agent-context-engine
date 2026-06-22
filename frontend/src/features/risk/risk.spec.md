# Spec: Monitor Risk Feature

## Purpose
Let operators inspect risk events, details, evidence, and review state through
the local React monitor.

## Scope
- Risk list panel.
- Risk detail panel.
- Review action UI that delegates to audited backend behavior.

## Non-Scope
- Classifier implementation.
- Firewall policy decisions.
- Raw tool output display.

## Responsibilities
- Use canonical risk endpoints and generated/shared types.
- Keep list/detail loading and error states explicit.
- Preserve audit-oriented fields in the UI.
- Keep visible risk copy in the shared frontend i18n catalog instead of panel-
  local bilingual strings.
- Expose taint lineage and actionable control context when the backend provides
  it, without re-implementing policy logic in the browser.
- Treat backend-normalized arrays and lineage (`categories`, `poisoning_flags`,
  `taint_context`, `approval_line`, `command_ref`) as canonical detail fields
  instead of rendering raw `*_json` database columns.
- Poll risk endpoints in the background so freshly blocked actions and approval
  requirements show up without a manual reload.

## Inputs / Outputs
- Inputs: `/api/risks`, `/api/risk`, risk review endpoint shapes from OpenAPI.
- Outputs: risk list, selected risk details, review action results, and enough
  detail to explain why a block is still open or derived from earlier taint.

## Failure Modes
- Unknown risk ids display not-found/error state.
- Review failure does not optimistically hide the event.

## Acceptance Criteria
- Risk list/detail stories cover normal and degraded states.
- Build passes with generated OpenAPI types.
- Review UI never bypasses backend audit rules.
- Risk details can show taint-derived provenance and backend-issued command/
  approval references without exposing raw sensitive tool output.
- Cursor classifier auth failures are legible in detail view as runner/readiness
  degradation, not as opaque escaped JSON blobs.
- Recent risk events become visible in-panel within the polling window.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/risk`.

## Agent Guardrails
- Do not duplicate risk policy in frontend code.
- Do not render raw sensitive tool outputs.
