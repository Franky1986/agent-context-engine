from __future__ import annotations

import argparse
import json
import os
import sys
from glob import glob
from pathlib import Path
from typing import Any

from ...adapters.runners.claude import claude_session_title, claude_transcript_path, sync_transcript_claude
from ...adapters.runners.codex import codex_thread_name, detect_client_version, sync_transcript_metrics
from ...adapters.runners.session_metadata import refresh_session_row_metadata, resolve_native_session_metadata
from ...application.classifier import deterministic_classifier
from ...infrastructure.config import DB_PATH, MEMORY_DIR, ROOT, detect_project, json_dumps, safe_slug, sh_quote, utc_now
from ...infrastructure.locks import acquire_lock, release_lock
from ...adapters.runners.cursor import normalize_cursor_payload, sync_cursor_payload_metrics
from ..http.request_db import connect
from ...application.firewall import active_firewall_override, firewall_enabled
from .support.payloads import effective_start_cwd, event_name, is_session_start_event, is_stop_event, load_payload, normalized_path, one_line, should_sync_transcript, write_event_jsonl
from .support.queue import (
    append_hook_queue_log,
    hook_queue_sort_key,
    load_hook_queue_item,
    queue_hook_event,
    recover_failed_hook_queue_events,
    reserve_queue_slot,
    update_hook_queue_audit,
    write_hook_queue_failure_artifact,
    write_hook_worker_status,
)
from .support.risk_gate import apply_consumed_command_approval, apply_policy_allowlist, apply_session_workdir_approval, apply_user_prompt_approval, blocking_reason, command_policy_allowlist_match, consume_recent_command_approval, firewall_add_command_for_blocked_tool, pending_approvals_context, pending_approvals_count, pending_approvals_summary_context, pending_firewall_rule_suggestion_context, recent_taint_context, session_approved_workdir_match, should_show_pending_approvals, should_suggest_firewall_add_for_blocked_tool
from .support.session_context import hook_context_output, memory_hooks_status_context, payload_workdir, recent_sessions_context
from ...application.hook_effects import spawn_hook_queue_kick, spawn_initial_prompt_dream, spawn_scheduler_kick, spawn_stop_dream
from ...application.firewall_rules import active_firewall_intent_summaries, active_llm_firewall_contexts, apply_direct_user_firewall_commands, apply_firewall_rule_match, firewall_policy_summary, match_firewall_rules, redact_control_plane_prompt, session_target_workdirs
from ...application.system_control import (
    apply_direct_user_system_command,
    audit_system_control_rejection,
    system_admission_open,
)
from ...application.hooks_state import (
    apply_direct_user_hook_state_commands,
    direct_user_hooks_disable_lines,
    direct_user_hooks_enable_lines,
    direct_user_hooks_status_lines,
    hooks_enabled_for,
    prompt_contains_only_hook_control,
)
from ...application.instance_profile import resolve_runner_wrapper_name
from ...application.integrations import cursor_project_background_runner_status, workspace_binding_status
from ...application.risk import RiskDecision, apply_taint_to_decision, extract_command_from_tool_input, is_non_overridable_block, record_risk_event, scan_tool_input, shell_command_hash, tool_action_class
from ...application.toolrefs import tool_output_event_summary, upsert_tool_call_and_output


def _redacted_blocked_tool_payload(payload: dict[str, Any], *, risk_event_id: str, command_hash: str | None) -> dict[str, Any]:
    redacted = dict(payload)
    redacted["tool_input"] = {
        "agent_memory_redacted": True,
        "reason": "blocked_pretool_input",
        "risk_event_id": risk_event_id,
        "command_hash": command_hash or "",
        "detail": "Full command is stored only in risk_events.preview / monitor risk detail.",
    }
    return redacted


def _redact_blocked_tool_context(
    conn: Any,
    *,
    session_id: str,
    seq: int,
    payload: dict[str, Any],
    risk_event_id: str,
    command_hash: str | None,
) -> tuple[str, str]:
    redacted_payload = _redacted_blocked_tool_payload(payload, risk_event_id=risk_event_id, command_hash=command_hash)
    redacted_tool_input_json = json_dumps(redacted_payload.get("tool_input"))
    redacted_payload_json = json_dumps(redacted_payload)
    conn.execute(
        """
        update events
        set tool_input_json = ?,
            payload_json = ?
        where session_id = ?
          and seq = ?
        """,
        (redacted_tool_input_json, redacted_payload_json, session_id, seq),
    )
    conn.execute(
        """
        update tool_calls
        set input_json = ?
        where session_id = ?
          and seq = ?
        """,
        (redacted_tool_input_json, session_id, seq),
    )
    return redacted_tool_input_json, redacted_payload_json


def _join_hook_context_blocks(*items: str) -> str:
    blocks = [str(item or "").strip() for item in items if str(item or "").strip()]
    return "\n\n ".join(f"{block} " for block in blocks).strip()


def _is_user_control_prompt(prompt: str | None) -> bool:
    text = str(prompt or "").strip().lower()
    return (
        text.startswith("approve ")
        or text == "reset taint"
        or text.startswith("firewall add ")
        or text.startswith("firewall disable ")
        or text.startswith("firewall enable ")
        or text.startswith("hooks-disable")
        or text.startswith("hooks-enable")
        or text.startswith("hooks-status")
    )


def _is_cursor_login_help_prompt(prompt: str | None) -> bool:
    text = str(prompt or "").strip().lower()
    return any(
        marker in text
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


def _prompt_attempt_count(conn: Any, session_id: str, upto_seq: int) -> int:
    row = conn.execute(
        """
        select count(*) as c
        from events
        where session_id = ?
          and seq <= ?
          and event_name in ('UserPromptSubmit', 'userPromptSubmit', 'beforeSubmitPrompt')
        """,
        (session_id, upto_seq),
    ).fetchone()
    return int(row["c"] or 0) if row else 0


def _pretool_event(name: str) -> bool:
    return name in {"PreToolUse", "preToolUse", "beforeShellExecution", "beforeMCPExecution", "beforeReadFile"}


def _user_prompt_event(name: str) -> bool:
    return name in {"UserPromptSubmit", "userPromptSubmit", "beforeSubmitPrompt"}


def _serialize_risk_decision(decision: RiskDecision | None) -> dict[str, Any] | None:
    if decision is None:
        return None
    payload = decision.to_json()
    payload["preview"] = decision.preview
    return payload


def _deserialize_risk_decision(value: Any) -> RiskDecision | None:
    if not isinstance(value, dict):
        return None
    try:
        decision = RiskDecision(
            decision=str(value.get("decision") or "allow"),
            risk_level=str(value.get("risk_level") or "none"),
            sensitivity=str(value.get("sensitivity") or "normal"),
            categories=[str(item) for item in value.get("categories") or [] if str(item)],
            poisoning_flags=[str(item) for item in value.get("poisoning_flags") or [] if str(item)],
            injection_policy=str(value.get("injection_policy") or "on_demand"),
            memory_action=str(value.get("memory_action") or "index"),
            impact=str(value.get("impact") or "No meaningful security impact identified."),
            reason=str(value.get("reason") or "No deterministic risk pattern matched."),
            confidence=float(value.get("confidence") or 0.25),
            deterministic_flags=[str(item) for item in value.get("deterministic_flags") or [] if str(item)],
            preview=str(value.get("preview") or ""),
            approval_state=str(value.get("approval_state") or ""),
            approval_token=str(value.get("approval_token") or ""),
            command_hash=str(value.get("command_hash") or ""),
            risk_event_id=str(value.get("risk_event_id") or ""),
            taint_context=[item for item in value.get("taint_context") or [] if isinstance(item, dict)],
        )
    except Exception:
        return None
    return decision


def _log_mode(args: argparse.Namespace, client: str, payload: dict[str, Any]) -> str:
    requested = str(getattr(args, "mode", "auto") or "auto").strip().lower()
    if requested == "sync":
        requested = "full"
    if requested != "auto":
        return requested
    name = event_name(payload)
    prompt = payload.get("prompt")
    if _user_prompt_event(name) and prompt_contains_only_hook_control(prompt):
        return "full"
    if _user_prompt_event(name):
        return "context"
    if _pretool_event(name):
        conn = connect(init=not DB_PATH.exists())
        try:
            return "fast" if firewall_enabled(conn) else "queue"
        finally:
            conn.close()
    return "queue"


def _hook_workspace_root(payload: dict[str, Any]) -> Path | None:
    cwd = str(payload.get("cwd") or os.environ.get("PWD") or "").strip()
    start_cwd = effective_start_cwd(cwd)
    workdir = payload_workdir(payload, start_cwd or cwd)
    for candidate in (workdir, start_cwd, cwd):
        text = str(candidate or "").strip()
        if not text:
            continue
        try:
            return Path(text).expanduser().resolve()
        except OSError:
            continue
    return None


def _workspace_has_managed_hook_config(client: str, root: Path) -> bool:
    if client == "codex":
        return (root / ".codex" / "hooks.json").exists()
    if client == "claude":
        return (root / ".claude" / "settings.json").exists()
    if client == "cursor":
        return (root / ".cursor" / "rules" / "everyChat.mdc").exists() or (root / ".cursor" / "hooks.json").exists()
    return False


def hooks_runtime_enabled_for(client: str, payload: dict[str, Any], *, root: Path = ROOT) -> bool:
    workspace_root = _hook_workspace_root(payload)
    if not hooks_enabled_for(client, root=root, project_root=workspace_root):
        return False
    if client not in {"codex", "claude", "cursor"}:
        return True
    if workspace_root is None:
        return False
    if workspace_root.resolve() == root.resolve():
        binding = workspace_binding_status(client, root=workspace_root, expected_memory_root=root)
        if _workspace_has_managed_hook_config(client, workspace_root) and str(binding.get("hook_binding_state") or "") != "bound":
            return False
        return True
    payload_cwd = normalized_path(str(payload.get("cwd") or os.environ.get("PWD") or ""))
    root_cwd = normalized_path(str(root))
    launch_cwd = normalized_path(os.environ.get("AGENT_MEMORY_LAUNCH_CWD"))
    if client in {"codex", "claude"} and launch_cwd and payload_cwd == root_cwd:
        return True
    binding = workspace_binding_status(client, root=workspace_root, expected_memory_root=root)
    return str(binding.get("hook_binding_state") or "") == "bound"


def _build_user_prompt_context(
    conn: Any,
    *,
    client: str,
    session_id: str,
    project_id: str,
    thread_name: str | None,
    current_folder: str,
    original_prompt: str | None,
) -> tuple[int, str, str]:
    prompt_attempt_count = _prompt_attempt_count(conn, session_id, 10**9) + 1
    include_cursor_auth_notice = (
        client == "cursor"
        and not _is_user_control_prompt(original_prompt)
        and (prompt_attempt_count <= 2 or _is_cursor_login_help_prompt(original_prompt))
    )
    prompt_context = memory_hooks_status_context(
        conn,
        session_id=session_id,
        current_folder=current_folder,
        client_type=client,
        agent_name=thread_name,
        thread_name=thread_name,
        project_id=project_id,
        include_user_only_controls=True,
        include_cursor_auth_notice=include_cursor_auth_notice,
    )
    firewall_suggestion = pending_firewall_rule_suggestion_context(conn, session_id, original_prompt)
    if firewall_suggestion:
        prompt_context = _join_hook_context_blocks(prompt_context, firewall_suggestion)

    def _contains_pending_summary(context_text: str) -> bool:
        return "Pending blocked approvals:" in context_text

    if should_show_pending_approvals(original_prompt):
        remaining_approvals = pending_approvals_summary_context(conn, session_id)
        if remaining_approvals and not _contains_pending_summary(prompt_context):
            prompt_context = _join_hook_context_blocks(prompt_context, remaining_approvals)
    else:
        remaining = pending_approvals_count(conn, session_id)
        if remaining and not _contains_pending_summary(prompt_context):
            prompt_context = _join_hook_context_blocks(prompt_context, pending_approvals_summary_context(conn, session_id))
    return 0, prompt_context, ""


def _build_session_start_context(
    conn: Any,
    *,
    client: str,
    session_id: str,
    project_id: str,
    thread_name: str | None,
    current_folder: str,
) -> str:
    return recent_sessions_context(
        conn,
        session_id,
        current_folder=current_folder,
        client_type=client,
        agent_name=thread_name,
        thread_name=thread_name,
        project_id=project_id,
        global_limit=5,
        folder_limit=10,
    )


def _risk_event_status(
    decision: RiskDecision,
    *,
    firewall_override: dict[str, Any] | None = None,
) -> str:
    if firewall_override and str(decision.approval_state or "") == "firewall_override":
        return "bypassed_by_firewall_override"
    if decision.decision == "block":
        return "blocked"
    if decision.decision == "quarantine":
        return "quarantined"
    if decision.decision == "warn":
        return "warned"
    return "allowed"


def _evaluate_pretool_fast(
    conn: Any,
    *,
    client: str,
    payload: dict[str, Any],
    session_id: str,
    seq: int,
    project_id: str,
    workdir: str,
    thread_name: str | None,
) -> tuple[RiskDecision | None, int, str]:
    name = event_name(payload)
    classifier_run_id = None
    pretool_decision = scan_tool_input(payload.get("tool_name"), payload.get("tool_input"))
    if pretool_decision is None:
        return None, 0, ""
    firewall_is_enabled = firewall_enabled(conn)
    firewall_override = active_firewall_override(
        conn,
        session_id=session_id,
        client_type=client,
        agent_name=thread_name,
        thread_name=thread_name,
        project_id=project_id,
        workdir=workdir,
    )
    firewall_bypass = bool(firewall_override) or not firewall_is_enabled
    command = extract_command_from_tool_input(payload.get("tool_input"))
    action_class = tool_action_class(
        payload.get("tool_name"),
        payload.get("tool_input"),
        hook_event_name=name,
    )
    command_hash = shell_command_hash(command, workdir=workdir)
    taint_context = recent_taint_context(conn, session_id, before_seq=seq)
    pretool_decision = apply_taint_to_decision(
        pretool_decision,
        action_class=action_class,
        taint_context=taint_context,
        command_hash=command_hash,
    )
    approved_workdir = session_approved_workdir_match(conn, session_id, command, workdir)
    pretool_decision = apply_session_workdir_approval(
        pretool_decision,
        approved_workdir,
        action_class=action_class,
    )
    pretool_decision = apply_policy_allowlist(
        pretool_decision,
        command_policy_allowlist_match(command, command_hash, workdir),
    )
    target_workdirs = session_target_workdirs(conn, session_id=session_id)
    firewall_rule_match = match_firewall_rules(
        conn,
        command=command,
        tool_name=payload.get("tool_name"),
        action_class=action_class,
        session_id=session_id,
        project_id=project_id,
        workdir=workdir,
        target_workdirs=target_workdirs,
    )
    pretool_decision = apply_firewall_rule_match(
        conn,
        pretool_decision,
        firewall_rule_match,
        session_id=session_id,
        event_seq=seq,
    )
    consumed_approval = consume_recent_command_approval(conn, session_id, command_hash)
    if pretool_decision.should_block and pretool_decision.approval_state == "required" and consumed_approval:
        pretool_decision = apply_consumed_command_approval(pretool_decision, consumed_approval)
    has_actionable_tool_input = bool(str(command or "").strip()) or payload.get("tool_name") or payload.get("tool_input") is not None
    classifier_mode = os.environ.get("AGENT_MEMORY_CLASSIFIER_MODE", "llm-on-noncritical")
    if has_actionable_tool_input and classifier_mode in {"llm-on-noncritical", "deterministic"}:
        classified = deterministic_classifier(
            conn,
            stage="pre_action",
            source_kind="tool_input",
            payload={
                "tool_input": payload.get("tool_input"),
                "decision_context": {
                    "action_class": action_class,
                    "command_hash": command_hash,
                    "taint_context": taint_context,
                    "approval_state": pretool_decision.approval_state,
                    "firewall_policy": firewall_policy_summary(firewall_rule_match),
                    "firewall_intents": active_firewall_intent_summaries(conn, session_id=session_id),
                    "firewall_llm_context_rules": active_llm_firewall_contexts(
                        conn,
                        session_id=session_id,
                        project_id=project_id,
                        workdir=workdir,
                        target_workdirs=target_workdirs,
                        event_seq=seq,
                    ),
                },
            },
            deterministic=pretool_decision,
            client_type=client,
            session_id=session_id,
            event_seq=seq,
            tool_call_id=f"toolcall_{safe_slug(session_id)}_{seq}" if payload.get("tool_name") or payload.get("tool_input") is not None else None,
            source_ref=str(payload.get("tool_use_id") or f"{session_id}:{seq}"),
            runner="auto",
        )
        pretool_decision = classified.decision
        classifier_run_id = classified.run_id
    if consumed_approval:
        pretool_decision = apply_consumed_command_approval(pretool_decision, consumed_approval)
    if firewall_bypass and pretool_decision.should_block:
        pretool_decision.decision = "warn"
        pretool_decision.risk_level = "high" if pretool_decision.risk_level == "critical" else pretool_decision.risk_level
        pretool_decision.approval_state = "firewall_override" if firewall_override else "firewall_disabled"
        pretool_decision.memory_action = "reference_only"
        if firewall_override:
            override_id = str(firewall_override.get("override_id") or "")
            scope = str(firewall_override.get("scope_type") or "")
            pretool_decision.reason = (
                f"Firewall enforcement disabled by scoped monitor override {override_id} ({scope}); "
                f"original block downgraded to warning. Original reason: {pretool_decision.reason}"
            )
            pretool_decision.impact = "Tool blocking is temporarily disabled for this matching scoped override; this risky tool use is audited but not blocked."
            for flag in ("firewall_scoped_override", f"firewall_override:{override_id}", f"firewall_scope:{scope}"):
                if flag not in pretool_decision.deterministic_flags:
                    pretool_decision.deterministic_flags.append(flag)
        else:
            pretool_decision.reason = f"Firewall enforcement disabled via monitor; original block downgraded to warning. Original reason: {pretool_decision.reason}"
            pretool_decision.impact = "Tool blocking is temporarily disabled from the monitor; this risky tool use is audited but not blocked."
            if "firewall_enforcement_disabled" not in pretool_decision.deterministic_flags:
                pretool_decision.deterministic_flags.append("firewall_enforcement_disabled")
    if pretool_decision.is_risky and not pretool_decision.risk_event_id:
        risk_event_id = record_risk_event(
            conn,
            pretool_decision,
            client_type=client,
            session_id=session_id,
            event_seq=seq,
            tool_call_id=f"toolcall_{safe_slug(session_id)}_{seq}" if payload.get("tool_name") or payload.get("tool_input") is not None else None,
            tool_name=payload.get("tool_name"),
            source_kind="tool_input",
            source_ref=str(payload.get("tool_use_id") or f"{session_id}:{seq}"),
            workdir=workdir,
            status=_risk_event_status(pretool_decision, firewall_override=firewall_override),
            classifier_run_id=classifier_run_id,
            approval_state=pretool_decision.approval_state,
            approval_token=pretool_decision.approval_token,
            command_hash=pretool_decision.command_hash,
            taint_context=pretool_decision.taint_context,
            evidence=[
                {
                    "source_kind": "tool_input",
                    "source_ref": str(payload.get("tool_use_id") or f"{session_id}:{seq}"),
                    "field": "tool_input",
                    "quote": pretool_decision.preview,
                }
            ],
        )
        conn.execute(
            """
            update firewall_rule_audit
            set risk_event_id = ?
            where session_id = ?
              and event_seq = ?
              and risk_event_id is null
              and action in ('matched', 'rejected')
            """,
            (risk_event_id, session_id, seq),
        )
    if pretool_decision.should_block:
        if should_suggest_firewall_add_for_blocked_tool(
            conn,
            session_id=session_id,
            workdir=workdir,
            command_hash=pretool_decision.command_hash,
            approval_state=pretool_decision.approval_state,
            categories=pretool_decision.categories,
            flags=[
                *[str(flag) for flag in pretool_decision.poisoning_flags or []],
                *[str(flag) for flag in pretool_decision.deterministic_flags or []],
            ],
        ):
            pretool_decision.firewall_add_command = firewall_add_command_for_blocked_tool(
                preview=pretool_decision.preview,
                workdir=workdir,
                risk_event_id=str(pretool_decision.risk_event_id or ""),
                categories=pretool_decision.categories,
            )
    exit_code = 2 if pretool_decision.should_block else 0
    block_reason = blocking_reason(pretool_decision) if exit_code == 2 else ""
    return pretool_decision, exit_code, block_reason


def _queue_hook_capture(
    client: str,
    payload: dict[str, Any],
    *,
    detect_version: bool,
    hook_mode: str,
    return_context: bool,
) -> int | tuple[int, str, str]:
    if client == "cursor":
        payload = normalize_cursor_payload(payload)
    recorded_at = utc_now()
    name = event_name(payload)
    original_prompt = payload.get("prompt")
    session_id = str(payload.get("session_id") or f"missing-session-{recorded_at}")
    cwd = str(payload.get("cwd") or os.environ.get("PWD") or "")
    start_cwd = effective_start_cwd(cwd)
    workdir = payload_workdir(payload, start_cwd or cwd)
    project_id = detect_project(workdir or start_cwd or cwd)
    transcript_path = payload.get("transcript_path")
    if not transcript_path and client == "claude":
        t = claude_transcript_path(session_id, cwd)
        transcript_path = str(t) if t else None
    client_version = detect_client_version(client) if detect_version else None
    native_metadata = resolve_native_session_metadata(
        client,
        session_id,
        cwd=cwd,
        workdir=workdir or start_cwd or cwd,
        payload=payload,
    )
    if native_metadata.transcript_path:
        transcript_path = native_metadata.transcript_path
        payload["transcript_path"] = transcript_path
    if native_metadata.latest_user_prompt and not payload.get("prompt"):
        payload["prompt"] = native_metadata.latest_user_prompt
        original_prompt = payload.get("prompt")
    if native_metadata.latest_assistant_message and not payload.get("last_assistant_message"):
        payload["last_assistant_message"] = native_metadata.latest_assistant_message
    if client == "codex":
        thread_name = codex_thread_name(session_id)
        native_resume = f"{resolve_runner_wrapper_name('codex', root=ROOT)} resume {session_id}"
    elif client == "claude":
        thread_name = claude_session_title(session_id, cwd)
        native_resume = f"{resolve_runner_wrapper_name('claude', root=ROOT)} --resume {session_id}"
    else:
        thread_name = native_metadata.thread_name
        native_resume = native_metadata.native_resume_command
    if native_metadata.thread_name:
        thread_name = native_metadata.thread_name
    if native_metadata.native_resume_command:
        native_resume = native_metadata.native_resume_command
    session_brief = native_metadata.session_brief
    preferred_dream_runner = client
    if client == "cursor":
        workspace_root = _hook_workspace_root(payload) or Path(workdir or start_cwd or cwd)
        preferred_dream_runner = (
            cursor_project_background_runner_status(workspace_root, expected_memory_root=ROOT)["headless_runner"] or client
        )
    reservation = reserve_queue_slot(
        client=client,
        payload=payload,
        event_name=name,
        hook_mode=hook_mode,
        recorded_at=recorded_at,
        cwd=cwd,
        workdir=workdir or start_cwd or cwd,
        project_id=project_id,
        transcript_path=str(transcript_path) if transcript_path else None,
        client_version=client_version,
        thread_name=thread_name,
        session_brief=session_brief,
        preferred_dream_runner=preferred_dream_runner,
        native_resume_command=native_resume,
        session_id=session_id,
    )
    exit_code = 0
    context = ""
    block_reason = ""
    sync_decision = ""
    sync_decision_data: dict[str, Any] | None = None
    conn = connect(init=not DB_PATH.exists())
    try:
        if hook_mode == "context":
            exit_code, context, block_reason = _build_user_prompt_context(
                conn,
                client=client,
                session_id=session_id,
                project_id=project_id,
                thread_name=thread_name,
                current_folder=workdir or start_cwd or cwd,
                original_prompt=original_prompt,
            )
            if exit_code == 0:
                approval_context = apply_user_prompt_approval(
                    conn,
                    session_id,
                    original_prompt,
                    event_seq=int(reservation["reserved_seq"]),
                )
                if approval_context:
                    payload["agent_memory_user_prompt_approval_applied"] = True
                    conn.commit()
                    _exit_code, refreshed_context, _block_reason = _build_user_prompt_context(
                        conn,
                        client=client,
                        session_id=session_id,
                        project_id=project_id,
                        thread_name=thread_name,
                        current_folder=workdir or start_cwd or cwd,
                        original_prompt=original_prompt,
                    )
                    context = _join_hook_context_blocks(refreshed_context, approval_context)
            if exit_code == 2:
                sync_decision = "block"
        elif hook_mode == "fast":
            try:
                conn.execute("begin immediate")
                decision, exit_code, block_reason = _evaluate_pretool_fast(
                    conn,
                    client=client,
                    payload=payload,
                    session_id=session_id,
                    seq=int(reservation["reserved_seq"]),
                    project_id=project_id,
                    workdir=workdir or start_cwd or cwd,
                    thread_name=thread_name,
                )
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                exit_code = 2
                block_reason = "Agent Context Engine blocked this tool use because the fast-path firewall check failed unexpectedly."
                decision = RiskDecision(
                    decision="block",
                    risk_level="critical",
                    sensitivity="normal",
                    categories=["fast_path_failure"],
                    poisoning_flags=["fast_path_failure"],
                    injection_policy="never_auto",
                    memory_action="reference_only",
                    impact="The synchronous firewall decision path failed before the command could be safely evaluated.",
                    reason="Agent Context Engine fast-path firewall check failed unexpectedly.",
                    confidence=1.0,
                    deterministic_flags=["fast_path_failure"],
                    preview=extract_command_from_tool_input(payload.get("tool_input")),
                )
            sync_decision = "block" if exit_code == 2 else "allow"
            sync_decision_data = _serialize_risk_decision(decision)
    finally:
        conn.close()
    if return_context and is_session_start_event(name):
        conn = connect(init=not DB_PATH.exists())
        try:
            context = _build_session_start_context(
                conn,
                client=client,
                session_id=session_id,
                project_id=project_id,
                thread_name=thread_name,
                current_folder=workdir or start_cwd or cwd,
            )
        finally:
            conn.close()
    try:
        queue_hook_event(
            client,
            payload,
            "queued",
            event_id=reservation["event_id"],
            reserved_seq=reservation["reserved_seq"],
            recorded_at=reservation["recorded_at"],
            queued_at=reservation["queued_at"],
            event_name=name,
            hook_mode=hook_mode,
            synchronous_decision=sync_decision,
            synchronous_decision_data=sync_decision_data,
        )
        if sync_decision:
            update_hook_queue_audit(
                reservation["event_id"],
                status="queued",
                synchronous_decision=sync_decision,
            )
        spawn_hook_queue_kick(name)
    except Exception as exc:
        failure_path = write_hook_queue_failure_artifact(
            client,
            payload,
            error="queue-write-failed",
            event_id=reservation["event_id"],
            reserved_seq=reservation["reserved_seq"],
            recorded_at=reservation["recorded_at"],
            queued_at=reservation["queued_at"],
            event_name=name,
            hook_mode=hook_mode,
            synchronous_decision=sync_decision,
        )
        update_hook_queue_audit(
            reservation["event_id"],
            status="failed",
            error="queue-write-failed",
            synchronous_decision=sync_decision or None,
        )
        append_hook_queue_log(
            "queue write failed after reservation",
            client=client,
            event_id=reservation["event_id"],
            session_id=session_id,
            reserved_seq=reservation["reserved_seq"],
            event_name=name,
            hook_mode=hook_mode,
            error=str(exc),
            failure_artifact_path=str(failure_path) if failure_path else "",
        )
    return (exit_code, context, block_reason) if return_context else exit_code



def log_hook(args: argparse.Namespace) -> int:
    payload = load_payload()
    if args.client == "cursor":
        payload = normalize_cursor_payload(payload)
    name = event_name(payload)
    prompt = payload.get("prompt")
    hook_control_requested = bool(
        _user_prompt_event(name)
        and (
            direct_user_hooks_status_lines(prompt)
            or direct_user_hooks_disable_lines(prompt)
            or direct_user_hooks_enable_lines(prompt)
        )
    )
    project_root = _hook_workspace_root(payload)
    if _user_prompt_event(name):
        try:
            system_context = apply_direct_user_system_command(
                payload.get("prompt"),
                event_name=name,
                installation_root=ROOT,
                session_id=str(payload.get("session_id") or ""),
                event_seq=payload.get("event_seq") if isinstance(payload.get("event_seq"), int) else None,
            )
        except (PermissionError, TimeoutError, ValueError) as exc:
            if str(payload.get("prompt") or "").strip().startswith("system-"):
                audit_system_control_rejection(
                    installation_root=ROOT,
                    raw_message=payload.get("prompt"),
                    event_name=name,
                    reason=str(exc),
                )
                hook_context_output(name, f"System control rejected: {exc}")
                return 0
            system_context = None
        if system_context:
            hook_context_output(name, system_context)
            return 0
    if not system_admission_open(installation_root=ROOT):
        if _user_prompt_event(name) and direct_user_hooks_status_lines(prompt):
            hook_context_output(
                name,
                "\n".join(
                    apply_direct_user_hook_state_commands(
                        prompt,
                        root=ROOT,
                        project_root=project_root,
                    )
                ),
            )
        elif _user_prompt_event(name) and (direct_user_hooks_disable_lines(prompt) or direct_user_hooks_enable_lines(prompt)):
            hook_context_output(
                name,
                "Hooks mutation rejected: Agent Context Engine is suspended and the preserved hook state cannot be changed.",
            )
        return 0
    if not hooks_runtime_enabled_for(args.client, payload):
        if hook_control_requested:
            try:
                control_context = "\n".join(
                    apply_direct_user_hook_state_commands(
                        prompt,
                        root=ROOT,
                        project_root=project_root,
                    )
                )
            except ValueError as exc:
                control_context = f"Hooks control rejected: {exc}"
            hook_context_output(name, control_context)
        return 0
    mode = _log_mode(args, args.client, payload)
    if mode in {"queue", "context", "fast"}:
        code, context, block_reason = _queue_hook_capture(
            args.client,
            payload,
            detect_version=args.detect_version,
            hook_mode=mode,
            return_context=True,
        )
    else:
        code, context, block_reason = log_payload(args.client, payload, detect_version=args.detect_version, queue_on_failure=True, return_context=True)
    if hook_control_requested:
        try:
            control_context = "\n".join(
                apply_direct_user_hook_state_commands(
                    prompt,
                    root=ROOT,
                    project_root=project_root,
                )
            )
        except ValueError as exc:
            control_context = f"Hooks control rejected: {exc}"
        context = _join_hook_context_blocks(context, control_context)
    # Codex currently accepts injected context for SessionStart/UserPromptSubmit,
    # but Stop has a stricter schema and reports "invalid stop hook JSON output"
    # when hookSpecificOutput is printed. Pending approvals are therefore shown
    # on the next UserPromptSubmit instead of during Stop.
    if context and not is_stop_event(event_name(payload)):
        hook_context_output(event_name(payload), context)
    if code == 2:
        print(block_reason or "Agent Context Engine blocked this tool use by policy.", file=sys.stderr)
    return code


def log_payload(
    client: str,
    payload: dict[str, Any],
    *,
    detect_version: bool = False,
    queue_on_failure: bool = True,
    return_context: bool = False,
    reserved_seq: int | None = None,
    event_id: str | None = None,
    recorded_at: str | None = None,
    queued_at: str | None = None,
    hook_mode: str = "sync",
    pretool_sync_decision: dict[str, Any] | None = None,
    audit_synchronous_decision: str | None = None,
) -> int | tuple[int, str, str]:
    if client == "cursor":
        payload = normalize_cursor_payload(payload)
    now = recorded_at or utc_now()
    name = event_name(payload)
    original_prompt = payload.get("prompt")
    if not system_admission_open(installation_root=ROOT):
        return (0, "", "") if return_context else 0
    if not hooks_runtime_enabled_for(client, payload):
        return (0, "", "") if return_context else 0
    session_id = str(payload.get("session_id") or f"missing-session-{now}")
    cwd = str(payload.get("cwd") or os.environ.get("PWD") or "")
    start_cwd = effective_start_cwd(cwd)
    workdir = payload_workdir(payload, start_cwd or cwd)
    project_id = detect_project(workdir or start_cwd or cwd)
    transcript_path = payload.get("transcript_path")
    # Claude Code does not include transcript_path in the hook payload; derive it.
    if not transcript_path and client == "claude":
        t = claude_transcript_path(session_id, cwd)
        transcript_path = str(t) if t else None
    client_version = detect_client_version(client) if detect_version else None
    native_metadata = resolve_native_session_metadata(
        client,
        session_id,
        cwd=cwd,
        workdir=workdir or start_cwd or cwd,
        payload=payload,
    )
    if native_metadata.transcript_path:
        transcript_path = native_metadata.transcript_path
        payload["transcript_path"] = transcript_path
    if native_metadata.latest_user_prompt and not payload.get("prompt"):
        payload["prompt"] = native_metadata.latest_user_prompt
    if native_metadata.latest_assistant_message and not payload.get("last_assistant_message"):
        payload["last_assistant_message"] = native_metadata.latest_assistant_message
    if client == "codex":
        thread_name = codex_thread_name(session_id)
        native_resume = f"{resolve_runner_wrapper_name('codex', root=ROOT)} resume {session_id}"
    elif client == "claude":
        thread_name = claude_session_title(session_id, cwd)
        native_resume = f"{resolve_runner_wrapper_name('claude', root=ROOT)} --resume {session_id}"
    else:
        thread_name = native_metadata.thread_name
        native_resume = native_metadata.native_resume_command
    if native_metadata.thread_name:
        thread_name = native_metadata.thread_name
    if native_metadata.native_resume_command:
        native_resume = native_metadata.native_resume_command
    session_brief = native_metadata.session_brief
    preferred_dream_runner = client
    if client == "cursor":
        workspace_root = _hook_workspace_root(payload) or Path(workdir or start_cwd or cwd)
        preferred_dream_runner = (
            cursor_project_background_runner_status(workspace_root, expected_memory_root=ROOT)["headless_runner"] or client
        )
    pretool_decision = None
    classifier_recorded_risk = False
    risk_event_id = ""
    if _pretool_event(name) and pretool_sync_decision:
        pretool_decision = _deserialize_risk_decision(pretool_sync_decision)
    elif _pretool_event(name):
        pretool_decision = scan_tool_input(payload.get("tool_name"), payload.get("tool_input"))

    conn = connect(init=not DB_PATH.exists())
    startup_context = ""
    prompt_context = ""
    initial_prompt_dream = False
    exit_code = 2 if pretool_decision and pretool_decision.should_block else 0
    block_reason = blocking_reason(pretool_decision) if exit_code == 2 else ""
    payload_for_jsonl = payload
    try:
        conn.execute("begin immediate")
        firewall_is_enabled = firewall_enabled(conn)
        firewall_override = active_firewall_override(
            conn,
            session_id=session_id,
            client_type=client,
            agent_name=thread_name,
            thread_name=thread_name,
            project_id=project_id,
            workdir=workdir or start_cwd or cwd,
        )
        firewall_bypass = bool(firewall_override) or not firewall_is_enabled
        if pretool_decision and firewall_bypass:
            exit_code = 0
            block_reason = ""
        if event_id:
            existing = conn.execute(
                "select seq from events where session_id = ? and source_id = ?",
                (session_id, event_id),
            ).fetchone()
            if existing is not None:
                conn.commit()
                return (0, "", "") if return_context else 0
        row = conn.execute(
            "select last_event_seq, last_dream_event_seq, last_reserved_event_seq, started_at from sessions where session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            seq = int(reserved_seq or 1)
            status = "stopped" if is_stop_event(name) else "open"
            ended_at = now if is_stop_event(name) else None
            conn.execute(
                """
                insert into sessions (
                  session_id, client_type, client_version, project_id, cwd, last_workdir,
                  thread_name, session_brief, transcript_path, started_at, last_event_at, status,
                  summary_status, dream_status, last_event_seq, last_reserved_event_seq,
                  ended_at, preferred_dream_runner, native_resume_command
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    client,
                    client_version,
                    project_id,
                    cwd,
                    workdir or start_cwd or cwd,
                    thread_name,
                    session_brief,
                    transcript_path,
                    now,
                    now,
                    status,
                    "summary_pending",
                    "dream_pending",
                    seq,
                    seq,
                    ended_at,
                    preferred_dream_runner,
                    native_resume,
                ),
            )
        else:
            seq = int(reserved_seq or (max(int(row["last_event_seq"] or 0), int(row["last_reserved_event_seq"] or 0)) + 1))
            status = "stopped" if is_stop_event(name) else "open"
            ended_at = now if is_stop_event(name) else None
            resume_clause = ", resume_count = resume_count + 1, last_resume_at = ?" if name in {"SessionStart", "sessionStart"} and row["started_at"] else ""
            params = [
                client_version,
                thread_name,
                session_brief,
                project_id,
                cwd,
                workdir or start_cwd or cwd,
                transcript_path,
                native_resume,
                now,
                status,
                ended_at,
                status,
                "summary_pending",
                "dream_pending",
                seq,
                seq,
            ]
            if resume_clause:
                params.append(now)
            params.append(session_id)
            conn.execute(
                f"""
                update sessions
                set client_version = coalesce(?, client_version),
                    thread_name = coalesce(?, thread_name),
                    session_brief = coalesce(session_brief, ?),
                    project_id = ?,
                    cwd = ?,
                    last_workdir = ?,
                    transcript_path = coalesce(?, transcript_path),
                    native_resume_command = coalesce(?, native_resume_command),
                    last_event_at = ?,
                    ended_at = case when ? = 'stopped' then ? else ended_at end,
                    status = ?,
                    summary_status = ?,
                    dream_status = ?,
                    last_event_seq = max(last_event_seq, ?),
                    last_reserved_event_seq = max(last_reserved_event_seq, ?)
                    {resume_clause}
                where session_id = ?
                """,
                tuple(params),
            )

        stored_prompt = redact_control_plane_prompt(original_prompt) if name in {"UserPromptSubmit", "userPromptSubmit"} else original_prompt
        if prompt_contains_only_hook_control(original_prompt):
            stored_prompt = "[agent-memory control-plane hooks command redacted; see hooks state]"
        payload_for_storage = dict(payload)
        if stored_prompt != original_prompt:
            payload_for_storage["prompt"] = stored_prompt
        tool_input_json = json_dumps(payload.get("tool_input")) if "tool_input" in payload else None
        tool_response_text = payload.get("tool_response")
        stored_tool_response_text = tool_output_event_summary(tool_response_text)
        if tool_response_text is not None:
            payload_for_storage["tool_response"] = stored_tool_response_text
            payload_for_storage["tool_response_raw_output_omitted"] = True
        payload_for_jsonl = payload_for_storage
        conn.execute(
            """
            insert into events (
              session_id, seq, event_name, recorded_at, client_type, cwd,
              project_id, turn_id, tool_name, tool_use_id, prompt,
              tool_input_json, tool_response_text, last_assistant_message,
              transcript_path, source_id, payload_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                seq,
                name,
                now,
                client,
                cwd,
                project_id,
                payload.get("turn_id"),
                payload.get("tool_name"),
                payload.get("tool_use_id"),
                stored_prompt,
                tool_input_json,
                stored_tool_response_text,
                payload.get("last_assistant_message"),
                transcript_path,
                event_id,
                json_dumps(payload_for_storage),
            ),
        )
        if is_stop_event(name):
            prior_prompt = conn.execute(
                """
                select 1
                from events
                where session_id = ?
                  and seq < ?
                  and event_name in ('UserPromptSubmit', 'userPromptSubmit', 'beforeSubmitPrompt')
                limit 1
                """,
                (session_id, seq),
            ).fetchone()
            initial_prompt_dream = prior_prompt is not None and (row is None or int(row["last_dream_event_seq"] or 0) == 0)
        if payload.get("tool_name") or tool_input_json is not None or tool_response_text is not None:
            tool_output_id = upsert_tool_call_and_output(
                conn,
                session_id=session_id,
                seq=seq,
                recorded_at=now,
                client_type=client,
                project_id=project_id,
                cwd=cwd,
                tool_name=payload.get("tool_name"),
                tool_use_id=payload.get("tool_use_id"),
                input_json=tool_input_json,
                response_text=tool_response_text,
            )
        else:
            tool_output_id = None
        if name in {"UserPromptSubmit", "userPromptSubmit", "beforeSubmitPrompt"}:
            if client == "cursor":
                prompt_attempt_count = _prompt_attempt_count(conn, session_id, seq)
                include_cursor_auth_notice = (
                    not _is_user_control_prompt(original_prompt)
                    and (
                        prompt_attempt_count <= 2
                        or _is_cursor_login_help_prompt(original_prompt)
                    )
                )
            else:
                include_cursor_auth_notice = False
            prompt_context = memory_hooks_status_context(
                conn,
                session_id=session_id,
                current_folder=workdir or start_cwd or cwd,
                client_type=client,
                agent_name=thread_name,
                thread_name=thread_name,
                project_id=project_id,
                include_user_only_controls=True,
                include_cursor_auth_notice=include_cursor_auth_notice,
            )
            control_plane_messages = apply_direct_user_firewall_commands(
                conn,
                original_prompt,
                session_id=session_id,
                event_seq=seq,
            )
            if not payload.get("agent_memory_user_prompt_approval_applied"):
                approval_context = apply_user_prompt_approval(conn, session_id, original_prompt, event_seq=seq)
                if approval_context:
                    prompt_context = _join_hook_context_blocks(prompt_context, approval_context)
            if control_plane_messages:
                prompt_context = _join_hook_context_blocks(prompt_context, "\n".join(control_plane_messages))
            firewall_suggestion = pending_firewall_rule_suggestion_context(conn, session_id, original_prompt)
            if firewall_suggestion:
                prompt_context = _join_hook_context_blocks(prompt_context, firewall_suggestion)
            if should_show_pending_approvals(original_prompt):
                remaining_approvals = pending_approvals_summary_context(conn, session_id)
                if remaining_approvals:
                    prompt_context = _join_hook_context_blocks(prompt_context, remaining_approvals)
            elif prompt_context:
                remaining = pending_approvals_count(conn, session_id)
                if remaining:
                    prompt_context = _join_hook_context_blocks(
                        prompt_context,
                        pending_approvals_summary_context(conn, session_id),
                    )
        classifier_run_id = None
        if pretool_decision:
            command = extract_command_from_tool_input(payload.get("tool_input"))
            action_class = tool_action_class(
                payload.get("tool_name"),
                payload.get("tool_input"),
                hook_event_name=name,
            )
            command_hash = shell_command_hash(command, workdir=workdir or start_cwd or cwd)
            approved_workdir = session_approved_workdir_match(conn, session_id, command, workdir or start_cwd or cwd)
            target_workdirs = session_target_workdirs(conn, session_id=session_id)
            taint_context = pretool_decision.taint_context
            firewall_rule_match = None
            consumed_approval = None
            if not pretool_sync_decision:
                taint_context = recent_taint_context(conn, session_id, before_seq=seq)
                pretool_decision = apply_taint_to_decision(
                    pretool_decision,
                    action_class=action_class,
                    taint_context=taint_context,
                    command_hash=command_hash,
                )
                pretool_decision = apply_session_workdir_approval(
                    pretool_decision,
                    approved_workdir,
                    action_class=action_class,
                )
                pretool_decision = apply_policy_allowlist(
                    pretool_decision,
                    command_policy_allowlist_match(command, command_hash, workdir or start_cwd or cwd),
                )
                firewall_rule_match = match_firewall_rules(
                    conn,
                    command=command,
                    tool_name=payload.get("tool_name"),
                    action_class=action_class,
                    session_id=session_id,
                    project_id=project_id,
                    workdir=workdir or start_cwd or cwd,
                    target_workdirs=target_workdirs,
                )
                pretool_decision = apply_firewall_rule_match(
                    conn,
                    pretool_decision,
                    firewall_rule_match,
                    session_id=session_id,
                    event_seq=seq,
                )
                consumed_approval = consume_recent_command_approval(conn, session_id, command_hash)
                if pretool_decision.should_block and pretool_decision.approval_state == "required" and consumed_approval:
                    pretool_decision = apply_consumed_command_approval(pretool_decision, consumed_approval)
            classifier_payload = {
                "tool_input": payload.get("tool_input"),
                "decision_context": {
                    "action_class": action_class,
                    "command_hash": command_hash,
                    "taint_context": taint_context,
                    "approval_state": pretool_decision.approval_state,
                    "firewall_policy": firewall_policy_summary(firewall_rule_match),
                    "firewall_intents": active_firewall_intent_summaries(conn, session_id=session_id),
                    "firewall_llm_context_rules": active_llm_firewall_contexts(
                        conn,
                        session_id=session_id,
                        project_id=project_id,
                        workdir=workdir or start_cwd or cwd,
                        target_workdirs=target_workdirs,
                        event_seq=seq,
                    ),
                },
            }
            has_actionable_tool_input = bool(str(command or "").strip()) or payload.get("tool_name") or tool_input_json is not None
            if has_actionable_tool_input and not pretool_sync_decision:
                classified = deterministic_classifier(
                    conn,
                    stage="pre_action",
                    source_kind="tool_input",
                    payload=classifier_payload,
                    deterministic=pretool_decision,
                    client_type=client,
                    session_id=session_id,
                    event_seq=seq,
                    tool_call_id=f"toolcall_{safe_slug(session_id)}_{seq}" if payload.get("tool_name") or tool_input_json is not None else None,
                    source_ref=str(payload.get("tool_use_id") or f"{session_id}:{seq}"),
                    runner="auto",
                )
                classifier_run_id = classified.run_id
                pretool_decision = classified.decision
                classifier_recorded_risk = classified.status != "succeeded"
            if not pretool_sync_decision:
                pretool_decision = apply_session_workdir_approval(
                    pretool_decision,
                    approved_workdir,
                    action_class=action_class,
                )
                pretool_decision = apply_firewall_rule_match(
                    conn,
                    pretool_decision,
                    firewall_rule_match,
                    session_id=session_id,
                    event_seq=seq,
                )
                if consumed_approval:
                    pretool_decision = apply_consumed_command_approval(pretool_decision, consumed_approval)
            if firewall_bypass and pretool_decision.should_block:
                pretool_decision.decision = "warn"
                pretool_decision.risk_level = "high" if pretool_decision.risk_level == "critical" else pretool_decision.risk_level
                pretool_decision.approval_state = "firewall_override" if firewall_override else "firewall_disabled"
                pretool_decision.memory_action = "reference_only"
                if firewall_override:
                    override_id = str(firewall_override.get("override_id") or "")
                    scope = str(firewall_override.get("scope_type") or "")
                    pretool_decision.reason = (
                        f"Firewall enforcement disabled by scoped monitor override {override_id} ({scope}); "
                        f"original block downgraded to warning. Original reason: {pretool_decision.reason}"
                    )
                    pretool_decision.impact = "Tool blocking is temporarily disabled for this matching scoped override; this risky tool use is audited but not blocked."
                    for flag in ("firewall_scoped_override", f"firewall_override:{override_id}", f"firewall_scope:{scope}"):
                        if flag not in pretool_decision.deterministic_flags:
                            pretool_decision.deterministic_flags.append(flag)
                else:
                    pretool_decision.reason = f"Firewall enforcement disabled via monitor; original block downgraded to warning. Original reason: {pretool_decision.reason}"
                    pretool_decision.impact = "Tool blocking is temporarily disabled from the monitor; this risky tool use is audited but not blocked."
                    if "firewall_enforcement_disabled" not in pretool_decision.deterministic_flags:
                        pretool_decision.deterministic_flags.append("firewall_enforcement_disabled")
            exit_code = 2 if pretool_decision.should_block else 0
            block_reason = blocking_reason(pretool_decision) if exit_code == 2 else ""
        if pretool_decision and pretool_decision.is_risky and not classifier_recorded_risk:
            risk_event_id = str(pretool_decision.risk_event_id or "")
            existing_risk = None
            if risk_event_id:
                existing_risk = conn.execute("select risk_event_id from risk_events where risk_event_id = ?", (risk_event_id,)).fetchone()
            if not existing_risk:
                risk_event_id = record_risk_event(
                    conn,
                    pretool_decision,
                    client_type=client,
                    session_id=session_id,
                    event_seq=seq,
                    tool_call_id=f"toolcall_{safe_slug(session_id)}_{seq}" if payload.get("tool_name") or tool_input_json is not None else None,
                    tool_name=payload.get("tool_name"),
                    source_kind="tool_input",
                    source_ref=str(payload.get("tool_use_id") or tool_output_id or f"{session_id}:{seq}"),
                    workdir=workdir or start_cwd or cwd,
                    status=_risk_event_status(pretool_decision, firewall_override=firewall_override),
                    classifier_run_id=classifier_run_id,
                    approval_state=pretool_decision.approval_state,
                    approval_token=pretool_decision.approval_token,
                    command_hash=pretool_decision.command_hash,
                    taint_context=pretool_decision.taint_context,
                    evidence=[
                        {
                            "source_kind": "tool_input",
                            "source_ref": str(payload.get("tool_use_id") or f"{session_id}:{seq}"),
                            "field": "tool_input",
                            "quote": pretool_decision.preview,
                        }
                    ],
                )
                conn.execute(
                    """
                    update firewall_rule_audit
                    set risk_event_id = ?
                    where session_id = ?
                      and event_seq = ?
                      and risk_event_id is null
                      and action in ('matched', 'rejected')
                    """,
                    (risk_event_id, session_id, seq),
                )
            else:
                conn.execute(
                    """
                    update risk_events
                    set updated_at = ?,
                        tool_name = ?,
                        source_ref = ?,
                        workdir = ?,
                        status = ?,
                        decision = ?,
                        policy = ?,
                        risk_level = ?,
                        sensitivity = ?,
                        categories_json = ?,
                        poisoning_flags_json = ?,
                        injection_policy = ?,
                        memory_action = ?,
                        impact = ?,
                        reason = ?,
                        confidence = ?,
                        deterministic_flags_json = ?,
                        classifier_run_id = coalesce(?, classifier_run_id),
                        preview = ?,
                        evidence_json = ?,
                        approval_state = ?,
                        approval_token = ?,
                        command_hash = ?,
                        taint_context_json = ?
                    where risk_event_id = ?
                    """,
                    (
                        utc_now(),
                        payload.get("tool_name"),
                        str(payload.get("tool_use_id") or tool_output_id or f"{session_id}:{seq}"),
                        workdir or start_cwd or cwd,
                        _risk_event_status(pretool_decision, firewall_override=firewall_override),
                        pretool_decision.decision,
                        pretool_decision.decision,
                        pretool_decision.risk_level,
                        pretool_decision.sensitivity,
                        json_dumps(pretool_decision.categories),
                        json_dumps(pretool_decision.poisoning_flags),
                        pretool_decision.injection_policy,
                        pretool_decision.memory_action,
                        pretool_decision.impact,
                        pretool_decision.reason,
                        pretool_decision.confidence,
                        json_dumps(pretool_decision.deterministic_flags),
                        classifier_run_id,
                        pretool_decision.preview,
                        json_dumps(
                            [
                                {
                                    "source_kind": "tool_input",
                                    "source_ref": str(payload.get("tool_use_id") or f"{session_id}:{seq}"),
                                    "field": "tool_input",
                                    "quote": pretool_decision.preview,
                                }
                            ]
                        ),
                        pretool_decision.approval_state,
                        pretool_decision.approval_token,
                        pretool_decision.command_hash,
                        json_dumps(pretool_decision.taint_context),
                        risk_event_id,
                    ),
                )
            if pretool_decision.should_block:
                if should_suggest_firewall_add_for_blocked_tool(
                    conn,
                    session_id=session_id,
                    workdir=workdir or start_cwd or cwd,
                    command_hash=pretool_decision.command_hash,
                    approval_state=pretool_decision.approval_state,
                    categories=pretool_decision.categories,
                    flags=[
                        *[str(flag) for flag in pretool_decision.poisoning_flags or []],
                        *[str(flag) for flag in pretool_decision.deterministic_flags or []],
                    ],
                ):
                    pretool_decision.firewall_add_command = firewall_add_command_for_blocked_tool(
                        preview=pretool_decision.preview,
                        workdir=workdir or start_cwd or cwd,
                        risk_event_id=risk_event_id,
                        categories=pretool_decision.categories,
                    )
                redacted_tool_input_json, _redacted_payload_json = _redact_blocked_tool_context(
                    conn,
                    session_id=session_id,
                    seq=seq,
                    payload=payload,
                    risk_event_id=risk_event_id,
                    command_hash=pretool_decision.command_hash,
                )
                payload_for_jsonl = _redacted_blocked_tool_payload(
                    payload,
                    risk_event_id=risk_event_id,
                    command_hash=pretool_decision.command_hash,
                )
                tool_input_json = redacted_tool_input_json
                block_reason = blocking_reason(pretool_decision)
        conn.commit()
        if is_stop_event(name):
            prompt_context = "\n\n".join(item for item in [prompt_context, pending_approvals_context(conn, session_id)] if item)
        if is_session_start_event(name):
            startup_context = recent_sessions_context(
                conn,
                session_id,
                current_folder=workdir or start_cwd,
                client_type=client,
                agent_name=thread_name,
                thread_name=thread_name,
                project_id=project_id,
                global_limit=5,
                folder_limit=10,
            )
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        if queue_on_failure:
            try:
                queued_path = queue_hook_event(
                    client,
                    payload,
                    "sqlite-write-failed",
                    event_id=event_id,
                    reserved_seq=reserved_seq,
                    recorded_at=now,
                    queued_at=queued_at,
                    event_name=name,
                    hook_mode=hook_mode,
                    synchronous_decision="block" if exit_code == 2 else "",
                )
                if event_id:
                    update_hook_queue_audit(
                        event_id,
                        status="failed",
                        error="sqlite-write-failed",
                        synchronous_decision="block" if exit_code == 2 else None,
                    )
                append_hook_queue_log(
                    "sqlite write failed; event re-queued",
                    client=client,
                    event_id=event_id or "",
                    session_id=session_id,
                    reserved_seq=reserved_seq,
                    event_name=name,
                    hook_mode=hook_mode,
                    queued_path=str(queued_path),
                )
            except Exception as queue_exc:
                failure_path = write_hook_queue_failure_artifact(
                    client,
                    payload,
                    error="sqlite-and-queue-write-failed",
                    event_id=event_id,
                    reserved_seq=reserved_seq,
                    recorded_at=now,
                    queued_at=queued_at,
                    event_name=name,
                    hook_mode=hook_mode,
                    synchronous_decision="block" if exit_code == 2 else "",
                )
                if event_id:
                    update_hook_queue_audit(
                        event_id,
                        status="failed",
                        error="sqlite-and-queue-write-failed",
                        synchronous_decision="block" if exit_code == 2 else None,
                    )
                append_hook_queue_log(
                    "sqlite write failed and queue fallback also failed",
                    client=client,
                    event_id=event_id or "",
                    session_id=session_id,
                    reserved_seq=reserved_seq,
                    event_name=name,
                    hook_mode=hook_mode,
                    error=str(queue_exc),
                    failure_artifact_path=str(failure_path) if failure_path else "",
                )
            spawn_hook_queue_kick("sqlite-write-failed")
            # Keep local policy enforcement fail-closed even when persistence is
            # temporarily unavailable. Non-risk events still degrade to queued logs.
            return (exit_code, "", block_reason) if return_context else exit_code
        raise

    write_event_jsonl(
        client,
        session_id,
        {"recorded_at": now, "client_type": client, "session_id": session_id, "seq": seq, "event_name": name, "project_id": project_id, "payload": payload_for_jsonl},
    )
    if transcript_path and should_sync_transcript(client, name):
        try:
            if client == "claude":
                sync_transcript_claude(conn, session_id, str(transcript_path))
            elif client == "codex":
                sync_transcript_metrics(conn, session_id, str(transcript_path))
        except Exception:
            # Transcript sync is recoverable through scheduler-run/sync-transcripts.
            pass
    try:
        session_row = conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
        if session_row is not None:
            refresh_session_row_metadata(conn, session_row)
            conn.commit()
    except Exception:
        pass
    if client == "cursor":
        try:
            sync_cursor_payload_metrics(conn, session_id, seq, payload, now)
        except Exception:
            pass
    if event_id:
        update_hook_queue_audit(
            event_id,
            status="processed",
            processed_at=utc_now(),
            synchronous_decision=audit_synchronous_decision,
        )
    if is_stop_event(name):
        if initial_prompt_dream:
            spawn_initial_prompt_dream(session_id)
        else:
            spawn_stop_dream(session_id)
        spawn_scheduler_kick(name)
    context = _join_hook_context_blocks(startup_context, prompt_context)
    return (exit_code, context, block_reason) if return_context else exit_code


def cmd_replay_hook_queue(args: argparse.Namespace) -> int:
    if not system_admission_open(installation_root=ROOT):
        print("replayed queued hook events: 0 worker=suspended")
        return 0
    root = MEMORY_DIR / "events" / "queue"
    worker_lock = None
    started_at = utc_now()
    try:
        if getattr(args, "worker", False):
            worker_lock = acquire_lock("hook-queue-worker", "global")
            if worker_lock is None:
                print("replayed queued hook events: 0 remaining=0 worker=busy")
                return 0
            write_hook_worker_status(running=True, reason="replay-hook-queue", started_at=started_at, heartbeat_at=started_at)
        recovered = recover_failed_hook_queue_events(client=args.client, limit=max(args.limit, getattr(args, "recover_limit", args.limit)))
        if not root.exists():
            print(
                "replayed queued hook events: 0 "
                f"remaining=0 failed={recovered['failed']} recovered={recovered['recovered']} dead_letters={recovered['remaining']}"
            )
            return 1 if recovered["failed"] and args.stop_on_error else 0
        patterns = [str(root / safe_slug(args.client) / "*.json")] if args.client else [str(root / "*" / "*.json")]
        files: list[tuple[tuple[str, str, str, int, str, str], Path, dict[str, Any]]] = []
        parse_failed = 0
        for pattern in patterns:
            for path in glob(pattern):
                queue_path = Path(path)
                try:
                    item = load_hook_queue_item(queue_path)
                    files.append((hook_queue_sort_key(queue_path, item), queue_path, item))
                except Exception as exc:
                    parse_failed += 1
                    append_hook_queue_log(
                        "queue replay could not parse item",
                        path=str(queue_path),
                        error=str(exc),
                    )
                    if args.stop_on_error:
                        print(f"replayed queued hook events: 0 remaining=0 failed={parse_failed}")
                        return 1
        files.sort(key=lambda entry: entry[0])
        files = files[: args.limit]
        replayed = 0
        failed = parse_failed
        for _sort_key, path, item in files:
            if not system_admission_open(installation_root=ROOT):
                append_hook_queue_log("queue replay paused before claim", reason="system-suspended")
                break
            try:
                client = str(item.get("client_type") or args.client or "unknown")
                payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
                event_id = str(item.get("event_id") or "")
                reserved_seq = item.get("reserved_seq")
                pretool_sync_decision = item.get("synchronous_decision_data")
                audit_synchronous_decision = str(item.get("synchronous_decision") or "").strip() or None
                log_payload(
                    client,
                    payload,
                    detect_version=False,
                    queue_on_failure=False,
                    reserved_seq=int(reserved_seq) if reserved_seq not in (None, "") else None,
                    event_id=event_id or None,
                    recorded_at=str(item.get("recorded_at") or ""),
                    queued_at=str(item.get("queued_at") or ""),
                    hook_mode=str(item.get("hook_mode") or "queue"),
                    pretool_sync_decision=pretool_sync_decision if isinstance(pretool_sync_decision, dict) else None,
                    audit_synchronous_decision=audit_synchronous_decision,
                )
                path.unlink(missing_ok=True)
                replayed += 1
            except Exception as exc:
                failed += 1
                try:
                    event_id = str(item.get("event_id") or "")
                    if event_id:
                        update_hook_queue_audit(event_id, status="failed", error="replay-failed")
                except Exception:
                    pass
                append_hook_queue_log(
                    "queue replay failed",
                    path=str(path),
                    event_id=str(item.get("event_id") or ""),
                    session_id=str(item.get("session_id") or ""),
                    reserved_seq=item.get("reserved_seq"),
                    error=str(exc),
                )
                if args.stop_on_error:
                    break
            finally:
                if getattr(args, "worker", False):
                    write_hook_worker_status(running=True, reason="replay-hook-queue", started_at=started_at, heartbeat_at=utc_now())
        remaining = len(list(root.glob("*/*.json")))
        if replayed:
            spawn_scheduler_kick("hook-replay")
        print(
            f"replayed queued hook events: {replayed} remaining={remaining} failed={failed} "
            f"recovered={recovered['recovered']} dead_letters={recovered['remaining']}"
        )
        return 1 if failed and args.stop_on_error else 0
    finally:
        if getattr(args, "worker", False) and worker_lock is not None:
            write_hook_worker_status(running=False, reason="replay-hook-queue", started_at=started_at, heartbeat_at=utc_now(), last_exit_at=utc_now())
            release_lock(worker_lock)


def cmd_recover_hook_queue_failures(args: argparse.Namespace) -> int:
    result = recover_failed_hook_queue_events(client=args.client, limit=args.limit)
    print(
        f"recovered dead-letter hook events: {result['recovered']} "
        f"remaining={result['remaining']} failed={result['failed']}"
    )
    return 1 if result["failed"] and getattr(args, "stop_on_error", False) else 0
