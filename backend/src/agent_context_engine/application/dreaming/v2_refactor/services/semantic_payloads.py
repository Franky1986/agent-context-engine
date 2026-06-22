"""Pure semantic payload helpers extracted from the legacy v2 orchestration layer."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..repositories import DreamV2Repository

__all__ = [
    "KNOWN_ENTITY_TYPES",
    "KNOWN_RELATION_TYPES",
    "SEMANTIC_SCHEMA_VERSION",
    "RECONCILIATION_SCHEMA_VERSION",
    "one_line_text",
    "load_reused_stage_json",
    "load_reused_stage_text",
    "remap_semantic_payload_for_rerun",
    "remap_reconciliation_payload_for_rerun",
    "apply_semantic_guardrails",
    "apply_reconciliation_guardrails",
    "validate_semantic_payload",
    "validate_reconciliation_payload",
    "validate_reconciliation_payload_with_context",
    "deterministic_semantic_payload",
    "deterministic_reconciliation_payload",
    "project_slug",
    "candidate_keys_for_reconciliation",
]

SIGNAL_STRENGTH_LEVELS = ("low", "medium", "high")
SIGNAL_RANK = {name: index for index, name in enumerate(SIGNAL_STRENGTH_LEVELS)}
ENTITY_MIN_SIGNAL = {
    "project": "low",
    "concept": "medium",
    "product": "medium",
    "feature": "medium",
    "organization": "medium",
    "person": "medium",
    "task": "medium",
    "issue": "high",
    "risk": "high",
    "preference": "high",
    "decision": "high",
    "policy": "high",
    "schema_proposal": "high",
}
RELATION_MIN_SIGNAL = {
    "belongs_to_project": "medium",
    "mentions_external_project": "medium",
    "discusses": "medium",
    "depends_on": "high",
    "decides": "high",
    "blocks": "high",
    "affects": "high",
    "supersedes": "high",
    "requests": "high",
    "resolves": "high",
    "schema_proposal": "high",
}

LOW_SIGNAL_GREETING_RE = re.compile(
    r"^(?:hi|hello|hey|hallo|moin|servus|yo|good morning|good evening|good afternoon|thanks|thank you|ok|okay|cool|nice|super)[!. ]*$",
    flags=re.IGNORECASE,
)
SUBSTANTIVE_REQUEST_RE = re.compile(
    r"\b("
    r"fix|build|create|debug|implement|review|refactor|help|problem|error|test|plan|write|change|explain|why|how|"
    r"mach|baue|erstelle|debugge|prüfe|teste|refactor|ändere|erkläre|warum|wie"
    r")\b",
    flags=re.IGNORECASE,
)
TECHNICAL_SIGNAL_RE = re.compile(r"(`[^`]+`|[/\\\\]|[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}|\b(?:repo|project|module|file|cli|api|sql|json)\b)", flags=re.IGNORECASE)


KNOWN_ENTITY_TYPES = {
    "project",
    "person",
    "organization",
    "product",
    "feature",
    "decision",
    "issue",
    "risk",
    "preference",
    "concept",
    "task",
    "policy",
    "schema_proposal",
}

KNOWN_RELATION_TYPES = {
    "discusses",
    "depends_on",
    "decides",
    "blocks",
    "affects",
    "belongs_to_project",
    "supersedes",
    "requests",
    "resolves",
    "mentions_external_project",
    "schema_proposal",
}

SEMANTIC_SCHEMA_VERSION = "semantic_proposals.v2"
RECONCILIATION_SCHEMA_VERSION = "reconciliation_decisions.v2"

REFERENTIAL_POSSESSIVES = {
    "his",
    "her",
    "their",
    "its",
    "my",
    "our",
    "your",
    "sein",
    "seine",
    "seiner",
    "seinem",
    "seinen",
    "ihr",
    "ihre",
    "ihrer",
    "ihrem",
    "ihren",
    "deren",
    "dessen",
}

GENERIC_PERSON_ROLE_TERMS = {
    "brother",
    "daughter",
    "father",
    "friend",
    "girlfriend",
    "granddaughter",
    "grandfather",
    "grandma",
    "grandmother",
    "grandpa",
    "grandson",
    "mother",
    "partner",
    "schwester",
    "sohn",
    "tochter",
    "vater",
    "wife",
    "mutter",
    "mann",
    "frau",
    "bruder",
    "freund",
    "freundin",
    "kollege",
    "kollegin",
    "sister",
    "son",
    "husband",
}


def one_line_text(value: str | None, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def load_reused_stage_json(
    conn,
    prior_dream_run_id: str | None,
    stage_name: str,
    *,
    root_fn,
    read_text_fn,
    json_loads_fn=json.loads,
) -> dict[str, Any] | None:
    if not prior_dream_run_id:
        return None
    row = DreamV2Repository(conn).fetch_succeeded_stage_run(prior_dream_run_id, stage_name)
    if row is None or not row["parsed_output_path"]:
        return None
    path = root_fn() / row["parsed_output_path"]
    if not path.exists() or not path.is_file():
        return None
    try:
        payload = json_loads_fn(read_text_fn(path))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def load_reused_stage_text(
    conn,
    prior_dream_run_id: str | None,
    stage_name: str,
    *,
    root_fn,
    read_text_fn,
) -> str | None:
    if not prior_dream_run_id:
        return None
    row = DreamV2Repository(conn).fetch_succeeded_stage_run(prior_dream_run_id, stage_name)
    if row is None or not row["parsed_output_path"]:
        return None
    path = root_fn() / row["parsed_output_path"]
    if not path.exists() or not path.is_file():
        return None
    text = read_text_fn(path).strip()
    return text or None


def _remap_payload(payload: dict[str, Any], *, safe_slug_fn, json_dumps_fn) -> dict[str, Any]:
    return json.loads(json_dumps_fn(payload))


def remap_semantic_payload_for_rerun(
    payload: dict[str, Any],
    *,
    dream_run_id: str,
    session_id: str,
    event_from: int,
    event_to: int,
    safe_slug_fn,
    json_dumps_fn,
) -> dict[str, Any]:
    suffix = safe_slug_fn(dream_run_id)[-16:]
    remapped = _remap_payload(payload, safe_slug_fn=safe_slug_fn, json_dumps_fn=json_dumps_fn)
    id_map: dict[str, str] = {}
    for collection in ("entities", "relations", "schema_proposals"):
        for item in remapped.get(collection, []) if isinstance(remapped.get(collection), list) else []:
            old_id = str(item.get("proposal_id") or "")
            if old_id:
                new_id = f"{old_id}__rerun_{suffix}"
                id_map[old_id] = new_id
                item["proposal_id"] = new_id
    for relation in remapped.get("relations", []) if isinstance(remapped.get("relations"), list) else []:
        if relation.get("source_ref") in id_map:
            relation["source_ref"] = id_map[relation["source_ref"]]
        if relation.get("target_ref") in id_map:
            relation["target_ref"] = id_map[relation["target_ref"]]
    remapped["dream_run_id"] = dream_run_id
    remapped["session_id"] = session_id
    remapped["source_event_range"] = {"start_seq": event_from, "end_seq": event_to}
    remapped["_rerun_id_map"] = id_map
    return remapped


def remap_reconciliation_payload_for_rerun(
    payload: dict[str, Any],
    *,
    dream_run_id: str,
    session_id: str,
    proposal_id_map: dict[str, str],
    safe_slug_fn,
    json_dumps_fn,
) -> dict[str, Any]:
    suffix = safe_slug_fn(dream_run_id)[-16:]
    remapped = _remap_payload(payload, safe_slug_fn=safe_slug_fn, json_dumps_fn=json_dumps_fn)
    for decision in remapped.get("decisions", []) if isinstance(remapped.get("decisions"), list) else []:
        old_decision_id = str(decision.get("decision_id") or "")
        if old_decision_id:
            decision["decision_id"] = f"{old_decision_id}__rerun_{suffix}"
        old_proposal_id = str(decision.get("proposal_id") or "")
        if old_proposal_id in proposal_id_map:
            decision["proposal_id"] = proposal_id_map[old_proposal_id]
    remapped["dream_run_id"] = dream_run_id
    remapped["session_id"] = session_id
    return remapped


def _schema_growth_index(payload: dict[str, Any]) -> dict[str, set[str]]:
    index = {"entity_type": set(), "relation_type": set()}
    proposals = payload.get("schema_proposals") if isinstance(payload.get("schema_proposals"), list) else []
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        kind = str(proposal.get("kind") or "")
        proposed_name = str(proposal.get("proposed_name") or "")
        if kind in index and proposed_name:
            index[kind].add(proposed_name)
    return index


def _requires_schema_review(kind: str, typ: Any, schema_growth: dict[str, set[str]]) -> bool:
    value = str(typ or "")
    if not value:
        return False
    if kind == "entity_type":
        return value not in KNOWN_ENTITY_TYPES and value in schema_growth["entity_type"]
    if kind == "relation_type":
        return value not in KNOWN_RELATION_TYPES and value in schema_growth["relation_type"]
    return False


def _underspecified_entity_review_reason(entity: dict[str, Any]) -> str | None:
    entity_type = str(entity.get("type") or "").strip().lower()
    if entity_type != "person":
        return None
    name = " ".join(str(entity.get("name") or "").strip().split())
    if not name:
        return None
    tokens = [token for token in re.findall(r"[A-Za-zÄÖÜäöüß]+", name.casefold()) if token]
    if len(tokens) < 2:
        return None
    if tokens[0] not in REFERENTIAL_POSSESSIVES:
        return None
    if any(token not in GENERIC_PERSON_ROLE_TERMS for token in tokens[1:]):
        return None
    return (
        "Referential person description is too underspecified for canonical persistence; "
        "require an explicit name or a stable title."
    )


def _event_text_chunks(event: dict[str, Any] | Any) -> list[str]:
    chunks: list[str] = []
    for key in ("prompt", "response", "content", "text", "message", "summary", "assistant_response"):
        try:
            value = event[key]
        except Exception:  # noqa: BLE001
            value = getattr(event, key, None)
        if isinstance(value, str):
            normalized = re.sub(r"\s+", " ", value).strip()
            if normalized and normalized not in chunks:
                chunks.append(normalized)
    return chunks


def _event_seq(event: dict[str, Any] | Any) -> int | None:
    try:
        value = event["seq"]
    except Exception:  # noqa: BLE001
        value = getattr(event, "seq", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _event_text_index(events: list[dict[str, Any]] | list[Any]) -> tuple[dict[int, str], str]:
    by_seq: dict[int, str] = {}
    all_chunks: list[str] = []
    for event in events:
        chunks = _event_text_chunks(event)
        if not chunks:
            continue
        seq = _event_seq(event)
        combined = " ".join(chunks)
        if seq is not None:
            by_seq[seq] = combined
        all_chunks.extend(chunks)
    conversation_text = " ".join(all_chunks)
    return by_seq, conversation_text


def _grounded_quote(candidate: str, event_text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", candidate or "").strip()
    if not normalized:
        return None
    if normalized in event_text:
        return normalized
    lowered = normalized.casefold()
    haystack = event_text.casefold()
    if lowered in haystack:
        start = haystack.index(lowered)
        return event_text[start : start + len(normalized)]
    return None


def _grounded_evidence_for_item(
    item: dict[str, Any],
    event_text_by_seq: dict[int, str],
    conversation_text: str,
) -> list[dict[str, Any]]:
    grounded: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for evidence in item.get("evidence", []) if isinstance(item.get("evidence"), list) else []:
        if not isinstance(evidence, dict):
            continue
        seq = evidence.get("event_seq")
        try:
            seq_int = int(seq) if seq is not None else None
        except (TypeError, ValueError):
            seq_int = None
        source_text = event_text_by_seq.get(seq_int) if seq_int is not None else None
        search_spaces = [space for space in [source_text, conversation_text] if isinstance(space, str) and space]
        quote: str | None = None
        for search_space in search_spaces:
            quote = _grounded_quote(str(evidence.get("quote") or ""), search_space)
            if quote:
                break
        if quote:
            identity = (seq_int, quote)
            if identity not in seen:
                grounded.append({**evidence, "event_seq": seq_int, "quote": quote})
                seen.add(identity)
            continue
        fallbacks = [str(item.get("name") or "").strip(), *(str(alias).strip() for alias in item.get("aliases", []) or [])]
        for fallback in fallbacks:
            for search_space in search_spaces:
                quote = _grounded_quote(fallback, search_space)
                if not quote:
                    continue
                identity = (seq_int, quote)
                if identity in seen:
                    break
                grounded.append(
                    {
                        **evidence,
                        "event_seq": seq_int,
                        "quote": quote,
                    }
                )
                seen.add(identity)
                break
            if quote:
                break
    return grounded


def _is_low_signal_window(events: list[dict[str, Any]] | list[Any]) -> bool:
    user_prompts: list[str] = []
    all_chunks: list[str] = []
    for event in events:
        chunks = _event_text_chunks(event)
        all_chunks.extend(chunks)
        try:
            prompt = event["prompt"]
        except Exception:  # noqa: BLE001
            prompt = getattr(event, "prompt", None)
        if isinstance(prompt, str) and prompt.strip():
            user_prompts.append(re.sub(r"\s+", " ", prompt).strip())
    if not user_prompts:
        return False
    if any(SUBSTANTIVE_REQUEST_RE.search(prompt) for prompt in user_prompts):
        return False
    if any(len(prompt) > 24 and not LOW_SIGNAL_GREETING_RE.match(prompt) for prompt in user_prompts):
        return False
    if not all(LOW_SIGNAL_GREETING_RE.match(prompt) for prompt in user_prompts):
        return False
    conversation_text = " ".join(all_chunks)
    if TECHNICAL_SIGNAL_RE.search(" ".join(user_prompts)):
        return False
    return len(conversation_text) < 500


def classify_signal_strength(events: list[dict[str, Any]] | list[Any]) -> str:
    if _is_low_signal_window(events):
        return "low"
    user_prompts: list[str] = []
    all_chunks: list[str] = []
    substantive_hits = 0
    technical_hits = 0
    for event in events:
        chunks = _event_text_chunks(event)
        all_chunks.extend(chunks)
        try:
            prompt = event["prompt"]
        except Exception:  # noqa: BLE001
            prompt = getattr(event, "prompt", None)
        if isinstance(prompt, str) and prompt.strip():
            normalized = re.sub(r"\s+", " ", prompt).strip()
            user_prompts.append(normalized)
            if SUBSTANTIVE_REQUEST_RE.search(normalized):
                substantive_hits += 1
            if TECHNICAL_SIGNAL_RE.search(normalized):
                technical_hits += 1
    conversation_text = " ".join(all_chunks)
    score = 0
    if substantive_hits:
        score += 1
    if technical_hits:
        score += 1
    if len(user_prompts) >= 2:
        score += 1
    if len(conversation_text) >= 700:
        score += 1
    return "high" if score >= 3 else "medium"


def _required_signal_for_entity(entity_type: str) -> str:
    return ENTITY_MIN_SIGNAL.get(entity_type, "high")


def _required_signal_for_relation(relation_type: str) -> str:
    return RELATION_MIN_SIGNAL.get(relation_type, "high")


def _signal_is_sufficient(signal_strength: str, required_signal: str) -> bool:
    return SIGNAL_RANK.get(signal_strength, 1) >= SIGNAL_RANK.get(required_signal, 2)


def apply_semantic_guardrails(payload: dict[str, Any], *, events: list[dict[str, Any]] | list[Any] | None = None) -> dict[str, Any]:
    events = events or []
    signal_strength = classify_signal_strength(events)
    low_signal_window = signal_strength == "low"
    event_text_by_seq, conversation_text = _event_text_index(events)
    entities = payload.get("entities") if isinstance(payload.get("entities"), list) else []
    kept_entities: list[dict[str, Any]] = []
    kept_entity_ids: set[str] = set()
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity = dict(entity)
        grounded_evidence = _grounded_evidence_for_item(entity, event_text_by_seq, conversation_text)
        entity_type = str(entity.get("type") or "").strip().lower()
        required_signal = _required_signal_for_entity(entity_type)
        if not grounded_evidence:
            if low_signal_window or entity_type in {"task", "preference", "decision", "issue", "risk", "policy"}:
                continue
            entity["review_required"] = True
            entity["review_reason"] = "Semantic proposal lacks evidence grounded in the actual conversation window."
        else:
            entity["evidence"] = grounded_evidence
        if not _signal_is_sufficient(signal_strength, required_signal):
            if signal_strength == "low" and entity_type != "project":
                continue
            entity["review_required"] = True
            entity["review_reason"] = (
                f"Signal strength `{signal_strength}` is below the minimum `{required_signal}` required for durable `{entity_type}` persistence."
            )
            if signal_strength == "low":
                entity["confidence"] = min(float(entity.get("confidence") or 0), 0.55)
        elif low_signal_window and entity_type == "project":
            entity["review_required"] = True
            entity["review_reason"] = "Low-signal greeting window; keep only as weak project hint pending review."
            entity["confidence"] = min(float(entity.get("confidence") or 0), 0.55)
        review_reason = _underspecified_entity_review_reason(entity)
        if review_reason:
            entity["review_required"] = True
            entity["review_reason"] = review_reason
        kept_entities.append(entity)
        if entity.get("proposal_id"):
            kept_entity_ids.add(str(entity["proposal_id"]))
    relations = payload.get("relations") if isinstance(payload.get("relations"), list) else []
    kept_relations: list[dict[str, Any]] = []
    if not low_signal_window:
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            relation = dict(relation)
            if str(relation.get("source_ref") or "") not in kept_entity_ids or str(relation.get("target_ref") or "") not in kept_entity_ids:
                continue
            grounded_evidence = _grounded_evidence_for_item(relation, event_text_by_seq, conversation_text)
            if not grounded_evidence:
                continue
            relation_type = str(relation.get("type") or "").strip().lower()
            required_signal = _required_signal_for_relation(relation_type)
            if not _signal_is_sufficient(signal_strength, required_signal):
                relation["review_required"] = True
                relation["review_reason"] = (
                    f"Signal strength `{signal_strength}` is below the minimum `{required_signal}` required for durable `{relation_type}` persistence."
                )
            relation["evidence"] = grounded_evidence
            kept_relations.append(relation)
    schema_proposals = payload.get("schema_proposals") if isinstance(payload.get("schema_proposals"), list) else []
    kept_schema_proposals: list[dict[str, Any]] = []
    if not low_signal_window:
        for proposal in schema_proposals:
            if not isinstance(proposal, dict):
                continue
            proposal = dict(proposal)
            grounded_evidence = _grounded_evidence_for_item(proposal, event_text_by_seq, conversation_text)
            if not grounded_evidence:
                continue
            proposal["evidence"] = grounded_evidence
            kept_schema_proposals.append(proposal)
    payload["entities"] = kept_entities
    payload["relations"] = kept_relations
    payload["schema_proposals"] = kept_schema_proposals
    payload["_low_signal_window"] = low_signal_window
    payload["_signal_strength"] = signal_strength
    return payload


def apply_reconciliation_guardrails(
    payload: dict[str, Any],
    *,
    semantic_payload: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(semantic_payload, dict):
        return payload
    proposal_index: dict[str, dict[str, Any]] = {}
    for collection in ("entities", "relations"):
        values = semantic_payload.get(collection) if isinstance(semantic_payload.get(collection), list) else []
        for item in values:
            if isinstance(item, dict) and item.get("proposal_id"):
                proposal_index[str(item["proposal_id"])] = item
    decisions = payload.get("decisions") if isinstance(payload.get("decisions"), list) else []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        proposal = proposal_index.get(str(decision.get("proposal_id") or ""))
        if not proposal:
            continue
        if proposal.get("review_required"):
            decision["action"] = "defer_for_review"
            decision["review_required"] = True
            decision["review_reason"] = proposal.get("review_reason") or "Proposal requires review before semantic persistence."
            decision["reason"] = decision["review_reason"]
            decision["human_summary"] = f"Defer semantic proposal {decision.get('proposal_id')} for review."
    return payload


def validate_semantic_payload(
    payload: Any,
    *,
    semantic_schema_version: str = SEMANTIC_SCHEMA_VERSION,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"ok": False, "errors": ["payload is not an object"]}
    if payload.get("schema_version") != semantic_schema_version:
        errors.append("schema_version mismatch")
    for key in ("entities", "relations", "schema_proposals"):
        if not isinstance(payload.get(key, []), list):
            errors.append(f"{key} must be a list")
    schema_growth = _schema_growth_index(payload)
    for proposal in payload.get("schema_proposals", []):
        if not isinstance(proposal, dict):
            errors.append("schema_proposal is not an object")
            continue
        if proposal.get("kind") not in {"entity_type", "relation_type"}:
            errors.append(f"schema_proposal unknown kind: {proposal.get('kind')}")
        if not proposal.get("proposal_id") or not proposal.get("proposed_name"):
            errors.append("schema_proposal missing proposal_id or proposed_name")
        if not proposal.get("reason"):
            errors.append(f"schema_proposal {proposal.get('proposal_id')} missing reason")
        if not proposal.get("evidence"):
            errors.append(f"schema_proposal {proposal.get('proposal_id')} missing evidence")
    for entity in payload.get("entities", []):
        if not isinstance(entity, dict):
            errors.append("entity is not an object")
            continue
        if entity.get("type") not in KNOWN_ENTITY_TYPES and not _requires_schema_review("entity_type", entity.get("type"), schema_growth):
            errors.append(f"unknown entity type: {entity.get('type')}")
        if entity.get("type") in {"file", "directory", "command", "clicommand", "tool"}:
            errors.append(f"operational entity rejected: {entity.get('type')}")
        if _requires_schema_review("entity_type", entity.get("type"), schema_growth) and not entity.get("review_required"):
            errors.append(f"entity {entity.get('proposal_id')} with new schema type must set review_required")
        if not entity.get("proposal_id") or not entity.get("name"):
            errors.append("entity missing proposal_id or name")
        if not entity.get("evidence"):
            errors.append(f"entity {entity.get('proposal_id')} missing evidence")
        underspecified_reason = _underspecified_entity_review_reason(entity)
        if underspecified_reason and not entity.get("review_required"):
            errors.append(f"entity {entity.get('proposal_id')} uses underspecified referential name without review_required")
    for relation in payload.get("relations", []):
        if not isinstance(relation, dict):
            errors.append("relation is not an object")
            continue
        if relation.get("type") not in KNOWN_RELATION_TYPES and not _requires_schema_review("relation_type", relation.get("type"), schema_growth):
            errors.append(f"unknown relation type: {relation.get('type')}")
        if _requires_schema_review("relation_type", relation.get("type"), schema_growth) and not relation.get("review_required"):
            errors.append(f"relation {relation.get('proposal_id')} with new schema type must set review_required")
        if not relation.get("proposal_id") or not relation.get("source_ref") or not relation.get("target_ref"):
            errors.append("relation missing proposal_id, source_ref or target_ref")
        if not relation.get("evidence"):
            errors.append(f"relation {relation.get('proposal_id')} missing evidence")
    return {"ok": not errors, "errors": errors}


def validate_reconciliation_payload(payload: Any) -> dict[str, Any]:
    return validate_reconciliation_payload_with_context(payload, semantic_payload=None)


def validate_reconciliation_payload_with_context(
    payload: Any,
    *,
    semantic_payload: dict[str, Any] | None,
    reconciliation_schema_version: str = RECONCILIATION_SCHEMA_VERSION,
) -> dict[str, Any]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"ok": False, "errors": ["payload is not an object"]}
    if payload.get("schema_version") != reconciliation_schema_version:
        errors.append("schema_version mismatch")
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        errors.append("decisions must be a list")
        decisions = []
    proposal_kinds: dict[str, str] = {}
    if isinstance(semantic_payload, dict):
        for entity in semantic_payload.get("entities", []) if isinstance(semantic_payload.get("entities"), list) else []:
            if isinstance(entity, dict) and entity.get("proposal_id"):
                proposal_kinds[str(entity["proposal_id"])] = "entity"
        for relation in semantic_payload.get("relations", []) if isinstance(semantic_payload.get("relations"), list) else []:
            if isinstance(relation, dict) and relation.get("proposal_id"):
                proposal_kinds[str(relation["proposal_id"])] = "relation"
    allowed = {"create_entity", "update_entity", "merge_entity", "create_relation", "update_relation", "reject", "defer_for_review", "propose_schema"}
    for decision in decisions:
        if not isinstance(decision, dict):
            errors.append("decision is not an object")
            continue
        if decision.get("action") not in allowed:
            errors.append(f"unknown action: {decision.get('action')}")
        if not decision.get("decision_id") or not decision.get("proposal_id"):
            errors.append("decision missing decision_id or proposal_id")
        if not decision.get("reason") or not decision.get("human_summary"):
            errors.append(f"decision {decision.get('decision_id')} missing reason or human_summary")
        proposal_id = str(decision.get("proposal_id") or "")
        if "<" in proposal_id or ">" in proposal_id:
            errors.append(f"decision {decision.get('decision_id')} uses placeholder proposal_id")
        if proposal_kinds and proposal_id not in proposal_kinds:
            errors.append(f"decision {decision.get('decision_id')} references unknown proposal_id: {proposal_id}")
            continue
        proposal_kind = proposal_kinds.get(proposal_id)
        action = str(decision.get("action") or "")
        if proposal_kind == "entity" and action in {"create_relation", "update_relation"}:
            errors.append(f"decision {decision.get('decision_id')} uses relation action for entity proposal")
        if proposal_kind == "relation" and action in {"create_entity", "update_entity", "merge_entity"}:
            errors.append(f"decision {decision.get('decision_id')} uses entity action for relation proposal")
    return {"ok": not errors, "errors": errors}


def _semantic_prompt_topic_from_events(events: list[dict[str, Any]] | list[Any]) -> tuple[str, int | None]:
    for event in reversed(events):
        prompt = str(event["prompt"] or "").strip()
        if prompt:
            return prompt, int(event["seq"])
    return "", None


def _entity_key(entity_type: str, name: str, *, safe_slug_fn) -> str:
    return safe_slug_fn(f"{entity_type}:{name.lower()}")[:180]


def _proposal_key(kind: str, typ: str, name: str, *, safe_slug_fn) -> str:
    return safe_slug_fn(f"{kind}:{typ}:{name.lower()}")[:180]


def deterministic_semantic_payload(
    session,
    events: list[dict[str, Any]] | list[Any],
    dream_markdown: str,
    *,
    dream_run_id: str,
    event_from: int,
    event_to: int,
    safe_slug_fn,
    semantic_schema_version: str = SEMANTIC_SCHEMA_VERSION,
) -> dict[str, Any]:
    prompt_text, prompt_seq = _semantic_prompt_topic_from_events(events)
    prompt_text = prompt_text or one_line_text(dream_markdown.splitlines()[0] if dream_markdown.strip() else "Session topic")
    prompt_text = one_line_text(prompt_text, 120)
    topic_match = re.search(r"\b(?:about|über)\s+([^\n,.!?;:]+)", prompt_text, flags=re.IGNORECASE)
    topic_name = one_line_text((topic_match.group(1) if topic_match else "").strip(" \"'`"), 80)
    evidence_seq = prompt_seq if prompt_seq is not None else event_from
    evidence_quote = prompt_text or one_line_text(dream_markdown, 160) or "Session content"
    task_proposal_id = f"entity-task-{safe_slug_fn(dream_run_id)[-8:]}"
    entities: list[dict[str, Any]] = [
        {
            "proposal_id": task_proposal_id,
            "type": "task",
            "name": prompt_text[:80] or "Session task",
            "aliases": [],
            "summary": one_line_text(f"Primary user request in this session: {prompt_text}" if prompt_text else "Primary user request in this session.", 160),
            "properties": {"fallback": "deterministic_semantic", "source": "prompt"},
            "confidence": 0.55,
            "evidence": [{"source": "conversation", "event_seq": evidence_seq, "quote": evidence_quote}],
            "review_required": False,
            "review_reason": None,
        }
    ]
    relations: list[dict[str, Any]] = []
    project_id = str(session["project_id"] or "").strip()
    if project_id:
        relations.append(
            {
                "proposal_id": f"relation-project-{safe_slug_fn(dream_run_id)[-8:]}",
                "type": "belongs_to_project",
                "source_ref": task_proposal_id,
                "target_ref": f"project:{safe_slug_fn(project_id)}",
                "summary": "The request belongs to the current project.",
                "properties": {"fallback": "deterministic_semantic"},
                "confidence": 0.7,
                "evidence": [{"source": "conversation", "event_seq": evidence_seq, "quote": evidence_quote}],
                "review_required": False,
                "review_reason": None,
            }
        )
    if topic_name and topic_name.lower() != prompt_text.lower():
        concept_proposal_id = f"entity-concept-{safe_slug_fn(dream_run_id)[-8:]}"
        entities.append(
            {
                "proposal_id": concept_proposal_id,
                "type": "concept",
                "name": topic_name[:80],
                "aliases": [],
                "summary": one_line_text(f"Topic explicitly referenced in the request: {topic_name}", 160),
                "properties": {"fallback": "deterministic_semantic", "source": "prompt_topic"},
                "confidence": 0.5,
                "evidence": [{"source": "conversation", "event_seq": evidence_seq, "quote": evidence_quote}],
                "review_required": False,
                "review_reason": None,
            }
        )
        relations.append(
            {
                "proposal_id": f"relation-topic-{safe_slug_fn(dream_run_id)[-8:]}",
                "type": "discusses",
                "source_ref": task_proposal_id,
                "target_ref": concept_proposal_id,
                "summary": "The request discusses the explicit topic from the prompt.",
                "properties": {"fallback": "deterministic_semantic"},
                "confidence": 0.5,
                "evidence": [{"source": "conversation", "event_seq": evidence_seq, "quote": evidence_quote}],
                "review_required": False,
                "review_reason": None,
            }
        )
    return {
        "schema_version": semantic_schema_version,
        "dream_run_id": dream_run_id,
        "session_id": str(session["session_id"]),
        "source_event_range": {"start_seq": event_from, "end_seq": event_to},
        "entities": entities,
        "relations": relations,
        "schema_proposals": [],
    }


def candidate_keys_for_reconciliation(candidates: dict[str, Any], proposal_id: str) -> list[str]:
    rows = candidates.get("candidates") if isinstance(candidates.get("candidates"), dict) else {}
    values = rows.get(proposal_id) if isinstance(rows, dict) else []
    if not isinstance(values, list):
        return []
    keys: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        key = str(value.get("entity_key") or value.get("key") or "").strip()
        if key and key not in keys:
            keys.append(key)
    return keys


def deterministic_reconciliation_payload(
    semantic_payload: dict[str, Any],
    candidates: dict[str, Any],
    *,
    dream_run_id: str,
    session_id: str,
    safe_slug_fn,
) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    for entity in semantic_payload.get("entities", []) if isinstance(semantic_payload.get("entities"), list) else []:
        if not isinstance(entity, dict):
            continue
        proposal_id = str(entity.get("proposal_id") or "").strip()
        if not proposal_id:
            continue
        candidate_keys = candidate_keys_for_reconciliation(candidates, proposal_id)
        review_required = bool(entity.get("review_required"))
        canonical_key = str(entity.get("canonical_key_candidate") or _entity_key(str(entity.get("type") or ""), str(entity.get("name") or ""), safe_slug_fn=safe_slug_fn)).strip()
        action = "defer_for_review" if review_required else ("update_entity" if candidate_keys else "create_entity")
        target_key = candidate_keys[0] if candidate_keys else canonical_key or None
        human_summary = (
            f"Defer semantic entity {proposal_id} for review."
            if review_required
            else (
                f"Reuse semantic entity {target_key} for {entity.get('name') or proposal_id}."
                if candidate_keys
                else f"Create semantic entity {entity.get('name') or proposal_id}."
            )
        )
        reason = (
            str(entity.get("review_reason") or "Proposal requires review before semantic persistence.")
            if review_required
            else (
                "Candidate reuse selected from deterministic semantic match results."
                if candidate_keys
                else "No reusable candidate was available; create the normalized semantic entity."
            )
        )
        decisions.append(
            {
                "decision_id": f"decision-{safe_slug_fn(proposal_id)}",
                "proposal_id": proposal_id,
                "action": action,
                "target_key": target_key,
                "candidate_keys": candidate_keys,
                "confidence": entity.get("confidence") or 0.75,
                "reason": reason,
                "human_summary": human_summary,
                "evidence": entity.get("evidence") or [],
                "review_required": review_required,
                "review_reason": entity.get("review_reason"),
                "write_patch": {
                    "type": entity.get("type"),
                    "canonical_key": canonical_key or None,
                    "name": entity.get("name"),
                    "aliases": entity.get("aliases") or [],
                    "summary": entity.get("summary"),
                    "properties": entity.get("properties") or {},
                },
            }
        )
    for relation in semantic_payload.get("relations", []) if isinstance(semantic_payload.get("relations"), list) else []:
        if not isinstance(relation, dict):
            continue
        proposal_id = str(relation.get("proposal_id") or "").strip()
        if not proposal_id:
            continue
        review_required = bool(relation.get("review_required"))
        target_key = str(
            relation.get("canonical_relation_key_candidate")
            or _proposal_key("relation", str(relation.get("type") or ""), proposal_id, safe_slug_fn=safe_slug_fn)
        ).strip()
        action = "defer_for_review" if review_required else "create_relation"
        human_summary = (
            f"Defer semantic relation {proposal_id} for review."
            if review_required
            else f"Create semantic relation {relation.get('type') or proposal_id}."
        )
        reason = (
            str(relation.get("review_reason") or "Relation requires review before semantic persistence.")
            if review_required
            else "Create the normalized semantic relation using the validated proposal endpoints."
        )
        decisions.append(
            {
                "decision_id": f"decision-{safe_slug_fn(proposal_id)}",
                "proposal_id": proposal_id,
                "action": action,
                "target_key": target_key or None,
                "candidate_keys": [],
                "confidence": relation.get("confidence") or 0.75,
                "reason": reason,
                "human_summary": human_summary,
                "evidence": relation.get("evidence") or [],
                "review_required": review_required,
                "review_reason": relation.get("review_reason"),
                "write_patch": {
                    "type": relation.get("type"),
                    "canonical_key": target_key or None,
                    "source_ref": relation.get("source_ref"),
                    "target_ref": relation.get("target_ref"),
                    "summary": relation.get("summary"),
                    "properties": relation.get("properties") or {},
                },
            }
        )
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "dream_run_id": dream_run_id,
        "session_id": session_id,
        "decisions": decisions,
    }


def project_slug(session, *, safe_slug_fn) -> str:
    return safe_slug_fn(session["project_id"] or "unknown")
