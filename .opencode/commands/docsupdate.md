---
description: Run repository documentation/version/changelog sync workflow.
---

# /docsupdate

Run the repository documentation/version/changelog sync workflow.

```text
agent-context-engine docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```

Equivalent:

```text
./scripts/docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```
