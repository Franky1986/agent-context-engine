# Integration Management Runbook

This runbook is the operational contract for managing Agent Context Engine client and
runner integrations. Use it when the task is about:

- checking integration status
- enabling or disabling hooks
- activating a client for a project
- understanding why a wrapper works only from the Agent Context Engine root
- changing or recommending mini/default models
- preparing new runner/client integrations

The public management CLI contract is `agent-context-engine` from `PATH` when
that command resolves to the active installation. For isolated installs or any
other case where `agent-context-engine` points somewhere else, use the active
installation command prefix from session-start guidance instead of silently
switching to the wrong global command.

For agent-facing execution rules, pair this runbook with:

- `docs/skills/integration-management-agent.md`

## Scope

Current integration families:

- `codex`
- `claude`
- `cursor`
- `antigravity`
- `gemini`
- `opencode`

Special current runtime caveat:

- `antigravity` is implemented across status, hooks, monitor, resume, and
  runner plumbing, but the concrete headless `agy` prompt contract remains a
  validation-sensitive path until confirmed against a real local CLI runtime.

This runbook covers both monitor-facing status semantics and the command paths
an agent should use.

When migrating from older per-project setups, explicitly check for stale
project-local `.agents/`, `.gemini/`, or `.opencode/` artifacts in external
projects. Under the current global-only model for Antigravity, Gemini, and
OpenCode, these leftovers should be removed once the central wrapper-based
bridge is enabled and verified.

## Status Model

Every integration must be reasoned about on separate axes. Do not collapse them
into a single "ready" judgement.

### 1. Runtime Ready

Meaning:

- The underlying client/runner executable and required provider path exist.

Examples:

- `codex`: `codex` exists
- `claude`: `claude` exists
- `cursor`: `cursor-agent` exists
- `antigravity`: `agy` exists
- `gemini`: `gemini` exists
- `opencode`: `opencode` exists, local provider path is available, and the
  required local model inventory is visible

This does **not** imply that:

- the global wrapper command exists in `PATH`
- hooks are enabled
- a project-level bridge is active

For `codex`, `claude`, and `cursor`, keep one more distinction explicit:

- `GUI hooks only`: hook files are prepared in the workspace root and the GUI
  can invoke them locally.
- `headless CLI ready`: the CLI executable also exists and is authenticated as
  needed for wrapper- and runner-driven flows.

### 2. Prepared

Meaning:

- Agent Context Engine has already created the local integration artifacts needed to
  operate this integration.

Examples:

- wrapper files under `scripts/`
- shell hook adapters under `.codex/`, `.claude/`, `.cursor/`, `.agents/`, `.gemini/`
- Opencode plugin bridge artifacts

Prepared does **not** imply that the wrapper is globally invokable or that the
hooks are currently enabled.

### 3. Wrapper Active

Meaning:

- The user can actually launch the integration through the Agent Context Engine wrapper
  path that matches the current setup.

Possible states:

- `global_active`
- `root_active`
- `blocked_by_hooks`
- `project_activation`
- `runner_missing`
- `not_prepared`

Interpretation:

- `global_active`:
  - the wrapper command is available in `PATH`
  - example: `claude-ace`
- `root_active`:
  - the wrapper exists under this Agent Context Engine root
  - but no global `PATH` command exists
  - use:
    - `cd <agent-context-engine-root> && ./scripts/<wrapper>`
    - or the absolute script path
- `blocked_by_hooks`:
  - the wrapper command may exist, but the local hook/config state prevents the
    intended managed flow
- `project_activation`:
  - client is enabled per target project, not as a single global wrapper
  - only `cursor` uses this mode now

### 4. Hooks

Meaning:

- The hook configuration is checked by **content**, not just by file presence.

Expected states:

- `enabled`
- `disabled`
- `disabled_by_control_plane`
- `inactive_missing_binding`
- `inactive_invalid_binding`
- `inactive_missing_target`
- `inactive_missing_cli`
- `partial`
- `configured_without_agent_memory`
- `not_prepared`
- `not_supported`

Rules:

- enabling must merge Agent Context Engine hook content into an existing config
- disabling must preserve the user's file by moving the active config to a
  `_deactivated` variant
- when other hook entries exist, Agent Context Engine must preserve them
- `disabled_by_control_plane` means the local config may still be present, but
  effective hook execution is centrally suppressed
- for `codex`, `claude`, and `cursor`, a missing or broken workspace binding
  file makes the effective hook state inactive even when the local hook config
  still exists

### 5. Workspace Binding

For `codex`, `claude`, and `cursor`, the local hook configuration and the
workspace-to-instance binding are separate concerns.

The monitor and CLI should surface at least:

- binding file path
- bound Agent Context Engine root
- bound Agent Context Engine instance id
- whether that root exists
- whether the bound Agent Context Engine CLI exists
- last binding parse or resolution error when present
- whether the binding points at the expected instance or a different one

If the binding file is missing or points to a dead target, treat the hook as
effectively inactive instead of assuming that the local hook config alone is
sufficient.

## Hook Control Plane

User-only commands:

```sh
hooks-disable [--runner <runner>] [--reason "..."]
hooks-enable [--runner <runner>] [--reason "..."]
hooks-status
```

Precedence:

- global disabled wins over every runner state
- otherwise runner overrides apply
- otherwise hooks are effectively enabled

Operational rules:

- agents must not execute these control-plane mutations themselves
- the monitor may display them, but not perform them as a normal mutation
- when disabled, the relevant hook path must no-op instead of partially
  running

## Global vs Root Wrapper Semantics

This distinction must stay explicit in the monitor and in agent guidance.

### Global

A wrapper is global only if the command resolves from any shell location:

```sh
which codex-ace
which claude-ace
which agy-ace
which gemini-ace
which opencode-ace
```

If `which` returns nothing, the wrapper is **not** global.

### Root-only

If the wrapper script exists under this repository but is not in `PATH`, it is
root-active only.

Examples:

```sh
cd /path/to/agent-context-engine-root && ./scripts/gemini-ace
cd /path/to/agent-context-engine-root && ./scripts/opencode-ace
cd /path/to/agent-context-engine-root && ./scripts/agy-ace
```

Agents must not claim global availability unless the actual global command is
resolvable in `PATH`.

## Root Wrapper Vs Project Context

Global/root wrappers and active project context are separate concerns.

- `Agent Context Engine root` stays the installation root that owns wrappers, hooks,
  monitor state, and the local CLI.
- `Project workdir` is the repo/folder the user actually wants to work in.

For the root-managed wrappers (`codex-ace`, `claude-ace`, `agy-ace`,
`gemini-ace`, `opencode-ace`):

- the wrapper may start the runner from the Agent Context Engine root
- but it must preserve the original shell folder as the initial workdir
  context when launched from somewhere else
- later explicit project switches inside the chat change the active workdir for
  the agent task, not the Agent Context Engine root itself

This distinction is mandatory when explaining or debugging session metadata:

- `cwd` may still point at the root-managed launch path
- `last_workdir` is the effective project folder the session worked against

Mention a project switch only when the user explicitly requests one. A repo
name used only for reference or context lookup does not change the active
workdir.

## User-Facing Command Contract

### Codex

Primary wrapper:

```sh
cd /path/to/agent-context-engine-root && ./scripts/codex-ace
```

Global command, only if linked in `PATH`:

```sh
codex-ace
```

If only the Codex GUI workspace is prepared but `codex` is missing, say that
explicitly. GUI-only hook capture may work, but `codex-ace`, `codex exec`,
monitor ask with runner `codex`, and Dreaming do not.

### Claude

Primary wrapper:

```sh
cd /path/to/agent-context-engine-root && ./scripts/claude-ace
```

Global command, only if linked in `PATH`:

```sh
claude-ace
```

Claude Desktop must not be treated as equivalent to Claude Code CLI here. If
`claude` is missing, the integration is not headless-ready even if a separate
GUI/editor experience exists elsewhere.

### Gemini CLI

Primary wrapper:

```sh
cd /path/to/agent-context-engine-root && ./scripts/gemini-ace
```

Global command, only if linked in `PATH`:

```sh
gemini-ace
```

Gemini loads hooks from the current working directory. The wrapper starts
Gemini from the central Agent Context Engine root so `.gemini/settings.json` and its
hook adapter are loaded, then adds the original launch directory back to the
workspace via `--include-directories`. The hook adapter uses
`AGENT_MEMORY_LAUNCH_CWD` as the effective project context.

Global hook bridge setup (run once per Agent Context Engine root):

```sh
agent-context-engine gemini-enable
```

`gemini-enable --target <project-path>` is deprecated and refused. Gemini
Agent Context Engine is global-only; `gemini` alone in a project does not activate
Agent Context Engine hooks.

### Antigravity CLI

Primary wrapper:

```sh
cd /path/to/agent-context-engine-root && ./scripts/agy-ace
```

Global command, only if linked in `PATH`:

```sh
agy-ace
```

Compatibility alias:

```sh
antigravity-ace
```

Antigravity loads hooks from the current working directory. The wrapper starts
Antigravity from the central Agent Context Engine root so `.agents/hooks.json` and its
hook adapter are loaded, then adds the original launch directory back as a
workspace via `--add-dir`. The hook adapter uses `AGENT_MEMORY_LAUNCH_CWD` as
the effective project context.

Global hook bridge setup (run once per Agent Context Engine root):

```sh
agent-context-engine antigravity-enable
```

`antigravity-enable --target <project-path>` is deprecated and refused.
Antigravity Agent Context Engine is global-only; `agy` alone in a project does not
activate Agent Context Engine hooks.

### Opencode

Primary wrapper:

```sh
cd /path/to/agent-context-engine-root && ./scripts/opencode-ace
```

Global command, only if linked in `PATH`:

```sh
opencode-ace [project]
```

OpenCode loads plugins only from its startup directory. The wrapper starts
OpenCode from the central Agent Context Engine root so `.opencode/plugins/agent-memory.js`
is loaded, then passes the original launch directory back as the project
argument via `AGENT_MEMORY_LAUNCH_CWD`.

Global plugin bridge setup (run once per Agent Context Engine root):

```sh
agent-context-engine opencode-enable
```

`opencode-enable --target <project-path>` is deprecated and refused. OpenCode
Agent Context Engine is global-only; starting `opencode` directly in a project does not
activate Agent Context Engine hooks.

Caveat: OpenCode also loads plugins from whichever directory it treats as the
active project. When using `opencode run --dir <project>`, plugins inside
`<project>/.opencode/plugins/` will load too. To avoid project-specific plugins,
pass the project as a positional argument or work in the Agent Context Engine root and
let `AGENT_MEMORY_LAUNCH_CWD` carry the project context.

### Cursor

Cursor is not a single global wrapper flow. It is activated per project.

Project activation:

```sh
agent-context-engine cursor-enable --target <project-path>
```

To pin a specific background runner instead of using auto-selection:

```sh
agent-context-engine cursor-enable --target <project-path> --background-runner claude
```

Operational rules for activation:

- if the requested target path does not exist, do not silently rewrite it to a
  different sibling path after multiple guesses; confirm the exact target
  before writing
- for isolated installs, use the active installation command prefix rather than
  assuming the global `agent-context-engine` command points at that instance
- after `cursor-enable`, verify with `cursor-status --target <project-path>` or
  by inspecting the generated binding and hook files; `--help` output is not a
  verification step

After activation:

- open the target project in Cursor
- work there normally
- Agent Context Engine hooks act inside that project
- required background LLM workflows use `codex` or `claude`, not `cursor-agent`
- if neither `codex` nor `claude` is installed, `cursor-enable` should fail
  instead of leaving a misleading partial-ready Cursor setup
- if `--background-runner claude` or `--background-runner codex` is used, the
  requested runner must be installed and authenticated; do not silently fall
  back to the other runner
- `codex` and `claude` both have explicit CLI auth contracts, but they differ:
  use `codex login status` for Codex and `claude auth status` for Claude Code.
  Do not invent a fake `claude status` contract; point users to
  `claude auth login` when Claude is not authenticated.
- if `cursor-enable --target ...` points at a path that does not exist, stop
  immediately and correct the target path; do not create a new folder under the
  installation root, and do not continue by trying `opencode-enable`,
  `gemini-enable`, or other unrelated client activation commands

## Hook Management Rules

### Enable

When enabling hooks:

- merge Agent Context Engine hook entries into the current config
- preserve unrelated existing hook entries
- restore from a known `_deactivated` file if no active config exists
- refresh or recreate the local hook adapter / plugin bridge file if needed

### Disable

When disabling hooks:

- do not destructively delete the user's configuration
- rename the active Agent Context Engine-managed config to a `_deactivated` variant
- preserve any other hook content in that renamed file

### Content Verification

An integration is not "hook-enabled" just because a config file exists.

It is hook-enabled only if:

- the expected Agent Context Engine command or plugin reference is present
- the expected event groups are present for that client

## Installation Diagnostics

Use these commands when installation quality is the issue rather than just
hook-state toggling:

```sh
agent-context-engine doctor
agent-context-engine integrations-status
agent-context-engine check-installation
```

Use `check-installation` when the issue could involve:

- a missing local `.venv`
- missing `PyYAML`
- a stale or missing `frontend/dist`
- Codex/Claude/Cursor GUI workspace roots that differ from the central
  installation root
- a stored workflow choice such as Dreaming or monitor ask that still requires
  a headless CLI although only GUI hooks were prepared

Use `repair-installation --apply` only after the user agrees with the proposed
repair actions. The monitor must stay read-only for these integration repairs;
it may show the exact agent command, but it must not execute the change itself.
For external Codex/Claude/Gemini workspaces, prefer an explicit adapter review
first: if the current hook adapter points to a different root or script,
require `--rewrite-workspace-hook-adapters` before rewriting it.

## Model Discovery And Changes

Model discovery must stay native to the integration/provider.

### Gemini

Discovery source:

- Gemini CLI model discovery / model command path

Agent rule:

- do not hardcode the currently recommended mini model as the only option
- probe the available Gemini model surface first
- then recommend and optionally switch

### Opencode

Current first supported local provider path:

- `ollama`

Current recommended local mini/default path:

- `ollama/gemma4:latest`

Discovery sources:

- Opencode model listing
- local Ollama inventory

If the preferred model is missing:

- recommend the exact model
- ask the user before a model download such as `ollama pull ...`

## Monitor Behavior Contract

The monitor must show these axes separately:

- runtime ready
- prepared
- wrapper active
- hooks
- global command available
- root path
- activation command or wrapper command

The monitor must not imply that:

- `ready` means globally invokable
- `prepared` means hook-enabled
- `root_active` means a command works from `~`

All monitor text must be language-toggle-aware. New integration text must not
ship as hardcoded English-only prose in a German view or vice versa.

## Agent Workflow

When asked to manage integrations, use this sequence:

1. inspect integration status first
2. determine whether the issue is runtime, wrapper, hook, or model related
3. prefer merge-based enable flows over rewriting configs from scratch
4. preserve unrelated user hooks
5. explain global-vs-root availability exactly
6. only trigger model downloads after user confirmation

## Files That Define The Integration System

- `backend/src/agent_context_engine/application/integrations.py`
- `backend/src/agent_context_engine/application/integrations.spec.md`
- `frontend/src/features/integrations/IntegrationsPanel.tsx`
- `frontend/src/features/integrations/integrations.spec.md`
- `docs/architecture/CONTRACTS.md`
- `AGENTS.md`
