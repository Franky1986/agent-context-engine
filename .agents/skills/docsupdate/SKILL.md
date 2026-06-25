---
name: docsupdate
description: Run repository documentation/version/changelog sync workflow.
aliases:
  - doup
  - docs-update
---
# docsupdate

Use this when repository-level documentation/version/changelog sync is requested.

Canonical command:

```sh
./scripts/docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```

If your Codex build does not expose `/docsupdate` in the slash menu, use:

```text
/use docsupdate
```

or invoke the skill directly:

```text
$docsupdate
```
