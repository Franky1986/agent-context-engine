# Spec: Monitor Diagnostics Feature

## Purpose
Show runtime diagnostics, doctor output, and configuration signals useful for
local operation and troubleshooting.

## Scope
- Diagnostics panel.
- Runtime configuration and doctor-result presentation.
- Loading and error states.

## Non-Scope
- Running destructive maintenance.
- Editing configuration.
- LaunchAgent management.

## Responsibilities
- Present backend diagnostics without turning them into frontend policy.
- Keep long diagnostic lines readable in constrained layouts.
- Avoid leaking secrets in stories or default fixtures.
- Use centralized monitor i18n keys for user-facing status and empty-state
  wording.

## Inputs / Outputs
- Inputs: `/api/diagnostics`.
- Outputs: diagnostics groups, status indicators, errors.

## Failure Modes
- Doctor/API failure renders a clear failed diagnostics state.
- Missing optional sections are omitted or marked unknown.

## Acceptance Criteria
- Diagnostics stories cover healthy and degraded states.
- Build passes with generated API types.
- No local secrets appear in committed mock data.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/diagnostics`.

## Agent Guardrails
- Do not add config mutation UI without a backend contract.
- Do not embed private local paths beyond sanitized fixtures.
