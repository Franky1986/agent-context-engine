# Central Installation Mode

Central-installation mode means one Agent Context Engine root is shared across multiple
projects or workspaces.

## When To Use It

Use this mode when:

- you work across multiple repositories
- you want one central runtime and monitor
- you want shared wrappers such as `codex-memory` or `claude-memory`
- you want one memory layer to follow work across projects

## User Experience

In this mode:

1. install Agent Context Engine into a dedicated root
2. optionally link wrapper commands
3. activate external workspaces or use wrappers where appropriate
4. let Agent Context Engine preserve the originating work context

## Benefits

- one shared runtime
- one shared monitor
- easier cross-project continuation
- convenient wrapper-based startup from different working directories

## Tradeoff

This mode is more powerful, but also more complex. Users need a clearer
understanding of:

- wrapper behavior
- external workspace activation
- GUI-only hooks versus headless CLI readiness

Use [Activation Model](activation-model.md) and
[Runner And Harness Guide](RUNNER_HARNESSES.md) together when setting this up.
