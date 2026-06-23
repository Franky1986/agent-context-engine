# Agent Instructions

This repository is the standalone Agent Context Engine public checkout. Future agents
should treat this file as the first operational guide after cloning or opening
the project.

Hook-based runtime sessions are expected to read
`session-start-hook-entry.md` first. That file contains the operational CLI
workflow and startup command contract for this installation. Keep `AGENTS.md`
as the canonical source for project rules, installation/bootstrap references,
and repository-level operating constraints.

## Agent Context Engine Quick Path
- Preferred interaction language for future agents: English.
- When asked about previous sessions, handovers, project context, "what happened last", "continue there", "we already analyzed this", or similar memory requests, use the local Agent Context Engine CLI first.
- Agent Context Engine command prefix: `./scripts/ace`
- Traceable retrieval: `./scripts/ace retrieve "<question or search terms>" --limit 10`
- Quick keyword search: `./scripts/ace search "<search terms>" --limit 5`
- Load a session handover: `./scripts/ace handover "<session|title|search terms>"`
- Recent sessions: `./scripts/ace last --limit 10`
- Status: `./scripts/ace doctor`
- For list/count/today questions about sessions, use `last` first and stop there unless the user explicitly asks for details about a specific session.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- Only after these commands should agents broaden the search with `rg` in the repository or memory tree.

## Documentation And Spec Discipline

- Public-facing documentation and bootstrap guidance should default to English unless a file is explicitly local/private.
- When a code change affects a non-trivial boundary, update the nearest `*.spec.md` file in the same area.
- When a `*.spec.md` file is added or moved, run `python3 scripts/update_docs_index.py --check` and keep `docs/index.md` aligned.
- Changes to installation, harnesses, monitor behavior, or agent workflow contracts must keep `AGENT_BOOTSTRAP.md`, `docs/setup/RUNNER_HARNESSES.md`, and `session-start-hook-entry.md` accurate.

## Installation Context

Do not load the full installation flow by default. Only when the user explicitly
asks to install, initialize, clone-and-setup, enable a harness, or configure a
new project, load `AGENT_BOOTSTRAP.md` first, then
`docs/setup/RUNNER_HARNESSES.md`, and then the relevant README sections. Keep
normal memory-search questions focused on the quick path above.

For install requests, keep the approval flow compact: use discovery first,
present the discovered defaults, and avoid drawing strong conclusions from
pre-approval `doctor` / `check-installation` failures in restricted
environments. Permission-related errors against `~/.agent-context-engine`
should be treated as inconclusive until rerun with the required access.
Include the monitor-port caveat explicitly in the approval summary: the shown
port is a discovery default and is revalidated again immediately before config
is written.

## Integration Management Context

When the user asks about client or runner integrations, wrapper commands,
global links, project activation, hook status, hook enable/disable, provider
readiness, or model selection for `codex`, `claude`, `cursor`, `antigravity`,
`gemini`, or `opencode`, load these documents first:

- `docs/setup/RUNNER_HARNESSES.md`
- `docs/runbooks/integration-management.md`

Use them as the operational contract before changing integration state or
explaining monitor status.

OpenCode, Antigravity, and Gemini are global-only: they are started through
`opencode-ace`, `agy-ace`, and `gemini-ace` from any directory. The
plain `opencode`, `agy`, and `gemini` commands start without Agent Context Engine hooks.

## Runtime And Privacy Rules

- Do not commit runtime memory data.
- `memory/`, SQLite databases, hook configs, local `memory/knowledge/`, IDE files,
  caches, and local environment files must remain gitignored.
- After repository updates that can affect the monitor or API/UI code, restart
  the local monitor with `./scripts/ace monitor --runner codex
  --replace-existing --port 8787 --no-open --language en`. The installer should also leave a fresh installation with the monitor already started unless the user explicitly opted out. Agents should treat
  this restart as part of the update flow instead of leaving an older monitor
  process running against newer code.
- After repository updates that can affect scheduler defaults, dream runners,
  launchagent behavior, or monitor/runtime status reporting, also reload the
  local LaunchAgent with `./scripts/ace install-launchagent --load`.
- After repository updates that can affect Dream-v2 semantic persistence rules,
  Cursor runner parsing, or dream-stage metadata contracts, also verify one
  fresh Cursor dream run before trusting the new runtime behavior. At minimum
  inspect the latest dream run for:
  - non-zero token usage when Cursor returns usage
  - grounded semantic evidence
  - no accidental low-signal over-persistence
- Treat `./scripts/ace launchagent-status --verbose` and the monitor
  runtime card from `/api/status` as the required drift check after such
  updates.
- The monitor is expected to show both the running monitor process metadata and
  the installed LaunchAgent metadata. If either side reports drift or stale
  runtime state, reconcile before trusting new dream behavior.
- Treat `memory/knowledge/repos.md` as local/private user context unless the user
  explicitly asks to publish a sanitized version.
- Raw tool outputs are intentionally not persisted. Use `tool-calls` metadata,
  event summaries, and risk records instead of expecting recoverable raw output.
- For security/risk events, inspect with:

```sh
./scripts/ace risk list --limit 20
./scripts/ace risk show <risk_event_id>
```

User-only controls such as `approve ...`, `reset taint`, `firewall add ...`,
`firewall disable session`, `firewall disable session 30m`, and
`firewall enable session`, `hooks-disable [--runner <runner>]`,
`hooks-enable [--runner <runner>]`, and `hooks-status` must be sent by the
user as chat messages. Do not execute those control lines as tools.

## Useful Development Checks

Before publishing changes, run:

```sh
./scripts/check --skip-runtime-db
```

For focused tests:

```sh
python3 tests/test_agent_context_engine.py
python3 -m unittest discover -s tests -v
```

## Hook Session Entry

- Hook-based runtime sessions are expected to load `session-start-hook-entry.md` first.
- That file contains the operational Agent Context Engine workflow and the available context-loading commands.
- Keep `AGENTS.md` as the canonical source for project rules, installation/bootstrap guidance, and repository-level operating constraints.
