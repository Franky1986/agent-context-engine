from __future__ import annotations

import json
from typing import Any


__all__ = [
    "DreamRunnerJsonError",
    "extract_json",
    "extract_json_with_diagnostics",
]


class DreamRunnerJsonError(ValueError):
    def __init__(self, message: str, *, code: str, diagnostics: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics


def extract_json_with_diagnostics(text: str) -> tuple[Any, dict[str, Any]]:
    stripped = text.strip()
    diagnostics: dict[str, Any] = {
        "input_chars": len(stripped),
        "fenced": False,
        "strategy": "strict",
        "trailing_text_detected": False,
    }
    if not stripped:
        raise DreamRunnerJsonError(
            "LLM returned blank output when strict JSON was required",
            code="blank_json_output",
            diagnostics={**diagnostics, "preview": ""},
        )
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
        diagnostics["fenced"] = True
        diagnostics["strategy"] = "code_fence_unwrapped"
    try:
        return json.loads(stripped), diagnostics
    except json.JSONDecodeError as primary_error:
        decoder = json.JSONDecoder()
        best_candidate: Any | None = None
        best_score: tuple[int, int] | None = None
        best_tail_present = False
        for index, char in enumerate(stripped):
            if char not in "{[":
                continue
            try:
                candidate, end = decoder.raw_decode(stripped[index:])
            except json.JSONDecodeError:
                continue
            tail = stripped[index + end :].strip()
            score = (
                0 if isinstance(candidate, dict) and candidate.get("schema_version") else 1,
                0 if not tail else 1,
            )
            if best_score is None or score < best_score:
                best_candidate = candidate
                best_score = score
                best_tail_present = bool(tail)
                if score == (0, 0):
                    break
        if best_candidate is not None:
            return best_candidate, {
                **diagnostics,
                "strategy": "embedded_json_candidate",
                "trailing_text_detected": best_tail_present,
            }
        raise DreamRunnerJsonError(
            str(primary_error),
            code="invalid_json_output",
            diagnostics={
                **diagnostics,
                "preview": stripped[:400],
            },
        ) from primary_error


def extract_json(text: str) -> Any:
    payload, _ = extract_json_with_diagnostics(text)
    return payload
