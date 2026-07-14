from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..infrastructure.config import MEMORY_DIR, ROOT, safe_slug
from .dream_queue import dream_queue_status
from ..adapters.runners.codex import iter_codex_transcript_messages
from ..adapters.runners.session_metadata import refresh_session_row_metadata
from ..adapters.sqlite.request_db import connect
from ..adapters.sqlite.row import row_dict as _row_dict


REPORTS_DIR = Path(MEMORY_DIR) / "analysis_reports"
REPORT_FILE_RE = re.compile(r"^analysis_(?P<session_slug>.+)_(?P<timestamp>\d{8}T\d{6}Z)\.html$")
_FILTER_OPTIONS_CACHE: tuple[float, dict[str, Any]] | None = None


def _runtime_allowed_roots() -> list[Path]:
    roots: list[Path] = []
    for candidate in (ROOT, MEMORY_DIR):
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def _resolve_runtime_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    for allowed_root in _runtime_allowed_roots():
        if resolved == allowed_root or allowed_root in resolved.parents:
            return resolved
    return None


def _normalized_artifact_path(path_value: str | None) -> str:
    return str(path_value or "").strip().replace("\\", "/")


def _is_v2_dream_run_path(path_value: str | None) -> bool:
    normalized = _normalized_artifact_path(path_value)
    return bool(normalized) and "/dream/v2/runs/" in f"/{normalized}"


def _is_v2_audit_path(path_value: str | None) -> bool:
    normalized = _normalized_artifact_path(path_value)
    return _is_v2_dream_run_path(normalized) and "/audit/" in f"/{normalized}"


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def elapsed_ms(started_at: str | None, finished_at: str | None) -> int | None:
    start = parse_time(started_at)
    finish = parse_time(finished_at)
    if start is None or finish is None:
        return None
    return max(0, int((finish - start).total_seconds() * 1000))


def _first_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _first_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value"):
            text = _first_text(value.get(key))
            if text:
                return text
    return ""


def _claude_content_text(content: object) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text" and isinstance(item.get("text"), str):
            parts.append(item["text"])
        elif item_type == "tool_result" and isinstance(item.get("content"), str):
            parts.append(f"[tool_result] {item['content']}")
    return "\n\n".join(part.strip() for part in parts if part and part.strip()).strip()


def _tag_body(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*(.*?)\s*</{tag}>", text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _compact_message_text(value: str | None, limit: int = 20_000) -> str:
    compact = str(value or "").strip()
    if not compact:
        return ""
    return compact[:limit]


def _session_transcript_messages(session: dict[str, Any]) -> list[dict[str, Any]]:
    client = str(session.get("client_type") or "").strip().lower()
    transcript_path = str(session.get("transcript_path") or "").strip()
    if not transcript_path:
        return []
    path = Path(transcript_path)
    if not path.exists() or not path.is_file():
        return []
    messages: list[dict[str, Any]] = []
    try:
        if client == "codex":
            _, rows = iter_codex_transcript_messages(path)
            for row in rows:
                text = _compact_message_text(str(row.get("text") or ""))
                role = str(row.get("role") or "")
                if not text or role not in {"user", "assistant"}:
                    continue
                messages.append(
                    {
                        "id": f"transcript:{path.name}:{row.get('line_no')}",
                        "role": role,
                        "content": text,
                        "timestamp": str(row.get("timestamp") or ""),
                        "source": "transcript",
                    }
                )
            return messages
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, start=1):
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                timestamp = str(row.get("timestamp") or row.get("created_at") or "")
                if client == "claude":
                    row_type = str(row.get("type") or "")
                    if row_type not in {"user", "assistant"}:
                        continue
                    message = row.get("message") if isinstance(row.get("message"), dict) else {}
                    text = _compact_message_text(_claude_content_text(message.get("content")))
                    if not text:
                        continue
                    messages.append(
                        {
                            "id": f"transcript:{path.name}:{line_no}",
                            "role": row_type,
                            "content": text,
                            "timestamp": timestamp,
                            "source": "transcript",
                        }
                    )
                elif client == "gemini":
                    row_type = str(row.get("type") or "")
                    if row_type == "user":
                        text = _compact_message_text(_first_text(row.get("content")))
                        if not text or "<session_context>" in text:
                            continue
                        messages.append(
                            {
                                "id": f"transcript:{path.name}:{line_no}",
                                "role": "user",
                                "content": text,
                                "timestamp": timestamp,
                                "source": "transcript",
                            }
                        )
                    elif row_type == "gemini":
                        text = _compact_message_text(str(row.get("content") or ""))
                        if not text:
                            continue
                        messages.append(
                            {
                                "id": f"transcript:{path.name}:{line_no}",
                                "role": "assistant",
                                "content": text,
                                "timestamp": timestamp,
                                "source": "transcript",
                            }
                        )
                elif client == "antigravity":
                    row_type = str(row.get("type") or "")
                    source = str(row.get("source") or "")
                    content = str(row.get("content") or "")
                    if row_type == "USER_INPUT" and source.startswith("USER"):
                        text = _compact_message_text(_tag_body(content, "USER_REQUEST"))
                        if not text:
                            continue
                        messages.append(
                            {
                                "id": f"transcript:{path.name}:{line_no}",
                                "role": "user",
                                "content": text,
                                "timestamp": timestamp,
                                "source": "transcript",
                            }
                        )
                    elif source == "MODEL":
                        text = _compact_message_text(content)
                        if not text:
                            continue
                        messages.append(
                            {
                                "id": f"transcript:{path.name}:{line_no}",
                                "role": "assistant",
                                "content": text,
                                "timestamp": timestamp,
                                "source": "transcript",
                            }
                        )
    except OSError:
        return []
    return messages


def _v2_stage_display(stage_name: str) -> dict[str, str]:
    displays = {
        "window": {
            "category": "llm_context",
            "badge": "LLM context",
            "label": "Event Window",
            "class_name": "llm-input",
        },
        "dream_narrative": {
            "category": "llm_call",
            "badge": "LLM sees/produces",
            "label": "Dream Narrative",
            "class_name": "llm-input",
        },
        "semantic_extraction": {
            "category": "llm_call",
            "badge": "LLM extracts",
            "label": "Semantic Extraction",
            "class_name": "llm-input",
        },
        "normalization": {
            "category": "deterministic",
            "badge": "deterministic",
            "label": "Semantic Normalization",
            "class_name": "llm-derived",
        },
        "operational_extraction": {
            "category": "deterministic",
            "badge": "deterministic",
            "label": "Operational Extraction",
            "class_name": "llm-derived",
        },
        "candidate_search": {
            "category": "retrieval",
            "badge": "retrieval",
            "label": "Candidate Search",
            "class_name": "llm-derived",
        },
        "reconciliation": {
            "category": "llm_call",
            "badge": "LLM decides",
            "label": "Reconciliation",
            "class_name": "llm-input",
        },
        "persistence": {
            "category": "persistence",
            "badge": "persistence",
            "label": "Persistence",
            "class_name": "llm-derived",
        },
    }
    return displays.get(
        stage_name,
        {"category": "artifact", "badge": "artifact", "label": stage_name or "Stage", "class_name": "llm-generated"},
    )


def _resolve_session_handover_from_v2(conn: Any, session_id: str) -> dict[str, Any]:
    if not session_id:
        return {}
    run = conn.execute(
        """
        select dream_run_id, output_summary_path, output_memory_paths_json,
               started_at, finished_at, input_event_seq_from, input_event_seq_to
        from dream_runs
        where session_id = ?
          and status = 'succeeded'
          and pipeline_version = 2
          and (
            output_summary_path is not null
            or output_memory_paths_json is not null
          )
        order by coalesce(finished_at, started_at) desc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    if not run:
        return {}
    summary_path = str(run["output_summary_path"] or "").strip()
    if not summary_path:
        normalized_output_paths = [str(path).strip() for path in _parse_json_list(run["output_memory_paths_json"])]
        for path in _parse_json_list(run["output_memory_paths_json"]):
            normalized_path = str(path).strip()
            if (
                "/audit/" in f"/{normalized_path}"
                and normalized_path.endswith("/summary.md")
                and _is_v2_dream_run_path(normalized_path)
            ):
                summary_path = normalized_path
                break
        if not summary_path:
            for path in normalized_output_paths:
                if path.endswith("/summary.md") and "/audit/" in f"/{path}":
                    summary_path = path
                    break
    if not summary_path:
        return {}
    event_from = int(run["input_event_seq_from"] or 0)
    event_to = int(run["input_event_seq_to"] or event_from)
    return {
        "summary_path": summary_path,
        "created_at": run["finished_at"] or run["started_at"],
        "input_event_count": max(0, event_to - event_from + 1),
        "summary_kind": "dream_pipeline_v2",
    }


def monitor_dreams(limit: int, status: str | None = None, runner: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    conn = connect()
    where: list[str] = []
    params: list[Any] = []
    if status:
        where.append("dr.status = ?")
        params.append(status)
    if runner:
        where.append("dr.runner = ?")
        params.append(runner)
    if session_id:
        where.append("dr.session_id = ?")
        params.append(session_id)
    where_sql = "where " + " and ".join(where) if where else ""
    rows = list(
        conn.execute(
            f"""
            with token_turns as (
              select session_id,
                     coalesce(turn_id, 'row:' || id) as turn_key,
                     max(coalesce(input_tokens, 0)) as input_tokens,
                     max(coalesce(cached_input_tokens, 0)) as cached_input_tokens,
                     max(coalesce(output_tokens, 0)) as output_tokens,
                     max(coalesce(reasoning_output_tokens, 0)) as reasoning_output_tokens,
                     max(coalesce(total_tokens, 0)) as total_tokens
              from token_usage
              group by session_id, turn_key
            ),
            session_tokens as (
              select session_id,
                     coalesce(sum(input_tokens), 0) as session_input_tokens,
                     coalesce(sum(cached_input_tokens), 0) as session_cached_input_tokens,
                     coalesce(sum(output_tokens), 0) as session_output_tokens,
                     coalesce(sum(reasoning_output_tokens), 0) as session_reasoning_tokens,
                     coalesce(sum(total_tokens), 0) as session_total_tokens
              from token_turns
              group by session_id
            )
            select dr.*,
                   s.thread_name, s.project_id, s.cwd, s.last_workdir,
                   coalesce(st.session_input_tokens, 0) as session_input_tokens,
                   coalesce(st.session_cached_input_tokens, 0) as session_cached_input_tokens,
                   coalesce(st.session_output_tokens, 0) as session_output_tokens,
                   coalesce(st.session_reasoning_tokens, 0) as session_reasoning_tokens,
                   coalesce(st.session_total_tokens, 0) as session_total_tokens
            from dream_runs dr
            left join sessions s on s.session_id = dr.session_id
            left join session_tokens st on st.session_id = dr.session_id
            {where_sql}
            order by dr.started_at desc
            limit ?
            """,
            (*params, limit),
        )
    )
    dreams: list[dict[str, Any]] = []
    totals = {
        "count": 0,
        "duration_ms": 0,
        "prompt_tokens": 0,
        "cached_prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    for row in rows:
        item = _row_dict(row)
        if item.get("duration_ms") is None:
            item["duration_ms"] = elapsed_ms(item.get("started_at"), item.get("finished_at"))
        for key in ("prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens", "duration_ms"):
            if item.get(key) is None:
                item[key] = 0
        if item.get("output_memory_paths_json"):
            try:
                item["output_memory_paths"] = json.loads(item["output_memory_paths_json"])
            except json.JSONDecodeError:
                item["output_memory_paths"] = []
        else:
            item["output_memory_paths"] = []
        files = _dream_file_items(item)
        episode_short, episode_title = _dream_episode_short(files, item)
        item["memory_files"] = files
        item["audit_files"] = _dream_audit_file_items(item)
        item["downstream_files"] = _dream_downstream_file_items(conn, item)
        _attach_v2_dream_details(conn, item)
        item["episode_short"] = episode_short
        item["episode_title"] = episode_title
        item["episode_meta_short"] = _dream_meta_preview(conn, item)
        item.update(_dream_count_preview(conn, item))
        dreams.append(item)
        totals["count"] += 1
        for key in ("duration_ms", "prompt_tokens", "cached_prompt_tokens", "completion_tokens", "reasoning_tokens", "total_tokens"):
            totals[key] += int(item.get(key) or 0)
    return {"dreams": dreams, "totals": totals}


def monitor_dream_queue(limit: int, status: str | None = None, session_id: str | None = None) -> dict[str, Any]:
    conn = connect()
    try:
        return dream_queue_status(conn, status=status or "all", session_id=session_id, limit=limit)
    finally:
        conn.close()


def _utc_now_hour() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(minute=0, second=0, microsecond=0)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _stats_window(range_name: str, start: str | None, end: str | None) -> tuple[datetime, datetime]:
    if range_name == "custom":
        parsed_start = parse_time(start)
        parsed_end = parse_time(end)
        if parsed_start is None or parsed_end is None:
            raise ValueError("custom range requires valid start and end")
        start_dt = _as_utc(parsed_start).replace(minute=0, second=0, microsecond=0)
        end_dt = _as_utc(parsed_end).replace(minute=0, second=0, microsecond=0)
        if end_dt <= start_dt:
            raise ValueError("end must be after start")
        return start_dt, end_dt
    end_dt = _utc_now_hour() + timedelta(hours=1)
    if range_name == "today":
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0), end_dt
    days = 7 if range_name == "7d" else 2
    return end_dt - timedelta(days=days), end_dt


def _sqlite_time(value: datetime) -> str:
    return _as_utc(value).isoformat()


def _hour_key(value: datetime) -> str:
    return _as_utc(value).replace(minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


def _folder_filter_sql(alias: str, workdir: str | None, params: list[Any]) -> str:
    if not workdir:
        return ""
    normalized = str(Path(workdir).expanduser())
    params.extend([normalized, normalized, f"{normalized}/%", normalized, normalized, f"{normalized}/%"])
    return f"""
      and (
        {alias}.last_workdir = ? or {alias}.cwd = ?
        or {alias}.last_workdir like ?
        or ? like {alias}.last_workdir || '/%'
        or ? like {alias}.cwd || '/%'
        or {alias}.cwd like ?
      )
    """


def monitor_filter_options() -> dict[str, Any]:
    global _FILTER_OPTIONS_CACHE
    now = time.monotonic()
    if _FILTER_OPTIONS_CACHE and now - _FILTER_OPTIONS_CACHE[0] < 30:
        return {
            "clients": list(_FILTER_OPTIONS_CACHE[1]["clients"]),
            "projects": list(_FILTER_OPTIONS_CACHE[1]["projects"]),
            "workdirs": list(_FILTER_OPTIONS_CACHE[1]["workdirs"]),
        }
    conn = connect()
    clients = [
        row["client_type"]
        for row in conn.execute(
            """
            select distinct client_type from sessions
            where client_type is not null and client_type != ''
            order by client_type
            """
        )
    ]
    projects = [
        row["project_id"]
        for row in conn.execute(
            """
            select distinct project_id from sessions
            where project_id is not null and project_id != ''
            order by project_id
            """
        )
    ]
    workdirs = [
        row["workdir"]
        for row in conn.execute(
            """
            select distinct coalesce(nullif(last_workdir, ''), nullif(cwd, '')) as workdir
            from sessions
            where coalesce(nullif(last_workdir, ''), nullif(cwd, '')) is not null
            order by workdir
            """
        )
    ]
    data = {"clients": clients, "projects": projects, "workdirs": workdirs}
    _FILTER_OPTIONS_CACHE = (now, data)
    return {"clients": list(clients), "projects": list(projects), "workdirs": list(workdirs)}


def _read_relative_text(path_value: str | None, max_chars: int = 200_000) -> str:
    resolved = _resolve_runtime_path(path_value)
    if resolved is None:
        return ""
    try:
        with resolved.open("r", encoding="utf-8", errors="replace") as handle:
            return handle.read(max_chars)
    except OSError:
        return ""


def _relative_file_metadata(path_value: str | None) -> dict[str, Any]:
    resolved = _resolve_runtime_path(path_value)
    if resolved is None:
        return {}
    try:
        stat = resolved.stat()
        return {"size_bytes": stat.st_size, "mtime": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")}
    except OSError:
        return {}


def _compact_preview_text(value: str | None, *, limit: int = 360) -> str:
    if not value:
        return ""
    return " ".join(str(value).replace("#", " ").split())[:limit]


def _llm_role_for_audit_path(path: str, kind: str) -> str:
    if kind == "prompt":
        return "llm_input"
    if kind == "response":
        return "llm_generated"
    if kind == "metadata":
        return "process_metadata"
    return "artifact"


def _llm_role_for_downstream_kind(kind: str) -> str:
    if kind == "graph_structurer_prompt":
        return "llm_input"
    if kind in {"graph_structurer_raw_output", "graph_structurer_response"}:
        return "llm_generated"
    if kind in {"memory_update", "graph_artifact"}:
        return "llm_derived"
    if kind == "graph_structurer_metadata":
        return "process_metadata"
    return "artifact"


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def _read_relative_json(path_value: str | None, max_chars: int = 500_000) -> Any:
    text = _read_relative_text(path_value, max_chars=max_chars)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _graph_entity_summary(entity: Any) -> dict[str, Any] | None:
    if not isinstance(entity, dict):
        return None
    evidence = [item for item in (entity.get("evidence") or []) if isinstance(item, dict)]
    return {
        "type": entity.get("type"),
        "key": entity.get("key"),
        "name": entity.get("name"),
        "aliases": [str(alias) for alias in (entity.get("aliases") or []) if alias][:8],
        "properties": entity.get("properties") if isinstance(entity.get("properties"), dict) else {},
        "memory_kind": entity.get("memory_kind"),
        "source_kind": entity.get("source_kind"),
        "confidence": entity.get("confidence"),
        "evidence_count": len(evidence),
        "evidence": evidence[:3],
    }


def _graph_relation_summary(relation: Any) -> dict[str, Any] | None:
    if not isinstance(relation, dict):
        return None
    evidence = [item for item in (relation.get("evidence") or []) if isinstance(item, dict)]
    from_ref = relation.get("from") if isinstance(relation.get("from"), dict) else {}
    to_ref = relation.get("to") if isinstance(relation.get("to"), dict) else {}
    return {
        "type": relation.get("type"),
        "from": {"type": from_ref.get("type"), "key": from_ref.get("key")},
        "to": {"type": to_ref.get("type"), "key": to_ref.get("key")},
        "properties": relation.get("properties") if isinstance(relation.get("properties"), dict) else {},
        "memory_kind": relation.get("memory_kind"),
        "source_kind": relation.get("source_kind"),
        "confidence": relation.get("confidence"),
        "evidence_count": len(evidence),
        "evidence": evidence[:3],
    }


def _dream_graph_sections(conn: Any, dream_run_id: str) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    facts_section = {"artifact": {}, "entities": [], "relations": []}
    patch_section = {"artifact": {}, "entities": [], "relations": []}
    rows = list(
        conn.execute(
            """
            select graph_artifact_id, artifact_type, path, created_at, status,
                   entity_count, relation_count, evidence_count, runner, intent,
                   helpful_score, tags_json, error_message
            from graph_artifacts
            where dream_run_id = ?
              and artifact_type in ('facts', 'patch')
            order by created_at asc
            """,
            (dream_run_id,),
        )
    )
    for row in rows:
        artifact = _row_dict(row)
        artifact["tags"] = _parse_json_list(artifact.pop("tags_json", None))
        payload = _read_relative_json(artifact.get("path"), max_chars=2_000_000)
        entities = []
        relations = []
        if isinstance(payload, dict):
            entities = [
                item
                for item in (_graph_entity_summary(entity) for entity in payload.get("entities", []))
                if item is not None
            ]
            relations = [
                item
                for item in (_graph_relation_summary(relation) for relation in payload.get("relations", []))
                if item is not None
            ]
        artifact["structured_entities"] = entities
        artifact["structured_relations"] = relations
        artifacts.append(artifact)
        if artifact.get("artifact_type") == "facts":
            facts_section = {"artifact": artifact, "entities": entities, "relations": relations}
        elif artifact.get("artifact_type") == "patch":
            patch_section = {"artifact": artifact, "entities": entities, "relations": relations}
    return {"artifacts": artifacts, "facts": facts_section, "patch": patch_section}


def _v2_audit_kind(path_value: str) -> str:
    filename = Path(path_value).name.lower()
    if filename == "summary.md":
        return "audit_summary"
    if filename == "memory-changes.md":
        return "memory_changes"
    if filename == "review-needed.md":
        return "review_needed"
    return "audit"


def _session_analysis_reports(session_id: str) -> list[dict[str, Any]]:
    session_slug = safe_slug(session_id)
    if not REPORTS_DIR.exists():
        return []
    reports: list[dict[str, Any]] = []
    for path in REPORTS_DIR.iterdir():
        if not path.is_file() or path.suffix != ".html":
            continue
        match = REPORT_FILE_RE.match(path.name)
        if not match or match.group("session_slug") != session_slug:
            continue
        timestamp = match.group("timestamp")
        try:
            created_at = datetime.strptime(timestamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
        except ValueError:
            created_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        topic = ""
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:120_000]
            topic_match = re.search(r"Topic \[[^\]]+\]: ([^<]+)</div>", text)
            if topic_match:
                topic = topic_match.group(1).strip()
        except OSError:
            pass
        reports.append(
            {
                "filename": path.name,
                "session_slug": session_slug,
                "created_at": created_at,
                "topic": topic,
                "size_bytes": path.stat().st_size,
            }
        )
    reports.sort(key=lambda item: item["created_at"], reverse=True)
    return reports


def _section_text(markdown: str, heading: str) -> str:
    lines = markdown.splitlines()
    start = None
    marker = f"## {heading}".lower()
    for index, line in enumerate(lines):
        if line.strip().lower() == marker:
            start = index + 1
            break
    if start is None:
        return ""
    out: list[str] = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if line.strip():
            out.append(line.strip())
    return " ".join(out).strip()


def _dream_file_items(row: dict[str, Any]) -> list[dict[str, str]]:
    paths: list[str] = []
    if row.get("output_summary_path"):
        paths.append(str(row["output_summary_path"]))
    for path in _parse_json_list(row.get("output_memory_paths_json")):
        if path not in paths and ("/memories/dreams/" in path or path.endswith(".md")):
            paths.append(path)
    items: list[dict[str, str]] = []
    for path in paths:
        if "/dream/runs/" in path and (path.endswith("/prompt.md") or path.endswith("/response.md")):
            continue
        content = _read_relative_text(path, max_chars=200_000)
        if content:
            items.append({"path": path, "content": content})
    return items


def _dream_audit_file_items(row: dict[str, Any]) -> list[dict[str, str]]:
    pipeline_version = int(row.get("pipeline_version") or 1)
    paths: list[str] = []
    if row.get("output_summary_path"):
        paths.append(str(row["output_summary_path"]))
    for path in _parse_json_list(row.get("output_memory_paths_json")):
        if path in paths:
            continue
        if _is_v2_audit_path(path):
            paths.append(path)
            continue
        if pipeline_version == 2:
            continue
        if "/dream/runs/" in path and path not in paths:
            paths.append(path)
    run_id = str(row.get("dream_run_id") or "")
    if run_id:
        run_dir = Path("memory") / "dream" / "runs" / safe_slug(run_id)
        if pipeline_version != 2:
            for name in (
                "prompt.md",
                "codex-output.md",
                "claude-output.md",
                "cursor-output.md",
                "response.md",
                "metadata.json",
            ):
                rel = str(run_dir / name)
                if rel not in paths:
                    paths.append(rel)
        for role in () if pipeline_version == 2 else ():
            pass
    items: list[dict[str, str]] = []
    for path in paths:
        content = _read_relative_text(path, max_chars=500_000)
        if not content:
            continue
        if path.endswith(".json"):
            kind = "metadata"
        elif path.endswith("prompt.md"):
            kind = "prompt"
        elif path.endswith("response.md") or path.endswith("-output.json"):
            kind = "response"
        elif _is_v2_audit_path(path):
            kind = _v2_audit_kind(path)
        elif _is_v2_dream_run_path(path):
            kind = "v2_stage_file"
        else:
            kind = "response"
        meta = _relative_file_metadata(path)
        meta["char_count"] = len(content)
        items.append({"path": path, "kind": kind, "content": content, "llm_role": _llm_role_for_audit_path(path, kind), "metadata": meta})
    return items


def _add_downstream_item(items: list[dict[str, Any]], *, path: str, kind: str, title: str, max_chars: int = 500_000, metadata: dict[str, Any] | None = None) -> None:
    if not path or any(item.get("path") == path and item.get("kind") == kind for item in items):
        return
    content = _read_relative_text(path, max_chars=max_chars)
    if not content:
        return
    file_metadata = _relative_file_metadata(path)
    file_metadata["char_count"] = len(content)
    file_metadata.update(metadata or {})
    items.append({"path": path, "kind": kind, "title": title, "content": content, "llm_role": _llm_role_for_downstream_kind(kind), "metadata": file_metadata})


def _dream_downstream_file_items(conn: Any, row: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    dream_run_id = str(row.get("dream_run_id") or "")
    pipeline_version = int(row.get("pipeline_version") or 1)
    if pipeline_version == 2:
        for path in _parse_json_list(row.get("output_memory_paths_json")):
            if not _is_v2_dream_run_path(path):
                continue
            if path in {item.get("path") for item in items}:
                continue
            if "/audit/" not in path:
                continue
            kind = "memory_update" if _v2_audit_kind(path) in {"memory_changes", "review_needed", "audit_summary"} else "v2_stage_file"
            _add_downstream_item(items, path=path, kind=kind, title=f"V2 Audit · {Path(path).name}", max_chars=220_000)
        for stage_row in conn.execute(
            """
            select stage_name, stage_order, prompt_path, raw_output_path, parsed_output_path, artifact_path
            from dream_stage_runs
            where dream_run_id = ?
            order by stage_order
            """,
            (dream_run_id,),
        ):
            for role, kind in (
                ("prompt_path", "v2_stage_prompt"),
                ("raw_output_path", "v2_stage_raw"),
                ("parsed_output_path", "v2_stage_parsed"),
                ("artifact_path", "v2_stage_artifact"),
            ):
                path = stage_row[role]
                if not path:
                    continue
                stage_name = stage_row["stage_name"] or "stage"
                stage_order = stage_row["stage_order"]
                title = f"V2 Stage {stage_order} · {stage_name} · {kind.replace('v2_stage_', '')}"
                _add_downstream_item(items, path=path, kind=kind, title=title, max_chars=180_000)
        for artifact in conn.execute(
            """
            select dream_artifact_id, artifact_kind, artifact_role, path, created_at,
                   byte_count, char_count, metadata_json
            from dream_artifacts
            where dream_run_id = ?
            order by created_at asc
            """,
            (dream_run_id,),
        ):
            metadata = _row_dict(artifact)
            title = f"Dream Artifact · {artifact['artifact_role'] or artifact['artifact_kind'] or ''}"
            _add_downstream_item(
                items,
                path=str(artifact["path"] or ""),
                kind="v2_artifact",
                title=title,
                max_chars=220_000,
                metadata=metadata,
            )
        for artifact in conn.execute(
            """
            select graph_artifact_id, artifact_type, path, created_at, status,
                   entity_count, relation_count, evidence_count, runner
            from graph_artifacts
            where dream_run_id = ?
              and artifact_type in ('facts', 'patch')
            order by created_at asc
            """,
            (dream_run_id,),
        ):
            metadata = _row_dict(artifact)
            title = "Graph facts" if artifact["artifact_type"] == "facts" else "Graph patch"
            _add_downstream_item(
                items,
                path=str(artifact["path"] or ""),
                kind="graph_artifact",
                title=title,
                max_chars=220_000,
                metadata=metadata,
            )
        return items

    for path in _parse_json_list(row.get("output_memory_paths_json")):
        if "/dream/runs/" in path:
            continue
        if "/memories/dreams/" not in path:
            continue
        _add_downstream_item(items, path=path, kind="memory_update", title="Dream Memory From LLM Response", max_chars=220_000)
    dream_run_id = str(row.get("dream_run_id") or "")
    if dream_run_id:
        llm_dir = Path("memory") / "graph" / "llm-runs" / safe_slug(dream_run_id)
        absolute_dir = ROOT / llm_dir
        if absolute_dir.exists():
            for path in sorted(absolute_dir.iterdir(), key=lambda item: item.name):
                if not path.is_file():
                    continue
                rel = str(llm_dir / path.name)
                if path.name == "prompt.md":
                    kind = "graph_structurer_prompt"
                    title = "Graph Structurer Prompt"
                elif path.name == "metadata.json":
                    kind = "graph_structurer_metadata"
                    title = "Graph Structurer Metadata"
                elif path.name.endswith("-raw-output.json"):
                    kind = "graph_structurer_raw_output"
                    title = "Graph Structurer Raw LLM Output"
                elif path.name.endswith("-output.json"):
                    kind = "graph_structurer_response"
                    title = "Graph Structurer Saved Response"
                else:
                    kind = "graph_structurer_artifact"
                    title = "Graph Structurer Artifact"
                _add_downstream_item(items, path=rel, kind=kind, title=title, max_chars=500_000)
        for artifact in conn.execute(
            """
            select graph_artifact_id, artifact_type, path, created_at, status,
                   entity_count, relation_count, evidence_count, runner, intent,
                   helpful_score, tags_json, error_message
            from graph_artifacts
            where dream_run_id = ?
            order by created_at asc
            """,
            (dream_run_id,),
        ):
            metadata = _row_dict(artifact)
            title = f"Graph {artifact['artifact_type']} ({artifact['runner'] or 'unknown'})"
            _add_downstream_item(
                items,
                path=str(artifact["path"] or ""),
                kind="graph_artifact",
                title=title,
                max_chars=500_000,
                metadata=metadata,
            )
    return items


def _dream_episode_short(files: list[dict[str, str]], row: dict[str, Any]) -> tuple[str, str]:
    def _first_meaningful_line(content: str) -> str:
        for raw_line in content.splitlines():
            stripped = raw_line.strip(" #-*\t")
            if not stripped:
                continue
            normalized = stripped.lower()
            if normalized in {"dream memory update", "session handover"}:
                continue
            if stripped.startswith("---"):
                continue
            if raw_line.lstrip().startswith("##"):
                continue
            if ":" in stripped[:28]:
                continue
            return stripped
        return ""

    def _dream_snippet(value: str) -> tuple[str, str]:
        text = " ".join(part.strip() for part in value.splitlines() if part.strip()).strip()
        text = text.lstrip("-* ").strip()
        if not text:
            return "", ""
        short = text[:360]
        title = text[:120] + ("..." if len(text) > 120 else "")
        return short, title

    for item in files:
        content = item.get("content") or ""
        for heading in ("Startup Brief", "Compact Summary", "Durable Decisions", "Open Tasks"):
            section = _section_text(content, heading)
            line = _first_meaningful_line(section)
            if line:
                return _dream_snippet(line)

    for item in files:
        path = str(item.get("path") or "")
        if not path.endswith("/dream.md") and not path.endswith("/raw-output.md"):
            continue
        line = _first_meaningful_line(item.get("content") or "")
        if line:
            return _dream_snippet(line)
    for item in files:
        content = item.get("content") or ""
        brief = _section_text(content, "Startup Brief")
        if brief:
            return _dream_snippet(brief)
    for item in files:
        line = _first_meaningful_line(item.get("content") or "")
        if line:
            return _dream_snippet(line)
    fallback = row.get("intent") or row.get("dream_run_id") or "Dream episode"
    return str(fallback)[:360], str(fallback)[:120]


def _latest_dream_preview(conn: Any, session_id: str) -> tuple[str, str]:
    row = conn.execute(
        """
        select *
        from dream_runs
        where session_id = ?
        order by input_event_seq_from desc, started_at desc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return "", ""
    item = _row_dict(row)
    files = _dream_file_items(item)
    seen = {str(file.get("path") or "") for file in files}
    for extra in _dream_downstream_file_items(conn, item):
        path = str(extra.get("path") or "")
        if not path or path in seen:
            continue
        files.append({"path": path, "content": str(extra.get("content") or "")})
        seen.add(path)
    episode_short, episode_title = _dream_episode_short(files, item)
    return episode_short, episode_title


def _dream_narrative_path(row: dict[str, Any]) -> str | None:
    dream_run_id = str(row.get("dream_run_id") or "").strip()
    if not dream_run_id:
        return None
    pipeline_version = int(row.get("pipeline_version") or 1)
    if pipeline_version == 2:
        return str(Path("memory") / "dream" / "v2" / "runs" / safe_slug(dream_run_id) / "01-dream-narrative" / "dream.md")
    return None


def _latest_dream_preview_light(row: dict[str, Any], *, session_brief: str | None = None) -> tuple[str, str]:
    brief = str(session_brief or "").strip()
    if brief:
        short = brief[:360]
        title = brief[:120] + ("..." if len(brief) > 120 else "")
        return short, title
    narrative_path = _dream_narrative_path(row)
    if narrative_path:
        content = _read_relative_text(narrative_path, max_chars=8000)
        if content:
            return _dream_episode_short([{"path": narrative_path, "content": content}], row)
    fallback = str(row.get("intent") or row.get("dream_run_id") or "").strip()
    if not fallback:
        return "", ""
    return fallback[:360], fallback[:120]


def _dream_pending(item: dict[str, Any]) -> bool:
    status = str(item.get("status") or "").lower()
    pipeline_status = str(item.get("pipeline_status") or "").lower()
    terminal = {"succeeded", "failed", "completed", "persisted", "dry_run"}
    if status in terminal or pipeline_status in terminal:
        return False
    pending_markers = {"queued", "running", "dreaming", "pending"}
    return status in pending_markers or pipeline_status in pending_markers


def _dream_meta_preview(conn: Any, row: dict[str, Any]) -> str:
    dream_run_id = str(row.get("dream_run_id") or "")
    if not dream_run_id:
        return ""
    status = str(row.get("status") or "").lower()
    pipeline_status = str(row.get("pipeline_status") or "").lower()
    if _dream_pending(row):
        stage = conn.execute(
            """
            select stage_name, status
            from dream_stage_runs
            where dream_run_id = ?
            order by stage_order desc, started_at desc
            limit 1
            """,
            (dream_run_id,),
        ).fetchone()
        if stage:
            stage_name = _v2_stage_display(str(stage["stage_name"] or "")).get("label", str(stage["stage_name"] or "Stage"))
            stage_status = str(stage["status"] or "running")
            return f"{stage_status} · {stage_name} · entities pending · relations pending"
        return f"{status or pipeline_status or 'running'} · entities pending · relations pending"
    if status == "failed" or pipeline_status == "failed":
        failed_stage = str(row.get("failed_stage") or "").strip()
        if failed_stage:
            label = _v2_stage_display(failed_stage).get("label", failed_stage)
            return f"failed · {label}"
        return "failed"
    deterministic = conn.execute(
        """
        select artifact_type, entity_count, relation_count
        from graph_artifacts
        where dream_run_id = ?
          and artifact_type in ('facts', 'patch')
        order by case artifact_type when 'patch' then 0 else 1 end, created_at desc
        limit 1
        """,
        (dream_run_id,),
    ).fetchone()
    det_entities = int((deterministic["entity_count"] if deterministic else 0) or 0)
    det_relations = int((deterministic["relation_count"] if deterministic else 0) or 0)
    sem_entities = int(
        conn.execute(
            "select count(*) as c from semantic_entities where source_dream_run_id = ?",
            (dream_run_id,),
        ).fetchone()["c"]
        or 0
    )
    sem_relations = int(
        conn.execute(
            "select count(*) as c from semantic_relations where source_dream_run_id = ?",
            (dream_run_id,),
        ).fetchone()["c"]
        or 0
    )
    decisions = int(
        conn.execute(
            "select count(*) as c from reconciliation_decisions where dream_run_id = ?",
            (dream_run_id,),
        ).fetchone()["c"]
        or 0
    )
    reviews = int(
        conn.execute(
            """
            select count(*) as c
            from reconciliation_decisions
            where dream_run_id = ?
              and (status = 'deferred_review' or review_required = 1)
            """,
            (dream_run_id,),
        ).fetchone()["c"]
        or 0
    )
    meta = f"{status or pipeline_status or 'succeeded'} · {det_entities} det / {sem_entities} sem entities · {det_relations} det / {sem_relations} sem relations"
    if decisions or reviews:
        meta = f"{meta} · {decisions} decisions"
        if reviews:
            meta = f"{meta} · {reviews} review"
    return meta


def _dream_count_preview(conn: Any, row: dict[str, Any]) -> dict[str, int]:
    dream_run_id = str(row.get("dream_run_id") or "")
    if not dream_run_id:
        return {
            "v2_deterministic_entity_count": 0,
            "v2_deterministic_relation_count": 0,
            "v2_semantic_entity_count": 0,
            "v2_semantic_relation_count": 0,
        }
    deterministic = conn.execute(
        """
        select artifact_type, entity_count, relation_count
        from graph_artifacts
        where dream_run_id = ?
          and artifact_type in ('facts', 'patch')
        order by case artifact_type when 'patch' then 0 else 1 end, created_at desc
        limit 1
        """,
        (dream_run_id,),
    ).fetchone()
    return {
        "v2_deterministic_entity_count": int((deterministic["entity_count"] if deterministic else 0) or 0),
        "v2_deterministic_relation_count": int((deterministic["relation_count"] if deterministic else 0) or 0),
        "v2_semantic_entity_count": int(
            conn.execute(
                "select count(*) as c from semantic_entities where source_dream_run_id = ?",
                (dream_run_id,),
            ).fetchone()["c"]
            or 0
        ),
        "v2_semantic_relation_count": int(
            conn.execute(
                "select count(*) as c from semantic_relations where source_dream_run_id = ?",
                (dream_run_id,),
            ).fetchone()["c"]
            or 0
        ),
    }


def _session_dream_count_preview(conn: Any, session_id: str) -> dict[str, int]:
    dream_run_ids = [
        str(row["dream_run_id"] or "")
        for row in conn.execute(
            """
            select dream_run_id
            from dream_runs
            where session_id = ?
            order by input_event_seq_from desc, started_at desc
            """,
            (session_id,),
        )
    ]
    det_entities = 0
    det_relations = 0
    for dream_run_id in dream_run_ids:
        if not dream_run_id:
            continue
        counts = _dream_count_preview(conn, {"dream_run_id": dream_run_id})
        det_entities += int(counts.get("v2_deterministic_entity_count") or 0)
        det_relations += int(counts.get("v2_deterministic_relation_count") or 0)
    sem_entities = int(
        conn.execute(
            """
            select count(distinct entity_key) as c
            from semantic_entities
            where source_session_id = ?
              and status = 'active'
            """,
            (session_id,),
        ).fetchone()["c"]
        or 0
    )
    sem_relations = int(
        conn.execute(
            """
            select count(distinct relation_key) as c
            from semantic_relations
            where source_session_id = ?
              and status = 'active'
            """,
            (session_id,),
        ).fetchone()["c"]
        or 0
    )
    return {
        "session_deterministic_entity_count": det_entities,
        "session_deterministic_relation_count": det_relations,
        "session_semantic_entity_count": sem_entities,
        "session_semantic_relation_count": sem_relations,
    }


def _client_filter_sql(alias: str, client_type: str | None, params: list[Any]) -> str:
    if not client_type:
        return ""
    params.append(client_type)
    return f" and {alias}.client_type = ?"


def _session_activity(row: dict[str, Any]) -> tuple[str, int | None, str]:
    last = parse_time(str(row.get("last_event_at") or row.get("started_at") or ""))
    if last is None:
        return str(row.get("status") or "unknown"), None, "unknown"
    age_seconds = max(0, int((datetime.now(timezone.utc) - _as_utc(last)).total_seconds()))
    if row.get("status") == "stopped":
        activity = "stopped"
    elif age_seconds <= 300:
        activity = "active"
    else:
        activity = "idle"
    if age_seconds < 60:
        label = f"{age_seconds}s ago"
    elif age_seconds < 3600:
        label = f"{age_seconds // 60}m ago"
    elif age_seconds < 86_400:
        label = f"{age_seconds // 3600}h ago"
    else:
        label = f"{age_seconds // 86_400}d ago"
    return activity, age_seconds, label


def _session_page_token_totals(conn: Any, session_ids: list[str]) -> dict[str, dict[str, int]]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    rows = conn.execute(
        f"""
        with token_turns as (
          select session_id,
                 coalesce(turn_id, 'row:' || id) as turn_key,
                 max(coalesce(input_tokens, 0)) as input_tokens,
                 max(coalesce(cached_input_tokens, 0)) as cached_input_tokens,
                 max(coalesce(output_tokens, 0)) as output_tokens,
                 max(coalesce(reasoning_output_tokens, 0)) as reasoning_tokens,
                 max(coalesce(total_tokens, 0)) as total_tokens
          from token_usage
          where session_id in ({placeholders})
          group by session_id, turn_key
        )
        select session_id,
               coalesce(sum(input_tokens), 0) as input_tokens,
               coalesce(sum(cached_input_tokens), 0) as cached_input_tokens,
               coalesce(sum(output_tokens), 0) as output_tokens,
               coalesce(sum(reasoning_tokens), 0) as reasoning_tokens,
               coalesce(sum(total_tokens), 0) as total_tokens
        from token_turns
        group by session_id
        """,
        session_ids,
    ).fetchall()
    return {
        row["session_id"]: {
            "input_tokens": int(row["input_tokens"] or 0),
            "cached_input_tokens": int(row["cached_input_tokens"] or 0),
            "output_tokens": int(row["output_tokens"] or 0),
            "reasoning_tokens": int(row["reasoning_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
        }
        for row in rows
    }


def _session_page_dream_totals(conn: Any, session_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not session_ids:
        return {}
    placeholders = ",".join("?" for _ in session_ids)
    rows = conn.execute(
        f"""
        select session_id,
               count(*) as dream_count,
               max(started_at) as last_dream_started_at,
               coalesce(sum(total_tokens), 0) as dream_total_tokens
        from dream_runs
        where session_id in ({placeholders})
        group by session_id
        """,
        session_ids,
    ).fetchall()
    return {
        row["session_id"]: {
            "dream_count": int(row["dream_count"] or 0),
            "last_dream_started_at": row["last_dream_started_at"],
            "dream_total_tokens": int(row["dream_total_tokens"] or 0),
        }
        for row in rows
    }


def _session_dream_token_totals(conn: Any, session_id: str) -> dict[str, int]:
    row = conn.execute(
        """
        select coalesce(sum(prompt_tokens), 0) as prompt_tokens,
               coalesce(sum(cached_prompt_tokens), 0) as cached_prompt_tokens,
               coalesce(sum(completion_tokens), 0) as completion_tokens,
               coalesce(sum(reasoning_tokens), 0) as reasoning_tokens,
               coalesce(sum(total_tokens), 0) as total_tokens
        from dream_runs
        where session_id = ?
        """,
        (session_id,),
    ).fetchone()
    item = _row_dict(row) if row else {}
    return {
        "prompt_tokens": int(item.get("prompt_tokens") or 0),
        "cached_prompt_tokens": int(item.get("cached_prompt_tokens") or 0),
        "completion_tokens": int(item.get("completion_tokens") or 0),
        "reasoning_tokens": int(item.get("reasoning_tokens") or 0),
        "total_tokens": int(item.get("total_tokens") or 0),
    }


def _add_session_lag_fields(item: dict[str, Any]) -> None:
    new_summary = max(int(item.get("last_event_seq") or 0) - int(item.get("last_summary_event_seq") or 0), 0)
    new_dream = max(int(item.get("last_event_seq") or 0) - int(item.get("last_dream_event_seq") or 0), 0)
    item["new_events_since_summary"] = new_summary
    item["new_events_since_dream"] = new_dream
    item["pending_summary_windows"] = 1 if new_summary > 0 or item.get("summary_status") == "summary_pending" else 0
    item["pending_dream_windows"] = 1 if new_dream > 0 or item.get("dream_status") == "dream_pending" else 0


def monitor_sessions(
    limit: int = 25,
    offset: int = 0,
    query: str | None = None,
    client_type: str | None = None,
    project_id: str | None = None,
    workdir: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    conn = connect()
    where = "where 1=1"
    params: list[Any] = []
    where += _client_filter_sql("s", client_type, params)
    if project_id:
        where += " and s.project_id = ?"
        params.append(project_id)
    where += _folder_filter_sql("s", workdir, params)
    if query:
        like = f"%{query}%"
        where += """
          and (
            s.session_id like ? or coalesce(s.thread_name, '') like ?
            or coalesce(s.session_brief, '') like ? or coalesce(s.project_id, '') like ?
            or coalesce(s.cwd, '') like ? or coalesce(s.last_workdir, '') like ?
          )
        """
        params.extend([like, like, like, like, like, like])
    if kind and kind.strip().lower() == "risky":
        where += """
          and exists (
            select 1
            from risk_events re
            where re.session_id = s.session_id
              and coalesce(re.status, '') not in ('allowed', 'reviewed_safe', 'review_consumed')
          )
        """
    total = conn.execute(f"select count(*) as c from sessions s {where}", params).fetchone()["c"]
    rows = list(
        conn.execute(
        f"""
            select s.*,
                   sm.summary_path,
                   sm.summary_kind,
                   sm.created_at as summary_created_at,
                   sm.input_event_count as summary_input_event_count,
                   (
                     select coalesce(
                       nullif(ev.last_assistant_message, ''),
                       nullif(ev.tool_response_text, ''),
                       nullif(ev.prompt, ''),
                       nullif(ev.tool_input_json, ''),
                       nullif(ev.event_name, '')
                     )
                     from events ev
                     where ev.session_id = s.session_id
                     order by ev.seq desc, ev.recorded_at desc
                     limit 1
                   ) as latest_event_preview
            from sessions s
            left join summaries sm on sm.session_id = s.session_id
            {where}
            order by coalesce(s.last_event_at, s.started_at, '') desc
            limit ? offset ?
            """,
            (*params, max(1, min(limit, 200)), max(0, offset)),
        )
        )
    session_ids = [row["session_id"] for row in rows]
    token_totals = _session_page_token_totals(conn, session_ids)
    dream_totals = _session_page_dream_totals(conn, session_ids)
    session_handover_cache: dict[str, dict[str, Any]] = {}
    sessions: list[dict[str, Any]] = []
    for row in rows:
        resolved = refresh_session_row_metadata(conn, row, persist=False)
        item = _row_dict(row)
        for key in ("thread_name", "session_brief", "transcript_path", "native_resume_command"):
            if resolved.get(key):
                item[key] = resolved[key]
        if not item.get("summary_path"):
            handover = session_handover_cache.get(item["session_id"])
            if handover is None:
                handover = _resolve_session_handover_from_v2(conn, item["session_id"])
                session_handover_cache[item["session_id"]] = handover or {}
            if handover:
                item["summary_path"] = handover["summary_path"]
                item["summary_kind"] = handover["summary_kind"]
                item["summary_created_at"] = handover["created_at"]
                item["summary_input_event_count"] = handover["input_event_count"]
        item.update(
            {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "total_tokens": 0,
                **token_totals.get(item["session_id"], {}),
            }
        )
        item.update(
            {
                "dream_count": 0,
                "last_dream_started_at": None,
                "dream_total_tokens": 0,
                **dream_totals.get(item["session_id"], {}),
            }
        )
        summary_text = _read_relative_text(item.get("summary_path"), max_chars=1200)
        if not summary_text:
            handover = session_handover_cache.get(item["session_id"])
            if handover is None:
                handover = _resolve_session_handover_from_v2(conn, item["session_id"])
                session_handover_cache[item["session_id"]] = handover or {}
            if handover:
                item["summary_path"] = handover["summary_path"]
                item["summary_kind"] = handover["summary_kind"]
                item["summary_created_at"] = handover["created_at"]
                item["summary_input_event_count"] = handover["input_event_count"]
                summary_text = _read_relative_text(item.get("summary_path"), max_chars=1200)

        activity, age_seconds, label = _session_activity(item)
        item["activity_status"] = activity
        item["last_seen_age_seconds"] = age_seconds
        item["last_seen_label"] = label
        _add_session_lag_fields(item)
        if summary_text:
            item["summary_preview"] = _compact_preview_text(summary_text, limit=360)
        else:
            item["summary_preview"] = ""
        latest_dream = conn.execute(
            """
            select *
            from dream_runs
            where session_id = ?
            order by input_event_seq_from desc, started_at desc
            limit 1
            """,
            (item["session_id"],),
        ).fetchone()
        latest_dream_item = _row_dict(latest_dream) if latest_dream else {}
        dream_summary_preview, dream_summary_title = _latest_dream_preview_light(
            latest_dream_item,
            session_brief=item.get("session_brief"),
        )
        item["dream_summary_preview"] = _compact_preview_text(dream_summary_preview, limit=240)
        item["dream_summary_title"] = dream_summary_title
        item["dream_meta_preview"] = _compact_preview_text(
            _dream_meta_preview(conn, latest_dream_item),
            limit=240,
        )
        item["latest_activity_summary"] = (
            _compact_preview_text(item.get("latest_event_preview"), limit=240)
            or item["summary_preview"]
            or _compact_preview_text(item.get("session_brief"), limit=240)
            or label
        )
        risk_summary, _risk_rows = _session_risk_payload(conn, item["session_id"], limit=8)
        item["risk_summary"] = risk_summary
        sessions.append(item)
    options = monitor_filter_options()
    return {
        "sessions": sessions,
        "total": int(total or 0),
        "limit": max(1, min(limit, 200)),
        "offset": max(0, offset),
        "clients": options["clients"],
        "projects": options["projects"],
        "workdirs": options["workdirs"],
    }

def _normalize_session_detail_includes(include: str | None) -> set[str] | None:
    if include is None:
        return None
    tokens = {token.strip().lower() for token in include.split(",") if token.strip()}
    tokens.discard("base")
    return tokens


def _latest_session_dream(conn: Any, session: dict[str, Any]) -> dict[str, Any]:
    session_id = str(session.get("session_id") or "")
    row = conn.execute(
        """
        select * from dream_runs
        where session_id = ?
        order by input_event_seq_from desc, started_at desc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    if row is None:
        return {}
    item = _row_dict(row)
    episode_short, episode_title = _latest_dream_preview_light(item, session_brief=session.get("session_brief"))
    item["episode_short"] = episode_short
    item["episode_title"] = episode_title
    item["episode_meta_short"] = _dream_meta_preview(conn, item)
    item.update(_dream_count_preview(conn, item))
    return item


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _session_taint_reset_info(conn: Any, session_id: str) -> tuple[int, int]:
    rows = list(
        conn.execute(
            """
            select event_seq
            from session_taint_resets
            where session_id = ?
            order by event_seq desc
            """,
            (session_id,),
        )
    )
    if not rows:
        return 0, 0
    latest = max(int(row["event_seq"] or 0) for row in rows)
    return len(rows), latest


def _session_taint_sources(conn: Any, session_id: str, *, after_event_seq: int, limit: int = 5) -> list[dict[str, Any]]:
    return [
        _row_dict(row)
        for row in conn.execute(
            """
            select risk_event_id, event_seq, created_at, status, decision, risk_level,
                   sensitivity, approval_state, source_kind, source_ref, reason, impact, preview,
                   categories_json, poisoning_flags_json, deterministic_flags_json, taint_context_json
            from risk_events
            where session_id = ?
              and coalesce(event_seq, 0) > ?
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
            (session_id, after_event_seq, limit),
        )
    ]


def _risk_display_reason(item: dict[str, Any]) -> str:
    flags = set(item.get("categories") or []) | set(item.get("poisoning_flags") or []) | set(item.get("deterministic_flags") or [])
    reason = str(item.get("reason") or "")
    impact = str(item.get("impact") or "")
    text = f"{reason} {impact}".lower()
    if {"classifier_invalid_output", "classifier_schema_violation"} & flags or "classifier runner failed" in text or "valid policy json" in text:
        return "Firewall classifier returned invalid structured output; ACE blocked fail-closed for explicit review."
    taint_context = item.get("taint_context") or []
    if {"tainted_context_side_effect", "approval_required"} & flags:
        for source in taint_context:
            if not isinstance(source, dict):
                continue
            source_flags = set(_json_list(source.get("categories_json"))) | set(_json_list(source.get("poisoning_flags_json")))
            source_reason = str(source.get("reason") or "").lower()
            if {"classifier_invalid_output", "classifier_schema_violation"} & source_flags or "classifier" in source_reason:
                return "Earlier firewall classifier failure tainted this session; this follow-up action needs explicit approval."
    return reason


def _decorate_session_risk_row(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = _row_dict(row) if not isinstance(row, dict) else dict(row)
    item["categories"] = _json_list(item.get("categories_json"))
    item["poisoning_flags"] = _json_list(item.get("poisoning_flags_json"))
    item["deterministic_flags"] = _json_list(item.get("deterministic_flags_json"))
    item["taint_context"] = _json_list(item.get("taint_context_json"))
    item["taint_source_refs"] = [
        str(entry.get("risk_event_id") or "")
        for entry in item["taint_context"]
        if isinstance(entry, dict) and str(entry.get("risk_event_id") or "")
    ]
    item["command_ref"] = f"monitor:risk_events:{item.get('risk_event_id')}" if item.get("risk_event_id") else ""
    approval_token = str(item.get("approval_token") or "")
    if str(item.get("approval_state") or "") == "required" and item.get("risk_event_id") and approval_token:
        item["approval_line"] = f"approve {item['risk_event_id']} {approval_token}"
    else:
        item["approval_line"] = ""
    item["display_reason"] = _risk_display_reason(item)
    item.pop("categories_json", None)
    item.pop("poisoning_flags_json", None)
    item.pop("deterministic_flags_json", None)
    item.pop("taint_context_json", None)
    return item


def _session_risk_payload(conn: Any, session_id: str, *, limit: int = 25) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    risk_rows = list(
        conn.execute(
            """
            select risk_event_id, created_at, updated_at, event_seq, status, decision,
                   risk_level, sensitivity, approval_state, approval_token, tool_name,
                   source_kind, source_ref, reason, impact, preview, categories_json,
                   poisoning_flags_json, deterministic_flags_json, command_hash,
                   taint_context_json
            from risk_events
            where session_id = ?
            order by coalesce(event_seq, 0) desc, created_at desc
            limit ?
            """,
            (session_id, limit),
        )
    )
    decorated_rows = [_decorate_session_risk_row(row) for row in risk_rows]
    totals = conn.execute(
        """
        select
          count(*) as total,
          sum(case when status = 'blocked' then 1 else 0 end) as blocked_count,
          sum(case when status = 'warned' then 1 else 0 end) as warned_count,
          sum(case when status = 'quarantined' then 1 else 0 end) as quarantined_count,
          sum(case when approval_state = 'required' then 1 else 0 end) as pending_approval_count,
          sum(
            case
              when approval_state = 'required'
                or status in ('blocked', 'quarantined')
              then 1 else 0
            end
          ) as open_count
        from risk_events
        where session_id = ?
        """,
        (session_id,),
    ).fetchone()
    taint_reset_count, latest_taint_reset_seq = _session_taint_reset_info(conn, session_id)
    taint_sources = _session_taint_sources(conn, session_id, after_event_seq=latest_taint_reset_seq)
    latest = decorated_rows[0] if decorated_rows else {}
    latest_open = next(
        (
            row
            for row in decorated_rows
            if row.get("approval_state") == "required" or row.get("status") in {"blocked", "quarantined"}
        ),
        {},
    )
    summary = {
        "total": int(totals["total"] or 0) if totals else 0,
        "blocked_count": int(totals["blocked_count"] or 0) if totals else 0,
        "warned_count": int(totals["warned_count"] or 0) if totals else 0,
        "quarantined_count": int(totals["quarantined_count"] or 0) if totals else 0,
        "open_count": int(totals["open_count"] or 0) if totals else 0,
        "pending_approval_count": int(totals["pending_approval_count"] or 0) if totals else 0,
        "taint_active": bool(taint_sources),
        "taint_reset_count": taint_reset_count,
        "latest_taint_reset_event_seq": latest_taint_reset_seq,
        "latest_risk_event_id": latest.get("risk_event_id"),
        "latest_risk_level": latest.get("risk_level"),
        "latest_risk_status": latest.get("status"),
        "latest_risk_reason": latest.get("display_reason") or latest.get("reason"),
        "latest_risk_created_at": latest.get("created_at"),
        "latest_open_risk_event_id": latest_open.get("risk_event_id"),
        "latest_open_risk_reason": latest_open.get("display_reason") or latest_open.get("reason"),
        "latest_open_risk_status": latest_open.get("status"),
        "taint_sources": [_decorate_session_risk_row(item) for item in taint_sources],
        "controls": {
            "reset_taint": "reset taint",
            "firewall_disable_session": "firewall disable session",
            "firewall_disable_session_30m": "firewall disable session 30m",
            "firewall_enable_session": "firewall enable session",
            "hooks_disable": "hooks-disable",
            "hooks_disable_opencode": "hooks-disable --runner opencode",
            "hooks_enable": "hooks-enable",
            "hooks_status": "hooks-status",
        },
    }
    return summary, decorated_rows


def monitor_session_detail(
    session_id: str,
    *,
    event_limit: int = 200,
    event_offset: int = 0,
    include: str | None = None,
) -> dict[str, Any]:
    conn = connect()
    session = conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
    if session is None:
        raise ValueError(f"session not found: {session_id}")
    resolved = refresh_session_row_metadata(conn, session, persist=False)
    session = conn.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
    if session is None:
        raise ValueError(f"session not found: {session_id}")
    include_sections = _normalize_session_detail_includes(include)
    include_all = include_sections is None
    event_limit = max(1, min(int(event_limit), 500))
    event_offset = max(0, int(event_offset))
    summary = conn.execute("select * from summaries where session_id = ?", (session_id,)).fetchone()
    summary_item = _row_dict(summary) if summary else {}
    if not summary_item.get("summary_path"):
        handover = _resolve_session_handover_from_v2(conn, session_id)
        if handover:
            summary_item.update(handover)
    summary_preview_text = _read_relative_text(summary_item.get("summary_path"), max_chars=1600)
    summary_item["content"] = ""
    if include_all or "summary" in include_sections:
        summary_item["content"] = _read_relative_text(summary_item.get("summary_path"), max_chars=200_000)
        if not summary_item["content"]:
            handover = _resolve_session_handover_from_v2(conn, session_id)
            if handover:
                summary_item.update(handover)
                summary_preview_text = _read_relative_text(summary_item.get("summary_path"), max_chars=1600)
                summary_item["content"] = _read_relative_text(summary_item.get("summary_path"), max_chars=200_000)

    dreams: list[dict[str, Any]] = []
    if include_all or "dreams" in include_sections:
        for row in conn.execute(
            """
            select * from dream_runs
            where session_id = ?
            order by input_event_seq_from desc, started_at desc
            """,
            (session_id,),
        ):
            item = _row_dict(row)
            files = _dream_file_items(item)
            episode_short, episode_title = _dream_episode_short(files, item)
            item["memory_files"] = files
            item["audit_files"] = _dream_audit_file_items(item)
            item["downstream_files"] = _dream_downstream_file_items(conn, item)
            _attach_v2_dream_details(conn, item)
            item["episode_short"] = episode_short
            item["episode_title"] = episode_title
            item["episode_meta_short"] = _dream_meta_preview(conn, item)
            item.update(_dream_count_preview(conn, item))
            dreams.append(item)

    graph_artifacts: list[dict[str, Any]] = []
    if include_all or "graph_artifacts" in include_sections:
        graph_artifacts = [
            _row_dict(row)
            for row in conn.execute(
                """
                select graph_artifact_id, session_id, dream_run_id, artifact_type, path,
                       created_at, status, entity_count, relation_count, evidence_count,
                       runner, intent, helpful_score, tags_json, error_message
                from graph_artifacts
                where session_id = ?
                order by created_at desc
                """,
                (session_id,),
            )
        ]
    events_total = int(conn.execute("select count(*) as c from events where session_id = ?", (session_id,)).fetchone()["c"] or 0)
    events: list[dict[str, Any]] = []
    if include_all or "events" in include_sections:
        events = [
            _row_dict(row)
            for row in conn.execute(
                """
                select seq, event_name, recorded_at, client_type, cwd, project_id, turn_id,
                       tool_name, tool_use_id, prompt, tool_input_json, tool_response_text,
                       last_assistant_message, transcript_path, source_id
                from events
                where session_id = ?
                order by seq asc, recorded_at asc
                limit ? offset ?
                """,
                (session_id, event_limit, event_offset),
            )
        ]
        output_refs = {
            row["seq"]: _row_dict(row)
            for row in conn.execute(
                """
                select tc.seq, tc.tool_name, tc.status as call_status,
                       out.tool_output_id, out.status as output_status, out.byte_count,
                       out.char_count, out.line_count, out.sha256, out.storage_kind, out.path
                from tool_calls tc
                left join tool_outputs out on out.tool_output_id = tc.output_id
                where tc.session_id = ?
                """,
                (session_id,),
            )
        }
        for event in events:
            event["tool_output_ref"] = output_refs.get(event["seq"])
    token_totals = conn.execute(
        """
        select coalesce(sum(input_tokens), 0) as input_tokens,
               coalesce(sum(cached_input_tokens), 0) as cached_input_tokens,
               coalesce(sum(output_tokens), 0) as output_tokens,
               coalesce(sum(reasoning_output_tokens), 0) as reasoning_tokens,
               coalesce(sum(total_tokens), 0) as total_tokens
        from (
          select coalesce(turn_id, 'row:' || id) as turn_key,
                 max(coalesce(input_tokens, 0)) as input_tokens,
                 max(coalesce(cached_input_tokens, 0)) as cached_input_tokens,
                 max(coalesce(output_tokens, 0)) as output_tokens,
                 max(coalesce(reasoning_output_tokens, 0)) as reasoning_output_tokens,
                 max(coalesce(total_tokens, 0)) as total_tokens
          from token_usage
          where session_id = ?
          group by turn_key
        )
        """,
        (session_id,),
    ).fetchone()
    session_item = _row_dict(session)
    for key in ("thread_name", "session_brief", "transcript_path", "native_resume_command"):
        if resolved.get(key):
            session_item[key] = resolved[key]
    activity, age_seconds, label = _session_activity(session_item)
    session_item["activity_status"] = activity
    session_item["last_seen_age_seconds"] = age_seconds
    _add_session_lag_fields(session_item)
    session_item["summary_preview"] = _compact_preview_text(summary_preview_text or summary_item.get("content"), limit=360)
    latest_event_preview_row = conn.execute(
        """
        select coalesce(
                 nullif(last_assistant_message, ''),
                 nullif(tool_response_text, ''),
                 nullif(prompt, ''),
                 nullif(tool_input_json, ''),
                 nullif(event_name, '')
               ) as preview
        from events
        where session_id = ?
        order by seq desc, recorded_at desc
        limit 1
        """,
        (session_id,),
    ).fetchone()
    latest_event_preview = _row_dict(latest_event_preview_row) if latest_event_preview_row else {}
    session_item["latest_activity_summary"] = (
        _compact_preview_text(latest_event_preview.get("preview"), limit=240)
        or session_item["summary_preview"]
        or _compact_preview_text(session_item.get("session_brief"), limit=240)
        or label
    )
    latest_dream = _latest_session_dream(conn, session_item)
    session_item["dream_summary_preview"] = _compact_preview_text(
        latest_dream.get("episode_short"),
        limit=240,
    )
    session_item["dream_summary_title"] = latest_dream.get("episode_title")
    session_item["dream_meta_preview"] = _compact_preview_text(latest_dream.get("episode_meta_short"), limit=260)
    session_item.update(_session_dream_count_preview(conn, session_id))
    messages: list[dict[str, Any]] = []
    if include_all or "messages" in include_sections:
        messages = _session_transcript_messages(session_item)
    risk_summary, risk_events = _session_risk_payload(conn, session_id, limit=40)
    return {
        "session": session_item,
        "last_seen_label": label,
        "summary": summary_item,
        "latest_dream": latest_dream,
        "messages": messages,
        "dreams": dreams,
        "graph_artifacts": graph_artifacts,
        "analysis_reports": _session_analysis_reports(session_id) if include_all or "analysis_reports" in include_sections else [],
        "events": events,
        "events_total": events_total,
        "events_limit": event_limit,
        "events_offset": event_offset,
        "token_totals": _row_dict(token_totals),
        "dream_token_totals": _session_dream_token_totals(conn, session_id),
        "risk_summary": risk_summary,
        "risk_events": risk_events,
    }


def _attach_v2_dream_details(conn: Any, item: dict[str, Any]) -> None:
    dream_run_id = str(item.get("dream_run_id") or "")

    def _safe_json(value: Any, default: Any) -> Any:
        if not value:
            return default
        if isinstance(value, (dict, list)):
            return value
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return default
        return parsed if parsed is not None else default

    if not dream_run_id or int(item.get("pipeline_version") or 1) != 2:
        item["v2_stages"] = []
        item["v2_artifacts"] = []
        item["v2_audit_entries"] = []
        item["v2_semantic_proposals"] = []
        item["v2_reconciliation_decisions"] = []
        item["v2_graph_artifacts"] = []
        item["v2_deterministic_entities"] = []
        item["v2_deterministic_relations"] = []
        item["v2_deterministic_source"] = {}
        item["v2_deterministic_patch_entities"] = []
        item["v2_deterministic_patch_relations"] = []
        item["v2_deterministic_patch_source"] = {}
        item["v2_semantic_entities"] = []
        item["v2_semantic_relations"] = []
        item["v2_review_items"] = []
        return
    stages: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        select *
        from dream_stage_runs
        where dream_run_id = ?
        order by stage_order
        """,
        (dream_run_id,),
    ):
        stage = _row_dict(row)
        for json_key in ("metadata_json", "validation_json"):
            try:
                stage[json_key.removesuffix("_json")] = json.loads(stage.get(json_key) or "{}")
            except json.JSONDecodeError:
                stage[json_key.removesuffix("_json")] = {}
        files: list[dict[str, Any]] = []
        for role, kind in (
            ("prompt_path", "prompt"),
            ("raw_output_path", "raw_output"),
            ("parsed_output_path", "parsed_output"),
            ("artifact_path", "artifact"),
        ):
            path = stage.get(role)
            if path:
                files.append(
                    {
                        "role": role.removesuffix("_path"),
                        "kind": kind,
                        "path": path,
                        "content": _read_relative_text(path, max_chars=500_000),
                    }
                )
        stage["files"] = files
        stage["file_count"] = len(files)
        stage.update(_v2_stage_display(str(stage.get("stage_name") or "")))
        stages.append(stage)
    artifacts: list[dict[str, Any]] = []
    for row in conn.execute(
        """
        select *
        from dream_artifacts
        where dream_run_id = ?
        order by created_at, artifact_role
        """,
        (dream_run_id,),
    ):
        artifact = _row_dict(row)
        artifact["content"] = _read_relative_text(artifact.get("path"), max_chars=220_000)
        try:
            artifact["metadata"] = json.loads(artifact.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            artifact["metadata"] = {}
        artifacts.append(artifact)
    audits = [
        _row_dict(row)
        for row in conn.execute(
            """
            select *
            from dream_audit_entries
            where dream_run_id = ?
            order by created_at
            """,
            (dream_run_id,),
        )
    ]
    proposals = [
        _row_dict(row)
        for row in conn.execute(
            """
            select semantic_proposal_id, proposal_kind, proposed_type, proposed_name,
                   confidence, status, review_required, review_reason,
                   aliases_json, summary, properties_json, evidence_json, validation_json
            from semantic_proposals
            where dream_run_id = ?
            order by created_at
            """,
            (dream_run_id,),
        )
    ]
    for row in proposals:
        row["aliases"] = _safe_json(row.pop("aliases_json", None), [])
        row["properties"] = _safe_json(row.pop("properties_json", None), {})
        row["evidence"] = _safe_json(row.pop("evidence_json", None), [])
        row["validation"] = _safe_json(row.pop("validation_json", None), {})
    decisions = [
        _row_dict(row)
        for row in conn.execute(
            """
            select reconciliation_decision_id, semantic_proposal_id, decision,
                   target_key, confidence, reason, human_summary, status,
                   review_required, review_reason, applied_at
            from reconciliation_decisions
            where dream_run_id = ?
            order by created_at
            """,
            (dream_run_id,),
        )
    ]
    try:
        mutations = [
            _row_dict(row)
            for row in conn.execute(
                """
                select mutation_id, dream_run_id, reconciliation_decision_id,
                       target_kind, target_id, target_key, mutation_kind,
                       mutation_summary, before_snapshot_json, after_snapshot_json,
                       created_at, source_dream_run_id, source_session_id
                from semantic_projection_mutations
                where dream_run_id = ?
                order by created_at, mutation_id
                """,
                (dream_run_id,),
            )
        ]
    except sqlite3.Error:
        mutations = []
    for row in mutations:
        row["before_snapshot"] = _safe_json(row.pop("before_snapshot_json", None), {})
        row["after_snapshot"] = _safe_json(row.pop("after_snapshot_json", None), {})
    mutations_by_target: dict[str, list[dict[str, Any]]] = {}
    mutations_by_decision: dict[str, list[dict[str, Any]]] = {}
    for mutation in mutations:
        target_id = str(mutation.get("target_id") or "")
        target_key = str(mutation.get("target_key") or "")
        if target_id:
            mutations_by_target.setdefault(target_id, []).append(mutation)
        if target_key:
            mutations_by_target.setdefault(target_key, []).append(mutation)
        decision_id = str(mutation.get("reconciliation_decision_id") or "")
        if decision_id:
            mutations_by_decision.setdefault(decision_id, []).append(mutation)
    latest_entity_updates = {
        str(row["entity_key"]): str(row["updated_at"] or "")
        for row in conn.execute(
            """
            select entity_key, max(updated_at) as updated_at
            from semantic_entities
            group by entity_key
            """
        )
    }
    latest_relation_updates = {
        str(row["relation_key"]): str(row["updated_at"] or "")
        for row in conn.execute(
            """
            select relation_key, max(updated_at) as updated_at
            from semantic_relations
            group by relation_key
            """
        )
    }
    for row in decisions:
        row["mutations"] = list(mutations_by_decision.get(str(row.get("reconciliation_decision_id") or ""), []))
    graph_sections = _dream_graph_sections(conn, dream_run_id)
    semantic_entities = [
        _row_dict(row)
        for row in conn.execute(
            """
            select semantic_entity_id, entity_key, entity_type, name, aliases_json,
                   summary, properties_json, confidence, source_session_id,
                   source_dream_run_id, evidence_json, status,
                   created_at, updated_at
            from semantic_entities
            where source_dream_run_id = ?
            order by entity_type, entity_key
            """,
            (dream_run_id,),
        )
    ]
    for row in semantic_entities:
        row["aliases"] = _safe_json(row.pop("aliases_json", None), [])
        row["properties"] = _safe_json(row.pop("properties_json", None), {})
        row["evidence"] = _safe_json(row.pop("evidence_json", None), [])
        target_id = str(row.get("semantic_entity_id") or "")
        target_key = str(row.get("entity_key") or "")
        row["mutations"] = list(mutations_by_target.get(target_id, []) or mutations_by_target.get(target_key, []))
        row["was_updated"] = any(
            str(mutation.get("mutation_kind") or "") in {"updated", "merged", "superseded"}
            for mutation in row["mutations"]
        ) or str(row.get("created_at") or "") != str(row.get("updated_at") or "")
        latest_update = latest_entity_updates.get(target_key, "")
        row["has_newer_version"] = bool(latest_update and str(row.get("updated_at") or "") < latest_update)
        row["is_latest_version"] = bool(latest_update and str(row.get("updated_at") or "") == latest_update)
    semantic_relations = [
        _row_dict(row)
        for row in conn.execute(
            """
            select semantic_relation_id, relation_key, relation_type,
                   source_entity_key, target_entity_key, summary,
                   properties_json, confidence, source_session_id,
                   source_dream_run_id, evidence_json, status,
                   created_at, updated_at
            from semantic_relations
            where source_dream_run_id = ?
            order by relation_type, relation_key
            """,
            (dream_run_id,),
        )
    ]
    for row in semantic_relations:
        row["properties"] = _safe_json(row.pop("properties_json", None), {})
        row["evidence"] = _safe_json(row.pop("evidence_json", None), [])
        target_id = str(row.get("semantic_relation_id") or "")
        target_key = str(row.get("relation_key") or "")
        row["mutations"] = list(mutations_by_target.get(target_id, []) or mutations_by_target.get(target_key, []))
        row["was_updated"] = any(
            str(mutation.get("mutation_kind") or "") in {"updated", "merged", "superseded"}
            for mutation in row["mutations"]
        ) or str(row.get("created_at") or "") != str(row.get("updated_at") or "")
        latest_update = latest_relation_updates.get(target_key, "")
        row["has_newer_version"] = bool(latest_update and str(row.get("updated_at") or "") < latest_update)
        row["is_latest_version"] = bool(latest_update and str(row.get("updated_at") or "") == latest_update)
    item["v2_stages"] = stages
    item["v2_artifacts"] = artifacts
    item["v2_audit_entries"] = audits
    item["v2_semantic_proposals"] = proposals
    item["v2_reconciliation_decisions"] = decisions
    item["v2_semantic_mutations"] = mutations
    item["v2_graph_artifacts"] = graph_sections["artifacts"]
    item["v2_deterministic_entities"] = graph_sections["facts"]["entities"]
    item["v2_deterministic_relations"] = graph_sections["facts"]["relations"]
    item["v2_deterministic_source"] = graph_sections["facts"]["artifact"]
    item["v2_deterministic_patch_entities"] = graph_sections["patch"]["entities"]
    item["v2_deterministic_patch_relations"] = graph_sections["patch"]["relations"]
    item["v2_deterministic_patch_source"] = graph_sections["patch"]["artifact"]
    item["v2_semantic_entities"] = semantic_entities
    item["v2_semantic_relations"] = semantic_relations
    item["v2_review_items"] = [row for row in decisions if row.get("status") == "deferred_review" or row.get("review_required")]


def monitor_stats(
    range_name: str = "2d",
    start: str | None = None,
    end: str | None = None,
    client_type: str | None = None,
    project_id: str | None = None,
    workdir: str | None = None,
) -> dict[str, Any]:
    conn = connect()
    start_dt, end_dt = _stats_window(range_name, start, end)
    params: list[Any] = [_sqlite_time(start_dt), _sqlite_time(end_dt)]
    session_where = "where datetime(tu.recorded_at) >= datetime(?) and datetime(tu.recorded_at) < datetime(?)"
    session_where += _client_filter_sql("s", client_type, params)
    if project_id:
        session_where += " and s.project_id = ?"
        params.append(project_id)
    session_where += _folder_filter_sql("s", workdir, params)
    session_rows = list(
        conn.execute(
            f"""
            with token_turns as (
              select strftime('%Y-%m-%dT%H:00:00Z', tu.recorded_at) as hour,
                     tu.session_id,
                     coalesce(tu.turn_id, 'row:' || tu.id) as turn_key,
                     max(coalesce(tu.input_tokens, 0)) as input_tokens,
                     max(coalesce(tu.cached_input_tokens, 0)) as cached_input_tokens,
                     max(coalesce(tu.output_tokens, 0)) as output_tokens,
                     max(coalesce(tu.reasoning_output_tokens, 0)) as reasoning_output_tokens,
                     max(coalesce(tu.total_tokens, 0)) as total_tokens
              from token_usage tu
              join sessions s on s.session_id = tu.session_id
              {session_where}
              group by hour, tu.session_id, turn_key
            )
            select hour,
                   coalesce(sum(input_tokens), 0) as session_input_tokens,
                   coalesce(sum(cached_input_tokens), 0) as session_cached_input_tokens,
                   coalesce(sum(output_tokens), 0) as session_output_tokens,
                   coalesce(sum(reasoning_output_tokens), 0) as session_reasoning_tokens,
                   coalesce(sum(total_tokens), 0) as session_total_tokens,
                   count(distinct session_id) as session_count
            from token_turns
            group by hour
            """,
            params,
        )
    )

    dream_params: list[Any] = [_sqlite_time(start_dt), _sqlite_time(end_dt)]
    dream_where = "where datetime(dr.started_at) >= datetime(?) and datetime(dr.started_at) < datetime(?)"
    if client_type:
        dream_where += " and coalesce(s.client_type, dr.client_type) = ?"
        dream_params.append(client_type)
    if project_id:
        dream_where += " and s.project_id = ?"
        dream_params.append(project_id)
    dream_where += _folder_filter_sql("s", workdir, dream_params)
    dream_rows = list(
        conn.execute(
            f"""
            select strftime('%Y-%m-%dT%H:00:00Z', dr.started_at) as hour,
                   coalesce(sum(dr.prompt_tokens), 0) as dream_prompt_tokens,
                   coalesce(sum(dr.cached_prompt_tokens), 0) as dream_cached_prompt_tokens,
                   coalesce(sum(dr.completion_tokens), 0) as dream_completion_tokens,
                   coalesce(sum(dr.reasoning_tokens), 0) as dream_reasoning_tokens,
                   coalesce(sum(dr.total_tokens), 0) as dream_total_tokens,
                   count(*) as dream_count
            from dream_runs dr
            left join sessions s on s.session_id = dr.session_id
            {dream_where}
            group by hour
            """,
            dream_params,
        )
    )

    buckets: dict[str, dict[str, Any]] = {}
    cursor = start_dt
    while cursor < end_dt:
        key = _hour_key(cursor)
        buckets[key] = {
            "hour": key,
            "session_input_tokens": 0,
            "session_cached_input_tokens": 0,
            "session_output_tokens": 0,
            "session_reasoning_tokens": 0,
            "session_total_tokens": 0,
            "session_count": 0,
            "dream_prompt_tokens": 0,
            "dream_cached_prompt_tokens": 0,
            "dream_completion_tokens": 0,
            "dream_reasoning_tokens": 0,
            "dream_total_tokens": 0,
            "dream_count": 0,
        }
        cursor += timedelta(hours=1)
    for row in session_rows:
        hour = row["hour"]
        if hour in buckets:
            for key in buckets[hour]:
                if key != "hour" and key in row.keys():
                    buckets[hour][key] = int(row[key] or 0)
    for row in dream_rows:
        hour = row["hour"]
        if hour in buckets:
            for key in buckets[hour]:
                if key != "hour" and key in row.keys():
                    buckets[hour][key] = int(row[key] or 0)

    totals = {key: 0 for key in next(iter(buckets.values())).keys() if key != "hour"} if buckets else {}
    for bucket in buckets.values():
        for key in totals:
            totals[key] += int(bucket.get(key) or 0)

    def _group_rows(sql: str, params: list[Any]) -> list[dict[str, Any]]:
        rows = [_row_dict(row) for row in conn.execute(sql, params)]
        total_all = max(int(totals.get("session_total_tokens") or 0) + int(totals.get("dream_total_tokens") or 0), 0)
        total_session = max(int(totals.get("session_total_tokens") or 0), 0)
        total_dream = max(int(totals.get("dream_total_tokens") or 0), 0)
        for row in rows:
            session_total = int(row.get("session_total_tokens") or 0)
            dream_total = int(row.get("dream_total_tokens") or 0)
            combined = session_total + dream_total
            row["total_tokens"] = combined
            row["session_share"] = (session_total / total_session) if total_session else 0.0
            row["dream_share"] = (dream_total / total_dream) if total_dream else 0.0
            row["total_share"] = (combined / total_all) if total_all else 0.0
        return rows

    session_group_filters: list[Any] = [_sqlite_time(start_dt), _sqlite_time(end_dt)]
    session_group_where = "where datetime(tu.recorded_at) >= datetime(?) and datetime(tu.recorded_at) < datetime(?)"
    session_group_where += _client_filter_sql("s", client_type, session_group_filters)
    if project_id:
        session_group_where += " and s.project_id = ?"
        session_group_filters.append(project_id)
    session_group_where += _folder_filter_sql("s", workdir, session_group_filters)

    dream_group_filters: list[Any] = [_sqlite_time(start_dt), _sqlite_time(end_dt)]
    if client_type:
        dream_group_where = "where datetime(dr.started_at) >= datetime(?) and datetime(dr.started_at) < datetime(?) and coalesce(s.client_type, dr.client_type) = ?"
        dream_group_filters.append(client_type)
    else:
        dream_group_where = "where datetime(dr.started_at) >= datetime(?) and datetime(dr.started_at) < datetime(?)"
    if project_id:
        dream_group_where += " and s.project_id = ?"
        dream_group_filters.append(project_id)
    dream_group_where += _folder_filter_sql("s", workdir, dream_group_filters)

    by_project = _group_rows(
        f"""
        with session_token_turns as (
          select s.project_id as group_key,
                 s.session_id,
                 coalesce(turn_id, 'row:' || tu.id) as turn_key,
                 max(coalesce(tu.total_tokens, 0)) as total_tokens
          from token_usage tu
          join sessions s on s.session_id = tu.session_id
          {session_group_where}
          group by s.project_id, s.session_id, turn_key
        ),
        session_grouped as (
          select group_key,
                 coalesce(sum(total_tokens), 0) as session_total_tokens,
                 count(distinct session_id) as session_count
          from session_token_turns
          group by group_key
        ),
        dream_grouped as (
          select s.project_id as group_key,
                 coalesce(sum(dr.total_tokens), 0) as dream_total_tokens,
                 count(*) as dream_count
          from dream_runs dr
          left join sessions s on s.session_id = dr.session_id
          {dream_group_where}
          group by s.project_id
        ),
        all_keys as (
          select group_key from session_grouped
          union
          select group_key from dream_grouped
        )
        select coalesce(all_keys.group_key, '') as group_key,
               coalesce(all_keys.group_key, '') as label,
               coalesce(session_grouped.session_total_tokens, 0) as session_total_tokens,
               coalesce(dream_grouped.dream_total_tokens, 0) as dream_total_tokens,
               coalesce(session_grouped.session_count, 0) as session_count,
               coalesce(dream_grouped.dream_count, 0) as dream_count
        from all_keys
        left join session_grouped on session_grouped.group_key = all_keys.group_key
        left join dream_grouped on dream_grouped.group_key = all_keys.group_key
        where coalesce(all_keys.group_key, '') != ''
        order by coalesce(session_grouped.session_total_tokens, 0) + coalesce(dream_grouped.dream_total_tokens, 0) desc,
                 coalesce(all_keys.group_key, '') asc
        """,
        session_group_filters + dream_group_filters,
    )

    by_client = _group_rows(
        f"""
        with session_token_turns as (
          select s.client_type as group_key,
                 s.session_id,
                 coalesce(turn_id, 'row:' || tu.id) as turn_key,
                 max(coalesce(tu.total_tokens, 0)) as total_tokens
          from token_usage tu
          join sessions s on s.session_id = tu.session_id
          {session_group_where}
          group by s.client_type, s.session_id, turn_key
        ),
        session_grouped as (
          select group_key,
                 coalesce(sum(total_tokens), 0) as session_total_tokens,
                 count(distinct session_id) as session_count
          from session_token_turns
          group by group_key
        ),
        dream_grouped as (
          select coalesce(s.client_type, dr.client_type) as group_key,
                 coalesce(sum(dr.total_tokens), 0) as dream_total_tokens,
                 count(*) as dream_count
          from dream_runs dr
          left join sessions s on s.session_id = dr.session_id
          {dream_group_where}
          group by coalesce(s.client_type, dr.client_type)
        ),
        all_keys as (
          select group_key from session_grouped
          union
          select group_key from dream_grouped
        )
        select coalesce(all_keys.group_key, '') as group_key,
               coalesce(all_keys.group_key, '') as label,
               coalesce(session_grouped.session_total_tokens, 0) as session_total_tokens,
               coalesce(dream_grouped.dream_total_tokens, 0) as dream_total_tokens,
               coalesce(session_grouped.session_count, 0) as session_count,
               coalesce(dream_grouped.dream_count, 0) as dream_count
        from all_keys
        left join session_grouped on session_grouped.group_key = all_keys.group_key
        left join dream_grouped on dream_grouped.group_key = all_keys.group_key
        where coalesce(all_keys.group_key, '') != ''
        order by coalesce(session_grouped.session_total_tokens, 0) + coalesce(dream_grouped.dream_total_tokens, 0) desc,
                 coalesce(all_keys.group_key, '') asc
        """,
        session_group_filters + dream_group_filters,
    )

    by_workdir = _group_rows(
        f"""
        with session_token_turns as (
          select coalesce(nullif(s.last_workdir, ''), nullif(s.cwd, '')) as group_key,
                 s.session_id,
                 coalesce(turn_id, 'row:' || tu.id) as turn_key,
                 max(coalesce(tu.total_tokens, 0)) as total_tokens
          from token_usage tu
          join sessions s on s.session_id = tu.session_id
          {session_group_where}
          group by group_key, s.session_id, turn_key
        ),
        session_grouped as (
          select group_key,
                 coalesce(sum(total_tokens), 0) as session_total_tokens,
                 count(distinct session_id) as session_count
          from session_token_turns
          group by group_key
        ),
        dream_grouped as (
          select coalesce(nullif(s.last_workdir, ''), nullif(s.cwd, '')) as group_key,
                 coalesce(sum(dr.total_tokens), 0) as dream_total_tokens,
                 count(*) as dream_count
          from dream_runs dr
          left join sessions s on s.session_id = dr.session_id
          {dream_group_where}
          group by group_key
        ),
        all_keys as (
          select group_key from session_grouped
          union
          select group_key from dream_grouped
        )
        select coalesce(all_keys.group_key, '') as group_key,
               coalesce(all_keys.group_key, '') as label,
               coalesce(session_grouped.session_total_tokens, 0) as session_total_tokens,
               coalesce(dream_grouped.dream_total_tokens, 0) as dream_total_tokens,
               coalesce(session_grouped.session_count, 0) as session_count,
               coalesce(dream_grouped.dream_count, 0) as dream_count
        from all_keys
        left join session_grouped on session_grouped.group_key = all_keys.group_key
        left join dream_grouped on dream_grouped.group_key = all_keys.group_key
        where coalesce(all_keys.group_key, '') != ''
        order by coalesce(session_grouped.session_total_tokens, 0) + coalesce(dream_grouped.dream_total_tokens, 0) desc,
                 coalesce(all_keys.group_key, '') asc
        """,
        session_group_filters + dream_group_filters,
    )

    dream_runner_rows = _group_rows(
        f"""
        select coalesce(dr.runner, '') as group_key,
               coalesce(dr.runner, '') as label,
               0 as session_total_tokens,
               coalesce(sum(dr.total_tokens), 0) as dream_total_tokens,
               0 as session_count,
               count(*) as dream_count
        from dream_runs dr
        left join sessions s on s.session_id = dr.session_id
        {dream_group_where}
        group by coalesce(dr.runner, '')
        having coalesce(dr.runner, '') != ''
        order by coalesce(sum(dr.total_tokens), 0) desc, coalesce(dr.runner, '') asc
        """,
        dream_group_filters,
    )

    dream_model_rows = _group_rows(
        f"""
        select coalesce(dr.runner_model, '') as group_key,
               coalesce(dr.runner_model, '') as label,
               0 as session_total_tokens,
               coalesce(sum(dr.total_tokens), 0) as dream_total_tokens,
               0 as session_count,
               count(*) as dream_count
        from dream_runs dr
        left join sessions s on s.session_id = dr.session_id
        {dream_group_where}
        group by coalesce(dr.runner_model, '')
        having coalesce(dr.runner_model, '') != ''
        order by coalesce(sum(dr.total_tokens), 0) desc, coalesce(dr.runner_model, '') asc
        """,
        dream_group_filters,
    )
    options = monitor_filter_options()
    return {
        "range": {"name": range_name, "start": _hour_key(start_dt), "end": _hour_key(end_dt)},
        "filters": {"client_type": client_type or "", "project_id": project_id or "", "workdir": workdir or ""},
        "clients": options["clients"],
        "projects": options["projects"],
        "workdirs": options["workdirs"],
        "buckets": list(buckets.values()),
        "totals": totals,
        "by_project": by_project,
        "by_client": by_client,
        "by_workdir": by_workdir,
        "by_dream_runner": dream_runner_rows,
        "by_dream_model": dream_model_rows,
    }
