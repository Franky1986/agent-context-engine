from __future__ import annotations

import argparse
import json
import json.decoder
from pathlib import Path

from ...infrastructure.config import ROOT, json_dumps
from ...domain.graph import GraphArtifact
from ...infrastructure.db import connect, resolve_session
from .adapters import display_path, graph_artifact_path, write_graph_artifact, deterministic_graph_patch, llm_graph_run
from .operations import graph_extract_for_session, graph_source_paths, graph_structure_for_session, latest_dream_run
from .adapters import graph_schema_context, validate_graph_patch
from ...infrastructure.text import read_text_limited


def cmd_graph_extract(args: argparse.Namespace) -> int:
    conn = connect()
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}")
        return 1
    dream_run = latest_dream_run(conn, session["session_id"]) if args.latest_dream else None
    path = graph_extract_for_session(conn, session, dream_run=dream_run)
    print(f"wrote {display_path(path)}")
    return 0


def cmd_graph_structure(args: argparse.Namespace) -> int:
    conn = connect()
    session = resolve_session(conn, args.selector)
    if session is None:
        print(f"No session found for selector: {args.selector}")
        return 1
    dream_run = latest_dream_run(conn, session["session_id"]) if args.latest_dream else None
    runner = (session["preferred_dream_runner"] or session["client_type"]) if args.runner == "same-as-session" else args.runner
    if runner in {"codex", "claude", "cursor", "antigravity", "gemini", "opencode"} and dream_run is not None:
        patch = deterministic_graph_patch(conn, session, dream_run=dream_run)
        path = graph_artifact_path("patches", f"graph_patch_{dream_run['dream_run_id']}")
        source_paths = graph_source_paths(dream_run)
        artifact_runner = runner
        conn.close()
        try:
            patch, llm_source_paths = llm_graph_run(
                session,
                dream_run,
                patch,
                runner=runner,
                model=args.runner_model,
                timeout=args.runner_timeout,
            )
            source_paths.extend(llm_source_paths)
            artifact_runner = f"{runner}:llm"
        except Exception as exc:  # noqa: BLE001
            patch["generated_by"] = f"{runner}:deterministic-graph-fallback"
            patch["llm_structuring_error"] = str(exc)
            source_paths.append(f"llm_graph_error:{str(exc)[:500]}")
            artifact_runner = f"{runner}:deterministic-fallback"
        conn = connect()
        write_graph_artifact(
            conn,
            patch=patch,
            artifact_type="patch",
            path=path,
            session_id=session["session_id"],
            dream_run_id=dream_run["dream_run_id"],
            runner=artifact_runner,
            source_paths=source_paths,
        )
    else:
        path = graph_structure_for_session(conn, session, dream_run=dream_run, runner=runner, model=args.runner_model, timeout=args.runner_timeout)
    print(f"wrote {display_path(path)}")
    return 0


def cmd_graph_status(args: argparse.Namespace) -> int:
    conn = connect()
    where: list[str] = []
    params: list[object] = []
    if args.intent:
        where.append("intent = ?")
        params.append(args.intent)
    if args.min_helpful_score is not None:
        where.append("coalesce(helpful_score, 0) >= ?")
        params.append(args.min_helpful_score)
    if args.tag:
        where.append("coalesce(tags_json, '') like ?")
        params.append(f"%{args.tag}%")
    where_sql = "where " + " and ".join(where) if where else ""
    rows = list(
        conn.execute(
            f"""
            select *
            from graph_artifacts
            {where_sql}
            order by created_at desc
            limit ?
            """,
            (*params, args.limit),
        )
    )
    artifact_total = conn.execute(
        f"""
        select count(*)
        from graph_artifacts
        {where_sql}
        """,
        tuple(params),
    ).fetchone()[0]
    entity_total = conn.execute("select count(*) from graph_entities").fetchone()[0]
    relation_total = conn.execute("select count(*) from graph_relations").fetchone()[0]
    evidence_total = conn.execute("select count(*) from graph_evidence").fetchone()[0]
    schema_registry_rows = list(conn.execute("select kind, status, count(*) as count from graph_schema_registry group by kind, status order by kind, status"))
    if args.intent or args.tag or args.min_helpful_score is not None:
        print(
            f"graph_status filter={ 'intent=' + args.intent if args.intent else ''}"
            f"{' tag=' + args.tag if args.tag else ''}"
            f"{' min_helpful_score=' + str(args.min_helpful_score) if args.min_helpful_score is not None else ''}"
        )
    print(
        f"graph_status: graph_artifacts={artifact_total} graph_entities={entity_total} "
        f"graph_relations={relation_total} graph_evidence={evidence_total}"
    )
    if not schema_registry_rows:
        print("graph_schema_registry: (none)")
    else:
        for row in schema_registry_rows:
            print(f"graph_schema_registry: kind={row['kind']} status={row['status']} count={row['count']}")
    artifacts = [GraphArtifact.from_row(row) for row in rows]
    if not rows:
        print("No graph artifacts recorded.")
        return 0
    for artifact in artifacts:
        print(
            f"{artifact.created_at} {artifact.artifact_type} {artifact.status} "
            f"entities={artifact.entity_count} relations={artifact.relation_count} evidence={artifact.evidence_count}"
        )
        print(
            f"  session={artifact.session_id or '-'} dream={artifact.dream_run_id or '-'} runner={artifact.runner or '-'}"
        )
        if artifact.has_signal:
            print(
                f"  intent={artifact.intent or '-'} helpful_score={artifact.helpful_score if artifact.helpful_score is not None else '-'} "
                f"tags={json_dumps(artifact.tags) if artifact.tags else '[]'}"
            )
        print(f"  path={artifact.short_path()}")
        if artifact.error_message:
            print(f"  error={artifact.error_message}")
    return 0


def cmd_graph_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    if not path.is_absolute():
        path = ROOT / path
    try:
        text = read_text_limited(path, 5_000_000)
    except OSError as exc:
        print(f"invalid_graph_patch: failed to read path: {exc}")
        return 1
    if not text:
        print("invalid_graph_patch: empty or unreadable graph patch")
        return 1
    try:
        patch = json.loads(text)
    except json.decoder.JSONDecodeError as exc:
        print(f"invalid_graph_patch: malformed json at {path.name}: {exc}")
        return 1
    if not isinstance(patch, dict):
        print("invalid_graph_patch: expected top-level json object")
        return 1
    try:
        errors = validate_graph_patch(patch)
    except (AttributeError, TypeError) as exc:
        print(f"invalid_graph_patch: schema mismatch ({exc})")
        return 1
    if errors:
        for error in errors:
            print(f"invalid_graph_patch: {error}")
        return 1
    print(f"valid {display_path(path)}")
    return 0


def cmd_graph_schema_context(args: argparse.Namespace) -> int:
    context = graph_schema_context()
    if args.format == "json":
        print(json_dumps(context))
        return 0
    print("# Agent Context Engine Graph Schema Context")
    print("")
    print(f"- patch_schema_version: `{context['schema_version']}`")
    print(f"- candidate_schema_version: `{context['candidate_schema_version']}`")
    print("")
    print("## Entity Types")
    print("")
    for item in context["entity_types"]:
        print(f"- `{item}`")
    print("")
    print("## Relation Types")
    print("")
    for item in context["relation_types"]:
        print(f"- `{item}`")
    print("")
    print("## Neo4j Internal Relation Types")
    print("")
    for item in context["neo4j_internal_relation_types"]:
        print(f"- `{item}`")
    print("")
    print("## Rules")
    print("")
    for item in context["rules"]:
        print(f"- {item}")
    return 0
