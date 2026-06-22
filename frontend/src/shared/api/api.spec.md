# Spec: Frontend Shared API Boundary

## Purpose
Provide the frontend's single API access layer for monitor feature panels,
backed by generated OpenAPI types and small local aliases.

## Scope
- Fetch wrapper behavior.
- Monitor endpoint helper functions.
- Generated type imports and local API aliases.

## Non-Scope
- Feature UI rendering.
- Backend route implementation.
- Manual generated type edits.

## Responsibilities
- Keep endpoint access consistent across panels.
- Surface HTTP/API failures as typed or predictable errors.
- Treat `frontend/src/shared/api/generated/types.ts` as generated output.
- Preserve structured backend error messages for protected control-plane
  actions instead of reducing them to generic status text.
- Translate shared monitor-facing API failure framing through the central
  frontend i18n catalog.

## Inputs / Outputs
- Inputs: endpoint names, request/query/body values.
- Outputs: parsed JSON payloads or controlled errors for feature components.

## Dependencies / Ports
- `contracts/openapi.yaml`.
- `frontend/src/shared/api/generated/types.ts`.
- Browser `fetch`.

## Failure Modes
- Non-2xx responses throw or return explicit failure shapes consistently.
- Invalid JSON is surfaced as an API error, not swallowed.
- If backend routes return JSON error payloads, the frontend API layer should
  expose the structured `error` detail so feature panels can explain protected
  or rejected actions accurately.

## Acceptance Criteria
- Feature components do not duplicate fetch boilerplate.
- OpenAPI type generation remains checkable.
- Build passes after API contract changes.

## Tests / Checks
- `python3 scripts/generate_openapi.py --check`
- `npm --prefix frontend run build`

## Agent Guardrails
- Do not hand-edit generated API types.
- Do not hardcode private monitor tokens in frontend source.
- Do not hide backend control-plane rejection reasons behind generic
  user-visible `500`/`403` summaries when structured detail is available.
