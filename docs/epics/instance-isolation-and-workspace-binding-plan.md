# Epic / Design: Instance Isolation, Wrapper Naming, and Workspace Binding

> Status 2026-06-22: **largely implemented**.
> Agent Context Engine now persists an instance profile with `instance_id`,
> root, wrapper naming, monitor defaults, and LaunchAgent defaults.
> Resume, handover, monitor, and integration paths resolve wrapper names from
> that profile. Workspace hooks for `codex`, `claude`, and `cursor` use
> explicit binding files; if the binding is missing or points to a missing
> root, the hook is treated as effectively inactive. Monitor, `doctor`, and
> `check-installation` surface binding drift, port drift, and LaunchAgent
> drift.

## Goal

Multiple local installations must be able to coexist on the same machine
without colliding through:

- global wrapper names,
- monitor ports,
- LaunchAgent labels and plist paths,
- GUI-workspace hook ownership.

## Delivered Behavior

- instance profiles persist wrapper prefix/suffix and monitor defaults,
- wrapper names are resolved from the instance profile,
- workspace bindings explicitly point to the owning installation,
- missing or broken bindings are surfaced as inactive hook state,
- monitor and diagnostics expose binding, port, and LaunchAgent drift.

## Practical Effect

You can test multiple versions of the runtime on one machine more safely, as
long as you give each installation its own identity, monitor port, and
optional wrapper naming.

## Remaining Gaps

- dedicated convenience commands for explicit workspace rebinding are still
  secondary to the current `install`, `repair-installation`, and enable flows,
- public documentation still needs broader examples for multi-version testing
  patterns.
