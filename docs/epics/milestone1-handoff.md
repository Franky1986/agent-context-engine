# Handoff: Milestone 1 - Project-local hooks via central hook-adapter hub

> Branch: `feat/central-hook-adapters`
> Workspace: public development checkout
> Active runtime installation during validation: separate test checkout
> Date: 2026-07-07

## Goal

`codex-ace` now starts in the current project directory, keeps that project as
the active context, and delegates through a central, stable hook-adapter hub in
the active Agent Context Engine installation. Local projects only contain
runner-native configuration files, such as `.codex/hooks.json`, plus a symlink
to the central hub.

## Decisions already made and implemented

1. **`--legacy` is removed.**
   There is no fallback to the old ACE-root startup mode. If hooks are not
   active, `codex-ace` exits and points the user to `--activate-here` or the
   `integration-hooks` command. Users must either activate the current project
   or start plain `codex` without ACE hooks.

2. **The current workspace was not retargeted.**
   `repair-installation --apply` was intentionally not run here. The
   `active-root` entry still points at the existing installation. This code is
   meant to be tested and initialized from a fresh clone.

3. **English and German i18n are part of the wrapper contract.**
   `scripts/codex-ace` reads `AGENT_CONTEXT_ENGINE_LANGUAGE`, `LANG`, and
   `LC_ALL`, then renders prompts in `en` or `de`. More languages can be added
   later through the same `_msg_*` pattern.

4. **Hub scaffolding now covers all central shell runners.**
   The central hub is wired for `codex`, `claude`, `gemini`, and `antigravity`.
   The templates are environment-variable driven and are written under the
   installation-specific metadata root.

5. **Isolated installations own their hub metadata.**
   Hub files, `active-root`, and `activated-projects.json` are scoped to the
   concrete installation metadata root. They no longer drift to a global
   metadata path when `AGENT_CONTEXT_ENGINE_STORAGE_ROOT` is used.

## Completed work

| Area | Done | Important files |
|------|------|-----------------|
| Storage-root helpers | yes | `backend/src/agent_context_engine/infrastructure/config.py` |
| Central hub for Codex | yes | `templates/codex-hooks/hook_hub.sh`, `backend/src/agent_context_engine/application/hook_rendering/` |
| Central hub for Claude | yes | `templates/claude-hooks/hook_hub.sh` |
| Central hubs for Gemini and Antigravity | yes | `templates/gemini-hooks/hook_hub.sh`, `templates/antigravity-hooks/hook_hub.sh` |
| Dynamic templates | yes | `templates/*-hooks/hook_adapter.sh`, `templates/*-hooks/hook_hub.sh` |
| Install/repair writes `active-root` and hubs | yes | `backend/src/agent_context_engine/interfaces/cli/commands/installation.py` |
| Activation/deactivation with registry and backup | yes | `backend/src/agent_context_engine/application/integrations.py` |
| CLI: `integration-hooks --activate` | yes | `backend/src/agent_context_engine/interfaces/cli/main.py` |
| Project-local wrappers with upward search and activation prompts | yes | `scripts/codex-ace`, `scripts/claude-ace`, `scripts/gemini-ace`, `scripts/agy-ace` |
| Specs and docs updated | yes | `backend/src/agent_context_engine/application/hooks.spec.md`, `backend/src/agent_context_engine/application/integrations.spec.md`, `docs/setup/RUNNER_HARNESSES.md`, `AGENT_BOOTSTRAP.md`, `docs/index.md` |
| Tests | yes | `tests/test_central_hub_hooks.py`, updated `tests/test_agent_context_engine.py` |

## Validation currently green

```sh
python3 -m unittest tests.test_central_hub_hooks -v
AGENT_MEMORY_RUN_INSTALL_INTEGRATION_TESTS=1 python3 -m unittest tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_install_copies_codex_and_claude_hooks tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_shell_hook_renderer_substitutes_placeholders tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_bash_hook_renderer_preserves_current_codex_contract tests.test_agent_context_engine.AgentContextEngineEndToEndTests.test_cursor_hook_renderer_pins_installation_root -v
bash -n scripts/codex-ace templates/codex-hooks/hook_adapter.sh templates/codex-hooks/hook_hub.sh templates/claude-hooks/hook_adapter.sh templates/claude-hooks/hook_hub.sh
git diff --check
python3 scripts/update_docs_index.py --check
npm run build
./scripts/check --skip-runtime-db --skip-tests
```

The full `./scripts/check --skip-runtime-db` gate should still be run once more
before merge because the final review-fix pass only completed the fast check
without the complete unit suite.

## Open tasks for the next agent

### 1. Initialize and test a fresh clone

- Clone the repository into a new directory.
- Run:

```sh
python3 scripts/agent_context_engine.py install --target <new-clone> --no-install-launchagent --no-start-monitor --no-bootstrap-runtime --force
```

Use the same command without `--no-bootstrap-runtime` when a fresh venv should
be created.

- Verify that `~/.agent-context-engine/active-root` points at the new clone.
- In a test project directory, run `codex-ace --activate-here` or the
  equivalent `integration-hooks` command and verify:
  - `.codex/hooks.json` is created.
  - `.codex/hooks/hook_adapter.sh` is a symlink to the installation metadata
    hub, for example `~/.agent-context-engine/hooks/codex/hook_adapter.sh`.
  - `activated-projects.json` under the installation metadata root contains the
    project entry with `active` status.
- Start a real `codex` run in the test project and confirm that hooks capture
  the session in the monitor or in `agent-context-engine last`.

### 2. Validate the fresh Claude path

`scripts/claude-ace` now follows the same project-local model as
`scripts/codex-ace`:

- it stays in the current working directory,
- searches upward for `.claude/settings.json`,
- validates the symlink to the central hub,
- starts `claude` through `cd "$PROJECT_DIR" && exec claude ...`,
- sets `AGENT_MEMORY_LAUNCH_CWD`.

The remaining work is practical validation in a fresh clone or real test
project.

### 3. Connect monitor integration status to the registry

The monitor still reads some hook status from workspace bindings and local
configuration. The new `activated-projects.json` registry should feed
`integrations.py` / `integration_summary()` so the monitor can show:

- which projects are active for each runner,
- whether a project is `disabled`, `missing`, or `error`,
- drift warnings for broken symlinks or outdated hubs.

### 4. Complete drift detection and repair

The epic defines drift for `doctor` / `check-installation`:

- missing or invalid `active-root`,
- missing or non-executable central hub,
- hub `spec_version` mismatch,
- broken local symlink or symlink pointing somewhere else.

The first three checks can be handled in `_ensure_central_hub_and_active_root()`
and the installation-check payload. The fourth needs a function that compares
`activated-projects.json` with the local symlink state.

### 5. Harden hook merge rules

Codex activation currently appends ACE hooks. If a runner/event already has a
non-ACE hook and the runner supports only one hook for that event, activation
should fail with a clear message. Codex itself supports multiple hooks per
event, but this logic should be centralized for all runners.

### 6. Verify additional runner hubs

The central hub infrastructure is wired for `antigravity` and `gemini`,
including project-local wrapper search and the symlink model. Practical
verification in a fresh installation/test run is still pending.

### 7. Finalize documentation

- Update `docs/epics/project-local-hooks-via-central-hook-adapter-links-plan.md`
  when the remaining tasks are closed.
- Check `session-start-hook-entry.md` for consistency with the new wrapper
  startup commands.
- Keep README, changelog, and version snapshots aligned through the
  `docsupdate` workflow.

### 8. Open the review path

- Ensure `git status` is clean before handing off.
- Keep generated/local artifacts such as `PYEOF`, `frontend/storybook-static/`,
  and `.pyc` files out of the commit.
- Open a draft PR from `feat/central-hook-adapters` and reference the epic.

## Important code paths for the next agent

- Storage root and paths: `backend/src/agent_context_engine/infrastructure/config.py`
- Hub rendering: `backend/src/agent_context_engine/application/hook_rendering/specs.py`, `renderers.py`
- Activation/deactivation: `backend/src/agent_context_engine/application/integrations.py`
  - `_merge_shell_hook_client`
  - `_disable_shell_hook_client`
  - `_ensure_central_hub_exists`
  - `_read_activated_projects` / `_update_project_registry_status`
- CLI: `backend/src/agent_context_engine/interfaces/cli/commands/installation.py`
  - `_ensure_central_hub_and_active_root`
  - `cmd_integration_hooks`
- Wrappers: `scripts/codex-ace`, `scripts/claude-ace`, `scripts/gemini-ace`, `scripts/agy-ace`
- Spec: `backend/src/agent_context_engine/application/hooks.spec.md`

## Risks and known limitations

- The `active-root` mechanism only works after `install` or `repair` has run at
  least once. Without `active-root`, the hub exits gracefully, but hooks do not
  run.
- Isolated installations must set `AGENT_CONTEXT_ENGINE_STORAGE_ROOT`; otherwise
  the global `active-root` can be overwritten.
- Windows is not part of this milestone.
