from __future__ import annotations

import argparse
from typing import Any

from ....interfaces.cli.commands.installation import _installation_check_payload
from ....infrastructure.config import ROOT
from ....application.monitoring.monitor.memory import (
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


def monitor_status(runner: str, monitor_context: dict[str, Any] | None = None) -> dict[str, Any]:
    return monitor_status_case(runner, monitor_context=monitor_context)


def monitor_reconcile_runtime() -> dict[str, Any]:
    return monitor_reconcile_runtime_case()


def monitor_integrations() -> dict[str, Any]:
    return monitor_integrations_case()


def monitor_installation_check() -> dict[str, Any]:
    return _installation_check_payload(
        root=ROOT,
        args=argparse.Namespace(
            target=None,
            codex_workspace_root=None,
            claude_workspace_root=None,
            cursor_workspace_root=None,
            monitor_runner=None,
            dream_runner=None,
            query_expansion_runner=None,
        ),
    )


def monitor_manage_integration_hooks(client: str, action: str, project_path: str | None = None) -> dict[str, Any]:
    return monitor_manage_integration_hooks_case(client, action, project_path)


def monitor_search(query: str, limit: int) -> dict[str, Any]:
    return monitor_search_case(query, limit=limit)


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
    return monitor_retrieve_case(
        query,
        limit=limit,
        kind=kind,
        include_risky=include_risky,
        expansion_mode=expansion_mode,
        runner=runner,
        runner_model_value=runner_model_value,
        runner_timeout=runner_timeout,
    )


def monitor_retrieval_runs(limit: int = 30) -> dict[str, Any]:
    return monitor_retrieval_runs_case(limit=limit)


def monitor_retrieval_run(retrieval_run_id: str) -> dict[str, Any]:
    return monitor_retrieval_run_case(retrieval_run_id)


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
