# Spec: Monitor Status Feature

## Purpose
Show local monitor health and key runtime state without requiring operators to
inspect the database manually.

## Scope
- Status and firewall-state summary display.
- Loading, empty, and error states for the monitor landing view.

## Non-Scope
- Risk event review.
- Session detail timelines.
- Backend policy decisions.

## Responsibilities
- Fetch status data through shared API client functions.
- Render compact operational state that fits desktop and narrow viewports.
- Avoid embedding backend constants that belong in OpenAPI/types.
- Keep runtime/firewall summary copy in the shared frontend i18n catalog.

## Inputs / Outputs
- Inputs: `/api/status`, `/api/firewall-state`.
- Outputs: React view state and visible monitor summary.

## Failure Modes
- Network/API errors render a usable error state.
- Missing optional fields render as unknown, not broken layout.
- Missing or still-loading firewall state must not be rendered as inactive.
- Slow `/api/status` integration probes must not cause the pilot to render a
  false firewall inactive state while the dedicated firewall endpoint is still
  loading or already reports enabled.

## Acceptance Criteria
- Storybook status stories remain representative.
- Frontend build succeeds with generated API types.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/status`.

## Agent Guardrails
- Do not hardcode stale API shapes; use shared API types.
