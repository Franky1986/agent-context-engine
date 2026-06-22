from __future__ import annotations

import hashlib
import json
import re
import secrets
import shlex
import uuid
from dataclasses import dataclass, field
from typing import Any

RISK_SCHEMA_VERSION = "risk-classifier-v1"
VALID_DECISIONS = {"allow", "warn", "quarantine", "block"}
VALID_RISK_LEVELS = {"none", "low", "medium", "high", "critical"}
VALID_SENSITIVITY = {"normal", "private", "secret"}
VALID_INJECTION_POLICIES = {"startup_safe", "on_demand", "never_auto", "quarantine"}
VALID_MEMORY_ACTIONS = {"index", "reference_only", "quarantine", "drop_from_memory"}
HARD_BLOCK_FLAGS = {
    "agent_self_approval_attempt",
    "network_to_shell",
    "network_to_interpreter",
    "network_download_execute",
    "decoded_payload_to_shell",
    "recursive_force_delete",
    "destructive_git",
    "firewall_disable_attempt",
    "hook_integrity_change",
    "tainted_context_side_effect",
}
NON_OVERRIDABLE_HARD_BLOCK_FLAGS = HARD_BLOCK_FLAGS - {"tainted_context_side_effect"}


@dataclass
class RiskDecision:
    decision: str = "allow"
    risk_level: str = "none"
    sensitivity: str = "normal"
    categories: list[str] = field(default_factory=list)
    poisoning_flags: list[str] = field(default_factory=list)
    injection_policy: str = "on_demand"
    memory_action: str = "index"
    impact: str = "No meaningful security impact identified."
    reason: str = "No deterministic risk pattern matched."
    confidence: float = 0.25
    deterministic_flags: list[str] = field(default_factory=list)
    preview: str = ""
    approval_state: str = ""
    approval_token: str = ""
    command_hash: str = ""
    risk_event_id: str = ""
    taint_context: list[dict[str, Any]] = field(default_factory=list)

    @property
    def should_block(self) -> bool:
        return self.decision == "block"

    @property
    def is_risky(self) -> bool:
        return self.decision in {"warn", "quarantine", "block"} or self.risk_level in {"medium", "high", "critical"}

    def to_json(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "risk_level": self.risk_level,
            "sensitivity": self.sensitivity,
            "categories": self.categories,
            "poisoning_flags": self.poisoning_flags,
            "injection_policy": self.injection_policy,
            "impact": self.impact,
            "memory_action": self.memory_action,
            "reason": self.reason,
            "confidence": self.confidence,
            "deterministic_flags": self.deterministic_flags,
            "approval_state": self.approval_state,
            "approval_token": self.approval_token,
            "command_hash": self.command_hash,
            "risk_event_id": self.risk_event_id,
            "taint_context": self.taint_context,
        }


def _preview(text: str, limit: int = 700) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:limit]


def _add(result: RiskDecision, *, category: str, flag: str | None = None) -> None:
    if category not in result.categories:
        result.categories.append(category)
    if flag and flag not in result.poisoning_flags:
        result.poisoning_flags.append(flag)
    if category not in result.deterministic_flags:
        result.deterministic_flags.append(category)


def _escalate(result: RiskDecision, *, decision: str, risk_level: str, injection_policy: str, memory_action: str, impact: str, reason: str, confidence: float) -> None:
    order_decision = {"allow": 0, "warn": 1, "quarantine": 2, "block": 3}
    order_risk = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    if order_decision[decision] > order_decision[result.decision]:
        result.decision = decision
    if order_risk[risk_level] > order_risk[result.risk_level]:
        result.risk_level = risk_level
    if injection_policy in {"never_auto", "quarantine"}:
        result.injection_policy = injection_policy
    if memory_action in {"reference_only", "quarantine", "drop_from_memory"}:
        result.memory_action = memory_action
    if confidence >= result.confidence:
        result.impact = impact
        result.reason = reason
        result.confidence = confidence


def scan_text(text: Any, *, source_kind: str = "text") -> RiskDecision:
    raw = str(text or "")
    lower = raw.lower()
    result = RiskDecision(preview=_preview(raw), memory_action="index")
    if not raw.strip():
        return result

    if re.search(r"\b(ignore|bypass|override|forget)\b.{0,80}\b(system|developer|previous|above)\b.{0,80}\b(instruction|prompt|rule)s?\b", lower, re.I):
        _add(result, category="prompt_injection", flag="instruction_override")
        _escalate(
            result,
            decision="quarantine",
            risk_level="high",
            injection_policy="quarantine",
            memory_action="quarantine",
            impact="May cause an agent to ignore higher-priority instructions if reused as context.",
            reason="Text attempts to override agent/system instructions.",
            confidence=0.9,
        )

    if re.search(r"\b(curl|wget)\b[^|;\n]{0,300}\|\s*(sh|bash|zsh)\b", lower, re.I):
        _add(result, category="shell_pipe_to_interpreter", flag="network_to_shell")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "quarantine",
            risk_level="critical",
            injection_policy="quarantine",
            memory_action="quarantine",
            impact="Downloads remote content and executes it with local user permissions.",
            reason="Network download is piped directly into a shell interpreter.",
            confidence=0.98,
        )

    if re.search(r"\b(curl|wget)\b[^|;\n]{0,300}\|\s*(python3?|node|deno|bun|ruby|perl|php|lua)\b", lower, re.I):
        _add(result, category="network_pipe_to_interpreter", flag="network_to_interpreter")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "quarantine",
            risk_level="critical",
            injection_policy="quarantine",
            memory_action="quarantine",
            impact="Downloads remote code and executes it with a local interpreter.",
            reason="Network download is piped directly into a code interpreter.",
            confidence=0.98,
        )

    if re.search(
        r"\b(curl|wget)\b[^\n]{0,240}https?://[^\n]{0,240}(-o|--output-document=|-O|--output)\s+([^\s;&|]+)[^\n]{0,300}(&&|;)[^\n]{0,180}\b(chmod\s+\+x\s+\3|sh\s+\3|bash\s+\3|zsh\s+\3|python3?\s+\3|node\s+\3|ruby\s+\3|perl\s+\3|php\s+\3|\.\/[^\s;&|]+)",
        lower,
        re.I,
    ):
        _add(result, category="download_then_execute", flag="network_download_execute")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "quarantine",
            risk_level="critical",
            injection_policy="quarantine",
            memory_action="quarantine",
            impact="Downloads remote content and executes or prepares it for execution in the same command chain.",
            reason="Network download is chained to local execution or executable permission changes.",
            confidence=0.94,
        )

    if source_kind != "tool_output_text" and (
        re.search(r"\b/api/firewall-(state|override)\b", lower)
        or re.search(r"\bfirewall_(state|overrides?|rules?)\b", lower)
        or re.search(r"\bset_firewall_enabled\s*\(", lower)
        or re.search(r"\b(create|revoke)_firewall_override\s*\(", lower)
        or re.search(r"\b(create|disable)_firewall_rule\s*\(", lower)
        or re.search(r"(^|\s)firewall\s+(add|disable|update|delete|enable|revoke)\b", lower)
    ) and (
        re.search(r"\b(post|put|patch|delete)\b", lower)
        or re.search(r"\b(enabled\s*=\s*false|enabled\s*:\s*false|enabled\s*=\s*0|enabled\s*:\s*0)\b", lower)
        or re.search(r"\b(update|insert\s+into|replace\s+into|delete\s+from)\s+firewall_(state|overrides?|rules?)\b", lower)
        or re.search(r"\bset_firewall_enabled\s*\([^)]*enabled\s*=\s*false", lower, re.S)
        or re.search(r"\b(create|revoke)_firewall_override\s*\(", lower)
        or re.search(r"\b(create|disable)_firewall_rule\s*\(", lower)
        or re.search(r"(^|\s)firewall\s+(add|disable|update|delete|enable|revoke)\b", lower)
    ):
        _add(result, category="firewall_control", flag="firewall_disable_attempt")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "quarantine",
            risk_level="critical",
            injection_policy="never_auto",
            memory_action="reference_only",
            impact="Would disable or alter Agent Context Engine firewall enforcement from an agent-controlled tool path.",
            reason="Firewall enforcement can only be changed through the trusted monitor UI, not by agent-executed scripts or API calls.",
            confidence=0.99,
        )

    if re.search(r"\b(base64|openssl\s+base64)\b[^|;\n]{0,300}(-d|--decode|decode)[^|;\n]{0,300}\|\s*(sh|bash|zsh)\b", lower, re.I):
        _add(result, category="shell_pipe_to_interpreter", flag="decoded_payload_to_shell")
        _add(result, category="obfuscated_payload", flag="base64_decode_execution")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "quarantine",
            risk_level="critical",
            injection_policy="quarantine",
            memory_action="quarantine",
            impact="Executes decoded shell content with local user permissions.",
            reason="Base64-decoded content is piped directly into a shell interpreter.",
            confidence=0.99,
        )

    if re.search(r"\beval\s+[`\"'$({]", lower) or re.search(r"\b(sh|bash|zsh)\s+-c\s+[`\"']", lower):
        _add(result, category="unsafe_automation", flag="dynamic_shell_eval")
        _escalate(
            result,
            decision="warn",
            risk_level="medium",
            injection_policy="on_demand",
            memory_action="reference_only",
            impact="Evaluates dynamically constructed shell content.",
            reason="Dynamic shell execution pattern matched.",
            confidence=0.78,
        )

    if re.search(r"\brm\s+-[^\n;&|]*r[^\n;&|]*f\s+(/|~|\$HOME|\*)", lower):
        _add(result, category="destructive_command", flag="recursive_force_delete")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "quarantine",
            risk_level="critical",
            injection_policy="quarantine",
            memory_action="quarantine",
            impact="May recursively delete important local files.",
            reason="Recursive force delete targets a broad or sensitive path.",
            confidence=0.98,
        )

    if re.search(r"\b(git\s+reset\s+--hard|git\s+clean\s+-[^\n;&|]*[fd])\b", lower):
        _add(result, category="destructive_command", flag="destructive_git")
        _escalate(
            result,
            decision="block" if source_kind in {"tool_input", "shell_command"} else "warn",
            risk_level="high",
            injection_policy="on_demand",
            memory_action="reference_only",
            impact="May irreversibly discard local worktree changes or untracked files.",
            reason="Destructive git operation matched.",
            confidence=0.95,
        )

    if re.search(r"(-----BEGIN (OPENSSH |RSA |EC |DSA )?PRIVATE KEY-----|xox[baprs]-|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})", raw):
        _add(result, category="credential_exfiltration", flag="credential_like_material")
        result.sensitivity = "secret"
        _escalate(
            result,
            decision="quarantine",
            risk_level="critical",
            injection_policy="never_auto",
            memory_action="quarantine",
            impact="May expose credentials or authentication material if stored or injected.",
            reason="Credential-like material matched.",
            confidence=0.96,
        )

    if "osascript" in lower or "system events" in lower:
        _add(result, category="unsafe_automation", flag="macos_ui_automation")
        _escalate(
            result,
            decision="warn",
            risk_level="medium",
            injection_policy="on_demand",
            memory_action="reference_only",
            impact="May automate local applications or system UI with side effects.",
            reason="macOS UI automation pattern matched.",
            confidence=0.72,
        )

    return result


def extract_command_from_tool_input(tool_input: Any) -> str:
    if isinstance(tool_input, str):
        return tool_input
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "shell_command", "script"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
        if "args" in tool_input:
            try:
                return json.dumps(tool_input["args"], ensure_ascii=False, sort_keys=True)
            except Exception:
                return str(tool_input["args"])
    return "" if tool_input is None else str(tool_input)


def shell_command_hash(command: str, *, workdir: str | None = None) -> str:
    normalized = " ".join(str(command or "").strip().split())
    return hashlib.sha256(f"{workdir or ''}\n{normalized}".encode("utf-8", errors="replace")).hexdigest()


def approval_nonce() -> str:
    return f"nonce_{secrets.token_hex(6)}"


def _iter_tool_input_strings(value: Any) -> list[str]:
    strings: list[str] = []

    def visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            if item:
                strings.append(item)
            return
        if isinstance(item, dict):
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple, set)):
            for nested in item:
                visit(nested)
            return
        if isinstance(item, (int, float, bool)):
            strings.append(str(item))

    visit(value)
    return strings


def _looks_like_remote_reference(value: str) -> bool:
    text = str(value or "").strip().lower()
    return bool(re.search(r"\b(https?|ftp|ssh)://", text))


def _looks_like_local_reference(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered.startswith("file://"):
        return True
    if _looks_like_remote_reference(text):
        return False
    return True


def _tool_input_has_remote_reference(tool_input: Any) -> bool:
    return any(_looks_like_remote_reference(item) for item in _iter_tool_input_strings(tool_input))


def _tool_input_looks_like_local_read(tool_input: Any) -> bool:
    if isinstance(tool_input, dict):
        path_keys = (
            "file_path",
            "path",
            "paths",
            "filename",
            "file",
            "target_file",
            "source_file",
            "uri",
        )
        for key in path_keys:
            value = tool_input.get(key)
            if isinstance(value, str) and _looks_like_local_reference(value):
                return True
            if isinstance(value, list) and value and all(isinstance(item, str) and _looks_like_local_reference(item) for item in value):
                return True
    return False


def shell_action_class(command: str) -> str:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return "unknown"
    lower = normalized.lower()
    if is_agent_memory_cli_command(normalized) and not is_agent_memory_self_approval_command(normalized):
        return "read"
    try:
        parts = shlex.split(normalized)
    except ValueError:
        parts = normalized.split()
    executable = parts[0] if parts else ""
    if re.search(r"\b(curl|wget|ssh|scp|sftp|nc|ncat|ftp|telnet)\b", lower) or re.search(r"https?://|ftp://|ssh://", lower):
        return "network"
    if executable in {"rm", "rmdir", "unlink"} or re.search(r"\b(delete|drop|truncate)\b", lower):
        return "delete"
    if "deploy" in executable.lower() or re.search(r"\b(deploy|deployment|rollout|release)\b", lower):
        return "deploy"
    if is_simple_read_only_shell_command(command):
        return "read"
    if is_verification_shell_command(command):
        return "verify"
    if is_secret_permission_hardening_shell_command(command):
        return "protect_secret"
    if executable in {"chmod", "chown", "mv", "cp", "install", "tee"} or re.search(r"[>|]|\b(apply_patch|patch|python|node|npm|pnpm|yarn|docker|kubectl|terraform|ansible|ssh|sh|bash|zsh)\b", lower):
        return "write_execute"
    if executable in {"git"} and any(arg in {"commit", "push", "pull", "fetch", "merge", "rebase", "reset", "clean", "checkout", "switch"} for arg in parts[1:]):
        return "write_execute"
    return "unknown"


def tool_action_class(tool_name: str | None, tool_input: Any, *, hook_event_name: str | None = None) -> str:
    event_name = str(hook_event_name or "").strip().lower()
    normalized_tool = str(tool_name or "").strip().lower()
    command = extract_command_from_tool_input(tool_input)
    if normalized_tool in {"bash", "shell", "exec_command"}:
        return shell_action_class(command)
    if event_name == "beforereadfile":
        return "read"
    if _tool_input_has_remote_reference(tool_input):
        return "network"
    if normalized_tool in {"read", "readfile", "open", "view"} and _tool_input_looks_like_local_read(tool_input):
        return "read"
    if _tool_input_looks_like_local_read(tool_input):
        return "read"
    return "unknown"


def apply_taint_to_decision(decision: RiskDecision, *, action_class: str, taint_context: list[dict[str, Any]], command_hash: str = "") -> RiskDecision:
    if not taint_context:
        return decision
    decision.taint_context = taint_context[:5]
    decision.command_hash = command_hash
    if "tainted_context_nearby" not in decision.deterministic_flags:
        decision.deterministic_flags.append("tainted_context_nearby")
    if action_class == "read":
        if decision.decision == "allow":
            decision.decision = "warn"
            decision.risk_level = "low"
            decision.memory_action = "reference_only"
            decision.injection_policy = "on_demand"
            decision.reason = "Read-only action follows prior sensitive or quarantined context; allowed with audit warning."
            decision.impact = "Reads local context after a tainted source but does not itself create side effects."
            decision.confidence = max(decision.confidence, 0.75)
        return decision
    if action_class == "verify":
        if decision.decision == "allow":
            decision.decision = "warn"
            decision.risk_level = "low"
            decision.memory_action = "reference_only"
            decision.injection_policy = "on_demand"
            decision.reason = "Verification command follows prior sensitive or quarantined context; allowed with audit warning."
            decision.impact = "Runs a local verification command such as typecheck, test, lint, or audit; no deploy/install/delete pattern matched."
            decision.confidence = max(decision.confidence, 0.86)
        if "verification_command_allowlisted" not in decision.deterministic_flags:
            decision.deterministic_flags.append("verification_command_allowlisted")
        return decision
    if action_class == "protect_secret":
        if decision.decision == "allow":
            decision.decision = "warn"
            decision.risk_level = "low"
            decision.memory_action = "reference_only"
            decision.injection_policy = "on_demand"
            decision.reason = "Secret-file permission hardening follows prior sensitive context; allowed with audit warning."
            decision.impact = "Restricts local secret file permissions without network, delete, or execute patterns."
            decision.confidence = max(decision.confidence, 0.88)
        if "secret_permission_hardening_allowlisted" not in decision.deterministic_flags:
            decision.deterministic_flags.append("secret_permission_hardening_allowlisted")
        return decision
    if action_class in {"write_execute", "network", "deploy", "delete", "unknown"}:
        decision.decision = "block"
        decision.risk_level = "high" if decision.risk_level != "critical" else "critical"
        decision.injection_policy = "never_auto"
        decision.memory_action = "reference_only"
        decision.approval_state = "required"
        decision.approval_token = approval_nonce()
        _add(decision, category="approval_required", flag="tainted_context_side_effect")
        decision.reason = "Side-effect-capable action follows prior sensitive or quarantined context and requires explicit user approval."
        decision.impact = "May execute a decision derived from tainted or sensitive context; require approval tied to this exact command hash."
        decision.confidence = max(decision.confidence, 0.9)
    return decision


def scan_tool_input(tool_name: str | None, tool_input: Any) -> RiskDecision:
    command = extract_command_from_tool_input(tool_input)
    source_kind = "shell_command" if str(tool_name or "").lower() in {"bash", "shell", "exec_command"} else "tool_input"
    result = scan_text(command, source_kind=source_kind)
    if is_agent_memory_cli_command(command):
        if (
            is_agent_memory_self_approval_command(command)
            or is_agent_memory_firewall_mutation_command(command)
            or is_agent_memory_hook_mutation_command(command)
        ):
            _add(result, category="approval_required", flag="agent_self_approval_attempt")
            _escalate(
                result,
                decision="block",
                risk_level="critical",
                injection_policy="never_auto",
                memory_action="reference_only",
                impact="Would let the active agent alter Agent Context Engine safety policy from inside the guarded conversation.",
                reason="Mutating Agent Context Engine policy commands must be sent by the user through the direct chat control-plane, not executed as agent tools.",
                confidence=0.99,
            )
        else:
            result.deterministic_flags.append("agent_memory_cli_allowlisted")
    if source_kind == "shell_command" and not is_simple_read_only_shell_command(command) and targets_hook_integrity(command):
        _add(result, category="hook_integrity", flag="hook_integrity_change")
        _escalate(
            result,
            decision="block",
            risk_level="critical",
            injection_policy="never_auto",
            memory_action="reference_only",
            impact="Would modify Agent Context Engine hook configuration or adapter files that enforce capture and policy controls.",
            reason="Hook configuration changes are security-sensitive and must not be altered through ordinary agent tool execution.",
            confidence=0.98,
        )
    if source_kind == "shell_command" and is_simple_read_only_shell_command(command):
        result.deterministic_flags.append("simple_read_only_shell_allowlisted")
        result.reason = "Simple local read-only shell command allowlisted by deterministic policy."
        result.impact = "Reads local working context without network traffic or shell side effects."
        result.confidence = max(result.confidence, 0.9)
    if source_kind == "shell_command" and is_verification_shell_command(command):
        result.deterministic_flags.append("verification_command_allowlisted")
        result.reason = "Local verification command allowlisted by deterministic policy."
        result.impact = "Runs local validation such as typecheck, test, lint, or audit without install/deploy/delete/network-shell patterns."
        result.confidence = max(result.confidence, 0.88)
    if source_kind == "shell_command" and is_secret_permission_hardening_shell_command(command):
        result.deterministic_flags.append("secret_permission_hardening_allowlisted")
        result.reason = "Secret-file permission hardening allowlisted by deterministic policy."
        result.impact = "Restricts permissions on a local secret-like file without network, delete, or execute patterns."
        result.confidence = max(result.confidence, 0.9)
    if str(tool_name or "").lower() in {"bash", "shell", "exec_command"} and result.is_risky and result.decision == "quarantine":
        result.decision = "block"
    return result


def is_agent_memory_cli_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    while True:
        unwrapped = re.sub(r"^cd\s+.+?\s*(?:&&|;)\s*", "", normalized, count=1)
        if unwrapped == normalized:
            break
        normalized = " ".join(unwrapped.strip().split())
    patterns = (
        "./scripts/agent-context-engine ",
        "scripts/agent-context-engine ",
        "./docs/skills/agent-context-engine/scripts/agent-context-engine ",
        "docs/skills/agent-context-engine/scripts/agent-context-engine ",
        "python3 ./scripts/agent_context_engine.py ",
        "python3 scripts/agent_context_engine.py ",
        "python3 ./docs/skills/agent-context-engine/scripts/agent_context_engine.py ",
        "python3 docs/skills/agent-context-engine/scripts/agent_context_engine.py ",
        "python ./scripts/agent_context_engine.py ",
        "python scripts/agent_context_engine.py ",
        "python ./docs/skills/agent-context-engine/scripts/agent_context_engine.py ",
        "python docs/skills/agent-context-engine/scripts/agent_context_engine.py ",
    )
    exact = {"./scripts/agent-context-engine", "scripts/agent-context-engine", "./docs/skills/agent-context-engine/scripts/agent-context-engine"}
    return normalized in exact or normalized.endswith("/scripts/agent-context-engine") or normalized.endswith("/docs/skills/agent-context-engine/scripts/agent-context-engine") or normalized.startswith(patterns)


def is_agent_memory_self_approval_command(command: str) -> bool:
    if not is_agent_memory_cli_command(command):
        return False
    normalized = " ".join(str(command or "").strip().split())
    try:
        parts = shlex.split(normalized)
    except ValueError:
        parts = normalized.split()
    lowered = [part.lower() for part in parts]
    if "risk" not in lowered or "review" not in lowered:
        return False
    mutating_actions = {"mark-safe", "quarantine", "block", "warn", "allow", "release", "approve"}
    return any(part in mutating_actions for part in lowered)


def is_agent_memory_firewall_mutation_command(command: str) -> bool:
    if not is_agent_memory_cli_command(command):
        return False
    normalized = " ".join(str(command or "").strip().split())
    try:
        parts = shlex.split(normalized)
    except ValueError:
        parts = normalized.split()
    lowered = [part.lower() for part in parts]
    if "firewall" not in lowered:
        return False
    mutating_actions = {"add", "update", "disable", "enable", "delete", "revoke"}
    return any(part in mutating_actions for part in lowered)


def is_agent_memory_hook_mutation_command(command: str) -> bool:
    if not is_agent_memory_cli_command(command):
        return False
    normalized = " ".join(str(command or "").strip().split())
    try:
        parts = shlex.split(normalized)
    except ValueError:
        parts = normalized.split()
    lowered = [part.lower() for part in parts]
    if "hooks-disable" in lowered or "hooks-enable" in lowered:
        return True
    if "integration-hooks" not in lowered:
        return False
    if "--action" in lowered:
        try:
            return lowered[lowered.index("--action") + 1] == "disable"
        except IndexError:
            return False
    return "disable" in lowered


def targets_hook_integrity(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    patterns = (
        ".codex/hooks.json",
        ".codex/hooks_not_use_at_the_moment.json",
        ".claude/settings.json",
        ".gemini/settings.json",
        ".cursor/hooks.json",
        ".agents/hooks.json",
        "hooks_deactivated.json",
        "hook_adapter.sh",
        ".opencode/plugins/agent-memory.js",
        ".opencode/plugins/agent-memory_deactivated.js",
    )
    return any(pattern in normalized for pattern in patterns)


def is_simple_read_only_shell_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    if is_read_only_test_shell_command(normalized):
        return True
    shell_tokens = shell_tokens_with_pipe_operators(normalized)
    if "|" in shell_tokens:
        return is_simple_read_only_shell_pipeline_tokens(shell_tokens)
    sequence = _split_read_only_shell_sequence(normalized)
    if sequence:
        return all(
            is_simple_read_only_shell_command(segment)
            or is_shell_cd_command(segment)
            or (is_agent_memory_cli_command(segment) and not is_agent_memory_self_approval_command(segment) and not is_agent_memory_firewall_mutation_command(segment))
            for segment in sequence
        )
    # Keep this intentionally narrow: no shell composition, no redirects, no
    # substitutions, no env assignments, no network-capable executables.
    if re.search(r"(\|\||&&|[;&<>`]|[$][(]|[$][{]|\n)", normalized):
        return False
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", normalized):
        return False
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return False
    if not parts:
        return False
    if any(part in {"|", "||", "&&", ";", "&", ">", ">>", "<", "2>", "2>>"} for part in parts):
        return False
    if any(re.search(r"(^|[0-9])>>?|<", part) for part in parts):
        return False
    executable = parts[0]
    if "/" in executable:
        return False
    if executable == "pwd":
        return len(parts) == 1 or all(part in {"-L", "-P"} for part in parts[1:])
    if executable in {"bun", "node", "npm", "pnpm", "yarn", "tsc"}:
        return _is_version_command_args(parts[1:])
    if executable in {"ls", "cat", "head", "tail", "sed", "rg", "find", "nl"}:
        return _is_read_only_command_args(executable, parts[1:])
    if executable == "git":
        return _is_read_only_git_args(parts[1:])
    return False


def _split_read_only_shell_sequence(command: str) -> list[str] | None:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return None
    if re.search(r"(\|\||[|<>`]|[$][(]|[$][{]|\n)", normalized):
        return None
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", normalized):
        return None
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return None
    if not parts or "&&" not in parts and ";" not in parts:
        return None
    segments: list[list[str]] = [[]]
    for part in parts:
        if part in {"&&", ";"}:
            if not segments[-1]:
                return None
            segments.append([])
            continue
        if part in {"||", "&", "|", ">", ">>", "<", "2>", "2>>"}:
            return None
        if re.search(r"(^|[0-9])>>?|<", part):
            return None
        segments[-1].append(part)
    if not segments[-1]:
        return None
    return [" ".join(segment) for segment in segments if segment]


def is_shell_cd_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return False
    if len(parts) != 2 or parts[0] != "cd":
        return False
    target = parts[1]
    return bool(target) and not re.search(r"[|;&<>`]|[$][(]|[$][{]", target)


def is_verification_shell_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    shell_tokens = shell_tokens_with_pipe_operators(normalized)
    if "|" in shell_tokens:
        return False
    if re.search(r"(\|\||&&|[;&<>`]|[$][(]|[$][{]|\n)", normalized):
        return False
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", normalized):
        return False
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return False
    if not parts:
        return False
    executable = parts[0]
    if executable in {"npm", "bun", "pnpm", "yarn"}:
        return _is_package_verification_args(executable, parts[1:])
    executable_name = executable.rsplit("/", 1)[-1]
    if executable_name in {"tsc", "tsc.cmd"}:
        return _is_tsc_noemit_args(parts[1:])
    return False


def is_read_only_test_shell_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    if re.search(r"[;<>`]|[$][(]|[$][{]|\n", normalized):
        return False
    patterns = [
        r"^test\s+-(?:f|d|x|e|r|s)\s+\S+\s+&&\s+echo\s+[^|&;<>`$]+(?:\s+\|\|\s+echo\s+[^|&;<>`$]+)?$",
        r"^test\s+-f\s+\S+\s+&&\s+wc\s+-l\s+\S+$",
        r"^test\s+-d\s+\S+\s+&&\s+pwd$",
    ]
    return any(re.match(pattern, normalized) for pattern in patterns)


def is_secret_permission_hardening_shell_command(command: str) -> bool:
    normalized = " ".join(str(command or "").strip().split())
    if not normalized:
        return False
    if re.search(r"(\|\||&&|[;&<>`|]|[$][(]|[$][{]|\n)", normalized):
        return False
    try:
        parts = shlex.split(normalized)
    except ValueError:
        return False
    if len(parts) != 3:
        return False
    mode, path = parts[1], parts[2]
    if parts[0] != "chmod" or mode not in {"600", "0600", "u=rw,go=", "go-rwx"}:
        return False
    basename = path.rsplit("/", 1)[-1].lower()
    return basename.endswith((".env", ".key", ".pem", ".token")) or basename in {"trello.env", ".env"}


def is_simple_read_only_shell_pipeline(command: str) -> bool:
    return is_simple_read_only_shell_pipeline_tokens(shell_tokens_with_pipe_operators(command))


def shell_tokens_with_pipe_operators(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars="|")
    lexer.whitespace_split = True
    try:
        return list(lexer)
    except ValueError:
        return []


def is_simple_read_only_shell_pipeline_tokens(tokens: list[str]) -> bool:
    if not tokens or "||" in tokens:
        return False
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token == "|":
            segments.append([])
        else:
            segments[-1].append(token)
    if len(segments) < 2 or any(not segment for segment in segments):
        return False
    if not _is_read_only_pipeline_source_tokens(segments[0]):
        return False
    return all(_is_read_only_pipeline_filter_tokens(segment) for segment in segments[1:])


def _is_read_only_pipeline_source_tokens(parts: list[str]) -> bool:
    if not parts:
        return False
    executable = parts[0]
    if "/" in executable:
        return False
    if executable not in {"ls", "cat", "head", "tail", "sed", "rg", "find", "nl", "pwd", "git"}:
        return False
    return _is_read_only_command_parts(parts)


def _is_read_only_pipeline_filter_tokens(parts: list[str]) -> bool:
    if not parts:
        return False
    executable = parts[0]
    if "/" in executable:
        return False
    if executable in {"sort", "uniq", "wc"}:
        return _is_read_only_command_args(executable, parts[1:])
    if executable in {"head", "tail", "sed", "rg", "cat"}:
        return _is_read_only_command_args(executable, parts[1:])
    return False


def _is_read_only_command_parts(parts: list[str]) -> bool:
    if not parts:
        return False
    if any(part in {"|", "||", "&&", ";", "&", ">", ">>", "<", "2>", "2>>"} for part in parts):
        return False
    if any(re.search(r"(^|[0-9])>>?|<", part) for part in parts):
        return False
    executable = parts[0]
    if "/" in executable:
        return False
    if executable == "pwd":
        return len(parts) == 1 or all(part in {"-L", "-P"} for part in parts[1:])
    if executable in {"ls", "cat", "head", "tail", "sed", "rg", "find", "nl"}:
        return _is_read_only_command_args(executable, parts[1:])
    if executable == "git":
        return _is_read_only_git_args(parts[1:])
    return False


def _is_read_only_command_args(executable: str, args: list[str]) -> bool:
    forbidden_tokens = {
        "-exec",
        "-execdir",
        "-delete",
        "-ok",
        "-okdir",
        "--exec",
        "--pre",
        "--pre-glob",
        "--replace",
        "--passthru",
        "-i",
        "--in-place",
        "--follow",
        "-z",
        "--files0-from",
    }
    forbidden_prefixes = ("--pre=", "--replace=", "--passthru=", "--files0-from=", "--output=", "--output-error=")
    network_like = re.compile(r"^(https?|ftp|ssh|scp|sftp)://", re.I)
    for arg in args:
        if arg in forbidden_tokens or any(arg.startswith(prefix) for prefix in forbidden_prefixes):
            return False
        if network_like.search(arg):
            return False
    if executable == "sed":
        # Allow common print-only inspection, not arbitrary editing scripts.
        joined = " ".join(args)
        return bool(re.search(r"(^|\s)-n(\s|$)", joined)) and bool(re.search(r"\bp\b|[0-9],[0-9]+p", joined))
    return True


def _is_package_verification_args(executable: str, args: list[str]) -> bool:
    if not args:
        return False
    forbidden = {
        "add",
        "ci",
        "create",
        "deploy",
        "exec",
        "install",
        "link",
        "publish",
        "remove",
        "run-script",
        "start",
        "unlink",
        "update",
        "upgrade",
    }
    verify_scripts = {
        "audit",
        "check",
        "ci:test",
        "lint",
        "test",
        "test:ci",
        "test:e2e",
        "test:unit",
        "type-check",
        "typecheck",
        "type-check:ci",
        "typecheck:ci",
        "verify",
    }
    network_like = re.compile(r"^(https?|ftp|ssh|scp|sftp)://", re.I)
    if any(network_like.search(arg) for arg in args):
        return False
    if any(arg in {"--exec", "--script-shell", "--ignore-scripts=false"} or arg.startswith(("--exec=", "--script-shell=")) for arg in args):
        return False
    command = args[0]
    if command in forbidden:
        return False
    if executable == "npm" and command == "run":
        return len(args) >= 2 and args[1] in verify_scripts
    if executable in {"bun", "pnpm", "yarn"} and command == "run":
        return len(args) >= 2 and args[1] in verify_scripts
    if command in verify_scripts:
        return True
    if command == "audit":
        return True
    return False


def _is_version_command_args(args: list[str]) -> bool:
    return bool(args) and all(arg in {"-v", "--version", "version"} for arg in args)


def _is_tsc_noemit_args(args: list[str]) -> bool:
    if not args or "--noEmit" not in args:
        return False
    forbidden = {"--watch", "-w", "--build", "-b", "--init"}
    if any(arg in forbidden for arg in args):
        return False
    if any(re.match(r"^(https?|ftp|ssh|scp|sftp)://", arg, re.I) for arg in args):
        return False
    return True


def _is_read_only_git_args(args: list[str]) -> bool:
    if not args:
        return False
    forbidden_subcommands = {
        "add",
        "am",
        "apply",
        "bisect",
        "branch",
        "checkout",
        "cherry-pick",
        "clean",
        "clone",
        "commit",
        "fetch",
        "gc",
        "init",
        "merge",
        "mv",
        "pull",
        "push",
        "rebase",
        "reflog",
        "remote",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "submodule",
        "switch",
        "tag",
        "worktree",
    }
    read_only_subcommands = {"status", "diff", "log", "show", "rev-parse", "ls-files", "describe"}
    index = 0
    while index < len(args) and args[index].startswith("-"):
        # Avoid broad global option parsing. These options influence config,
        # repository paths, external paging, or output targets.
        if args[index] in {"-c", "-C", "--git-dir", "--work-tree", "--exec-path", "--paginate", "-p", "--no-pager"}:
            return False
        index += 1
    if index >= len(args):
        return False
    subcommand = args[index]
    if subcommand in forbidden_subcommands or subcommand not in read_only_subcommands:
        return False
    for arg in args[index + 1 :]:
        if arg in {"--output", "--exec-path"} or arg.startswith(("--output=", "--exec-path=")):
            return False
        if re.match(r"^(https?|ftp|ssh|scp|sftp)://", arg, re.I):
            return False
    return True


def scan_tool_output(text: Any) -> RiskDecision:
    result = scan_text(text, source_kind="tool_output_text")
    if result.decision == "allow":
        result.memory_action = "reference_only"
        result.impact = "Tool output should be stored as audit data and referenced before reuse."
    elif result.decision == "block":
        result.decision = "quarantine"
    return result


def invalid_classifier_decision(*, source_kind: str, existing: RiskDecision | None = None) -> RiskDecision:
    levels = {
        "tool_output_text": "medium",
        "shell_command": "high",
        "tool_input": "high",
        "mcp_output": "high",
        "browser_output": "high",
        "personal_memory_promotion": "high",
        "startup_injection": "critical",
        "graph_patch": "high",
    }
    result = existing or RiskDecision()
    if result.decision != "block":
        result.decision = "quarantine"
    result.risk_level = result.risk_level if result.risk_level == "critical" else levels.get(source_kind, "medium")
    result.injection_policy = "quarantine"
    result.memory_action = "quarantine"
    result.impact = "Classifier returned invalid structured output; source content may have influenced or broken the safety classifier."
    result.reason = "Classifier output was not valid JSON or did not match the risk schema."
    result.confidence = max(result.confidence, 0.85)
    _add(result, category="classifier_invalid_output", flag="classifier_schema_violation")
    return result


def generate_payload_marker() -> str:
    return f"UNTRUSTED_PAYLOAD_{secrets.token_hex(8)}"


def payload_contains_marker(payload: str, marker: str) -> bool:
    return marker in payload


def validate_classifier_json(value: Any) -> RiskDecision:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return invalid_classifier_decision(source_kind="classifier_output")
    if not isinstance(value, dict):
        return invalid_classifier_decision(source_kind="classifier_output")
    try:
        decision = str(value["decision"])
        risk_level = str(value["risk_level"])
        sensitivity = str(value["sensitivity"])
        injection_policy = str(value["injection_policy"])
        memory_action = str(value["memory_action"])
        impact = str(value["impact"]).strip()
        reason = str(value["reason"]).strip()
        confidence = float(value["confidence"])
    except (KeyError, TypeError, ValueError):
        return invalid_classifier_decision(source_kind="classifier_output")
    if (
        decision not in VALID_DECISIONS
        or risk_level not in VALID_RISK_LEVELS
        or sensitivity not in VALID_SENSITIVITY
        or injection_policy not in VALID_INJECTION_POLICIES
        or memory_action not in VALID_MEMORY_ACTIONS
        or not impact
        or not reason
        or not (0 <= confidence <= 1)
    ):
        return invalid_classifier_decision(source_kind="classifier_output")
    categories = value.get("categories") if isinstance(value.get("categories"), list) else []
    flags = value.get("poisoning_flags") if isinstance(value.get("poisoning_flags"), list) else []
    return RiskDecision(
        decision=decision,
        risk_level=risk_level,
        sensitivity=sensitivity,
        categories=[str(item) for item in categories],
        poisoning_flags=[str(item) for item in flags],
        injection_policy=injection_policy,
        memory_action=memory_action,
        impact=impact,
        reason=reason,
        confidence=confidence,
    )


def merge_decisions(deterministic: RiskDecision, classifier: RiskDecision) -> RiskDecision:
    result = RiskDecision(**deterministic.__dict__)
    order_decision = {"allow": 0, "warn": 1, "quarantine": 2, "block": 3}
    order_risk = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    if deterministic.should_block and not is_non_overridable_block(deterministic) and order_decision[classifier.decision] < order_decision[deterministic.decision]:
        result.decision = classifier.decision
        if result.approval_state == "required":
            result.approval_state = ""
            result.approval_token = ""
        result.injection_policy = classifier.injection_policy
        result.memory_action = classifier.memory_action
        result.impact = classifier.impact
        result.reason = classifier.reason
        result.confidence = classifier.confidence
    if order_decision[classifier.decision] > order_decision[result.decision]:
        result.decision = classifier.decision
    if order_risk[classifier.risk_level] > order_risk[result.risk_level]:
        result.risk_level = classifier.risk_level
    if classifier.sensitivity in {"private", "secret"}:
        result.sensitivity = classifier.sensitivity
    if classifier.injection_policy in {"never_auto", "quarantine"}:
        result.injection_policy = classifier.injection_policy
    if classifier.memory_action in {"reference_only", "quarantine", "drop_from_memory"}:
        result.memory_action = classifier.memory_action
    for category in classifier.categories:
        if category not in result.categories:
            result.categories.append(category)
    for flag in classifier.poisoning_flags:
        if flag not in result.poisoning_flags:
            result.poisoning_flags.append(flag)
    if classifier.confidence >= result.confidence:
        result.impact = classifier.impact
        result.reason = classifier.reason
        result.confidence = classifier.confidence
    return result


def is_hard_block(decision: RiskDecision) -> bool:
    if decision.risk_level == "critical":
        return True
    flags = set(decision.poisoning_flags) | set(decision.deterministic_flags) | set(decision.categories)
    return bool(flags & HARD_BLOCK_FLAGS)


def is_non_overridable_block(decision: RiskDecision) -> bool:
    if decision.risk_level == "critical":
        return True
    flags = set(decision.poisoning_flags) | set(decision.deterministic_flags) | set(decision.categories)
    return bool(flags & NON_OVERRIDABLE_HARD_BLOCK_FLAGS)
