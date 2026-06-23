# Session Start

Agent Context Engine command prefix: `./scripts/ace`

- For session list/count/today questions, use `last --limit 10` first and answer from that result. Do not open session, summary, or dream files unless the user explicitly asks for details.
- For session list/count/today questions, use `last` first and stop there unless the user explicitly asks for deeper detail.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- If the user mentions a local repo/project/folder by name, or asks for side information about another project, resolve it via one of these — do not browse the filesystem:
  - `cat ./docs/knowledge/repos.md` — full repos context (fastest, no CLI needed)
  - `repo-context --list` — overview of known repos
  - `repo-context <identifier>` — targeted context for a specific repo
- Load personal context only on demand, e.g. for "my preferences", "as usual", writing style, language, or personal standards.

Start here for previous work:
- `./scripts/ace last --limit 10`
- `./scripts/ace use "<session|title|search terms>"`
- `./scripts/ace handover "<session|title|search terms>"`
- `./scripts/ace retrieve "<question or search terms>" --limit 10`
- `./scripts/ace search "<search terms>" --limit 5`

Load extra context when needed:
- `./scripts/ace session-start-context`
- `./scripts/ace personal-context --list`
- `./scripts/ace personal-context <identifier>`
- `./scripts/ace repo-context --list`
- `./scripts/ace repo-context <identifier>`
- `./scripts/ace retrieval-runs --limit 10`
- `./scripts/ace retrieval-run <retrieval_run_id>`

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
- `./scripts/ace monitor --runner codex --host 127.0.0.1 --port 8787 --language en --replace-existing --no-open`
