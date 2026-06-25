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
  mutation.

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
  `check-installation`.

## Integration State

- `codex`, `claude`, and `cursor` distinguish GUI-hook readiness from headless
  CLI readiness.
- `antigravity`, `gemini`, and `opencode` are global-only bridge flows.
- missing or stale workspace bindings are surfaced in diagnostics and the
  monitor instead of being treated as silently valid.
- Cursor activation now persists configured background runner and project launch
  context for hook capture and dream routing.
- Session list rows now show both origin client and dream runner, plus effective
  workdir (`last_workdir`) for session-level provenance.

## Known Follow-Up Areas

- broader English cleanup across historical internal progress notes,
- further polish for multi-version installation ergonomics,
- deeper storage migration tooling for future breaking schema changes,
- continued public curation of older internal design history.
