# Spec: Monitor Graph Feature

## Purpose
Show graph entities, relations, table options, query results, and graph artifact
state from the local monitor API.

It also supports drill-down into entities/relations and linked sessions from the
same monitor surface.

## Scope
- Focused read-only graph visualization centered on the current session, dream,
  entity, or relation.
- Graph overview panel.
- Graph query panel.
- Inspect workflow (entity/relation detail, linked sessions/relation hops).
- Empty/error/loading states for graph data.

## Non-Scope
- Graph extraction/materialization logic.
- Neo4j administration.
- Dream artifact generation.

## Responsibilities
- Use canonical graph endpoints and shared API types.
- Keep query controls stable and predictable.
- Preserve evidence/status fields needed for troubleshooting.
- Keep focus/query/inspect wording in the shared frontend i18n catalog.
- Present one focused graph context before broader table/query exploration.

## Inputs / Outputs
- Inputs: `/api/graph-entities`, `/api/graph-relations`,
  `/api/graph-table-options`, `/api/graph`.
- Outputs: graph tables, query results, inspect details, session links, and
  status/error UI state.

## Failure Modes
- Empty graph data renders as empty state.
- Query not-found/failed responses render without crashing.

## Acceptance Criteria
- Graph stories cover populated and empty states.
- Build passes with generated OpenAPI types.
- UI does not create graph policy outside backend application services.
- The knowledge area can show a focused graph context derived from the current
  session, dream, entity, or relation without requiring a global free-navigation
  graph.

## Tests / Checks
- `npm --prefix frontend run build`
- Storybook stories under `frontend/src/features/graph`.

## Agent Guardrails
- Do not hardcode backend graph schema beyond generated/shared types.
