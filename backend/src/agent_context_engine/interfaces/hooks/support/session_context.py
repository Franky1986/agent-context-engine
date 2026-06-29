from __future__ import annotations

import json
import os
from typing import Any

from pathlib import Path

from ....application.integrations import cursor_project_background_runner_status
from ....infrastructure.config import ROOT, json_dumps, session_short
from ....application.personal import PERSONAL_ROOT, parse_frontmatter, personal_files, startup_safe_personal_context
from ....application.firewall import active_firewall_override, firewall_status
from .payloads import normalized_path, one_line
from ....application.instance_profile import preferred_agent_memory_cli_for_root


SESSION_START_HOOK_ENTRY = ROOT / "session-start-hook-entry.md"


def _quote_platform_value(value: str | Path) -> str:
    from ....application.platform import current_platform_profile
    from ....application.platform.runtime_selection import select_path_quoting_adapter

    return select_path_quoting_adapter(current_platform_profile()).quote(str(value))


def agent_memory_command_prefix() -> str:
    cli = preferred_agent_memory_cli_for_root(ROOT)
    if cli == "agent-context-engine":
        return cli
    return f"cd {_quote_platform_value(ROOT)} && {cli}"


def _default_startup_entry(command_prefix: str) -> str:
    from ....application.agent_flow import build_agent_flow_contract, render_session_start_hook_entry
    from ....application.instance_profile import WORKFLOW_RUNNER_DEFAULTS, load_installation_profile

    monitor_runner = str(
        load_installation_profile(ROOT).get("workflows", {}).get("monitor_runner") or WORKFLOW_RUNNER_DEFAULTS["monitor_runner"]
    ).strip() or "codex"
    contract = build_agent_flow_contract(
        preferred_language="en",
        command_prefix=command_prefix,
        repo_context_path="memory/knowledge/repos.md",
        monitor_runner=monitor_runner,
    )
    return render_session_start_hook_entry(contract)


def _user_only_controls_block() -> str:
    return """User-only controls:
- `approve <risk_event_id> <nonce>` for one blocked tool retry
- `approve workdir /absolute/project/path`
- `approve explain <reason>`
- `reset taint`
- `firewall add ...`
- `firewall disable session`
- `firewall disable session 30m`
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
    background = cursor_project_background_runner_status(Path(current_folder or ROOT), expected_memory_root=ROOT)
    runner = str(background.get("headless_runner") or "").strip()
    if not runner:
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
            where dr.runner = ?
              and dr.status = 'failed'
              and (
                lower(coalesce(dr.error_message, '')) like '%authentication required%'
                or lower(coalesce(dr.error_message, '')) like '%not logged in%'
                or lower(coalesce(dr.error_message, '')) like '%not ready%'
                or lower(coalesce(dr.error_message, '')) like '% login%'
                or lower(coalesce(dr.error_message, '')) like '%run /login%'
                or lower(coalesce(dr.error_message, '')) like '%please run /login%'
                or lower(coalesce(dr.error_message, '')) like '%run agent login%'
                or lower(coalesce(dr.error_message, '')) like '%cursor_api_key%'
              )
              and not exists (
                select 1
                from dream_runs later
                where later.session_id = dr.session_id
                  and later.runner = ?
                  and later.status = 'succeeded'
                  and datetime(coalesce(later.finished_at, later.started_at)) > datetime(coalesce(dr.finished_at, dr.started_at))
              )
              and ({scope_sql})
            order by coalesce(dr.finished_at, dr.started_at) desc
            limit ?
            """,
            tuple([runner, runner, *params]),
        )
    )
    if not rows and background["headless_runner_ready"]:
        return ""
    if not rows:
        return ""
    login_command = str(background.get("background_runner_login_command") or f"{runner} login").strip()
    return (
        f"Recent Cursor background runs already failed with authentication errors for `{runner}`. "
        f"Run `{login_command}` so it works in headless background workflows as well."
    )


def _cursor_background_candidates_hint(background: dict[str, Any]) -> str:
    candidates = background.get("background_runner_candidates")
    if not isinstance(candidates, list):
        return ""
    hints: list[str] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        runner = str(item.get("runner") or "").strip()
        if runner not in {"codex", "claude"}:
            continue
        status = str(item.get("auth_status") or item.get("readiness_status") or "").strip()
        if status == "ready":
            continue
        login_command = str(item.get("login_command") or "").strip()
        if status == "auth_required" and login_command:
            hints.append(f"{runner}: run `{login_command}`")
        elif status == "missing_executable":
            hints.append(f"{runner}: install the CLI")
    if len(hints) < 2:
        return ""
    return " Checked background candidates: " + "; ".join(hints) + "."


def cursor_dream_auth_context(client_type: str | None, *, current_folder: str = "") -> str:
    if client_type != "cursor":
        return ""
    background = cursor_project_background_runner_status(Path(current_folder or ROOT), expected_memory_root=ROOT)
    if background["headless_runner_ready"]:
        return ""
    runner = str(background.get("headless_runner") or "").strip()
    detail = str(background.get("background_runner_auth_detail") or background.get("background_runner_detail") or "").strip()
    suffix = f" Current status: {one_line(detail, 180)}" if detail else ""
    candidates_hint = _cursor_background_candidates_hint(background)
    if background["background_runner_status"] == "auth_required" and runner:
        return (
            f"Cursor background runner `{runner}` is not ready. "
            f"Run `{background.get('background_runner_login_command') or f'{runner} login'}` before expecting automatic firewall classification, dreaming, and query expansion in Cursor sessions."
            f"{candidates_hint}{suffix}"
        )
    return (
        "Cursor background LLM workflows are not ready. "
        "Install and authenticate `codex` or `claude` before expecting automatic firewall classification, dreaming, and query expansion in Cursor sessions."
        f"{candidates_hint}{suffix}"
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
    context = cursor_dream_auth_context(client_type, current_folder=current_folder)
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
    background = cursor_project_background_runner_status(Path(current_folder or ROOT), expected_memory_root=ROOT)
    runner = str(background.get("headless_runner") or "").strip()
    login_command = str(background.get("background_runner_login_command") or (f"{runner} login" if runner else "")).strip()
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
        return (
            f"{context} "
            f"Run `{login_command or 'codex login or claude login'}` in a local terminal, finish the auth flow, and then continue in this same chat. "
            "If the requested background runner is missing, install it first. "
            "After that, continue in this same chat with your original Agent Context Engine question. "
            "You can disable the Cursor hooks in Cursor Settings > Hooks, but then Agent Context Engine will not work in this project."
        )
    return (
        f"{context} "
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
        cursor_context = cursor_dream_auth_context(client_type, current_folder=current_folder)
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
