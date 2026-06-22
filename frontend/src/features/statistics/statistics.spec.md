# Spec: Monitor Statistics Feature

## Purpose
Provide a dedicated operator-facing usage surface for token consumption across
sessions and dreams.

## Scope
- Top-level `Statistics` monitor section.
- Filtered stats loading from `/api/stats`.
- Time-based chart for session-vs-dream token usage.
- Grouped breakdowns for project, client, workdir, dream runner, and dream
  model.

## Non-Scope
- Billing or price estimation.
- Heuristic model attribution for normal session token usage.
- Mutation or control-plane actions.

## Responsibilities
- Keep `Session` and `Dream` token totals explicitly separated.
- Reuse generated/shared API types and the shared i18n catalog.
- Present only statistically defensible dimensions.
- Avoid pretending that normal session tokens can be attributed to a model when
  the persistence model does not support that cleanly.

## Inputs / Outputs
- Inputs: `/api/stats`.
- Outputs: KPI cards, time-series chart, grouped usage breakdowns, loading and
  empty states.

## Failure Modes
- Empty result ranges render controlled empty states instead of blank charts.
- API failures render a visible panel error without crashing the app shell.

## Acceptance Criteria
- `Statistics` is reachable as a dedicated top-level section.
- The feature shows separate totals for session tokens and dream tokens.
- The time chart visualizes session-vs-dream usage over time.
- Grouped usage is visible for project, client, workdir, dream runner, and
  dream model.
- Filters for range, client, project, and workdir are available.
- Frontend build passes with generated API types.

## Tests / Checks
- `python3 -m unittest tests.test_agent_memory.AgentMemoryEndToEndTests.test_monitor_stats_groups_session_and_dream_tokens_by_hour`
- `npm --prefix frontend run build`

## Agent Guardrails
- Do not add model-based grouping for normal session usage without a real
  backend attribution model.
- Do not mix firewall/control actions into this analytics surface.
