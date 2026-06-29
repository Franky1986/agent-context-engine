# Runner And Harness Guide

This document is the maintained source of truth for Agent Context Engine harness
selection during installation, project activation, and integration Q&A.

Use it together with:

- `AGENT_BOOTSTRAP.md` for fresh-clone installation flow
- `docs/setup/WINDOWS_INSTALLATION.md` for the Windows setup contract
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

Platform note:

- macOS remains the active supported runtime target
- Windows now has an explicit experimental runtime path with native `.cmd` and
  PowerShell wrappers/hooks
- Linux and WSL remain scaffolded

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

For install language, discovery should prefer the user's current install
interaction language first. If the user switches language during the approval
flow, rerun discovery with an explicit `--language de` or `--language en`
instead of silently keeping the older checkout default.

`python3 scripts/agent_context_engine.py install` without an explicit `--target` now
uses that same discovery context. In interactive use it guides the remaining
choices, shows a final install-plan confirmation before writing files, and in
non-interactive use it prints the recommended explicit command.

Central installation into the chosen target root prepares these local artifacts
by default. Hook artifacts and GUI workspace hooks are activated only as the
final install step, after runtime bootstrap, frontend build, scheduler
installation/loading, and requested monitor startup have succeeded. The full
`doctor` / `check-installation` verification pass runs after that final hook
activation:

- Codex hooks under `.codex/`
- Claude Code hooks under `.claude/`
- Antigravity hooks under `.agents/` in the central root
- Gemini hooks under `.gemini/` in the central root
- OpenCode plugin bridge under `.opencode/plugins/` in the central root
- Agent guidance in `AGENTS.md`
- startup contract in `session-start-hook-entry.md`
- repo-local compatibility CLI under `scripts/agent-context-engine` and
  `scripts/ace`
- on Windows, the same installation also materializes `.cmd` companions for
  the public CLI and managed wrappers
- on Windows, the configured command link directory is added to the current
  process `PATH` and to the user `PATH` when missing, so `codex-ace` and other
  wrappers resolve in new shells
- installed public CLI `agent-context-engine`, relinked to the chosen
  installation by default
- default `.venv/` when `install` runs normally; use `--no-bootstrap-runtime` to skip it
- platform scheduler installation/loading by default so summaries, dreams,
  graph extraction, and catch-up work continue after hook capture; use
  `--no-install-launchagent` only as an explicit opt-out
- fresh-install discovery should still recommend scheduler installation by
  default even when an older user config stored a prior opt-out; the discovery
  output now shows whether the recommendation came from the fresh-install
  default or a saved user setting
- local frontend build prerequisites; keep `node`/`npm` aligned with the
  checked-in monitor frontend lockfile and rely on `install-discovery` /
  `check-installation` for the exact currently required version floor

Monitor status uses a fast integration summary. It reports wrapper and hook
state without blocking `/api/status` on external runner authentication or model
discovery; full readiness probes remain explicit integration checks.

Central installation does not automatically activate every client in every other
project folder.

Per-project activation remains explicit for:

- `cursor`
- external Codex GUI workspace roots that differ from the central Agent Context Engine root
- external Claude/Claude Code workspace roots that differ from the central Agent Context Engine root

`antigravity`, `gemini`, and `opencode` are **global-only**: they are started
through their `*-ace` wrappers from any directory. No project-specific
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
  require a separate headless LLM runner.
- Cursor project activation now requires `codex` or `claude` on the machine.
- Cursor itself provides the IDE-side hook/session capture; Codex or Claude
  handles firewall classification, dreaming, query expansion, and other
  background LLM workflows.
- `install` should also record the intended workflow runners via
  `--monitor-runner`, `--dream-runner`, and `--query-expansion-runner`, because
  those choices determine whether a GUI-only setup is sufficient later.

## Global Commands

Optional global wrappers can be linked into `~/.local/bin`:

- `agent-context-engine`
- `ace` (compatibility shortcut)
- `codex-ace`
- `claude-ace`
- `agy-ace`
- `gemini-ace`
- `opencode-ace`

On Windows, publication uses generated `.cmd` shims instead of symlinks.
Python-entrypoint shims must prefer `AGENT_CONTEXT_ENGINE_PYTHON`, then
`AGENT_MEMORY_PYTHON`, then the installation-local `.venv\Scripts\python.exe`
before falling back to PATH Python or `py -3`. This prevents global commands
from bypassing the runtime environment that contains the installed backend
dependencies.

The default public installation behavior is to relink these shared commands to
the chosen installation. If a previous installation already owns them, discovery
should surface that takeover in the proposed plan before the user approves the
write step.

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

If another Agent Context Engine installation already exists, the default shared
public contract is to move `agent-context-engine`, `ace`, and the shared
`*-ace` commands to the newly selected installation. Use `--isolated` when you
explicitly want side-by-side command isolation instead of takeover:

- `--isolated` for a target-local memory root and instance-specific command names
- `--instance-name <name>` to override the auto-derived isolated instance name
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
  --isolated \
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

The CLI flag names remain `launchagent-*` for compatibility, but on Windows the
same install path drives the per-user Task Scheduler job instead of a macOS
LaunchAgent.

Monitor startup is also platform-specific. On Windows, long-running monitor
startup should be hosted through `cmd.exe /c start "ace-monitor" /min ...` with
`AGENT_CONTEXT_ENGINE_ROOT` and `AGENT_CONTEXT_ENGINE_STORAGE_ROOT` set for the
child process. A detached `python.exe` process can exit immediately after
printing the monitor banner, so verification must check the bound port and
`/api/status`.

If the command-host launch does not expose a stable port from an agent-run
install, Windows autostart falls back to a per-user Task Scheduler launcher
script under `<memory-root>\local\windows-monitor-start.cmd`. That fallback is
specifically for transient agent tool processes that clean up child processes
after command completion.

For manual recovery, run `scripts\start-monitor-windows.ps1 -ReplaceExisting`
or `scripts\start-monitor-windows.cmd -ReplaceExisting` from a normal Windows
terminal. The helper records stdout/stderr under the active memory-root logs
directory and waits for both status and firewall endpoints.

Scheduler setup is part of the default install contract because background
dreaming depends on periodic catch-up. Operators may skip it only with an
explicit `--no-install-launchagent` opt-out, and diagnostics should report that
as drift until the scheduler is installed and loaded.

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
agent-context-engine cursor-enable --target /path/to/project --installation-root /path/to/agent-context-engine-root
```

To pin Cursor background workflows to a specific runner:

```sh
agent-context-engine cursor-enable --target /path/to/project --installation-root /path/to/agent-context-engine-root --background-runner claude
```

For `cursor-enable`, `antigravity-enable`, `gemini-enable`, `opencode-enable`,
and `integration-hooks`, `--installation-root` selects the Agent Context Engine
checkout that owns scripts, wrappers, templates, and hook bindings. The legacy
`--memory-root` flag remains accepted there as a compatibility alias, but it is
not the install-time runtime storage flag described above.

For Cursor specifically, `--background-runner codex` or `--background-runner claude`
pins the background LLM workflows for that workspace. The requested runner must
be installed and authenticated; Agent Context Engine must not silently switch
to the other runner after activation.

For `codex`, `claude`, and `cursor`, the workspace hook setup now also writes a
workspace binding file that points back to the owning Agent Context Engine instance.
That binding is part of the effective hook state:

- if the binding file is missing, hooks are treated as inactive
- if the binding points to a missing Agent Context Engine root, hooks are treated as inactive
- the monitor shows the binding path, target root, target instance, binding error, and effective inactive reason

The following clients are global-only. Enable their central hook bridge once per
Agent Context Engine root, then use the global wrapper from any directory:

```sh
agent-context-engine antigravity-enable
agent-context-engine gemini-enable
agent-context-engine opencode-enable
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
- whether the shared public commands should be taken over here or isolated with
  instance-specific naming
- whether this is a second installation
- whether the actual Codex/Claude/Cursor workspace root differs from the central Agent Context Engine root
- whether any local projects should be indexed immediately

Agent rule:

- answer in the user's language from the first install reply onward
- prefer discovery-driven defaults over asking for raw CLI flags
- summarize suggested target, memory root, monitor port, wrapper naming, and
  refresh mode, then wait for explicit user approval before applying them
- mention whether repo/folder entries are already known from the active memory
  root, where the runtime repo index lives, that the monitor exposes it under
  `Personal -> Repo-Index`, and that agents can add further repo/folder entries
  there later
- leave fully successful installs with the local monitor already started unless
  the user explicitly opted out; do not start a monitor when backend/runtime
  dependencies or the frontend build are incomplete
- activate hooks only as the final step of a successful install so an incomplete
  setup can still be repaired without live hook traffic

Reasonable defaults:

- prepare Codex, Claude, Antigravity, and Gemini in the central root
- activate Cursor only when a project path is named
- enable the central Antigravity, Gemini, and OpenCode bridges in the root
- relink the shared `agent-context-engine`, `ace`, and `*-ace` commands to the
  chosen installation unless the user explicitly wants isolated instance naming

## Verification

After installation or project activation, verify with:

```sh
agent-context-engine doctor
agent-context-engine check-installation
agent-context-engine monitor --runner codex --replace-existing --no-open
agent-context-engine integrations-status
agent-context-engine cursor-status --target /path/to/project
agent-context-engine gemini-status
agent-context-engine antigravity-status
agent-context-engine opencode-status
```

Verification rules:

- use the active installation command prefix for isolated installs instead of
  assuming the global `agent-context-engine` command was taken over
- for project activation, run the concrete status command for that target, for
  example `cursor-status --target /path/to/project`
- do not count `--help` output as a verification step

Use `repair-installation --apply` after review when the check reports a missing
`.venv`, missing `PyYAML`, stale/missing `frontend/dist`, or missing GUI
workspace-root hook activation.

If `check-installation` or `install-discovery` reports unsupported local
`node`/`npm` versions, upgrade those prerequisites first; otherwise
`repair-installation --apply --install-frontend-deps` will not be able to
rebuild the monitor frontend.

For external Codex/Claude/Gemini GUI workspaces, hook adapters must point back
to the central Agent Context Engine root with explicit absolute `ROOT` and `SCRIPT`
paths. If `check-installation` reports a workspace adapter mismatch,
`repair-installation --apply` should not rewrite it automatically; require the
explicit opt-in flag `--rewrite-workspace-hook-adapters`.
