from __future__ import annotations

from typing import Any

from ....adapters.sqlite.request_db import connect
from ....infrastructure.config import ROOT
from ....interfaces.http.version import MONITOR_VERSION
from ...monitor import (
    monitor_integrations as monitor_integrations_case,
    monitor_manage_integration_hooks as monitor_manage_integration_hooks_case,
    monitor_personal_file as monitor_personal_file_case,
    monitor_personal_files as monitor_personal_files_case,
    monitor_reconcile_runtime as monitor_reconcile_runtime_case,
    monitor_repo_index as monitor_repo_index_case,
    monitor_retrieve as monitor_retrieve_case,
    monitor_retrieval_run as monitor_retrieval_run_case,
    monitor_retrieval_runs as monitor_retrieval_runs_case,
    monitor_save_personal_file as monitor_save_personal_file_case,
    monitor_save_repo_index as monitor_save_repo_index_case,
    monitor_search as monitor_search_case,
    monitor_status as monitor_status_case,
)


def _with_connection() -> Any:
    return connect()


def monitor_status(runner: str, monitor_context: dict[str, Any] | None = None) -> dict[str, Any]:
    conn = _with_connection()
    try:
        return monitor_status_case(conn, runner, ROOT, monitor_version=MONITOR_VERSION, monitor_context=monitor_context)
    finally:
        conn.close()


def monitor_integrations() -> dict[str, Any]:
    return monitor_integrations_case(ROOT)


def monitor_reconcile_runtime() -> dict[str, Any]:
    return monitor_reconcile_runtime_case(root=ROOT)


def monitor_manage_integration_hooks(client: str, action: str, project_path: str | None = None) -> dict[str, Any]:
    return monitor_manage_integration_hooks_case(ROOT, client, action, project_path)


def monitor_search(query: str, limit: int) -> dict[str, Any]:
    conn = _with_connection()
    try:
        return monitor_search_case(conn, query, limit=limit)
    finally:
        conn.close()


def monitor_retrieve(
    query: str,
    limit: int,
    kind: str | None = None,
    include_risky: bool = False,
    expansion_mode: str = "auto",
    runner: str | None = None,
    runner_model_value: str | None = None,
    runner_timeout: int = 20,
) -> dict[str, Any]:
    conn = _with_connection()
    try:
        return monitor_retrieve_case(
            conn,
            query,
            limit=limit,
            kind=kind,
            include_risky=include_risky,
            expansion_mode=expansion_mode,
            runner=runner,
            runner_model_value=runner_model_value,
            runner_timeout=runner_timeout,
        )
    finally:
        conn.close()


def monitor_retrieval_runs(limit: int = 30) -> dict[str, Any]:
    conn = _with_connection()
    try:
        return monitor_retrieval_runs_case(conn, limit=limit)
    finally:
        conn.close()


def monitor_retrieval_run(retrieval_run_id: str) -> dict[str, Any]:
    conn = _with_connection()
    try:
        return monitor_retrieval_run_case(conn, retrieval_run_id)
    finally:
        conn.close()


def monitor_personal_files() -> dict[str, Any]:
    return monitor_personal_files_case()


def monitor_personal_file(path_value: str) -> dict[str, Any]:
    return monitor_personal_file_case(path_value)


def monitor_save_personal_file(path_value: str, content: str) -> dict[str, Any]:
    return monitor_save_personal_file_case(path_value, content)


def monitor_repo_index() -> dict[str, Any]:
    return monitor_repo_index_case()


def monitor_save_repo_index(content: str) -> dict[str, Any]:
    return monitor_save_repo_index_case(content)
