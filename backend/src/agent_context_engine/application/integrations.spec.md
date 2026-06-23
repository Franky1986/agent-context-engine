# Spec: Integration Management Application Boundary

## Purpose

This boundary owns Agent Context Engine integration status, activation, hook
enable/disable, wrapper metadata, and model/provider readiness summaries for
supported clients and runners.

Primary scope:

- `integrations_summary`
- model/provider discovery summaries
- wrapper/global-command classification
- hook status inspection
- hook enable/disable mutation orchestration
- Opencode project bridge preparation
- installation-root bridge preparation for global-only runners that share an
  external memory root

## Driving Inputs

- monitor and CLI requests for integration status
- monitor mutation requests to enable or disable hooks
- installation and enable commands for Cursor / Opencode
- future model discovery and model change flows

## Outputs

Each integration item must expose separable status axes:

- `ready`
- `readiness_status`
- `prepared`
- `wrapper_state`
- `wrapper_ready`
- `global_command_name`
- `global_command_available`
- `global_command_path`
- `global_activation_command`
- `global_deactivation_command`
- `global_status_command`
- `hooks_manageable`
- `hooks_state`
- `hook_config_state`
- `hooks_control_state`
- `hooks_control_source`
- `hooks_enabled`
- `activation_command`
- `terminal_command`
- `recommended_model`
- `mini_model`
- discovered model inventory when available
- recent integration history and last history entry
- operator-facing commands that reflect the active installation's public CLI
  contract

## Invariants

1. Runtime readiness is not the same as wrapper readiness.
2. Global command availability is not the same as root availability.
3. Hook enablement is determined by config content, not just by file presence.
4. Enable operations must merge Agent Context Engine hook content into existing configs.
5. Disable operations must preserve the active config via a `_deactivated`
   rename instead of destructive deletion.
6. Integrations must preserve unrelated user hook entries.
7. Integration enable/disable and activation changes must be written to a
   persistent audit trail that later agents and the monitor can inspect.
8. Hook deactivation is a protected control-plane change and must not be
   offered as a normal monitor mutation.
9. Effective hook execution must respect the central hook control plane before
   local config presence is considered.
10. Runner-level overrides may further disable a client while global hooks stay
    enabled; a global disable always wins over a runner enable override.
11. Global-only runners must prepare their bridge or hook files in the
    installation root that their wrapper actually launches from, not in the
    shared memory root.
12. Public activation/status commands shown to operators should prefer the
    installed `agent-context-engine` command when it resolves to the active
    installation; repo-local script paths are compatibility fallbacks only.

## Client Families

### Shell-hook clients

- `codex`
- `claude`
- `antigravity`
- `gemini`

Rules:

- hook config and hook adapter script must be tracked separately
- wrapper state may become `blocked_by_hooks` when wrapper launch depends on an
  inactive hook config

### Project activation clients

- `cursor`

Rules:

- activation is per target project
- no single global wrapper command is implied

### Plugin-bridge clients

- `opencode`

Rules:

- plugin-bridge preparation is distinct from root/global wrapper availability
- project hook activation is tracked separately from local wrapper execution
- readiness must reflect the actual plugin file under the installation root
  used by the wrapper, not merely a bridge file somewhere else

## Failure Classes

- `missing_executable`
- `model_missing`
- `provider_unreachable`
- `client_auth_missing`
- `hooks_not_prepared`
- `hooks_config_invalid`
- `hook_merge_failed`
- `hook_disable_failed`

## Observability

- monitor integrations endpoint
- monitor hook mutation endpoint
- CLI enable/status outputs
- hook config paths and disabled config paths

## Control Plane Guardrail

- Hook enablement may be monitor-managed.
- Hook disable must be treated as a protected control-plane mutation.
- Agents must not bypass this by direct file mutation, alternate CLI commands,
  or monitor-API calls.
- The direct user control contract is `hooks-disable`, `hooks-enable`, and
  `hooks-status`.

## Rollback

- hook enablement is reversible by writing the config back to a `_deactivated`
  file
- local wrapper and config artifacts can be regenerated from templates
- model/provider discovery failure must degrade to explicit status, not silent
  "ready" claims
