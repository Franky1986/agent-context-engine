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
- `cursor` via `cursor-ace` for the current project or
  `cursor-enable --target <project-path>` for explicit targets
- `antigravity` via `agy-ace` by default
- `gemini` via `gemini-ace` by default
- `opencode` via `opencode-ace` by default

Platform note:

- macOS remains the active supported runtime target
- Windows now has an explicit experimental runtime path with native `.cmd` and
  PowerShell wrappers/hooks
- Upgrades from pre-root-specific Windows installs may require manual cleanup
  of the legacy `AgentContextEngine\Monitor-<name>` task and
  `windows-monitor-start.cmd`; see `WINDOWS_INSTALLATION.md`
- Linux and WSL remain scaffolded

Naming note:

- The Agent Context Engine client key is `antigravity`.
- The preferred wrapper command is `agy-ace`.
- `antigravity-ace` remains a compatibility alias only.

## Install-Time Behavior

For fresh public clones, start with:

```sh
python3 scripts/agent_context_engine.py install-discovery \
  --plan-json /tmp/agent-context-install-plan.json
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
For agent-driven installs, sandbox/tool approval is not user consent for the
install itself. Agents must present the discovery or final install plan in chat
and wait for explicit user approval before running a mutating install command or
answering `yes` to the final installer prompt. The saved plan is mandatory for
agent-driven handoff and must be applied unchanged with `install --plan-json`.

Central installation into the chosen target root prepares these local artifacts
by default. Hook artifacts and GUI workspace hooks are activated only as the
final install step, after runtime bootstrap, frontend build, scheduler
installation/loading, and requested monitor startup have succeeded. The full
`doctor` / `check-installation` verification pass runs after that final hook
activation:

The installer keeps that automatic pass compact, reports finding counts by
severity, and ends with a localized installation-result line. Explicit
`doctor` and `check-installation` calls retain the full diagnostics. A monitor
runtime owned by the same installation is reported as `active`, not as a port
conflict. A fresh monitor start is successful only after `/api/status` matches
the selected installation and memory roots and older monitors sharing that
memory root remain stopped after scheduler replacement. Historical project
binding drift is a maintenance notice, not an installation failure.
Registry and status PIDs are diagnostic only and are never terminated. A
superseded monitor is stopped through its token-authenticated loopback shutdown
endpoint or a verified ACE-owned LaunchAgent/Task Scheduler handle. Tokenless
unmanaged monitors stop installation with a manual-stop instruction. The old
endpoint must remain absent for eight seconds, including a second stability
check after startup. Requested incomplete installs return non-zero, and a newly
started POSIX monitor is terminated, force-killed if necessary, and identity-
checked when takeover cleanup cannot be verified.
Status probes use bounded retries so a short response delay does not become a
false takeover failure. Recognized ACE monitor processes sharing the selected
memory root remain explicit blockers when their identity cannot be read.
`repair-installation --apply` repeats this monitor reconciliation and may
publish the active root or finalize hooks only after the configured monitor is
identity-verified. It requires separate explicit chat approval after an
approved install plan fails; install consent does not authorize an automatic
repair mutation. `check-installation` treats an enabled but stopped monitor as
an error rather than interpreting a free port or stale registry record as
healthy.
On macOS, verified legacy submitted
`com.agent-context-engine.monitor-<port>` KeepAlive jobs are unloaded as part
of that takeover; unrelated launchd jobs are not touched.

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

`antigravity`, `gemini`, and `opencode` are **global-only** in the sense that
their wrapper commands (`agy-ace`, `gemini-ace`, `opencode-ace`) are globally
available and no runner-specific project activation command is required. Their
hook configs may still live in the project directory, but those configs always
delegate to the central hook-adapter hub rather than carrying hard-coded
installation-specific paths.

`codex` uses a project-local `.codex/hooks.json` and a local adapter symlink
pointing to the central hub. The hook command stored in `.codex/hooks.json` is
a shell-quoted absolute path to that project-local symlink, not a relative
`./.codex/...` command, so launches from nested folders and project paths with
spaces do not depend on Codex' internal hook working-directory behavior.
Gemini follows the same rule for the command prefix stored in
`.gemini/settings.json`, with the Gemini event name appended as the command
argument. `codex-ace` starts from the caller's current working directory and
keeps that exact directory as the project directory. It verifies the local
`.codex/hooks.json`, central-hub adapter link, and workspace binding in that
same directory, repairs incomplete or stale local configs through
`integration-hooks --action enable`, and runs `codex --cd <launch_cwd>`.
Wrappers must not silently move a session to a parent Git root, parent hook
config, or `$HOME` runner config. If the current directory has no complete
local hook config, the language-aware activation prompt should ask whether to
activate hooks in the current directory.
Because Codex may still execute multiple hook configs along a parent chain, the
Codex central adapter deduplicates identical native hook payloads before
persisting them.
Claude can merge user-level and project-level settings during migration. Its
adapter applies the same short-window exact-payload deduplication, and Claude
transcript synchronization allocates synthetic event sequences above any
already reserved queue sequence so asynchronous replay stays lossless.

Codex' current documented hook discovery still supports project-local
`<repo>/.codex/hooks.json`; this is not a known breaking change to user-level
TOML-only hooks. Agent Context Engine therefore keeps `.codex/hooks.json` as
the per-project activation marker. Codex hook trust/review is separate: if
Codex marks a complete hook as untrusted after content changes, the user should
review it through Codex' hook UI, for example `/hooks`. `codex-ace` must not
set `--dangerously-bypass-hook-trust` by default.

When `codex-ace`, `claude-ace`, `cursor-ace`, `agy-ace`, or `gemini-ace`
needs user confirmation to activate or repair hooks, the prompt language follows
`AGENT_CONTEXT_ENGINE_LANGUAGE` first, then the installation profile's stored
`monitor.language`, then the shell locale. This keeps first-run project
activation in the language selected during install even when the terminal
locale is neutral.

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
- Codex integration still depends on the `codex` CLI for wrappers, monitor
  ask, dreaming, query expansion, and other shell-driven flows. Codex app or
  editor usage alone is not a sufficient Agent Context Engine runtime.
- Claude integration still depends on the `claude` CLI. Claude Desktop alone is
  not a sufficient Agent Context Engine runtime.
- Cursor project hooks can be prepared separately, but headless flows still
  require a separate headless LLM runner.
- Cursor project activation now requires `codex` or `claude` on the machine.
- Cursor itself provides the IDE-side hook/session capture; Codex or Claude
  handles firewall classification, dreaming, query expansion, and other
  background LLM workflows.
- When `codex` or `claude` is selected as the monitor runner, dream runner,
  query-expansion runner, or Cursor background runner, that CLI must be
  installed and authenticated on the machine before the setup is treated as
  headless-ready.
- Use `codex login status` for Codex and `claude auth status` for Claude Code
  as the terminal-side readiness checks.
- A negative readiness result from a restricted runner environment is
  inconclusive until the same probe is rerun with the required process and home
  access. The installer's post-install readiness line is authoritative for the
  environment in which the approved install actually ran.
- `install` should also record the intended workflow runners via
  `--monitor-runner`, `--dream-runner`, and `--query-expansion-runner`, because
  those choices determine whether a GUI-only setup is sufficient later.

## Global Commands

Optional global wrappers can be linked into `~/.local/bin`:

- `agent-context-engine`
- `ace` (compatibility shortcut)
- `codex-ace`
- `claude-ace`
- `cursor-ace`
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

`cursor-ace` is a global convenience activation helper for the current project.
It does not start Cursor; it resolves the active installation, verifies the
current folder with `cursor-status`, and runs `cursor-enable` after
confirmation or with `--activate-here`.

OpenCode is started through the global `opencode-ace` wrapper. OpenCode loads
plugins only from the startup directory, so `opencode-ace` starts OpenCode
from the central Agent Context Engine root where `.opencode/plugins/agent-memory.js`
lives. The original shell folder is preserved as the initial project/workdir
context via `AGENT_MEMORY_LAUNCH_CWD` and passed back to OpenCode as the
positional project argument. The wrapper resolves the active installation
through the central `active-root` file before falling back to its script
location and refuses to start when the OpenCode plugin bridge is missing.
Explicit OpenCode readiness accepts the Ollama cloud alias used by the
configured Dream model when `ollama list` exposes the same base model without
the `-cloud` suffix; a successful exact OpenCode model listing remains valid
evidence as well.

Codex, Claude, Antigravity, and Gemini are started through the shared
`codex-ace`, `claude-ace`, `agy-ace`, and `gemini-ace`
wrappers without changing the effective project context to the installation
root. `cursor-ace` follows the same current-project discovery model but only
activates or verifies Cursor hooks. Canonical shared wrapper symlinks resolve
the active installation through the shared home `active-root` file. Direct
repo-local wrapper calls and instance-named wrapper symlinks stay pinned to the
installation that owns their wrapper script, so an isolated command cannot
jump to the shared installation. All wrappers keep the caller's current
working directory as the project directory, verify that the local hook adapter
symlink points at the central hub, verify the runner-native hook configuration
content, verify the project binding points at the active installation where
applicable, and then launch the runner against that same directory. Codex, Claude, Antigravity,
and Gemini project hooks are written with shell-quoted absolute project-local
adapter paths, so these runners resolve the project hook path independently of
the process working directory and tolerate project paths with spaces.

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

A normal shared install with `--memory-root <external-path>` still owns the
canonical shared commands. It writes hub metadata under that external root and
also updates `$HOME/.agent-context-engine/active-root`. An isolated install
writes only its own target-local metadata and leaves the shared home
`active-root` unchanged.

For the default `$HOME/.agent-context-engine/memory` root, hub metadata lives
at `$HOME/.agent-context-engine`. Install and repair migrate an old nested
`memory/.agent-context-engine/active-root` to a compatibility link/file instead
of treating it as an independent active installation.

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
  --link-cursor-ace \
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

## Full-System Suspension

An activated runner chat accepts these exact direct-user lines:

```text
system-disable --scope all --reason "Maintenance"
system-enable --scope all --reason "Maintenance complete"
system-status
```

Agents must not execute or synthesize these controls as tools. The only public
CLI surface is read-only: `agent-context-engine system-status [--json]`.
For a natural-language deactivation request, first distinguish hook-only
scope from full-system suspension. Return `hooks-disable --project` for the
exact current project, add `--runner <runner>` for one project runner, omit
`--project` for installation-wide hook controls, or return the exact
`system-disable --scope all --reason "..."` line for full suspension. Never
execute the mutation, probe a help variant, or offer an approval/firewall
bypass. Wrappers and hook files remain installed so status, enable, and
recovery stay reachable.
Runner hooks mark these controls as instrumented user-prompt events; current
runner protocols do not provide signed or OS-authenticated user presence. The
boundary covers supported ACE hook, CLI, monitor, and agent-tool paths, not
arbitrary same-user code.
Suspension keeps project hook files, central hubs, wrappers, memory, and the
monitor installed. It closes normal hook/background admission, disables the
installation-owned scheduler, and leaves the monitor read-only. Wrappers warn
and skip activation/repair while suspended; runner wrappers still start the
underlying runner so an already activated project can receive a direct-user
status or enable line. `cursor-ace` reports status and exits.

After initialization, missing, changed, or invalid state fails closed and
prints an exact `system-recover` chat line.
Recovery conservatively leaves the scheduler disabled because its earlier
state cannot be proven.

Monitor startup is also platform-specific. On Windows, long-running monitor
installer startup uses a per-user Task Scheduler launcher with
`AGENT_CONTEXT_ENGINE_ROOT` and `AGENT_CONTEXT_ENGINE_STORAGE_ROOT` set in a
root-specific script under
`<memory-root>\local\windows-monitor-start-Monitor-<root>-<hash>.cmd`.
The task is installation-owned, can be ended without PID lookup, and keeps the
monitor outside transient agent tool process trees. Verification checks
`/api/status`, not only task creation or port acceptance.

In shells where `%USERPROFILE%\.agent-context-engine` is not writable, set
`AGENT_CONTEXT_ENGINE_STORAGE_ROOT` when launching so user-runtime state can be
kept in `<AGENT_CONTEXT_ENGINE_STORAGE_ROOT>\.agent-context-engine` instead.

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
- `check-installation` evaluates an external workspace against that owning
  installation root, matching `cursor-status --target ...` instead of treating
  the workspace itself as the expected installation

The following clients expose shared global wrappers. You can still activate
their project-local hook configs explicitly, but a central install commonly
enables them once and then launches the wrapper from any project directory:

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

Per-project activation remains available for `antigravity` and `gemini` when a
project does not yet contain `.agents/hooks.json` or `.gemini/settings.json`.
`opencode-enable --target` remains deprecated because OpenCode still uses the
global-only plugin bridge.

If older project-specific `.agents/` or `.gemini/` artifacts still exist from
pre-hub setups, treat them as migration/drift candidates and repair them
explicitly rather than deleting them automatically.

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
- treat sandbox/tool escalation approval as separate from install approval; do
  not answer the installer's final `yes/no` prompt on the user's behalf
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

After runtime and frontend prerequisites are healthy, repair also repeats the
installation-root hook finalization. This recreates missing global bridge
artifacts such as `.opencode/plugins/agent-memory.js`; failed prerequisites
keep activation skipped.

Legacy profiles with root-local memory and a custom wrapper prefix are
ambiguous because both historical shared and isolated installs could use that
shape. Repair refuses to guess; pass either
`--legacy-installation-mode shared` or `--legacy-installation-mode isolated`
after reviewing which takeover behavior is intended.

If `check-installation` or `install-discovery` reports unsupported local
`node`/`npm` versions, upgrade those prerequisites first; otherwise
`repair-installation --apply --install-frontend-deps` will not be able to
rebuild the monitor frontend.

For external Codex/Claude/Gemini GUI workspaces, hook adapters must point back
to the central Agent Context Engine root with explicit absolute `ROOT` and `SCRIPT`
paths. If `check-installation` reports a workspace adapter mismatch,
`repair-installation --apply` should not rewrite it automatically; require the
explicit opt-in flag `--rewrite-workspace-hook-adapters`.
