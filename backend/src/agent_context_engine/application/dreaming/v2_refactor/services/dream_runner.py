from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from agent_context_engine.application.dreaming.runners import (
    antigravity_dream_command,
    claude_dream_command,
    codex_dream_command,
    codex_stdout_has_tool_events,
    cursor_dream_command,
    cursor_stdout_text,
    extract_runner_token_usage,
    gemini_dream_command,
    opencode_dream_command,
    opencode_stdout_text,
    runner_token_usage_available,
)
from agent_context_engine.adapters.runners.codex import codex_subprocess_env
from agent_context_engine.application.dreaming.v2_ports import CommandResult, CommandRunner


__all__ = [
    "invoke_runner",
    "mock_llm_output",
    "extract_json",
]


def mock_llm_output(
    prompt: str,
    *,
    semantic_schema_version: str,
    reconciliation_schema_version: str,
    json_dumps_fn,
) -> str:
    if "Return strict JSON semantic proposals" in prompt:
        return json_dumps_fn(
            {
                "schema_version": semantic_schema_version,
                "dream_run_id": "mock",
                "session_id": "mock",
                "source_event_range": {"start_seq": 1, "end_seq": 1},
                "entities": [
                    {
                        "proposal_id": "entity-main-task",
                        "type": "task",
                        "name": "Dream Pipeline 2.0 Umsetzung",
                        "aliases": [],
                        "summary": "Die Session arbeitet an der Umsetzung der Dream Pipeline 2.0.",
                        "properties": {},
                        "confidence": 0.82,
                        "evidence": [{"source": "conversation", "event_seq": 1, "quote": "setze nun das epic um"}],
                        "review_required": False,
                        "review_reason": None,
                    }
                ],
                "relations": [],
                "schema_proposals": [],
            }
        )
    if "Return strict JSON reconciliation decisions" in prompt:
        return json_dumps_fn(
            {
                "schema_version": reconciliation_schema_version,
                "dream_run_id": "mock",
                "session_id": "mock",
                "decisions": [
                    {
                        "decision_id": "decision-main-task",
                        "proposal_id": "entity-main-task",
                        "action": "create_entity",
                        "target_key": None,
                        "candidate_keys": [],
                        "confidence": 0.82,
                        "reason": "No matching existing semantic entity was supplied.",
                        "human_summary": "Neue Aufgabe zur Umsetzung der Dream Pipeline 2.0 speichern.",
                        "evidence": [{"source": "conversation", "event_seq": 1, "quote": "setze nun das epic um"}],
                        "review_required": False,
                        "review_reason": None,
                        "write_patch": {},
                    }
                ],
            }
        )
    return """# Dream Memory Update

## Startup Brief
The session implemented Dream Pipeline 2.0 as the canonical memory pipeline.

## Compact Summary
The session focused on implementing Dream Pipeline 2.0 as the canonical memory pipeline.

## Durable Decisions
- Dream Pipeline 2.0 should use staged LLM narrative, semantic extraction, reconciliation, deterministic operational extraction, and SQLite-first persistence.

## Open Tasks
- Continue implementation and verification against the epic plan.
"""


def _run_command(
    command_runner: CommandRunner,
    command: list[str],
    *,
    input_text: str,
    timeout: int,
    cwd: str,
    env: dict[str, str],
) -> CommandResult:
    return command_runner.run(
        command,
        input=input_text,
        timeout=timeout,
        cwd=cwd,
        env=env,
    )


def invoke_runner(
    runner: str,
    model: str | None,
    prompt: str,
    raw_output_path: Path,
    timeout: int,
    *,
    command_runner: CommandRunner,
    root_path: str,
    now_fn: Callable[[], str],
    monotonic_fn: Callable[[], float],
    read_text_limited_fn: Callable[[Path, int], str],
    write_text_fn: Callable[[Path, str], None],
    base_env: dict[str, str],
    max_output_bytes: int,
    mock_enabled: bool,
    semantic_schema_version: str,
    reconciliation_schema_version: str,
    json_dumps_fn,
    codex_dream_command_fn=codex_dream_command,
    claude_dream_command_fn=claude_dream_command,
    cursor_dream_command_fn=cursor_dream_command,
    antigravity_dream_command_fn=antigravity_dream_command,
    gemini_dream_command_fn=gemini_dream_command,
    opencode_dream_command_fn=opencode_dream_command,
    codex_stdout_has_tool_events_fn=codex_stdout_has_tool_events,
    opencode_stdout_text_fn=opencode_stdout_text,
    extract_runner_token_usage_fn=extract_runner_token_usage,
    codex_subprocess_env_fn=codex_subprocess_env,
    write_input_text_separator: str = "\n",
) -> tuple[str, dict[str, Any]]:
    if mock_enabled or runner == "deterministic":
        output = mock_llm_output(
            prompt,
            semantic_schema_version=semantic_schema_version,
            reconciliation_schema_version=reconciliation_schema_version,
            json_dumps_fn=json_dumps_fn,
        )
        write_text_fn(raw_output_path, output + (write_input_text_separator if output else ""))
        return output, {
            "mock": True,
            "runner": runner,
            "token_usage": {
                "input_tokens": len(prompt) // 4,
                "output_tokens": 64,
                "total_tokens": len(prompt) // 4 + 64,
            },
        }
    if runner in {"deterministic", "none"}:
        raise RuntimeError(f"v2 requires an LLM runner, got {runner}")

    started = now_fn()
    started_mono = monotonic_fn()
    runner_env = {"AGENT_MEMORY_DREAM": "1", "AGENT_MEMORY_ROOT": root_path}

    if runner == "codex":
        command = codex_dream_command_fn(raw_output_path, model)
        proc = _run_command(
            command_runner,
            command,
            input_text=prompt,
            timeout=timeout,
            cwd=root_path,
            env=codex_subprocess_env_fn(extra=runner_env),
        )
        output = read_text_limited_fn(raw_output_path, max_output_bytes + 1).strip()
        tool_event_detected = codex_stdout_has_tool_events_fn(proc.stdout)
    elif runner == "claude":
        command = claude_dream_command_fn(model)
        proc = _run_command(
            command_runner,
            command,
            input_text=prompt,
            timeout=timeout,
            cwd=root_path,
            env={**base_env, **{"AGENT_MEMORY_DREAM": "1"}},
        )
        output = proc.stdout.strip()
        write_text_fn(raw_output_path, output + (write_input_text_separator if output else ""))
        tool_event_detected = False
    elif runner == "cursor":
        command = cursor_dream_command_fn(model)
        proc = _run_command(
            command_runner,
            command + [prompt],
            input_text="",
            timeout=timeout,
            cwd=root_path,
            env={**base_env, **runner_env},
        )
        output = cursor_stdout_text(proc.stdout)
        write_text_fn(raw_output_path, output + (write_input_text_separator if output else ""))
        tool_event_detected = False
    elif runner == "antigravity":
        command = antigravity_dream_command_fn(model)
        proc = _run_command(
            command_runner,
            command + [prompt],
            input_text="",
            timeout=timeout,
            cwd=root_path,
            env={**base_env, **runner_env},
        )
        output = proc.stdout.strip()
        write_text_fn(raw_output_path, output + (write_input_text_separator if output else ""))
        tool_event_detected = False
    elif runner == "gemini":
        command = gemini_dream_command_fn(model)
        proc = _run_command(
            command_runner,
            command + [prompt],
            input_text="",
            timeout=timeout,
            cwd=root_path,
            env={**base_env, **runner_env},
        )
        output = proc.stdout.strip()
        write_text_fn(raw_output_path, output + (write_input_text_separator if output else ""))
        tool_event_detected = False
    elif runner == "opencode":
        command = opencode_dream_command_fn(model)
        proc = _run_command(
            command_runner,
            command + [prompt],
            input_text="",
            timeout=timeout,
            cwd=root_path,
            env={**base_env, **runner_env},
        )
        output = opencode_stdout_text_fn(proc.stdout)
        write_text_fn(raw_output_path, output + (write_input_text_separator if output else ""))
        tool_event_detected = False
    else:
        raise RuntimeError(f"v2 requires an LLM runner, got {runner}")

    token_usage = extract_runner_token_usage_fn(proc.stdout, proc.stderr)
    metadata = {
        "command": command,
        "started_at": started,
        "finished_at": now_fn(),
        "duration_ms": int((monotonic_fn() - started_mono) * 1000),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-12000:],
        "stderr": proc.stderr[-12000:],
        "tool_event_detected": tool_event_detected,
        "token_usage": token_usage,
        "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
    }
    if proc.returncode != 0:
        raise RuntimeError(f"{runner} v2 LLM stage failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    if tool_event_detected:
        raise RuntimeError(f"{runner} v2 LLM stage used or attempted to use a tool")
    if not output:
        raise RuntimeError(f"{runner} v2 LLM stage produced empty output")
    if len(output.encode("utf-8")) > max_output_bytes:
        raise RuntimeError(f"{runner} v2 LLM stage output exceeds {max_output_bytes} bytes")
    return output, metadata


def extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as primary_error:
        decoder = json.JSONDecoder()
        best_candidate: Any | None = None
        best_score: tuple[int, int] | None = None
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
                if score == (0, 0):
                    break
        if best_candidate is not None:
            return best_candidate
        raise primary_error
