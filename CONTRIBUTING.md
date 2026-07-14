# Contributing

Thanks for considering a contribution to Agent Context Engine.

## Development Setup

Use a normal Python 3 environment. The core package intentionally uses the
standard library for the local CLI, SQLite runtime, hooks, and tests.

Run checks from the repository root:

```sh
./scripts/check-agent-context-engine --skip-runtime-db
python3 -m unittest discover -s tests -v
./scripts/audit
```

For a fresh install smoke test:

```sh
python3 scripts/agent_context_engine.py install \
  --target /tmp/agent-context-engine-target \
  --instance-name smoke \
  --link-dir /tmp/agent-context-engine-bin \
  --link-codex-ace \
  --link-claude-ace \
  --link-cursor-ace \
  --no-interactive \
  --force

agent-context-engine doctor
```

## Pull Request Expectations

- Keep changes focused.
- Add or update tests for behavior changes.
- Do not commit local runtime data, transcripts, logs, databases, secrets, or
  personal memory files.
- Preserve both supported layouts:
  - standalone public repo root
  - nested install layout under `docs/skills/agent-context-engine`
- Keep installer output useful for human users and agents.

## Agent Bootstrap Contract

Changes to installation behavior should keep `AGENT_BOOTSTRAP.md` accurate. A
fresh Codex, Claude Code, or Cursor agent should be able to clone the repository,
read the bootstrap guide, ask the user for the few necessary setup choices, run
the installer, finish with `doctor`, and leave the monitor running unless the
user explicitly opted out.

Behavioral changes should also update the nearest `*.spec.md` contract and keep
`docs/index.md` in sync via `python3 scripts/update_docs_index.py --check`.

Dependency changes must keep `backend/requirements-runtime.txt`,
`backend/requirements-build.txt`, and `backend/requirements-audit.txt` aligned
with `backend/pyproject.toml` and the audit toolchain.
