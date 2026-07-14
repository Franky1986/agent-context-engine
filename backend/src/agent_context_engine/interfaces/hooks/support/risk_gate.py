from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import uuid
from typing import Any

from ....infrastructure.config import MEMORY_DIR, utc_now
from ....application.firewall_rules import VALID_ACTIONS, apply_direct_user_firewall_commands
from ....application.hooks_state import apply_direct_user_hook_state_commands
from ....application.risk import shell_action_class
from .payloads import normalized_path, one_line


def risk_labels(preview: str | None, reason: str | None = "", impact: str | None = "", flags: list[str] | None = None) -> dict[str, str]:
    command = one_line(preview, 260)
    lower = command.lower()
    joined_flags = set(flags or [])
    if command.startswith("*** Begin Patch"):
        match = re.search(r"\*\*\* (Add|Update|Delete) File: ([^\n\r]+)", preview or "")
        action = {"Add": "create file", "Update": "modify file", "Delete": "delete file"}.get(match.group(1), "apply patch") if match else "apply patch"
        target = one_line(match.group(2), 120) if match else "local file(s)"
        intent = f"{action}: {target}"
        not_executed = "The patch was not applied; affected files were left unchanged."
    elif re.match(r"^(bun|npm|pnpm|yarn)\s+", lower):
        intent = "run project verification" if re.search(r"\b(test|typecheck|type-check|lint|audit|check|verify)\b", lower) else "run package-manager command"
        not_executed = "The package-manager command was not executed; verification or script execution is still missing."
    elif lower.startswith("git status"):
        intent = "inspect Git working tree"
        not_executed = "Git status was not queried; the working tree state was not confirmed by this tool call."
    elif lower.startswith("git "):
        intent = "run Git command"
        not_executed = "The Git command was not executed."
    elif re.match(r"^mkdir\b", lower):
        intent = "create directory structure"
        not_executed = "The directories were not created."
    elif re.match(r"^chmod\b", lower):
        intent = "change file permissions"
        not_executed = "File permissions were not changed."
    elif re.match(r"^(sed|cat|head|tail|nl|rg|find|ls|pwd)\b", lower):
        intent = "read local context"
        not_executed = "The local inspection was not executed; the requested information is still missing."
    elif re.search(r"\b(curl|wget)\b", lower):
        intent = "start network download or external request"
        not_executed = "The network/download command was not executed."
    elif re.search(r"\brm\b|\bdelete\b|\btruncate\b", lower):
        intent = "delete or remove data"
        not_executed = "The delete action was not executed."
    else:
        intent = "run tool call"
        not_executed = "The tool call was not executed; the planned step is still open."

    reason_text = " ".join(str(item or "") for item in [reason, impact]).lower()
    if "agent_self_approval_attempt" in joined_flags:
        why = "The active agent is not allowed to approve its own risk blocks through tool calls."
    elif "classifier_invalid_output" in joined_flags or "classifier_schema_violation" in joined_flags:
        why = "The firewall classifier returned invalid structured output, so Agent Context Engine blocked fail-closed instead of guessing."
    elif "tainted_context_side_effect" in joined_flags or "approval_required" in joined_flags or "tainted context" in reason_text or "prior sensitive" in reason_text:
        why = "Earlier risky or sensitive context was detected in this session; follow-up write or execution actions need explicit approval."
    elif (
        "network_to_shell" in joined_flags
        or "network_to_interpreter" in joined_flags
        or "network_download_execute" in joined_flags
        or "shell_pipe_to_interpreter" in joined_flags
    ):
        why = "Remote or decoded content would be passed directly to an interpreter/shell or made executable in the same step."
    elif "recursive_force_delete" in joined_flags or "destructive_command" in joined_flags:
        why = "The command can delete local data broadly or irreversibly."
    elif "credential_like_material" in joined_flags or "credential_exfiltration" in joined_flags:
        why = "The content looks like credentials or other secret material."
    else:
        why = one_line(reason, 220) or "Agent Context Engine detected risk in this tool call."
    return {"intent": intent, "why": why, "not_executed": not_executed}


def _taint_sources(decision: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    raw = getattr(decision, "taint_context", None) or []
    items: list[dict[str, Any]] = []
    for entry in raw[:limit]:
        if not isinstance(entry, dict):
            continue
        items.append(
            {
                "risk_event_id": one_line(entry.get("risk_event_id"), 80),
                "status": one_line(entry.get("status"), 40),
                "decision": one_line(entry.get("decision"), 40),
                "risk_level": one_line(entry.get("risk_level"), 40),
                "reason": one_line(entry.get("reason"), 220),
                "categories": entry.get("categories") or entry.get("categories_json") or [],
                "poisoning_flags": entry.get("poisoning_flags") or entry.get("poisoning_flags_json") or [],
            }
        )
    return items


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item)]
    return []


def _taint_context_has_classifier_failure(items: list[dict[str, Any]]) -> bool:
    for item in items:
        flags = set(_json_list(item.get("categories"))) | set(_json_list(item.get("poisoning_flags")))
        text = f"{item.get('reason') or ''} {item.get('impact') or ''}".lower()
        if {"classifier_invalid_output", "classifier_schema_violation"} & flags:
            return True
        if "classifier runner failed" in text or "classifier output" in text or "valid policy json" in text:
            return True
    return False


def blocking_reason(decision: Any) -> str:
    reason = one_line(getattr(decision, "reason", "") or "Tool use blocked by Agent Context Engine policy.", 260)
    impact = one_line(getattr(decision, "impact", "") or "", 260)
    approval_state = one_line(getattr(decision, "approval_state", "") or "", 80)
    approval_token = one_line(getattr(decision, "approval_token", "") or "", 80)
    command_hash = one_line(getattr(decision, "command_hash", "") or "", 80)
    risk_event_id = one_line(getattr(decision, "risk_event_id", "") or "", 80)
    flags: list[str] = []
    for attr in ("categories", "poisoning_flags", "deterministic_flags"):
        for flag in getattr(decision, attr, None) or []:
            if str(flag) not in flags:
                flags.append(str(flag))
    flag_text = ", ".join(str(flag) for flag in list(flags)[:6])
    command_preview = one_line(getattr(decision, "preview", "") or "", 700)
    labels = risk_labels(getattr(decision, "preview", "") or "", reason, impact, [str(flag) for flag in flags])
    taint_sources = _taint_sources(decision)
    if "tainted_context_side_effect" in flags and _taint_context_has_classifier_failure(taint_sources):
        labels["why"] = (
            "An earlier firewall classifier failure tainted this session. "
            "This follow-up side-effect action needs explicit approval because Agent Context Engine cannot rely on that prior classifier output."
        )
    parts = [
        f"Blocked command: `{command_preview or '<unavailable>'}`",
        f"Agent Context Engine blocked this tool use: {labels['intent']}.",
        f"Why: {labels['why']}",
        f"Not executed: {labels['not_executed']}",
    ]
    if impact:
        parts.append(f"Impact: {impact}")
    if approval_state:
        parts.append(f"Approval: {approval_state}.")
    if risk_event_id:
        parts.append(f"Command: stored in local risk audit/monitor only (`monitor:risk_events:{risk_event_id}`).")
    if taint_sources:
        parts.append(
            "Taint sources that currently influence this block:\n"
            + "\n".join(
                f"- `{item['risk_event_id'] or '-'}` status={item['status'] or '-'} decision={item['decision'] or '-'} level={item['risk_level'] or '-'} "
                f"flags={json.dumps(_json_list(item.get('categories')) + _json_list(item.get('poisoning_flags')), ensure_ascii=False)} "
                f"reason={json.dumps(item['reason'] or '-', ensure_ascii=False)}"
                for item in taint_sources
            )
        )
    firewall_command = one_line(getattr(decision, "firewall_add_command", "") or "", 900)
    self_control_block = "agent_self_approval_attempt" in flags
    if self_control_block:
        parts.append(
            "This control-plane block cannot be bypassed with an approval or firewall rule. "
            "Do not retry the command, its help variant, or another mutating ACE command as a tool."
        )
        parts.append(
            "If the user asked to suspend the whole system, reply with this exact copyable direct-chat form:\n"
            "system-disable --scope all --reason \"<reason>\"\n"
            "For hook-only control, tell the user to send the bare `hooks-disable` chat line. "
            "Do not remove global wrappers; they are part of the recovery path."
        )
    elif firewall_command:
        parts.append(
            "To persistently allow this reviewed command pattern, the user can send this exact chat line; "
            f"the agent must not execute it as a tool:\n{firewall_command}"
        )
    else:
        command_pattern_hint = ""
        if command_preview:
            command_pattern_hint = f" for example `--command-pattern {shlex.quote(command_preview)}`"
        parts.append(
            "If the user wants a persistent reviewed allow-rule instead of a one-off approval, "
            f"they can send a matching `firewall add ...` chat line{command_pattern_hint}; the agent must not execute it as a tool."
        )
    if "tainted_context_side_effect" in flags:
        parts.append(
            "If the older tainted context was reviewed and should no longer affect this chat, "
            "the user can clear only the taint guard with this exact chat line; do not execute it as a tool:\nreset taint"
        )
        parts.append(
            "If the user instead wants to suspend blocking for the whole session, these control-plane chat lines also work and must not be executed as tools:\n"
            "firewall disable session\n"
            "firewall disable session 30m"
        )
    if command_hash:
        parts.append(f"Command hash: {command_hash[:16]}.")
    if flag_text:
        parts.append(f"Flags: {flag_text}")
    if not self_control_block and approval_state == "required" and risk_event_id and approval_token:
        parts.append(
            "Only this exact one-time approval syntax is valid here. "
            "Do not replace it with the blocked shell command or paraphrase it."
        )
        parts.append("Copyable approval line for this exact blocked tool use:")
        parts.append(f"approve {risk_event_id} {approval_token}")
    return "\n\n".join(parts)


def recent_taint_context(conn: Any, session_id: str, *, before_seq: int, limit: int = 5) -> list[dict[str, Any]]:
    try:
        window = max(1, int(os.environ.get("AGENT_MEMORY_TAINT_EVENT_WINDOW", "16")))
    except ValueError:
        window = 16
    min_seq = max(0, int(before_seq or 0) - window)
    reset = conn.execute(
        """
        select max(event_seq) as event_seq
        from session_taint_resets
        where session_id = ?
          and event_seq < ?
        """,
        (session_id, before_seq),
    ).fetchone()
    if reset and reset["event_seq"] is not None:
        min_seq = max(min_seq, int(reset["event_seq"]))
    rows = conn.execute(
        """
        select risk_event_id, created_at, event_seq, source_kind, source_ref,
               status, decision, risk_level, sensitivity, categories_json,
               poisoning_flags_json, substr(reason, 1, 220) as reason
        from risk_events
        where session_id = ?
          and coalesce(event_seq, 0) < ?
          and coalesce(event_seq, 0) >= ?
          and coalesce(status, '') not in ('reviewed_safe', 'review_consumed')
          and coalesce(approval_state, '') not in ('approved', 'approved_by_user_prompt', 'consumed', 'policy_allowlisted')
          and (
            status in ('blocked', 'quarantined')
            or decision in ('block', 'quarantine')
            or risk_level = 'critical'
            or sensitivity = 'secret'
            or injection_policy in ('never_auto', 'quarantine')
          )
        order by coalesce(event_seq, 0) desc, created_at desc
        limit ?
        """,
        (session_id, before_seq, min_seq, limit),
    )
    return [
        {
            "risk_event_id": row["risk_event_id"],
            "event_seq": row["event_seq"],
            "source_kind": row["source_kind"],
            "source_ref": row["source_ref"],
            "status": row["status"],
            "decision": row["decision"],
            "risk_level": row["risk_level"],
            "sensitivity": row["sensitivity"],
            "categories_json": row["categories_json"],
            "poisoning_flags_json": row["poisoning_flags_json"],
            "reason": row["reason"],
        }
        for row in rows
    ]


def consume_recent_command_approval(conn: Any, session_id: str, command_hash: str) -> str | None:
    if not command_hash:
        return None
    row = conn.execute(
        """
        select risk_event_id
        from risk_events
        where session_id = ?
          and command_hash = ?
          and status = 'reviewed_safe'
          and decision = 'allow'
          and approval_state in ('approved_by_user_prompt', 'approved')
        order by updated_at desc
        limit 1
        """,
        (session_id, command_hash),
    ).fetchone()
    if row is None:
        return None
    conn.execute(
        """
        update risk_events
        set updated_at = ?,
            approval_state = 'consumed',
            status = 'review_consumed'
        where risk_event_id = ?
        """,
        (utc_now(), row["risk_event_id"]),
    )
    return str(row["risk_event_id"])


def apply_consumed_command_approval(decision: Any, consumed_approval: str | None) -> Any:
    if not consumed_approval:
        return decision
    decision.decision = "warn"
    if decision.risk_level == "critical":
        decision.risk_level = "high"
    elif decision.risk_level not in {"high", "medium"}:
        decision.risk_level = "medium"
    decision.approval_state = "approved_by_user_prompt"
    decision.memory_action = "reference_only"
    if "approved_command_hash" not in decision.deterministic_flags:
        decision.deterministic_flags.append("approved_command_hash")
    decision.reason = f"User prompt approved this exact command hash once via {consumed_approval}; allowing with audit warning."
    decision.impact = "The exact command hash was approved by the user in this chat; execution is audited and the approval is consumed once."
    return decision


def user_prompt_approvals(prompt: str | None) -> list[tuple[str, str]]:
    approvals: list[tuple[str, str]] = []
    pattern = re.compile(r"^\s*approve\s+(risk_[A-Za-z0-9]+)\s+((?:nonce_|approve:)[A-Fa-f0-9]+)\s*$", re.I)
    for line in (prompt or "").splitlines():
        match = pattern.fullmatch(line)
        if match:
            approvals.append((match.group(1), match.group(2)))
    return approvals


def user_prompt_approval(prompt: str | None) -> tuple[str, str] | None:
    approvals = user_prompt_approvals(prompt)
    return approvals[0] if approvals else None


def invalid_user_prompt_approvals(prompt: str | None) -> list[str]:
    invalid: list[str] = []
    approve_once_pattern = re.compile(r"^\s*approve\s+(risk_[A-Za-z0-9]+)\s+((?:nonce_|approve:)[A-Fa-f0-9]+)\s*$", re.I)
    approve_workdir_pattern = re.compile(r"^\s*approve\s+workdir\s+(.+?)\s*$", re.I)
    approve_explain_pattern = re.compile(r"^\s*approve\s+explain\b.+$", re.I)
    for line in (prompt or "").splitlines():
        stripped = line.strip()
        if not stripped or not re.match(r"^approve\b", stripped, re.I):
            continue
        if (
            approve_once_pattern.fullmatch(stripped)
            or approve_workdir_pattern.fullmatch(stripped)
            or approve_explain_pattern.fullmatch(stripped)
        ):
            continue
        invalid.append(stripped)
    return invalid


def user_prompt_workdir_approvals(prompt: str | None) -> list[str]:
    approvals: list[str] = []
    pattern = re.compile(r"^\s*approve\s+workdir\s+(.+?)\s*$", re.I)
    for line in (prompt or "").splitlines():
        match = pattern.fullmatch(line)
        if not match:
            continue
        raw = match.group(1).strip().strip("`\"'")
        path = normalized_path(raw)
        if path and path.startswith("/"):
            approvals.append(path)
    return approvals


def user_prompt_taint_reset(prompt: str | None) -> bool:
    for line in (prompt or "").splitlines():
        normalized = line.strip().lower()
        if normalized in {
            "reset taint",
            "reset risk taint",
            "reset firewall taint",
            "agent-memory reset taint",
            "agent memory reset taint",
            "taint reset",
        }:
            return True
    return False


def _record_taint_reset(conn: Any, session_id: str, *, event_seq: int | None, reviewer: str, reason: str) -> None:
    conn.execute(
        """
        insert into session_taint_resets (
          reset_id, session_id, event_seq, created_at, reviewer, reason
        ) values (?, ?, ?, ?, ?, ?)
        """,
        (f"taintrst_{uuid.uuid4().hex[:16]}", session_id, int(event_seq or 0), utc_now(), reviewer, reason),
    )


def apply_user_prompt_approval(conn: Any, session_id: str, prompt: str | None, *, event_seq: int | None = None) -> str:
    risk_approvals = user_prompt_approvals(prompt)
    invalid_approvals = invalid_user_prompt_approvals(prompt)
    workdir_approvals = user_prompt_workdir_approvals(prompt)
    reset_taint = user_prompt_taint_reset(prompt)
    try:
        firewall_lines = apply_direct_user_firewall_commands(conn, prompt, session_id=session_id, event_seq=event_seq)
    except ValueError as exc:
        firewall_lines = [f"Firewall command rejected: {exc}"]
    try:
        hook_lines = apply_direct_user_hook_state_commands(prompt)
    except ValueError as exc:
        hook_lines = [f"Hooks command rejected: {exc}"]
    if not risk_approvals and not invalid_approvals and not workdir_approvals and not reset_taint and not firewall_lines and not hook_lines:
        return ""
    lines: list[str] = []
    now = utc_now()
    lines.extend(hook_lines)
    lines.extend(firewall_lines)
    for invalid_line in invalid_approvals:
        lines.extend(
            [
                f"Invalid direct chat approval command: {invalid_line}",
                "Valid direct chat approval forms are:",
                "- `approve <risk_event_id> <nonce>` for exactly one blocked tool retry",
                "- `approve workdir /absolute/project/path` for a local workdir in this session",
                "- `approve explain <reason>` for short-lived classifier context",
                "A line such as `approve <shell command>` is not valid and does not approve the blocked tool use.",
            ]
        )
    reset_recorded = False
    if any(
        line.startswith(
            (
                "Firewall rule created:",
                "Firewall intent recorded:",
                "Session firewall disabled:",
                "Session firewall enabled:",
            )
        )
        for line in firewall_lines
    ):
        _record_taint_reset(
            conn,
            session_id,
            event_seq=event_seq,
            reviewer="user_prompt",
            reason="reset tainted-context guard after direct user firewall approval command",
        )
        reset_recorded = True
        lines.append(
            "Reset tainted-context guard after direct firewall approval command. "
            "Audit history is preserved; future high-risk commands are still classified normally."
        )
    if reset_taint:
        _record_taint_reset(
            conn,
            session_id,
            event_seq=event_seq,
            reviewer="user_prompt",
            reason="reset tainted-context guard by direct user prompt",
        )
        reset_recorded = True
        lines.append(
            "Reset tainted-context guard for this chat from this point forward. "
            "Audit history is preserved; future high-risk commands are still classified normally."
        )
    for risk_event_id, nonce in risk_approvals:
        row = conn.execute(
            """
            select risk_event_id, command_hash
            from risk_events
            where session_id = ?
              and risk_event_id = ?
              and approval_token = ?
              and approval_state = 'required'
              and status = 'blocked'
              and decision = 'block'
            """,
            (session_id, risk_event_id, nonce),
        ).fetchone()
        if row is None:
            lines.append(f"Approval token did not match an active blocked risk event in this session: {risk_event_id}")
            continue
        conn.execute(
            """
            update risk_events
            set updated_at = ?,
                status = 'reviewed_safe',
                decision = 'allow',
                risk_level = 'medium',
                approval_state = 'approved_by_user_prompt',
                policy = 'chat-approval'
            where risk_event_id = ?
            """,
            (now, risk_event_id),
        )
        lines.append(f"Approved exactly once for next matching command hash: {risk_event_id} hash={str(row['command_hash'] or '')[:16]}")
        if not reset_recorded:
            _record_taint_reset(
                conn,
                session_id,
                event_seq=event_seq,
                reviewer="user_prompt",
                reason=f"reset tainted-context guard after direct user approval {risk_event_id}",
            )
            reset_recorded = True
            lines.append(
                "Reset tainted-context guard after direct approval. "
                "Audit history is preserved; future high-risk commands are still classified normally."
            )
    for path in workdir_approvals:
        conn.execute(
            """
            insert into session_approved_workdirs (
              session_id, approved_path, created_at, reviewer, reason
            ) values (?, ?, ?, ?, ?)
            on conflict(session_id, approved_path) do update set
              created_at = excluded.created_at,
              reviewer = excluded.reviewer,
              reason = excluded.reason
            """,
            (session_id, path, now, "user_prompt", "approved by direct user prompt"),
        )
        lines.append(f"Approved workdir for this session: {path}")
    return "\n".join(lines)


def pending_approvals_count(conn: Any, session_id: str) -> int:
    row = conn.execute(
        """
        select count(*) as count
        from risk_events
        where session_id = ?
          and status = 'blocked'
          and decision = 'block'
          and approval_state = 'required'
        """,
        (session_id,),
    ).fetchone()
    return int(row["count"] or 0) if row else 0


def should_show_pending_approvals(prompt: str | None) -> bool:
    stripped_lines = [line.strip() for line in (prompt or "").splitlines() if line.strip()]
    recognized = len(user_prompt_approvals(prompt)) + len(user_prompt_workdir_approvals(prompt)) + (1 if user_prompt_taint_reset(prompt) else 0)
    if stripped_lines and recognized == len(stripped_lines):
        return False
    text = (prompt or "").lower()
    return bool(re.search(r"\b(block|blocked|approval|approvals|approve|pending|risk|quarantine|firewall)\b|freigab|geblock|offen|nicht ausgef", text))


def should_suggest_firewall_rule(prompt: str | None) -> bool:
    text = (prompt or "").lower()
    if "firewall" not in text:
        return False
    return bool(
        re.search(
            r"\b(add|allow|rule|rules|suggest|suggestion|vorschlag|vorschlagen|regel|regeln|aufnehmen|freigeben|erlauben)\b",
            text,
        )
    )


def _firewall_action_from_risk_row(row: Any) -> str:
    preview = str(row["preview"] or "")
    action = shell_action_class(preview)
    if action in VALID_ACTIONS:
        return action
    try:
        categories = json.loads(row["categories_json"] or "[]")
    except json.JSONDecodeError:
        categories = []
    category_set = {str(item) for item in categories if item}
    for candidate in ("deploy", "network", "write_execute", "delete", "write", "verify", "read"):
        if candidate in category_set:
            return candidate
    return "unknown"


def firewall_add_command_for_blocked_tool(
    *,
    preview: str | None,
    workdir: str | None,
    risk_event_id: str | None = None,
    categories: list[str] | None = None,
) -> str:
    command = " ".join(str(preview or "").strip().split())
    if not command or command.startswith("*** Begin Patch") or len(command) > 500:
        return ""
    action = shell_action_class(command)
    if action not in VALID_ACTIONS:
        category_set = {str(item) for item in categories or [] if item}
        action = next((candidate for candidate in ("deploy", "network", "write_execute", "delete", "write", "verify", "read") if candidate in category_set), "unknown")
    risk_short = str(risk_event_id or "risk").replace("risk_", "")[:8] or "reviewed"
    name = f"allow-{action}-{risk_short}"
    reason = f"User reviewed blocked {action} tool use and wants a persistent Agent Context Engine firewall rule"
    return " ".join(
        [
            "firewall",
            "add",
            "--name",
            shlex.quote(name),
            "--reason",
            shlex.quote(reason),
            "--scope",
            "workdir",
            "--workdir",
            shlex.quote(str(workdir or os.getcwd())),
            "--action",
            shlex.quote(action),
            "--command-pattern",
            shlex.quote(command),
            "--permanent",
        ]
    )


def should_suggest_firewall_add_for_blocked_tool(
    conn: Any,
    *,
    session_id: str,
    workdir: str | None,
    command_hash: str | None,
    approval_state: str | None,
    categories: list[str] | None = None,
    flags: list[str] | None = None,
) -> bool:
    approval = str(approval_state or "").strip()
    if approval and approval != "required":
        return False
    category_set = {str(item) for item in categories or [] if item}
    flag_set = {str(item) for item in flags or [] if item}
    if not command_hash:
        return False
    if flag_set & {
        "credential_like_material",
        "credential_exfiltration",
        "network_to_shell",
        "network_to_interpreter",
        "network_download_execute",
        "decoded_payload_to_shell",
        "recursive_force_delete",
        "destructive_git",
        "firewall_disable_attempt",
        "agent_self_approval_attempt",
    }:
        return False
    if category_set & {
        "credential_exfiltration",
        "shell_pipe_to_interpreter",
        "network_pipe_to_interpreter",
        "download_then_execute",
        "destructive_command",
        "firewall_control",
    }:
        return False
    if approval == "required" and not (
        {"approval_required"} & category_set
        or {"tainted_context_side_effect", "tainted_context_nearby"} & flag_set
    ):
        return False
    row = conn.execute(
        """
        select count(*) as count
        from risk_events
        where session_id = ?
          and command_hash = ?
          and coalesce(workdir, '') = coalesce(?, '')
          and (
            status in ('blocked', 'reviewed_safe', 'review_consumed')
            or approval_state in ('required', 'approved_by_user_prompt', 'consumed')
          )
        """,
        (session_id, command_hash, workdir or ""),
    ).fetchone()
    prior_count = max(0, int((row["count"] or 0) if row else 0) - 1)
    return prior_count >= 1


def _latest_pending_firewall_risk(conn: Any, session_id: str) -> Any | None:
    return conn.execute(
        """
        select risk_event_id, event_seq, created_at, preview, workdir,
               categories_json, poisoning_flags_json, deterministic_flags_json
        from risk_events
        where session_id = ?
          and status = 'blocked'
          and decision = 'block'
          and coalesce(preview, '') != ''
        order by coalesce(event_seq, 0) desc, created_at desc
        limit 1
        """,
        (session_id,),
    ).fetchone()


def pending_firewall_rule_suggestion_context(conn: Any, session_id: str, prompt: str | None) -> str:
    if not should_suggest_firewall_rule(prompt):
        return ""
    row = _latest_pending_firewall_risk(conn, session_id)
    if row is None:
        return "Agent Context Engine firewall suggestion: no active blocked tool use found for this session."
    command = firewall_add_command_for_blocked_tool(
        preview=row["preview"],
        workdir=row["workdir"],
        risk_event_id=row["risk_event_id"],
        categories=json.loads(row["categories_json"] or "[]"),
    )
    if not command:
        return ""
    return "\n".join(
        [
            "Agent Context Engine suggested firewall rule for the latest blocked tool use:",
            command,
            "The agent must not execute this as a shell/tool command. The user must send the exact `firewall add ...` line as a chat message to store it deterministically.",
        ]
    )


def pending_approvals_summary_context(conn: Any, session_id: str) -> str:
    total = pending_approvals_count(conn, session_id)
    if total <= 0:
        return ""
    return (
        f"Pending blocked approvals: {total}. "
        "Details and exact commands are available in agent-monitor; commands are not injected into chat context. "
        f"{total} older blocked approval(s) remain hidden."
    )


def pending_approvals_context(conn: Any, session_id: str, *, limit: int = 8) -> str:
    total = pending_approvals_count(conn, session_id)
    rows = list(
        conn.execute(
            """
            select risk_event_id, approval_token, event_seq, created_at,
                   substr(replace(preview, char(10), ' '), 1, 220) as preview,
                   substr(replace(reason, char(10), ' '), 1, 240) as reason,
                   substr(replace(impact, char(10), ' '), 1, 240) as impact,
                   categories_json, poisoning_flags_json, deterministic_flags_json
            from risk_events
            where session_id = ?
              and status = 'blocked'
              and decision = 'block'
              and approval_state = 'required'
            order by coalesce(event_seq, 0) desc, created_at desc
            limit ?
            """,
            (session_id, limit),
        )
    )
    if not rows:
        return ""
    suffix = "" if total <= len(rows) else f" of {total}"
    lines = [
        f"Agent Context Engine pending blocked approvals: {len(rows)}{suffix} shown.",
        "Each listed tool use was not executed. Approve only the exact item you want retried.",
        "Only these direct chat approval forms are valid: `approve <risk_event_id> <nonce>`, `approve workdir /absolute/project/path`, and `approve explain <reason>`. A line such as `approve <shell command>` is invalid.",
        "Commands are stored in the local risk audit/monitor only and are not injected into chat context.",
        "If these blocks only came from earlier tainted context and you reviewed it, the user can clear only the taint guard with this exact chat line; do not execute it as a tool:",
        "reset taint",
        "If the user wants to suspend blocking for the whole session instead, these control-plane chat lines also work and must not be executed as tools:",
        "firewall disable session",
        "firewall disable session 30m",
    ]
    approval_lines: list[str] = []
    for row in rows:
        flags: list[str] = []
        for field in ("categories_json", "poisoning_flags_json", "deterministic_flags_json"):
            try:
                decoded = json.loads(row[field] or "[]")
                if isinstance(decoded, list):
                    flags.extend(str(item) for item in decoded)
            except json.JSONDecodeError:
                pass
        labels = risk_labels(row["preview"], row["reason"], row["impact"], flags)
        lines.append(
            "- "
            f"risk=`{row['risk_event_id']}` "
            f"seq=`{row['event_seq']}` "
            f"intent={json.dumps(labels['intent'], ensure_ascii=False)} "
            f"why={json.dumps(labels['why'], ensure_ascii=False)} "
            f"not_executed={json.dumps(labels['not_executed'], ensure_ascii=False)} "
            f"command_ref=`monitor:risk_events:{row['risk_event_id']}`"
        )
        approval_line = f"approve {row['risk_event_id']} {row['approval_token']}"
        approval_lines.append(approval_line)
        lines.append(f"  approve once: `{approval_line}`")
    if approval_lines:
        lines.extend(
            [
                "Copyable approval lines for the shown blocked tool uses:",
                *approval_lines,
            ]
        )
    return "\n".join(lines)


def command_policy_allowlist_match(command: str, command_hash: str, workdir: str | None) -> dict[str, Any] | None:
    path = MEMORY_DIR / "policies" / "risk-allowlist.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    entries = data.get("entries") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return None
    now = utc_now()
    normalized_command = " ".join(str(command or "").strip().split())
    normalized_workdir = str(workdir or "")
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        expires_at = str(entry.get("expires_at") or "")
        if expires_at and expires_at < now:
            continue
        workdir_prefix = str(entry.get("workdir_prefix") or "")
        if workdir_prefix and not normalized_workdir.startswith(workdir_prefix):
            continue
        hashes = entry.get("command_hashes")
        if isinstance(hashes, list) and command_hash and command_hash in {str(item) for item in hashes}:
            return entry
        pattern = str(entry.get("command_pattern") or "")
        if pattern and fnmatch.fnmatch(normalized_command, pattern):
            return entry
    return None


def session_approved_workdir_match(conn: Any, session_id: str, command: str, workdir: str | None) -> str | None:
    rows = list(
        conn.execute(
            """
            select approved_path
            from session_approved_workdirs
            where session_id = ?
            order by length(approved_path) desc
            """,
            (session_id,),
        )
    )
    if not rows:
        return None
    normalized_command = str(command or "")
    normalized_workdir = normalized_path(workdir or "")
    for row in rows:
        approved_path = str(row["approved_path"] or "")
        if not approved_path:
            continue
        aliases = {approved_path}
        if approved_path.startswith("/private/var/"):
            aliases.add("/var/" + approved_path[len("/private/var/") :])
        elif approved_path.startswith("/var/"):
            aliases.add("/private/var/" + approved_path[len("/var/") :])
        if normalized_workdir and any(normalized_workdir == alias or normalized_workdir.startswith(alias + "/") for alias in aliases):
            return approved_path
        if any(alias in normalized_command for alias in aliases):
            return approved_path
    return None


def apply_session_workdir_approval(decision: Any, approved_path: str | None, *, action_class: str) -> Any:
    if not approved_path or action_class in {"network", "delete"}:
        return decision
    flags = set(getattr(decision, "poisoning_flags", []) or []) | set(getattr(decision, "deterministic_flags", []) or []) | set(getattr(decision, "categories", []) or [])
    hard_without_taint = flags - {"tainted_context_side_effect", "tainted_context_nearby", "approval_required"}
    if {"network_to_shell", "decoded_payload_to_shell", "recursive_force_delete", "destructive_git", "agent_self_approval_attempt"} & hard_without_taint:
        return decision
    if getattr(decision, "should_block", False) or getattr(decision, "approval_state", "") == "required":
        decision.decision = "warn"
        if decision.risk_level == "critical":
            decision.risk_level = "high"
        elif decision.risk_level not in {"high", "medium", "low"}:
            decision.risk_level = "medium"
        decision.approval_state = "workdir_approved"
        decision.memory_action = "reference_only"
        decision.injection_policy = "on_demand"
        if "session_workdir_approved" not in decision.deterministic_flags:
            decision.deterministic_flags.append("session_workdir_approved")
        decision.reason = f"User approved this workdir for the session: {approved_path}; local non-network side effect allowed with audit warning."
        decision.impact = "The command targets a session-approved local workdir. Network, delete, and hard-block patterns still require separate review."
        decision.confidence = max(float(getattr(decision, "confidence", 0) or 0), 0.92)
    return decision


def apply_policy_allowlist(decision: Any, policy_entry: dict[str, Any] | None) -> Any:
    if not policy_entry:
        return decision
    decision.decision = "warn"
    if getattr(decision, "risk_level", "") == "critical":
        decision.risk_level = "high"
    decision.injection_policy = "on_demand"
    decision.memory_action = "reference_only"
    decision.approval_state = "policy_allowlisted"
    if "user_policy_allowlisted" not in decision.deterministic_flags:
        decision.deterministic_flags.append("user_policy_allowlisted")
    reason = str(policy_entry.get("reason") or "User-maintained local risk allowlist matched this command.")
    reviewer = str(policy_entry.get("reviewer") or "local_policy")
    decision.reason = f"Local risk allowlist matched: {reason}"
    decision.impact = f"Allowed by local policy reviewer={reviewer}; still audited as risky."
    decision.confidence = max(float(getattr(decision, "confidence", 0) or 0), 0.95)
    return decision
