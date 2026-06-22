from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from ..query_intent import (
    HIGH_VALUE_ENTITY_TYPES,
    OPERATIONAL_ENTITY_TYPES,
    classify_query_intent,
    entity_type_weight_for_query,
)
from ...domain.graph import (
    GraphCuratedContext,
    GraphCuratedEntity,
    GraphCuratedRelation,
    GraphCountSummary,
    GraphQueryAssessment,
    GraphExpectedPresence,
    GraphQualityEvaluation,
    GraphQualityOverview,
    GraphResolutionCandidate,
)
from ..retrieval import query_terms, search_memory_chunks, significant_terms
from ...infrastructure.config import ROOT, json_dumps
from ...infrastructure.db import connect


GENERIC_NAMES = {
    "default",
    "decision",
    "entscheidung",
    "gilt",
    "offen",
    "open task",
    "todo",
    "follow-up",
    "nächste",
    "naechste",
}
DEFAULT_EVAL_QUERIES = [
    "What is still open for agent-memory?",
    "Why was graph-prune built and what can be deleted?",
    "Which sessions and files are most important for Agent Memory firewall risk handling?",
    "How are workManagement and the standalone agent-memory repository connected?",
    "Which Neo4j or graph improvements are pending?",
]
_CANONICAL_SURFACE_RE = re.compile(r"[^a-z0-9]+")


def _count(conn: Any, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(row[0] if row else 0)


def _canonical_surface(value: str) -> str:
    return _CANONICAL_SURFACE_RE.sub(" ", value.lower()).strip()


def _load_eval_questions(path_arg: str | None) -> list[dict[str, Any]]:
    if not path_arg:
        return [{"query": query} for query in DEFAULT_EVAL_QUERIES]
    path = Path(path_arg)
    if not path.is_absolute():
        path = ROOT / path
    data = json.loads(path.read_text(encoding="utf-8"))
    questions: list[dict[str, Any]] = []
    for item in data.get("questions", []):
        query = str(item.get("query") or "").strip()
        if query:
            questions.append(dict(item, query=query))
    return questions or [{"query": query} for query in DEFAULT_EVAL_QUERIES]


def quality_overview(conn: Any) -> GraphQualityOverview:
    entity_total = _count(conn, "select count(*) from graph_entities")
    relation_total = _count(conn, "select count(*) from graph_relations")
    evidence_total = _count(conn, "select count(*) from graph_evidence")
    entity_evidence_total = _count(
        conn,
        """
        select count(*)
        from graph_entities ge
        where exists (
          select 1 from graph_evidence ev
          where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id
        )
        """,
    )
    relation_evidence_total = _count(
        conn,
        """
        select count(*)
        from graph_relations gr
        where exists (
          select 1 from graph_evidence ev
          where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id
        )
        """,
    )
    orphan_entity_total = _count(
        conn,
        """
        select count(*)
        from graph_entities ge
        where not exists (
          select 1 from graph_relations gr
          where gr.from_entity_id = ge.entity_id or gr.to_entity_id = ge.entity_id
        )
        """,
    )
    source_anchored_entity_total = _count(
        conn,
        """
        select count(*)
        from graph_entities
        where coalesce(session_id, '') <> '' or coalesce(dream_run_id, '') <> ''
        """,
    )
    operational_total = _count(
        conn,
        f"select count(*) from graph_entities where type in ({','.join('?' for _ in OPERATIONAL_ENTITY_TYPES)})",
        tuple(sorted(OPERATIONAL_ENTITY_TYPES)),
    )
    high_value_total = _count(
        conn,
        f"select count(*) from graph_entities where type in ({','.join('?' for _ in HIGH_VALUE_ENTITY_TYPES)})",
        tuple(sorted(HIGH_VALUE_ENTITY_TYPES)),
    )
    generic_semantic_total = _count(
        conn,
        f"""
        select count(*)
        from graph_entities
        where type in ('Decision','OpenTask','FailureMode')
          and lower(name) in ({','.join('?' for _ in GENERIC_NAMES)})
        """,
        tuple(sorted(GENERIC_NAMES)),
    )
    duplicate_rows = list(
        conn.execute(
            """
            select type, lower(name) as normalized_name, count(*) as count
            from graph_entities
            where coalesce(name, '') <> ''
            group by type, lower(name)
            having count(*) > 1
            order by count desc
            limit 20
            """
        )
    )
    type_rows = list(
        conn.execute(
            """
            select type, count(*) as count
            from graph_entities
            group by type
            order by count desc
            limit 30
            """
        )
    )
    relation_rows = list(
        conn.execute(
            """
            select relation_type, count(*) as count
            from graph_relations
            group by relation_type
            order by count desc
            limit 30
            """
        )
    )
    resolution_candidates = _entity_resolution_candidates(conn)
    return GraphQualityOverview(
        entity_total=entity_total,
        relation_total=relation_total,
        evidence_total=evidence_total,
        entity_evidence_total=entity_evidence_total,
        relation_evidence_total=relation_evidence_total,
        orphan_entity_total=orphan_entity_total,
        source_anchored_entity_total=source_anchored_entity_total,
        operational_entity_total=operational_total,
        high_value_entity_total=high_value_total,
        generic_semantic_entity_total=generic_semantic_total,
        top_entity_types=[GraphCountSummary.from_row(row) for row in type_rows],
        top_relation_types=[GraphCountSummary.from_row(row) for row in relation_rows],
        duplicate_name_groups=[GraphCountSummary.from_row(row) for row in duplicate_rows],
        entity_resolution_candidates=resolution_candidates,
    )


def _entity_resolution_candidates(conn: Any, *, limit: int = 12) -> list[GraphResolutionCandidate]:
    groups: dict[str, dict[str, Any]] = {}
    for row in conn.execute(
        """
        select type, name, key
        from graph_entities
        where coalesce(name, '') <> ''
          and type not in ('FileAccess','CLICommand','Tool','Directory')
        """
    ):
        surface = _canonical_surface(str(row["name"] or ""))
        if len(surface) < 4 or surface in GENERIC_NAMES:
            continue
        group = groups.setdefault(surface, {"surface": surface, "count": 0, "types": set(), "examples": []})
        group["count"] += 1
        group["types"].add(str(row["type"] or ""))
        if len(group["examples"]) < 6:
            group["examples"].append({"type": row["type"], "name": row["name"], "key": row["key"]})
    candidates = [
        GraphResolutionCandidate(
            surface=group["surface"],
            count=group["count"],
            types=sorted(group["types"]),
            examples=group["examples"],
        )
        for group in groups.values()
        if group["count"] > 1 and len(group["types"]) > 1
    ]
    candidates.sort(key=lambda item: (-int(item.count), item.surface))
    return candidates[:limit]


def curated_graph_context(conn: Any, query: str, *, limit: int = 8) -> GraphCuratedContext:
    terms = significant_terms(query_terms(query))
    if not terms:
        terms = query_terms(query)
    if not terms:
        terms = [query.lower()]
    intent_profile = classify_query_intent(terms)
    where_parts: list[str] = []
    params: list[Any] = []
    for term in terms[:8]:
        like = f"%{term}%"
        where_parts.append("(name like ? or key like ? or coalesce(aliases_json, '') like ? or coalesce(properties_json, '') like ?)")
        params.extend([like, like, like, like])
    rows = list(
        conn.execute(
            f"""
            select ge.*,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id) as evidence_count,
                   (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id or gr.to_entity_id = ge.entity_id) as relation_count
            from graph_entities ge
            where {' or '.join(where_parts)}
            limit 200
            """,
            tuple(params),
        )
    )
    scored: list[tuple[float, Any]] = []
    query_lower = query.lower()
    for row in rows:
        name = str(row["name"] or "")
        key = str(row["key"] or "")
        entity_type = str(row["type"] or "")
        exact = 1.0 if query_lower in name.lower() or query_lower in key.lower() else 0.0
        term_hits = sum(1 for term in terms if term in name.lower() or term in key.lower())
        score = (
            exact
            + min(1.0, term_hits / max(1, len(terms)))
            + entity_type_weight_for_query(entity_type, str(intent_profile["intent"]))
            + min(0.4, float(row["evidence_count"] or 0) * 0.03)
            + min(0.35, float(row["relation_count"] or 0) * 0.01)
            + min(0.25, float(row["confidence"] or 0.0) * 0.25)
        )
        if name.lower() in GENERIC_NAMES:
            score -= 0.8
        scored.append((score, row))
    scored.sort(key=lambda item: (-item[0], str(item[1]["type"]), str(item[1]["name"])))
    entities = []
    selected_ids = []
    for score, row in scored[:limit]:
        selected_ids.append(row["entity_id"])
        entities.append(
            {
                "entity_id": row["entity_id"],
                "type": row["type"],
                "name": row["name"],
                "key": row["key"],
                "score": round(score, 4),
                "evidence_count": int(row["evidence_count"] or 0),
                "relation_count": int(row["relation_count"] or 0),
            }
        )
    if not selected_ids:
        return GraphCuratedContext(
            query=query,
            terms=terms,
            intent_profile=intent_profile,
            entities=[],
            relations=[],
            quality_notes=["no curated graph entities matched"],
            max_score=0.0,
        )
    placeholders = ",".join("?" for _ in selected_ids)
    relation_rows = list(
        conn.execute(
            f"""
            select gr.relation_type, gr.confidence,
                   f.entity_id as from_id, f.type as from_type, f.name as from_name,
                   t.entity_id as to_id, t.type as to_type, t.name as to_name,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
            from graph_relations gr
            join graph_entities f on f.entity_id = gr.from_entity_id
            join graph_entities t on t.entity_id = gr.to_entity_id
            where gr.from_entity_id in ({placeholders}) or gr.to_entity_id in ({placeholders})
            order by
              case when f.type in ('FileAccess','CLICommand','Tool','Directory') or t.type in ('FileAccess','CLICommand','Tool','Directory') then 1 else 0 end,
              coalesce(gr.confidence, 0) desc,
              gr.last_seen_at desc
            limit ?
            """,
            (*selected_ids, *selected_ids, limit * 4),
        )
    )
    relations = [GraphCuratedRelation.from_mapping(row) for row in relation_rows]
    curated_entities = [GraphCuratedEntity.from_mapping(item) for item in entities]
    notes = []
    generic_hits = [item for item in curated_entities if str(item.name).lower() in GENERIC_NAMES]
    if generic_hits:
        notes.append(f"{len(generic_hits)} generic semantic entity name(s) still matched")
    operational_relations = [
        rel
        for rel in relations
        if rel.from_entity["type"] in OPERATIONAL_ENTITY_TYPES or rel.to_entity["type"] in OPERATIONAL_ENTITY_TYPES
    ]
    if operational_relations:
        notes.append(
            f"{len(operational_relations)} operational/supporting relation(s) included "
            f"with {intent_profile['intent']} query budget={intent_profile['operational_context_budget']}"
        )
    max_score = float(entities[0]["score"]) if entities else 0.0
    if max_score < 1.75:
        notes.append("weak graph match; text retrieval should dominate or graph needs fresher/cleaner entities")
    return GraphCuratedContext(
        query=query,
        terms=terms,
        intent_profile=intent_profile,
        entities=curated_entities,
        relations=relations,
        quality_notes=notes,
        max_score=max_score,
    )


def _expected_presence(
    conn: Any,
    graph_context: GraphCuratedContext,
    *,
    expected_entity_types: list[str],
    expected_relation_types: list[str],
) -> GraphExpectedPresence:
    seen_entity_types = {str(entity.type) for entity in graph_context.entities}
    seen_relation_types = {str(relation.type) for relation in graph_context.relations}
    for entity_type in expected_entity_types:
        if entity_type in seen_entity_types:
            continue
        row = conn.execute("select 1 from graph_entities where type = ? limit 1", (entity_type,)).fetchone()
        if row is not None:
            seen_entity_types.add(entity_type)
    for relation_type in expected_relation_types:
        if relation_type in seen_relation_types:
            continue
        row = conn.execute("select 1 from graph_relations where relation_type = ? limit 1", (relation_type,)).fetchone()
        if row is not None:
            seen_relation_types.add(relation_type)
    missing_entity_types = [entity_type for entity_type in expected_entity_types if entity_type not in seen_entity_types]
    missing_relation_types = [relation_type for relation_type in expected_relation_types if relation_type not in seen_relation_types]
    return GraphExpectedPresence(
        expected_entity_types=expected_entity_types,
        expected_relation_types=expected_relation_types,
        seen_entity_types=sorted(seen_entity_types),
        seen_relation_types=sorted(seen_relation_types),
        missing_entity_types=missing_entity_types,
        missing_relation_types=missing_relation_types,
    )


def evaluate_queries(conn: Any, questions: list[dict[str, Any]], *, limit: int) -> list[GraphQualityEvaluation]:
    evaluations: list[GraphQualityEvaluation] = []
    for question in questions:
        query = str(question.get("query") or "")
        text_rows = search_memory_chunks(conn, query, limit=limit)
        text_results = [
            {
                "kind": row["kind"],
                "title": row["title"] or row["heading"] or row["path"],
                "path": f"{row['path']}#{row['chunk_index']}",
                "session_id": row["session_id"],
                "dream_run_id": row["dream_run_id"],
            }
            for row in text_rows
        ]
        graph_context = curated_graph_context(conn, query, limit=limit)
        expected = _expected_presence(
            conn,
            graph_context,
            expected_entity_types=[str(item) for item in question.get("expected_entity_types", [])],
            expected_relation_types=[str(item) for item in question.get("expected_relation_types", [])],
        )
        assessment = GraphQueryAssessment(
            text_result_count=len(text_results),
            graph_entity_count=len(graph_context.entities),
            graph_relation_count=len(graph_context.relations),
            likely_graph_lift=bool(
                graph_context.entities and graph_context.relations and graph_context.max_score >= 1.75
            ),
            graph_max_score=graph_context.max_score,
            expected_presence=expected,
        )
        evaluations.append(
            GraphQualityEvaluation(
                id=question.get("id"),
                query=query,
                text_results=text_results,
                curated_graph=graph_context,
                assessment=assessment,
            )
        )
    return evaluations


def cmd_graph_quality(args: argparse.Namespace) -> int:
    conn = connect(init=False)
    overview = quality_overview(conn)
    questions = [{"query": query} for query in args.query or []]
    if not questions:
        questions = _load_eval_questions(args.eval_file)
    evaluations = evaluate_queries(conn, questions[: max(1, args.query_limit)], limit=max(1, args.limit))
    result = {"overview": overview.to_dict(), "evaluations": [item.to_dict() for item in evaluations]}
    if args.json:
        print(json_dumps(result))
        return 0
    print("Graph quality overview")
    print(f"  entities={overview.entity_total} relations={overview.relation_total} evidence={overview.evidence_total}")
    print(
        f"  entity_evidence_ratio={overview.entity_evidence_ratio} "
        f"relation_evidence_ratio={overview.relation_evidence_ratio} "
        f"orphan_entity_ratio={overview.orphan_entity_ratio}"
    )
    print(f"  source_anchored_entity_ratio={overview.source_anchored_entity_ratio}")
    print(f"  high_value_entities={overview.high_value_entity_total} ratio={overview.high_value_entity_ratio}")
    print(f"  operational_entities={overview.operational_entity_total} ratio={overview.operational_entity_ratio}")
    print(f"  generic_decision_task_names={overview.generic_semantic_entity_total}")
    print("  top entity types:")
    for row in overview.top_entity_types[:10]:
        print(f"    {row.name}: {row.count}")
    print("  top duplicate name groups:")
    for row in overview.duplicate_name_groups[:8]:
        print(f"    {row.name}: {row.count}")
    print("  entity resolution candidates:")
    for row in overview.entity_resolution_candidates[:8]:
        print(f"    {row.surface}: {row.count} across {', '.join(row.types)}")
    print("")
    print("Query evaluation")
    for item in evaluations:
        print(f"- {item.query}")
        print(
            f"  text={item.assessment.text_result_count} "
            f"graph_entities={item.assessment.graph_entity_count} "
            f"graph_relations={item.assessment.graph_relation_count} "
            f"lift={'yes' if item.assessment.likely_graph_lift else 'no'}"
        )
        intent_profile = item.curated_graph.intent_profile
        if intent_profile:
            print(
                f"  intent={intent_profile.get('intent')} "
                f"operational_budget={intent_profile.get('operational_context_budget')}"
            )
        for entity in item.curated_graph.entities[:5]:
            print(f"    entity {entity.type} {entity.name} score={entity.score} rels={entity.relation_count}")
        for note in item.curated_graph.quality_notes:
            print(f"    note {note}")
        expected = item.assessment.expected_presence
        if expected and (expected.expected_entity_types or expected.expected_relation_types):
            status = "pass" if expected.passed else "fail"
            print(f"    expected {status}")
            if expected.missing_entity_types:
                print(f"    missing entity types: {', '.join(expected.missing_entity_types)}")
            if expected.missing_relation_types:
                print(f"    missing relation types: {', '.join(expected.missing_relation_types)}")
    return 0
