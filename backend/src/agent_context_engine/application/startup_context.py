from __future__ import annotations

import argparse
import re

from .instance_profile import monitor_restart_command, preferred_agent_memory_cli_for_root, resolve_monitor_profile
from .personal import PERSONAL_ROOT, parse_frontmatter, personal_files
from ..infrastructure.config import ROOT, read_repos_index_text


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()


def _matches_selector(selector: str | None, *values: str) -> bool:
    if not selector:
        return True
    needle = selector.strip().lower()
    return any(needle in value.lower() for value in values if value)


def startup_safe_personal_entries() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for path in personal_files():
        meta = parse_frontmatter(path)
        if meta.get("injection_policy") != "startup_safe" or meta.get("sensitivity") != "normal":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        body = _strip_frontmatter(text)
        if not body:
            continue
        rel = path.relative_to(PERSONAL_ROOT).with_suffix("")
        title = str(rel).replace("\\", "/")
        entries.append((title, body))
    return entries


def startup_safe_personal_markdown(max_chars: int = 4000, selector: str | None = None) -> str:
    parts: list[str] = []
    for title, body in startup_safe_personal_entries():
        if not _matches_selector(selector, title, body):
            continue
        parts.append(f"### {title}\n\n{body}")
        if sum(len(item) for item in parts) >= max_chars:
            break
    return "\n\n".join(parts)[:max_chars].strip()


def repo_index_entries() -> list[tuple[str, str]]:
    text = read_repos_index_text(ROOT)
    if not text:
        return []
    sections: list[str] = []
    current_name = ""
    current_lines: list[str] = []
    for raw_line in text.splitlines():
        heading = re.match(r"^### `([^`]+)`", raw_line)
        if heading:
            if current_name:
                body = "\n".join(current_lines).strip()
                sections.append(f"### {current_name}\n\n{body}" if body else f"### {current_name}")
            current_name = heading.group(1).strip()
            current_lines = []
            continue
        line = raw_line.strip()
        if not current_name or not line:
            continue
        lowered = line.lower()
        if lowered.startswith("- path:") or lowered.startswith("- pfad:"):
            continue
        current_lines.append(line)
    if current_name:
        body = "\n".join(current_lines).strip()
        sections.append(f"### {current_name}\n\n{body}" if body else f"### {current_name}")
    entries: list[tuple[str, str]] = []
    for section in sections:
        lines = section.splitlines()
        name = lines[0].removeprefix("### ").strip()
        body = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        entries.append((name, body))
    return entries


def repo_index_markdown(max_chars: int = 3000, selector: str | None = None) -> str:
    sections: list[str] = []
    for name, body in repo_index_entries():
        if not _matches_selector(selector, name, body):
            continue
        sections.append(f"### {name}\n\n{body}" if body else f"### {name}")
    return "\n\n".join(sections)[:max_chars].strip()


def _identifier_line(label: str, identifiers: list[str]) -> str:
    if not identifiers:
        return f"- {label}: none"
    return f"- {label}: " + ", ".join(f"`{item}`" for item in identifiers)


def cmd_personal_context(args: argparse.Namespace) -> int:
    print("# Personal Operating Memory Context")
    print("")
    identifiers = [title for title, _body in startup_safe_personal_entries()]
    if args.list or not args.selector:
        if not args.list:
            print("Use personal context only when the user asks for preferences, writing style, personal standards, or similar operator-specific context.")
            print("")
            print("Use:")
            print("- `personal-context --list`")
            print("- `personal-context <identifier>`")
            print("")
        print("## Available Identifiers")
        print("")
        print(_identifier_line("personal", identifiers))
        return 0
    personal = startup_safe_personal_markdown(max_chars=args.personal_chars, selector=args.selector)
    print(personal or "_No startup-safe personal memory available._")
    return 0


def cmd_repo_context(args: argparse.Namespace) -> int:
    print("# Repository Knowledge Context")
    print("")
    identifiers = [name for name, _body in repo_index_entries()]
    if args.list or not args.selector:
        if not args.list:
            print("Use repo context when the user mentions a local repo/project/folder by name or asks for side information about another project.")
            print("")
            print("Use:")
            print("- `repo-context --list`")
            print("- `repo-context <identifier>`")
            print("")
        print("## Available Identifiers")
        print("")
        print(_identifier_line("repos", identifiers))
        return 0
    repos = repo_index_markdown(max_chars=args.repo_chars, selector=args.selector)
    print(repos or "_No repository knowledge available._")
    return 0


def cmd_session_start_context(args: argparse.Namespace) -> int:
    cli_prefix = preferred_agent_memory_cli_for_root(ROOT)
    print("# Agent Context Engine Session Start Context")
    print("")
    print("## Session Start")
    print("")
    print("- This context is intended for hook-based runtime sessions.")
    print("- Run the commands below from the active Agent Context Engine root for this session.")
    print("- Start with the local Agent Context Engine CLI before broad repository exploration.")
    print("- Use retrieval and handover first; use source browsing only when the memory workflow is insufficient.")
    print("")
    print("## CLI Workflow")
    print("")
    print(f"- `{cli_prefix} session-start-context`")
    print(f"- `{cli_prefix} last --limit 10`")
    print(f'- `{cli_prefix} use "<session|title|search terms>"`')
    print(f'- `{cli_prefix} handover "<session|title|search terms>"`')
    print(f'- `{cli_prefix} retrieve "<question or search terms>" --limit 10`')
    print(f'- `{cli_prefix} search "<search terms>" --limit 5`')
    print(f"- `{cli_prefix} retrieval-runs --limit 10`")
    print(f"- `{cli_prefix} retrieval-run <retrieval_run_id>`")
    print(f"- `{cli_prefix} personal-context --list`")
    print(f"- `{cli_prefix} personal-context <identifier>`")
    print(f"- `{cli_prefix} repo-context --list`")
    print(f"- `{cli_prefix} repo-context <identifier>`")
    print("")
    print("## Monitor Workflow")
    print("")
    monitor_profile = resolve_monitor_profile(ROOT)
    restart_command = monitor_restart_command(ROOT)
    cli_prefix = preferred_agent_memory_cli_for_root(ROOT)
    print(f"- `{restart_command}`")
    print(f"- `{cli_prefix} runtime-reconcile`")
    print(f"- Local URL after start: `http://{monitor_profile['host']}:{monitor_profile['port']}/?lang={monitor_profile['language']}`")
    print("")
    print("## Personal Operating Memory")
    print("")
    print(_identifier_line("available personal identifiers", [title for title, _body in startup_safe_personal_entries()]))
    print("")
    personal = startup_safe_personal_markdown(max_chars=args.personal_chars)
    print(personal or "_No startup-safe personal memory available._")
    print("")
    print("## Repository Knowledge")
    print("")
    print(_identifier_line("available repo identifiers", [name for name, _body in repo_index_entries()]))
    print("")
    repos = repo_index_markdown(max_chars=args.repo_chars)
    print(repos or "_No repository knowledge available._")
    print("")
    print("## Operating Rules")
    print("")
    print("- Treat repository knowledge and personal memory as local/private operator context.")
    print(f"- After local repository updates that affect monitor/backend/frontend code, restart the local monitor with `{restart_command}` so the running process matches the current checkout.")
    print("- User-only controls such as `approve <risk_event_id> <nonce>`, `approve workdir /absolute/project/path`, `approve explain <reason>`, `reset taint`, `firewall add ...`, `firewall disable session`, `firewall disable session 30m`, `firewall enable session`, `hooks-disable`, `hooks-enable`, and `hooks-status` must be sent by the user as chat messages and must not be executed as tools.")
    return 0


__all__ = [
    "cmd_personal_context",
    "cmd_repo_context",
    "cmd_session_start_context",
    "repo_index_markdown",
    "startup_safe_personal_markdown",
]
