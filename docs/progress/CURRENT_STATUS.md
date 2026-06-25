# Current Status

## Date
2026-06-25

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
- explicit Windows experimental runtime adapters for command publication,
  PowerShell wrappers/hooks, Task Scheduler wiring, and diagnostics.

Versioned release snapshot:

- Backend / product: `0.2.7`
- Monitor: `0.6.5`

## Installation State

The current install flow now supports:

- read-only `install-discovery`,
- explicit `memory_root` configuration,
- detection of existing installations and storage candidates,
- public-checkout guardrails against cross-checkout mutation,
- automatic post-install verification through `doctor` and
  `check-installation`,
- isolated wrapper naming and local SQLite/runtime storage for side-by-side
  installs,
- Windows-native `.cmd` publication and PowerShell hook/wrapper generation for
  experimental installs.

## Integration State

- `codex`, `claude`, and `cursor` distinguish GUI-hook readiness from headless
  CLI readiness.
- `antigravity`, `gemini`, and `opencode` are global-only bridge flows.
- Windows now uses native `.cmd` publication plus PowerShell-based hooks and
  wrappers while remaining explicitly below `supported`.
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
- `/Users/frankrichter/projects/test` activates correctly through
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
- focused Windows contract tests and fresh-install smoke checks are green on
  the development host,
- real Windows runtime validation and CI remain intentionally pending.

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
