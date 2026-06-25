# `docsupdate` command (Doc-sync + version + changelog)

Use this command pack to keep documentation, specs, versions, and changelog aligned after behavior changes.

## Canonical runner

Use this workflow as an editor-level maintenance task:

- Ensure all touched behavior boundaries are covered in the closest `*.spec.md`.
- Confirm version-sensitive references are current (`backend/pyproject.toml`, frontend manifests).
- Confirm snapshot docs (`README.md`, `docs/progress/CURRENT_STATUS.md`, and
  `docs/runbooks/test-strategy-and-validation-status.md`) reflect current state.
- Prepare backend and monitor changelog notes.

`/docsupdate` should resolve to this document from the configured client entry points and be executed via the editor/runtime command path.

## Required workflow before running docsupdate

- Confirm all touched behavior-facing files are covered in the nearest `*.spec.md`.
- Confirm version-sensitive references are ready (`backend/pyproject.toml`, frontend version manifests).
- Confirm release snapshots are current (`README.md`, `docs/index.md`, relevant progress/runbook snapshots).
- Decide concise changelog notes for backend + monitor before finalizing.

## Client command surfaces

The canonical contract is this README. Client bindings are thin references:

- `.codex/commands/docsupdate.md`
- `.claude/commands/docsupdate.md`
- `.cursor/commands/docsupdate.md`
- `.opencode/commands/docsupdate.md`

Use `/docsupdate` in clients configured for slash-command mapping.
