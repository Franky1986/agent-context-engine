# Spec: Central Hook Adapter Hub

## Purpose

This spec defines the active contract for project-local hooks that delegate to
a stable, central hook-adapter hub. It applies to `codex`, `claude`,
`cursor`, `antigravity`, and `gemini` on macOS first; other runners follow in
later milestones.

## Goals

- Wrappers (`codex-ace`, `claude-ace`, `agy-ace`, `gemini-ace`) start from the
  caller's current working directory and preserve it as the project context;
  `cursor-ace` activates or verifies Cursor hooks for that project and exits.
- Each project keeps only the runner-native hook configuration (e.g.
  `.codex/hooks.json`).
- On POSIX, the actual hook-adapter logic is invoked through a central, stable
  hub script that resolves the active installation at runtime. On Windows,
  project-local `.cmd`/PowerShell adapters are rendered natively to avoid
  symlink privilege requirements.
- Project-local configs never contain installation-specific paths.
- When a POSIX installation moves or is replaced, only the `active-root` file
  needs to be updated. On Windows, repair rewrites native project-local
  `.cmd`/PowerShell adapters instead of relying on symlinked hubs.

## Central storage layout

```text
$AGENT_CONTEXT_ENGINE_STORAGE_ROOT/.agent-context-engine/
├── active-root                 # plain-text path to the active install root
├── hooks/
│   ├── codex/                  # POSIX central hubs
│   │   └── hook_adapter.sh     # stable central hub for codex
│   ├── claude/
│   │   └── hook_adapter.sh     # stable central hub for claude
│   └── ...
├── backups/
│   └── {sha256(project-path)}/
│       └── hooks.json.{timestamp}.bak
└── activated-projects.json     # project path -> runner -> status
```

Writers resolve `$AGENT_CONTEXT_ENGINE_STORAGE_ROOT`, then
`$AGENT_MEMORY_STORAGE_ROOT`, then `$HOME`. A central hub invoked without
those variables derives its metadata root from its own resolved filesystem
path under `<metadata-root>/.agent-context-engine/hooks/<runner>/`. This keeps
direct runner, GUI, and IDE hook calls bound to the hub they actually reached.

Default home-storage installs write the active installation root to
`$HOME/.agent-context-engine/active-root`. A shared install with an external
memory root writes both its external hub metadata and the shared home
`active-root`, because it takes over canonical shared commands. Isolated
installs write only to their own metadata root and must not overwrite the
user-global active root.

Install and repair normalize the default memory root before reading, writing,
or checking metadata. If an older installation left
`$HOME/.agent-context-engine/memory/.agent-context-engine/active-root`, POSIX
migrates that file to a compatibility symlink targeting the canonical home
`active-root`; Windows refreshes it as a compatibility file. Fresh installs do
not create the legacy nested path.

## Hub-template contract

The central hub (`hooks/<runner>/hook_adapter.sh`):

1. Resolves the effective storage root from explicit environment variables or,
   when they are absent, from the hub's own resolved path.
2. Reads `$STORAGE_ROOT/.agent-context-engine/active-root`. For the default
   home storage layout this is `$HOME/.agent-context-engine/active-root`, not
   `$HOME/.agent-context-engine/memory/.agent-context-engine/active-root`.
3. Exports `AGENT_CONTEXT_ENGINE_ROOT` and
   `AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT=<runner>`.
4. Preserves `AGENT_MEMORY_LAUNCH_CWD` (set by the wrapper).
5. Resolves the CLI script path by convention under the active root.
6. `exec`s the active root template at
   `$ROOT/templates/<runner>-hooks/hook_adapter.sh` with the same arguments and
   stdin.

The installation-specific template is fully dynamic:

- It uses `AGENT_CONTEXT_ENGINE_ROOT` to locate `memory/local/hooks-state.json`
  and log files.
- It uses `AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT` for runner-specific
  control-plane checks.
- It contains no hard-coded paths or placeholder replacements.

## Wrapper contract

`scripts/codex-ace`, `scripts/claude-ace`, `scripts/agy-ace`, and
`scripts/gemini-ace`:

1. Stays in the caller's current working directory.
2. Resolves `AGENT_CONTEXT_ENGINE_ROOT` according to wrapper ownership:
   explicit environment override first; direct repo-local and instance-named
   wrappers use their owning installation; canonical shared wrapper symlinks
   follow the shared home `active-root` takeover contract.
3. Treat the exact current shell directory as the project root. Parent Git
   roots, parent hook configs, and `$HOME` runner configs must not silently
   replace the launch directory.
4. Check whether the local config is complete and whether the local adapter
   points to the expected central hub or native Windows adapter. A pre-existing config is not
   enough by itself; for Codex the wrapper verifies that all Agent Context
   Engine hook events and adapter commands are present in valid JSON before
   treating the project as active. The central hub target must exist and be
   executable. Codex and Claude also verify that the workspace binding file
   points at the active installation root.
5. In interactive mode, prompts to activate if hooks are missing/incomplete.
   In non-interactive mode, aborts with a pointer to
   `integration-hooks --client codex --target <path> --activate`.
   The interactive wrappers choose the prompt language from
   `AGENT_CONTEXT_ENGINE_LANGUAGE`, then the installation profile's
   `monitor.language`, then locale variables.
6. Start the runner from the current project directory while preserving
   `AGENT_MEMORY_LAUNCH_CWD`.
7. Codex uses `codex --cd <current_dir> ...`; Claude uses
   `cd <current_dir> && exec claude ...` because the CLI has no `--cd`
   equivalent.
8. Antigravity and Gemini also start directly from the current directory
   because their local hook configs now live there and delegate through the
   central hub.

## Codex hook source contract

Codex' documented hook discovery model supports both project-local
`<repo>/.codex/hooks.json` and inline hook tables in `<repo>/.codex/config.toml`
or user-level config. This central-adapter design intentionally keeps
project-local `.codex/hooks.json` as the activation marker and does not install
a global user-level TOML bridge by default.

Hook trust is a separate Codex concern. Non-managed command hooks can require a
Codex trust review when hook content changes. `codex-ace` must not bypass that
review by default; if Codex skips a syntactically correct and complete hook
because trust is stale, the user-facing recovery path is Codex' hook review UI,
for example `/hooks`, not a blanket `--dangerously-bypass-hook-trust` wrapper
flag.

## Activation contract

`agent-context-engine integration-hooks --client <runner> --target <path> --activate`:

1. Writes the runner-native hook config (`.codex/hooks.json` or
   `.claude/settings.json`) merged with existing non-Agent-Context-Engine
   hooks; append when possible, abort on single-hook conflict.
2. Creates `.codex/hooks/hook_adapter.sh` or
   `.claude/hooks/hook_adapter.sh` as a symlink to the central hub. Claude
   settings reference that symlink through
   `${CLAUDE_PROJECT_DIR}/.claude/hooks/hook_adapter.sh`; older relative ACE
   commands are removed during repair.
3. Stores a timestamped backup of the previous config in the metadata root
   resolved from the activating installation profile, never from unrelated
   process-global storage state.
4. Records the project as `active` in `activated-projects.json`.

Deactivation renames `.codex/hooks.json` to `.codex/hooks_deactivated.json` and
records `disabled` in the registry.

## Registry status values

- `active`: hooks present, enabled, and pointing to the central hub.
- `disabled`: hooks were explicitly disabled by the user.
- `missing`: no hook config found for this runner.
- `error`: a structural problem was detected (broken symlink, conflict, drift).

## Repair drift

`doctor` / `check-installation` report hook drift when:

1. `active-root` is missing or points to a non-existent directory.
2. The central hub script for a supported runner is missing or not executable.
3. The central hub's spec version differs from the running installation.
4. A project marked `active` has a missing, broken, or misdirected local adapter
   symlink.

`repair-installation --apply` fixes items 1–3. Project-level item 4 is repaired
via `integration-hooks --client <runner> --target <path> --activate`.

## OpenCode / Windows / Cursor

- OpenCode remains global-only for the first milestones; its wrapper continues
  to start from the Agent Context Engine root.
- Cursor is handled in a separate milestone because its adapter must return
  JSON responses to before-hooks.
- Windows project activation writes native `.cmd` launchers with PowerShell
  companions. It does not depend on POSIX hub symlinks or Windows symlink
  privileges.

## System suspension

- The installation-specific system admission gate is orthogonal to the
  preserved hook-control document.
- Exact direct-user system controls run before hook-state and admission checks.
- The hook entry records `instrumented_runner_event_unverified`; runner-native
  payloads do not provide cryptographic or OS-authenticated user presence.
- When admission is closed, other hook events return success without capture,
  retrieval, classification, dreaming, or queue work.
- `hooks-status` remains readable while suspended; hook mutations are rejected
  so the restoration snapshot cannot drift.

## Related documents

- `docs/setup/RUNNER_HARNESSES.md`
- `AGENT_BOOTSTRAP.md`
- `session-start-hook-entry.md`
- `application/integrations.spec.md`
