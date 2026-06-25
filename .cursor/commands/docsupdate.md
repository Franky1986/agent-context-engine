# /docsupdate

Run the repository documentation/version/changelog sync workflow.
Source of truth: docs/commands/docsupdate/README.md

```sh
./scripts/docsupdate \
  --bump-backend patch \
  --bump-monitor patch \
  --changelog-note "backend: ..." \
  --changelog-note "monitor: ..."
```
