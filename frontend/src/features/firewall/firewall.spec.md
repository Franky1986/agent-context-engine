# Spec: Monitor Firewall Feature

## Purpose
Expose firewall state, active overrides, rules, and audit context while keeping
security-control mutations on the explicit user path.

## Scope
- Firewall state panel.
- Direct user control guidance for session-scoped firewall disable/enable.
- Audit/list presentation.
- API error/loading/empty states.

## Non-Scope
- Firewall policy evaluation.
- Risk classifier execution.
- User-only chat control parsing.
- Normal monitor actions that disable the firewall or create/revoke overrides.

## Responsibilities
- Use canonical firewall endpoints and shared API types.
- Never make frontend-only allow/block decisions.
- Explain the direct user chat path for session firewall control.
- Prefer an operations-first presentation: urgent approvals and active
  exceptions before deeper rule/audit detail.

## Inputs / Outputs
- Inputs: `/api/firewall-state`, `/api/firewall-rules`, `/api/firewall-suggestions`, `/api/risks`.
- Outputs: firewall status UI, direct-control guidance, action errors.

## Failure Modes
- Missing optional audit entries render as empty state.
- The frontend must not expose stale or forbidden disable/override actions after
  backend policy hardening.

## Acceptance Criteria
- Firewall stories cover state, direct user control guidance, and error scenarios.
- Build passes with generated API types.
- The control surface remains usable for everyday operation without exposing
  forbidden disable/override actions.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/firewall`.

## Agent Guardrails
- Do not duplicate firewall policy in frontend code.
- Do not add unaudited disable or override shortcuts.
