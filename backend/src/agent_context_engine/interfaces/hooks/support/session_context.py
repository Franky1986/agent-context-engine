from __future__ import annotations

import json
import os
from typing import Any

from ....application.dreaming.runners import cursor_agent_auth_status
from ....infrastructure.config import ROOT, json_dumps, session_short, sh_quote
from ....application.personal import PERSONAL_ROOT, parse_frontmatter, personal_files, startup_safe_personal_context
from ....application.firewall import active_firewall_override, firewall_status
from .payloads import normalized_path, one_line
from ....application.instance_profile import preferred_agent_memory_cli_for_root


SESSION_START_HOOK_ENTRY = ROOT / "session-start-hook-entry.md"


def agent_memory_command_prefix() -> str:
    cli = preferred_agent_memory_cli_for_root(ROOT)
    if cli == "agent-context-engine":
        return cli
    return f"cd {sh_quote(str(ROOT))} && {cli}"


def _default_startup_entry(command_prefix: str) -> str:
    return f"""# Session Start

Agent Context Engine command prefix: `{command_prefix}`

- For session list/count/today questions, use `last --limit 10` first and answer from that result. Do not open session, summary, or dream files unless the user explicitly asks for details.
- If the user mentions a local repo/project/folder by name, or asks for side information about another project, resolve it via one of these — do not browse the filesystem:
  - `cat ./memory/knowledge/repos.md` — full repos context (fastest, no CLI needed)
  - `repo-context --list` — overview of known repos
  - `repo-context <identifier>` — targeted context for a specific repo
- Load personal context only on demand, e.g. for "my preferences", "as usual", writing style, language, or personal standards.

Start here for previous work:
- `{command_prefix} last --limit 10`
- `{command_prefix} use "<session|title|search terms>"`
- `{command_prefix} handover "<session|title|search terms>"`
- `{command_prefix} retrieve "<question or search terms>" --limit 10`
- `{command_prefix} search "<search terms>" --limit 5`

Load extra context when needed:
- `{command_prefix} session-start-context`
- `{command_prefix} personal-context --list`
- `{command_prefix} personal-context <identifier>`
- `{command_prefix} repo-context --list`
- `{command_prefix} repo-context <identifier>`
- `{command_prefix} retrieval-runs --limit 10`
- `{command_prefix} retrieval-run <retrieval_run_id>`

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
- `{command_prefix} monitor --runner codex --replace-existing`
"""


def _user_only_controls_block() -> str:
    return """User-only controls:
- `approve ...`
- `reset taint`
- `firewall add ...`
- `firewall disable session`
- `firewall enable session`
- `hooks-disable [--runner <runner>]`
- `hooks-enable [--runner <runner>]`
- `hooks-status`"""


def startup_entry_content() -> str:
    default = _default_startup_entry(agent_memory_command_prefix())
    if not SESSION_START_HOOK_ENTRY.exists():
        return default
    try:
        return SESSION_START_HOOK_ENTRY.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return default


def session_hint(conn: Any, session_id: str, thread_name: str | None) -> str:
    session = conn.execute("select session_brief from sessions where session_id = ?", (session_id,)).fetchone()
    if session and session["session_brief"]:
        return one_line(session["session_brief"])
    if thread_name:
        return one_line(thread_name)
    row = conn.execute(
        """
        select prompt, last_assistant_message
        from events
        where session_id = ? and (prompt is not null or last_assistant_message is not null)
        order by seq desc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    if not row:
        return "No prompt or assistant summary recorded yet."
    return one_line(row["prompt"] or row["last_assistant_message"] or "")


def payload_workdir(payload: dict[str, Any], fallback: str) -> str:
    candidates: list[Any] = []
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        candidates.extend([tool_input.get("workdir"), tool_input.get("working_dir"), tool_input.get("cwd")])
    candidates.extend([
        payload.get("workdir"),
        payload.get("working_dir"),
        fallback,
        payload.get("cwd"),
    ])
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return normalized_path(candidate)
    return normalized_path(fallback)


def session_line(conn: Any, row: Any) -> str:
    hint = session_hint(conn, row["session_id"], row["thread_name"])
    return (
        "- "
        f"id=`{row['session_id']}` "
        f"short=`{session_short(row['session_id'])}` "
        f"client=`{row['client_type']}` "
        f"project=`{row['project_id'] or 'unknown'}` "
        f"last=`{row['last_event_at'] or row['started_at'] or ''}` "
        f"status=`{row['status']}` "
        f"dream=`{row['dream_status']}` "
        f"workdir=`{row['last_workdir'] or row['cwd'] or ''}` "
        f"hint={json.dumps(hint, ensure_ascii=False)}"
    )


def recent_global_sessions(conn: Any, current_session_id: str, *, limit: int = 5) -> list[Any]:
    rows = list(
        conn.execute(
            """
            select *
            from sessions
            where session_id != ?
            order by coalesce(last_event_at, started_at) desc
            limit ?
            """,
            (current_session_id, limit),
        )
    )
    return rows


def recent_folder_sessions(conn: Any, current_session_id: str, folder: str, *, limit: int = 10) -> list[Any]:
    folder = normalized_path(folder)
    if not folder:
        return []
    like_child = f"{folder}/%"
    rows = list(
        conn.execute(
            """
            select *
            from sessions
            where session_id != ?
              and (
                coalesce(last_workdir, '') = ?
                or coalesce(cwd, '') = ?
                or coalesce(last_workdir, '') like ?
                or coalesce(cwd, '') like ?
                or (coalesce(last_workdir, '') != '' and ? like coalesce(last_workdir, '') || '/%')
                or (coalesce(cwd, '') != '' and ? like coalesce(cwd, '') || '/%')
              )
            order by coalesce(last_event_at, started_at) desc
            limit ?
            """,
            (current_session_id, folder, folder, like_child, like_child, folder, folder, limit),
        )
    )
    return list(reversed(rows))


def recent_sessions_context(
    conn: Any,
    current_session_id: str,
    *,
    current_folder: str = "",
    client_type: str | None = None,
    agent_name: str | None = None,
    thread_name: str | None = None,
    project_id: str | None = None,
    global_limit: int = 5,
    folder_limit: int = 10,
) -> str:
    runtime_status = memory_hooks_status_context(
        conn,
        session_id=current_session_id,
        current_folder=current_folder,
        client_type=client_type,
        agent_name=agent_name,
        thread_name=thread_name,
        project_id=project_id,
        include_dream_notice=True,
        include_cursor_auth_notice=True,
    )
    folder_rows = recent_folder_sessions(conn, current_session_id, current_folder, limit=folder_limit)
    global_rows = recent_global_sessions(conn, current_session_id, limit=global_limit)
    personal_startup_count = sum(
        1
        for path in personal_files()
        if parse_frontmatter(path).get("injection_policy") == "startup_safe"
        and parse_frontmatter(path).get("sensitivity") == "normal"
    )
    mode = os.environ.get("AGENT_MEMORY_STARTUP_CONTEXT", "minimal").strip().lower()
    if mode in {"", "minimal", "quiet"}:
        parts = [
            runtime_status,
            startup_entry_content(),
        ]
        return "\n\n".join(part for part in parts if part.strip())
    if not folder_rows and not global_rows and not personal_startup_count:
        return ""
    if mode in {"compact", "brief"}:
        prefix = agent_memory_command_prefix()
        parts = [
            runtime_status,
            startup_entry_content(),
            "Previous sessions are available on demand, but are not injected into the visible chat.",
            f"Use `{prefix} last --limit 10` when needed.",
        ]
        if current_folder:
            parts.append(f"Current launch/work folder: `{current_folder}`.")
        parts.append(f"Indexed recent sessions: folder={len(folder_rows)}, global={len(global_rows)}.")
        if personal_startup_count:
            parts.append(f"Personal operating memory available: {personal_startup_count} startup-safe files under `{PERSONAL_ROOT}`.")
        parts.append("Set `AGENT_MEMORY_STARTUP_CONTEXT=full` before starting Codex to inject the detailed session list.")
        return "\n".join(parts)
    if mode not in {"full", "verbose"}:
        return memory_hooks_status_context(
            conn,
            session_id=current_session_id,
            current_folder=current_folder,
            client_type=client_type,
            agent_name=agent_name,
            thread_name=thread_name,
            project_id=project_id,
        )
    lines = [
        runtime_status,
        "",
        startup_entry_content(),
        "",
        "Agent Context Engine startup context: the last recorded sessions are listed below.",
        f"Use `{agent_memory_command_prefix()} use <session_id>` when the user wants to continue one of them.",
        "",
    ]
    if folder_rows:
        lines.append(f"## Same/Overlapping Folder Sessions (oldest to newest, last {len(folder_rows)})")
        lines.append(f"folder=`{current_folder}`")
        for row in folder_rows:
            lines.append(session_line(conn, row))
        lines.append("")
    if global_rows:
        lines.append(f"## Global Recent Sessions (newest first, last {len(global_rows)})")
        for row in global_rows:
            lines.append(session_line(conn, row))
    personal_context = startup_safe_personal_context(max_chars=4000)
    if personal_context:
        lines.extend(["", "## Personal Operating Memory", personal_context])
    return "\n\n".join(f"{line} " for line in lines).strip()


def _format_firewall_target(row: dict[str, Any]) -> str:
    scope = str(row.get("scope_type") or "unknown")
    if scope == "session":
        return f"session `{row.get('session_id') or ''}`"
    if scope == "agent":
        target = row.get("agent_name") or row.get("thread_name") or row.get("client_type") or "current agent"
        return f"agent `{target}`"
    if scope == "project":
        return f"project `{row.get('project_id') or ''}`"
    if scope == "workdir":
        return f"workdir `{row.get('workdir') or ''}`"
    return scope


def dream_failure_context(
    conn: Any,
    *,
    session_id: str,
    client_type: str | None = None,
    project_id: str | None = None,
    current_folder: str = "",
    limit: int = 3,
) -> str:
    params: list[Any] = [session_id]
    scope_sql = "dr.session_id = ?"
    if client_type and project_id:
        scope_sql += """
            or (
              dr.client_type = ?
              and s.project_id = ?
              and (
                coalesce(s.last_workdir, s.cwd, '') = ?
                or ? like coalesce(s.last_workdir, s.cwd, '') || '/%'
              )
            )
        """
        params.extend([client_type, project_id, current_folder, current_folder])
    params.append(max(1, min(limit, 5)))
    rows = list(
        conn.execute(
            f"""
            select dr.dream_run_id, dr.session_id, dr.client_type, dr.runner,
                   dr.runner_model, dr.finished_at, dr.error_message,
                   s.project_id, s.last_workdir, s.cwd
            from dream_runs dr
            join sessions s on s.session_id = dr.session_id
            where dr.status = 'failed'
              and not exists (
                select 1
                from dream_runs later
                where later.session_id = dr.session_id
                  and later.status = 'succeeded'
                  and datetime(coalesce(later.finished_at, later.started_at)) > datetime(coalesce(dr.finished_at, dr.started_at))
                  and (
                    (
                      lower(coalesce(dr.error_message, '')) like '%database is locked%'
                    )
                    or (
                      later.runner = dr.runner
                      and coalesce(later.runner_model, '') = coalesce(dr.runner_model, '')
                    )
                  )
              )
              and ({scope_sql})
            order by coalesce(dr.finished_at, dr.started_at) desc
            limit ?
            """,
            tuple(params),
        )
    )
    if not rows:
        return ""
    runners = sorted({str(row["runner"] or "-") for row in rows})
    return (
        "Agent Context Engine dream processing needs attention. "
        "Recent dream failures may delay long-term memory updates. "
        f"Affected recent runs: {len(rows)}; runners: {', '.join(runners)}. "
        "Inspect details in the monitor or rerun after fixing the runner."
    )


def cursor_recent_auth_failure_context(
    conn: Any,
    *,
    session_id: str,
    client_type: str | None = None,
    project_id: str | None = None,
    current_folder: str = "",
    limit: int = 3,
) -> str:
    if client_type != "cursor":
        return ""
    ready, _detail = cursor_agent_auth_status()
    if ready:
        return ""
    params: list[Any] = [session_id]
    scope_sql = "dr.session_id = ?"
    if project_id:
        scope_sql += """
            or (
              s.project_id = ?
              and (
                coalesce(s.last_workdir, s.cwd, '') = ?
                or ? like coalesce(s.last_workdir, s.cwd, '') || '/%'
              )
            )
        """
        params.extend([project_id, current_folder, current_folder])
    params.append(max(1, min(limit, 5)))
    rows = list(
        conn.execute(
            f"""
            select dr.dream_run_id, dr.session_id, dr.finished_at, dr.error_message
            from dream_runs dr
            join sessions s on s.session_id = dr.session_id
            where dr.runner = 'cursor'
              and dr.status = 'failed'
              and lower(coalesce(dr.error_message, '')) like '%authentication required%'
              and not exists (
                select 1
                from dream_runs later
                where later.session_id = dr.session_id
                  and later.runner = 'cursor'
                  and later.status = 'succeeded'
                  and datetime(coalesce(later.finished_at, later.started_at)) > datetime(coalesce(dr.finished_at, dr.started_at))
              )
              and ({scope_sql})
            order by coalesce(dr.finished_at, dr.started_at) desc
            limit ?
            """,
            tuple(params),
        )
    )
    if not rows:
        return ""
    return (
        "Recent Cursor dream runs already failed with authentication errors in the background environment. "
        "Run `cursor-agent login` so it works outside the IDE as well, or set `CURSOR_API_KEY`."
    )


def cursor_dream_auth_context(client_type: str | None) -> str:
    if client_type != "cursor":
        return ""
    ready, detail = cursor_agent_auth_status()
    if ready:
        return ""
    suffix = f" Current status: {one_line(detail, 180)}" if detail else ""
    lowered = str(detail or "").lower()
    if "executable is missing" in lowered or "not found" in lowered:
        return (
            "Cursor dream runner is not ready. Install `cursor-agent` first, then run `cursor-agent login` "
            "before expecting automatic dream processing in Cursor sessions."
            f"{suffix}"
        )
    return (
        "Cursor dream runner is not ready. Run `cursor-agent login` or set `CURSOR_API_KEY` "
        "before expecting automatic dream processing in Cursor sessions."
        f"{suffix}"
    )


def cursor_dream_auth_block_message(
    conn: Any,
    *,
    session_id: str,
    client_type: str | None = None,
    project_id: str | None = None,
    current_folder: str = "",
    prompt: str | None = None,
    login_trigger: str = "",
) -> str:
    context = cursor_dream_auth_context(client_type)
    if not context:
        context = cursor_recent_auth_failure_context(
            conn,
            session_id=session_id,
            client_type=client_type,
            project_id=project_id,
            current_folder=current_folder,
        )
    if not context:
        return ""
    prompt_text = str(prompt or "").strip().lower()
    login_intent = any(
        marker in prompt_text
        for marker in (
            "log dich ein",
            "logg dich ein",
            "login",
            "sign in",
            "sign-in",
            "einloggen",
            "anmelden",
        )
    )
    if login_intent:
        if login_trigger == "started":
            login_lead = (
                "I just started `cursor-agent login` for this machine. "
                "Complete the Cursor authentication flow that opens outside the IDE, then continue in this same chat. "
            )
        elif login_trigger == "recently_triggered":
            login_lead = (
                "The Cursor login flow was already triggered for this session a moment ago. "
                "Finish that authentication flow, then continue in this same chat. "
            )
        else:
            login_lead = ""
        return (
            f"{login_lead}{context} "
            "If the login flow did not open, run `cursor-agent login` in a local terminal, finish the auth flow, then verify it with `cursor-agent status`. "
            "If `cursor-agent` is missing, install the Cursor CLI first so the `cursor-agent` command exists. "
            "After that, continue in this same chat with your original Agent Context Engine question. "
            "You can disable the Cursor hooks in Cursor Settings > Hooks, but then Agent Context Engine will not work in this project."
        )
    if login_trigger == "started":
        login_lead = (
            "Agent Context Engine just started `cursor-agent login` for this machine. "
            "Complete the Cursor authentication flow that opens outside the IDE, then continue in this same chat. "
        )
    elif login_trigger == "recently_triggered":
        login_lead = (
            "The Cursor login flow was already triggered for this session a moment ago. "
            "Finish that authentication flow, then continue in this same chat. "
        )
    elif login_trigger == "missing_executable":
        login_lead = (
            "The login flow could not be started because `cursor-agent` is missing on this machine. "
            "Install the Cursor CLI first, then continue in this same chat. "
        )
    elif login_trigger == "start_failed":
        login_lead = (
            "Agent Context Engine tried to start `cursor-agent login` automatically but the local process could not be launched. "
            "Run `cursor-agent login` in a local terminal, then continue in this same chat. "
        )
    else:
        login_lead = ""
    return (
        f"{login_lead}{context} "
        "You can disable the Cursor hooks in Cursor Settings > Hooks, but then Agent Context Engine will not work in this project."
    )


def memory_hooks_status_context(
    conn: Any,
    *,
    session_id: str,
    current_folder: str = "",
    client_type: str | None = None,
    agent_name: str | None = None,
    thread_name: str | None = None,
    project_id: str | None = None,
    include_dream_notice: bool = True,
    include_cursor_auth_notice: bool = False,
) -> str:
    lines = [
        f"Agent Context Engine active in `{ROOT}`",
        f"Agent Context Engine active root: `{ROOT}`",
    ]
    status = firewall_status(conn)
    if not status.get("enabled", True):
        until = status.get("disabled_until") or "unknown"
        reason = one_line(status.get("reason") or "", 180)
        suffix = f" Reason: {reason}" if reason else ""
        lines.append(f"Firewall disabled globally until `{until}`.{suffix}")
    override = active_firewall_override(
        conn,
        session_id=session_id,
        client_type=client_type,
        agent_name=agent_name or thread_name,
        thread_name=thread_name,
        project_id=project_id,
        workdir=current_folder,
    )
    if override:
        until = override.get("expires_at") or "unknown"
        reason = one_line(override.get("reason") or "", 180)
        suffix = f" Reason: {reason}" if reason else ""
        lines.append(f"Firewall override active for {_format_firewall_target(override)} until `{until}`.{suffix}")
    lines.append(_user_only_controls_block())
    if include_dream_notice:
        dream_context = dream_failure_context(
            conn,
            session_id=session_id,
            client_type=client_type,
            project_id=project_id,
            current_folder=current_folder,
        )
        if dream_context:
            lines.append(dream_context)
    if include_cursor_auth_notice:
        cursor_context = cursor_dream_auth_context(client_type)
        if cursor_context:
            lines.append(cursor_context)
    return "\n\n".join(line for line in lines if line.strip())


def hook_context_output(event: str, additional_context: str) -> None:
    if not additional_context.strip():
        return
    print(
        json_dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": additional_context,
                }
            }
        )
    )
