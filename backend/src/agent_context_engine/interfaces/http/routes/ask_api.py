from __future__ import annotations

import argparse
from typing import Any

from ....application.monitoring.monitor.ask import (
    monitor_ask as monitor_ask_case,
    build_answer_prompt as build_answer_prompt_case,
    build_query_plan_prompt as build_query_plan_prompt_case,
    deterministic_query_plan as deterministic_query_plan_case,
    extract_json_object as extract_json_object_case,
    llm_query_plan as llm_query_plan_case,
    monitor_retrieval as monitor_retrieval_case,
    neo4j_graph as neo4j_graph_case,
    query_plan_schema as query_plan_schema_case,
    run_monitor_llm as run_monitor_llm_case,
    runner_model as runner_model_case,
    sqlite_graph as sqlite_graph_case,
)


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
    return monitor_ask_case(
        question,
        args,
        graph_view=graph_view,
        retrieval_limit=retrieval_limit,
        graph_limit=graph_limit,
        chunk_context_limit=chunk_context_limit,
        query_expansion_mode=query_expansion_mode,
    )


def deterministic_query_plan(question: str) -> dict[str, Any]:
    return deterministic_query_plan_case(question)


def extract_json_object(text: str) -> dict[str, Any]:
    return extract_json_object_case(text)


def build_query_plan_prompt(question: str) -> str:
    return build_query_plan_prompt_case(question)


def llm_query_plan(question: str, args: argparse.Namespace) -> dict[str, Any]:
    return llm_query_plan_case(question, args)


def monitor_retrieval(question: str, plan: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    return monitor_retrieval_case(question, plan, limit=limit)


def sqlite_graph(query: str, view: str, limit: int, memory_view: str = "both") -> dict[str, Any]:
    return sqlite_graph_case(query, view, limit, memory_view=memory_view)


def neo4j_graph(query: str, view: str, limit: int, args: argparse.Namespace) -> dict[str, Any]:
    return neo4j_graph_case(query, view, limit, args)


def build_answer_prompt(question: str, query_plan: dict[str, Any], chunks: list[dict[str, Any]], graph: dict[str, Any]) -> str:
    return build_answer_prompt_case(question, query_plan, chunks, graph)


def runner_model(runner: str, requested: str | None) -> str | None:
    return runner_model_case(runner, requested)


def query_plan_schema() -> dict[str, Any]:
    return query_plan_schema_case()


def run_monitor_llm(runner: str, model: str | None, prompt: str, timeout: int, *, output_schema: dict[str, Any] | None = None) -> str:
    return run_monitor_llm_case(runner, model, prompt, timeout, output_schema=output_schema)
