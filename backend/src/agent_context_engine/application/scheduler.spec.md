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
- A session whose latest Dream state is terminal `failed` is not selected by
  the automatic pending sweep again. Explicit reruns remain available, and a
  newly accepted hook event changes the session back to `dream_pending`, which
  makes the new event window eligible.
- Check the installation-specific system admission gate before acquiring the
  scheduler run lock or claiming work. Suspended and fail-closed partial modes
  skip successfully.
- Use `SystemSchedulerPort` for system suspension: macOS unloads/restores only
  the owned LaunchAgent without deleting its plist; Windows disables/restores
  only the owned Task Scheduler task.
- Restore a scheduler only when the pre-disable snapshot proves it was active.

## Observability / Audit
- Each scheduler step records name, status, timing, and error class.
- Operators can inspect recent runs through CLI/monitor read models.

## Acceptance Criteria
- `scheduler-status` and `scheduler-run` remain behavior-compatible.
- Replay and repair steps are visible in scheduler step history.
- Terminal Dream failures do not create an endless sequence of new
  `pending_sweep` queue jobs when no session events changed.
- No LaunchAgent implementation detail leaks into core scheduling policy.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `agent-context-engine doctor`

## Agent Guardrails
- Do not reintroduce direct launchctl/plist handling here.
- Keep new step names stable once persisted.
