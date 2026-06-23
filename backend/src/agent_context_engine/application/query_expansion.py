from __future__ import annotations

import json
from dataclasses import dataclass
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Protocol

from ..adapters.runners.codex import codex_subprocess_env
from ..infrastructure.config import ANTIGRAVITY_DREAM_MODEL, CLAUDE_DREAM_MODEL, CODEX_DREAM_MODEL, CURSOR_DREAM_MODEL, GEMINI_DREAM_MODEL, OPENCODE_DREAM_MODEL, ROOT
from .dreaming.runners import antigravity_dream_command, gemini_dream_command, opencode_dream_command, opencode_stdout_text
from .query_intent import ENTITY_TYPES, RESULT_KIND_WEIGHTS_BY_INTENT, clamp_profile_weight, retrieval_profile_from_terms


@dataclass
class QueryExpansionResult:
    """Value object for query expansion contracts between use-case and adapters."""

    input_language: str
    normalized_english_query: str
    search_queries: tuple[str, ...]
    terms: tuple[str, ...]
    retrieval_profile: dict[str, Any]
    source: str
    llm_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "input_language": self.input_language,
            "normalized_english_query": self.normalized_english_query,
            "search_queries": list(self.search_queries),
            "terms": list(self.terms),
            "retrieval_profile": self.retrieval_profile,
            "source": self.source,
        }
        if self.llm_error is not None:
            payload["llm_error"] = self.llm_error
        return payload

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


GERMAN_HINTS = {
    "architektur",
    "datei",
    "dateien",
    "entscheidung",
    "entscheidungen",
    "hexagonale",
    "offene",
    "offen",
    "suche",
    "wo",
    "ist",
    "was",
    "zuletzt",
    "projekt",
    "ordner",
    "zusammenfassung",
    "speicher",
    "arbeit",
}

ALIASES = {
    "hexagonale architektur": ["hexagonal architecture", "ports adapters architecture"],
    "domänengetriebenes design": ["domain driven design", "ddd"],
    "domaenengetriebenes design": ["domain driven design", "ddd"],
    "arbeitsordner": ["working directory", "workdir", "cwd"],
    "zusammenfassung": ["summary", "brief", "handover"],
    "letzte sessions": ["recent sessions", "last sessions"],
    "speicher": ["memory"],
    "gedächtnis": ["memory"],
    "gedaechtnis": ["memory"],
    "werkzeuge": ["tools"],
    "befehl": ["command"],
    "befehle": ["commands"],
}


class QueryExpansionPort(Protocol):
    """Port contract for retrieval query-expansion strategies."""

    strategy_name: str

    def expand(self, query: str) -> QueryExpansionResult:
        """Resolve normalization profile and search hints for a query."""


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = " ".join(str(value).strip().split())
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            out.append(text)
    return out


def detect_input_language(query: str) -> str:
    lowered = query.lower()
    if re.search(r"[äöüß]", lowered):
        return "de"
    tokens = set(re.findall(r"[\w-]+", lowered))
    if tokens & GERMAN_HINTS:
        return "de"
    return "en"


def deterministic_query_expansion(query: str) -> QueryExpansionResult:
    lowered = query.lower()
    language = detect_input_language(query)
    queries = [query]
    normalized_english = ""
    matched_aliases: list[str] = []
    for phrase, aliases in ALIASES.items():
        if phrase in lowered:
            matched_aliases.extend(aliases)
            queries.extend(aliases)
    if matched_aliases:
        normalized_english = matched_aliases[0]
    elif language == "en":
        normalized_english = query
    terms = _unique(re.findall(r"[\w./:@-]+", query.lower()) + matched_aliases)
    return QueryExpansionResult(
        input_language=language,
        normalized_english_query=normalized_english,
        search_queries=tuple(_unique(queries)),
        terms=tuple(terms),
        retrieval_profile=retrieval_profile_from_terms(terms),
        source="deterministic",
    )


class OffQueryExpansionStrategy:
    strategy_name = "off"

    def expand(self, query: str) -> QueryExpansionResult:
        terms = _unique(re.findall(r"[\w./:@-]+", query.lower()))
        return QueryExpansionResult(
            input_language=detect_input_language(query),
            normalized_english_query="",
            search_queries=(query,),
            terms=tuple(terms),
            retrieval_profile=retrieval_profile_from_terms(terms),
            source=self.strategy_name,
        )


class DeterministicQueryExpansionStrategy:
    strategy_name = "deterministic"

    def expand(self, query: str) -> QueryExpansionResult:
        return deterministic_query_expansion(query)


class LlmQueryExpansionStrategy:
    strategy_name = "llm"

    def __init__(self, *, runner: str | None, model: str | None, timeout: int) -> None:
        self._runner = runner
        self._model = model
        self._timeout = timeout

    def expand(self, query: str) -> QueryExpansionResult:
        if not self._runner:
            return deterministic_query_expansion(query)
        try:
            return llm_query_expansion(query, runner=self._runner, model=self._model, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001
            fallback = deterministic_query_expansion(query)
            return QueryExpansionResult(
                input_language=fallback.input_language,
                normalized_english_query=fallback.normalized_english_query,
                search_queries=fallback.search_queries,
                terms=fallback.terms,
                retrieval_profile=fallback.retrieval_profile,
                source="deterministic_after_llm_error",
                llm_error=str(exc),
            )


def get_query_expansion_strategy(
    *,
    mode: str,
    runner: str | None,
    model: str | None,
    timeout: int,
) -> QueryExpansionPort:
    if mode == "off":
        return OffQueryExpansionStrategy()
    if mode == "llm":
        return LlmQueryExpansionStrategy(runner=runner, model=model, timeout=timeout)
    return DeterministicQueryExpansionStrategy()


def merge_retrieval_profile(fallback: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    profile = json.loads(json.dumps(fallback.get("retrieval_profile") or retrieval_profile_from_terms(fallback.get("terms") or [])))
    parsed_profile = parsed.get("retrieval_profile")
    if not isinstance(parsed_profile, dict):
        return profile
    parsed_entity_weights = parsed_profile.get("entity_type_weights")
    if isinstance(parsed_entity_weights, dict):
        entity_weights = dict(profile.get("entity_type_weights") or {})
        for entity_type, weight in parsed_entity_weights.items():
            if str(entity_type) in ENTITY_TYPES:
                entity_weights[str(entity_type)] = clamp_profile_weight(weight, default=float(entity_weights.get(str(entity_type), 0.0)))
        profile["entity_type_weights"] = entity_weights
    parsed_kind_weights = parsed_profile.get("result_kind_weights")
    allowed_kinds = {kind for weights in RESULT_KIND_WEIGHTS_BY_INTENT.values() for kind in weights}
    if isinstance(parsed_kind_weights, dict):
        kind_weights = dict(profile.get("result_kind_weights") or {})
        for kind, weight in parsed_kind_weights.items():
            if str(kind) in allowed_kinds:
                kind_weights[str(kind)] = clamp_profile_weight(weight, default=float(kind_weights.get(str(kind), 0.0)))
        profile["result_kind_weights"] = kind_weights
    return profile


def _runner_model(runner: str, model: str | None) -> str | None:
    if model and model != "default":
        return model
    return {
        "codex": CODEX_DREAM_MODEL,
        "claude": CLAUDE_DREAM_MODEL,
        "cursor": CURSOR_DREAM_MODEL,
        "antigravity": ANTIGRAVITY_DREAM_MODEL,
        "gemini": GEMINI_DREAM_MODEL,
        "opencode": OPENCODE_DREAM_MODEL,
    }.get(runner)


def _run_hardened_llm(runner: str, model: str | None, prompt: str, timeout: int) -> str:
    env = {**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)}
    resolved_model = _runner_model(runner, model)
    if runner == "codex":
        if not shutil.which("codex"):
            raise RuntimeError("codex executable not found")
        env = codex_subprocess_env(base_env=env)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "query-expansion.json"
            schema = Path(tmp) / "query-expansion.schema.json"
            schema.write_text(
                json.dumps(
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["input_language", "normalized_english_query", "search_queries", "terms"],
                        "properties": {
                            "input_language": {"type": "string"},
                            "normalized_english_query": {"type": "string"},
                            "search_queries": {"type": "array", "items": {"type": "string"}},
                            "terms": {"type": "array", "items": {"type": "string"}},
                            "retrieval_profile": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "entity_type_weights": {"type": "object", "additionalProperties": {"type": "number"}},
                                    "result_kind_weights": {"type": "object", "additionalProperties": {"type": "number"}},
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            command = ["codex", "exec"]
            if resolved_model:
                command.extend(["--model", resolved_model])
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
                    "--output-schema",
                    str(schema),
                    "--output-last-message",
                    str(out),
                    "-",
                ]
            )
            proc = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
            return out.read_text(encoding="utf-8", errors="replace") if out.exists() else proc.stdout
    if runner == "claude":
        command = ["claude", "--print", "--model", resolved_model or CLAUDE_DREAM_MODEL, "--tools", "", "--disable-slash-commands", "--no-session-persistence"]
    elif runner == "cursor":
        command = ["cursor-agent", "--print", "--output-format", "text", "--mode", "ask", "--trust", "--workspace", str(ROOT)]
        if resolved_model:
            command.extend(["--model", resolved_model])
    elif runner == "antigravity":
        command = antigravity_dream_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
        return proc.stdout or ""
    elif runner == "gemini":
        command = gemini_dream_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
        return (proc.stdout or "").strip()
    elif runner == "opencode":
        command = opencode_dream_command(resolved_model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
        return opencode_stdout_text(proc.stdout)
    else:
        raise RuntimeError(f"unsupported runner: {runner}")
    proc = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
    return proc.stdout or ""


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start : end + 1]
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("query expander did not return an object")
    return parsed


def llm_query_expansion(query: str, *, runner: str, model: str | None = None, timeout: int = 20) -> QueryExpansionResult:
    prompt = f"""You normalize a search query for a local agent-memory retrieval system.

Return ONLY strict JSON:
{{
  "input_language": "de|en|other",
  "normalized_english_query": "short English query",
  "search_queries": ["original query", "English equivalent", "important aliases"],
  "terms": ["important terms"],
  "retrieval_profile": {{
    "entity_type_weights": {{"Decision": 1.0, "OpenTask": 1.0, "FileAccess": -0.5, "CLICommand": -0.5}},
    "result_kind_weights": {{"entity": 0.08, "summary": 0.05, "dream": 0.04, "session": 0.03}}
  }}
}}

Rules:
- Preserve proper nouns, project names, file names, ticket names, and IDs exactly.
- If the input is German, include the German original and a concise English equivalent.
- Keep search_queries to at most 6 entries.
- Set entity_type_weights between -1.0 and 1.0 based on what the user is trying to retrieve.
- For file/command/audit/tool questions, boost FileAccess, File, CLICommand, CommandFamily, Directory, Tool.
- For decision/task/architecture/risk questions, boost Decision, OpenTask, FailureMode, Project, Session, Document, Concept, RiskEvent.
- Do not answer the query.

Query: {query}
"""
    raw = _run_hardened_llm(runner, model, prompt, timeout)
    parsed = _parse_json_object(raw)
    fallback = deterministic_query_expansion(query)
    fallback_payload = fallback.to_dict()
    search_queries = _unique([query, *[str(item) for item in parsed.get("search_queries", [])], *fallback_payload["search_queries"]])[:8]
    terms = _unique([str(item) for item in parsed.get("terms", [])] + fallback_payload["terms"])[:20]
    return QueryExpansionResult(
        input_language=str(parsed.get("input_language") or fallback.input_language),
        normalized_english_query=str(parsed.get("normalized_english_query") or fallback.normalized_english_query),
        search_queries=tuple(search_queries),
        terms=tuple(terms),
        retrieval_profile=merge_retrieval_profile(fallback_payload, parsed),
        source="llm",
    )


def build_query_expansion(query: str, *, mode: str = "auto", runner: str | None = None, model: str | None = None, timeout: int = 20) -> QueryExpansionResult:
    strategy = get_query_expansion_strategy(mode=mode, runner=runner, model=model, timeout=timeout)
    return strategy.expand(query)


def query_expansion_payload(expansion: QueryExpansionResult | dict[str, Any] | None) -> dict[str, Any]:
    """Normalize expansion object to transport payload shape."""
    if expansion is None:
        return {}
    if isinstance(expansion, QueryExpansionResult):
        return expansion.to_dict()
    return expansion
