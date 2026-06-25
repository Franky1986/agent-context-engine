# Spec: Scheduler Application Boundary

## Purpose
Coordinate background processing steps for ingestion replay, summaries, dreams,
graph repair, sync, cleanup, and recovery.

## Scope
- Scheduler run/step orchestration.
- Retryable vs hard failure classification.
- Delegation to application services and infrastructure adapters.

## Non-Scope
- LaunchAgent/plist mechanics.
- Direct UI rendering.
- Business logic owned by dream, graph, retrieval, or firewall use cases.

## Responsibilities
- Persist scheduler runs and step outcomes consistently.
- Keep queue replay and recovery behavior deterministic.
- Avoid concurrent writer collisions through lock/adapter boundaries.

## Inputs / Outputs
- Inputs: scheduler command options, due work, runtime config.
- Outputs: scheduler run rows, step rows, operational summaries.

## Dependencies / Ports
- SQLite scheduler adapter.
- Platform-selected scheduler installation adapter for OS integration.
- Locking infrastructure.
- Application services for dream, graph, summaries, and ingestion.

## Failure Modes
- SQLite busy/locked errors are retryable when safe.
- Step hard failures are recorded without hiding later steps.
- Missing optional integrations do not fail unrelated core steps.

## Observability / Audit
- Each scheduler step records name, status, timing, and error class.
- Operators can inspect recent runs through CLI/monitor read models.

## Acceptance Criteria
- `scheduler-status` and `scheduler-run` remain behavior-compatible.
- Replay and repair steps are visible in scheduler step history.
- No LaunchAgent implementation detail leaks into core scheduling policy.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `agent-context-engine doctor`

## Agent Guardrails
- Do not reintroduce direct launchctl/plist handling here.
- Keep new step names stable once persisted.
