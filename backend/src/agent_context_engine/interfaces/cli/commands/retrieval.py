from __future__ import annotations

import argparse
import sys
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....infrastructure.config import json_dumps
from ....application.runtime_guidance import print_runtime_memory_sandbox_note
from ....application.retrieval import (
    get_retrieval_run,
    list_retrieval_runs,
    retrieve_memory_for_interface,
)
from ....infrastructure.text import markdown_escape


def normalize_path_text(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except OSError:
        return str(Path(value).expanduser())


def local_time(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def cmd_retrieve(args: argparse.Namespace) -> int:
    if not args.query:
        print("# Retrieve")
        print("")
        print("Traceable memory retrieval with ranked results, provenance, and optional safety filtering.")
        print("")
        print("Use:")
        print('- `retrieve "<question or search terms>" --limit 10`')
        print('- `retrieve "<question>" --workdir <absolute-path> --client <runner>` to scope retrieval')
        print('- `retrieval-runs --limit 10` to inspect recent retrievals')
        print_runtime_memory_sandbox_note()
        return 0
    data = retrieve_memory_for_interface(
        args.query,
        project_id=args.project,
        workdir=normalize_path_text(args.workdir) if args.workdir else None,
        client_type=args.client,
        since=args.since,
        until=args.until,
        kind=args.kind,
        include_risky=args.include_risky,
        limit=args.limit,
        runner=args.runner,
        log=not args.no_log,
        query_expansion_mode=args.query_expansion,
        query_expander_runner=args.expander_runner,
        query_expander_model=args.expander_model,
        query_expander_timeout=args.expander_timeout,
        safety_scan=True,
        safety_runner="auto",
    )
    if args.json:
        print(json_dumps(data))
        return 0
    print(f"retrieval_run: {data['retrieval_run_id']}")
    print(f"query: {data['query']}")
    print(f"query_expansion: {json_dumps(data.get('query_expansion', {}))}")
    if data.get("retrieval_safety"):
        safety = data["retrieval_safety"]
        print(f"retrieval_safety: decision={safety.get('decision')} risk={safety.get('risk_level')} classifier_run={safety.get('classifier_run_id')}")
    for index, item in enumerate(data["results"], start=1):
        risk = item.get("risk", {})
        print(
            f"{index}. score={float(item['score']):.3f} kind={item['kind']} id={item['id']} "
            f"risk={risk.get('risk_level', '-')} sensitivity={risk.get('sensitivity', '-')}"
        )
        print(f"   title: {item.get('title') or '-'}")
        if item.get("path"):
            print(f"   path: {item['path']}")
        print(f"   score_breakdown: {json_dumps(item.get('score_breakdown', {}))}")
        print(f"   provenance: {json_dumps(item.get('provenance', {}))}")
        text = str(item.get("text") or "").strip()
        if text:
            print(markdown_escape(text, args.chars).replace("\n", "\n   "))
    if not data["results"]:
        print("No matches.")
    return 0


def cmd_retrieval_runs(args: argparse.Namespace) -> int:
    if (
        args.limit is None
        and args.results is None
        and not args.query
        and not args.project
        and not args.client
        and not args.json
    ):
        print("# Retrieval Runs")
        print("")
        print("Inspect previously persisted retrieval runs and their top results.")
        print("")
        print("Use:")
        print("- `retrieval-runs --limit 10`")
        print("- `retrieval-runs --query <search terms> --limit 10`")
        print("- `retrieval-run <retrieval_run_id>` for one run")
        print_runtime_memory_sandbox_note()
        return 0
    data = list_retrieval_runs(
        query=args.query,
        project_id=args.project,
        client=args.client,
        limit=args.limit or 20,
        results=args.results or 3,
    )
    if args.json:
        print(json_dumps({"runs": data}))
        return 0
    if not data:
        print("No retrieval runs.")
        return 0
    for run in data:
        print(
            f"{local_time(run['started_at'])} {run['retrieval_run_id']} "
            f"status={run['status']} results={run['result_count']} "
            f"project={run.get('project_id') or '-'} client={run.get('client_type') or '-'}"
        )
        print(f"  query: {run['query']}")
        if run.get("workdir"):
            print(f"  workdir: {run['workdir']}")
        for result in run["top_results"]:
            print(
                f"  #{result['rank']} score={float(result['score'] or 0):.3f} "
                f"kind={result['kind']} id={result['id']}"
            )
            if result.get("title"):
                print(f"     title: {result['title']}")
            if result.get("path"):
                print(f"     path: {result['path']}")
            print(f"     score_breakdown: {json_dumps(result.get('score_breakdown', {}))}")
            print(f"     provenance: {json_dumps(result.get('provenance', {}))}")
    return 0


def cmd_retrieval_run(args: argparse.Namespace) -> int:
    data = get_retrieval_run(args.retrieval_run_id)
    if not data:
        print(f"retrieval run not found: {args.retrieval_run_id}", file=sys.stderr)
        return 1
    run = data["run"]
    result_items = data["results"]
    access_rows = data["access_log"]
    if args.json:
        print(json_dumps(data))
        return 0
    print(f"retrieval_run: {run['retrieval_run_id']}")
    print(f"query: {run['query']}")
    print(f"status: {run['status']} results={run['result_count']} started={local_time(run['started_at'])} finished={local_time(run['finished_at'])}")
    print(f"filters: {json_dumps(run.get('filters', {}))}")
    for result in result_items:
        print(
            f"{result['rank']}. score={float(result['score'] or 0):.3f} "
            f"kind={result['result_kind']} id={result['result_id']}"
        )
        print(f"   title: {result.get('title') or '-'}")
        if result.get("path"):
            print(f"   path: {result['path']}")
        print(f"   score_breakdown: {json_dumps(result.get('score_breakdown', {}))}")
        print(f"   provenance: {json_dumps(result.get('provenance', {}))}")
        text = str(result.get("text") or "").strip()
        if text and args.chars:
            print(markdown_escape(text, args.chars).replace("\n", "\n   "))
    if access_rows:
        print("access_log:")
        for access in access_rows:
            print(
                f"  {access['accessed_at']} {access['access_kind']} "
                f"{access['target_kind']} {access['target_id']} used_in_context={access['used_in_context']}"
            )
    return 0
