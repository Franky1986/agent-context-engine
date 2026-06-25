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
- top-of-log changelog scaffold entries

## Required inputs

- choose the target versions (`x.y.z`), or request patch/minor/major bumps
- provide at least one changelog note per touched component where possible

## Fast agent command

Use this short command during cleanup releases after cross-cutting behavior changes:

```sh
# CLI-first operator command (recommended in this repo)
agent-context-engine docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."

# direct script fallback, if you prefer repository scripts
./scripts/docsupdate \
  --bump-backend patch \
  --bump-monitor patch 
```

In chat clients that support a custom slash binding, map this to:

- `/docsupdate`
- `docs/commands/docsupdate/README.md` (source of truth)
- `.agents/skills/docsupdate/SKILL.md` (Codex primary path where supported)
- `.codex/commands/docsupdate.md`
- `.claude/commands/docsupdate.md`
- `.cursor/commands/docsupdate.md`
- `.opencode/commands/docsupdate.md`

`/docsupdate` runs:

```sh
agent-context-engine docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```

If `/docsupdate` is not surfaced in one client, run `/use docsupdate` or `/skills`
then invoke `docsupdate` from the returned skill list.

## Recommended command flow

```sh
# Bump both components and update all docs/changelog artifacts
./scripts/release-doc-sync \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: fixed cursor session runner provenance in session and dream routing"
  --changelog-note "monitor: fixed session/provenance visibility in active/closed states"
```

If you do not want the release note scaffolding yet:

```sh
./scripts/release-doc-sync --bump-backend patch --bump-monitor patch --skip-index
```

`--skip-index` is useful for staged manual edits where the `.spec.md` index is updated
later by another pass.

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
- Use the generated changelog entries as a scaffold and refine text immediately
  after the run.
