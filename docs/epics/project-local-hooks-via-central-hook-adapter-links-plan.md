# Epic / Design: Project-local hooks via central hook-adapter links

> Status 2026-07-13: Milestones 1-4 and isolation regression fixes are
> implemented in code; fresh-install and real-runner end-to-end validation
> remain open.


## Implementation status (updated 2026-07-13)

The central-hub model is implemented for `codex`, `claude`, `antigravity`, and
`gemini` on macOS. The remaining work is validation and release cleanup.

### Completed

| Area | What changed | Files |
|------|--------------|-------|
| Storage-root helpers | Added `storage_root()`, `active_root_path()`, `central_hub_path()`, `project_backup_dir()`, `activated_projects_path()` | `backend/src/agent_context_engine/infrastructure/config.py` |
| Central hub rendering | Added `CentralHubSpec`, `build_central_hub_spec()`, `render_central_hub_script()`, hub templates for `codex`, `claude`, `antigravity`, and `gemini` | `backend/src/agent_context_engine/application/hook_rendering/specs.py`, `renderers.py`, `__init__.py`, `templates/*-hooks/hook_hub.sh` |
| Dynamic codex template | `templates/codex-hooks/hook_adapter.sh` now uses `AGENT_CONTEXT_ENGINE_ROOT`, `AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT`, optional `AGENT_CONTEXT_ENGINE_SCRIPT` | `templates/codex-hooks/hook_adapter.sh` |
| Install / repair | `install` and `repair-installation --apply` write `active-root` and refresh the central hub set for `codex`, `claude`, `antigravity`, and `gemini` | `backend/src/agent_context_engine/interfaces/cli/commands/installation.py` |
| Activation / deactivation | `integration-hooks --client <runner> --target <path> --activate` writes runner-native project config, symlinks the local adapter to the central hub, stores central backup, updates `activated-projects.json`; disable records `disabled` | `backend/src/agent_context_engine/application/integrations.py`, `backend/src/agent_context_engine/interfaces/cli/main.py` |
| Wrappers | `scripts/codex-ace`, `scripts/claude-ace`, `scripts/agy-ace`, and `scripts/gemini-ace` keep the exact current shell directory as the project root, check the local runner-native config, support `--activate-here` or abort, and start the runner from that directory; instance-named wrappers stay pinned to their owning installation | `scripts/codex-ace`, `scripts/claude-ace`, `scripts/agy-ace`, `scripts/gemini-ace`, `scripts/lib/ace-wrapper-root.sh` |
| Specs / docs | New `hooks.spec.md`; updated `integrations.spec.md`, `RUNNER_HARNESSES.md`, `AGENT_BOOTSTRAP.md`, `docs/index.md` | `backend/src/agent_context_engine/application/hooks.spec.md`, `backend/src/agent_context_engine/application/integrations.spec.md`, `docs/setup/RUNNER_HARNESSES.md`, `AGENT_BOOTSTRAP.md`, `docs/index.md` |
| Tests | New `tests/test_central_hub_hooks.py`; updated existing hook renderer/install tests | `tests/test_central_hub_hooks.py`, `tests/test_agent_context_engine.py`, `tests/fixtures/platform_capability_agent_flow_refactor/codex_hook_adapter.sh` |

### Validation

- `python3 tests/test_central_hub_hooks.py` -> 26/26 OK, including direct hub
  execution without wrapper environment and shared/isolated wrapper symlink
  execution
- `AGENT_MEMORY_RUN_INSTALL_INTEGRATION_TESTS=1 python3 -m unittest tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_install_copies_codex_and_claude_hooks ...` → OK
- `./scripts/check --skip-runtime-db` → exit 0
- `bash -n scripts/codex-ace templates/codex-hooks/hook_adapter.sh templates/codex-hooks/hook_hub.sh` → OK

### Remaining work

1. **Fresh-install validation**  
   Run the installation flow in a fresh clone and verify `active-root`, central
   hubs, project activation, and wrapper behavior end to end.

2. **Runtime validation**  
   Start real `codex`, `claude`, `agy`, and `gemini` sessions from project
   roots and confirm that session metadata and hook capture follow the new
   project-local contract.

3. **Release cleanup**  
   Final commit/PR prep once the fresh-install and runtime checks are green.


## Goal

Global wrappers (`codex-ace`, `claude-ace`, `cursor-ace`, `agy-ace`,
`gemini-ace`, `opencode-ace`) must start from the caller's current working
directory and preserve it as the project context. Each project keeps only the
runner-native hook configuration (`.codex/hooks.json`, `.claude/settings.json`,
`.agents/hooks.json`, `.gemini/settings.json`, `.cursor/hooks.json`).
The actual hook-adapter logic is invoked through a **central, stable hub
script** under `$AGENT_CONTEXT_ENGINE_STORAGE_ROOT/.agent-context-engine/hooks/{runner}/hook_adapter.sh`.
The hub reads the active Agent Context Engine root at runtime and executes the
current installation's template, so project-local configs never contain
installation-specific paths.

When a POSIX installation moves or is replaced, only the `active-root` file
needs to be updated. Existing project hook configurations remain valid because
they still point to the same central hub path. On Windows, activation and
repair rewrite the native project-local `.cmd`/PowerShell adapter so runners do
not depend on symlink privileges.

## Important terminology change

"Global-only" for `antigravity`, `gemini`, and `opencode` in the existing
documentation means that the **wrapper commands** are globally available and
no runner-specific project activation is required. It does **not** mean that
their hook configuration cannot live in the project directory. In the new
model every supported runner may have project-local hook config files, but
these configs always delegate to the central hub rather than carrying
hard-coded installation-specific paths.

## Concrete behavior

1. Wrappers stay in the caller's current working directory.
2. The wrapper treats the exact current shell directory as the project root.
   It must not move to a parent Git root, parent hook config, or `$HOME`
   runner config.
3. The wrapper checks whether the local configuration in that directory is
   complete, active, and points to the central hub or native Windows adapter.
4. If hooks are missing, incomplete, disabled, or point to an old
   installation, the wrapper informs the user and asks whether to activate
   or repair them (interactive mode). In non-interactive mode it aborts with a
   clear message and a pointer to `--activate-here`. A `--legacy` fallback
   to the old installation-root launch mode is documented but not yet
   implemented.
5. If hooks are complete and active, the wrapper starts the runner in the
   current directory.
6. If the user declines activation in interactive mode, the wrapper aborts.
7. Activation writes the runner-native config file in the project directory.
   On POSIX it creates a local `hooks/{runner}/hook_adapter.sh` symlink
   pointing to the central hub. On Windows it writes native
   `hook_adapter.cmd`/PowerShell adapter files and does not require symlink
   privileges.
8. The central hub resolves the active installation root at runtime via
   `AGENT_CONTEXT_ENGINE_ROOT` (preferred) or the `active-root` file (fallback)
   and then executes the current installation's template.
9. Non-Agent-Context-Engine hooks are preserved and merged. If the runner
   supports multiple hooks per event, ACE hooks are appended. If not, the
   activation aborts with a clear message.
10. Activation and repair are CLI-driven; the monitor UI only shows status
    and instructions, never a one-click repair button.

## Central hub design and hub-template contract

The central directory contains a small, stable hub script per runner:

```text
$STORAGE_ROOT/.agent-context-engine/hooks/codex/hook_adapter.sh
```

The hub:

1. Resolves the effective storage root from `AGENT_CONTEXT_ENGINE_STORAGE_ROOT`
   (legacy: `AGENT_MEMORY_STORAGE_ROOT`) or `$HOME`.
2. Reads `$STORAGE_ROOT/.agent-context-engine/active-root`.
3. Exports `AGENT_CONTEXT_ENGINE_ROOT` and `AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT=codex`.
4. Executes the template at `$ROOT/templates/codex-hooks/hook_adapter.sh`
   with the same arguments and stdin.
5. If `active-root` is missing or invalid, the hub prints a warning to
   stderr and exits 0 so the runner workflow is not broken.

The templates are refactored so they **no longer contain hard-coded
installation paths or `__AGENT_CONTEXT_ENGINE_ROOT__` placeholders**. They
consume only:

- `AGENT_CONTEXT_ENGINE_ROOT` (active installation root)
- `AGENT_MEMORY_LAUNCH_CWD` (original project CWD)
- `AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT` (runner key)

This design makes the central path stable across installation moves. Only the
plain-text `active-root` file changes when the default installation changes.

## Project-local adapter symlink

In a project that has ACE hooks activated, the runner-native Codex, Claude,
Gemini, and Antigravity configs refer to shell-quoted absolute paths for the
project-local adapter symlink, for example:

```text
'/path/to/project/.codex/hooks/hook_adapter.sh'
```

The shell quoting is required for project paths that contain spaces; relative
commands remain migratable legacy config.

That project-local path is a **symlink** pointing to the stable central hub:

```text
$STORAGE_ROOT/.agent-context-engine/hooks/codex/hook_adapter.sh
```

The wrapper's "points to central hub" check means: the local symlink exists,
is not broken, and resolves to the expected central hub path for that runner.

## Root resolution contract

1. Canonical shared wrapper symlinks determine the active Agent Context Engine
   root from the shared home `active-root`; direct repo-local and
   instance-named wrappers use their owning installation. The wrapper exports
   the result as `AGENT_CONTEXT_ENGINE_ROOT`.
2. The central hub uses `AGENT_CONTEXT_ENGINE_ROOT` as its primary source.
3. If `AGENT_CONTEXT_ENGINE_ROOT` is unset, the hub derives its metadata root
   from its own resolved path and reads that root's `active-root` file.
4. If both are missing or invalid, the hub prints a warning and exits
   gracefully so the runner can continue without crashing.

## Storage root handling

All references to `~/.agent-context-engine` must be resolved against
`$AGENT_CONTEXT_ENGINE_STORAGE_ROOT/.agent-context-engine` when the environment
variable is set, with `AGENT_MEMORY_STORAGE_ROOT` as legacy fallback, otherwise
`$HOME/.agent-context-engine`. The active-root path is therefore:

```text
${AGENT_CONTEXT_ENGINE_STORAGE_ROOT:-${AGENT_MEMORY_STORAGE_ROOT:-$HOME}}/.agent-context-engine/active-root
```

Isolated installations use their own storage root and therefore their own
`active-root`, `hooks/`, `backups/`, and `activated-projects.json`.
Instance-named wrapper symlinks resolve their installation from the wrapper
script they target, so they do not depend on the shared home `active-root`.
Normal shared installs with an external memory root additionally update the
shared home `active-root` because they take over the canonical shared commands.

## Per-runner strategy

| Runner      | Config file                              | Local adapter symlink                              | Runner start behavior in new model                               |
|-------------|------------------------------------------|----------------------------------------------------|-------------------------------------------------------------------|
| codex       | `.codex/hooks.json`                      | `.codex/hooks/hook_adapter.sh` on POSIX; `.cmd`/PowerShell on Windows | `codex --cd <current_dir>` from CWD                                |
| claude      | `.claude/settings.json`                  | `.claude/hooks/hook_adapter.sh` on POSIX; `.cmd`/PowerShell on Windows | `claude` from CWD                                                 |
| cursor      | `.cursor/hooks.json`                     | `.cursor/hooks/hook_adapter.sh` on POSIX; `.cmd`/PowerShell on Windows | Cursor IDE plugin loads hooks from project                         |
| antigravity | `.agents/hooks.json`                     | `.agents/hooks/hook_adapter.sh` on POSIX; `.cmd`/PowerShell on Windows | `agy` from current directory                                      |
| gemini      | `.gemini/settings.json`                  | `.gemini/hooks/hook_adapter.sh` on POSIX; `.cmd`/PowerShell on Windows | `gemini` from current directory                                   |

OpenCode is kept out of the first milestones; its wrapper continues to start
from the ACE-Root until a clean plugin-load strategy is found.

## Decisions made

1. **macOS shell-runner rollout now covers Codex, Claude, Antigravity, and Gemini.**  
   Cursor activation is implemented; Windows has native `.cmd`/PowerShell
   project adapters with direct renderer regression coverage and remains
   experimental at the platform level.

2. **Central adapter is a stable hub that executes the active root template.**  
   The hub sets environment variables and execs the template, avoiding dead
   symlinks after installation moves.

3. **Templates become fully dynamic.**  
   No `__AGENT_CONTEXT_ENGINE_ROOT__` placeholders; templates rely only on
   `AGENT_CONTEXT_ENGINE_ROOT`, `AGENT_MEMORY_LAUNCH_CWD`, and
   `AGENT_CONTEXT_ENGINE_GLOBAL_WRAPPER_CLIENT`.

4. **Root resolution via installation ownership plus `active-root`.**
   Canonical shared wrapper symlinks read the shared home `active-root`;
   direct and instance-named wrappers use their owning installation. The hub
   uses the exported root first and otherwise derives its own metadata root
   before reading `active-root`.

5. **Normal installation always updates `active-root` and central hubs.**  
   `install`, `install-discovery`, and `repair-installation --apply` must
   rewrite `active-root` and recreate hub scripts so the system is
   self-healing after a default-installation move. Isolated installations do
   not touch the global `active-root` file and use their own storage root.

6. **Declined activation aborts in interactive mode.**  
   In non-interactive mode the wrapper also aborts with a helpful message,
   pointing the user to `--activate-here` or `--legacy`.

7. **Project activation tracking uses a central registry.**  
   `$STORAGE_ROOT/.agent-context-engine/activated-projects.json` maps project
   path -> runner -> status. The monitor reads from this single source. Doctor
   reports stale entries but does not delete them automatically.

8. **Backups stored in the activating installation's metadata root.**
   Before mutating a project-local hook config, a timestamped backup is stored
   under the metadata root resolved from the activating installation profile at
   `$STORAGE_ROOT/.agent-context-engine/backups/{project-path-hash}/` to
   avoid polluting the project's Git status. The `project-path-hash` is the
   SHA-256 digest of the absolute project path. Using an absolute path hash is
   machine-dependent but deterministic per machine, which is acceptable for local
   backups.

9. **Hook control plane remains authoritative.**  
   The template checks the central hooks-state in the active root before
   executing the hook, regardless of whether local config exists.

10. **`AGENT_MEMORY_LAUNCH_CWD` is preserved.**  
    It is set to the original project CWD so internal Agent Context Engine
    subprocesses can still distinguish the launch context.

11. **Merge rule: append when possible, abort on conflict.**  
    If the runner supports multiple hooks per event, ACE hooks are appended
    to existing ones. If the runner only supports a single hook per event and
    the event is already occupied by a non-ACE hook, activation aborts with a
    clear message.

12. **i18n for CLI prompts: English first.**  
    Prompts in the wrapper and CLI verb are English for the proof of concept.
    A follow-up milestone adds backend-side i18n.

## Deactivation semantics

When a user disables ACE hooks for a runner in a project:

1. The runner-native config file is renamed to its disabled variant
   (e.g. `.codex/hooks.json` → `.codex/hooks_deactivated.json`).
2. The local adapter symlink (e.g. `.codex/hooks/hook_adapter.sh`) may remain on
   disk; it is harmless because the runner config no longer invokes it.
3. The central registry entry for that project+runner is updated to
   `status: disabled` with the deactivation timestamp.
4. Re-activation moves the disabled config back and sets the registry entry to
   `status: active`.

## Registry status enum

The central registry `activated-projects.json` uses the following status values
per runner:

- `active`: hooks are present, enabled, and point to the central hub.
- `disabled`: hooks were explicitly disabled by the user.
- `missing`: no hook config was found for this runner.
- `error`: a structural problem was detected (broken symlink, conflict, drift).

## Repair drift definition

`doctor` / `check-installation` report hook drift when any of the following is
true:

1. `active-root` is missing or points to a non-existent directory.
2. A central hub script for a supported runner is missing or not executable.
3. The central hub script's `spec_version` differs from the expected version of
   the running installation.
4. A project in `activated-projects.json` is marked `active` but its local
   adapter symlink is missing, broken, or resolves to a path outside the expected
   central hub directory.

`repair-installation --apply` fixes items 1–3. Item 4 is reported for manual
repair via `integration-hooks --client <runner> --target <path> --repair`.

## Open risks and mitigations

| Risk | Mitigation |
|---|---|
| Tote zentrale Links nach Root-Loeschung | Hub-Design vermeidet tote Links; `install`/`repair-installation` erneuert Hubs und `active-root` |
| Verzeichnishierarchie unklar | Wrapper sucht aufwaerts bis `.git` (Datei/Verzeichnis) oder max. Tiefe/Filesystem-Root |
| `AGENT_CONTEXT_ENGINE_ROOT` vs. `active-root` divergieren | Hub verwendet Env-Variable primaer, `active-root` nur als Fallback |
| Backups vermuellen Projekt-Git | Backups liegen zentral im Storage-Root |
| Registry veraltet bei Projekt-Verschiebung | Doctor meldet tote Pfade; Repair-Flag fuer Aufrauemen kann spaeter ergaenzt werden |
| OpenCode-Plugins | Ausgenommen bis klar ist, wie Plugins ausserhalb des Startverzeichnisses geladen werden koennen |

## Affected areas

- `scripts/codex-ace` (Milestone 1)
- `scripts/claude-ace` (Milestone 2)
- `scripts/cursor-*` helpers and `cursor-enable` (Milestone 3)
- `scripts/agy-ace` and `scripts/gemini-ace` (Milestone 4)
- `scripts/opencode-ace` — no functional change in Milestones 1-4
- `templates/codex-hooks/hook_adapter.sh` (Milestone 1)
- `application/integrations.py` and runner-specific hook helpers
- `application/hook_rendering/` templates and renderer
- `application/installation.py`
- `application/hooks_state.py`
- `interfaces/cli/main.py`
- `infrastructure/config.py`
- Monitor frontend `features/integrations/*`
- i18n `frontend/src/app/i18n/en.ts` and `de.ts`
- Tests
- Documentation: `docs/setup/RUNNER_HARNESSES.md`, `AGENT_BOOTSTRAP.md`,
  `session-start-hook-entry.md`, `application/integrations.spec.md`,
  new `application/hooks.spec.md`

## Milestones and documentation sync

### Milestone 1: macOS proof of concept for codex

- Refactor `templates/codex-hooks/hook_adapter.sh` to be fully dynamic.
- Implement central hub `$STORAGE_ROOT/.agent-context-engine/hooks/codex/hook_adapter.sh`.
- Update `install` / `repair-installation` to write `active-root` and central hub.
- Rewrite `scripts/codex-ace` to stay in CWD, inspect only the local
  `.codex/hooks.json`, prompt or abort, and start `codex --cd <project_dir>`.
- Add CLI verb `agent-context-engine integration-hooks --client codex --target /path --activate`.
- Implement hook merge logic (append when possible, abort on single-hook conflict).
- Write central registry `activated-projects.json`.
- Add isolated E2E test and unit tests for root resolution / merge / fallback.
- Update `RUNNER_HARNESSES.md`, `AGENT_BOOTSTRAP.md`, `session-start-hook-entry.md`,
  and specs before marking Milestone 1 complete.

### Milestone 2: cursor

- Apply hub model to `.cursor/hooks.json` and Cursor adapter (preserving JSON responses).
- Handle `.sh` / `.cmd` adapter dual-mode for later Windows support.
- Update `cursor-enable`, `cursor-status`, and related docs.

### Milestone 3: Windows support

- Keep Windows `.cmd`/PowerShell project adapters native and avoid requiring
  symlink privileges for project hook activation.
- Keep central hub symlinks as the POSIX implementation detail.
- Update Windows installation docs.

### Milestone 4: OpenCode strategy

- Decide how to load the Agent Context Engine plugin when `opencode-ace` starts in a
  project directory. Until then, `opencode-ace` keeps starting from the ACE-Root.

### Milestone 5: i18n

- Add backend-side i18n module for CLI and wrapper prompts.
- Respect `AGENT_CONTEXT_ENGINE_LANGUAGE` and the installation profile language.

## Testing strategy

- Isolated E2E test that creates a temporary project directory, activates
  Codex hooks, and verifies the local config, the local adapter symlink, the
  central hub, the `active-root` file, and the registry entry.
- Unit tests for root resolution, hook merge logic (append vs. conflict),
  deactivation, repair drift detection, and fallback when `active-root` is missing.
- Unit test for isolated installation: separate storage root, separate hubs,
  no global `active-root` mutation.
