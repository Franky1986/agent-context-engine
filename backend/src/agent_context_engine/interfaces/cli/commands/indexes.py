from __future__ import annotations

import argparse
import json
import sys

from ....infrastructure.config import ROOT, ensure_repos_index
from ....infrastructure.db import connect
from ....application.personal import PERSONAL_ROOT, parse_frontmatter, personal_files
from ....application.query_intent import classify_query_intent
from ....application.retrieval import index_memory_document, query_terms, recreate_memory_chunks_fts, search_memory_chunks
from ....infrastructure.text import markdown_escape


def cmd_search(args: argparse.Namespace) -> int:
    conn = connect()
    query_intent = classify_query_intent(query_terms(args.query))
    print(f"query_intent={query_intent['intent']} operational_budget={query_intent['operational_context_budget']}")
    rows = search_memory_chunks(
        conn,
        args.query,
        project_id=args.project,
        intent=args.intent,
        tag=args.tag,
        min_helpful_score=args.min_helpful_score,
        limit=args.limit,
    )
    for row in rows:
        print(f"{row['path']}#{row['chunk_index']} kind={row['kind']} project={row['project_id'] or '-'} intent={row['intent'] or '-'} helpful_score={row['helpful_score'] if row['helpful_score'] is not None else '-'}")
        if row["heading"]:
            print(f"  heading={row['heading']}")
        print(markdown_escape(row["text"], args.chars).replace("\n", "\n  "))
    if not rows:
        print("No matches.")
    return 0


def cmd_rebuild_indexes(args: argparse.Namespace) -> int:
    conn = connect()
    docs = 0
    graph = 0
    with conn:
        recreate_memory_chunks_fts(conn)
        conn.execute("delete from memory_chunks")
        conn.execute("delete from memory_documents")
        conn.execute("delete from dream_tags")
    summary_rows = list(conn.execute(
        """
        select s.session_id, s.project_id, s.thread_name, m.summary_path
        from summaries m
        join sessions s on s.session_id = m.session_id
        """
    ))
    for row in summary_rows:
        path = ROOT / row["summary_path"]
        if index_memory_document(conn, path, kind="summary", session_id=row["session_id"], project_id=row["project_id"], title=row["thread_name"]):
            docs += 1
    dream_rows = list(conn.execute("select * from dream_runs where output_memory_paths_json is not null"))
    for row in dream_rows:
        session = conn.execute("select * from sessions where session_id = ?", (row["session_id"],)).fetchone()
        if session is None:
            continue
        tags = []
        if row["tags_json"]:
            try:
                tags = json.loads(row["tags_json"])
            except json.JSONDecodeError:
                tags = []
        try:
            paths = json.loads(row["output_memory_paths_json"] or "[]")
        except json.JSONDecodeError:
            paths = []
        for rel in paths:
            if "/dream/runs/" in str(rel):
                continue
            path = ROOT / str(rel)
            if path.suffix != ".md":
                continue
            kind = "project_memory" if "/projects/" in str(rel) else "dream"
            if index_memory_document(conn, path, kind=kind, session_id=row["session_id"], dream_run_id=row["dream_run_id"], project_id=session["project_id"], title=session["thread_name"], intent=row["intent"], helpful_score=row["helpful_score"], tags=tags):
                docs += 1
    for path in personal_files():
        rel = path.relative_to(PERSONAL_ROOT)
        meta = parse_frontmatter(path)
        try:
            confidence = float(meta.get("confidence", "0.5"))
        except ValueError:
            confidence = 0.5
        if index_memory_document(
            conn,
            path,
            kind="personal_memory",
            project_id="personal",
            title=str(rel),
            memory_kind=meta.get("memory_kind") or "personal_operating",
            source_kind=meta.get("source_kind") or "manual",
            confidence=confidence,
            risk_level=meta.get("risk_level") or "low",
            sensitivity=meta.get("sensitivity") or "normal",
            injection_policy=meta.get("injection_policy") or "on_demand",
            evidence=meta.get("evidence") or [],
        ):
            docs += 1
    repo_index = ensure_repos_index(ROOT)
    if repo_index.exists():
        if index_memory_document(
            conn,
            repo_index,
            kind="repo_index",
            project_id="personal",
            title="repository-index",
            memory_kind="repo_index",
            source_kind="runtime_repo_index",
            confidence=0.9,
            risk_level="low",
            sensitivity="normal",
            injection_policy="on_demand",
            evidence=[],
        ):
            docs += 1
    if args.graph:
        from ....application.graph import materialize_graph_patch, read_graph_json

        graph_rows = list(conn.execute("select * from graph_artifacts where status = 'valid'"))
        for row in graph_rows:
            try:
                _, patch = read_graph_json(row["path"])
                tags = json.loads(row["tags_json"] or "[]")
                materialize_graph_patch(conn, patch, row["graph_artifact_id"], session_id=row["session_id"] or "", dream_run_id=row["dream_run_id"], intent=row["intent"], helpful_score=row["helpful_score"], tags=tags)
                graph += 1
            except Exception as exc:  # noqa: BLE001
                if args.verbose:
                    print(f"skipped graph artifact {row['path']}: {exc}", file=sys.stderr)
    print(f"rebuilt indexes documents={docs} graph_artifacts={graph}")
    return 0
