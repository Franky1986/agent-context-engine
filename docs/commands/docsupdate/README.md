# `docsupdate` command (Doc-sync + version + changelog)

Use this command pack to keep documentation, specs, versions, and changelog aligned after behavior changes.

## Canonical runner

From repo root:

```sh
./scripts/docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```

Equivalent:

```sh
agent-context-engine docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```

## Client surfaces

For Codex/CLI compatibility, the workflow is maintained as:

- `.agents/skills/docsupdate/SKILL.md` (preferred)
- `.codex/commands/docsupdate.md` (fallback)
- `.claude/commands/docsupdate.md`
- `.cursor/commands/docsupdate.md`
- `.opencode/commands/docsupdate.md`

All references use the same command spec.

If `/docsupdate` is not offered in the startup slash menu, run:

```text
/use docsupdate
```

Or if that is also unavailable:

```text
/skills
```

then invoke the `docsupdate` skill.

If Codex exposes slash commands, run:

```text
/docsupdate
```

For OpenCode, use:

```text
/docsupdate
```

### Recommended usage pattern

- Use the workflow after release-relevant changes:
  - versions synced (`backend/pyproject.toml`, frontend package versions)
  - release snapshots (`README.md`, `docs/progress/CURRENT_STATUS.md`, `docs/runbooks/test-strategy-and-validation-status.md`)
  - `docs/index.md` spec section refreshed
  - `CHANGELOG.md` sections updated

- If a changelog note is not ready yet:
  - use `--skip-index` once, then add notes in a follow-up run.
