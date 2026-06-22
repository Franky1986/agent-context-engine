# Security Policy

Agent Context Engine is local-first tooling for agentic coding sessions. It can record
prompts, assistant messages, tool calls, file paths, summaries, graph artifacts,
and other local workflow context in the installation target's `memory/`
directory.

## Supported Versions

Until the first tagged release, security fixes target the default branch.

## Reporting A Vulnerability

Please do not open public issues that include secrets, private transcripts,
private memory files, credentials, API keys, local database contents, or
reproduction archives containing user data.

Use GitHub private vulnerability reporting if it is enabled for the repository,
or contact the maintainer privately through the GitHub profile.

Include:

- affected commit or version
- operating system
- agent harness involved, if any: Codex, Claude Code, Cursor IDE
- concise reproduction steps
- whether private memory, credentials, or command execution could be affected

## Local Data Handling

Do not commit runtime data:

- `memory/`
- SQLite databases
- logs
- generated analysis reports
- local environment files
- transcripts or copied chat exports

The repository `.gitignore` is configured to exclude common runtime artifacts,
but users remain responsible for reviewing staged files before publishing.

## Security Boundaries

Agent Context Engine includes deterministic scanning, optional classifier review,
quarantine, and firewall controls. These controls are defense-in-depth for local
agent workflows; they are not a sandbox boundary. Continue to review commands
that can write files, execute code, access networks, deploy software, or expose
credentials.
