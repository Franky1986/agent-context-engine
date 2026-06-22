from __future__ import annotations

import re
from pathlib import Path
from typing import Any


def markdown_escape(value: Any, limit: int = 1200) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


def read_text_limited(path: Path, limit: int = 24000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit] + "\n...[truncated]"
    return text


LARGE_CONTEXT_MARKERS = (
    "Project Memory Reference memory/memories/projects/",
    "Deterministic Session Handover",
    "Current Deterministic Handover",
)


def redact_embedded_context_artifacts(value: Any) -> str:
    text = str(value or "")
    marker = next((item for item in LARGE_CONTEXT_MARKERS if item in text), "")
    if not marker:
        return text
    first_line = text.strip().splitlines()[0] if text.strip() else marker
    return (
        f"{first_line}\n"
        "[embedded memory/handover artifact omitted from LLM-visible conversation context; "
        "refer to deterministic memory artifacts by path instead]"
    )


def xml_text(value: Any, limit: int = 4000) -> str:
    text = markdown_escape(value, limit)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tagged_block(tag: str, attrs: dict[str, Any] | None, body: Any, limit: int = 4000) -> str:
    attr_text = ""
    if attrs:
        parts = [f'{key}="{xml_text(value, 300)}"' for key, value in attrs.items() if value is not None]
        if parts:
            attr_text = " " + " ".join(parts)
    return f"<{tag}{attr_text}>\n{xml_text(body, limit)}\n</{tag}>"


def tool_response_summary(value: Any, limit: int = 700) -> str:
    text = str(value or "").strip()
    if not text:
        return "tool_status=empty chars=0 lines=0 raw_output_omitted=true"
    lines = [line.rstrip() for line in text.splitlines()]
    path_matches = re.findall(r"(?:/Users/[^\s'\"`]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)", text)
    failed = bool(re.search(r"\b(error|failed|exception|traceback|permission denied|not found|exit code [1-9])\b", text, re.I))
    summary_lines = [
        f"tool_status={'failed' if failed else 'successful'} chars={len(text)} lines={len(lines)} raw_output_omitted=true",
    ]
    if path_matches:
        unique_paths = list(dict.fromkeys(path_matches))
        summary_lines.append("mentioned paths:")
        summary_lines.extend(f"- {path[:240]}" for path in unique_paths[:8])
    summary = "\n".join(summary_lines)
    if len(summary) > limit:
        return summary[:limit].rstrip() + "\n...[summary truncated]"
    return summary
