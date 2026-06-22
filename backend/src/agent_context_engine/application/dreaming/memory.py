from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ...infrastructure.config import MEMORY_DIR, ROOT, safe_slug, session_short
from ..retrieval import index_memory_document


def memory_project_path(session: sqlite3.Row) -> Path:
    return MEMORY_DIR / "memories" / "projects" / f"{safe_slug(session['project_id'] or 'unknown')}.md"


def append_project_memory(session: sqlite3.Row, summary_rel: str, dream_run_id: str) -> Path:
    path = memory_project_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {session['project_id'] or 'unknown'}\n\n"
    block = (
        f"\n## Session {session_short(session['session_id'])} ({session['last_event_at'] or ''})\n\n"
        f"- Client: `{session['client_type']}`\n"
        f"- Dream run: `{dream_run_id}`\n"
        f"- Summary: `{summary_rel}`\n"
        f"- Events: `1-{session['last_event_seq']}`\n"
    )
    if f"Dream run: `{dream_run_id}`" not in existing:
        existing += block
        path.write_text(existing, encoding="utf-8")
    return path


def append_project_memory_ref(session: sqlite3.Row, summary_rel: str, dream_rel: str, dream_run_id: str, runner: str, model: str | None) -> Path:
    path = memory_project_path(session)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else f"# {session['project_id'] or 'unknown'}\n\n"
    block = (
        f"\n## Session {session_short(session['session_id'])} ({session['last_event_at'] or ''})\n\n"
        f"- Client: `{session['client_type']}`\n"
        f"- Runner: `{runner}`\n"
        f"- Model: `{model or ''}`\n"
        f"- Dream run: `{dream_run_id}`\n"
        f"- Handover: `{summary_rel}`\n"
        f"- Dream memory: `{dream_rel}`\n"
        f"- Events: `{int(session['last_dream_event_seq']) + 1}-{session['last_event_seq']}`\n"
    )
    if f"Dream run: `{dream_run_id}`" not in existing:
        existing += block
        path.write_text(existing, encoding="utf-8")
    return path


def extract_session_brief(markdown: str) -> str | None:
    for section_name in ("## Startup Brief", "## Compact Summary"):
        in_section = False
        for raw_line in markdown.splitlines():
            line = raw_line.strip()
            if line == section_name:
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if not in_section or not line:
                continue
            line = line.removeprefix("-").strip()
            if line:
                return line[:240]
    return None


def extract_memory_metadata(markdown: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "memory_kind": "episodic",
        "source_kind": "dream",
        "confidence": 0.8,
        "risk_level": "low",
        "sensitivity": "normal",
        "injection_policy": "on_demand",
        "poisoning_flags": [],
    }
    in_section = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line == "## Memory Metadata":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section or ":" not in line:
            continue
        line = line.removeprefix("-").strip()
        key, value = line.split(":", 1)
        key = key.strip().strip("`")
        value = value.strip().strip("`").strip()
        if key == "confidence":
            try:
                metadata[key] = max(0.0, min(1.0, float(value)))
            except ValueError:
                pass
        elif key == "poisoning_flags":
            metadata[key] = [item.strip() for item in value.strip("[]").split(",") if item.strip()]
        elif key in metadata:
            metadata[key] = value
    return metadata


def index_dream_outputs(conn: sqlite3.Connection, session: sqlite3.Row, dream_run: sqlite3.Row) -> None:
    tags: list[str] = []
    if dream_run["tags_json"]:
        try:
            tags = [str(item) for item in json.loads(dream_run["tags_json"])]
        except json.JSONDecodeError:
            tags = []
    paths: list[str] = []
    if dream_run["output_memory_paths_json"]:
        try:
            paths = [str(item) for item in json.loads(dream_run["output_memory_paths_json"])]
        except json.JSONDecodeError:
            paths = []
    for rel in paths:
        if "/dream/runs/" in rel:
            continue
        path = ROOT / rel
        if not path.exists() or path.suffix != ".md":
            continue
        kind = "project_memory" if "/projects/" in rel else "dream"
        content = path.read_text(encoding="utf-8", errors="replace")
        metadata = extract_memory_metadata(content)
        evidence = {
            "session_id": session["session_id"],
            "dream_run_id": dream_run["dream_run_id"],
            "event_seq_from": dream_run["input_event_seq_from"],
            "event_seq_to": dream_run["input_event_seq_to"],
            "runner": dream_run["runner"],
            "runner_model": dream_run["runner_model"],
        }
        index_memory_document(
            conn,
            path,
            kind=kind,
            session_id=session["session_id"],
            dream_run_id=dream_run["dream_run_id"],
            project_id=session["project_id"],
            title=session["thread_name"] or dream_run["dream_run_id"],
            intent=dream_run["intent"],
            helpful_score=dream_run["helpful_score"],
            tags=tags,
            memory_kind=metadata["memory_kind"],
            source_kind=metadata["source_kind"],
            confidence=metadata["confidence"],
            risk_level=metadata["risk_level"],
            sensitivity=metadata["sensitivity"],
            injection_policy=metadata["injection_policy"],
            poisoning_flags=metadata["poisoning_flags"],
            evidence=[evidence],
        )
