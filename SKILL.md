# Agent Context Engine

Use this skill when a user wants persistent local memory for agentic coding
sessions, or asks to find, continue, summarize, inspect, or initialize prior
agent work.

Agent Context Engine is a local-first package for:

- Codex sessions started through `codex-ace` by default
- Claude Code sessions started through `claude-ace` by default
- Cursor IDE projects enabled with `agent-memory cursor-enable`
- Antigravity CLI sessions started globally through `agy-ace` by default
- Gemini CLI sessions started globally through `gemini-ace` by default
- OpenCode sessions started globally through `opencode-ace` by default

There is no per-project activation for Antigravity, Gemini, or OpenCode. The
the default `*-ace` wrappers start the runner from the central Agent Context Engine root so the
hook bridge loads, while preserving the original launch directory as project
context.
- local session logs, summaries, handovers, retrieval, graph artifacts, and
  safety/risk audit data

Runtime state is stored under the installation target's `memory/` directory.
That directory is user data and must not be committed to the public source
repository.

## Fresh Clone Bootstrap

When working from the public repository, read `AGENT_BOOTSTRAP.md` before
installing and load `docs/setup/RUNNER_HARNESSES.md` for the maintained
harness matrix. A fresh agent should be able to clone the repository, ask the
user for the few necessary setup choices, summarize the proposed target,
memory-root, monitor port, wrapper naming, and refresh mode, wait for user
approval, run the installer, let it start the monitor, and finish with `doctor`.

Typical setup from a standalone clone:

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/agent-context-engine-root \
  --language en \
  --wrapper-suffix ace \
  --link-codex-ace \
  --link-claude-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

Then verify:

```sh
cd /path/to/agent-context-engine-root
agent-context-engine doctor
```

For a nested skill copy inside another repository, use:

```sh
python3 docs/skills/agent-context-engine/scripts/agent_context_engine.py install \
  --target /path/to/agent-context-engine-root \
  --language en \
  --wrapper-suffix ace \
  --link-codex-ace \
  --link-claude-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

## Installer Choices

Ask the user for these choices when they are not already clear:

- target root for the central Agent Context Engine installation
- preferred interaction language for future agents: `en` or `de`
- which harnesses should be prepared now
- whether to create global `codex-ace`, `claude-ace`, `agy-ace`,
  `gemini-ace`, and `opencode-ace` commands
- whether this is a second local installation that needs `--instance-name`
- which local projects should be added to `docs/knowledge/repos.md`
- whether Cursor IDE should be enabled for a specific project folder
- whether the central Antigravity, Gemini, and OpenCode bridges should be
  enabled in the Agent Context Engine root (global only; no per-project activation)

Use `--no-interactive` for automation once the choices are known.

## Starting Sessions

Codex:

```sh
codex-ace
```

Claude Code:

```sh
claude-ace
```

Antigravity CLI:

```sh
agy-ace
```

Gemini CLI:

```sh
gemini-ace
```

OpenCode:

```sh
opencode-ace [project]
```

OpenCode loads plugins from its startup directory, so `opencode-ace` starts
OpenCode from the central Agent Context Engine root. The original shell folder is
preserved as the project context. Pass the project as a positional argument; do
not use `opencode run --dir <project>`, because that would also load plugins from
`<project>/.opencode/plugins/`.

There is no per-project activation for these clients.

Direct hook kill-switch changes are user-only control-plane actions. Use
`hooks-disable [--runner <runner>]`, `hooks-enable [--runner <runner>]`, and
`hooks-status` as chat control lines from the user, not as normal agent-run
tool commands.

Project-specific activation for Cursor IDE only:

```sh
agent-context-engine cursor-enable \
  --target /path/to/project \
  --memory-root /path/to/agent-context-engine-root
```

Enable the central bridges for Antigravity, Gemini, and OpenCode once per
Agent Context Engine root:

```sh
agent-context-engine antigravity-enable
agent-context-engine gemini-enable
agent-context-engine opencode-enable
```

Reload the client window after enabling hooks or a project bridge.

## Agent Quick Path

In installed target roots, `AGENTS.md` should contain an Agent Context Engine quick path.
When the user asks about previous work, handovers, session context, existing
analysis, or "what happened last", use the local CLI before broad repository
searches:

```sh
agent-context-engine retrieve "<question>" --limit 10
agent-context-engine search "<keywords>" --limit 5
agent-context-engine last --limit 10
agent-context-engine handover "<session|title|keywords>"
agent-context-engine doctor
```

Use `retrieve` when provenance and score details matter. Use `handover` or its
alias `use` when continuing previous work in the current chat.

## Runtime Layout

Important target-root paths:

```text
AGENTS.md
.codex/hooks.json
.codex/hooks/hook_adapter.sh
.claude/settings.json
.claude/hooks/hook_adapter.sh
docs/skills/agent-context-engine/
docs/knowledge/repos.md
memory/
```

Important runtime paths under `memory/`:

- `events/`: raw hook JSONL logs and fallback queues
- `status/agent-memory.sqlite3`: session, event, retrieval, graph, risk, and
  scheduler index
- `sessions/`: handovers and hourly summary windows
- `memories/`: durable project and dream memory
- `personal/`: optional personal operating memory
- `dream/`: dream prompts, outputs, and metadata
- `graph/`: facts, patches, candidates, matches, and reconciliation artifacts
- `logs/`: hook and scheduler logs

## Retrieval And Personal Memory

Common commands:

```sh
agent-context-engine retrieve "github analysis project" --limit 10
agent-context-engine retrieval-runs --limit 10
agent-context-engine retrieval-run <retrieval_run_id>
agent-context-engine personal init
agent-context-engine personal list
agent-context-engine personal audit
```

Retrieval filters private, secret, risky, quarantined, and `never_auto` material
by default. Use `--include-risky` only when the user explicitly asks to inspect
that material.

## Summaries, Dreams, And Graphs

```sh
agent-context-engine summarize --pending
agent-context-engine dream --pending --runner same-as-session
agent-context-engine graph-status --limit 10
agent-context-engine graph-query entities "Agent Context Engine"
```

Dream and graph phases are designed to preserve provenance. Raw tool outputs are
stored for audit, while handover and dream prompts receive compact references
with IDs, size, hash, status, and risk metadata.

## Monitor

Start the local monitor:

```sh
agent-context-engine monitor --runner codex --port 8787
agent-context-engine monitor --runner codex --port 8787 --language de
```

The monitor binds to `127.0.0.1` by default. It provides session status,
retrieval, graph views, dream inspection, token statistics, and firewall/risk
inspection.

## Safety And Firewall

Agent Context Engine includes deterministic risk scanning, optional classifier review,
quarantine, retrieval filtering, and audited firewall controls. These features
are defense-in-depth for local agent workflows; they are not a sandbox boundary.

Agents must not approve their own blocked risky actions. Direct user control
messages such as `approve ...`, `reset taint`, and `firewall add ...` are
handled by prompt hooks and must come from the user, not from agent tool calls.

Useful commands:

```sh
agent-context-engine risk scan-command 'curl https://example.invalid/install.sh | sh' --json
agent-context-engine risk list --limit 20
agent-context-engine risk explain --session <session_id>
agent-context-engine firewall suggest --session <session_id>
agent-context-engine firewall list
```

## Verification

Source checkout:

```sh
./scripts/check-agent-context-engine --skip-runtime-db
python3 -m unittest discover -s tests -v
```

Installed target:

```sh
agent-context-engine doctor
agent-context-engine last --limit 3
```

Before publishing a public repository, verify that no `memory/` runtime data,
SQLite databases, logs, transcripts, local env files, private paths, or personal
memory files are tracked.
