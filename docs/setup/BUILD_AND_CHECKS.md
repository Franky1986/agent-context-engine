# Build And Checks

Use these checks before publishing substantial changes.

## Core Checks

```sh
./scripts/check --skip-runtime-db
python3 -m unittest discover -s tests -v
./scripts/agent-context-engine doctor
./scripts/audit
```

## Targeted Checks

Run additional focused checks for the areas you touched:

- retrieval changes: inspect retrieval behavior and any related tests
- graph changes: inspect graph status and graph-related tests
- monitor changes: rebuild frontend assets and verify monitor behavior
- installation changes: rerun install, verify the monitor autostart behavior, and run `check-installation`
- safety changes: validate risk/firewall behavior carefully

## Recommended Review Gates

Consider these runtime checks when relevant:

```sh
./scripts/agent-context-engine retrieve-runs --limit 10
./scripts/agent-context-engine graph-status --limit 10
./scripts/agent-context-engine risk list --limit 20
```

## Runtime Hygiene

- do not commit local runtime data under `memory/`
- do not commit SQLite databases, logs, or local environment files
- treat `memory/knowledge/` as runtime-local state, not source documentation
- verify that copied/generated artifacts are not accidentally staged
- when changing non-trivial behavior, update the nearest `*.spec.md` and keep `docs/index.md` aligned
- when changing Python dependencies, keep `backend/requirements-runtime.txt`, `backend/requirements-build.txt`, and `backend/requirements-audit.txt` aligned
