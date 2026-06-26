from __future__ import annotations

from dataclasses import dataclass


LANGUAGE_LABELS = {
    "de": "German",
    "en": "English",
}


@dataclass(frozen=True)
class AgentFlowContract:
    preferred_language: str
    command_prefix: str
    repo_context_path: str = "memory/knowledge/repos.md"
    monitor_runner: str = "codex"
    monitor_host: str = "127.0.0.1"
    monitor_port: int = 8787
    monitor_replace_existing: bool = True
    monitor_no_open: bool = True

    @property
    def preferred_language_label(self) -> str:
        return LANGUAGE_LABELS.get(self.preferred_language, "English")


def build_agent_flow_contract(
    *,
    preferred_language: str,
    command_prefix: str,
    repo_context_path: str = "memory/knowledge/repos.md",
    monitor_runner: str = "codex",
    monitor_host: str = "127.0.0.1",
    monitor_port: int = 8787,
    monitor_replace_existing: bool = True,
    monitor_no_open: bool = True,
) -> AgentFlowContract:
    language = str(preferred_language or "en").strip().lower() or "en"
    runner = str(monitor_runner or "codex").strip() or "codex"
    path = str(repo_context_path or "memory/knowledge/repos.md").strip() or "memory/knowledge/repos.md"
    return AgentFlowContract(
        preferred_language=language,
        command_prefix=str(command_prefix).strip(),
        repo_context_path=path,
        monitor_runner=runner,
        monitor_host=str(monitor_host or "127.0.0.1").strip() or "127.0.0.1",
        monitor_port=int(monitor_port or 8787),
        monitor_replace_existing=bool(monitor_replace_existing),
        monitor_no_open=bool(monitor_no_open),
    )


def render_agents_quick_path(contract: AgentFlowContract) -> str:
    return f"""## Agent Context Engine Quick Path
- Preferred interaction language for future agents: {contract.preferred_language_label}.
- When asked about previous sessions, handovers, project context, "what happened last", "continue there", "we already analyzed this", or similar memory requests, use the local Agent Context Engine CLI first.
- Agent Context Engine command prefix: `{contract.command_prefix}`
- Canonical public CLI contract: `{contract.command_prefix}` from `PATH`. Repo-local `./scripts/ace` and `./scripts/agent-context-engine` remain compatibility fallbacks, not the primary hook/session contract.
- Traceable retrieval: `{contract.command_prefix} retrieve "<question or search terms>" --limit 10`
- Quick keyword search: `{contract.command_prefix} search "<search terms>" --limit 5`
- Load a session handover: `{contract.command_prefix} handover "<session|title|search terms>"`
- Recent sessions: `{contract.command_prefix} last --limit 10`
- Status: `{contract.command_prefix} doctor`
- For list/count/today questions about sessions, use `last` first and stop there unless the user explicitly asks for details about a specific session.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- Only after these commands should agents broaden the search with `rg` in the repository or memory tree.
"""


def render_session_start_hook_entry(contract: AgentFlowContract) -> str:
    monitor_args = [
        f"{contract.command_prefix} monitor",
        f"--runner {contract.monitor_runner}",
        f"--host {contract.monitor_host}",
        f"--port {contract.monitor_port}",
        f"--language {contract.preferred_language}",
    ]
    if contract.monitor_replace_existing:
        monitor_args.append("--replace-existing")
    if contract.monitor_no_open:
        monitor_args.append("--no-open")
    monitor_command = " ".join(monitor_args)
    return f"""# Session Start

Agent Context Engine command prefix: `{contract.command_prefix}`

The installed public CLI is expected to resolve from `PATH`. If `{contract.command_prefix}`
is missing, treat that as an installation/linking problem and repair the active
installation instead of falling back silently to stale repo-local shortcuts.

- For session list/count/today questions, use `last --limit 10` first and answer from that result. Do not open session, summary, or dream files unless the user explicitly asks for details.
- For session list/count/today questions, use `last` first and stop there unless the user explicitly asks for deeper detail.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- If the user mentions a local repo/project/folder by name, or asks for side information about another project, resolve it via one of these — do not browse the filesystem:
  - `repo-context --list` — overview of known repos
  - `repo-context <identifier>` — targeted context for a specific repo
  - the canonical runtime repo index lives under `{contract.repo_context_path}` in the active memory root
- Load personal context only on demand, e.g. for "my preferences", "as usual", writing style, language, or personal standards.

Start here for previous work:
- `{contract.command_prefix} last --limit 10`
- `{contract.command_prefix} use "<session|title|search terms>"`
- `{contract.command_prefix} handover "<session|title|search terms>"`
- `{contract.command_prefix} retrieve "<question or search terms>" --limit 10`
- `{contract.command_prefix} search "<search terms>" --limit 5`

Load extra context when needed:
- `{contract.command_prefix} session-start-context`
- `{contract.command_prefix} personal-context --list`
- `{contract.command_prefix} personal-context <identifier>`
- `{contract.command_prefix} repo-context --list`
- `{contract.command_prefix} repo-context <identifier>`
- `{contract.command_prefix} retrieval-runs --limit 10`
- `{contract.command_prefix} retrieval-run <retrieval_run_id>`

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
- `{monitor_command}`
"""


def render_claude_entrypoint() -> str:
    return """# Claude Entry Point

Follow `AGENTS.md` in this directory as the canonical project instructions.

Do not duplicate or reinterpret the project rules here. When instructions need to change, update `AGENTS.md`.

Important startup behavior:

- Read `AGENTS.md` first.
- Use the Agent Context Engine quick path from `AGENTS.md` for earlier sessions, handovers, project context, and "what happened last" questions.
- Keep startup context small; load deeper docs only when the concrete task needs them.
"""


def render_cursor_every_chat_rule() -> str:
    return """---
description: Canonical project entrypoint for every Cursor chat
globs:
  - "**/*"
alwaysApply: true
---

# Project Instructions

`AGENTS.md` in this directory is the canonical instruction file for this project.

Cursor must use `AGENTS.md` as the source of truth for:

- local Git rules
- safety rules for file operations
- Agent Context Engine lookup workflow
- linked workflow references
- commit behavior

Do not duplicate those rules here. If project instructions need to change, update `AGENTS.md`.

At the start of a chat, read `AGENTS.md` before loading deeper project context.
"""
