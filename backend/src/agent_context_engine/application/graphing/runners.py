from __future__ import annotations

import json
from pathlib import Path

from ...infrastructure.config import ANTIGRAVITY_DREAM_MODEL, CLAUDE_DREAM_MODEL, CODEX_DREAM_MODEL, CURSOR_DREAM_MODEL, GEMINI_DREAM_MODEL, OPENCODE_DREAM_MODEL, ROOT


def graph_runner_model(runner: str, model: str | None) -> str | None:
    if model and model != "default":
        return model
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


def codex_graph_command(response_path: Path, model: str | None = None) -> list[str]:
    command = ["codex", "exec"]
    if model:
        command.extend(["--model", model])
    command.extend(
        [
            "-c",
            'model_reasoning_effort="low"',
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


def claude_graph_command(model: str | None = None) -> list[str]:
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


def cursor_graph_command(model: str | None = None) -> list[str]:
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


def gemini_graph_command(model: str | None = None) -> list[str]:
    return [
        "gemini",
        "--model",
        model or GEMINI_DREAM_MODEL,
        "--output-format",
        "text",
        "--prompt",
    ]


def antigravity_graph_command(model: str | None = None) -> list[str]:
    return [
        "agy",
        "--model",
        model or ANTIGRAVITY_DREAM_MODEL,
        "--output-format",
        "text",
        "--prompt",
    ]


def opencode_graph_command(model: str | None = None) -> list[str]:
    command = [
        "opencode",
        "run",
        "--dir",
        str(ROOT),
        "--dangerously-skip-permissions",
    ]
    if model or OPENCODE_DREAM_MODEL:
        command.extend(["--model", model or OPENCODE_DREAM_MODEL])
    return command


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
