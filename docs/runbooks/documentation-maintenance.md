# Documentation and Version Maintenance

Use this runbook when a change set is complete and release-oriented operator docs,
`.spec.md` index, and changelog metadata should be synchronized in one pass.

## Purpose

This workflow keeps source-of-truth version references and release metadata aligned:

- backend package version (`backend/pyproject.toml`)
- monitor package version (`frontend/package.json` + lockfile root version)
- nearest `*.spec.md` updates that match the changed behavior (spec scope must be part of the same PR)
- public version mentions in README and progress/runbook snapshots
- spec index in `docs/index.md`
- changelog scaffold entries

## Required inputs

- choose target versions (`x.y.z`) or request patch/minor/major bumps
- decide concise changelog notes for backend and monitor before final pass

## Fast agent command

Use this workflow after release-relevant behavior updates:

- Run through the `/docsupdate` editor entry for the active client.
- Keep this document as the source of truth and run the concrete release sync steps from your preferred maintenance path.

In chat clients that support slash mapping, expose the same runbook via:

- `/docsupdate`
- `docs/commands/docsupdate/README.md` (source of truth)
- `.codex/commands/docsupdate.md`
- `.claude/commands/docsupdate.md`
- `.cursor/commands/docsupdate.md`
- `.opencode/commands/docsupdate.md`

`/docsupdate` is the shared maintenance entry point. The runtime steps are defined in:

- `docs/commands/docsupdate/README.md`

## Recommended command flow

Follow the flow in `docs/commands/docsupdate/README.md` to:

- align backend + monitor versions,
- refresh release snapshots and spec references,
- add changelog notes,
- refresh doc index checks.

If changelog wording is still pending, use the draft path described in the README.

`--skip-index` is useful for staged manual edits where notes and changelog wording
are intentionally deferred.

## Post conditions

- `backend/pyproject.toml` and `frontend/package*.json` versions are aligned
- `README.md`, `docs/progress/CURRENT_STATUS.md`, and
  `docs/runbooks/test-strategy-and-validation-status.md` show the updated release
  snapshot
- `docs/index.md` spec section is refreshed
- a new `## Backend <version>` and `## Monitor <version>` section exists in
  `CHANGELOG.md` for changed versions
- `./scripts/update_docs_index.py --check` should pass after the run

## Notes

- This helper does not run runtime tests.
- Use generated changelog entries as a scaffold and refine text before finalizing the release note.
