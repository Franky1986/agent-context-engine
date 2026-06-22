# Epic / Refactoring Plan: Memory-Root Decoupling and Storage Versioning

> Status 2026-06-22: **implemented as the current MVP slice**.
> Agent Context Engine now separates the installation root from the persistent
> `memory_root`, resolves runtime paths from that storage root, persists a
> `storage-profile.json`, shows install-versus-storage paths in `doctor`,
> `check-installation`, and the monitor, and supports
> `install --memory-root`, `attach-memory-root`, and `migrate-storage`.
> Automatic physical data migration and stronger shared-storage protection are
> still future work.

## Why It Matters

The code checkout, runtime identity, and persistent memory storage must be
separate concerns. That separation enables:

- source upgrades without moving runtime data,
- parallel test installations,
- explicit rebinding to an existing memory store,
- future storage-schema evolution.

## Delivered Model

The public runtime now distinguishes:

- `install_root`: source code, scripts, templates, monitor assets
- `instance profile`: instance id, wrapper naming, monitor defaults,
  LaunchAgent defaults, workflow defaults
- `memory_root`: SQLite, logs, queues, dreams, sessions, materialized memory,
  local runtime configuration

## Current Commands

- `install --memory-root <path>`
- `attach-memory-root --memory-root <path>`
- `migrate-storage`
- `doctor`
- `check-installation`

## Open Follow-Up

- physical migration tooling for older layouts,
- stronger safety rules for shared or concurrent writers,
- explicit storage-schema migrations for future breaking changes.
