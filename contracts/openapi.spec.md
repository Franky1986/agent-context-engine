# Spec: Monitor OpenAPI Contract

## Purpose
Keep the local monitor HTTP API contract explicit, versionable, and shared
between backend and frontend.

## Scope
- `contracts/openapi.yaml` as canonical API specification.
- Backend `/api/openapi.json` serving the same contract.
- Frontend generated types under `frontend/src/shared/api/generated/types.ts`.

## Non-Scope
- Runtime database schema.
- Frontend layout or styling.
- Undocumented private helper routes.

## Responsibilities
- Treat `contracts/openapi.yaml` as source of truth.
- Regenerate/check frontend API types when contract shapes change.
- Keep compatibility aliases documented when they remain supported.
- Keep protected control-plane behavior explicit in the contract when routes
  intentionally reject classes of mutation requests.

## Inputs / Outputs
- Inputs: OpenAPI YAML edits.
- Outputs: backend-served OpenAPI response and generated TypeScript types.

## Dependencies / Ports
- `scripts/generate_openapi.py`.
- `openapi-typescript` through the frontend toolchain.

## Failure Modes
- Generated frontend types out of date must fail the check.
- Backend route/contract drift should be caught before publish.
- Routes that intentionally reject protected control-plane mutations must do so
  as documented behavior, not as accidental undocumented server errors.

## Acceptance Criteria
- `python3 scripts/generate_openapi.py --check` passes.
- `npm --prefix frontend run build` passes after API changes.
- HTTP feature specs reference this contract instead of duplicating shapes.
- Sensitive mutation routes such as integration-hook or firewall control paths
  can express intentional rejection semantics without leaving the frontend to
  guess whether a `403`/`409` is expected.

## Tests / Checks
- `python3 scripts/generate_openapi.py --check`
- `./scripts/check --skip-runtime-db`
- `npm --prefix frontend run build`

## Agent Guardrails
- Do not edit generated TypeScript types by hand.
- Do not make backend route behavior the undocumented source of truth.
