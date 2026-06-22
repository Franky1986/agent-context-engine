# Spec: CLI Interface Boundary

## Purpose
Expose operator and agent-facing commands while delegating business behavior to
application services.

## Scope
- Argument parsing, command dispatch, exit codes, and output formatting.
- Compatibility wrappers for documented commands.

## Non-Scope
- SQL queries for core business behavior.
- Runner policy decisions.
- HTTP or frontend concerns.

## Responsibilities
- Keep documented commands stable.
- Normalize user inputs before calling application functions.
- Preserve useful non-zero exits for controlled failures.

## Inputs / Outputs
- Inputs: command line arguments, environment flags, current working directory.
- Outputs: text/JSON output, exit code, controlled stderr messages.

## Dependencies / Ports
- Application services.
- Infrastructure config for runtime options.
- Thin launcher `scripts/agent_context_engine.py`.

## Failure Modes
- Invalid arguments fail with argparse/help behavior.
- Application failures are surfaced without Python tracebacks in expected
  user-error cases.

## Observability / Audit
- Commands that access memory or mutate risk/firewall state must call
  application paths that audit those effects.

## Acceptance Criteria
- `./scripts/agent-context-engine --help` and core commands remain stable.
- No new core logic appears in command modules.
- JSON output stays parseable where documented.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not add direct SQLite business queries to CLI commands.
- Do not execute user-only control lines as shell commands.
