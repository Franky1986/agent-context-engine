# Runner And Harness Guide

This document is the maintained source of truth for Agent Context Engine harness
selection during installation, project activation, and integration Q&A.

Use it together with:

- `AGENT_BOOTSTRAP.md` for fresh-clone installation flow
- `docs/skills/integration-management-agent.md` for status/change workflow
- `docs/runbooks/integration-management.md` for operational semantics

## Supported Clients

Agent Context Engine currently supports these interactive clients and wrappers:

- `codex` via `codex-ace` by default
- `claude` via `claude-ace` by default
- `cursor` via `cursor-enable --target <project-path>`
- `antigravity` via `agy-ace` by default
- `gemini` via `gemini-ace` by default
- `opencode` via `opencode-ace` by default

Naming note:

- The Agent Context Engine client key is `antigravity`.
- The preferred wrapper command is `agy-ace`.
- `antigravity-ace` remains a compatibility alias only.

## Install-Time Behavior

For fresh public clones, start with:

```sh
python3 scripts/agent_context_engine.py install-discovery
```

The discovery step is read-only. It reports the detected checkout root and
role, suggests the install target, shows discovered `memory_root` candidates,
and proposes safe defaults such as an isolated monitor port or the `-ace`
wrapper suffix for test installs.

`python3 scripts/agent_context_engine.py install` without an explicit `--target` now
uses that same discovery context. In interactive use it guides the remaining
choices, shows a final install-plan confirmation before writing files, and in
non-interactive use it prints the recommended explicit command.

Central installation into the chosen target root prepares these local artifacts
by default:

- Codex hooks under `.codex/`
- Claude Code hooks under `.claude/`
- Antigravity hooks under `.agents/` in the central root
- Gemini hooks under `.gemini/` in the central root
- OpenCode plugin bridge under `.opencode/plugins/` in the central root
- Agent guidance in `AGENTS.md`
- startup contract in `session-start-hook-entry.md`
- local CLI under `scripts/ace` (shortcut to `scripts/agent-context-engine`) or `docs/skills/agent-context-engine/scripts/agent-context-engine`
- default `.venv/` when `install` runs normally; use `--no-bootstrap-runtime` to skip it

Central installation does not automatically activate every client in every other
project folder.

Per-project activation remains explicit for:

- `cursor`
- external Codex GUI workspace roots that differ from the central Agent Context Engine root
- external Claude/Claude Code workspace roots that differ from the central Agent Context Engine root

`antigravity`, `gemini`, and `opencode` are **global-only**: they are started
through their `*-memory` wrappers from any directory. No project-specific
`.agents/hooks.json`, `.gemini/settings.json`, or `.opencode/plugins/agent-memory.js`
files are created anymore.

For `codex`, `claude`, and `cursor`, installation and status must distinguish
between two levels:

- `GUI hooks only`: the workspace root contains the Agent Context Engine hook files and
  the GUI can call them locally.
- `headless CLI ready`: the corresponding CLI executable also exists on the
  machine, so wrappers, monitor ask, dreaming, and other shell-driven flows can
  run.

Rules:

- Codex GUI hooks can be prepared in another workspace root via
  `--codex-workspace-root`.
- Claude integration still depends on the `claude` CLI. Claude Desktop alone is
  not a sufficient Agent Context Engine runtime.
- Cursor project hooks can be prepared separately, but headless flows still
  require `cursor-agent` plus its login/auth path.
- `install` should also record the intended workflow runners via
  `--monitor-runner`, `--dream-runner`, and `--query-expansion-runner`, because
  those choices determine whether a GUI-only setup is sufficient later.

## Global Commands

Optional global wrappers can be linked into `~/.local/bin`:

- `codex-ace`
- `claude-ace`
- `agy-ace`
- `gemini-ace`
- `opencode-ace`

`cursor` has no single global wrapper. It is activated per project.

OpenCode is started through the global `opencode-ace` wrapper. OpenCode loads
plugins only from the startup directory, so `opencode-ace` starts OpenCode
from the central Agent Context Engine root where `.opencode/plugins/agent-memory.js`
lives. The original shell folder is preserved as the initial project/workdir
context via `AGENT_MEMORY_LAUNCH_CWD` and passed back to OpenCode as the
positional project argument.

Antigravity and Gemini are started through the global `agy-ace` and
`gemini-ace` wrappers. Their hook configs are loaded from the current working
directory, so the wrappers start the runner from the central Agent Context Engine root
where `.agents/hooks.json` and `.gemini/settings.json` live. The original shell
folder is added back as a workspace via `--add-dir` / `--include-directories`,
and the hook adapters use `AGENT_MEMORY_LAUNCH_CWD` as the effective project
context.

When any linked global wrapper is started from another shell folder, Agent Context Engine
must preserve that original folder as the initial project/workdir context even
though the wrapper itself is rooted in the central installation.

That means:

- the installation root remains the hook/config owner
- the launch folder becomes the starting work context for the session
- a later explicit project switch inside the chat can move the active workdir
  again without moving the Agent Context Engine root

If another Agent Context Engine installation already exists, do not reuse the same
global command names blindly. Use:

- `--instance-name <name>` during install for isolated commands
- or `--command-prefix <prefix>` for legacy-compatible prefixes
- or `--wrapper-prefix <prefix>` / `--wrapper-suffix <suffix>` for explicit
  instance-specific command naming

Current naming note:

- the preferred public default is `--wrapper-suffix ace`, which produces `codex-ace`
- `--wrapper-prefix test-` produces `test-codex`
- `--wrapper-suffix v2` produces `codex-v2`

Example:

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/second-agent-context-engine-root \
  --instance-name client-a \
  --bootstrap-runtime \
  --link-codex-ace \
  --link-claude-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

The installation profile now also persists the default monitor host/port and
LaunchAgent identity for the instance. By default user-scoped metadata lives in
`~/.agent-context-engine`, the default install root lives in
`~/.agent-context-engine/install`, and runtime data lives in
`~/.agent-context-engine/memory`. Use:

- `--memory-root <path>` when runtime data should live somewhere else
- `--monitor-host <host>`
- `--monitor-port <port>`
- `--launchagent-label <label>`
- `--launchagent-path <plist-path>`
- `--launchagent-env-file <env-file>`

The `--memory-root` path is the persistent runtime storage root. It owns:

- SQLite
- logs
- hook queues
- dream artifacts
- session files
- materialized memories

The installation root remains the place that owns source code, scripts,
templates, wrappers, and monitor assets.

## Project Activation Commands

Use these after the central installation exists:

```sh
./docs/skills/agent-context-engine/scripts/agent-context-engine cursor-enable --target /path/to/project --memory-root /path/to/agent-context-engine-root
```

For `codex`, `claude`, and `cursor`, the workspace hook setup now also writes a
workspace binding file that points back to the owning Agent Context Engine instance.
That binding is part of the effective hook state:

- if the binding file is missing, hooks are treated as inactive
- if the binding points to a missing Agent Context Engine root, hooks are treated as inactive
- the monitor shows the binding path, target root, target instance, binding error, and effective inactive reason

The following clients are global-only. Enable their central hook bridge once per
Agent Context Engine root, then use the global wrapper from any directory:

```sh
./docs/skills/agent-context-engine/scripts/agent-context-engine antigravity-enable
./docs/skills/agent-context-engine/scripts/agent-context-engine gemini-enable
./docs/skills/agent-context-engine/scripts/agent-context-engine opencode-enable
```

After enabling the central bridge:

```sh
agy-ace
gemini-ace
opencode-ace [project]
```

Per-project `antigravity-enable --target`, `gemini-enable --target`, and
`opencode-enable --target` are deprecated and will refuse to create
project-specific hooks.

If older project-specific `.agents/`, `.gemini/`, or `.opencode/` artifacts
still exist from earlier setups, remove them after migrating to the global
wrappers so plain runner starts in those projects no longer pick up stale Agent
Context Engine hook state.

## Recommended Agent Questions

When a user asks an agent to install Agent Context Engine and details are missing, ask
only for:

- target root
- preferred interaction language
- which harnesses should be used now
- whether global wrapper links are wanted
- whether this is a second installation
- whether the actual Codex/Claude/Cursor workspace root differs from the central Agent Context Engine root
- whether any local projects should be indexed immediately

Agent rule:

- answer in the user's language from the first install reply onward
- prefer discovery-driven defaults over asking for raw CLI flags
- summarize suggested target, memory root, monitor port, wrapper naming, and
  refresh mode, then wait for explicit user approval before applying them
- leave successful installs with the local monitor already started unless the
  user explicitly opted out

Reasonable defaults:

- prepare Codex, Claude, Antigravity, and Gemini in the central root
- activate Cursor only when a project path is named
- enable the central Antigravity, Gemini, and OpenCode bridges in the root
- avoid global links unless the user asks for shell commands

## Verification

After installation or project activation, verify with:

```sh
./docs/skills/agent-context-engine/scripts/agent-context-engine doctor
./docs/skills/agent-context-engine/scripts/agent-context-engine check-installation
./docs/skills/agent-context-engine/scripts/agent-context-engine monitor --runner codex --replace-existing --no-open
./docs/skills/agent-context-engine/scripts/agent-context-engine integrations-status
./docs/skills/agent-context-engine/scripts/agent-context-engine cursor-status --target /path/to/project
./docs/skills/agent-context-engine/scripts/agent-context-engine gemini-status
./docs/skills/agent-context-engine/scripts/agent-context-engine antigravity-status
./docs/skills/agent-context-engine/scripts/agent-context-engine opencode-status
```

Use `repair-installation --apply` after review when the check reports a missing
`.venv`, missing `PyYAML`, stale/missing `frontend/dist`, or missing GUI
workspace-root hook activation.

For external Codex/Claude/Gemini GUI workspaces, hook adapters must point back
to the central Agent Context Engine root with explicit absolute `ROOT` and `SCRIPT`
paths. If `check-installation` reports a workspace adapter mismatch,
`repair-installation --apply` should not rewrite it automatically; require the
explicit opt-in flag `--rewrite-workspace-hook-adapters`.
