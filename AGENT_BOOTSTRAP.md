# Agent Bootstrap Guide

This file is the agent-facing bootstrap path for a fresh public clone.

Use it when the user asks an agent to clone, install, initialize, or try Agent
Context Engine for a local project. The goal is to move from a fresh GitHub checkout to
a working local installation without guessing hidden project conventions.

## Agent Contract

When a user says something like "clone agent-context-engine and initialize it", the
agent should:

1. Clone or open the repository.
2. Inspect this file, `docs/setup/RUNNER_HARNESSES.md`, and `README.md`.
3. Reply in the same language as the user's install request from the first
   answer onward.
4. Run `python3 scripts/agent_context_engine.py install-discovery` first when this is a
   fresh public clone or the target/memory-root relationship is still unclear.
5. Summarize the suggested target root, memory root, monitor port, wrapper
   naming, and refresh mode, then wait for the user's approval before any
   install or refresh mutation.
   That summary should explicitly say that the proposed monitor port is only a
   discovery default and will be revalidated again immediately before config is
   written.
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
12. After install, run `doctor` and `check-installation`.
13. Ensure the installer leaves the local monitor running with the stored default host/port unless the user explicitly opted out.
14. Explain how the user starts the selected harness.

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
- Harnesses: Codex, Claude Code, Cursor IDE, Antigravity CLI (`agy`), Gemini
  CLI, OpenCode, or a subset.
- Workspace roots: the actual folders opened by Codex GUI, Claude/Claude Code,
  and Cursor when they differ from the central Agent Context Engine root.
- Global commands: whether to create `codex-ace`, `claude-ace`,
  `agy-ace`, `gemini-ace`, and/or `opencode-ace` symlinks in
  `~/.local/bin`.
- Instance name: only needed when the user already has another Agent Context Engine
  installation or wants prefixed commands.
- Project index: optional list of local projects to add to
  `docs/knowledge/repos.md`.

Reasonable defaults:

- Target root: the cloned repository if the user wants a self-contained trial;
  otherwise another explicit workspace folder, while the runtime storage default stays `~/.agent-context-engine/memory`.
- Preferred interaction language: English for public/default setups, or the
  user's preferred language when stated.
- Harnesses: prepare Codex, Claude, Antigravity, and Gemini in the central
  root; enable Cursor and OpenCode per project only when requested.
- Global commands: create them only if the user wants convenient shell commands.
- Project index: skip initially if the user has not named projects.

## Fresh Clone Commands

From the fresh repository clone, discovery is now the preferred first step:

```sh
python3 scripts/agent_context_engine.py install-discovery
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
wrapper suffix, runtime bootstrap, disabled global PATH links by default, and
delayed LaunchAgent installation, shows a final install-plan confirmation, and
starts the local monitor at the end unless `--no-start-monitor` is used before
writing files in interactive use.

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
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

For a second local installation, avoid replacing existing global commands:

```sh
python3 scripts/agent_context_engine.py install \
  --target /path/to/agent-context-engine-root \
  --language en \
  --instance-name client-a \
  --link-codex-ace \
  --link-claude-ace \
  --link-agy-ace \
  --link-gemini-ace \
  --link-opencode-ace \
  --no-interactive
```

That produces prefixed global commands such as `client-a-codex-ace`,
`client-a-claude-ace`, `client-a-agy-ace`, `client-a-gemini-ace`, and
`client-a-opencode-ace`.

After install:

```sh
cd /path/to/agent-context-engine-root
./docs/skills/agent-context-engine/scripts/agent-context-engine doctor
./docs/skills/agent-context-engine/scripts/agent-context-engine check-installation
./docs/skills/agent-context-engine/scripts/agent-context-engine launchagent-status
# monitor should already be running after install; restart it manually only if needed
./docs/skills/agent-context-engine/scripts/agent-context-engine monitor --runner codex --port 8788 --replace-existing --no-open
```

The hooks start capturing sessions immediately. The first completed agent turn
in a new session queues a small deterministic initial dream by default, while
the LaunchAgent provides periodic catch-up for summaries, dreams, graph
extraction, and optional Neo4j sync.

If a specific project should be activated for a client:

```sh
./docs/skills/agent-context-engine/scripts/agent-context-engine cursor-enable \
  --target /path/to/project \
  --memory-root /path/to/agent-context-engine-root
./docs/skills/agent-context-engine/scripts/agent-context-engine antigravity-enable \
  --target /path/to/project \
  --memory-root /path/to/agent-context-engine-root
./docs/skills/agent-context-engine/scripts/agent-context-engine gemini-enable \
  --target /path/to/project
./docs/skills/agent-context-engine/scripts/agent-context-engine opencode-enable \
  --target /path/to/project \
  --memory-root /path/to/agent-context-engine-root
```

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

Open the project folder after `cursor-enable`; reload the Cursor window if it
was already open.

## Verification

Minimum verification:

```sh
./docs/skills/agent-context-engine/scripts/agent-context-engine doctor
./docs/skills/agent-context-engine/scripts/agent-context-engine last --limit 3
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
  workspace-root hook activation, and when GUI-only Codex/Claude/Cursor usage
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
  `./docs/skills/agent-context-engine/scripts/agent-context-engine doctor`.
- `docs/setup/RUNNER_HARNESSES.md` matches the supported install and activation
  commands.
