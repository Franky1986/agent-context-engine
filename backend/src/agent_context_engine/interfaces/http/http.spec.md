# Spec: HTTP Monitor Interface Boundary

## Purpose
Serve the local monitor API, static React monitor build, OpenAPI contract, and
minimal HTML fallback.

## Scope
- HTTP routing, token injection, static asset serving, request parsing, and DTO
  mapping for monitor endpoints.
- `/api/openapi.json` must reflect `contracts/openapi.yaml`.

## Non-Scope
- Business rules for sessions, risk, graph, dreams, or retrieval.
- Frontend component implementation.

## Responsibilities
- Keep HTTP handlers thin and route to application/read-model services.
- Serve `frontend/dist` when present.
- Use `interfaces/http/html.py` only as a minimal fallback.
- Expose enough installation and runtime metadata for operators to understand
  active install roots, memory roots, launchagent identity, monitor runtime
  registry state, link registry state, and version drift.

## Inputs / Outputs
- Inputs: local HTTP requests, query params, JSON bodies, monitor token.
- Outputs: JSON DTOs, OpenAPI YAML-as-JSON response, static assets.

## Dependencies / Ports
- Application monitoring/read-model modules.
- `contracts/openapi.yaml`.
- Static frontend build artifacts.

## Failure Modes
- Missing frontend build returns fallback HTML, not a broken server.
- Invalid request bodies return controlled client errors.
- Application failures return explicit JSON errors where possible.

## Observability / Audit
- Mutating routes such as firewall/risk review must delegate to audited
  application behavior.

## Acceptance Criteria
- OpenAPI generation check passes.
- Canonical routes and compatibility aliases remain documented.
- HTTP route code has no hidden business policy branches.
- `/api/status` includes monitor version, backend version, installation
  timestamps, update timestamps, and integration/runtime bookkeeping required
  by the monitor.

## Tests / Checks
- `python3 scripts/generate_openapi.py --check`
- `./scripts/check --skip-runtime-db`
- `npm --prefix frontend run build`

## Agent Guardrails
- Do not rebuild the old Python monitor UI.
- Do not make `contracts/openapi.yaml` secondary to generated output.
