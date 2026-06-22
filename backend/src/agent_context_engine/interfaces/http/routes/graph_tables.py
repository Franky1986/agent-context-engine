from __future__ import annotations

from typing import Any

from ....application.monitoring.monitor.graph import (
    graph_table_overview as monitor_graph_table_overview,
    graph_entities as monitor_graph_entities,
    graph_entity_detail as monitor_graph_entity_detail,
    graph_relation_detail as monitor_graph_relation_detail,
    graph_relations as monitor_graph_relations,
    graph_table_options as monitor_graph_table_options,
    graph_type_detail as monitor_graph_type_detail,
    graph_type_rows as monitor_graph_type_rows,
)


# Monitoring graph-tables transport adapter.
# All business logic and DB query composition stays in
# `application.monitoring.monitor.graph`.
def graph_table_overview(conn: Any | None = None) -> dict[str, Any]:
    return monitor_graph_table_overview(conn=conn)


def graph_table_options(conn: Any | None = None) -> dict[str, Any]:
    return monitor_graph_table_options(conn=conn)


def graph_type_rows(
    *,
    limit: int = 200,
    offset: int = 0,
    query: str | None = None,
    kind: str | None = None,
    conn: Any | None = None,
) -> dict[str, Any]:
    return monitor_graph_type_rows(limit=limit, offset=offset, query=query, kind=kind, conn=conn)


def graph_type_detail(kind: str, name: str, *, limit: int = 100, conn: Any | None = None) -> dict[str, Any]:
    return monitor_graph_type_detail(kind=kind, name=name, limit=limit, conn=conn)


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
    return monitor_graph_entities(limit=limit, offset=offset, query=query, entity_type=entity_type, memory_view=memory_view, sort=sort, direction=direction, conn=conn)


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
    return monitor_graph_relations(limit=limit, offset=offset, query=query, relation_type=relation_type, memory_view=memory_view, sort=sort, direction=direction, conn=conn)


def graph_entity_detail(entity_id: str, *, memory_view: str = "both", conn: Any | None = None) -> dict[str, Any]:
    return monitor_graph_entity_detail(entity_id, memory_view=memory_view, conn=conn)


def graph_relation_detail(relation_id: str, *, memory_view: str = "both", conn: Any | None = None) -> dict[str, Any]:
    return monitor_graph_relation_detail(relation_id, memory_view=memory_view, conn=conn)
