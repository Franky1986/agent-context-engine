# Agent Bootstrap Guide

This file is the agent-facing bootstrap path for a fresh public clone.

Use it when the user asks an agent to clone, install, initialize, or try Agent
Context Engine for a local project. The goal is to move from a fresh GitHub checkout to
a working local installation without guessing hidden project conventions.

Current platform posture:

- macOS is the active supported runtime target
- Windows is an experimental native runtime path
- Linux and WSL remain scaffolded

## Agent Contract

When a user says something like "clone agent-context-engine and initialize it", the
agent should:

1. Clone or open the repository.
2. Inspect this file, `docs/setup/RUNNER_HARNESSES.md`, and `README.md`.
3. Reply in the same language as the user's install request from the first
   answer onward.
   If the request contains an explicit German install phrase (for example `bitte installieren`),
   force the install language for that interaction to `de`.
4. Run `python3 scripts/agent_context_engine.py install-discovery --plan-json
   <file>` first for every agent-driven install. The plan file is the approval
   artifact even when target and memory-root relationships appear obvious.
   If the user later switches the install conversation language, rerun
   discovery with an explicit `--language de` or `--language en`, and carry
   that same explicit language into the final install command.
   Keep the resulting file unchanged until explicit user approval, then invoke
   `install --plan-json <file>` rather than reconstructing its options.
5. Summarize the suggested target root, memory root, monitor port, wrapper
   naming, and refresh mode, then wait for the user's approval before any
   install or refresh mutation.
   Sandbox/tool escalation approval is not sufficient. If the installer later
   shows a final `yes/no` confirmation prompt, agents must not answer `yes`
   unless the user already gave explicit chat approval for that exact plan.
   That summary should explicitly say that the proposed monitor port is only a
   discovery default and will be revalidated again immediately before config is
   written.
   It should also mention whether repo/folder entries are already known from
   the active memory root, where the runtime repo index lives, that the monitor
   exposes it under `Personal -> Repo-Index`, and that agents can add later
   repo/folder entries there.
   If the intended workflow uses `codex` or `claude` for wrappers, monitor
   ask, dream runs, query expansion, or Cursor background work, that summary
   must also state whether the matching terminal CLI is installed and
   authenticated. Codex app/editor usage alone and Claude Desktop alone do not
   satisfy that requirement.
   A negative auth result from a filesystem- or process-restricted environment
   is inconclusive. Rerun that exact readiness probe with the required access
   before reporting a runner as unauthenticated.
6. If discovery points to the central default install root
   `~/.agent-context-engine/install`, treat that as the default plan even when
   the current checkout itself is fresh. State clearly that the checkout stays
   unchanged unless the user explicitly chooses another `--target`.
7. Do not drift into extra diagnostics on an existing installation before the
   approval gate unless they are strictly needed to explain an ambiguity in the
   proposed plan.
8. If `doctor` or `check-installation` are run before approval from a
   restricted environment, do not treat permission failures such as
   `Operation not permitted`, non-writable home-directory paths, or
   `unable to open database file` as authoritative evidence that the install is
   broken. Those findings are inconclusive until rerun with the required
   permissions.
9. Ask only for additional choices that still remain genuinely open after that
   discovery summary.
10. Run the installer with explicit options.
11. Keep all writes inside the chosen target root and explicit memory root. Do
   not mutate a separate source checkout when working inside
   `agent-context-engine`.
12. Read the installer's localized final result line and authoritative
    post-install headless-CLI readiness. Its automatic
    post-install pass keeps successful output compact and reports finding
    counts by severity; run `doctor` and `check-installation` explicitly when
    detailed diagnostics are needed.
13. Ensure the installer leaves the local monitor running with the stored
    default host/port unless the user explicitly opted out. Treat monitor start
    as successful only when `/api/status` reports the selected installation
    root and memory root and superseded monitors using that memory root no
    longer remain active.
14. Explain how the user starts the selected harness.

Install and repair preserve an existing disabled or fail-closed system-control
state under the resolved memory root. They must not silently reopen admission
or reload a scheduler that the direct user suspended. Use the read-only
`agent-context-engine system-status` command to diagnose that state.
After system-control initialization, a missing or changed state file must also
remain fail-closed through its installation-specific integrity anchor.

Do not copy private runtime data into the public repository. Agent Context Engine stores
runtime state under the default user root `~/.agent-context-engine`, with the default
central install root at `~/.agent-context-engine/install` and the default runtime
storage root at `~/.agent-context-engine/memory`, unless the user explicitly chooses
another `--memory-root`. If the user chooses a source-local storage path, it must
remain gitignored.

## Required User Choices

Ask for these only when they are not already clear from the prompt or from
`install-discovery`, and still get explicit approval for the discovered
defaults before writing files:

- Target root: where the central Agent Context Engine installation should live.
- Preferred interaction language: default to English for public setups unless the user asked in another language.
  - If an explicit German install phrase like `bitte installieren` is present, default to `de`.
- Harnesses: Codex, Claude Code, Cursor IDE, Antigravity CLI (`agy`), Gemini
  CLI, OpenCode, or a subset.
- Headless runner readiness: whether `codex` and/or `claude` is installed and
  authenticated on the machine when the chosen workflow depends on it.
- Workspace roots: the actual folders opened by Codex GUI, Claude/Claude Code,
  and Cursor when they differ from the central Agent Context Engine root.
- Global commands: whether to keep the shared public command names on this
  installation. By default the installer relinks `agent-context-engine`,
  `ace`, `codex-ace`, `claude-ace`, `cursor-ace`, `agy-ace`, `gemini-ace`, and
  `opencode-ace` to the chosen target unless the user explicitly wants an
  isolated instance name instead.
- Instance name: only needed when the user already has another Agent Context Engine
  installation or wants prefixed commands.
- Project index: optional list of local projects to add to
  `memory/knowledge/repos.md` under the active runtime storage root.

Reasonable defaults:

- Target root: the cloned repository if the user wants a self-contained trial;
  otherwise another explicit workspace folder, while the runtime storage default stays `~/.agent-context-engine/memory`.
- Preferred interaction language: English for public/default setups, or the
  user's preferred language when stated. Discovery should propose the install
  language from the current install interaction before reusing an older
  checkout language.
  - Explicit German install phrasing such as `bitte installieren` must map to `de`.
- Harnesses: prepare Codex, Claude, Antigravity, and Gemini in the central
  root; enable Cursor and OpenCode per project only when requested. Cursor
  activation requires `codex` or `claude` for background LLM workflows. Do not
  treat Codex app usage or Claude Desktop as a substitute for those CLIs.
- Global commands: relink the shared public commands to the chosen
  installation by default; switch to `--instance-name` or explicit prefixes only
  when the user wants side-by-side isolated commands.
- Project index: skip initially if the user has not named projects.

## Fresh Clone Commands

From the fresh repository clone, discovery is now the preferred first step:

```sh
python3 scripts/agent_context_engine.py install-discovery \
  --plan-json /tmp/agent-context-install-plan.json
```

That reports:

- detected checkout root and role
- suggested install target
- detected `memory_root` candidates
- suggested monitor port
- suggested wrapper suffix for isolated test installs
- whether LaunchAgent should be postponed

Agents must not execute that suggested command until the user has approved the
suggested target, memory root, monitor port, wrapper naming, and whether an
existing installation should be refreshed in place.

When discovery suggests `repair_existing_installation` because a central target
already exists, the agent should stay on the approval path: summarize the
default central target, memory root, monitor port, wrapper naming, and whether
the checkout remains unchanged. Do not infer install health from pre-approval
checks that may be constrained by sandbox or home-directory permissions.

Discovery now also consults the central monitor runtime registry at
`~/.agent-context-engine/monitor-runtime.json`, which records monitor starts by
instance, host, port, PID, and timestamps. Treat that registry as a conflict
hint and visibility aid; it improves default port selection, but runtime socket
checks still remain the final truth.

Immediately before the installer writes the final monitor configuration, it
also reconciles the chosen port again against active runtime entries and live
port availability. Discovery therefore proposes a default, but the install step
still has the final chance to shift the monitor port when the earlier proposal
has gone stale.

After discovery, the minimal guided entrypoint remains:

```sh
python3 scripts/agent_context_engine.py install
```

Without explicit flags, `install` now keeps the source checkout as the source
only and suggests the central default install root under
`~/.agent-context-engine/install`, keeps prompts in the detected user language
where possible, offers safe public-checkout defaults such as the `-ace`
wrapper suffix, runtime bootstrap, shared global command relinking by default,
and scheduler installation/loading by default, shows a final install-plan confirmation,
and starts the local monitor at the end only after runtime bootstrap, frontend
build, and scheduler installation/loading succeed unless `--no-start-monitor`
is used before writing files in interactive use. Hook configs and GUI
workspace hooks are the final activation step, and the closing
`doctor`/`check-installation` pass runs after those hook files exist; if the
install remains incomplete, leave hooks inactive and rerun install or repair
after prerequisites are fixed. Once runtime and frontend prerequisites are
healthy, `repair-installation --apply` repeats installation-root hook and
global bridge finalization, including recreation of a missing OpenCode plugin
bridge. The automatic pass suppresses successful
`doctor` detail, summarizes findings, and ends with an explicit localized
installation result. A configured monitor already running for this same
installation is reported as active rather than as a port conflict. A newly
started monitor is accepted only after its status API matches both the chosen
installation and memory root; the installer also verifies that older monitors
sharing that memory root stay stopped after scheduler replacement.
Registry or status PIDs are terminated only after loopback, status identity,
and local process-command ownership checks. The same status identity contract
applies on Windows; port acceptance alone is insufficient. An incomplete
requested installation returns a non-zero exit code, and a new monitor is
rolled back if superseded-monitor cleanup cannot be verified.
On macOS this includes unloading the exact verified legacy submitted
`com.agent-context-engine.monitor-<port>` KeepAlive job before terminating its
superseded monitor process.

For `codex`, `claude`, `antigravity`, and `gemini`, installation writes the
central hook-adapter hubs under
`$AGENT_CONTEXT_ENGINE_STORAGE_ROOT/.agent-context-engine/hooks/<runner>/` and
a plain-text `active-root` file pointing to the chosen installation root. The
local project adapters are symlinks to those stable hubs, so project configs
stay valid even when the default installation moves.

For the default memory root, metadata is normalized to
`$HOME/.agent-context-engine`; install and repair migrate a legacy nested
`memory/.agent-context-engine/active-root` into a compatibility link/file and
do not treat that stale path as a second active installation.

The hub derives its metadata root from its own resolved path when runner or IDE
hooks invoke it without wrapper environment. A normal shared install with an
external memory root updates both that external hub metadata and the shared
home `active-root`; an isolated install updates only its own local metadata.
Instance-named wrapper commands are pinned to their owning installation.

When discovery detects that `agent-context-engine`, `ace`, or the shared
`*-ace` wrapper names already point at another installation, the default plan
should propose moving those links to the newly chosen installation. Agents
should present that takeover explicitly in the approval summary instead of
requiring the user to discover `--force` only after a failed first attempt.

For an agent-driven non-interactive setup, prefer an explicit command:

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/agent-context-engine-root \
  --language en \
  --bootstrap-runtime \
  --codex-workspace-root /path/to/actual/codex-workspace \
  --claude-workspace-root /path/to/actual/claude-workspace \
  --project "example=/path/to/example" \
  --wrapper-suffix ace \
  --link-codex-ace \
  --link-claude-ace \
  --link-cursor-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

For a second local installation that must keep existing shared commands
unchanged, use the deterministic isolated mode:

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/agent-context-engine-root \
  --language en \
  --isolated \
  --link-codex-ace \
  --link-claude-ace \
  --link-cursor-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

That keeps shared `agent-context-engine`, `ace`, and unprefixed `*-ace`
commands untouched, defaults runtime storage to `<target>/memory`, and
produces instance-prefixed global commands.

On Windows, installation should explain the generated `.cmd` launchers for the
public CLI, managed wrappers, and hook adapters. Do not describe the Windows
path as symlink-based by default.

After install:

```sh
cd /path/to/agent-context-engine-root
agent-context-engine doctor
agent-context-engine check-installation
agent-context-engine launchagent-status
# monitor should already be running after a fully successful install; restart it manually only if needed
agent-context-engine monitor --runner codex --port 8788 --replace-existing --no-open
```

After a fully successful install, hooks start capturing sessions immediately.
The first completed agent turn in a new session queues a small deterministic
initial dream by default, while
the scheduler (macOS LaunchAgent, Windows Task Scheduler, or the active
platform scheduler adapter) provides periodic catch-up for summaries, dreams,
graph extraction, and optional Neo4j sync.

If a specific project should be activated for a client:

```sh
cursor-ace
agent-context-engine cursor-enable \
  --target /path/to/project \
  --installation-root /path/to/agent-context-engine-root
agent-context-engine antigravity-enable
agent-context-engine gemini-enable
agent-context-engine opencode-enable
```

If Cursor should use a specific headless background runner instead of the
default auto-selection:

```sh
agent-context-engine cursor-enable \
  --target /path/to/project \
  --installation-root /path/to/agent-context-engine-root \
  --background-runner claude
```

The requested `codex` or `claude` runner must already be installed and
authenticated; Cursor activation must fail instead of silently falling back to
the other runner.

## Start Commands

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
opencode-ace
```

Cursor IDE:

```sh
cursor-ace
```

`cursor-ace` activates or verifies the current project and prints a reminder to
reload/restart Cursor if newly written hooks are not picked up immediately.

## Verification

Minimum verification:

```sh
agent-context-engine doctor
agent-context-engine last --limit 3
```

Full package verification from the source checkout:

```sh
./scripts/check-agent-context-engine --skip-runtime-db
python3 -m unittest discover -s tests -v
```

If `doctor` or `check-installation` reports missing Codex, Claude, or Cursor
binaries, keep the distinction explicit:

- GUI-only hook activation may still work for a prepared workspace root.
- headless features such as `codex-ace`, `claude-ace`, monitor ask, dream
  runners, and CLI-driven repair paths still require the corresponding CLI on
  the machine.
- `install` should therefore capture the intended workflow runners up front via
  `--monitor-runner`, `--dream-runner`, and `--query-expansion-runner`.
- `check-installation` is the preferred follow-up because it also reports
  missing `.venv`/`PyYAML`, frontend build drift, missing external
  workspace-root hook activation, unsupported local `node`/`npm` versions for
  the checked-in frontend lockfile, and when GUI-only Codex/Claude/Cursor usage
  is insufficient for the stored workflow profile.
- For external Codex/Claude/Gemini GUI workspaces, adapter rewrites should be
  treated carefully: Agent Context Engine now writes explicit absolute root/script
  paths, and any later rewrite of a mismatched adapter should require the
  explicit flag `--rewrite-workspace-hook-adapters`.

## Public Release Requirements

Before pushing this repository publicly, verify:

- `memory/` is not tracked.
- SQLite databases, logs, analysis reports, transcripts, and local env files are
  not tracked.
- No private absolute paths, credentials, or personal memories are included.
- A fresh clone can run `python3 scripts/agent_context_engine.py install --target ...`.
- The installed target can run
  `agent-context-engine doctor`.
- `docs/setup/RUNNER_HARNESSES.md` matches the supported install and activation
  commands.
