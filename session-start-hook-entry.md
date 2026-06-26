# Session Start

Agent Context Engine command prefix: `agent-context-engine`

The installed public CLI is expected to resolve from `PATH`. If `agent-context-engine`
is missing, treat that as an installation/linking problem and repair the active
installation instead of falling back silently to stale repo-local shortcuts.

- For session list/count/today questions, use `last --limit 10` first and answer from that result. Do not open session, summary, or dream files unless the user explicitly asks for details.
- For session list/count/today questions, use `last` first and stop there unless the user explicitly asks for deeper detail.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- If the user mentions a local repo/project/folder by name, or asks for side information about another project, resolve it via one of these — do not browse the filesystem:
  - `cat ./docs/knowledge/repos.md` — full repos context (fastest, no CLI needed)
  - `repo-context --list` — overview of known repos
  - `repo-context <identifier>` — targeted context for a specific repo
- Load personal context only on demand, e.g. for "my preferences", "as usual", writing style, language, or personal standards.

Start here for previous work:
- `agent-context-engine last --limit 10`
- `agent-context-engine use "<session|title|search terms>"`
- `agent-context-engine handover "<session|title|search terms>"`
- `agent-context-engine retrieve "<question or search terms>" --limit 10`
- `agent-context-engine search "<search terms>" --limit 5`

Load extra context when needed:
- `agent-context-engine session-start-context`
- `agent-context-engine personal-context --list`
- `agent-context-engine personal-context <identifier>`
- `agent-context-engine repo-context --list`
- `agent-context-engine repo-context <identifier>`
- `agent-context-engine retrieval-runs --limit 10`
- `agent-context-engine retrieval-run <retrieval_run_id>`

User-only controls:
- `approve ...`
- `reset taint`
- `firewall add ...`
- `firewall disable session`
- `firewall enable session`
- `hooks-disable [--runner <runner>]`
- `hooks-enable [--runner <runner>]`
- `hooks-status`

Monitor:
- `agent-context-engine monitor --runner codex --host 127.0.0.1 --port 8787 --language de --replace-existing --no-open`
