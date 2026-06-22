from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from ..infrastructure.config import MEMORY_DIR, json_dumps, safe_slug, utc_now
from .classifier import deterministic_classifier
from ..infrastructure.db import connect
from .risk import record_risk_event, scan_text


PERSONAL_ROOT = MEMORY_DIR / "personal"
PERSONAL_PROPOSAL_ROOT = MEMORY_DIR / "personal-proposals"


PERSONAL_TEMPLATES: dict[str, str] = {
    "README.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 1.0
source_kind: manual
last_reviewed_at:
evidence: []
---

# Personal Operating Memory

This folder contains human-readable, cross-project memory for agent behavior, user preferences, engineering preferences, tools, and boundaries.

Rules:

- Keep entries short and durable.
- Prefer explicit user instructions over inferred patterns.
- Do not store secrets here.
- Mark sensitive or unverified items as `on_demand` or `never_auto`.
- Every non-manual claim should point to evidence.
""",
    "user/profile.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.5
source_kind: manual
last_reviewed_at:
evidence: []
---

# User Profile

## Explicit Facts

- TBD

## Observed Patterns

- TBD

## Avoid

- Do not infer personal traits without explicit evidence.
""",
    "user/communication.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 0.8
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Communication

## Do

- Prefer German when the user writes German.
- Be direct, pragmatic, and technically concrete.
- Keep status updates concise.

## Avoid

- Avoid cheerleading and vague reassurance.
- Avoid hiding uncertainty.
""",
    "user/working-style.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.6
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Working Style

## Do

- Prefer implementation after a clear plan when the task is actionable.
- Preserve auditability and reproducibility.

## Ask Before

- Ask before destructive changes or broad unrelated refactors.
""",
    "user/preferences.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.5
source_kind: manual
last_reviewed_at:
evidence: []
---

# Preferences

## Explicit Instructions

- TBD

## Candidate Preferences

- TBD
""",
    "agent/behavior.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 0.8
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Agent Behavior

## Do

- Act as a pragmatic senior engineer.
- Read the codebase before changing behavior.
- Prefer deterministic tools and inspectable artifacts.
- Keep large raw outputs out of summaries; use references.

## Avoid

- Do not treat derived memory as ground truth without evidence.
""",
    "agent/operating-principles.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 0.8
source_kind: manual
last_reviewed_at:
evidence: []
---

# Operating Principles

## Do

- Preserve provenance for derived memories.
- Keep memory layers scoped: raw, episodic, semantic, procedural, personal.
- Use low-risk startup context and retrieve the rest on demand.
""",
    "agent/escalation.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 0.8
source_kind: manual
last_reviewed_at:
evidence: []
---

# Escalation

## Ask Before

- Destructive filesystem or git operations.
- Any action that could expose secrets.
- Promotion of sensitive or unverified personal memory to startup context.
""",
    "engineering/architecture.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 0.7
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Architecture Preferences

## Do

- Prefer clear boundaries and explicit contracts.
- Treat hexagonal architecture / hexagonale Architektur and DDD compatibility as positive signals when they fit the codebase.
- Prefer auditable state machines for risky workflows.

## Avoid

- Avoid direct uncontrolled writes to production-like state.
""",
    "engineering/coding-style.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.6
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Coding Style

## Do

- Follow existing repository patterns.
- Keep changes scoped.
- Prefer typed/structured data over ad hoc string parsing.
""",
    "engineering/testing.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 0.8
source_kind: manual
last_reviewed_at:
evidence: []
---

# Testing

## Do

- Scale tests with risk and blast radius.
- Add unit tests for schema and parser behavior.
- Add end-to-end tests for critical memory flows.
""",
    "engineering/review.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.7
source_kind: manual
last_reviewed_at:
evidence: []
---

# Review

## Do

- Lead with risks, bugs, and regressions.
- Include file/line references when reviewing code.
""",
    "tools/preferred-tools.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.7
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Preferred Tools

## Do

- Prefer `rg` for search.
- Prefer existing local scripts over reimplementation.
- Prefer inspectable CLI flows for agent-memory.
""",
    "tools/runner-preferences.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: on_demand
confidence: 0.7
source_kind: observed_pattern
last_reviewed_at:
evidence: []
---

# Runner Preferences

## Do

- Use the same runner family for dream processing when feasible: Codex for Codex sessions, Claude for Claude sessions, Cursor for Cursor sessions.
- Keep dream runners isolated from hooks, skills, and tools where possible.
""",
    "boundaries/privacy.md": """---
memory_kind: personal_operating
scope: global
sensitivity: private
injection_policy: never_auto
confidence: 1.0
source_kind: manual
last_reviewed_at:
evidence: []
---

# Privacy

## Rules

- Do not store secrets in personal memory.
- Do not automatically inject private or secret personal memory.
- Treat personal assumptions as claims unless explicitly confirmed.
""",
    "boundaries/do-not-assume.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 1.0
source_kind: manual
last_reviewed_at:
evidence: []
---

# Do Not Assume

## Rules

- Do not infer personal traits, diagnoses, motives, or sensitive attributes without explicit user confirmation.
- Do not convert repeated behavior into a hard preference without review.
""",
    "boundaries/requires-confirmation.md": """---
memory_kind: personal_operating
scope: global
sensitivity: normal
injection_policy: startup_safe
confidence: 1.0
source_kind: manual
last_reviewed_at:
evidence: []
---

# Requires Confirmation

## Rules

- Confirm before promoting sensitive memory.
- Confirm before changing injection policy to `startup_safe`.
- Confirm before deleting or rewriting user-edited personal memory.
""",
}


def parse_frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    meta: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith("  "):
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"')
    return meta


def personal_files() -> list[Path]:
    if not PERSONAL_ROOT.exists():
        return []
    return sorted(path for path in PERSONAL_ROOT.rglob("*.md") if path.is_file())


def proposal_id_for(target: str, text: str) -> str:
    digest = hashlib.sha256(f"{target}\n{text}".encode("utf-8")).hexdigest()[:12]
    return f"pm_{digest}"


def proposal_path(proposal_id: str) -> Path:
    return PERSONAL_PROPOSAL_ROOT / f"{safe_slug(proposal_id)}.md"


def parse_proposal(path: Path) -> tuple[dict[str, str], str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, str] = {}
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end >= 0:
            for line in text[4:end].splitlines():
                if ":" not in line or line.startswith("  "):
                    continue
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip('"')
            text = text[end + len("\n---") :].lstrip()
    return meta, text


def cmd_personal_init(args: argparse.Namespace) -> int:
    created = 0
    skipped = 0
    now = utc_now()
    for rel, template in PERSONAL_TEMPLATES.items():
        path = PERSONAL_ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and not args.overwrite:
            skipped += 1
            continue
        text = template.replace("last_reviewed_at:\n", f"last_reviewed_at: {now}\n")
        path.write_text(text, encoding="utf-8")
        created += 1
    print(f"personal memory root: {PERSONAL_ROOT}")
    print(f"created: {created}")
    print(f"skipped: {skipped}")
    return 0


def cmd_personal_list(args: argparse.Namespace) -> int:
    rows = []
    for path in personal_files():
        meta = parse_frontmatter(path)
        if args.startup_safe and meta.get("injection_policy") != "startup_safe":
            continue
        rows.append((path.relative_to(PERSONAL_ROOT), meta))
    if not rows:
        print("No personal memory files found. Run: agent-memory personal init")
        return 0
    for rel, meta in rows:
        print(
            f"{rel} policy={meta.get('injection_policy', '-')} "
            f"sensitivity={meta.get('sensitivity', '-')} confidence={meta.get('confidence', '-')}"
        )
    return 0


def cmd_personal_propose(args: argparse.Namespace) -> int:
    text = args.text.strip()
    if not text:
        print("proposal text is required")
        return 1
    target = args.path.strip().strip("/")
    if not target.endswith(".md"):
        target += ".md"
    proposal_id = proposal_id_for(target, text)
    path = proposal_path(proposal_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    risk_decision = scan_text(text, source_kind="personal_memory_promotion")
    conn = connect()
    with conn:
        classified = deterministic_classifier(
            conn,
            stage="personal_memory_promotion",
            source_kind="personal_memory_promotion",
            payload=text,
            deterministic=risk_decision,
            source_ref=proposal_id,
            runner="auto",
        )
        risk_decision = classified.decision
        if risk_decision.is_risky:
            record_risk_event(
                conn,
                risk_decision,
                source_kind="personal_memory_promotion",
                source_ref=proposal_id,
                status="quarantined" if risk_decision.decision == "quarantine" else "warned",
                classifier_run_id=classified.run_id,
                evidence=[{"source_kind": "personal_memory_promotion", "source_ref": proposal_id, "field": "proposal_text", "quote": risk_decision.preview}],
            )
    status = "quarantined" if risk_decision.decision == "quarantine" else "proposed"
    injection_policy = args.injection_policy
    sensitivity = args.sensitivity
    if risk_decision.decision == "quarantine" or risk_decision.sensitivity == "secret":
        injection_policy = "never_auto"
        sensitivity = "secret" if risk_decision.sensitivity == "secret" else sensitivity
    metadata = {
        "proposal_id": proposal_id,
        "target_path": target,
        "created_at": utc_now(),
        "status": status,
        "source_kind": args.source_kind,
        "confidence": str(args.confidence),
        "sensitivity": sensitivity,
        "injection_policy": injection_policy,
        "risk_level": risk_decision.risk_level,
        "risk_categories": json_dumps(risk_decision.categories),
        "classifier_run_id": classified.run_id,
        "evidence": json_dumps({"session_id": args.session, "note": args.note} if args.session or args.note else {}),
    }
    frontmatter = "---\n" + "\n".join(f"{key}: {value}" for key, value in metadata.items()) + "\n---\n\n"
    body = f"# Personal Memory Proposal\n\n## Target\n\n`{target}`\n\n## Proposed Text\n\n{text}\n"
    path.write_text(frontmatter + body, encoding="utf-8")
    print(f"proposal: {proposal_id}")
    print(f"path: {path.relative_to(MEMORY_DIR)}")
    return 0


def cmd_personal_proposals(args: argparse.Namespace) -> int:
    rows = sorted(PERSONAL_PROPOSAL_ROOT.glob("*.md")) if PERSONAL_PROPOSAL_ROOT.exists() else []
    if not rows:
        print("No personal memory proposals.")
        return 0
    for path in rows:
        meta, body = parse_proposal(path)
        if args.status and meta.get("status") != args.status:
            continue
        preview = " ".join(body.split())[:160]
        print(f"{meta.get('proposal_id', path.stem)} status={meta.get('status', '-')} target={meta.get('target_path', '-')}")
        print(f"  {preview}")
    return 0


def proposal_text_from_body(body: str) -> str:
    marker = "## Proposed Text"
    if marker not in body:
        return body.strip()
    return body.split(marker, 1)[1].strip()


def cmd_personal_accept(args: argparse.Namespace) -> int:
    path = proposal_path(args.proposal_id)
    if not path.exists():
        print(f"proposal not found: {args.proposal_id}")
        return 1
    meta, body = parse_proposal(path)
    if meta.get("status") == "quarantined" and not args.force:
        print(f"proposal is quarantined; inspect risk metadata first or use --force: {args.proposal_id}")
        return 1
    if meta.get("status") == "accepted" and not args.force:
        print(f"proposal already accepted: {args.proposal_id}")
        return 1
    target = resolve_personal_path(meta.get("target_path") or "")
    if not target.exists():
        print(f"target personal memory file not found: {target}")
        return 1
    proposal_text = proposal_text_from_body(body)
    existing = target.read_text(encoding="utf-8", errors="replace")
    block = (
        f"\n\n## Accepted Memory {utc_now()}\n\n"
        f"Source proposal: `{meta.get('proposal_id', args.proposal_id)}`\n\n"
        f"{proposal_text}\n"
    )
    if proposal_text in existing and not args.force:
        print("target already contains proposed text")
        return 1
    target.write_text(existing.rstrip() + block, encoding="utf-8")
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"status: [^\n]+", "status: accepted", raw, count=1)
    raw = re.sub(r"accepted_at: [^\n]*", f"accepted_at: {utc_now()}", raw, count=1) if "accepted_at:" in raw else raw.replace("---\n\n", f"accepted_at: {utc_now()}\n---\n\n", 1)
    path.write_text(raw, encoding="utf-8")
    print(f"accepted: {args.proposal_id}")
    print(f"updated: {target.relative_to(PERSONAL_ROOT)}")
    return 0


def resolve_personal_path(selector: str) -> Path:
    value = selector.strip().strip("/")
    if not value.endswith(".md"):
        value += ".md"
    path = (PERSONAL_ROOT / value).resolve()
    root = PERSONAL_ROOT.resolve()
    if root not in path.parents and path != root:
        raise ValueError(f"path escapes personal memory root: {selector}")
    return path


def cmd_personal_show(args: argparse.Namespace) -> int:
    path = resolve_personal_path(args.path)
    if not path.exists():
        print(f"not found: {path}")
        return 1
    print(path.read_text(encoding="utf-8", errors="replace"))
    return 0


def cmd_personal_audit(args: argparse.Namespace) -> int:
    failures = 0
    required = {"memory_kind", "scope", "sensitivity", "injection_policy", "confidence", "source_kind"}
    allowed_policies = {"startup_safe", "on_demand", "never_auto"}
    allowed_sensitivity = {"normal", "private", "secret"}
    for path in personal_files():
        rel = path.relative_to(PERSONAL_ROOT)
        meta = parse_frontmatter(path)
        missing = sorted(required - set(meta))
        if missing:
            failures += 1
            print(f"bad {rel}: missing {', '.join(missing)}")
            continue
        if meta.get("injection_policy") not in allowed_policies:
            failures += 1
            print(f"bad {rel}: invalid injection_policy={meta.get('injection_policy')}")
        if meta.get("sensitivity") not in allowed_sensitivity:
            failures += 1
            print(f"bad {rel}: invalid sensitivity={meta.get('sensitivity')}")
        if meta.get("injection_policy") == "startup_safe" and meta.get("sensitivity") != "normal":
            failures += 1
            print(f"bad {rel}: startup_safe requires sensitivity=normal")
    if failures:
        return 1
    print(f"ok personal memory files: {len(personal_files())}")
    return 0


def startup_safe_personal_context(max_chars: int = 4000) -> str:
    parts: list[str] = []
    for path in personal_files():
        meta = parse_frontmatter(path)
        if meta.get("injection_policy") != "startup_safe" or meta.get("sensitivity") != "normal":
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        body = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S).strip()
        if body:
            parts.append(f"<personal_memory path=\"{path.relative_to(PERSONAL_ROOT)}\">\n{body}\n</personal_memory>")
        if sum(len(item) for item in parts) >= max_chars:
            break
    return "\n\n".join(parts)[:max_chars]
