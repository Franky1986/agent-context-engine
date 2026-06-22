from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
import uuid
from pathlib import Path
from typing import Any

from ..ports.clock import Clock
from ..ports.filesystem import FileSystem
from ..ports.repositories.sqlite import SQLiteConnectionProvider
from .query_expansion import QueryExpansionResult, build_query_expansion, deterministic_query_expansion, query_expansion_payload
from .query_intent import QueryIntent, classify_query_intent, entity_type_weight_for_query, retrieval_profile_from_terms
from .classifier import deterministic_classifier
from .risk import record_risk_event, scan_text


class _DefaultClock(Clock):
    def utc_now(self) -> str:
        return _utc_now()


class _DefaultFileSystem(FileSystem):
    def exists(self, path: Path) -> bool:
        return path.exists()

    def read_text(self, path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def write_text(self, path: Path, value: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def read_bytes(self, path: Path) -> bytes:
        return path.read_bytes()

    def write_bytes(self, path: Path, value: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)


def _default_clock() -> Clock:
    return _DefaultClock()


def _default_file_system() -> FileSystem:
    return _DefaultFileSystem()


class _RequestDbProvider(SQLiteConnectionProvider):
    def connect(self, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        from ..adapters.sqlite.request_db import connect

        return connect(*args, **kwargs)


def _default_db_provider() -> SQLiteConnectionProvider:
    return _RequestDbProvider()


def _default_root() -> Path:
    from ..infrastructure.config import ROOT

    return ROOT


def _json_dumps(value: Any) -> str:
    from ..infrastructure.config import json_dumps

    return json_dumps(value)


def _safe_slug(value: str) -> str:
    from ..infrastructure.config import safe_slug

    return safe_slug(str(value))


def _utc_now() -> str:
    from ..infrastructure.config import utc_now

    return utc_now()


def _now() -> str:
    return _default_clock().utc_now()


MAX_CHUNK_CHARS = 3200
TOKEN_RE = re.compile(r"[\w./:@-]+")
ENTITY_LOOKUP_STOP_TERMS = {
    "a",
    "an",
    "and",
    "are",
    "der",
    "die",
    "das",
    "den",
    "dem",
    "des",
    "ein",
    "eine",
    "einer",
    "einem",
    "einen",
    "for",
    "für",
    "ist",
    "is",
    "the",
    "to",
    "und",
    "was",
    "welche",
    "welcher",
    "welches",
    "wurden",
    "wurde",
    "zu",
}

RELATION_TYPE_SCORE_WEIGHTS = {
    "decides": 0.20,
    "resolves": 0.16,
    "supersedes": 0.16,
    "depends_on": 0.14,
    "mentions": 0.05,
    "discusses": 0.08,
    "references": 0.04,
}


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        if text.endswith("Z"):
            try:
                dt = datetime.fromisoformat(text[:-1] + "+00:00")
            except ValueError:
                return None
        else:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _session_recency_bonus(last_event_at: Any) -> float:
    ts = _parse_timestamp(last_event_at)
    if ts is None:
        return 0.0
    now = datetime.now(timezone.utc)
    age_hours = max(0.0, (now - ts).total_seconds() / 3600)
    if age_hours <= 3.0:
        return 0.14
    if age_hours <= 12.0:
        return 0.10
    if age_hours <= 72.0:
        return 0.06
    return 0.02


def _relation_type_weight(relation_type: Any) -> float:
    text = str(relation_type or "").strip().lower()
    if not text:
        return 0.0
    return float(RELATION_TYPE_SCORE_WEIGHTS.get(text, 0.04))


def _safe_query_expansion_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def _query_expansion_payload(expansion: QueryExpansionResult | dict[str, Any] | None) -> dict[str, Any]:
    if expansion is None:
        return {}
    if isinstance(expansion, QueryExpansionResult):
        payload = expansion.to_dict()
    else:
        payload = query_expansion_payload(expansion) if expansion is not None else {}
    if not isinstance(payload, dict):
        return {}
    payload = dict(payload)
    payload["search_queries"] = _safe_query_expansion_list(payload.get("search_queries"))
    payload["terms"] = _safe_query_expansion_list(payload.get("terms"))
    return payload


def _query_intent_payload(profile: QueryIntent | dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(profile, QueryIntent):
        return profile.to_dict()
    if isinstance(profile, dict):
        return profile
    return {}


def token_estimate(text: str) -> int:
    return max(1, len(text) // 4)


def display_path(path: Path, root: Path | None = None) -> str:
    safe_root = root or _default_root()
    try:
        return str(path.resolve().relative_to(safe_root.resolve()))
    except ValueError:
        return str(path)


def normalize_tags(tags: Any) -> list[str]:
    if not tags:
        return []
    raw_tags = tags if isinstance(tags, list) else [tags]
    result: list[str] = []
    for tag in raw_tags:
        value = _safe_slug(str(tag).strip().lower())
        if value and value not in result:
            result.append(value)
    return result


def document_id_for(path: Path, kind: str) -> str:
    raw = f"{kind}:{display_path(path)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def chunk_id_for(document_id: str, index: int) -> str:
    return f"{document_id}:{index:04d}"


def split_markdown_chunks(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            chunks.append((heading, body))
        buffer = []

    for line in text.splitlines():
        if line.startswith("#"):
            if buffer:
                flush()
            heading = line.strip("# ").strip() or heading
            buffer.append(line)
            continue
        prospective = "\n".join([*buffer, line])
        if len(prospective) > max_chars and buffer:
            flush()
        buffer.append(line)
    flush()
    return chunks or [("", text[:max_chars])]


def parse_markdown_frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" not in line or line.startswith("  "):
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"')
    return result


def strip_markdown_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---", 4)
    if end < 0:
        return text
    return text[end + len("\n---") :].lstrip()


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for term in TOKEN_RE.findall(query.lower()):
        if len(term) < 2:
            continue
        if term not in terms:
            terms.append(term)
    return terms


def _has_signal_shape(term: str) -> bool:
    return len(term) > 3 or any(char.isdigit() for char in term) or any(char in term for char in "./:@-_")


def significant_terms(terms: list[str]) -> list[str]:
    shaped = [term for term in terms if _has_signal_shape(term)]
    return shaped or terms


def fts_quote(term: str) -> str:
    return f'"{term.replace(chr(34), "")}"'


def is_fts_corruption_error(exc: sqlite3.Error) -> bool:
    message = str(exc).lower()
    return "fts5:" in message or "memory_chunks_fts" in message or "database disk image is malformed" in message


def recreate_memory_chunks_fts(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        drop table if exists memory_chunks_fts;
        create virtual table memory_chunks_fts using fts5(
          chunk_id unindexed,
          document_id unindexed,
          project_id unindexed,
          kind unindexed,
          heading,
          text,
          tags
        );
        """
    )


def rebuild_memory_chunks_fts(conn: sqlite3.Connection) -> int:
    recreate_memory_chunks_fts(conn)
    cursor = conn.execute(
        """
        select chunk_id, document_id, coalesce(project_id, '') as project_id,
               kind, coalesce(heading, '') as heading, coalesce(text, '') as text,
               coalesce(tags_json, '') as tags
        from memory_chunks
        order by document_id, chunk_index
        """
    )
    count = 0
    while True:
        rows = cursor.fetchmany(1000)
        if not rows:
            break
        conn.executemany(
            """
            insert into memory_chunks_fts(chunk_id, document_id, project_id, kind, heading, text, tags)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [(row["chunk_id"], row["document_id"], row["project_id"], row["kind"], row["heading"], row["text"], row["tags"]) for row in rows],
        )
        count += len(rows)
    conn.commit()
    return count


def corpus_ranked_terms(conn: sqlite3.Connection, terms: list[str], *, limit: int = 12) -> list[str]:
    if not terms:
        return []
    total_row = conn.execute("select count(*) as c from memory_chunks").fetchone()
    total = max(1, int(total_row["c"] if total_row else 1))
    scored: list[tuple[float, str]] = []
    for term in terms:
        for attempt in range(2):
            try:
                count_row = conn.execute(
                    "select count(*) as c from memory_chunks_fts where memory_chunks_fts match ?",
                    (fts_quote(term),),
                ).fetchone()
                count = int(count_row["c"] if count_row else 0)
                break
            except sqlite3.Error as exc:
                if attempt == 0 and is_fts_corruption_error(exc):
                    rebuild_memory_chunks_fts(conn)
                    continue
                count = total
                break
        if count <= 0:
            continue
        common_ratio = count / total
        shape_bonus = 0.25 if _has_signal_shape(term) else 0.0
        rarity = common_ratio / (1 + min(len(term), 24) * 0.08 + shape_bonus)
        scored.append((rarity, term))
    if not scored:
        return significant_terms(terms)[:limit]
    scored.sort(key=lambda item: (item[0], item[1]))
    shaped = {term for term in terms if _has_signal_shape(term)}
    if shaped:
        filtered = [term for _, term in scored if term in shaped]
    else:
        filtered = [term for rarity, term in scored if rarity <= 0.08 or len(scored) <= 2]
    return (filtered or [term for _, term in scored])[:limit]


def fts_query(query: str, conn: sqlite3.Connection | None = None) -> str:
    terms = query_terms(query)
    if conn is not None:
        terms = corpus_ranked_terms(conn, terms)
    else:
        terms = significant_terms(terms)
    if not terms:
        return ""
    return " OR ".join(fts_quote(term) for term in terms[:12])


def index_memory_document(
    conn: sqlite3.Connection,
    path: Path,
    *,
    kind: str,
    session_id: str | None = None,
    dream_run_id: str | None = None,
    project_id: str | None = None,
    title: str | None = None,
    intent: str | None = None,
    helpful_score: float | None = None,
    tags: list[str] | None = None,
    memory_kind: str | None = None,
    source_kind: str | None = None,
    confidence: float | None = None,
    risk_level: str | None = None,
    sensitivity: str | None = None,
    injection_policy: str | None = None,
    poisoning_flags: list[str] | None = None,
    evidence: Any | None = None,
) -> str | None:
    file_system = _default_file_system()
    if not file_system.exists(path):
        return None
    text = file_system.read_text(path)
    frontmatter = parse_markdown_frontmatter(text)
    index_text = strip_markdown_frontmatter(text)
    scanned = scan_text(index_text, source_kind="memory_candidate")
    classified = deterministic_classifier(
        conn,
        stage="pre_memory",
        source_kind="memory_candidate",
        payload=index_text,
        deterministic=scanned,
        client_type=None,
        session_id=session_id,
        event_seq=None,
        source_ref=display_path(path),
        runner="auto",
    )
    scanned = classified.decision
    memory_kind = memory_kind or frontmatter.get("memory_kind")
    source_kind = source_kind or frontmatter.get("source_kind")
    risk_level = risk_level or frontmatter.get("risk_level") or scanned.risk_level or "unknown"
    sensitivity = sensitivity or frontmatter.get("sensitivity") or scanned.sensitivity or "normal"
    injection_policy = injection_policy or frontmatter.get("injection_policy") or scanned.injection_policy or "on_demand"
    if confidence is None and frontmatter.get("confidence"):
        try:
            confidence = float(frontmatter["confidence"])
        except ValueError:
            confidence = None
    flags = list(dict.fromkeys([*(poisoning_flags or []), *scanned.poisoning_flags]))
    if scanned.categories:
        tag_values = normalize_tags([*(tags or []), *scanned.categories])
    else:
        tag_values = normalize_tags(tags)
    rel_path = display_path(path)
    doc_id = document_id_for(path, kind)
    now = _now()
    old_chunks = [row["chunk_id"] for row in conn.execute("select chunk_id from memory_chunks where document_id = ?", (doc_id,))]
    with conn:
        for chunk_id in old_chunks:
            conn.execute("delete from memory_chunks_fts where chunk_id = ?", (chunk_id,))
        conn.execute("delete from memory_chunks where document_id = ?", (doc_id,))
        conn.execute(
            """
            insert or replace into memory_documents (
              document_id, kind, session_id, dream_run_id, project_id, path, title,
              created_at, updated_at, intent, helpful_score, tags_json,
              memory_kind, source_kind, confidence, risk_level, sensitivity,
              injection_policy, poisoning_flags_json, evidence_json, token_estimate
            ) values (
              ?, ?, ?, ?, ?, ?, ?,
              coalesce((select created_at from memory_documents where document_id = ?), ?),
              ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                doc_id,
                kind,
                session_id,
                dream_run_id,
                project_id,
                rel_path,
                title or path.stem,
                doc_id,
                now,
                now,
                intent,
                helpful_score,
                _json_dumps(tag_values),
                memory_kind,
                source_kind,
                confidence,
                risk_level,
                sensitivity,
                injection_policy,
                _json_dumps(flags),
                _json_dumps(evidence or []),
                token_estimate(index_text),
            ),
        )
        for index, (heading, body) in enumerate(split_markdown_chunks(index_text)):
            chunk_id = chunk_id_for(doc_id, index)
            conn.execute(
                """
                insert into memory_chunks (
                  chunk_id, document_id, chunk_index, kind, session_id, dream_run_id,
                  project_id, path, heading, text, tags_json, memory_kind, source_kind,
                  confidence, risk_level, sensitivity, injection_policy,
                  poisoning_flags_json, token_estimate, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    doc_id,
                    index,
                    kind,
                    session_id,
                    dream_run_id,
                    project_id,
                    rel_path,
                    heading,
                    body,
                    _json_dumps(tag_values),
                    memory_kind,
                    source_kind,
                    confidence,
                    risk_level,
                    sensitivity,
                    injection_policy,
                    _json_dumps(flags),
                    token_estimate(body),
                    now,
                ),
            )
            conn.execute(
                "insert into memory_chunks_fts(chunk_id, document_id, project_id, kind, heading, text, tags) values (?, ?, ?, ?, ?, ?, ?)",
                (chunk_id, doc_id, project_id or "", kind, heading, body, " ".join(tag_values)),
            )
        if dream_run_id:
            conn.execute("delete from dream_tags where dream_run_id = ?", (dream_run_id,))
            for tag in tag_values:
                conn.execute("insert or ignore into dream_tags(dream_run_id, tag) values (?, ?)", (dream_run_id, tag))
    return doc_id


def search_memory_chunks(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: str | None = None,
    intent: str | None = None,
    tag: str | None = None,
    min_helpful_score: float | None = None,
    limit: int = 10,
) -> list[sqlite3.Row]:
    return _search_memory_chunks(conn, query, project_id=project_id, intent=intent, tag=tag, min_helpful_score=min_helpful_score, limit=limit, repair_on_fts_error=True)


def _search_memory_chunks(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: str | None = None,
    intent: str | None = None,
    tag: str | None = None,
    min_helpful_score: float | None = None,
    limit: int = 10,
    repair_on_fts_error: bool = True,
) -> list[sqlite3.Row]:
    match = fts_query(query, conn)
    where = []
    params: list[Any] = []
    if match:
        where.append("memory_chunks_fts match ?")
        params.append(match)
    if project_id:
        where.append("coalesce(d.project_id, '') = ?")
        params.append(project_id)
    if intent:
        where.append("d.intent = ?")
        params.append(intent)
    if min_helpful_score is not None:
        where.append("coalesce(d.helpful_score, 0) >= ?")
        params.append(min_helpful_score)
    if tag:
        where.append("coalesce(c.tags_json, '') like ?")
        params.append(f"%{_safe_slug(tag.lower())}%")
    where_sql = "where " + " and ".join(where) if where else ""
    order_sql = "bm25(memory_chunks_fts), d.updated_at desc" if match else "d.updated_at desc, c.chunk_index"
    try:
        return list(
            conn.execute(
                f"""
                select c.*, d.intent, d.helpful_score, d.title, d.updated_at,
                       d.confidence as document_confidence,
                       d.risk_level as document_risk_level,
                       d.sensitivity as document_sensitivity,
                       d.injection_policy as document_injection_policy,
                       d.poisoning_flags_json as document_poisoning_flags_json,
                       bm25(memory_chunks_fts) as bm25_score
                from memory_chunks_fts
                join memory_chunks c on c.chunk_id = memory_chunks_fts.chunk_id
                join memory_documents d on d.document_id = c.document_id
                {where_sql}
                order by {order_sql}
                limit ?
                """,
                (*params, limit),
            )
        )
    except sqlite3.Error as exc:
        if repair_on_fts_error and is_fts_corruption_error(exc):
            rebuild_memory_chunks_fts(conn)
            return _search_memory_chunks(
                conn,
                query,
                project_id=project_id,
                intent=intent,
                tag=tag,
                min_helpful_score=min_helpful_score,
                limit=limit,
                repair_on_fts_error=False,
            )
        raise


def _safe_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _confidence_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.5


def _risk_penalty(risk_level: str | None, sensitivity: str | None, include_risky: bool) -> float:
    if include_risky:
        return 0.0
    penalty = 0.0
    if risk_level in {"high", "critical"}:
        penalty += 0.35
    elif risk_level in {"medium"}:
        penalty += 0.12
    if sensitivity in {"private", "secret"}:
        penalty += 0.5
    return penalty


def _allowed_by_policy(item: dict[str, Any], include_risky: bool) -> bool:
    if include_risky:
        return True
    sensitivity = item.get("sensitivity") or "normal"
    risk_level = item.get("risk_level") or "unknown"
    injection_policy = item.get("injection_policy") or item.get("risk", {}).get("injection_policy") or "on_demand"
    flags = item.get("poisoning_flags") or []
    return (
        sensitivity == "normal"
        and risk_level not in {"medium", "high", "critical"}
        and injection_policy not in {"never_auto", "quarantine"}
        and "contradicted" not in flags
    )


def _retrieval_profile_for_query(query_expansion: dict[str, Any] | None, query: str) -> dict[str, Any]:
    profile = (query_expansion or {}).get("retrieval_profile")
    if isinstance(profile, dict):
        return profile
    terms = [str(item) for item in (query_expansion or {}).get("terms", []) if str(item).strip()]
    return retrieval_profile_from_terms(terms or query_terms(query))


def _profile_kind_weight(profile: dict[str, Any], kind: str) -> float:
    weights = profile.get("result_kind_weights")
    if not isinstance(weights, dict):
        return 0.0
    try:
        return float(weights.get(kind, 0.0))
    except (TypeError, ValueError):
        return 0.0


def _profile_entity_type_weight(profile: dict[str, Any], entity_type: str, fallback_intent: str) -> float:
    weights = profile.get("entity_type_weights")
    if isinstance(weights, dict) and entity_type in weights:
        try:
            return float(weights[entity_type])
        except (TypeError, ValueError):
            pass
    return entity_type_weight_for_query(entity_type, fallback_intent)


def _entity_lookup_queries(query_expansion: dict[str, Any] | None, expanded_queries: list[str]) -> list[str]:
    values: list[str] = []
    for value in expanded_queries:
        if len(str(value).strip()) <= 80:
            values.append(str(value))
    for term in (query_expansion or {}).get("terms", []):
        text = str(term).strip()
        if len(text) >= 3 and text.lower() not in ENTITY_LOOKUP_STOP_TERMS:
            values.append(text)
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result[:20]


def _semantic_entity_context(
    conn: sqlite3.Connection,
    *,
    entity_key: str,
    source_session_id: str | None,
    source_dream_run_id: str | None,
    project_id: str | None,
    relation_limit: int = 6,
) -> dict[str, Any]:
    relation_params: list[Any] = [entity_key, entity_key]
    relation_where = """
        sr.status = 'active'
        and (sr.source_entity_key = ? or sr.target_entity_key = ?)
    """
    if project_id:
        relation_where += " and coalesce(sr.source_session_id, '') in (select session_id from sessions where project_id = ?)"
        relation_params.append(project_id)
    relation_rows = list(
        conn.execute(
            f"""
            select
              sr.semantic_relation_id,
              sr.relation_key,
              sr.relation_type,
              sr.source_entity_key,
              sr.target_entity_key,
              sr.summary,
              sr.confidence,
              sr.source_session_id,
              sr.source_dream_run_id,
              source_session.last_event_at as source_session_last_event_at,
              source_session.last_event_seq as source_session_last_event_seq,
              source_entity.name as source_entity_name,
              source_entity.entity_type as source_entity_type,
              target_entity.name as target_entity_name,
              target_entity.entity_type as target_entity_type
            from semantic_relations sr
            left join sessions source_session
              on source_session.session_id = sr.source_session_id
            left join semantic_entities source_entity
              on source_entity.entity_key = sr.source_entity_key
             and source_entity.status = 'active'
            left join semantic_entities target_entity
              on target_entity.entity_key = sr.target_entity_key
             and target_entity.status = 'active'
            where {relation_where}
            order by coalesce(sr.confidence, 0.5) desc, sr.updated_at desc
            limit ?
            """,
            (*relation_params, relation_limit),
        )
    )
    sessions_by_id: dict[str, dict[str, Any]] = {}
    dreams_by_id: dict[str, dict[str, Any]] = {}
    related_entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []

    def _touch_session(
        session_id: str,
        relation_type: str | None,
        related_entity_key: str | None,
        relation_weight: float,
        last_event_at: Any,
        last_event_seq: Any,
    ) -> None:
        if not session_id:
            return
        entry = sessions_by_id.setdefault(
            session_id,
            {
                "session_id": session_id,
                "supporting_relation_count": 0,
                "supporting_relation_weight": 0.0,
                "relation_types": [],
                "related_entity_keys": [],
            },
        )
        entry["supporting_relation_count"] += 1
        entry["supporting_relation_weight"] += relation_weight
        if relation_type and relation_type not in entry["relation_types"]:
            entry["relation_types"].append(relation_type)
        if related_entity_key and related_entity_key not in entry["related_entity_keys"]:
            entry["related_entity_keys"].append(related_entity_key)
        if last_event_seq is not None and str(last_event_seq).isdigit():
            try:
                entry["source_session_last_event_seq"] = max(int(last_event_seq), int(entry.get("source_session_last_event_seq") or 0))
            except ValueError:
                pass
        if last_event_at and str(last_event_at).strip():
            previous = entry.get("source_session_last_event_at")
            parsed_current = _parse_timestamp(last_event_at)
            parsed_previous = _parse_timestamp(previous)
            if parsed_current is not None and (parsed_previous is None or parsed_current > parsed_previous):
                entry["source_session_last_event_at"] = str(last_event_at)

    def _touch_dream(dream_run_id: str, relation_type: str | None) -> None:
        if not dream_run_id:
            return
        entry = dreams_by_id.setdefault(
            dream_run_id,
            {
                "dream_run_id": dream_run_id,
                "supporting_relation_count": 0,
                "relation_types": [],
            },
        )
        entry["supporting_relation_count"] += 1
        if relation_type and relation_type not in entry["relation_types"]:
            entry["relation_types"].append(relation_type)

    if source_session_id:
        sessions_by_id[source_session_id] = {
            "session_id": source_session_id,
            "supporting_relation_count": 0,
            "supporting_relation_weight": 0.0,
            "relation_types": [],
            "related_entity_keys": [],
            "is_source_session": True,
        }
    if source_dream_run_id:
        dreams_by_id[source_dream_run_id] = {
            "dream_run_id": source_dream_run_id,
            "supporting_relation_count": 0,
            "relation_types": [],
            "is_source_dream": True,
        }

    mutation_params: list[Any] = [entity_key]
    mutation_where = "target_kind in ('entity', 'semantic_entity') and target_key = ?"
    if project_id:
        mutation_where += " and coalesce(source_session_id, '') in (select session_id from sessions where project_id = ?)"
        mutation_params.append(project_id)
    mutation_rows = list(
        conn.execute(
            f"""
            select source_session_id, source_dream_run_id, mutation_kind
            from semantic_projection_mutations
            where {mutation_where}
            order by created_at desc
            """,
            mutation_params,
        )
    )
    for row in mutation_rows:
        session_id = str(row["source_session_id"] or "")
        dream_run_id = str(row["source_dream_run_id"] or "")
        mutation_kind = str(row["mutation_kind"] or "")
        if session_id:
            entry = sessions_by_id.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "supporting_relation_count": 0,
                    "supporting_relation_weight": 0.0,
                    "relation_types": [],
                    "related_entity_keys": [],
                },
            )
            if mutation_kind and mutation_kind not in entry["relation_types"]:
                entry["relation_types"].append(mutation_kind)
                entry["supporting_relation_weight"] += _relation_type_weight(mutation_kind)
        if dream_run_id:
            entry = dreams_by_id.setdefault(
                dream_run_id,
                {
                    "dream_run_id": dream_run_id,
                    "supporting_relation_count": 0,
                    "supporting_relation_weight": 0.0,
                    "relation_types": [],
                },
            )
            if mutation_kind and mutation_kind not in entry["relation_types"]:
                entry["relation_types"].append(mutation_kind)

    for row in relation_rows:
        source_key = str(row["source_entity_key"] or "")
        target_key = str(row["target_entity_key"] or "")
        outgoing = source_key == entity_key
        related_key = target_key if outgoing else source_key
        related_name = row["target_entity_name"] if outgoing else row["source_entity_name"]
        related_type = row["target_entity_type"] if outgoing else row["source_entity_type"]
        relation = {
            "semantic_relation_id": row["semantic_relation_id"],
            "relation_key": row["relation_key"],
            "relation_type": row["relation_type"],
            "summary": row["summary"],
            "direction": "outgoing" if outgoing else "incoming",
            "related_entity_key": related_key,
            "related_entity_name": related_name,
            "related_entity_type": related_type,
            "source_session_id": row["source_session_id"],
            "source_dream_run_id": row["source_dream_run_id"],
            "confidence": _confidence_value(row["confidence"]),
        }
        relations.append(relation)
        if related_key:
            related_entry = {
                "entity_key": related_key,
                "name": related_name,
                "entity_type": related_type,
                "via_relation_type": row["relation_type"],
                "direction": relation["direction"],
            }
            if related_entry not in related_entities:
                related_entities.append(related_entry)
        relation_type = str(row["relation_type"] or "")
        relation_weight = _relation_type_weight(relation_type)
        _touch_session(
            str(row["source_session_id"] or ""),
            relation_type,
            related_key,
            relation_weight,
            row["source_session_last_event_at"],
            row["source_session_last_event_seq"],
        )
        _touch_dream(str(row["source_dream_run_id"] or ""), str(row["relation_type"] or ""))

    relation_bonus = sum(item.get("supporting_relation_weight", 0.0) for item in sessions_by_id.values())
    return {
        "relations": relations,
        "related_entities": related_entities[:relation_limit],
        "linked_sessions": list(sessions_by_id.values()),
        "linked_dream_runs": list(dreams_by_id.values()),
        "relation_count": len(relations),
        "relation_type_bonus": round(min(0.52, relation_bonus), 6),
        "cross_session_count": len(sessions_by_id),
    }


def _insert_result(
    results: dict[tuple[str, str], dict[str, Any]],
    item: dict[str, Any],
) -> None:
    key = (str(item["kind"]), str(item["id"]))
    existing = results.get(key)
    if existing is None or float(item["score"]) > float(existing["score"]):
        results[key] = item


def retrieve_memory(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: str | None = None,
    workdir: str | None = None,
    client_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    kind: str | None = None,
    include_risky: bool = False,
    limit: int = 10,
    runner: str | None = None,
    log: bool = True,
    query_expansion: QueryExpansionResult | dict[str, Any] | None = None,
) -> dict[str, Any]:
    started_at = _now()
    retrieval_run_id = f"ret_{uuid.uuid4().hex[:16]}"
    expanded_queries = [query]
    query_expansion_payload = _query_expansion_payload(query_expansion)
    if not query_expansion_payload:
        query_expansion_payload = _query_expansion_payload(deterministic_query_expansion(query))
    if query_expansion_payload:
        expanded_queries = [str(item) for item in query_expansion_payload.get("search_queries", []) if str(item).strip()] or [query]
    expanded_queries = list(dict.fromkeys(expanded_queries))[:8]
    retrieval_profile = _retrieval_profile_for_query(query_expansion_payload, query)
    query_intents = {
        lookup_query: _query_intent_payload(
            classify_query_intent(query_terms(lookup_query), return_payload=False)
        )
        for lookup_query in expanded_queries
    }
    profile_intent = retrieval_profile.get("intent") if isinstance(retrieval_profile.get("intent"), dict) else None
    primary_query_intent = profile_intent or query_intents.get(query, _query_intent_payload(classify_query_intent(query_terms(query), return_payload=False)))
    filters = {
        "project_id": project_id,
        "workdir": workdir,
        "client_type": client_type,
        "since": since,
        "until": until,
        "kind": kind,
        "include_risky": include_risky,
        "query_language": query_expansion_payload.get("input_language"),
        "query_expansion_source": query_expansion_payload.get("source"),
        "expanded_queries": expanded_queries,
        "query_intent": primary_query_intent,
        "expanded_query_intents": query_intents,
        "retrieval_profile": retrieval_profile,
    }
    results: dict[tuple[str, str], dict[str, Any]] = {}

    # Exact and fuzzy session lookup.
    session_where = ["1=1"]
    session_params: list[Any] = []
    if project_id:
        session_where.append("project_id = ?")
        session_params.append(project_id)
    if client_type:
        session_where.append("client_type = ?")
        session_params.append(client_type)
    if since:
        session_where.append("datetime(coalesce(last_event_at, started_at)) >= datetime(?)")
        session_params.append(since)
    if until:
        session_where.append("datetime(coalesce(last_event_at, started_at)) <= datetime(?)")
        session_params.append(until)
    if workdir:
        session_where.append("(coalesce(last_workdir, cwd, '') = ? or coalesce(last_workdir, cwd, '') like ?)")
        session_params.extend([workdir, f"{workdir}/%"])
    if kind in {None, "session"}:
        for lookup_query in expanded_queries:
            like = f"%{lookup_query}%"
            for row in conn.execute(
                f"""
                select *
                from sessions
                where {' and '.join(session_where)}
                  and (session_id like ? or coalesce(thread_name, '') like ? or coalesce(session_brief, '') like ?)
                order by coalesce(last_event_at, started_at, '') desc
                limit ?
                """,
                (*session_params, f"{lookup_query}%", like, like, max(limit, 20)),
            ):
                exact = 1.0 if str(row["session_id"]).startswith(lookup_query) else 0.0
                recency = 0.12 if row["last_event_at"] else 0.0
                kind_weight = _profile_kind_weight(retrieval_profile, "session")
                score = 0.45 + exact + recency + kind_weight
                _insert_result(
                    results,
                    {
                        "kind": "session",
                        "id": row["session_id"],
                        "title": row["thread_name"] or row["session_brief"] or row["session_id"],
                        "path": row["transcript_path"] or "",
                        "score": score,
                        "score_breakdown": {"exact": exact, "bm25": 0, "entity": 0, "recency": recency, "confidence": 0.5, "usage": 0, "kind_weight": kind_weight, "query": lookup_query},
                        "provenance": {"session_id": row["session_id"]},
                        "risk": {"confidence": 1.0, "risk_level": "low", "sensitivity": "normal", "poisoning_flags": []},
                        "evidence": [{"source_type": "session", "session_id": row["session_id"], "field": "session", "query": lookup_query}],
                        "text": row["session_brief"] or "",
                        "sensitivity": "normal",
                        "risk_level": "low",
                        "poisoning_flags": [],
                    },
                )

    # FTS-backed document/chunk lookup.
    for lookup_query in expanded_queries:
        for row in search_memory_chunks(conn, lookup_query, project_id=project_id, limit=max(limit * 3, 30)):
            if kind and row["kind"] != kind:
                continue
            sensitivity = row["sensitivity"] or row["document_sensitivity"] or "normal"
            risk_level = row["risk_level"] or row["document_risk_level"] or "unknown"
            flags = _safe_json(row["poisoning_flags_json"] or row["document_poisoning_flags_json"], [])
            confidence = _confidence_value(row["confidence"] if row["confidence"] is not None else row["document_confidence"])
            bm25_raw = abs(float(row["bm25_score"] or 0.0))
            bm25_score = min(0.65, 0.18 + bm25_raw / 10)
            risk_penalty = _risk_penalty(risk_level, sensitivity, include_risky)
            kind_weight = _profile_kind_weight(retrieval_profile, str(row["kind"] or ""))
            score = bm25_score + confidence * 0.18 + kind_weight - risk_penalty
            item = {
                "kind": row["kind"],
                "id": row["chunk_id"],
                "title": row["title"] or row["heading"] or row["path"],
                "path": f"{row['path']}#{row['chunk_index']}",
                "score": score,
                "score_breakdown": {"exact": 0, "bm25": bm25_score, "entity": 0, "recency": 0, "confidence": confidence * 0.18, "usage": 0, "kind_weight": kind_weight, "risk_penalty": risk_penalty, "query": lookup_query},
                "provenance": {"session_id": row["session_id"], "dream_run_id": row["dream_run_id"], "document_id": row["document_id"], "chunk_id": row["chunk_id"]},
                "risk": {
                    "confidence": confidence,
                    "risk_level": risk_level,
                    "sensitivity": sensitivity,
                    "poisoning_flags": flags,
                    "injection_policy": row["injection_policy"] or row["document_injection_policy"] or "on_demand",
                },
                "evidence": [{"source_type": "memory_chunk", "path": row["path"], "field": row["heading"] or "text", "query": lookup_query}],
                "text": row["text"],
                "sensitivity": sensitivity,
                "risk_level": risk_level,
                "poisoning_flags": flags,
                "injection_policy": row["injection_policy"] or row["document_injection_policy"] or "on_demand",
            }
            if _allowed_by_policy(item, include_risky):
                _insert_result(results, item)

    # Entity lookup from materialized graph.
    if kind in {None, "entity", "graph_entity"}:
        entity_lookup_queries = _entity_lookup_queries(query_expansion_payload, expanded_queries)
        entity_lookup_forms = {
            value.lower()
            for value in [query, *entity_lookup_queries]
            if str(value).strip()
        }
        for lookup_query in entity_lookup_queries:
            query_intent = query_intents.get(lookup_query, primary_query_intent)
            entity_like = f"%{lookup_query}%"
            entity_params: list[Any] = [entity_like, entity_like, entity_like, entity_like, entity_like]
            entity_where = """
                (
                  name like ? or entity_key like ? or coalesce(aliases_json, '') like ?
                  or coalesce(summary, '') like ? or coalesce(properties_json, '') like ?
                )
            """
            if project_id:
                entity_where += " and coalesce(source_session_id, '') in (select session_id from sessions where project_id = ?)"
                entity_params.append(project_id)
            for row in conn.execute(
                f"""
                select *
                from semantic_entities
                where {entity_where}
                order by coalesce(confidence, 0.5) desc, updated_at desc
                limit ?
                """,
                (*entity_params, max(limit, 20)),
            ):
                confidence = _confidence_value(row["confidence"])
                risk_penalty = 0.0
                name_text = str(row["name"] or "").lower()
                exact = 0.4 if any(form in name_text for form in entity_lookup_forms) else 0.0
                aliases = _safe_json(row["aliases_json"], [])
                properties = _safe_json(row["properties_json"], {})
                if not isinstance(properties, dict):
                    properties = {}
                normalization = properties.get("normalization", {})
                normalization_aliases = []
                if isinstance(normalization.get("aliases"), list):
                    normalization_aliases = normalization.get("aliases")
                elif isinstance(normalization.get("aliases"), str):
                    normalization_aliases = [normalization.get("aliases")]
                alias_forms = [
                    *(str(item) for item in aliases),
                    str(properties.get("source_name") or ""),
                    *(str(item) for item in normalization_aliases),
                ]
                alias_text_lower = " ".join(alias_forms).lower()
                alias_bonus = 0.18 if any(form in alias_text_lower for form in entity_lookup_forms) else 0.0
                normalized_english_name = str(normalization.get("normalized_english_name") or "").lower()
                normalized_bonus = 0.22 if any(form in normalized_english_name for form in entity_lookup_forms) else 0.0
                raw_type_weight = 0.35 if str(row["entity_type"] or "").lower() in lookup_query.lower() else 0.0
                type_weight = raw_type_weight * 0.2
                semantic_context = _semantic_entity_context(
                    conn,
                    entity_key=str(row["entity_key"] or ""),
                    source_session_id=row["source_session_id"],
                    source_dream_run_id=row["source_dream_run_id"],
                    project_id=project_id,
                )
                relation_type_bonus = min(0.22, float(semantic_context.get("relation_type_bonus", 0.0)))
                relation_bonus = min(0.08, 0.03 * semantic_context["relation_count"])
                cross_session_bonus = min(0.2, 0.06 * max(0, semantic_context["cross_session_count"] - 1))
                linked_session_recency = max(
                    (_session_recency_bonus(item.get("source_session_last_event_at")) for item in semantic_context["linked_sessions"]),
                    default=0.0,
                )
                kind_weight = _profile_kind_weight(retrieval_profile, "entity")
                relation_weight_bonus = min(
                    0.12,
                    sum(float(item.get("supporting_relation_weight", 0.0)) for item in semantic_context["linked_sessions"]),
                )
                score = (
                    0.28
                    + exact
                    + alias_bonus
                    + normalized_bonus
                    + type_weight
                    + relation_type_bonus
                    + relation_weight_bonus
                    + relation_bonus
                    + linked_session_recency
                    + cross_session_bonus
                    + kind_weight
                    + confidence * 0.22
                    - risk_penalty
                )
                evidence = [{"source_type": "semantic_entity", "field": row["entity_type"], "quote": row["name"], "query": lookup_query}]
                for relation in semantic_context["relations"][:3]:
                    if relation.get("summary"):
                        evidence.append(
                            {
                                "source_type": "semantic_relation",
                                "field": relation.get("relation_type"),
                                "quote": relation.get("summary"),
                                "query": lookup_query,
                            }
                        )
                item = {
                    "kind": "entity",
                    "id": row["semantic_entity_id"],
                    "title": row["name"],
                    "path": "",
                    "score": score,
                    "score_breakdown": {
                        "exact": exact,
                        "bm25": 0,
                        "entity": 0.28,
                        "alias_bonus": alias_bonus,
                        "normalized_bonus": normalized_bonus,
                        "entity_type_weight": type_weight,
                        "raw_entity_type_weight": raw_type_weight,
                        "relation_bonus": relation_bonus,
                        "relation_type_bonus": relation_type_bonus,
                        "relation_weight_bonus": relation_weight_bonus,
                        "cross_session_bonus": cross_session_bonus,
                        "linked_session_recency_bonus": linked_session_recency,
                        "query_intent": query_intent,
                        "recency": 0,
                        "confidence": confidence * 0.22,
                        "usage": 0,
                        "kind_weight": kind_weight,
                        "risk_penalty": risk_penalty,
                        "query": lookup_query,
                    },
                    "provenance": {
                        "session_id": row["source_session_id"],
                        "dream_run_id": row["source_dream_run_id"],
                        "semantic_entity_id": row["semantic_entity_id"],
                        "semantic_entity_key": row["entity_key"],
                        "linked_session_ids": [item["session_id"] for item in semantic_context["linked_sessions"]],
                        "linked_dream_run_ids": [item["dream_run_id"] for item in semantic_context["linked_dream_runs"]],
                    },
                    "risk": {"confidence": confidence, "risk_level": "low", "sensitivity": "normal", "poisoning_flags": [], "injection_policy": "on_demand"},
                    "evidence": evidence,
                    "text": row["summary"] or row["properties_json"] or row["name"],
                    "semantic_context": semantic_context,
                    "sensitivity": "normal",
                    "risk_level": "low",
                    "poisoning_flags": [],
                    "injection_policy": "on_demand",
                }
                if _allowed_by_policy(item, include_risky):
                    _insert_result(results, item)
                    if kind in {None, "session"}:
                        session_kind_weight = _profile_kind_weight(retrieval_profile, "session")
                        for linked_session in semantic_context["linked_sessions"]:
                            session_id = str(linked_session.get("session_id") or "")
                            if not session_id:
                                continue
                            session_row = conn.execute(
                                """
                                select session_id, thread_name, session_brief, transcript_path,
                                       started_at, last_event_at
                                from sessions
                                where session_id = ?
                                """,
                                (session_id,),
                            ).fetchone()
                            if session_row is None:
                                continue
                            linked_count = int(linked_session.get("supporting_relation_count") or 0)
                            session_recency = _session_recency_bonus(session_row["last_event_at"])
                            linked_relation_weight = min(
                                0.12,
                                float(linked_session.get("supporting_relation_weight", 0.0)),
                            )
                            session_score = (
                                0.2
                                + min(0.12, 0.05 * linked_count)
                                + linked_relation_weight
                                + (0.08 if linked_session.get("is_source_session") else 0.0)
                                + session_recency
                                + session_kind_weight
                                + confidence * 0.1
                            )
                            session_item = {
                                "kind": "session",
                                "id": session_row["session_id"],
                                "title": session_row["thread_name"] or session_row["session_brief"] or session_row["session_id"],
                                "path": session_row["transcript_path"] or "",
                                "score": session_score,
                                "score_breakdown": {
                                    "exact": 0,
                                    "bm25": 0,
                                    "entity": 0.2,
                                    "semantic_context_bonus": min(0.18, 0.05 * linked_count),
                                    "source_session_bonus": 0.08 if linked_session.get("is_source_session") else 0.0,
                                    "query_intent": query_intent,
                                    "recency": session_recency,
                                    "confidence": confidence * 0.1,
                                    "usage": 0,
                                    "kind_weight": session_kind_weight,
                                    "relation_weight_bonus": linked_relation_weight,
                                    "recency_bonus": session_recency,
                                    "query": lookup_query,
                                },
                                "provenance": {
                                    "session_id": session_row["session_id"],
                                    "semantic_entity_id": row["semantic_entity_id"],
                                    "semantic_entity_key": row["entity_key"],
                                    "supporting_relation_count": linked_count,
                                    "supporting_relation_types": linked_session.get("relation_types", []),
                                },
                                "risk": {"confidence": confidence, "risk_level": "low", "sensitivity": "normal", "poisoning_flags": [], "injection_policy": "on_demand"},
                                "evidence": [
                                    {
                                        "source_type": "semantic_entity_link",
                                        "session_id": session_row["session_id"],
                                        "field": row["entity_type"],
                                        "quote": row["name"],
                                        "query": lookup_query,
                                    }
                                ],
                                "text": session_row["session_brief"] or row["summary"] or row["name"],
                                "sensitivity": "normal",
                                "risk_level": "low",
                                "poisoning_flags": [],
                                "injection_policy": "on_demand",
                            }
                            if _allowed_by_policy(session_item, include_risky):
                                _insert_result(results, session_item)
                    if kind in {None, "dream"}:
                        dream_kind_weight = _profile_kind_weight(retrieval_profile, "dream")
                        for linked_dream in semantic_context["linked_dream_runs"]:
                            dream_run_id = str(linked_dream.get("dream_run_id") or "")
                            if not dream_run_id:
                                continue
                            dream_row = conn.execute(
                                """
                                select dream_run_id, session_id, started_at, finished_at, status,
                                       pipeline_version, output_summary_path
                                from dream_runs
                                where dream_run_id = ?
                                """,
                                (dream_run_id,),
                            ).fetchone()
                            if dream_row is None:
                                continue
                            linked_count = int(linked_dream.get("supporting_relation_count") or 0)
                            dream_score = (
                                0.18
                                + min(0.16, 0.05 * linked_count)
                                + (0.06 if linked_dream.get("is_source_dream") else 0.0)
                                + dream_kind_weight
                                + confidence * 0.08
                            )
                            dream_item = {
                                "kind": "dream",
                                "id": dream_row["dream_run_id"],
                                "title": dream_row["dream_run_id"],
                                "path": dream_row["output_summary_path"] or "",
                                "score": dream_score,
                                "score_breakdown": {
                                    "exact": 0,
                                    "bm25": 0,
                                    "entity": 0.18,
                                    "semantic_context_bonus": min(0.16, 0.05 * linked_count),
                                    "source_dream_bonus": 0.06 if linked_dream.get("is_source_dream") else 0.0,
                                    "query_intent": query_intent,
                                    "recency": 0,
                                    "confidence": confidence * 0.08,
                                    "usage": 0,
                                    "kind_weight": dream_kind_weight,
                                    "query": lookup_query,
                                },
                                "provenance": {
                                    "dream_run_id": dream_row["dream_run_id"],
                                    "session_id": dream_row["session_id"],
                                    "semantic_entity_id": row["semantic_entity_id"],
                                    "semantic_entity_key": row["entity_key"],
                                    "supporting_relation_count": linked_count,
                                    "supporting_relation_types": linked_dream.get("relation_types", []),
                                },
                                "risk": {"confidence": confidence, "risk_level": "low", "sensitivity": "normal", "poisoning_flags": [], "injection_policy": "on_demand"},
                                "evidence": [
                                    {
                                        "source_type": "semantic_entity_link",
                                        "session_id": dream_row["session_id"],
                                        "field": row["entity_type"],
                                        "quote": row["name"],
                                        "query": lookup_query,
                                    }
                                ],
                                "text": row["summary"] or row["name"],
                                "sensitivity": "normal",
                                "risk_level": "low",
                                "poisoning_flags": [],
                                "injection_policy": "on_demand",
                            }
                            if _allowed_by_policy(dream_item, include_risky):
                                _insert_result(results, dream_item)

        for lookup_query in entity_lookup_queries:
            query_intent = query_intents.get(lookup_query, primary_query_intent)
            entity_like = f"%{lookup_query}%"
            entity_params: list[Any] = [entity_like, entity_like, entity_like]
            entity_where = "(name like ? or key like ? or coalesce(aliases_json, '') like ?)"
            if project_id:
                entity_where += " and coalesce(session_id, '') in (select session_id from sessions where project_id = ?)"
                entity_params.append(project_id)
            for row in conn.execute(
                f"""
                select *
                from graph_entities
                where {entity_where}
                order by coalesce(confidence, 0.5) desc, last_seen_at desc
                limit ?
                """,
                (*entity_params, max(limit, 20)),
            ):
                query_intent = query_intents.get(lookup_query, primary_query_intent)
                sensitivity = row["sensitivity"] or "normal"
                risk_level = row["risk_level"] or "unknown"
                injection_policy = row["injection_policy"] or "on_demand"
                flags = _safe_json(row["poisoning_flags_json"], [])
                confidence = _confidence_value(row["confidence"])
                risk_penalty = _risk_penalty(risk_level, sensitivity, include_risky)
                exact = 0.35 if lookup_query.lower() in str(row["name"]).lower() else 0.0
                raw_type_weight = _profile_entity_type_weight(retrieval_profile, str(row["type"] or ""), str(query_intent["intent"]))
                type_weight = raw_type_weight * 0.25
                kind_weight = _profile_kind_weight(retrieval_profile, "entity")
                score = 0.25 + exact + type_weight + kind_weight + confidence * 0.22 - risk_penalty
                item = {
                    "kind": "entity",
                    "id": row["entity_id"],
                    "title": row["name"],
                    "path": "",
                    "score": score,
                    "score_breakdown": {
                        "exact": exact,
                        "bm25": 0,
                        "entity": 0.25,
                        "entity_type_weight": type_weight,
                        "raw_entity_type_weight": raw_type_weight,
                        "query_intent": query_intent,
                        "recency": 0,
                        "confidence": confidence * 0.22,
                        "usage": 0,
                        "kind_weight": kind_weight,
                        "risk_penalty": risk_penalty,
                        "query": lookup_query,
                    },
                    "provenance": {"session_id": row["session_id"], "dream_run_id": row["dream_run_id"], "artifact_id": row["artifact_id"]},
                    "risk": {"confidence": confidence, "risk_level": risk_level, "sensitivity": sensitivity, "poisoning_flags": flags, "injection_policy": injection_policy},
                    "evidence": [{"source_type": "graph_entity", "field": row["type"], "quote": row["name"], "query": lookup_query}],
                    "text": row["properties_json"] or row["name"],
                    "sensitivity": sensitivity,
                    "risk_level": risk_level,
                    "poisoning_flags": flags,
                    "injection_policy": injection_policy,
                }
                if _allowed_by_policy(item, include_risky):
                    _insert_result(results, item)

    ranked = sorted(results.values(), key=lambda item: float(item["score"]), reverse=True)[: max(1, limit)]
    finished_at = _now()
    if log:
        with conn:
            conn.execute(
                """
                insert into retrieval_runs (
                  retrieval_run_id, query, runner, client_type, project_id, workdir,
                  filters_json, started_at, finished_at, status, result_count
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'succeeded', ?)
                """,
                (retrieval_run_id, query, runner, client_type, project_id, workdir, _json_dumps(filters), started_at, finished_at, len(ranked)),
            )
            for index, item in enumerate(ranked, start=1):
                conn.execute(
                    """
                    insert into retrieval_results (
                      retrieval_run_id, rank, result_kind, result_id, title, path, score,
                      score_breakdown_json, provenance_json, risk_json, evidence_json,
                      injected, created_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (
                        retrieval_run_id,
                        index,
                        item["kind"],
                        item["id"],
                        item.get("title"),
                        item.get("path"),
                        float(item["score"]),
                        _json_dumps(item["score_breakdown"]),
                        _json_dumps(item["provenance"]),
                        _json_dumps(item["risk"]),
                        _json_dumps(item["evidence"]),
                        finished_at,
                    ),
                )
                conn.execute(
                    """
                    insert into memory_access_log (
                      accessed_at, access_kind, runner, client_type, retrieval_run_id,
                      target_kind, target_id, project_id, workdir, used_in_context
                    ) values (?, 'retrieve', ?, ?, ?, ?, ?, ?, ?, 0)
                    """,
                    (finished_at, runner, client_type, retrieval_run_id, item["kind"], item["id"], project_id, workdir),
                )
    return {
        "retrieval_run_id": retrieval_run_id,
        "query": query,
        "query_expansion": query_expansion_payload,
        "query_intent": primary_query_intent,
        "retrieval_profile": retrieval_profile,
        "filters": filters,
        "results": ranked,
    }


def apply_retrieval_safety_filter(
    conn: sqlite3.Connection,
    retrieval_payload: dict[str, Any],
    *,
    include_risky: bool = False,
    runner: str = "auto",
) -> dict[str, Any]:
    results = retrieval_payload.get("results", [])
    context_text = "\n\n".join(str(item.get("text") or "")[:1200] for item in results[: min(len(results), 5)])
    if not context_text:
        return retrieval_payload

    safety = deterministic_classifier(
        conn,
        stage="retrieval_safety",
        source_kind="retrieval_context",
        payload=context_text,
        deterministic=scan_text(context_text, source_kind="retrieval_context"),
        source_ref=retrieval_payload.get("retrieval_run_id"),
        runner=runner,
    )
    payload = dict(retrieval_payload)
    payload["retrieval_safety"] = {"classifier_run_id": safety.run_id, **safety.decision.to_json(), "status": safety.status}

    if safety.decision.is_risky and not include_risky:
        retrieval_run_id = retrieval_payload.get("retrieval_run_id")
        record_risk_event(
            conn,
            safety.decision,
            source_kind="retrieval_context",
            source_ref=retrieval_run_id,
            status="quarantined" if safety.decision.decision == "quarantine" else "warned",
            classifier_run_id=safety.run_id,
            evidence=[{"source_kind": "retrieval_context", "source_ref": retrieval_run_id, "field": "retrieval_results", "quote": safety.decision.preview}],
        )
        if safety.decision.decision == "quarantine":
            payload["results"] = []
    return payload


def retrieve_memory_with_safety(
    conn: sqlite3.Connection,
    query: str,
    *,
    project_id: str | None = None,
    workdir: str | None = None,
    client_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    kind: str | None = None,
    include_risky: bool = False,
    limit: int = 10,
    runner: str | None = None,
    log: bool = True,
    query_expansion_mode: str = "auto",
    query_expander_runner: str | None = None,
    query_expander_model: str | None = None,
    query_expander_timeout: int = 20,
    safety_scan: bool = True,
    safety_runner: str = "auto",
) -> dict[str, Any]:
    expansion = build_query_expansion(
        query,
        mode=query_expansion_mode,
        runner=query_expander_runner,
        model=query_expander_model,
        timeout=query_expander_timeout,
    )
    payload = retrieve_memory(
        conn,
        query,
        project_id=project_id,
        workdir=workdir,
        client_type=client_type,
        since=since,
        until=until,
        kind=kind,
        include_risky=include_risky,
        limit=limit,
        runner=runner,
        log=log,
        query_expansion=expansion,
    )
    if not safety_scan:
        return payload
    return apply_retrieval_safety_filter(conn, payload, include_risky=include_risky, runner=safety_runner)


def _safe_json_load(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except (TypeError, ValueError):
        return default


def list_retrieval_runs_data(
    conn: sqlite3.Connection,
    *,
    query: str | None,
    project_id: str | None,
    client: str | None,
    limit: int,
    results: int,
) -> list[dict[str, Any]]:
    rows = list(
        conn.execute(
            """
            select
              r.retrieval_run_id,
              r.query,
              r.runner,
              r.client_type,
              r.project_id,
              r.workdir,
              r.started_at,
              r.finished_at,
              r.status,
              r.result_count,
              r.filters_json,
              (
                select json_group_array(
                  json_object(
                    'rank', rr.rank,
                    'kind', rr.result_kind,
                    'id', rr.result_id,
                    'title', rr.title,
                    'path', rr.path,
                    'score', rr.score,
                    'score_breakdown', rr.score_breakdown_json,
                    'provenance', rr.provenance_json
                  )
                )
                from (
                  select *
                  from retrieval_results
                  where retrieval_run_id = r.retrieval_run_id
                  order by rank
                  limit ?
                ) rr
              ) as top_results_json
            from retrieval_runs r
            where (? is null or r.query like '%' || ? || '%')
              and (? is null or r.project_id = ?)
              and (? is null or r.client_type = ?)
            order by r.started_at desc
            limit ?
            """,
            (
                max(1, int(results)),
                query,
                query,
                project_id,
                project_id,
                client,
                client,
                limit,
            ),
        )
    )
    data: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["filters"] = _safe_json_load(item.pop("filters_json"), {})
        top_results = _safe_json_load(item.pop("top_results_json"), [])
        if isinstance(top_results, list):
            for result in top_results:
                if not isinstance(result, dict):
                    continue
                result["score_breakdown"] = _safe_json_load(result.get("score_breakdown"), {})
                result["provenance"] = _safe_json_load(result.get("provenance"), {})
        else:
            top_results = []
        item["top_results"] = top_results
        data.append(item)
    return data


def get_retrieval_run_data(
    conn: sqlite3.Connection,
    retrieval_run_id: str,
) -> dict[str, Any] | None:
    run_row = conn.execute("select * from retrieval_runs where retrieval_run_id = ?", (retrieval_run_id,)).fetchone()
    if not run_row:
        return None
    results = list(
        conn.execute(
            """
            select *
            from retrieval_results
            where retrieval_run_id = ?
            order by rank
            """,
            (retrieval_run_id,),
        )
    )
    access_rows = list(
        conn.execute(
            """
            select accessed_at, access_kind, runner, client_type, target_kind, target_id, project_id, workdir, used_in_context
            from memory_access_log
            where retrieval_run_id = ?
            order by accessed_at, access_id
            """,
            (retrieval_run_id,),
        )
    )
    run = dict(run_row)
    run["filters"] = _safe_json_load(run.pop("filters_json"), {})
    result_items: list[dict[str, Any]] = []
    for row in results:
        item = dict(row)
        item["score_breakdown"] = _safe_json_load(item.pop("score_breakdown_json"), {})
        item["provenance"] = _safe_json_load(item.pop("provenance_json"), {})
        result_items.append(item)
    return {
        "run": run,
        "results": result_items,
        "access_log": [dict(access_row) for access_row in access_rows],
    }


def retrieve_memory_for_interface(
    query: str,
    *,
    project_id: str | None = None,
    workdir: str | None = None,
    client_type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    kind: str | None = None,
    include_risky: bool = False,
    limit: int = 10,
    runner: str | None = None,
    log: bool = True,
    query_expansion_mode: str = "auto",
    query_expander_runner: str | None = None,
    query_expander_model: str | None = None,
    query_expander_timeout: int = 20,
    safety_scan: bool = True,
    safety_runner: str = "auto",
) -> dict[str, Any]:
    clock = _default_clock()
    conn = _default_db_provider().connect()
    try:
        return retrieve_memory_with_safety(
            conn,
            query,
            project_id=project_id,
            workdir=workdir,
            client_type=client_type,
            since=since,
            until=until,
            kind=kind,
            include_risky=include_risky,
            limit=limit,
            runner=runner,
            log=log,
            query_expansion_mode=query_expansion_mode,
            query_expander_runner=query_expander_runner,
            query_expander_model=query_expander_model,
            query_expander_timeout=query_expander_timeout,
            safety_scan=safety_scan,
            safety_runner=safety_runner,
        )
    finally:
        conn.close()


def list_retrieval_runs(
    *,
    query: str | None,
    project_id: str | None,
    client: str | None,
    limit: int,
    results: int,
) -> list[dict[str, Any]]:
    conn = _default_db_provider().connect()
    try:
        return list_retrieval_runs_data(
            conn,
            query=query,
            project_id=project_id,
            client=client,
            limit=limit,
            results=results,
        )
    finally:
        conn.close()


def get_retrieval_run(retrieval_run_id: str) -> dict[str, Any] | None:
    conn = _default_db_provider().connect()
    try:
        return get_retrieval_run_data(conn, retrieval_run_id)
    finally:
        conn.close()
