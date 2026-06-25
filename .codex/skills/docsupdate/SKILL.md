---
name: docsupdate
description: Run repository documentation/version/changelog sync workflow.
aliases:
  - doup
  - docs-update
---
# docsupdate

Run the repository documentation/version/changelog sync workflow.

Canonical command:

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

If `/docsupdate` is not surfaced in the slash menu, use:

```sh
/use docsupdate
```

or invoke this skill directly with:

```text
$docsupdate
```
