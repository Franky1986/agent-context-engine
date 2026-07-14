# Search And Repository Context Contract

## Scope

The `search` command remains a quick keyword lookup over indexed Agent Context
Engine memory. Repository knowledge is a separate context source and must not be
presented as session or memory evidence.

## Repository alternatives

- After the normal memory results, `search` should inspect the current runtime
  repository index for matching identifiers or descriptions.
- Matching repository entries must be shown in a separate section as concrete
  `repo-context "<identifier>"` follow-up commands.
- Repository suggestions must work even when `rebuild-indexes` has not yet
  indexed the repository index into memory search.
- Suggestions expose repository identifiers and public CLI commands only. They
  must not expose the local filesystem paths stored in the private repository
  index.
- Approximate token-prefix matching may bridge minor spelling variants, but it
  must not merge repository knowledge into the ranked memory result set.
