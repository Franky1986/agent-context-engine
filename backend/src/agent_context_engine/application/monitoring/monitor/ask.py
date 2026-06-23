from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ....adapters.runners.codex import codex_subprocess_env
from ...retrieval import query_terms, search_memory_chunks, significant_terms
from ....infrastructure.config import ANTIGRAVITY_DREAM_MODEL, CLAUDE_DREAM_MODEL, CODEX_DREAM_MODEL, CURSOR_DREAM_MODEL, GEMINI_DREAM_MODEL, OPENCODE_DREAM_MODEL, ROOT, json_dumps
from ....infrastructure.db import connect
from ...graph import neo4j_config_for_args, neo4j_query_rows
from ...dreaming.runners import antigravity_dream_command, gemini_dream_command, opencode_dream_command, opencode_stdout_text
from .graph import sqlite_graph as monitor_graph_sqlite_graph


def deterministic_query_plan(question: str) -> dict[str, Any]:
    terms = significant_terms(query_terms(question))
    compact = " ".join(terms) if terms else question
    return {
        "rewritten_question": question,
        "search_queries": [compact, question] if compact != question else [question],
        "graph_queries": [compact] if compact else [question],
        "entity_hints": [],
        "reason": "deterministic corpus-aware fallback",
    }


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start < 0 or end < start:
        raise ValueError("query planner returned no JSON object")
    return json.loads(stripped[start : end + 1])


def build_query_plan_prompt(question: str) -> str:
    return f"""You are translating a user's question into search instructions for a local agent-memory archive.
Return exactly one RFC-8259 JSON object. Do not use markdown. Do not call tools.

The archive contains markdown handovers, dream summaries, graph entities, file paths, project names, commands, tools, and concepts from coding-agent sessions.

Create a compact retrieval plan:
- rewritten_question: one concise German restatement of the user's intent
- search_queries: 3 to 8 exact text searches, ordered by expected usefulness
- graph_queries: 1 to 5 entity/concept searches, ordered by expected usefulness
- entity_hints: short candidate entities, project names, paths, tools, technologies, or concepts
- reason: one short explanation

Infer useful synonyms, project names, and likely entity forms, but do not invent facts.
For location/path questions, include likely project/path query variants.

User question:
{question}
"""


def llm_query_plan(question: str, args: argparse.Namespace) -> dict[str, Any]:
    prompt = build_query_plan_prompt(question)
    text = run_monitor_llm(args.runner, runner_model(args.runner, args.runner_model), prompt, min(args.runner_timeout, 90), output_schema=query_plan_schema())
    raw_plan = extract_json_object(text)
    fallback = deterministic_query_plan(question)
    plan = {
        "rewritten_question": str(raw_plan.get("rewritten_question") or fallback["rewritten_question"]),
        "search_queries": [str(item) for item in raw_plan.get("search_queries") or [] if str(item).strip()],
        "graph_queries": [str(item) for item in raw_plan.get("graph_queries") or [] if str(item).strip()],
        "entity_hints": [str(item) for item in raw_plan.get("entity_hints") or [] if str(item).strip()],
        "reason": str(raw_plan.get("reason") or "llm query planner"),
    }
    if not plan["search_queries"]:
        plan["search_queries"] = fallback["search_queries"]
    if not plan["graph_queries"]:
        plan["graph_queries"] = fallback["graph_queries"]
    return plan


def _query_expansion_mode_from_env() -> str:
    mode = (os.environ.get("AGENT_MEMORY_QUERY_EXPANSION_MODE") or "auto").strip().lower()
    if mode in {"auto", "deterministic", "off", "llm"}:
        return mode
    return "auto"


def monitor_retrieval(question: str, plan: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    conn = connect()
    try:
        queries = [*plan.get("search_queries", []), question]
        seen: set[str] = set()
        results: list[dict[str, Any]] = []
        for query in queries:
            for row in search_memory_chunks(conn, query, limit=limit):
                item = dict(row)
                key = str(item.get("chunk_id"))
                if key in seen:
                    continue
                seen.add(key)
                results.append(item)
                if len(results) >= limit:
                    return results
        return results
    finally:
        conn.close()


def sqlite_graph(query: str, view: str, limit: int, memory_view: str = "both") -> dict[str, Any]:
    return monitor_graph_sqlite_graph(query=query, view=view, limit=limit, memory_view=memory_view)


def neo4j_graph(query: str, view: str, limit: int, args: argparse.Namespace) -> dict[str, Any]:
    config = neo4j_config_for_args(args)
    if not config["password"]:
        return {"nodes": [], "links": [], "source": "neo4j", "error": "Neo4j password not configured"}
    _, rows = neo4j_query_rows(
        args,
        """
        MATCH (n:AgentMemoryEntity)
        WHERE toLower(coalesce(n.name,'')) CONTAINS toLower($q)
           OR toLower(coalesce(n.key,'')) CONTAINS toLower($q)
        WITH n LIMIT $limit
        OPTIONAL MATCH (n)-[:AM_RELATION_FROM|AM_RELATION_TO]-(rel:AgentMemoryRelation)
        OPTIONAL MATCH (rel)-[:AM_RELATION_FROM|AM_RELATION_TO]-(m:AgentMemoryEntity)
        RETURN n.entity_id, n.name, n.type, collect(distinct [rel.key, rel.type, m.entity_id, m.name, m.type])[0..80]
        """,
        {"q": query, "limit": int(limit)},
    )
    nodes: dict[str, dict[str, Any]] = {}
    links: list[dict[str, Any]] = []
    for entity_id, name, etype, rels in rows:
        if not entity_id:
            continue
        nodes[entity_id] = {"id": entity_id, "name": name or entity_id, "type": etype or "Entity", "size": 11}
        for rel_key, rel_type, other_id, other_name, other_type in rels or []:
            if not rel_key or not other_id or other_id == entity_id:
                continue
            nodes[other_id] = {"id": other_id, "name": other_name or other_id, "type": other_type or "Entity", "size": 8}
            links.append({"source": entity_id, "target": other_id, "type": rel_type or "RELATED", "weight": 1})
    return {"nodes": list(nodes.values()), "links": links, "source": "neo4j"}


def build_answer_prompt(question: str, query_plan: dict[str, Any], chunks: list[dict[str, Any]], graph: dict[str, Any]) -> str:
    context = "\n\n".join(
        f"<memory_chunk path=\"{item.get('path')}\" kind=\"{item.get('kind')}\" project=\"{item.get('project_id')}\">\n{item.get('text','')[:1800]}\n</memory_chunk>"
        for item in chunks[:8]
    )
    graph_context = json_dumps({"nodes": graph.get("nodes", [])[:30], "links": graph.get("links", [])[:50]})
    return f"""You answer questions about a local Agent Context Engine system.
Use only the following retrieval and graph context.
If the context is insufficient, state exactly what is missing and which agent-memory search would be useful.
Answer concisely and factually.

Question:
{question}

Query-Plan:
{json_dumps(query_plan)}

Retrieval Context:
{context or '_No chunks found._'}

Graph Context:
{graph_context}
"""


def runner_model(runner: str, requested: str | None) -> str | None:
    if requested and requested != "default":
        return requested
    return {
        "codex": CODEX_DREAM_MODEL,
        "claude": CLAUDE_DREAM_MODEL,
        "cursor": CURSOR_DREAM_MODEL,
        "antigravity": ANTIGRAVITY_DREAM_MODEL,
        "gemini": GEMINI_DREAM_MODEL,
        "opencode": OPENCODE_DREAM_MODEL,
    }.get(runner)


def query_plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["rewritten_question", "search_queries", "graph_queries", "entity_hints", "reason"],
        "properties": {
            "rewritten_question": {"type": "string"},
            "search_queries": {"type": "array", "items": {"type": "string"}},
            "graph_queries": {"type": "array", "items": {"type": "string"}},
            "entity_hints": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
        },
    }


def run_monitor_llm(runner: str, model: str | None, prompt: str, timeout: int, *, output_schema: dict[str, Any] | None = None) -> str:
    env = {**os.environ, "AGENT_MEMORY_DREAM": "1", "AGENT_CONTEXT_ENGINE_ROOT": str(ROOT)}
    if runner == "codex":
        if not shutil.which("codex"):
            raise RuntimeError("codex executable not found")
        env = codex_subprocess_env(base_env=env)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "answer.md"
            schema_path = None
            if output_schema:
                schema_path = Path(tmp) / "output.schema.json"
                schema_path.write_text(json_dumps(output_schema), encoding="utf-8")
            command = ["codex", "exec"]
            if model:
                command.extend(["--model", model])
            command.extend(
                ["-c", 'model_reasoning_effort="low"', "--disable", "hooks", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "-C", str(ROOT), "--sandbox", "read-only", "--json"]
            )
            if schema_path:
                command.extend(["--output-schema", str(schema_path)])
            command.extend(["--output-last-message", str(out), "-"])
            proc = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
            if proc.returncode != 0:
                raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
            return out.read_text(encoding="utf-8", errors="replace") if out.exists() else proc.stdout
    if runner == "claude":
        command = ["claude", "--print", "--model", model or CLAUDE_DREAM_MODEL, "--tools", "", "--disable-slash-commands", "--no-session-persistence"]
    elif runner == "cursor":
        command = ["cursor-agent", "--print", "--output-format", "text", "--mode", "ask", "--trust", "--workspace", str(ROOT)]
        if model:
            command.extend(["--model", model])
    elif runner == "antigravity":
        command = antigravity_dream_command(model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
        return (proc.stdout or "").strip()
    elif runner == "gemini":
        command = gemini_dream_command(model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
        return (proc.stdout or "").strip()
    elif runner == "opencode":
        command = opencode_dream_command(model)
        proc = subprocess.run(command + [prompt], text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
        return opencode_stdout_text(proc.stdout)
    else:
        raise RuntimeError(f"unsupported runner: {runner}")
    proc = subprocess.run(command, input=prompt, text=True, capture_output=True, timeout=timeout, cwd=str(ROOT), env=env)
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout)[-1000:])
    return (proc.stdout or "").strip()


def monitor_ask(
    question: str,
    args: argparse.Namespace,
    *,
    graph_view: str = "search",
    retrieval_limit: int = 10,
    graph_limit: int = 50,
    chunk_context_limit: int = 8,
    query_expansion_mode: str | None = None,
) -> dict[str, Any]:
    query_mode = (query_expansion_mode or _query_expansion_mode_from_env()).strip().lower()
    if query_mode not in {"auto", "deterministic", "off", "llm"}:
        query_mode = "auto"
    try:
        if query_mode in {"deterministic", "off"}:
            query_plan = deterministic_query_plan(question)
            query_plan["reason"] = "forced deterministic query plan"
        else:
            query_plan = llm_query_plan(question, args)
    except Exception as exc:  # noqa: BLE001
        query_plan = deterministic_query_plan(question)
        query_plan["planner_error"] = str(exc)
    chunks = monitor_retrieval(question, query_plan, limit=retrieval_limit)
    graph_query = " ".join(query_plan.get("graph_queries", [])[:3]) or question
    graph = sqlite_graph(graph_query, graph_view, graph_limit)
    prompt = build_answer_prompt(question, query_plan, chunks, graph)
    answer = run_monitor_llm(
        args.runner,
        runner_model(args.runner, args.runner_model),
        prompt,
        args.runner_timeout,
    )
    return {"answer": answer, "query_plan": query_plan, "chunks": chunks[:chunk_context_limit], "graph": graph}
