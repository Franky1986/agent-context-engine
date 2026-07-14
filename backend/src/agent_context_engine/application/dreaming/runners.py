from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any

from ...infrastructure.config import (
    CLAUDE_DREAM_MODEL,
    CODEX_DREAM_MODEL,
    CURSOR_DREAM_MODEL,
    ANTIGRAVITY_DREAM_MODEL,
    GEMINI_DREAM_MODEL,
    LOCK_DIR,
    MEMORY_DIR,
    OPENCODE_DREAM_MODEL,
    ROOT,
    json_dumps,
    safe_slug,
    utc_now,
)


def runner_for_session(session: sqlite3.Row, requested: str) -> str:
    if requested == "same-as-session":
        return session["preferred_dream_runner"] or session["client_type"]
    return requested


def runner_available(runner: str) -> bool:
    if runner in {"deterministic", "none"}:
        return True
    if runner == "cursor":
        return shutil.which("cursor-agent") is not None
    if runner == "antigravity":
        return shutil.which("agy") is not None
    return shutil.which(runner) is not None


def _looks_unauthenticated(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "not logged in",
            "not authenticated",
            "authentication required",
            "please run /login",
            "please run login",
            "run 'agent login' first",
            "run agent login first",
            "run `codex login`",
            "run codex login",
            "run `claude login`",
            "run claude login",
            "run `claude auth login`",
            "run claude auth login",
            "set cursor_api_key",
            "api key not found",
            "missing api key",
        )
    )


def codex_auth_status() -> tuple[bool, str]:
    executable = shutil.which("codex")
    if not executable:
        return False, "codex executable is missing."
    try:
        proc = subprocess.run(
            [executable, "login", "status"],
            text=True,
            capture_output=True,
            timeout=5,
            cwd=str(ROOT),
            env={
                **os.environ,
                "AGENT_MEMORY_INTERNAL_RUN": "1",
                "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT),
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"codex login status failed: {exc}"
    detail = (proc.stderr or proc.stdout or "").strip()
    if _looks_unauthenticated(detail):
        return False, detail
    if proc.returncode == 0:
        return True, detail
    return False, detail or f"codex login status exited with code {proc.returncode}"


def claude_auth_status() -> tuple[bool, str]:
    executable = shutil.which("claude")
    if not executable:
        return False, "claude executable is missing."
    try:
        proc = subprocess.run(
            [executable, "auth", "status"],
            text=True,
            capture_output=True,
            timeout=5,
            cwd=str(ROOT),
            env={
                **os.environ,
                "AGENT_MEMORY_INTERNAL_RUN": "1",
                "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT),
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"claude auth status failed: {exc}"
    stdout = (proc.stdout or "").strip()
    detail = (proc.stderr or stdout or "").strip()
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            if bool(payload.get("loggedIn")):
                return True, stdout
            return False, stdout or "Claude Code CLI is not logged in. Run `claude auth login` to authenticate."
    if _looks_unauthenticated(detail):
        return False, detail
    if proc.returncode == 0:
        return True, detail
    return False, detail or f"claude auth status exited with code {proc.returncode}"


def cursor_agent_auth_status() -> tuple[bool, str]:
    executable = shutil.which("cursor-agent")
    if not executable:
        return False, "cursor-agent executable is missing."
    try:
        proc = subprocess.run(
            [executable, "status"],
            text=True,
            capture_output=True,
            timeout=5,
            cwd=str(ROOT),
            env={
                **os.environ,
                "AGENT_MEMORY_INTERNAL_RUN": "1",
                "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT),
            },
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"cursor-agent status failed: {exc}"
    detail = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode == 0 and _looks_unauthenticated(detail):
        return False, detail
    if proc.returncode == 0:
        return True, detail
    return False, detail or f"cursor-agent status exited with code {proc.returncode}"


def runner_auth_status(runner: str) -> tuple[bool, str]:
    if runner == "codex":
        return codex_auth_status()
    if runner == "claude":
        return claude_auth_status()
    if runner == "cursor":
        return cursor_agent_auth_status()
    if not runner_available(runner):
        return False, f"{runner} executable is missing."
    return True, ""


def trigger_cursor_agent_login(session_id: str, *, cool_down_seconds: int = 300) -> str:
    executable = shutil.which("cursor-agent")
    if not executable:
        return "missing_executable"
    marker_dir = LOCK_DIR / "cursor-login"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = marker_dir / f"{safe_slug(session_id)}.json"
    if marker_path.exists():
        try:
            age = time.time() - marker_path.stat().st_mtime
            if age < cool_down_seconds:
                return "recently_triggered"
        except OSError:
            pass
    log_dir = MEMORY_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "cursor-login.log"
    try:
        with open(log_path, "ab") as handle:
            proc = subprocess.Popen(
                [executable, "login"],
                cwd=str(ROOT),
                stdin=subprocess.DEVNULL,
                stdout=handle,
                stderr=handle,
                start_new_session=True,
                close_fds=True,
                env={
                    **os.environ,
                    "AGENT_MEMORY_INTERNAL_RUN": "1",
                    "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT),
                },
            )
        marker_path.write_text(
            json_dumps(
                {
                    "session_id": session_id,
                    "pid": proc.pid,
                    "started_at": utc_now(),
                    "log_path": str(log_path),
                }
            ),
            encoding="utf-8",
        )
        return "started"
    except OSError:
        return "start_failed"


def default_model_for_runner(runner: str) -> str | None:
    if runner == "codex":
        return CODEX_DREAM_MODEL
    if runner == "claude":
        return CLAUDE_DREAM_MODEL
    if runner == "cursor":
        return CURSOR_DREAM_MODEL
    if runner == "antigravity":
        return ANTIGRAVITY_DREAM_MODEL
    if runner == "gemini":
        return GEMINI_DREAM_MODEL
    if runner == "opencode":
        return OPENCODE_DREAM_MODEL
    return None


def model_for_runner(runner: str, requested_model: str | None) -> str | None:
    if requested_model and requested_model != "default":
        return requested_model
    return default_model_for_runner(runner)


def codex_dream_command(response_path: Path, model: str | None = None) -> list[str]:
    command = [
        "codex",
        "exec",
    ]
    if model:
        command.extend(["--model", model])
    command.extend(
        [
            "--disable",
            "hooks",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--skip-git-repo-check",
            "-C",
            str(ROOT),
            "--sandbox",
            "read-only",
            "--json",
            "--output-last-message",
            str(response_path),
            "-",
        ]
    )
    return command


def claude_dream_command(model: str | None = None) -> list[str]:
    return [
        "claude",
        "--print",
        "--model",
        model or CLAUDE_DREAM_MODEL,
        "--tools",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]


def cursor_dream_command(model: str | None = None) -> list[str]:
    command = [
        "cursor-agent",
        "--print",
        "--output-format",
        "json",
        "--mode",
        "ask",
        "--trust",
        "--workspace",
        str(ROOT),
    ]
    if model:
        command.extend(["--model", model])
    return command


def gemini_dream_command(model: str | None = None, *, output_format: str = "text") -> list[str]:
    return [
        "gemini",
        "--model",
        model or GEMINI_DREAM_MODEL,
        "--output-format",
        output_format,
        "--prompt",
    ]


def antigravity_dream_command(model: str | None = None) -> list[str]:
    return [
        "agy",
        "--model",
        model or ANTIGRAVITY_DREAM_MODEL,
        "-p",
    ]


def opencode_dream_command(model: str | None = None) -> list[str]:
    command = [
        "opencode",
        "run",
        "--dir",
        str(ROOT),
        "--auto",
    ]
    if model or OPENCODE_DREAM_MODEL:
        command.extend(["--model", model or OPENCODE_DREAM_MODEL])
    return command


def opencode_stdout_text(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        return ""
    for line in reversed(stripped.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        for key in ("text", "message", "content", "output"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return stripped


def cursor_stdout_text(stdout: str) -> str:
    stripped = stdout.strip()
    if not stripped:
        return ""
    preferred_keys = ("text", "message", "content", "output", "result", "response")
    for line in reversed(stripped.splitlines()):
        candidate = line.strip()
        if not candidate.startswith("{"):
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        for item in reversed(walk_json_values(payload)):
            if isinstance(item, str) and item.strip():
                continue
            if not isinstance(item, dict):
                continue
            for key in preferred_keys:
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list):
                    text_parts = [part.strip() for part in value if isinstance(part, str) and part.strip()]
                    if text_parts:
                        return "\n".join(text_parts)
        if isinstance(payload, dict):
            text_parts: list[str] = []
            for item in walk_json_values(payload):
                if not isinstance(item, str):
                    continue
                value = item.strip()
                if not value or value.startswith("{") or value.startswith("["):
                    continue
                text_parts.append(value)
            if text_parts:
                return text_parts[-1]
    return stripped


def json_event_has_tool_use(value: object) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"type", "event", "event_type", "kind", "name"} and isinstance(item, str):
                item_text = item.lower()
                if "tool" in item_text or item_text in {"exec_command", "apply_patch", "shell", "bash"}:
                    return True
            if key_text in {"tool_name", "tool_use_id", "tool_call_id"} and item:
                return True
            if json_event_has_tool_use(item):
                return True
    elif isinstance(value, list):
        return any(json_event_has_tool_use(item) for item in value)
    return False


def codex_stdout_has_tool_events(stdout: str) -> bool:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if json_event_has_tool_use(event):
            return True
    return False


def int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def walk_json_values(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(walk_json_values(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(walk_json_values(child))
    return values


def _iter_runner_usage_dicts(*texts: str):
    seen: set[str] = set()
    for text in texts:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("{"):
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            for item in walk_json_values(payload):
                if not isinstance(item, dict):
                    continue
                if not any(
                    key in item
                    for key in (
                        "input_tokens",
                        "prompt_tokens",
                        "output_tokens",
                        "completion_tokens",
                        "total_tokens",
                        "inputTokens",
                        "promptTokens",
                        "outputTokens",
                        "completionTokens",
                        "totalTokens",
                    )
                ):
                    continue
                identity = json_dumps(item)
                if identity in seen:
                    continue
                seen.add(identity)
                yield item


def runner_token_usage_available(*texts: str) -> bool:
    return any(True for _ in _iter_runner_usage_dicts(*texts))


def extract_runner_token_usage(*texts: str) -> dict[str, int]:
    totals = {
        "prompt_tokens": 0,
        "cached_prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    for item in _iter_runner_usage_dicts(*texts):
        prompt = int_or_zero(
            item.get("prompt_tokens")
            or item.get("input_tokens")
            or item.get("promptTokens")
            or item.get("inputTokens")
        )
        cached = int_or_zero(
            item.get("cached_prompt_tokens")
            or item.get("cached_input_tokens")
            or item.get("cache_read_input_tokens")
            or item.get("cachedPromptTokens")
            or item.get("cachedInputTokens")
            or item.get("cacheReadTokens")
        )
        completion = int_or_zero(
            item.get("completion_tokens")
            or item.get("output_tokens")
            or item.get("completionTokens")
            or item.get("outputTokens")
        )
        reasoning = int_or_zero(
            item.get("reasoning_tokens")
            or item.get("reasoning_output_tokens")
            or item.get("reasoningTokens")
            or item.get("reasoningOutputTokens")
        )
        total = int_or_zero(item.get("total_tokens") or item.get("totalTokens"))
        if total == 0 and (prompt or completion or reasoning):
            total = prompt + completion + reasoning
        totals["prompt_tokens"] += prompt
        totals["cached_prompt_tokens"] += cached
        totals["completion_tokens"] += completion
        totals["reasoning_tokens"] += reasoning
        totals["total_tokens"] += total
    return totals


def update_dream_run_metrics(conn: sqlite3.Connection, dream_run_id: str, *, duration_ms: int | None, token_usage: dict[str, int]) -> None:
    with conn:
        conn.execute(
            """
            update dream_runs
            set duration_ms = coalesce(?, duration_ms),
                prompt_tokens = ?,
                cached_prompt_tokens = ?,
                completion_tokens = ?,
                reasoning_tokens = ?,
                total_tokens = ?
            where dream_run_id = ?
            """,
            (
                duration_ms,
                token_usage.get("prompt_tokens") or None,
                token_usage.get("cached_prompt_tokens") or None,
                token_usage.get("completion_tokens") or None,
                token_usage.get("reasoning_tokens") or None,
                token_usage.get("total_tokens") or None,
                dream_run_id,
            ),
        )


def metrics_from_dream_paths(paths: list[Path]) -> tuple[int | None, dict[str, int]]:
    token_usage = {
        "prompt_tokens": 0,
        "cached_prompt_tokens": 0,
        "completion_tokens": 0,
        "reasoning_tokens": 0,
        "total_tokens": 0,
    }
    duration_ms: int | None = None
    for path in paths:
        if path.name != "metadata.json" or not path.exists():
            continue
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if duration_ms is None and meta.get("duration_ms") is not None:
            duration_ms = int_or_zero(meta.get("duration_ms")) or None
        raw_usage = meta.get("token_usage") if isinstance(meta, dict) else None
        if isinstance(raw_usage, dict):
            for key in token_usage:
                token_usage[key] += int_or_zero(raw_usage.get(key))
    return duration_ms, token_usage
