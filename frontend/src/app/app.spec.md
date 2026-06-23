# Spec: Monitor App Shell

## Purpose

Compose monitor feature panels into the first usable React application screen
served by the local backend.

## Scope

- app-level layout
- feature ordering
- high-level loading boundaries
- shared visual structure

## Non-Scope

- feature-specific data policy
- backend API implementation
- marketing or landing-page content

## Responsibilities

- Keep the monitor operational and dense enough for repeated use.
- Avoid nested card-heavy layouts and keep feature panels scannable.
- Delegate data fetching to feature and shared API modules.
- Route user-visible monitor copy through the central frontend i18n catalog
  rather than inline bilingual string pairs.
- Provide the primary top-level information architecture for the monitor:
  `Overview`, `Sessions`, `Dreams`, `Knowledge`, `Control`, and `Howto`.
- Keep `Sessions` as the default entry point for the daily operator journey.
- Keep `Howto` available as a persistent rightmost tab and as a stable deep-link target for fresh installations.
- Surface versioned monitor state cleanly enough that backend/product version
  and monitor version can evolve together without UI ambiguity.
- Group legacy or specialized monitor surfaces under the new primary sections
  instead of exposing them as competing top-level tabs.

## Inputs / Outputs

- Inputs: React feature components and shared styles.
- Outputs: monitor app UI rendered from `frontend/src/main.tsx`.

## Failure Modes

- A feature error should not make unrelated panels unusable when isolation is
  practical.
- Missing backend build-time data should not be hardcoded in the shell.

## Acceptance Criteria

- `npm --prefix frontend run build` passes.
- The app renders all active monitor feature panels without layout overlap.
- App shell contains no backend business logic.
- Legacy hash targets can be mapped into the active primary sections without a
  broken screen.
- `#howto` opens the guided orientation screen without displacing operational tabs.

## Tests / Checks

- `npm --prefix frontend run build`
- Storybook stories for major feature panels

## Agent Guardrails

- Do not create a marketing landing page for the monitor.
- Do not duplicate endpoint shapes in app-level code.
- New app-shell copy must use catalog keys, not ad-hoc inline translations.
