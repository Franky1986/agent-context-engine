# Current Status

## Date
2026-07-14

## Public Snapshot

Agent Context Engine is usable today as a local-first runtime for coding-agent
workflows. The current public slice includes:

- local session capture and retrieval,
- summaries and dream runs,
- graph extraction and inspectable monitor views,
- hook and firewall safety controls,
- instance profiles with wrapper naming, monitor defaults, and LaunchAgent
  defaults,
- explicit workspace bindings for `codex`, `claude`, and `cursor`,
- origin client + dream runner visibility in session list rows,
- storage-root decoupling through `memory_root`,
- guided installation discovery with explicit user confirmation before
  mutation,
- isolated installs with target-local runtime storage,
- verified Cursor project activation with a pinned Claude background runner,
- verified retrieval over fresh isolated-session summaries and semantic memory,
- canonical runtime repo knowledge under `memory/knowledge/repos.md` with
  legacy docs-path import fallback,
- install discovery/install summaries that surface already known repos/folders
  and where that knowledge is visible in the monitor,
- explicit Windows experimental runtime adapters for command publication,
  PowerShell wrappers/hooks, Task Scheduler wiring, and diagnostics.
- dream/monitor artifact inspection and CLI handover rendering now resolve
  external runtime-memory roots consistently, including Dream-v2 summaries,
  audit files, and dream-first session briefs.
- session-start bootstrapping is consolidated with preserved exploratory behavior:
  recent-session context injection, scoped `session-start-context`, and
  user prompt hook messaging that still points to
  `session-start-hook-entry.md`.
- project-local central hook-adapter hubs now let supported runner wrappers
  stay in the current project directory while delegating through
  installation-owned hub symlinks.
- direct hub calls now derive their metadata root from the resolved hub path;
  instance-named wrappers and isolated backups remain bound to their owning
  installation, while shared external-storage installs update the canonical
  home `active-root` takeover pointer.
- direct-user system suspension is implemented as an installation-specific,
  fail-closed admission gate with preserved hook state, owned-scheduler
  disable/restore, read-only monitor status, bounded audit records, and no
  public mutating CLI or HTTP endpoint. Initialized state is hash-anchored and
  suspended CLI admission is default-deny with an explicit
  safe-while-suspended inspection set. Runner-event provenance is
  instrumented but not OS-authenticated, so arbitrary same-user code remains
  outside the security boundary. The 2026-07-14 canonical unit and
  install-integration buckets are green, and direct startup was confirmed for
  all six supported wrapper commands. Event-level direct-chat suspension
  coverage across every runner and real Windows validation remain release
  gates.
- direct-user hook controls now distinguish all hooks, one runner, the exact
  current project, and one runner in that project. Project disable keeps the
  hook recovery channel installed; agent tool and hook-state file mutations
  remain hard-blocked.
- Codex, Claude, Gemini, and Antigravity project hooks now use shell-quoted
  absolute commands to the project-local adapter symlink, and activation
  repairs legacy relative or runner-variable hook commands.
- hook blocking messages and monitor session risk summaries now distinguish
  invalid firewall classifier output from ordinary policy or tainted-context
  blocks.
- PreTool classifier runners now handle structured and event-wrapped output
  more robustly across Claude, Gemini, Antigravity, and OpenCode, including a
  one-shot schema repair prompt for text-only runners.
- Antigravity headless calls use the `agy -p <prompt>` contract; the PreTool
  classifier and dream runner share the directly validated
  `Gemini 3.5 Flash (Low)` default. Current `agy` releases reject the removed
  `Minimal` thinking-level label.

Versioned release snapshot:

- Backend / product: `0.2.14`
- Monitor: `0.6.10`

## Installation State

The current install flow now supports:

- installation-nonmutating `install-discovery`; `--plan-json` intentionally
  writes only the requested approval artifact,
- explicit `memory_root` configuration,
- detection of existing installations and storage candidates,
- public-checkout guardrails against cross-checkout mutation,
- automatic post-install verification through `doctor` and
  `check-installation`,
- compact localized install completion with severity-counted findings, correct
  recognition of the installation's own active monitor, and migration of the
  legacy nested default-home `active-root`,
- mandatory plan-JSON approval handoff for agent-driven installs, authoritative
  post-install Codex/Claude readiness, and separate historical binding
  maintenance notices,
- verified monitor takeover using status identity plus cleanup of
  registered or locally discovered superseded monitors sharing the memory root,
  including verified legacy macOS submitted KeepAlive monitor jobs. Registry
  and status PIDs are never terminated; owned monitors use an authenticated
  HTTP shutdown or a verified platform launcher and must remain absent through
  an eight-second stability window. Failed takeover robustly rolls back the
  newly started owned monitor,
- Windows monitor startup uses a root-specific owned Task Scheduler launcher
  and requires matching `/api/status` identity rather than stable port
  acceptance; incomplete requested installs return non-zero,
- isolated wrapper naming and local SQLite/runtime storage for side-by-side
  installs,
- Windows-native `.cmd` publication and PowerShell hook/wrapper generation for
  experimental installs,
- Windows user `PATH` repair for generated command shims,
- runtime repo-index migration/import from legacy docs storage into canonical
  memory storage, plus install-time visibility into recognized repos/folders,
- guarded install finalization where hook activation stays until the end, the
  monitor starts only after runtime/bootstrap, frontend build, and scheduler
  setup succeed, and the full `doctor`/`check-installation` pass closes the
  install afterwards.
- successful installation-root finalization checks the required runner hook
  configs and the OpenCode plugin bridge. Once runtime and frontend repair are
  healthy, `repair-installation --apply` repeats that root finalization without
  implicitly rewriting external workspace adapters.

## Integration State

- `codex`, `claude`, and `cursor` distinguish GUI-hook readiness from headless
  CLI readiness.
- `antigravity`, `gemini`, and `opencode` are global-only bridge flows.
- `codex`, `claude`, `gemini`, and `antigravity` wrappers can use
  project-local central hook-adapter hubs; `opencode` remains the deprecated
  global-only exception.
- Windows now uses native `.cmd` publication plus PowerShell-based hooks and
  wrappers while remaining explicitly below `supported`.
- Monitor dashboard status uses a fast integration summary; slow external
  runner auth and model-discovery probes are reserved for explicit integration
  checks so `/api/status` does not make the overview appear unavailable.
- missing or stale workspace bindings are surfaced in diagnostics and the
  monitor instead of being treated as silently valid.
- Cursor activation now persists configured background runner and project launch
  context for hook capture and dream routing.
- external Cursor project activation now also registers the target in the
  install-wide workspace-root profile, so `doctor` and `check-installation`
  reflect the same project set as `cursor-status --target ...`.
- end-to-end Cursor dreaming has been revalidated with `claude` as the pinned
  background runner in an isolated installation.
- Session list rows now show both origin client and dream runner, plus effective
  workdir (`last_workdir`) for session-level provenance.

## Validation Snapshot

Recent direct validation on isolated installation `agent-context-engine-refactor-2`
confirmed:

- install root and memory root stay local to the checkout,
- `search` and `retrieve` return the expected fresh session/dream content,
- an external test project activates correctly through
  `cursor-enable --target ... --installation-root ... --background-runner claude`,
- the activation is now visible both in target-local `cursor-status --target ...`
  and in install-wide diagnostics via persisted `workspace_roots.cursor`,
- Cursor sessions in that project were summarized and dreamed with
  `preferred_dream_runner=claude`,
- no stale running dream remained after scheduler recovery.

Recent validation for the Windows experimental slice confirmed:

- Windows platform profile now reports `support=experimental`,
- runtime selection surfaces Windows-specific publisher, wrapper, hook,
  scheduler, quoting, process-launch, workspace-binding, and system-open
  adapters,
- focused Windows contract tests are green on the development host, including
  `.cmd` shim runtime-Python selection, stale PID handling, monitor metadata
  sync tolerance, and Windows monitor autostart command hosting,
- global wrapper publication now verifies `.cmd` shim paths and resolves
  `codex-ace` from `PATH`,
- `codex-ace --version` completed through the generated wrapper on Windows,
- monitor frontend typecheck/build completed with the Windows Node toolchain,
- a native Windows monitor smoke confirmed `/api/status`, `/api/integrations`,
  `/api/dreams`, `/api/dream-queue`, and `/api/firewall-state`; firewall state
  reported enabled from the backend while the frontend pilot needed an
  `unknown/loading` state fix to avoid showing missing data as inactive,
- detached monitor startup through raw `python.exe`, PowerShell, or command-host
  processes proved unreliable on Windows; installer autostart now uses a
  root-specific owned Task Scheduler launcher with explicit install and
  storage-root environment,
- `dream --pending --runner deterministic` against the active Windows runtime
  returned `No sessions to dream`, so an empty Dreams view was confirmed as an
  empty-work state rather than a broken Dream endpoint,
- interrupted dream state was cleaned to an empty dream queue and no running
  dream runs,
- the Windows Task Scheduler job is installed and ready rather than stuck
  running,
- broader CI and a full fresh external-project runner-to-retrieval pass remain
  pending before any Windows support-level increase.

Latest automated validation on the current public checkout install also
confirmed:

- `doctor`, `check-installation`, `install-discovery`, `last`, `search`,
  `retrieve`, `session-start-context`, `repo-context --list`,
  `personal-context --list`, `integrations-status`,
  `launchagent-status --verbose`, and `dream-queue-status` completed against
  the active macOS install,
- `agent-context-engine risk list --limit 5` now completes again against the
  active runtime and renders normalized category lists,
- `python3 scripts/check_agent_context_engine.py --skip-tests --skip-runtime-db`
  now completes the fresh-install smoke path without the previous interactive
  install stall,
- the active public checkout monitor was restarted on `127.0.0.1:8787` after
  the suspension hardening pass; `/api/status` reports backend
  `0.2.14`, monitor `0.6.10`, the external shared memory root, and no
  LaunchAgent drift,
- `doctor` now degrades to a warning when instance metadata cannot be written,
  instead of crashing the diagnostic run.
- runtime repo-index migration, rebuild-index indexing, and retrieval over the
  canonical repo-index document were revalidated through focused end-to-end
  tests.

## Consolidation Review (Windows Codex Push)

Latest pull consolidation merged:

- `5e4712a fix: harden monitor startup and status reliability`
- `3144057 main - fix: stabilize windows autostart tests and define session start gating`
- `3552c4a chore: compact session start command guidance`

Impact summary:

- monitor startup/status behavior is more resilient on macOS as well as Windows,
  including non-fatal handling of instance metadata synchronization failures,
  and status reads now avoid stalling on slow integration lookups;
- userprompt/SessionStart exploratory paths are preserved and still route startup
  context through the documented hook entry contract;
- macOS monitor workflow remains LaunchAgent-based, with more deterministic status
  and reduced risk of status blanking during transient integration metadata issues.

Verification references (automated, current checkout):

- `tests/test_agent_context_engine.py::test_codex_session_start_injects_recent_sessions_context`
- `tests/test_agent_context_engine.py::test_user_prompt_submit_context_points_to_session_start_hook_entry`
- `tests/test_agent_context_engine.py::test_session_start_context_surfaces_personal_and_repo_knowledge_without_paths`
- `tests/test_agent_context_engine.py::test_personal_and_repo_context_commands_are_scoped_and_path_safe`
- `tests/test_agent_context_engine.py::test_monitor_status_uses_fast_integration_summary`
- `tests/test_agent_context_engine.py::test_monitor_status_survives_instance_metadata_sync_permission_error`
- `tests/test_agent_context_engine.py::test_windows_monitor_autostart_uses_cmd_start_and_storage_root_env`
- `tests/test_agent_context_engine.py::test_windows_monitor_autostart_rejects_brief_port_acceptance`
- `tests/test_agent_context_engine.py::test_windows_monitor_autostart_falls_back_to_task_scheduler`

Residual risk:

- Windows support is still `experimental`; real-machine end-to-end validation for
  retrieval and external-project dreams is the remaining blocker for stronger
  support claims.
- Upgrades from pre-root-specific Windows installs may require manual removal of
  the legacy `AgentContextEngine\\Monitor-<name>` task and
  `windows-monitor-start.cmd`; see `docs/setup/WINDOWS_INSTALLATION.md`.

## Known Follow-Up Areas

- install-wide diagnostics still list external Cursor projects only when they
  are recorded in `workspace_roots`; target-local `cursor-status --target ...`
  is currently the authoritative check for externally activated projects,
- `pending dreams` intentionally tracks uncovered event ranges, so it can stay
  non-zero until those ranges are actually dreamed even after older dream runs
  already succeeded; session rows now revert immediately to pending when queued
  follow-up work appears,
- broader English cleanup across historical internal progress notes,
- further polish for multi-version installation ergonomics,
- deeper storage migration tooling for future breaking schema changes,
- continued public curation of older internal design history,
- one real Windows machine validation pass before any support-level increase
  beyond `experimental`.
- Windows diagnostics and monitor UI should continue replacing macOS-specific
  `LaunchAgent` wording with scheduler-neutral or Windows Task
  Scheduler-specific wording.
