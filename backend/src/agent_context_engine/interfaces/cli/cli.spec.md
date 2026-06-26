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
- Keep installation and enable/repair flows explicit about target root,
  memory root, wrapper naming, monitor port selection, and user confirmation.
- Expose global-only runner preparation flows that operate on the installation
  root while still allowing an external shared memory root.
- Keep the public management CLI contract explicit: generated guidance and
  operator-facing commands should prefer `agent-context-engine` from `PATH`,
  with repo-local script paths treated as compatibility fallbacks.
- Keep install-time runtime storage flags distinct from integration activation
  flags: `cursor-enable`, `antigravity-enable`, `gemini-enable`,
  `opencode-enable`, and `integration-hooks` must refer to the owning
  installation root explicitly, not mislabel it as a runtime memory root.

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
- Maintain `docsupdate` as an editor/runtime maintenance workflow entrypoint.
  This repo-level workflow is documented in `docs/commands/docsupdate/README.md`
  and exposed to IDE/runtime clients through local command surfaces. It is
  intentionally not a standalone `agent-context-engine` CLI verb.

## Observability / Audit
- Commands that access memory or mutate risk/firewall state must call
  application paths that audit those effects.

## Acceptance Criteria
- `agent-context-engine --help` and core commands remain stable.
- No new core logic appears in command modules.
- JSON output stays parseable where documented.
- Install discovery and install execution agree on shared-command takeover
  semantics for `agent-context-engine`, `ace`, and `*-ace` wrapper links.
- `--isolated` is a deterministic install mode: target-local runtime storage by
  default, instance-specific wrapper naming, and no takeover of shared
  `agent-context-engine` / `ace` commands.
- Install discovery and install execution agree on wrapper-link conflict
  semantics for direct `scripts/*` targets and active installed script targets
  within the same checkout.
- Install execution must verify the platform-published command path: plain
  symlink names on POSIX systems and `.cmd` shim paths on Windows. Windows
  installs must also make the configured link directory available to current
  command resolution and persist it in the user `PATH` when possible.
- Install discovery and `check-installation` must surface unsupported local
  Python/Node/npm prerequisites before pointing operators or agents at
  bootstrap or frontend repair commands that would fail immediately.
- Install discovery and install execution must describe the active scheduler
  backend accurately for the current platform profile. The historical
  `install-launchagent` command name may remain as a compatibility surface, but
  Windows guidance and approval prompts must refer to Task Scheduler rather
  than implying a macOS LaunchAgent.
- Install discovery and install execution must surface the runtime repo-index
  state: whether repos/folders are already known from the active memory root,
  where the canonical repo index lives, where operators can review it in the
  monitor (`Personal -> Repo-Index`), and how later repo/folder additions can
  be made without editing tracked docs files.
- Install discovery and install execution must keep scheduler installation and
  loading enabled by default because periodic summaries, dreams, graph
  extraction, and catch-up depend on it. `--no-install-launchagent` remains an
  explicit opt-out, not the public-checkout default. A saved user-level
  launchagent opt-out must not silently flip fresh-install discovery away from
  that default; discovery should surface the recommendation source explicitly.
- Install execution must activate hook configs, GUI workspace hooks, and
  global-only integration hooks only after runtime bootstrap, frontend build,
  scheduler installation/loading, and requested monitor startup have completed
  successfully. The full `doctor` / `check-installation` pass belongs at the
  very end, after those hook files exist. Incomplete installs must leave hooks
  inactive and must not start a monitor for an unbuilt frontend or unusable
  backend.
- Install discovery, install execution, and repo-context commands must treat
  `memory/knowledge/repos.md` under the active memory root as the canonical
  runtime repo index. Legacy `docs/knowledge/repos.md` files may be imported as
  a compatibility fallback, but new runtime writes must not depend on mutating
  checkout-tracked docs files.
- `docsupdate` is the canonical maintenance workflow label and resolves to the
  shared editor entrypoint contract (`docs/commands/docsupdate/README.md`).
- Install discovery must prefer an explicit language hint first, then the
  current interaction/environment language, before reusing an older
  checkout-installed language.
- `cursor-enable` must fail clearly when neither `codex` nor `claude` is
  available for required background LLM workflows.
- `cursor-enable --background-runner <codex|claude>` must pin that exact
  background runner into the workspace binding and fail clearly when the
  requested runner is missing or not authenticated for headless use.
- Successful `cursor-enable --target <external-project> --installation-root <installation>`
  runs must also persist that external Cursor workspace into the installation
  profile so `doctor`, `check-installation`, and monitor installation summaries
  report the same activated-project set as `cursor-status --target ...`.
- For `claude`, Agent Context Engine must use the real `claude auth status`
  contract instead of inventing a fake `claude status` probe, and auth
  guidance must point to `claude auth login`.
- `cursor-enable`, `cursor-disable`, and `cursor-status --target ...` must fail
  clearly when the requested target directory does not exist; they must not
  silently create or reinterpret a mistaken relative path under the active
  installation root.
- When Cursor activation fails, operators and agents must not treat
  `opencode-enable`, `gemini-enable`, or other client activation commands as a
  substitute for `cursor-enable`.
- `dream`, `scheduler-run`, and `install-launchagent` must default
  `--graph-runner` to `same-as-session` so deterministic or non-Codex dream
  runs do not silently trigger a separate Codex graph-materialization fallback.

## Tests / Checks
- `python3 tests/test_agent_context_engine.py`
- `./scripts/check --skip-runtime-db`

## Agent Guardrails
- Do not add direct SQLite business queries to CLI commands.
- Do not execute user-only control lines as shell commands.
