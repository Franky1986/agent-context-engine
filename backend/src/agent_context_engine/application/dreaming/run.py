from __future__ import annotations

import os
import sqlite3
import subprocess
from pathlib import Path
from time import monotonic

from ...adapters.runners.codex import codex_subprocess_env
from ...infrastructure.config import DREAM_DIR, MEMORY_DIR, ROOT, json_dumps, safe_slug, utc_now
from ...infrastructure.text import read_text_limited
from .memory import append_project_memory, append_project_memory_ref
from .prompt import build_dream_prompt
from .runners import (
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


def run_codex_dream(session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    run_dir = DREAM_DIR / "runs" / safe_slug(dream_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_slug = safe_slug(session["project_id"] or "unknown")
    prompt = build_dream_prompt(session, summary_rel, events, "codex", model)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "codex-output.md"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = codex_dream_command(response_path, model)
    started = utc_now()
    started_mono = monotonic()
    proc = subprocess.run(
        command,
        input=prompt,
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(ROOT),
        env=codex_subprocess_env(extra={"AGENT_MEMORY_DREAM": "1", "AGENT_MEMORY_ROOT": str(ROOT)}),
    )
    duration_ms = int((monotonic() - started_mono) * 1000)
    tool_event_detected = codex_stdout_has_tool_events(proc.stdout)
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "isolation": {
                    "hooks_disabled": True,
                    "ignore_user_config": True,
                    "ignore_rules": True,
                    "ephemeral": True,
                    "sandbox": "read-only",
                    "json_event_audit": True,
                    "tool_event_detected": tool_event_detected,
                    "model": model,
                },
                "started_at": started,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "response_path": str(response_path.relative_to(ROOT)),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"codex dream failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    if tool_event_detected:
        raise RuntimeError("codex dream used or attempted to use a tool; refusing dream output")
    response = read_text_limited(response_path, 100000).strip()
    if not response:
        raise RuntimeError("codex dream produced an empty response")
    dream_path = MEMORY_DIR / "memories" / "dreams" / project_slug / f"{safe_slug(dream_run_id)}.md"
    dream_path.parent.mkdir(parents=True, exist_ok=True)
    dream_path.write_text(response + "\n", encoding="utf-8")
    project_path = append_project_memory_ref(session, summary_rel, str(dream_path.relative_to(ROOT)), dream_run_id, "codex", model)
    return [dream_path, project_path, prompt_path, response_path, meta_path]


def run_claude_dream(session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    run_dir = DREAM_DIR / "runs" / safe_slug(dream_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_slug = safe_slug(session["project_id"] or "unknown")
    prompt = build_dream_prompt(session, summary_rel, events, "claude", model)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "claude-output.md"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = claude_dream_command(model)
    started = utc_now()
    started_mono = monotonic()
    proc = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env={**os.environ, "AGENT_MEMORY_DREAM": "1"})
    duration_ms = int((monotonic() - started_mono) * 1000)
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "isolation": {
                    "tools_disabled": True,
                    "skills_disabled": True,
                    "no_session_persistence": True,
                    "hook_guard": "AGENT_MEMORY_DREAM=1",
                    "model": model,
                },
                "started_at": started,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "response_path": str(response_path.relative_to(ROOT)),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude dream failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    response = cursor_stdout_text(proc.stdout)
    if not response:
        raise RuntimeError("claude dream produced an empty response")
    response_path.write_text(response + "\n", encoding="utf-8")
    dream_path = MEMORY_DIR / "memories" / "dreams" / project_slug / f"{safe_slug(dream_run_id)}.md"
    dream_path.parent.mkdir(parents=True, exist_ok=True)
    dream_path.write_text(response + "\n", encoding="utf-8")
    project_path = append_project_memory_ref(session, summary_rel, str(dream_path.relative_to(ROOT)), dream_run_id, "claude", model)
    return [dream_path, project_path, prompt_path, response_path, meta_path]


def run_cursor_dream(session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    run_dir = DREAM_DIR / "runs" / safe_slug(dream_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_slug = safe_slug(session["project_id"] or "unknown")
    prompt = build_dream_prompt(session, summary_rel, events, "cursor", model)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "cursor-output.md"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = cursor_dream_command(model)
    started = utc_now()
    started_mono = monotonic()
    proc = subprocess.run(
        command + [prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(ROOT),
        env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_MEMORY_ROOT": str(ROOT)},
    )
    duration_ms = int((monotonic() - started_mono) * 1000)
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "isolation": {
                    "mode": "ask",
                    "workspace": str(ROOT),
                    "hook_guard": "AGENT_MEMORY_DREAM=1",
                    "auth_source": "cursor-agent local auth",
                    "model": model,
                },
                "started_at": started,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "response_path": str(response_path.relative_to(ROOT)),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"cursor dream failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    response = proc.stdout.strip()
    if not response:
        raise RuntimeError("cursor dream produced an empty response")
    response_path.write_text(response + "\n", encoding="utf-8")
    dream_path = MEMORY_DIR / "memories" / "dreams" / project_slug / f"{safe_slug(dream_run_id)}.md"
    dream_path.parent.mkdir(parents=True, exist_ok=True)
    dream_path.write_text(response + "\n", encoding="utf-8")
    project_path = append_project_memory_ref(session, summary_rel, str(dream_path.relative_to(ROOT)), dream_run_id, "cursor", model)
    return [dream_path, project_path, prompt_path, response_path, meta_path]


def run_gemini_dream(session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    run_dir = DREAM_DIR / "runs" / safe_slug(dream_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_slug = safe_slug(session["project_id"] or "unknown")
    prompt = build_dream_prompt(session, summary_rel, events, "gemini", model)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "gemini-output.md"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = gemini_dream_command(model)
    started = utc_now()
    started_mono = monotonic()
    proc = subprocess.run(
        command + [prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(ROOT),
        env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_MEMORY_ROOT": str(ROOT)},
    )
    duration_ms = int((monotonic() - started_mono) * 1000)
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "isolation": {
                    "mode": "prompt",
                    "output_format": "text",
                    "model": model,
                },
                "started_at": started,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "response_path": str(response_path.relative_to(ROOT)),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gemini dream failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    response = proc.stdout.strip()
    if not response:
        raise RuntimeError("gemini dream produced an empty response")
    response_path.write_text(response + "\n", encoding="utf-8")
    dream_path = MEMORY_DIR / "memories" / "dreams" / project_slug / f"{safe_slug(dream_run_id)}.md"
    dream_path.parent.mkdir(parents=True, exist_ok=True)
    dream_path.write_text(response + "\n", encoding="utf-8")
    project_path = append_project_memory_ref(session, summary_rel, str(dream_path.relative_to(ROOT)), dream_run_id, "gemini", model)
    return [dream_path, project_path, prompt_path, response_path, meta_path]


def run_antigravity_dream(session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    run_dir = DREAM_DIR / "runs" / safe_slug(dream_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_slug = safe_slug(session["project_id"] or "unknown")
    prompt = build_dream_prompt(session, summary_rel, events, "antigravity", model)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "antigravity-output.md"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = antigravity_dream_command(model)
    started = utc_now()
    started_mono = monotonic()
    proc = subprocess.run(
        command + [prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(ROOT),
        env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_MEMORY_ROOT": str(ROOT)},
    )
    duration_ms = int((monotonic() - started_mono) * 1000)
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "isolation": {
                    "mode": "prompt",
                    "output_format": "text",
                    "model": model,
                },
                "started_at": started,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "response_path": str(response_path.relative_to(ROOT)),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"antigravity dream failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    response = proc.stdout.strip()
    if not response:
        raise RuntimeError("antigravity dream produced an empty response")
    response_path.write_text(response + "\n", encoding="utf-8")
    dream_path = MEMORY_DIR / "memories" / "dreams" / project_slug / f"{safe_slug(dream_run_id)}.md"
    dream_path.parent.mkdir(parents=True, exist_ok=True)
    dream_path.write_text(response + "\n", encoding="utf-8")
    project_path = append_project_memory_ref(session, summary_rel, str(dream_path.relative_to(ROOT)), dream_run_id, "antigravity", model)
    return [dream_path, project_path, prompt_path, response_path, meta_path]


def run_opencode_dream(session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    run_dir = DREAM_DIR / "runs" / safe_slug(dream_run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_slug = safe_slug(session["project_id"] or "unknown")
    prompt = build_dream_prompt(session, summary_rel, events, "opencode", model)
    prompt_path = run_dir / "prompt.md"
    response_path = run_dir / "opencode-output.md"
    meta_path = run_dir / "metadata.json"
    prompt_path.write_text(prompt, encoding="utf-8")
    command = opencode_dream_command(model)
    started = utc_now()
    started_mono = monotonic()
    proc = subprocess.run(
        command + [prompt],
        text=True,
        capture_output=True,
        timeout=timeout,
        cwd=str(ROOT),
        env={**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_MEMORY_ROOT": str(ROOT)},
    )
    duration_ms = int((monotonic() - started_mono) * 1000)
    meta_path.write_text(
        json_dumps(
            {
                "command": command,
                "isolation": {
                    "mode": "run",
                    "workspace": str(ROOT),
                    "permissions": "skip",
                    "model": model,
                },
                "started_at": started,
                "finished_at": utc_now(),
                "duration_ms": duration_ms,
                "token_usage": extract_runner_token_usage(proc.stdout, proc.stderr),
                "token_usage_available": runner_token_usage_available(proc.stdout, proc.stderr),
                "returncode": proc.returncode,
                "stdout": proc.stdout[-12000:],
                "stderr": proc.stderr[-12000:],
                "prompt_path": str(prompt_path.relative_to(ROOT)),
                "response_path": str(response_path.relative_to(ROOT)),
            }
        ),
        encoding="utf-8",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"opencode dream failed with exit code {proc.returncode}: {(proc.stderr or proc.stdout)[-1000:]}")
    response = opencode_stdout_text(proc.stdout)
    if not response:
        raise RuntimeError("opencode dream produced an empty response")
    response_path.write_text(response + "\n", encoding="utf-8")
    dream_path = MEMORY_DIR / "memories" / "dreams" / project_slug / f"{safe_slug(dream_run_id)}.md"
    dream_path.parent.mkdir(parents=True, exist_ok=True)
    dream_path.write_text(response + "\n", encoding="utf-8")
    project_path = append_project_memory_ref(session, summary_rel, str(dream_path.relative_to(ROOT)), dream_run_id, "opencode", model)
    return [dream_path, project_path, prompt_path, response_path, meta_path]


def run_dream_runner(runner: str, session: sqlite3.Row, summary_rel: str, events: list[sqlite3.Row], dream_run_id: str, timeout: int, model: str | None) -> list[Path]:
    if runner == "codex":
        return run_codex_dream(session, summary_rel, events, dream_run_id, timeout, model)
    if runner == "claude":
        return run_claude_dream(session, summary_rel, events, dream_run_id, timeout, model)
    if runner == "cursor":
        return run_cursor_dream(session, summary_rel, events, dream_run_id, timeout, model)
    if runner == "antigravity":
        return run_antigravity_dream(session, summary_rel, events, dream_run_id, timeout, model)
    if runner == "gemini":
        return run_gemini_dream(session, summary_rel, events, dream_run_id, timeout, model)
    if runner == "opencode":
        return run_opencode_dream(session, summary_rel, events, dream_run_id, timeout, model)
    if runner in {"deterministic", "none"}:
        return [append_project_memory(session, summary_rel, dream_run_id)]
    raise RuntimeError(f"runner is available but no dream adapter is implemented yet: {runner}")
