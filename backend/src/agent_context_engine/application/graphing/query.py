from __future__ import annotations

import argparse
import json
from typing import Any

from ...infrastructure.config import json_dumps
from ...infrastructure.db import connect


def entity_matches(entity: dict[str, Any], query: str | None, entity_type: str | None) -> bool:
    if entity_type and entity.get("type") != entity_type:
        return False
    if not query:
        return True
    haystack = " ".join(
        [
            str(entity.get("type") or ""),
            str(entity.get("key") or ""),
            str(entity.get("name") or ""),
            " ".join(str(alias) for alias in entity.get("aliases") or []),
            json_dumps(entity.get("properties") or {}),
        ]
    ).lower()
    return query.lower() in haystack


def entity_ref_id(ref: dict[str, Any]) -> str:
    return f"{ref.get('type')}:{ref.get('key')}"


def _normalize_query(raw_query: Any) -> str | None:
    if raw_query is None:
        return None
    if isinstance(raw_query, list):
        joined = " ".join(raw_query).strip()
        return joined or None
    query = str(raw_query).strip()
    return query or None


def cmd_graph_query(args: argparse.Namespace) -> int:
    conn = connect()
    query = _normalize_query(args.query)

    if args.query_command == "sessions":
        rows = list(
            conn.execute(
                """
                select session_id, dream_run_id, path, created_at
                from graph_artifacts
                where artifact_type = 'patch' and status = 'valid'
                order by created_at desc
                limit ?
                """,
                (args.limit,),
            )
        )
        if not rows:
            print("No valid graph patches found.")
            return 0
        for row in rows:
            print(f"{row['created_at']} {row['session_id']} source={row['dream_run_id'] or '-'}")
            print(f"  patch={row['path']}")
        return 0

    if args.query_command in {"entities", "recent"}:
        where = []
        params: list[Any] = []
        if args.type:
            where.append("type = ?")
            params.append(args.type)
        if query:
            where.append("(name like ? or key like ? or aliases_json like ? or properties_json like ?)")
            like = f"%{query}%"
            params.extend([like, like, like, like])
        where_sql = "where " + " and ".join(where) if where else ""
        rows = list(
            conn.execute(
                f"""
                select *
                from graph_entities
                {where_sql}
                order by last_seen_at desc, type, name
                limit ?
                """,
                (*params, args.limit),
            )
        )
        if not rows:
            print("No entities found.")
            return 0
        for entity in rows:
            print(f"{entity['type']} {entity['name']} key={entity['key']}")
            try:
                props = json.loads(entity["properties_json"] or "{}")
            except json.JSONDecodeError:
                props = {}
            if props.get("path"):
                print(f"  path={props['path']}")
            if props.get("command"):
                print(f"  command={props['command']}")
            ev = conn.execute("select * from graph_evidence where owner_type = 'entity' and owner_id = ? limit 1", (entity["entity_id"],)).fetchone()
            if ev:
                print(f"  evidence=session:{ev['session_id'] or '-'} seq:{ev['event_seq'] or '-'} field:{ev['field'] or '-'}")
        return 0

    if args.query_command in {"entity", "related"}:
        where = []
        params = []
        if args.type:
            where.append("type = ?")
            params.append(args.type)
        if query:
            where.append("(name like ? or key like ? or aliases_json like ? or properties_json like ?)")
            like = f"%{query}%"
            params.extend([like, like, like, like])
        where_sql = "where " + " and ".join(where) if where else ""
        focus = conn.execute(
            f"""
            select *
            from graph_entities
            {where_sql}
            order by last_seen_at desc, type, name
            limit 1
            """,
            tuple(params),
        ).fetchone()
        if focus is None:
            if query is None:
                if args.type:
                    print(f"No entity found for type: {args.type}")
                else:
                    print("No entity found")
            else:
                print(f"No entity found for query: {query}")
            return 1
        print(f"{focus['type']} {focus['name']} key={focus['key']}")
        try:
            props = json.loads(focus["properties_json"] or "{}")
        except json.JSONDecodeError:
            props = {}
        if props:
            print(f"  properties={json_dumps(props)}")
        evidence_rows = list(conn.execute("select * from graph_evidence where owner_type = 'entity' and owner_id = ? limit ?", (focus["entity_id"], args.evidence_limit)))
        for ev in evidence_rows:
            print(f"  evidence session={ev['session_id'] or '-'} seq={ev['event_seq'] or '-'} field={ev['field'] or '-'}: {(ev['quote'] or '')[:180]}")
        if args.query_command == "related":
            related_rows = list(
                conn.execute(
                    """
                    select 'out' as direction, r.relation_type, e.*
                    from graph_relations r
                    join graph_entities e on e.entity_id = r.to_entity_id
                    where r.from_entity_id = ?
                    union all
                    select 'in' as direction, r.relation_type, e.*
                    from graph_relations r
                    join graph_entities e on e.entity_id = r.from_entity_id
                    where r.to_entity_id = ?
                    limit ?
                    """,
                    (focus["entity_id"], focus["entity_id"], args.limit),
                )
            )
            for row in related_rows:
                arrow = "->" if row["direction"] == "out" else "<-"
                print(f"  {arrow} {row['relation_type']} {row['type']} {row['name']} key={row['key']}")
        return 0

    print(f"Unsupported graph query command: {args.query_command}")
    return 1
