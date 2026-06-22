"""Risk application facade.

This module is the application layer entry for risk policy operations.
It keeps existing command/risk-call sites stable while we move toward
clearer boundary separation without changing behavior in this phase.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ..domain import risk as _risk_domain
from ..ports.clock import Clock


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        from ..infrastructure.config import utc_now

        return utc_now()


def _default_clock() -> Clock:
    return _DefaultClock()


def _now() -> str:
    return _default_clock().utc_now()


def _json_dumps(value: Any) -> str:
    from ..infrastructure.config import json_dumps

    return json_dumps(value)

RiskDecision = _risk_domain.RiskDecision
RISK_SCHEMA_VERSION = _risk_domain.RISK_SCHEMA_VERSION
VALID_DECISIONS = _risk_domain.VALID_DECISIONS
VALID_RISK_LEVELS = _risk_domain.VALID_RISK_LEVELS
VALID_SENSITIVITY = _risk_domain.VALID_SENSITIVITY
VALID_INJECTION_POLICIES = _risk_domain.VALID_INJECTION_POLICIES
VALID_MEMORY_ACTIONS = _risk_domain.VALID_MEMORY_ACTIONS
HARD_BLOCK_FLAGS = _risk_domain.HARD_BLOCK_FLAGS
NON_OVERRIDABLE_HARD_BLOCK_FLAGS = _risk_domain.NON_OVERRIDABLE_HARD_BLOCK_FLAGS


class RiskUseCase:
    """Explicit use-case façade used by interface/application adapters."""

    def scan_text(self, text: Any, *, source_kind: str = "text") -> RiskDecision:
        return _risk_domain.scan_text(text, source_kind=source_kind)

    def scan_tool_input(self, tool_name: str | None, tool_input: Any) -> RiskDecision:
        return _risk_domain.scan_tool_input(tool_name, tool_input)

    def scan_tool_output(self, text: Any) -> RiskDecision:
        return _risk_domain.scan_tool_output(text)

    def classify_tool_command(self, tool_name: str | None, tool_input: Any) -> RiskDecision:
        return self.scan_tool_input(tool_name, tool_input)

    def apply_taint_to_decision(
        self,
        decision: RiskDecision,
        *,
        action_class: str,
        taint_context: list[dict[str, Any]],
        command_hash: str = "",
    ) -> RiskDecision:
        return _risk_domain.apply_taint_to_decision(
            decision,
            action_class=action_class,
            taint_context=taint_context,
            command_hash=command_hash,
        )

    def extract_command_from_tool_input(self, tool_input: Any) -> str:
        return _risk_domain.extract_command_from_tool_input(tool_input)

    def shell_action_class(self, command: str) -> str:
        return _risk_domain.shell_action_class(command)

    def tool_action_class(self, tool_name: str | None, tool_input: Any, *, hook_event_name: str | None = None) -> str:
        return _risk_domain.tool_action_class(tool_name, tool_input, hook_event_name=hook_event_name)

    def shell_command_hash(self, command: str, *, workdir: str | None = None) -> str:
        return _risk_domain.shell_command_hash(command, workdir=workdir)

    def record_event(
        self,
        conn,
        decision: RiskDecision,
        *,
        client_type: str | None = None,
        session_id: str | None = None,
        event_seq: int | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        source_kind: str,
        source_ref: str | None = None,
        workdir: str | None = None,
        status: str | None = None,
        classifier_run_id: str | None = None,
        approval_state: str | None = None,
        approval_token: str | None = None,
        command_hash: str | None = None,
        taint_context: list[dict[str, Any]] | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> str:
        now = _now()
        rid = risk_event_id()
        decision.risk_event_id = rid
        final_status = status or {
            "allow": "allowed",
            "warn": "warned",
            "quarantine": "quarantined",
            "block": "blocked",
        }.get(decision.decision, decision.decision)
        conn.execute(
            """
            insert into risk_events (
              risk_event_id, created_at, updated_at, client_type, session_id,
              event_seq, tool_call_id, tool_name, source_kind, source_ref, workdir,
              status, decision, policy, risk_level, sensitivity, categories_json,
              poisoning_flags_json, injection_policy, memory_action, impact, reason,
              confidence, deterministic_flags_json, classifier_run_id, preview,
              evidence_json, approval_state, approval_token, command_hash,
              taint_context_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rid,
                now,
                now,
                client_type,
                session_id,
                event_seq,
                tool_call_id,
                tool_name,
                source_kind,
                source_ref,
                workdir,
                final_status,
                decision.decision,
                decision.decision,
                decision.risk_level,
                decision.sensitivity,
                _json_dumps(decision.categories),
                _json_dumps(decision.poisoning_flags),
                decision.injection_policy,
                decision.memory_action,
                decision.impact,
                decision.reason,
                decision.confidence,
                _json_dumps(decision.deterministic_flags),
                classifier_run_id,
                decision.preview,
                _json_dumps(evidence or []),
                approval_state or decision.approval_state or "",
                approval_token or decision.approval_token or "",
                command_hash or decision.command_hash or "",
                _json_dumps(taint_context if taint_context is not None else decision.taint_context),
            ),
        )
        for item in evidence or []:
            quote = str(item.get("quote") or decision.preview or "")
            conn.execute(
                """
                insert into risk_evidence (
                  evidence_id, risk_event_id, created_at, source_kind, source_ref,
                  field, quote, sha256
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"riskev_{uuid.uuid4().hex[:16]}",
                    rid,
                    now,
                    str(item.get("source_kind") or source_kind),
                    str(item.get("source_ref") or source_ref or ""),
                    str(item.get("field") or ""),
                    quote[:1200],
                    hashlib.sha256(quote.encode("utf-8", errors="replace")).hexdigest() if quote else None,
                ),
            )
        return rid

    def is_hard_block(self, decision: RiskDecision) -> bool:
        return _risk_domain.is_hard_block(decision)

    def is_non_overridable_block(self, decision: RiskDecision) -> bool:
        return _risk_domain.is_non_overridable_block(decision)

    def generate_payload_marker(self) -> str:
        return _risk_domain.generate_payload_marker()

    def payload_contains_marker(self, payload: str, marker: str) -> bool:
        return _risk_domain.payload_contains_marker(payload, marker)

    def validate_classifier_json(self, value: Any) -> RiskDecision:
        return _risk_domain.validate_classifier_json(value)

    def merge_decisions(self, deterministic: RiskDecision, classifier: RiskDecision) -> RiskDecision:
        return _risk_domain.merge_decisions(deterministic, classifier)

    def invalid_classifier_decision(self, *, source_kind: str, existing: RiskDecision | None = None) -> RiskDecision:
        return _risk_domain.invalid_classifier_decision(source_kind=source_kind, existing=existing)


risk_use_case = RiskUseCase()


def scan_text(text: Any, *, source_kind: str = "text") -> RiskDecision:
    return risk_use_case.scan_text(text, source_kind=source_kind)


def scan_tool_input(tool_name: str | None, tool_input: Any) -> RiskDecision:
    return risk_use_case.scan_tool_input(tool_name, tool_input)


def scan_tool_output(text: Any) -> RiskDecision:
    return risk_use_case.scan_tool_output(text)


def classify_tool_command(tool_name: str | None, tool_input: Any) -> RiskDecision:
    return risk_use_case.classify_tool_command(tool_name, tool_input)


def apply_taint_to_decision(decision: RiskDecision, *, action_class: str, taint_context: list[dict[str, Any]], command_hash: str = "") -> RiskDecision:
    return risk_use_case.apply_taint_to_decision(
        decision,
        action_class=action_class,
        taint_context=taint_context,
        command_hash=command_hash,
    )


def extract_command_from_tool_input(tool_input: Any) -> str:
    return risk_use_case.extract_command_from_tool_input(tool_input)


def shell_action_class(command: str) -> str:
    return risk_use_case.shell_action_class(command)


def tool_action_class(tool_name: str | None, tool_input: Any, *, hook_event_name: str | None = None) -> str:
    return risk_use_case.tool_action_class(tool_name, tool_input, hook_event_name=hook_event_name)


def shell_command_hash(command: str, *, workdir: str | None = None) -> str:
    return risk_use_case.shell_command_hash(command, workdir=workdir)


def risk_event_id() -> str:
    return f"risk_{uuid.uuid4().hex[:16]}"


def is_hard_block(decision: RiskDecision) -> bool:
    return risk_use_case.is_hard_block(decision)


def is_non_overridable_block(decision: RiskDecision) -> bool:
    return risk_use_case.is_non_overridable_block(decision)


def generate_payload_marker() -> str:
    return risk_use_case.generate_payload_marker()


def payload_contains_marker(payload: str, marker: str) -> bool:
    return risk_use_case.payload_contains_marker(payload, marker)


def validate_classifier_json(value: Any) -> RiskDecision:
    return risk_use_case.validate_classifier_json(value)


def merge_decisions(deterministic: RiskDecision, classifier: RiskDecision) -> RiskDecision:
    return risk_use_case.merge_decisions(deterministic, classifier)


def invalid_classifier_decision(*, source_kind: str, existing: RiskDecision | None = None) -> RiskDecision:
    return risk_use_case.invalid_classifier_decision(source_kind=source_kind, existing=existing)


def record_risk_event(
    conn,
    decision: RiskDecision,
    *,
    client_type: str | None = None,
    session_id: str | None = None,
    event_seq: int | None = None,
    tool_call_id: str | None = None,
    tool_name: str | None = None,
    source_kind: str,
    source_ref: str | None = None,
    workdir: str | None = None,
    status: str | None = None,
    classifier_run_id: str | None = None,
    approval_state: str | None = None,
    approval_token: str | None = None,
    command_hash: str | None = None,
    taint_context: list[dict[str, Any]] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> str:
    return risk_use_case.record_event(
        conn,
        decision,
        client_type=client_type,
        session_id=session_id,
        event_seq=event_seq,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        source_kind=source_kind,
        source_ref=source_ref,
        workdir=workdir,
        status=status,
        classifier_run_id=classifier_run_id,
        approval_state=approval_state,
        approval_token=approval_token,
        command_hash=command_hash,
        taint_context=taint_context,
        evidence=evidence,
    )
