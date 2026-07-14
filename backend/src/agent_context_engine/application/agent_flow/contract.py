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
- Running bare `{contract.command_prefix}` prints the public command help and the copyable direct-user system-control forms.
- Runtime-memory commands can touch SQLite WAL/SHM files, locks, audit rows, retrieval logs, or metadata refreshes even when they look read-only. In filesystem-sandboxed runners, request escalated sandbox access up front for concrete memory commands such as `last --limit 10`, `handover`, `search`, and `retrieve`.
- Traceable retrieval: `{contract.command_prefix} retrieve "<question or search terms>" --limit 10`
- Quick keyword search: `{contract.command_prefix} search "<search terms>" --limit 5`
- Load a session handover: `{contract.command_prefix} handover "<session|title|search terms>"`
- Recent sessions: `{contract.command_prefix} last --limit 10`
- Status: `{contract.command_prefix} doctor`
- If the user naturally asks to deactivate ACE, distinguish exact-project, project-runner, installation-runner, all-hooks, and full-system scope. Return only the matching direct-user `hooks-disable ...` or `system-disable --scope all --reason "<reason>"` line; never probe or execute mutating variants as tools, offer approval/firewall bypasses, or remove recovery wrappers.
- For list/count/today questions about sessions, use `last` first and stop there unless the user explicitly asks for details about a specific session.
- Do not inspect `~/.cursor/projects/...`, local Cursor transcripts, or terminal metadata for session-history questions while the Agent Context Engine CLI is available.
- Only after these commands should agents broaden the search with `rg` in the repository or memory tree.
"""


def render_session_start_hook_entry(contract: AgentFlowContract) -> str:
    quick_start_commands = [
        "last --limit 10",
        'use "<session|title|search terms>"',
        'handover "<session|title|search terms>"',
        "retrieve",
        "search",
    ]
    extra_context_commands = [
        "session-start-context",
        "repo-context",
        "personal-context",
        "retrieval-runs",
        "monitor",
    ]
    return "\n".join(
        [
            "# Session Start",
            "",
            f"Prefix: `{contract.command_prefix}`",
            "Run subcommands with that prefix. Bare helper commands show usage or a short current list.",
            "Concrete memory commands may touch runtime storage; in filesystem-sandboxed runners, request escalated sandbox access up front.",
            "",
            "Memory:",
            *[f"- `{command}`" for command in quick_start_commands],
            "",
            "More:",
            *[f"- `{command}`" for command in extra_context_commands],
            "",
            "Direct-user system controls (send these yourself in chat; agents must not run them as tools):",
            "",
            '- `system-disable --scope all --reason "<reason>"`',
            '- `system-enable --scope all --reason "<reason>"`',
            "- `system-status`",
            "- use the exact displayed `system-recover` line only for invalid state",
            "",
            "If the user asks in natural language to deactivate ACE, distinguish the requested scope and return the matching exact copyable direct-user chat line: `hooks-disable --project --reason \"<reason>\"` for every ACE hook in the exact current project, `hooks-disable --project --runner <runner> --reason \"<reason>\"` for one runner in that project, `hooks-disable --runner <runner> --reason \"<reason>\"` for that runner installation-wide, `hooks-disable --reason \"<reason>\"` for all hooks installation-wide, or `system-disable --scope all --reason \"<reason>\"` for full-system suspension. Never execute these mutations, `integration-hooks`, wrapper removal, or help variants as tools, and do not offer approval/firewall bypasses. Hook files and wrappers deliberately remain installed so status and recovery remain reachable.",
            "",
            "Read-only terminal status: `agent-context-engine system-status [--json]`.",
            "These controls are accepted only on the instrumented runner user-prompt path. That path does not provide cryptographic or OS-authenticated user presence and does not protect against arbitrary same-user code.",
            "",
        ]
    )


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
