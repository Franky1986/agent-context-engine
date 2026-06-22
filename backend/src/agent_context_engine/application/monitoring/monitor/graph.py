from __future__ import annotations

import json
from typing import Any

from ....infrastructure.db import connect


def _graph_limit(value: int) -> int:
    return max(1, min(int(value or 50), 200))


def _graph_offset(value: int) -> int:
    return max(0, int(value or 0))


def _row_as_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return dict(row)


def _json_property(row: dict[str, Any], key: str) -> str:
    try:
        props = json.loads(row.get("properties_json") or "{}")
    except json.JSONDecodeError:
        return ""
    value = props.get(key)
    return str(value) if value is not None else ""


def _memory_view(value: str | None) -> str:
    view = str(value or "both").strip().lower()
    if view in {"deterministic", "semantic", "both"}:
        return view
    return "both"


def _annotate_origin(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("origin_kind"):
        return row
    row["origin_kind"] = "semantic_projection" if str(row.get("memory_kind") or "") == "semantic" else "graph_fact"
    return row


def _entity_union_sql(memory_view: str) -> str:
    parts: list[str] = []
    if memory_view in {"both", "deterministic"}:
        parts.append(
            """
            select ge.entity_id,
                   ge.entity_id as id,
                   ge.type,
                   ge.key,
                   ge.name,
                   ge.confidence,
                   ge.session_id,
                   ge.dream_run_id,
                   ge.artifact_id,
                   ge.first_seen_at,
                   ge.last_seen_at,
                   ge.memory_kind,
                   ge.source_kind,
                   'graph_fact' as origin_kind,
                   ge.properties_json,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id) as evidence_count,
                   (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id) as out_relation_count,
                   (select count(*) from graph_relations gr where gr.to_entity_id = ge.entity_id) as in_relation_count,
                   (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id or gr.to_entity_id = ge.entity_id) as relation_count
            from graph_entities ge
            where coalesce(ge.memory_kind, 'graph_fact') != 'semantic'
            """
        )
    if memory_view in {"both", "semantic"}:
        parts.append(
            """
            select se.semantic_entity_id as entity_id,
                   se.semantic_entity_id as id,
                   se.entity_type as type,
                   se.entity_key as key,
                   se.name,
                   se.confidence,
                   se.source_session_id as session_id,
                   se.source_dream_run_id as dream_run_id,
                   null as artifact_id,
                   se.created_at as first_seen_at,
                   se.updated_at as last_seen_at,
                   'semantic' as memory_kind,
                   'dream_run' as source_kind,
                   'semantic_projection' as origin_kind,
                   se.properties_json,
                   0 as evidence_count,
                   (select count(*) from semantic_relations sr where sr.source_entity_key = se.entity_key) as out_relation_count,
                   (select count(*) from semantic_relations sr where sr.target_entity_key = se.entity_key) as in_relation_count,
                   (select count(*) from semantic_relations sr where sr.source_entity_key = se.entity_key or sr.target_entity_key = se.entity_key) as relation_count
            from semantic_entities se
            where se.status = 'active'
            """
        )
    return " union all ".join(parts) or "select '' as entity_id, '' as id, '' as type, '' as key, '' as name, 0 as confidence, null as session_id, null as dream_run_id, null as artifact_id, null as first_seen_at, null as last_seen_at, '' as memory_kind, '' as source_kind, '' as origin_kind, '{}' as properties_json, 0 as evidence_count, 0 as out_relation_count, 0 as in_relation_count, 0 as relation_count where 0"


def _relation_union_sql(memory_view: str) -> str:
    parts: list[str] = []
    if memory_view in {"both", "deterministic"}:
        parts.append(
            """
            select gr.relation_id,
                   gr.relation_id as id,
                   gr.relation_type,
                   gr.relation_type as type,
                   gr.from_entity_id as source,
                   gr.to_entity_id as target,
                   f.name as source_name,
                   t.name as target_name,
                   f.type as source_type,
                   t.type as target_type,
                   f.key as source_key,
                   t.key as target_key,
                   gr.confidence,
                   gr.session_id,
                   gr.dream_run_id,
                   gr.artifact_id,
                   gr.first_seen_at,
                   gr.last_seen_at,
                   gr.memory_kind,
                   gr.source_kind,
                   'graph_fact' as origin_kind,
                   gr.properties_json,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
            from graph_relations gr
            left join graph_entities f on f.entity_id = gr.from_entity_id
            left join graph_entities t on t.entity_id = gr.to_entity_id
            where coalesce(gr.memory_kind, 'graph_fact') != 'semantic'
            """
        )
    if memory_view in {"both", "semantic"}:
        parts.append(
            """
            select sr.semantic_relation_id as relation_id,
                   sr.semantic_relation_id as id,
                   sr.relation_type,
                   sr.relation_type as type,
                   coalesce(sf.semantic_entity_id, sr.source_entity_key) as source,
                   coalesce(st.semantic_entity_id, sr.target_entity_key) as target,
                   sf.name as source_name,
                   st.name as target_name,
                   sf.entity_type as source_type,
                   st.entity_type as target_type,
                   sr.source_entity_key as source_key,
                   sr.target_entity_key as target_key,
                   sr.confidence,
                   sr.source_session_id as session_id,
                   sr.source_dream_run_id as dream_run_id,
                   null as artifact_id,
                   sr.created_at as first_seen_at,
                   sr.updated_at as last_seen_at,
                   'semantic' as memory_kind,
                   'dream_run' as source_kind,
                   'semantic_projection' as origin_kind,
                   sr.properties_json,
                   0 as evidence_count
            from semantic_relations sr
            left join semantic_entities sf on sf.entity_key = sr.source_entity_key and sf.status = 'active'
            left join semantic_entities st on st.entity_key = sr.target_entity_key and st.status = 'active'
            where sr.status = 'active'
            """
        )
    return " union all ".join(parts) or "select '' as relation_id, '' as id, '' as relation_type, '' as type, '' as source, '' as target, '' as source_name, '' as target_name, '' as source_type, '' as target_type, '' as source_key, '' as target_key, 0 as confidence, null as session_id, null as dream_run_id, null as artifact_id, null as first_seen_at, null as last_seen_at, '' as memory_kind, '' as source_kind, '' as origin_kind, '{}' as properties_json, 0 as evidence_count where 0"


def graph_table_overview(conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        entity_count = conn.execute("select count(*) as c from graph_entities").fetchone()["c"]
        relation_count = conn.execute("select count(*) as c from graph_relations").fetchone()["c"]
        evidence_count = conn.execute("select count(*) as c from graph_evidence").fetchone()["c"]
        latest = conn.execute(
            """
            select max(last_seen_at) as last_seen_at, max(first_seen_at) as first_seen_at
            from (
              select first_seen_at, last_seen_at from graph_entities
              union all
              select first_seen_at, last_seen_at from graph_relations
            )
            """
        ).fetchone()
        return {
            "entity_count": int(entity_count or 0),
            "relation_count": int(relation_count or 0),
            "evidence_count": int(evidence_count or 0),
            "first_seen_at": latest["first_seen_at"] if latest else None,
            "last_seen_at": latest["last_seen_at"] if latest else None,
        }
    finally:
        if own_conn:
            conn.close()


def graph_table_options(conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        entity_types = [row["type"] for row in conn.execute("select distinct type from graph_entities order by type")]
        relation_types = [row["relation_type"] for row in conn.execute("select distinct relation_type from graph_relations order by relation_type")]
        return {"entity_types": entity_types, "relation_types": relation_types, "overview": graph_table_overview(conn)}
    finally:
        if own_conn:
            conn.close()


def graph_type_rows(*, limit: int = 200, offset: int = 0, query: str | None = None, kind: str | None = None, conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        limit = _graph_limit(limit)
        offset = _graph_offset(offset)
        query_sql = "where name like ?" if query else ""
        query_params: list[Any] = [f"%{query}%"] if query else []
        parts: list[str] = []
        params: list[Any] = []
        if kind in (None, "", "entity"):
            parts.append(
                """
                select 'entity' as kind, type as name, count(*) as item_count,
                       min(first_seen_at) as first_seen_at, max(last_seen_at) as last_seen_at,
                       sum((select count(*) from graph_evidence ev where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id)) as evidence_count,
                       sum((select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id or gr.to_entity_id = ge.entity_id)) as relation_count
                from graph_entities ge
                group by type
                """
            )
        if kind in (None, "", "relation"):
            parts.append(
                """
                select 'relation' as kind, relation_type as name, count(*) as item_count,
                       min(first_seen_at) as first_seen_at, max(last_seen_at) as last_seen_at,
                       sum((select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id)) as evidence_count,
                       count(*) as relation_count
                from graph_relations gr
                group by relation_type
                """
            )
        union_sql = " union all ".join(parts) or "select 'entity' as kind, '' as name, 0 as item_count, null as first_seen_at, null as last_seen_at, 0 as evidence_count, 0 as relation_count where 0"
        total = conn.execute(f"select count(*) as c from ({union_sql}) types {query_sql}", query_params).fetchone()["c"]
        rows = [
            _row_as_dict(row)
            for row in conn.execute(
                f"""
                select *
                from ({union_sql}) types
                {query_sql}
                order by item_count desc, kind, name
                limit ? offset ?
                """,
                (*params, *query_params, limit, offset),
            )
        ]
        return {"types": rows, "total": int(total or 0), "limit": limit, "offset": offset, "overview": graph_table_overview(conn)}
    finally:
        if own_conn:
            conn.close()


def graph_type_detail(kind: str, name: str, *, limit: int = 100, conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        limit = _graph_limit(limit)
        if kind == "relation":
            stats = conn.execute(
                """
                select 'relation' as kind, relation_type as name, count(*) as item_count,
                       min(first_seen_at) as first_seen_at, max(last_seen_at) as last_seen_at,
                       avg(confidence) as avg_confidence
                from graph_relations
                where relation_type = ?
                group by relation_type
                """,
                (name,),
            ).fetchone()
            rows = [
                _row_as_dict(row)
                for row in conn.execute(
                    """
                    select gr.*, f.name as from_name, f.type as from_type, f.key as from_key,
                           t.name as to_name, t.type as to_type, t.key as to_key,
                           (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
                    from graph_relations gr
                    left join graph_entities f on f.entity_id = gr.from_entity_id
                    left join graph_entities t on t.entity_id = gr.to_entity_id
                    where gr.relation_type = ?
                    order by gr.last_seen_at desc, gr.first_seen_at desc
                    limit ?
                    """,
                    (name, limit),
                )
            ]
            return {"type": _row_as_dict(stats) if stats else {"kind": kind, "name": name}, "relations": rows, "entities": []}
        stats = conn.execute(
            """
            select 'entity' as kind, type as name, count(*) as item_count,
                   min(first_seen_at) as first_seen_at, max(last_seen_at) as last_seen_at,
                   avg(confidence) as avg_confidence
            from graph_entities
            where type = ?
            group by type
            """,
            (name,),
        ).fetchone()
        rows = [
            _row_as_dict(row)
            for row in conn.execute(
                """
                select ge.*,
                       (select count(*) from graph_evidence ev where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id) as evidence_count,
                       (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id) as out_relation_count,
                       (select count(*) from graph_relations gr where gr.to_entity_id = ge.entity_id) as in_relation_count,
                       (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id or gr.to_entity_id = ge.entity_id) as relation_count
                from graph_entities ge
                where ge.type = ?
                order by ge.last_seen_at desc, ge.first_seen_at desc
                limit ?
                """,
                (name, limit),
            )
        ]
        return {"type": _row_as_dict(stats) if stats else {"kind": kind, "name": name}, "entities": rows, "relations": []}
    finally:
        if own_conn:
            conn.close()


def graph_entities(
    *,
    limit: int = 50,
    offset: int = 0,
    query: str | None = None,
    entity_type: str | None = None,
    memory_view: str = "both",
    sort: str = "last_seen_at",
    direction: str = "desc",
    conn: Any | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        memory_view = _memory_view(memory_view)
        limit = _graph_limit(limit)
        offset = _graph_offset(offset)
        sort_sql = {
            "first_seen_at": "first_seen_at",
            "last_seen_at": "last_seen_at",
            "type": "type",
            "name": "name",
            "confidence": "coalesce(confidence, 0)",
            "evidence_count": "evidence_count",
            "relation_count": "relation_count",
        }.get(sort, "last_seen_at")
        dir_sql = "asc" if str(direction).lower() == "asc" else "desc"
        where: list[str] = []
        params: list[Any] = []
        if query:
            like = f"%{query}%"
            where.append(
                """
                (ge.entity_id like ? or ge.name like ? or ge.key like ? or coalesce(ge.properties_json, '') like ?
                 or coalesce(ge.session_id, '') like ? or coalesce(ge.dream_run_id, '') like ? or coalesce(ge.artifact_id, '') like ?)
                """
            )
            params.extend([like, like, like, like, like, like, like])
        if entity_type:
            where.append("ge.type = ?")
            params.append(entity_type)
        where_sql = "where " + " and ".join(where) if where else ""
        base_sql = _entity_union_sql(memory_view)
        total = conn.execute(f"select count(*) as c from ({base_sql}) ge {where_sql}", params).fetchone()["c"]
        rows = [
            _annotate_origin(_row_as_dict(row))
            for row in conn.execute(
                f"""
                select ge.*
                from ({base_sql}) ge
                {where_sql}
                order by {sort_sql} {dir_sql}, ge.type asc, ge.name asc
                limit ? offset ?
                """,
                (*params, limit, offset),
            )
        ]
        for row in rows:
            row["path"] = _json_property(row, "path")
            row["url"] = _json_property(row, "url")
            row["command"] = _json_property(row, "command")
            row["family"] = _json_property(row, "family")
            row["executable"] = _json_property(row, "executable")
            row["variant_count"] = _json_property(row, "variant_count")
        return {
            "entities": rows,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "memory_view": memory_view,
            "sort": sort,
            "dir": dir_sql,
            "overview": graph_table_overview(conn),
        }
    finally:
        if own_conn:
            conn.close()


def graph_relations(
    *,
    limit: int = 50,
    offset: int = 0,
    query: str | None = None,
    relation_type: str | None = None,
    memory_view: str = "both",
    sort: str = "last_seen_at",
    direction: str = "desc",
    conn: Any | None = None,
) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        memory_view = _memory_view(memory_view)
        limit = _graph_limit(limit)
        offset = _graph_offset(offset)
        sort_sql = {
            "first_seen_at": "gr.first_seen_at",
            "last_seen_at": "gr.last_seen_at",
            "relation_type": "gr.relation_type",
            "confidence": "coalesce(gr.confidence, 0)",
            "evidence_count": "evidence_count",
        }.get(sort, "gr.last_seen_at")
        dir_sql = "asc" if str(direction).lower() == "asc" else "desc"
        where: list[str] = []
        params: list[Any] = []
        if query:
            like = f"%{query}%"
            where.append(
                """
                (gr.relation_id like ? or gr.relation_type like ? or coalesce(gr.properties_json, '') like ?
                 or coalesce(gr.session_id, '') like ? or coalesce(gr.dream_run_id, '') like ? or coalesce(gr.artifact_id, '') like ?
                 or coalesce(gr.source_name, '') like ? or coalesce(gr.source_key, '') like ? or coalesce(gr.target_name, '') like ? or coalesce(gr.target_key, '') like ?)
                """
            )
            params.extend([like, like, like, like, like, like, like, like, like, like])
        if relation_type:
            where.append("gr.relation_type = ?")
            params.append(relation_type)
        where_sql = "where " + " and ".join(where) if where else ""
        from_join = f"from ({_relation_union_sql(memory_view)}) gr"
        total = conn.execute(f"select count(*) as c {from_join} {where_sql}", params).fetchone()["c"]
        rows = [
            _annotate_origin(_row_as_dict(row))
            for row in conn.execute(
                f"""
                select gr.*
                {from_join}
                {where_sql}
                order by {sort_sql} {dir_sql}, gr.relation_type asc
                limit ? offset ?
                """,
                (*params, limit, offset),
            )
        ]
        return {
            "relations": rows,
            "total": int(total or 0),
            "limit": limit,
            "offset": offset,
            "memory_view": memory_view,
            "sort": sort,
            "dir": dir_sql,
            "overview": graph_table_overview(conn),
        }
    finally:
        if own_conn:
            conn.close()


def graph_entity_detail(entity_id: str, *, memory_view: str = "both", conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        memory_view = _memory_view(memory_view)
        if entity_id.startswith("sem_ent_") or memory_view == "semantic":
            entity = conn.execute(
                """
                select se.semantic_entity_id as entity_id,
                       se.semantic_entity_id as id,
                       se.entity_type as type,
                       se.entity_key as key,
                       se.name,
                       se.confidence,
                       se.source_session_id as session_id,
                       se.source_dream_run_id as dream_run_id,
                       null as artifact_id,
                       se.created_at as first_seen_at,
                       se.updated_at as last_seen_at,
                       'semantic' as memory_kind,
                       'dream_run' as source_kind,
                       'semantic_projection' as origin_kind,
                       se.properties_json,
                       se.summary,
                       0 as evidence_count,
                       (select count(*) from semantic_relations sr where sr.source_entity_key = se.entity_key) as out_relation_count,
                       (select count(*) from semantic_relations sr where sr.target_entity_key = se.entity_key) as in_relation_count,
                       (select count(*) from semantic_relations sr where sr.source_entity_key = se.entity_key or sr.target_entity_key = se.entity_key) as relation_count,
                       se.evidence_json
                from semantic_entities se
                where se.semantic_entity_id = ? and se.status = 'active'
                """,
                (entity_id,),
            ).fetchone()
            if entity is None:
                raise ValueError(f"graph entity not found: {entity_id}")
            entity_row = _annotate_origin(_row_as_dict(entity))
            relations = [
                _annotate_origin(_row_as_dict(row))
                for row in conn.execute(
                    """
                    select sr.semantic_relation_id as relation_id,
                           sr.semantic_relation_id as id,
                           sr.relation_type,
                           sr.relation_type as type,
                           coalesce(sf.semantic_entity_id, sr.source_entity_key) as source,
                           coalesce(st.semantic_entity_id, sr.target_entity_key) as target,
                           sf.name as from_name,
                           st.name as to_name,
                           sf.entity_type as from_type,
                           st.entity_type as to_type,
                           sr.source_entity_key as from_key,
                           sr.target_entity_key as to_key,
                           sr.confidence,
                           sr.source_session_id as session_id,
                           sr.source_dream_run_id as dream_run_id,
                           null as artifact_id,
                           sr.created_at as first_seen_at,
                           sr.updated_at as last_seen_at,
                           'semantic' as memory_kind,
                           'dream_run' as source_kind,
                           'semantic_projection' as origin_kind,
                           sr.properties_json,
                           0 as evidence_count
                    from semantic_relations sr
                    left join semantic_entities sf on sf.entity_key = sr.source_entity_key and sf.status = 'active'
                    left join semantic_entities st on st.entity_key = sr.target_entity_key and st.status = 'active'
                    where sr.status = 'active' and (sr.source_entity_key = ? or sr.target_entity_key = ?)
                    order by sr.updated_at desc, sr.relation_type
                    limit 160
                    """,
                    (entity_row["key"], entity_row["key"]),
                )
            ]
            evidence = []
            try:
                raw_evidence = json.loads(entity_row.get("evidence_json") or "[]")
            except json.JSONDecodeError:
                raw_evidence = []
            for index, item in enumerate(raw_evidence if isinstance(raw_evidence, list) else []):
                if isinstance(item, dict):
                    evidence.append({"evidence_id": f"{entity_id}:{index}", "owner_type": "entity", "owner_id": entity_id, **item})
            return {"entity": entity_row, "relations": relations, "evidence": evidence}
        entity = conn.execute(
            """
            select ge.*,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'entity' and ev.owner_id = ge.entity_id) as evidence_count,
                   (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id) as out_relation_count,
                   (select count(*) from graph_relations gr where gr.to_entity_id = ge.entity_id) as in_relation_count,
                   (select count(*) from graph_relations gr where gr.from_entity_id = ge.entity_id or gr.to_entity_id = ge.entity_id) as relation_count
            from graph_entities ge
            where ge.entity_id = ?
            """,
            (entity_id,),
        ).fetchone()
        if entity is None:
            raise ValueError(f"graph entity not found: {entity_id}")
        relations = [
            _annotate_origin(_row_as_dict(row))
            for row in conn.execute(
                """
                select gr.*, f.name as from_name, f.type as from_type, f.key as from_key,
                       t.name as to_name, t.type as to_type, t.key as to_key,
                       (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
                from graph_relations gr
                left join graph_entities f on f.entity_id = gr.from_entity_id
                left join graph_entities t on t.entity_id = gr.to_entity_id
                where gr.from_entity_id = ? or gr.to_entity_id = ?
                order by gr.last_seen_at desc, gr.relation_type
                limit 160
                """,
                (entity_id, entity_id),
            )
        ]
        evidence = [
            _row_as_dict(row)
            for row in conn.execute(
                """
                select * from graph_evidence
                where owner_type = 'entity' and owner_id = ?
                order by event_seq, evidence_id
                limit 80
                """,
                (entity_id,),
            )
        ]
        return {"entity": _annotate_origin(_row_as_dict(entity)), "relations": relations, "evidence": evidence}
    finally:
        if own_conn:
            conn.close()


def graph_relation_detail(relation_id: str, *, memory_view: str = "both", conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        memory_view = _memory_view(memory_view)
        if relation_id.startswith("sem_rel_") or memory_view == "semantic":
            relation = conn.execute(
                """
                select sr.semantic_relation_id as relation_id,
                       sr.semantic_relation_id as id,
                       sr.relation_type,
                       sr.relation_type as type,
                       coalesce(sf.semantic_entity_id, sr.source_entity_key) as source,
                       coalesce(st.semantic_entity_id, sr.target_entity_key) as target,
                       sf.name as from_name,
                       st.name as to_name,
                       sf.entity_type as from_type,
                       st.entity_type as to_type,
                       sr.source_entity_key as from_key,
                       sr.target_entity_key as to_key,
                       sr.confidence,
                       sr.source_session_id as session_id,
                       sr.source_dream_run_id as dream_run_id,
                       null as artifact_id,
                       sr.created_at as first_seen_at,
                       sr.updated_at as last_seen_at,
                       'semantic' as memory_kind,
                       'dream_run' as source_kind,
                       'semantic_projection' as origin_kind,
                       sr.properties_json,
                       sr.evidence_json,
                       0 as evidence_count
                from semantic_relations sr
                left join semantic_entities sf on sf.entity_key = sr.source_entity_key and sf.status = 'active'
                left join semantic_entities st on st.entity_key = sr.target_entity_key and st.status = 'active'
                where sr.semantic_relation_id = ? and sr.status = 'active'
                """,
                (relation_id,),
            ).fetchone()
            if relation is None:
                raise ValueError(f"graph relation not found: {relation_id}")
            relation_row = _annotate_origin(_row_as_dict(relation))
            try:
                raw_evidence = json.loads(relation_row.get("evidence_json") or "[]")
            except json.JSONDecodeError:
                raw_evidence = []
            evidence = []
            for index, item in enumerate(raw_evidence if isinstance(raw_evidence, list) else []):
                if isinstance(item, dict):
                    evidence.append({"evidence_id": f"{relation_id}:{index}", "owner_type": "relation", "owner_id": relation_id, **item})
            endpoint_relations = [
                _annotate_origin(_row_as_dict(row))
                for row in conn.execute(
                    """
                    select sr.semantic_relation_id as relation_id,
                           sr.semantic_relation_id as id,
                           sr.relation_type,
                           sr.relation_type as type,
                           coalesce(sf.semantic_entity_id, sr.source_entity_key) as source,
                           coalesce(st.semantic_entity_id, sr.target_entity_key) as target,
                           sf.name as from_name,
                           st.name as to_name,
                           sf.entity_type as from_type,
                           st.entity_type as to_type,
                           sr.source_entity_key as from_key,
                           sr.target_entity_key as to_key,
                           sr.confidence,
                           sr.source_session_id as session_id,
                           sr.source_dream_run_id as dream_run_id,
                           null as artifact_id,
                           sr.created_at as first_seen_at,
                           sr.updated_at as last_seen_at,
                           'semantic' as memory_kind,
                           'dream_run' as source_kind,
                           'semantic_projection' as origin_kind,
                           sr.properties_json,
                           0 as evidence_count
                    from semantic_relations sr
                    left join semantic_entities sf on sf.entity_key = sr.source_entity_key and sf.status = 'active'
                    left join semantic_entities st on st.entity_key = sr.target_entity_key and st.status = 'active'
                    where sr.status = 'active'
                      and (sr.source_entity_key in (?, ?) or sr.target_entity_key in (?, ?))
                      and sr.semantic_relation_id != ?
                    order by sr.updated_at desc
                    limit 120
                    """,
                    (
                        relation_row["source"],
                        relation_row["target"],
                        relation_row["source"],
                        relation_row["target"],
                        relation_id,
                    ),
                )
            ]
            return {"relation": relation_row, "evidence": evidence, "endpoint_relations": endpoint_relations}
        relation = conn.execute(
            """
            select gr.*, f.name as from_name, f.type as from_type, f.key as from_key,
                   f.first_seen_at as from_first_seen_at, f.last_seen_at as from_last_seen_at,
                   t.name as to_name, t.type as to_type, t.key as to_key,
                   t.first_seen_at as to_first_seen_at, t.last_seen_at as to_last_seen_at,
                   (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
            from graph_relations gr
            left join graph_entities f on f.entity_id = gr.from_entity_id
            left join graph_entities t on t.entity_id = gr.to_entity_id
            where gr.relation_id = ?
            """,
            (relation_id,),
        ).fetchone()
        if relation is None:
            raise ValueError(f"graph relation not found: {relation_id}")
        evidence = [
            _row_as_dict(row)
            for row in conn.execute(
                """
                select * from graph_evidence
                where owner_type = 'relation' and owner_id = ?
                order by event_seq, evidence_id
                limit 80
                """,
                (relation_id,),
            )
        ]
        endpoint_ids = [relation["from_entity_id"], relation["to_entity_id"]]
        endpoint_relations = [
            _annotate_origin(_row_as_dict(row))
            for row in conn.execute(
                """
                select gr.*, f.name as from_name, f.type as from_type, f.key as from_key,
                       t.name as to_name, t.type as to_type, t.key as to_key,
                       (select count(*) from graph_evidence ev where ev.owner_type = 'relation' and ev.owner_id = gr.relation_id) as evidence_count
                from graph_relations gr
                left join graph_entities f on f.entity_id = gr.from_entity_id
                left join graph_entities t on t.entity_id = gr.to_entity_id
                where (gr.from_entity_id in (?, ?) or gr.to_entity_id in (?, ?))
                  and gr.relation_id != ?
                order by gr.last_seen_at desc
                limit 120
                """,
                (*endpoint_ids, *endpoint_ids, relation_id),
            )
        ]
        return {"relation": _annotate_origin(_row_as_dict(relation)), "evidence": evidence, "endpoint_relations": endpoint_relations}
    finally:
        if own_conn:
            conn.close()


def sqlite_graph(query: str, view: str, limit: int, memory_view: str = "both", conn: Any | None = None) -> dict[str, Any]:
    own_conn = conn is None
    conn = conn or connect()
    try:
        memory_view = _memory_view(memory_view)
        like = f"%{query}%"
        type_filter = {
            "project": "Project",
            "session": "Session",
            "concept": "Concept",
        }.get(view)
        params: list[Any] = []
        where = """
        (
          name like ?
          or key like ?
          or coalesce(properties_json, '') like ?
          or coalesce(session_id, '') like ?
          or coalesce(dream_run_id, '') like ?
          or coalesce(artifact_id, '') like ?
        )
        """
        params.extend([like, like, like, like, like, like])
        if type_filter:
            where += " and type = ?"
            params.append(type_filter)
        entity_sql = _entity_union_sql(memory_view)
        entities = list(
            conn.execute(
                f"""
                select * from ({entity_sql}) entities
                where {where}
                order by last_seen_at desc
                limit ?
                """,
                (*params, _graph_limit(limit)),
            )
        )
        ids = [row["entity_id"] for row in entities]
        if not ids:
            return {"nodes": [], "links": [], "source": "sqlite", "memory_view": memory_view}
        placeholders = ",".join("?" for _ in ids)
        relation_sql = _relation_union_sql(memory_view)
        relations = list(
            conn.execute(
                f"""
                select *
                from ({relation_sql}) r
                where r.source in ({placeholders}) or r.target in ({placeholders})
                order by r.last_seen_at desc
                limit ?
                """,
                (*ids, *ids, _graph_limit(limit) * 2),
            )
        )
        node_map: dict[str, dict[str, Any]] = {}
        for row in entities:
            node_map[row["entity_id"]] = {
                "id": row["entity_id"],
                "name": row["name"],
                "label": row["name"],
                "type": row["type"],
                "key": row["key"],
                "size": 11,
                "properties": row["properties_json"],
                "memory_kind": row["memory_kind"],
                "source_kind": row["source_kind"],
                "origin_kind": row["origin_kind"],
            }
        for row in relations:
            node_map.setdefault(row["source"], {"id": row["source"], "name": row["source_name"], "label": row["source_name"], "type": row["source_type"], "size": 8, "origin_kind": row["origin_kind"]})
            node_map.setdefault(row["target"], {"id": row["target"], "name": row["target_name"], "label": row["target_name"], "type": row["target_type"], "size": 8, "origin_kind": row["origin_kind"]})
        links = [
            {"id": row["relation_id"], "source": row["source"], "target": row["target"], "type": row["relation_type"], "weight": max(1, float(row["confidence"] or 1)), "origin_kind": row["origin_kind"], "memory_kind": row["memory_kind"], "source_kind": row["source_kind"]}
            for row in relations
        ]
        return {"nodes": list(node_map.values()), "links": links, "source": "sqlite", "memory_view": memory_view}
    finally:
        if own_conn:
            conn.close()
