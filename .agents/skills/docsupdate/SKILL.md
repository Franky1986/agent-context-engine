---
name: docsupdate
description: Run the repository documentation/version/changelog sync workflow via the shared editor entrypoints.
---

Use this skill to execute the docs maintenance workflow after behavior/surface updates.

The executable source of truth is:

- `docs/commands/docsupdate/README.md`

Preferred invocation surfaces:

- `.codex/commands/docsupdate.md`
- `.claude/commands/docsupdate.md`
- `.cursor/commands/docsupdate.md`
- `.opencode/commands/docsupdate.md`

Keep this workflow limited to maintenance pass steps:

- verify versioned surfaces are aligned,
- update nearest `*.spec.md` files,
- refresh changelog + metadata snapshots,
- run docs index refresh as documented.
