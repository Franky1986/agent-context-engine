# Session Start

Agent Context Engine command prefix: `agent-context-engine`

The installed public CLI is expected to resolve from `PATH`. If `agent-context-engine` is missing, treat that as an installation/linking problem and repair the active installation instead of falling back silently to stale repo-local shortcuts.

- For session list/count/today questions, use `last --limit 10` first and answer from that result. Do not open session, summary, or dream files unless the user explicitly asks for details.
- For session list/count/today questions, use `last` first and stop there unless the user explicitly asks for deeper detail.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- If the user mentions a local repo/project/folder by name, or asks for side information about another project, resolve it via one of these — do not browse the filesystem:
  - `repo-context --list` — overview of known repos
  - `repo-context <identifier>` — targeted context for a specific repo
  - the canonical runtime repo index lives under `memory/knowledge/repos.md` in the active memory root
- Load personal context only on demand, e.g. for "my preferences", "as usual", writing style, language, or personal standards.

Start here for previous work:
- `last --limit 10`
- `use "<session|title|search terms>"`
- `handover "<session|title|search terms>"`
- `retrieve "<question or search terms>" --limit 10`
- `search "<search terms>" --limit 5`

Load extra context when needed:
- `session-start-context`
- `personal-context --list`
- `personal-context <identifier>`
- `repo-context --list`
- `repo-context <identifier>`
- `retrieval-runs --limit 10`
- `retrieval-run <retrieval_run_id>`

Monitor:
- `agent-context-engine monitor --runner codex --host 127.0.0.1 --port 8787 --language en --replace-existing --no-open`
