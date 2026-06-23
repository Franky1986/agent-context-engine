# Spec: Monitor Integrations Feature

## Purpose

The Integrations feature shows whether Agent Context Engine clients and runners are
operational, how they are started, whether hooks are enabled, and whether the
stored installation profile still matches the intended workflows.

It must help a user distinguish between:

- runtime readiness
- root-only wrapper usage
- global command availability
- hook enablement
- project activation requirements

## Data Contract

Primary source:

- `/api/integrations`
- `/api/installation-check`

The feature consumes integration items with separate fields for:

- runtime readiness
- wrapper command and wrapper path
- global command availability
- hook state and manageability
- activation command
- terminal command
- global wrapper activation command
- discovered models
- recent integration history and last history entry
- stored workflow runner profile
- read-only findings plus agent-only and manual follow-up commands

## UX Rules

1. Do not collapse all integration status into a single "ready" label.
2. Show runtime, wrapper, and hooks as separate concerns.
3. If a wrapper is only usable from the Agent Context Engine root, the UI must say so.
4. If a command works globally only when linked in `PATH`, the UI must say so.
5. The monitor must stay diagnostic-only for integration changes.
6. Follow-up commands may be shown, but they must execute outside the monitor
   through an agent-approved terminal flow.
7. Project-activation clients such as Cursor must show project-scoped commands
   and recorded activations instead of one global toggle.
8. The UI should show recent integration history so operators and agents can
   reconstruct who enabled or disabled hooks and where.
9. Hook enablement must not be inferred from file existence alone.
10. All user-visible text must be language-toggle-aware.
11. Installed wrapper links under `docs/skills/.../scripts/*` must be treated
    as valid current-installation targets, not as conflicts.

## Status Semantics

### Runtime

- "ready" means the underlying client/runner/provider path exists
- it does not imply a global wrapper

### Wrapper

Expected states:

- `global_active`
- `root_active`
- `blocked_by_hooks`
- `project_activation`
- `runner_missing`
- `not_prepared`

### Hooks

Expected states:

- `enabled`
- `disabled`
- `partial`
- `configured_without_agent_memory`
- `not_prepared`
- `not_supported`

### Global-only bridge semantics

- `opencode`, `gemini`, and `antigravity` may share a central memory root while
  still requiring hook or plugin files to live under the installation root that
  their wrapper launches from.
- The UI must report bridge readiness from the actual installation-root files.

## Interaction Rules

- do not mutate hooks from the monitor UI
- surface exact Agent Context Engine terminal commands for additive enable/repair flows
- treat hook disable and hook enable alike as out-of-band operational changes
- if the UI explains the path, it must point to an explicit agent/user terminal
  flow, not a direct monitor action

## Localization Rule

New strings in this feature must be expressed through the monitor language
toggle path. Do not add hardcoded English-only or German-only text.
