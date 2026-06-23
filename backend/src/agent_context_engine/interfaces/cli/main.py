from __future__ import annotations

import argparse
import os
import sys

from .commands.access import cmd_file_accesses, cmd_operational_facts, cmd_rebuild_file_accesses, cmd_tool_calls, cmd_tool_output
from .commands.diagnostics import cmd_doctor
from .commands.analyze import cmd_analyze
from .commands.firewall import cmd_firewall_list, cmd_firewall_show, cmd_firewall_suggest
from .commands.handover import cmd_context, cmd_handover, cmd_resume
from .commands.indexes import cmd_rebuild_indexes, cmd_search
from .commands.installation import (
    cmd_antigravity_enable,
    cmd_attach_memory_root,
    cmd_antigravity_status,
    cmd_check_installation,
    cmd_install_discovery,
    cmd_cursor_disable,
    cmd_cursor_enable,
    cmd_cursor_status,
    cmd_gemini_enable,
    cmd_gemini_status,
    cmd_integration_hooks,
    cmd_global_wrapper_disable,
    cmd_global_wrapper_enable,
    cmd_global_wrapper_status,
    cmd_install,
    cmd_integrations_status,
    cmd_migrate_storage,
    cmd_hooks_disable,
    cmd_hooks_enable,
    cmd_hooks_status,
    cmd_opencode_enable,
    cmd_opencode_status,
    cmd_repair_installation,
)
from .commands.maintenance import GRAPH_PRUNE_KINDS, cmd_graph_prune, cmd_prune_event_logs, cmd_prune_logs, cmd_purge_tool_outputs
from .commands.retrieval import cmd_retrieve, cmd_retrieval_run, cmd_retrieval_runs
from .commands.risk import (
    cmd_quarantine_list,
    cmd_quarantine_show,
    cmd_risk_explain,
    cmd_risk_list,
    cmd_risk_review,
    cmd_risk_scan_command,
    cmd_risk_scan_file,
    cmd_risk_scan_text,
    cmd_risk_show,
)
from .commands.sessions import cmd_folder, cmd_last, cmd_sync_codex_transcript, cmd_sync_transcripts
from .commands.status import cmd_dream_insights, cmd_metrics, cmd_status
from ...application.dream_queue import cmd_dream_queue_status
from ...application.dreaming.v2 import cmd_dream_v2
from ...application.dreaming.v2_cli import (
    cmd_dream_v2_audit,
    cmd_dream_v2_evaluate,
    cmd_dream_v2_apply,
    cmd_dream_v2_fixture,
    cmd_dream_v2_fixture_evaluate,
    cmd_dream_v2_inspect,
    cmd_dream_v2_readiness,
    cmd_dream_v2_rerun,
    cmd_dream_v2_review,
    cmd_neo4j_repair_semantic_projection,
)
from ...application.graph import (
    add_neo4j_args,
    cmd_neo4j_create_database,
    cmd_neo4j_import,
    cmd_neo4j_import_status,
    cmd_neo4j_install_schema,
    cmd_graph_candidates,
    cmd_graph_extract,
    cmd_graph_backfill_command_families,
    cmd_graph_quality,
    cmd_graph_match_candidates,
    cmd_graph_query,
    cmd_graph_reconcile,
    cmd_graph_schema_context,
    cmd_graph_status,
    cmd_graph_structure,
    cmd_graph_validate,
    cmd_neo4j_status,
    cmd_neo4j_sync_pending,
)
from ..hooks.main import cmd_recover_hook_queue_failures, cmd_replay_hook_queue, log_hook
from ...application.personal import cmd_personal_accept, cmd_personal_audit, cmd_personal_init, cmd_personal_list, cmd_personal_proposals, cmd_personal_propose, cmd_personal_show
from ...application.scheduler import (
    DEFAULT_ENV_FILE,
    DEFAULT_LAUNCHD_PATH,
    DEFAULT_LABEL,
    cmd_install_launchagent,
    cmd_launchagent_status,
    cmd_scheduler_run,
    cmd_scheduler_status,
    cmd_uninstall_launchagent,
)
from ...application.schema_proposals import cmd_schema_proposals
from ...application.startup_context import cmd_personal_context, cmd_repo_context, cmd_session_start_context
from ...application.summaries import cmd_summarize, cmd_summarize_windows


def _parse_bool_arg(value: str | None) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on", "enable", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "n", "off", "disable", "disabled"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid bool value: {value!r}")


def _default_query_expansion_mode() -> str:
    mode = (os.environ.get("AGENT_MEMORY_CLI_QUERY_EXPANSION") or "auto").strip().lower()
    if mode in {"auto", "off", "deterministic", "llm"}:
        return mode
    return "auto"


def _cmd_monitor_lazy(args: argparse.Namespace) -> int:
    from ...monitor import cmd_monitor

    return cmd_monitor(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-context-engine")
    sub = parser.add_subparsers(dest="command", required=True)

    log = sub.add_parser("log-hook")
    log.add_argument("--client", required=True)
    log.add_argument("--detect-version", action="store_true")
    log.add_argument("--mode", choices=["auto", "full", "fast", "queue", "context", "sync"], default="auto")
    log.set_defaults(func=log_hook)

    status = sub.add_parser("status")
    status.add_argument("--limit", type=int, default=20)
    status.set_defaults(func=cmd_status)

    last = sub.add_parser("last")
    last.add_argument("--limit", type=int, default=10)
    last.add_argument("--folder", help="Only list sessions whose cwd/last_workdir overlaps this folder")
    last.add_argument("query", nargs="?")
    last.set_defaults(func=cmd_last)

    folder = sub.add_parser("folder")
    folder.add_argument("folder", nargs="?", help="Folder to inspect; defaults to current directory")
    folder.add_argument("--limit", type=int, default=20)
    folder.add_argument("--include-transcripts", action=argparse.BooleanOptionalAction, default=True)
    folder.add_argument("--transcript-limit", type=int, default=10)
    folder.set_defaults(func=cmd_folder)

    resume = sub.add_parser("resume")
    resume.add_argument("selector")
    resume.add_argument("--print", dest="print_only", action="store_true")
    resume.set_defaults(func=cmd_resume)

    context = sub.add_parser("context")
    context.add_argument("selector")
    context.add_argument("--timeline", type=int, default=12)
    context.add_argument("--tools", type=int, default=10)
    context.add_argument("--show-tools", action="store_true")
    context.add_argument("--show-handover", action="store_true")
    context.set_defaults(func=cmd_context)

    tool_calls = sub.add_parser("tool-calls")
    tool_calls.add_argument("--session")
    tool_calls.add_argument("--limit", type=int, default=20)
    tool_calls.set_defaults(func=cmd_tool_calls)

    tool_output = sub.add_parser("tool-output")
    tool_output.add_argument("output_id", nargs="?")
    tool_output.add_argument("--session")
    tool_output.add_argument("--seq", type=int)
    tool_output.add_argument("--chars", type=int, default=0)
    tool_output.add_argument("--metadata", action=argparse.BooleanOptionalAction, default=True)
    tool_output.set_defaults(func=cmd_tool_output)

    file_accesses = sub.add_parser("file-accesses")
    file_accesses.add_argument("path", nargs="?")
    file_accesses.add_argument("--session")
    file_accesses.add_argument("--operation", choices=["read", "list", "create", "modify", "delete", "rename", "write"])
    file_accesses.add_argument("--limit", type=int, default=50)
    file_accesses.add_argument("--evidence", action="store_true")
    file_accesses.add_argument("--chars", type=int, default=800)
    file_accesses.add_argument("--json", action="store_true")
    file_accesses.set_defaults(func=cmd_file_accesses)

    rebuild_file_accesses = sub.add_parser("rebuild-file-accesses")
    rebuild_file_accesses.add_argument("--session")
    rebuild_file_accesses.set_defaults(func=cmd_rebuild_file_accesses)

    operational_facts = sub.add_parser("operational-facts")
    operational_facts.add_argument("--session")
    operational_facts.add_argument("--dream-run-id")
    operational_facts.add_argument("--kind")
    operational_facts.add_argument("--limit", type=int, default=50)
    operational_facts.add_argument("--include-pretool", action=argparse.BooleanOptionalAction, default=True)
    operational_facts.add_argument("--chars", type=int, default=600)
    operational_facts.add_argument("--json", action="store_true")
    operational_facts.set_defaults(func=cmd_operational_facts)

    handover = sub.add_parser("handover")
    handover.add_argument("selector")
    handover.add_argument("--timeline", type=int, default=10)
    handover.add_argument("--tools", type=int, default=10)
    handover.add_argument("--graph-limit", type=int, default=6)
    handover.add_argument("--summary-chars", type=int, default=12000)
    handover.add_argument("--dream-chars", type=int, default=16000)
    handover.add_argument("--project-chars", type=int, default=8000)
    handover.add_argument("--retrieval-limit", type=int, default=6)
    handover.add_argument("--retrieval-chars", type=int, default=900)
    handover.add_argument("--include-project-memory", action=argparse.BooleanOptionalAction, default=True)
    handover.set_defaults(func=cmd_handover)

    use = sub.add_parser("use")
    use.add_argument("selector")
    use.add_argument("--timeline", type=int, default=10)
    use.add_argument("--tools", type=int, default=10)
    use.add_argument("--graph-limit", type=int, default=6)
    use.add_argument("--summary-chars", type=int, default=12000)
    use.add_argument("--dream-chars", type=int, default=16000)
    use.add_argument("--project-chars", type=int, default=8000)
    use.add_argument("--retrieval-limit", type=int, default=6)
    use.add_argument("--retrieval-chars", type=int, default=900)
    use.add_argument("--include-project-memory", action=argparse.BooleanOptionalAction, default=True)
    use.set_defaults(func=cmd_handover)

    session_start_context = sub.add_parser("session-start-context")
    session_start_context.add_argument("--personal-chars", type=int, default=4000)
    session_start_context.add_argument("--repo-chars", type=int, default=3000)
    session_start_context.set_defaults(func=cmd_session_start_context)

    personal_context = sub.add_parser("personal-context")
    personal_context.add_argument("selector", nargs="?")
    personal_context.add_argument("--personal-chars", type=int, default=4000)
    personal_context.add_argument("--list", action="store_true")
    personal_context.set_defaults(func=cmd_personal_context)

    repo_context = sub.add_parser("repo-context")
    repo_context.add_argument("selector", nargs="?")
    repo_context.add_argument("--repo-chars", type=int, default=3000)
    repo_context.add_argument("--list", action="store_true")
    repo_context.set_defaults(func=cmd_repo_context)

    integrations_status = sub.add_parser("integrations-status")
    integrations_status.add_argument("--target")
    integrations_status.add_argument("--probe-gemini", action="store_true")
    integrations_status.set_defaults(func=cmd_integrations_status)

    hooks_disable = sub.add_parser("hooks-disable")
    hooks_disable.add_argument("--runner", default="all", choices=["all", "codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    hooks_disable.add_argument("--reason")
    hooks_disable.set_defaults(func=cmd_hooks_disable)

    hooks_enable = sub.add_parser("hooks-enable")
    hooks_enable.add_argument("--runner", default="all", choices=["all", "codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    hooks_enable.add_argument("--reason")
    hooks_enable.set_defaults(func=cmd_hooks_enable)

    hooks_status = sub.add_parser("hooks-status")
    hooks_status.set_defaults(func=cmd_hooks_status)

    integration_hooks = sub.add_parser("integration-hooks")
    integration_hooks.add_argument("--client", required=True, choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    integration_hooks.add_argument("--action", required=True, choices=["enable", "disable"])
    integration_hooks.add_argument("--target")
    integration_hooks.add_argument("--memory-root")
    integration_hooks.set_defaults(func=cmd_integration_hooks)

    gemini_status = sub.add_parser("gemini-status")
    gemini_status.add_argument("--target")
    gemini_status.add_argument("--probe", action="store_true")
    gemini_status.set_defaults(func=cmd_gemini_status)

    gemini_enable = sub.add_parser("gemini-enable")
    gemini_enable.add_argument("--target", help="Project folder where .gemini/settings.json should be written")
    gemini_enable.add_argument("--memory-root", help="Central Agent Context Engine memory root; defaults to this installation root")
    gemini_enable.set_defaults(func=cmd_gemini_enable)

    antigravity_enable = sub.add_parser("antigravity-enable")
    antigravity_enable.add_argument("--target", help="Project folder where .agents/hooks.json should be written")
    antigravity_enable.add_argument("--memory-root", help="Central Agent Context Engine root; defaults to this installation root")
    antigravity_enable.set_defaults(func=cmd_antigravity_enable)

    antigravity_status = sub.add_parser("antigravity-status")
    antigravity_status.add_argument("--target")
    antigravity_status.set_defaults(func=cmd_antigravity_status)

    opencode_enable = sub.add_parser("opencode-enable")
    opencode_enable.add_argument("--target")
    opencode_enable.add_argument("--memory-root")
    opencode_enable.add_argument("--model")
    opencode_enable.add_argument("--small-model")
    opencode_enable.set_defaults(func=cmd_opencode_enable)

    opencode_status = sub.add_parser("opencode-status")
    opencode_status.add_argument("--target")
    opencode_status.set_defaults(func=cmd_opencode_status)

    global_wrapper_enable = sub.add_parser("global-wrapper-enable")
    global_wrapper_enable.add_argument("wrapper", choices=["codex-ace", "claude-ace", "agy-ace", "gemini-ace", "opencode-ace"])
    global_wrapper_enable.add_argument("--link-dir", default="~/.local/bin")
    global_wrapper_enable.add_argument("--instance-name", help="Optional instance name used for prefixed global command links")
    global_wrapper_enable.add_argument("--command-prefix", help="Optional prefix for the global command link, e.g. personal-")
    global_wrapper_enable.add_argument("--wrapper-prefix", help="Optional prefix for the global command link, e.g. test-")
    global_wrapper_enable.add_argument("--wrapper-suffix", help="Optional suffix for the global command link, e.g. -v2")
    global_wrapper_enable.add_argument("--force", action="store_true")
    global_wrapper_enable.set_defaults(func=cmd_global_wrapper_enable)

    global_wrapper_disable = sub.add_parser("global-wrapper-disable")
    global_wrapper_disable.add_argument("wrapper", choices=["codex-ace", "claude-ace", "agy-ace", "gemini-ace", "opencode-ace"])
    global_wrapper_disable.add_argument("--link-dir", default="~/.local/bin")
    global_wrapper_disable.add_argument("--instance-name", help="Optional instance name used for prefixed global command links")
    global_wrapper_disable.add_argument("--command-prefix", help="Optional prefix for the global command link, e.g. personal-")
    global_wrapper_disable.add_argument("--wrapper-prefix", help="Optional prefix for the global command link, e.g. test-")
    global_wrapper_disable.add_argument("--wrapper-suffix", help="Optional suffix for the global command link, e.g. -v2")
    global_wrapper_disable.set_defaults(func=cmd_global_wrapper_disable)

    global_wrapper_status = sub.add_parser("global-wrapper-status")
    global_wrapper_status.add_argument("--link-dir", default="~/.local/bin")
    global_wrapper_status.set_defaults(func=cmd_global_wrapper_status)

    summarize = sub.add_parser("summarize")
    summarize.add_argument("--pending", action="store_true")
    summarize.add_argument("--session")
    summarize.set_defaults(func=cmd_summarize)

    summarize_windows = sub.add_parser("summarize-windows")
    summarize_windows.add_argument("--grace-minutes", type=int, default=5)
    summarize_windows.add_argument("--force", action="store_true")
    summarize_windows.add_argument("--fix-gaps", action=argparse.BooleanOptionalAction, default=True)
    summarize_windows.set_defaults(func=cmd_summarize_windows)

    dream = sub.add_parser("dream")
    dream.add_argument("--pending", action="store_true")
    dream.add_argument("--session")
    dream.add_argument("--runner", default="same-as-session")
    dream.add_argument("--runner-model")
    dream.add_argument("--runner-timeout", type=int, default=1800)
    dream.add_argument("--pipeline-version", type=int, choices=[2], help="Only pipeline version 2 is supported")
    dream.add_argument("--dry-run", action="store_true", help="For pipeline v2, write run artifacts without durable semantic/session persistence")
    dream.add_argument("--graph-runner", default="codex")
    dream.add_argument("--graph-runner-model")
    dream.add_argument("--fix-windows", action=argparse.BooleanOptionalAction, default=True)
    dream.add_argument("--window-grace-minutes", type=int, default=5)
    dream.add_argument("--repair-missing-graph-patches-limit", type=int, default=3)
    dream.add_argument("--created-by", default="manual")
    dream.add_argument("--sync-neo4j", action=argparse.BooleanOptionalAction, default=True)
    add_neo4j_args(dream)
    dream.set_defaults(func=cmd_dream_v2)

    dream_v2_inspect = sub.add_parser("dream-v2-inspect")
    dream_v2_inspect.add_argument("dream_run_id")
    dream_v2_inspect.add_argument("--include-content", action="store_true")
    dream_v2_inspect.add_argument("--content-chars", type=int, default=12000)
    dream_v2_inspect.add_argument("--json", action="store_true")
    dream_v2_inspect.set_defaults(func=cmd_dream_v2_inspect)

    dream_v2_audit = sub.add_parser("dream-v2-audit")
    dream_v2_audit.add_argument("dream_run_id")
    dream_v2_audit.add_argument("--section", default="all", choices=["all", "summary", "changes", "review"])
    dream_v2_audit.add_argument("--json", action="store_true")
    dream_v2_audit.set_defaults(func=cmd_dream_v2_audit)

    dream_v2_eval = sub.add_parser("dream-v2-evaluate")
    dream_v2_eval.add_argument("--limit", type=int, default=20)
    dream_v2_eval.add_argument("--json", action="store_true")
    dream_v2_eval.set_defaults(func=cmd_dream_v2_evaluate)

    dream_v2_fixture = sub.add_parser("dream-v2-fixture")
    dream_v2_fixture.add_argument("--kind", default="small", choices=["small", "medium", "oversized", "injection"])
    dream_v2_fixture.add_argument("--session-id")
    dream_v2_fixture.add_argument("--project", default="agent-memory-fixtures")
    dream_v2_fixture.add_argument("--replace", action="store_true")
    dream_v2_fixture.add_argument("--json", action="store_true")
    dream_v2_fixture.set_defaults(func=cmd_dream_v2_fixture)

    dream_v2_fixture_eval = sub.add_parser("dream-v2-fixture-evaluate")
    dream_v2_fixture_eval.add_argument("--kind", default="small", choices=["small", "medium", "oversized", "injection"])
    dream_v2_fixture_eval.add_argument("--session-id")
    dream_v2_fixture_eval.add_argument("--project", default="agent-memory-fixtures")
    dream_v2_fixture_eval.add_argument("--runner", default="codex")
    dream_v2_fixture_eval.add_argument("--runner-model")
    dream_v2_fixture_eval.add_argument("--runner-timeout", type=int, default=60)
    dream_v2_fixture_eval.add_argument("--json", action="store_true")
    dream_v2_fixture_eval.set_defaults(func=cmd_dream_v2_fixture_evaluate)

    dream_v2_readiness = sub.add_parser("dream-v2-readiness")
    dream_v2_readiness.add_argument("--runner", default="codex")
    dream_v2_readiness.add_argument("--runner-model")
    dream_v2_readiness.add_argument("--runner-timeout", type=int, default=60)
    dream_v2_readiness.add_argument("--json", action="store_true")
    dream_v2_readiness.set_defaults(func=cmd_dream_v2_readiness)

    dream_v2_rerun = sub.add_parser("dream-v2-rerun")
    dream_v2_rerun.add_argument("dream_run_id")
    dream_v2_rerun.add_argument("--runner")
    dream_v2_rerun.add_argument("--runner-model")
    dream_v2_rerun.add_argument("--runner-timeout", type=int, default=1800)
    dream_v2_rerun.add_argument("--reuse-validated-stages", action="store_true", help="Reuse validated prior LLM stage outputs when the rerun event window matches.")
    dream_v2_rerun.add_argument("--force", action="store_true")
    dream_v2_rerun.set_defaults(func=cmd_dream_v2_rerun)

    dream_v2_apply = sub.add_parser("dream-v2-apply")
    dream_v2_apply.add_argument("dream_run_id")
    dream_v2_apply.add_argument("--json", action="store_true")
    dream_v2_apply.set_defaults(func=cmd_dream_v2_apply)

    dream_v2_review = sub.add_parser("dream-v2-review")
    dream_v2_review_sub = dream_v2_review.add_subparsers(dest="review_command", required=True)
    dream_v2_review_list = dream_v2_review_sub.add_parser("list")
    dream_v2_review_list.add_argument("--limit", type=int, default=50)
    dream_v2_review_list.add_argument("--json", action="store_true")
    dream_v2_review_list.set_defaults(func=cmd_dream_v2_review)
    dream_v2_review_decide = dream_v2_review_sub.add_parser("decide")
    dream_v2_review_decide.add_argument("decision_id")
    dream_v2_review_decide.add_argument("action", choices=["approve", "reject", "defer"])
    dream_v2_review_decide.add_argument("--reason")
    dream_v2_review_decide.add_argument("--reviewer", default="manual")
    dream_v2_review_decide.set_defaults(func=cmd_dream_v2_review)

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--project")
    search.add_argument("--intent")
    search.add_argument("--tag")
    search.add_argument("--min-helpful-score", type=float)
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--chars", type=int, default=900)
    search.set_defaults(func=cmd_search)

    retrieve = sub.add_parser("retrieve")
    retrieve.add_argument("query")
    retrieve.add_argument("--project")
    retrieve.add_argument("--workdir")
    retrieve.add_argument("--client")
    retrieve.add_argument("--since")
    retrieve.add_argument("--until")
    retrieve.add_argument("--kind")
    retrieve.add_argument("--include-risky", action="store_true")
    retrieve.add_argument("--limit", type=int, default=10)
    retrieve.add_argument("--chars", type=int, default=700)
    retrieve.add_argument("--runner")
    retrieve.add_argument(
        "--query-expansion",
        choices=["auto", "off", "llm", "deterministic"],
        default=_default_query_expansion_mode(),
    )
    retrieve.add_argument("--expander-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    retrieve.add_argument("--expander-model")
    retrieve.add_argument("--expander-timeout", type=int, default=20)
    retrieve.add_argument("--json", action="store_true")
    retrieve.add_argument("--no-log", action="store_true")
    retrieve.set_defaults(func=cmd_retrieve)

    retrieval_runs = sub.add_parser("retrieval-runs")
    retrieval_runs.add_argument("--limit", type=int, default=20)
    retrieval_runs.add_argument("--results", type=int, default=3)
    retrieval_runs.add_argument("--query")
    retrieval_runs.add_argument("--project")
    retrieval_runs.add_argument("--client")
    retrieval_runs.add_argument("--json", action="store_true")
    retrieval_runs.set_defaults(func=cmd_retrieval_runs)

    retrieval_run = sub.add_parser("retrieval-run")
    retrieval_run.add_argument("retrieval_run_id")
    retrieval_run.add_argument("--chars", type=int, default=700)
    retrieval_run.add_argument("--json", action="store_true")
    retrieval_run.set_defaults(func=cmd_retrieval_run)

    personal = sub.add_parser("personal")
    personal_sub = personal.add_subparsers(dest="personal_command", required=True)
    personal_init = personal_sub.add_parser("init")
    personal_init.add_argument("--overwrite", action="store_true")
    personal_init.set_defaults(func=cmd_personal_init)
    personal_list = personal_sub.add_parser("list")
    personal_list.add_argument("--startup-safe", action="store_true")
    personal_list.set_defaults(func=cmd_personal_list)
    personal_show = personal_sub.add_parser("show")
    personal_show.add_argument("path")
    personal_show.set_defaults(func=cmd_personal_show)
    personal_propose = personal_sub.add_parser("propose")
    personal_propose.add_argument("path")
    personal_propose.add_argument("text")
    personal_propose.add_argument("--session")
    personal_propose.add_argument("--note", default="")
    personal_propose.add_argument("--source-kind", default="observed_pattern", choices=["explicit_instruction", "observed_pattern", "manual", "dream"])
    personal_propose.add_argument("--confidence", type=float, default=0.5)
    personal_propose.add_argument("--sensitivity", default="normal", choices=["normal", "private", "secret"])
    personal_propose.add_argument("--injection-policy", default="on_demand", choices=["startup_safe", "on_demand", "never_auto"])
    personal_propose.set_defaults(func=cmd_personal_propose)
    personal_proposals = personal_sub.add_parser("proposals")
    personal_proposals.add_argument("--status")
    personal_proposals.set_defaults(func=cmd_personal_proposals)
    personal_accept = personal_sub.add_parser("accept")
    personal_accept.add_argument("proposal_id")
    personal_accept.add_argument("--force", action="store_true")
    personal_accept.set_defaults(func=cmd_personal_accept)
    personal_audit = personal_sub.add_parser("audit")
    personal_audit.set_defaults(func=cmd_personal_audit)

    risk = sub.add_parser("risk")
    risk_sub = risk.add_subparsers(dest="risk_command", required=True)
    risk_scan_file = risk_sub.add_parser("scan-file")
    risk_scan_file.add_argument("path")
    risk_scan_file.add_argument("--json", action="store_true")
    risk_scan_file.set_defaults(func=cmd_risk_scan_file)
    risk_scan_text = risk_sub.add_parser("scan-text")
    risk_scan_text.add_argument("--json", action="store_true")
    risk_scan_text.set_defaults(func=cmd_risk_scan_text)
    risk_scan_command = risk_sub.add_parser("scan-command")
    risk_scan_command.add_argument("command")
    risk_scan_command.add_argument("--json", action="store_true")
    risk_scan_command.add_argument("--exit-code", action="store_true")
    risk_scan_command.set_defaults(func=cmd_risk_scan_command)
    risk_list = risk_sub.add_parser("list")
    risk_list.add_argument("--status")
    risk_list.add_argument("--category")
    risk_list.add_argument("--client")
    risk_list.add_argument("--session")
    risk_list.add_argument("--limit", type=int, default=50)
    risk_list.add_argument("--json", action="store_true")
    risk_list.set_defaults(func=cmd_risk_list)
    risk_explain = risk_sub.add_parser("explain")
    risk_explain.add_argument("--session")
    risk_explain.add_argument("--status")
    risk_explain.add_argument("--category")
    risk_explain.add_argument("--limit", type=int, default=20)
    risk_explain.add_argument("--json", action="store_true")
    risk_explain.set_defaults(func=cmd_risk_explain)
    risk_show = risk_sub.add_parser("show")
    risk_show.add_argument("risk_event_id")
    risk_show.add_argument("--json", action="store_true")
    risk_show.set_defaults(func=cmd_risk_show)
    risk_review = risk_sub.add_parser("review")
    risk_review.add_argument("risk_event_id")
    risk_review.add_argument("action", choices=["mark-safe", "block", "keep-quarantined"])
    risk_review.add_argument("--reason", required=True)
    risk_review.add_argument("--reviewer")
    risk_review.add_argument("--force", action="store_true")
    risk_review.add_argument("--json", action="store_true")
    risk_review.set_defaults(func=cmd_risk_review)

    quarantine = sub.add_parser("quarantine")
    quarantine_sub = quarantine.add_subparsers(dest="quarantine_command", required=True)
    quarantine_list = quarantine_sub.add_parser("list")
    quarantine_list.add_argument("--category")
    quarantine_list.add_argument("--client")
    quarantine_list.add_argument("--session")
    quarantine_list.add_argument("--limit", type=int, default=50)
    quarantine_list.add_argument("--json", action="store_true")
    quarantine_list.set_defaults(func=cmd_quarantine_list)
    quarantine_show = quarantine_sub.add_parser("show")
    quarantine_show.add_argument("id")
    quarantine_show.add_argument("--json", action="store_true")
    quarantine_show.set_defaults(func=cmd_quarantine_show)

    firewall = sub.add_parser("firewall")
    firewall_sub = firewall.add_subparsers(dest="firewall_command", required=True)
    firewall_suggest = firewall_sub.add_parser("suggest")
    firewall_suggest.add_argument("--since")
    firewall_suggest.add_argument("--until")
    firewall_suggest.add_argument("--session")
    firewall_suggest.add_argument("--workdir")
    firewall_suggest.add_argument("--host")
    firewall_suggest.add_argument("--action", choices=["read", "verify", "write", "write_execute", "network", "deploy", "delete", "protect_secret", "unknown"])
    firewall_suggest.add_argument("--limit", type=int, default=50)
    firewall_suggest.add_argument("--no-store", action="store_true")
    firewall_suggest.add_argument("--json", action="store_true")
    firewall_suggest.set_defaults(func=cmd_firewall_suggest)
    firewall_list = firewall_sub.add_parser("list")
    firewall_list.add_argument("--status", default="active")
    firewall_list.add_argument("--all", action="store_true")
    firewall_list.add_argument("--limit", type=int, default=50)
    firewall_list.add_argument("--json", action="store_true")
    firewall_list.set_defaults(func=cmd_firewall_list)
    firewall_show = firewall_sub.add_parser("show")
    firewall_show.add_argument("rule_id")
    firewall_show.add_argument("--json", action="store_true")
    firewall_show.set_defaults(func=cmd_firewall_show)

    rebuild = sub.add_parser("rebuild-indexes")
    rebuild.add_argument("--graph", action=argparse.BooleanOptionalAction, default=True)
    rebuild.add_argument("--verbose", action="store_true")
    rebuild.set_defaults(func=cmd_rebuild_indexes)

    metrics = sub.add_parser("metrics")
    metrics.add_argument("--limit", type=int, default=10)
    metrics.set_defaults(func=cmd_metrics)

    dream_insights = sub.add_parser("dream-insights")
    dream_insights.add_argument("--limit", type=int, default=20)
    dream_insights.add_argument("--intent")
    dream_insights.add_argument("--tag")
    dream_insights.add_argument("--min-helpful-score", type=float)
    dream_insights.add_argument("--aggregate", action="store_true")
    dream_insights.set_defaults(func=cmd_dream_insights)

    dream_queue_status = sub.add_parser("dream-queue-status")
    dream_queue_status.add_argument("--status", default="all", choices=["all", "queued", "running", "failed", "terminal_failed", "succeeded"])
    dream_queue_status.add_argument("--session")
    dream_queue_status.add_argument("--limit", type=int, default=20)
    dream_queue_status.add_argument("--json", action="store_true")
    dream_queue_status.set_defaults(func=cmd_dream_queue_status)

    sync = sub.add_parser("sync-transcripts")
    sync.add_argument("--session")
    sync.set_defaults(func=cmd_sync_transcripts)

    sync_codex = sub.add_parser("sync-codex-transcript")
    sync_codex.add_argument("path")
    sync_codex.add_argument("--session-id")
    sync_codex.add_argument("--cwd")
    sync_codex.set_defaults(func=cmd_sync_codex_transcript)

    replay_queue = sub.add_parser("replay-hook-queue")
    replay_queue.add_argument("--client")
    replay_queue.add_argument("--limit", type=int, default=200)
    replay_queue.add_argument("--recover-limit", type=int, default=200)
    replay_queue.add_argument("--stop-on-error", action="store_true")
    replay_queue.add_argument("--worker", action="store_true")
    replay_queue.set_defaults(func=cmd_replay_hook_queue)

    recover_queue = sub.add_parser("recover-hook-queue-failures")
    recover_queue.add_argument("--client")
    recover_queue.add_argument("--limit", type=int, default=200)
    recover_queue.add_argument("--stop-on-error", action="store_true")
    recover_queue.set_defaults(func=cmd_recover_hook_queue_failures)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--check-codex-features", action="store_true")
    doctor.add_argument("--relocation-report", action="store_true", help="Show sample absolute paths that still point outside this root")
    doctor.set_defaults(func=cmd_doctor)

    check_installation = sub.add_parser("check-installation")
    check_installation.add_argument("--target")
    check_installation.add_argument("--memory-root")
    check_installation.add_argument("--codex-workspace-root", action="append")
    check_installation.add_argument("--claude-workspace-root", action="append")
    check_installation.add_argument("--cursor-workspace-root", action="append")
    check_installation.add_argument("--monitor-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    check_installation.add_argument("--dream-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode", "deterministic"])
    check_installation.add_argument("--query-expansion-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode", "deterministic", "off"])
    check_installation.set_defaults(func=cmd_check_installation)

    install_discovery = sub.add_parser("install-discovery")
    install_discovery.add_argument("--target")
    install_discovery.add_argument("--memory-root")
    install_discovery.add_argument("--language", choices=["en", "de"])
    install_discovery.add_argument("--json", action="store_true")
    install_discovery.set_defaults(func=cmd_install_discovery)

    repair_installation = sub.add_parser("repair-installation")
    repair_installation.add_argument("--target")
    repair_installation.add_argument("--memory-root")
    repair_installation.add_argument("--codex-workspace-root", action="append")
    repair_installation.add_argument("--claude-workspace-root", action="append")
    repair_installation.add_argument("--cursor-workspace-root", action="append")
    repair_installation.add_argument("--monitor-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    repair_installation.add_argument("--dream-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode", "deterministic"])
    repair_installation.add_argument("--query-expansion-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode", "deterministic", "off"])
    repair_installation.add_argument("--install-cli", action="append", choices=["codex", "claude"], help="Additively install a known headless CLI after review")
    repair_installation.add_argument("--rewrite-workspace-hook-adapters", action="store_true", help="Explicitly allow rewriting external Codex/Claude workspace hook adapters when they point to the wrong memory root")
    repair_installation.add_argument("--install-frontend-deps", action="store_true")
    repair_installation.add_argument("--apply", action="store_true")
    repair_installation.set_defaults(func=cmd_repair_installation)

    monitor = sub.add_parser("monitor")
    monitor.add_argument("--runner", required=True, choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode"])
    monitor.add_argument("--runner-model")
    monitor.add_argument("--runner-timeout", type=int, default=120)
    monitor.add_argument("--host", default="127.0.0.1")
    monitor.add_argument("--port", type=int, default=8787)
    monitor.add_argument("--language", choices=["en", "de"], default="en", help="Initial monitor UI language")
    monitor.add_argument("--open", action=argparse.BooleanOptionalAction, default=True)
    monitor.add_argument("--install-frontend-deps", action="store_true", help="Install frontend npm dependencies before auto-building the monitor UI if needed")
    monitor.add_argument(
        "--replace-existing",
        nargs="?",
        const=True,
        default=True,
        type=_parse_bool_arg,
        help="Replace existing local monitor on the same host/port (true/false).",
    )
    monitor.add_argument("--no-replace-existing", dest="replace_existing", action="store_false")
    add_neo4j_args(monitor)
    monitor.set_defaults(func=_cmd_monitor_lazy)

    analyze = sub.add_parser("analyze", aliases=["analyse"])
    analyze.add_argument("selector")
    analyze.add_argument("--json", action="store_true")
    analyze.add_argument("--html", action=argparse.BooleanOptionalAction, default=False, help="Generate an HTML report page.")
    analyze.add_argument(
        "--open",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Open generated HTML report in browser when --html is enabled.",
    )
    analyze.add_argument("--include-entities", action=argparse.BooleanOptionalAction, default=True)
    analyze.add_argument("--include-relations", action=argparse.BooleanOptionalAction, default=True)
    analyze.add_argument("--include-risks", action=argparse.BooleanOptionalAction, default=True)
    analyze.add_argument("--entity-limit", type=int, default=0, help="0 means all entities")
    analyze.add_argument("--entity-offset", type=int, default=0)
    analyze.add_argument("--relation-limit", type=int, default=0, help="0 means all relations")
    analyze.add_argument("--relation-offset", type=int, default=0)
    analyze.add_argument("--dream-limit", type=int, default=5)
    analyze.add_argument("--risk-limit", type=int, default=10)
    analyze.add_argument("--firewall-limit", type=int, default=20)
    analyze.set_defaults(func=cmd_analyze)

    cursor_enable = sub.add_parser("cursor-enable")
    cursor_enable.add_argument("--target", help="Project folder where .cursor/hooks.json should be written")
    cursor_enable.add_argument("--memory-root", help="Central Agent Context Engine root; defaults to this installation root")
    cursor_enable.set_defaults(func=cmd_cursor_enable)

    cursor_disable = sub.add_parser("cursor-disable")
    cursor_disable.add_argument("--target", help="Project folder whose Agent Context Engine Cursor hooks should be removed")
    cursor_disable.set_defaults(func=cmd_cursor_disable)

    cursor_status = sub.add_parser("cursor-status")
    cursor_status.add_argument("--target", help="Project folder whose Cursor hook status should be checked")
    cursor_status.set_defaults(func=cmd_cursor_status)

    install = sub.add_parser("install")
    install.add_argument("--target")
    install.add_argument("--memory-root", help="Persistent runtime storage root. Defaults to ~/.agent-context-engine/memory")
    install.add_argument("--storage-schema-version", type=int, help=argparse.SUPPRESS)
    install.add_argument("--instance-name", help="Optional instance name used for prefixed global command links")
    install.add_argument("--command-prefix", help="Optional prefix for global command links, e.g. personal-")
    install.add_argument("--wrapper-prefix", help="Optional prefix for global command links, e.g. test-")
    install.add_argument("--wrapper-suffix", help="Optional suffix for global command links, e.g. -v2")
    install.add_argument("--link-codex-ace", dest="link_codex_memory", action=argparse.BooleanOptionalAction, default=None)
    install.add_argument("--link-claude-ace", dest="link_claude_memory", action=argparse.BooleanOptionalAction, default=None)
    install.add_argument("--link-agy-ace", dest="link_agy_memory", action=argparse.BooleanOptionalAction, default=None)
    install.add_argument("--link-gemini-ace", dest="link_gemini_memory", action=argparse.BooleanOptionalAction, default=None)
    install.add_argument("--link-opencode-ace", dest="link_opencode_memory", action=argparse.BooleanOptionalAction, default=None)
    install.add_argument("--link-dir", default="~/.local/bin")
    install.add_argument("--language", choices=["en", "de"], help="Preferred interaction language for future agents")
    install.add_argument("--monitor-host", help="Default monitor host stored in the installation profile")
    install.add_argument("--monitor-port", type=int, help="Default monitor port stored in the installation profile")
    install.add_argument("--launchagent-label", help="Default LaunchAgent label stored in the installation profile")
    install.add_argument("--launchagent-path", help="Default LaunchAgent plist path stored in the installation profile")
    install.add_argument("--launchagent-env-file", help="Default LaunchAgent env-file stored in the installation profile")
    install.add_argument("--codex-workspace-root", action="append", help="Additional Codex GUI workspace root that should receive .codex hook files pointing back to this Agent Context Engine installation")
    install.add_argument("--claude-workspace-root", action="append", help="Additional Claude workspace root that should receive .claude hook files pointing back to this Agent Context Engine installation")
    install.add_argument("--cursor-workspace-root", action="append", help="Cursor project root to activate during install")
    install.add_argument("--monitor-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode"], help="Runner Agent Context Engine should depend on for monitor ask / monitor operator flows")
    install.add_argument("--dream-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode", "deterministic"], help="Runner Agent Context Engine should depend on for dreaming and headless analysis")
    install.add_argument("--query-expansion-runner", choices=["codex", "claude", "cursor", "antigravity", "gemini", "opencode", "deterministic", "off"], help="Runner Agent Context Engine should depend on for LLM query expansion")
    install.add_argument(
        "--project",
        action="append",
        help="Initial repos.md entry as name=/path or name:/path. Can be repeated.",
    )
    install.add_argument("--no-interactive", action="store_true", help="Do not prompt for initial repos.md projects")
    install.add_argument("--bootstrap-runtime", action=argparse.BooleanOptionalAction, default=True, help="Create `.venv` and install backend dependencies into it during install")
    install.add_argument("--install-launchagent", action=argparse.BooleanOptionalAction, default=True, help="Install and load the periodic LaunchAgent after setup")
    install.add_argument("--start-monitor", action=argparse.BooleanOptionalAction, default=True, help="Start the local monitor with the stored default host/port after setup")
    install.add_argument("--force", action="store_true")
    install.set_defaults(func=cmd_install)

    attach_memory_root = sub.add_parser("attach-memory-root")
    attach_memory_root.add_argument("--target")
    attach_memory_root.add_argument("--memory-root", required=True, help="Persistent runtime storage root to attach")
    attach_memory_root.add_argument("--storage-schema-version", type=int, help=argparse.SUPPRESS)
    attach_memory_root.set_defaults(func=cmd_attach_memory_root)

    migrate_storage = sub.add_parser("migrate-storage")
    migrate_storage.add_argument("--target")
    migrate_storage.add_argument("--storage-schema-version", type=int, help=argparse.SUPPRESS)
    migrate_storage.set_defaults(func=cmd_migrate_storage)

    scheduler_run = sub.add_parser("scheduler-run")
    scheduler_run.add_argument("--grace-minutes", type=int, default=5)
    scheduler_run.add_argument("--runner", default="same-as-session")
    scheduler_run.add_argument("--runner-model")
    scheduler_run.add_argument("--runner-timeout", type=int, default=1800)
    scheduler_run.add_argument("--pipeline-version", type=int, choices=[2], help="Only pipeline version 2 is supported")
    scheduler_run.add_argument("--graph-runner", default="codex")
    scheduler_run.add_argument("--graph-runner-model")
    scheduler_run.add_argument("--sync-neo4j", action=argparse.BooleanOptionalAction, default=True)
    scheduler_run.add_argument("--neo4j-sync-limit", type=int, default=5)
    scheduler_run.add_argument("--neo4j-batch-size", type=int, default=500)
    scheduler_run.add_argument("--neo4j-timeout", type=int, default=60)
    scheduler_run.add_argument("--repair-missing-graph-patches-limit", type=int, default=0)
    scheduler_run.add_argument("--dream-enqueue-limit", type=int, default=25)
    scheduler_run.add_argument("--dream-queue-limit", type=int, default=5)
    add_neo4j_args(scheduler_run)
    scheduler_run.set_defaults(func=cmd_scheduler_run)

    install_launchagent = sub.add_parser("install-launchagent")
    install_launchagent.add_argument("--label", default=DEFAULT_LABEL)
    install_launchagent.add_argument("--interval", type=int, default=900)
    install_launchagent.add_argument("--grace-minutes", type=int, default=5)
    install_launchagent.add_argument("--runner", default="same-as-session")
    install_launchagent.add_argument("--runner-model")
    install_launchagent.add_argument("--runner-timeout", type=int, default=1800)
    install_launchagent.add_argument("--graph-runner", default="codex")
    install_launchagent.add_argument("--graph-runner-model")
    install_launchagent.add_argument("--sync-neo4j", action=argparse.BooleanOptionalAction, default=False)
    install_launchagent.add_argument("--neo4j-sync-limit", type=int, default=5)
    install_launchagent.add_argument("--neo4j-batch-size", type=int, default=500)
    install_launchagent.add_argument("--neo4j-timeout", type=int, default=60)
    install_launchagent.add_argument("--repair-missing-graph-patches-limit", type=int, default=0)
    install_launchagent.add_argument("--dream-enqueue-limit", type=int, default=25)
    install_launchagent.add_argument("--dream-queue-limit", type=int, default=5)
    install_launchagent.add_argument("--path", default=DEFAULT_LAUNCHD_PATH)
    install_launchagent.add_argument("--plist-path")
    install_launchagent.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    install_launchagent.add_argument("--run-at-load", action="store_true")
    install_launchagent.add_argument("--load", action="store_true")
    install_launchagent.set_defaults(func=cmd_install_launchagent)

    uninstall_launchagent = sub.add_parser("uninstall-launchagent")
    uninstall_launchagent.add_argument("--label", default=DEFAULT_LABEL)
    uninstall_launchagent.add_argument("--plist-path")
    uninstall_launchagent.add_argument("--unload", action=argparse.BooleanOptionalAction, default=True)
    uninstall_launchagent.set_defaults(func=cmd_uninstall_launchagent)

    launchagent_status = sub.add_parser("launchagent-status")
    launchagent_status.add_argument("--label", default=DEFAULT_LABEL)
    launchagent_status.add_argument("--plist-path")
    launchagent_status.add_argument("--verbose", action="store_true")
    launchagent_status.set_defaults(func=cmd_launchagent_status)

    scheduler_status = sub.add_parser("scheduler-status")
    scheduler_status.add_argument("--limit", type=int, default=10)
    scheduler_status.set_defaults(func=cmd_scheduler_status)

    prune_logs = sub.add_parser("prune-logs")
    prune_logs.add_argument("--days", type=int, default=3)
    prune_logs.add_argument("--all", action="store_true")
    prune_logs.add_argument("--dry-run", action="store_true")
    prune_logs.set_defaults(func=cmd_prune_logs)

    prune_event_logs = sub.add_parser("prune-event-logs")
    prune_event_logs.add_argument("--dry-run", action="store_true")
    prune_event_logs.set_defaults(func=cmd_prune_event_logs)

    purge_tool_outputs = sub.add_parser("purge-tool-outputs")
    purge_tool_outputs.add_argument("--dry-run", action="store_true")
    purge_tool_outputs.set_defaults(func=cmd_purge_tool_outputs)

    graph_prune = sub.add_parser("graph-prune")
    graph_prune.add_argument("--kind", choices=GRAPH_PRUNE_KINDS, action="append", help="Artifact kind to prune. Repeat for multiple kinds. Defaults to all processed graph artifact kinds.")
    graph_prune.add_argument("--archive", help="Write selected artifacts to a .tar.gz archive before optional deletion.")
    graph_prune.add_argument("--delete", action="store_true", help="Delete selected artifacts from memory/graph after optional archive creation.")
    graph_prune.add_argument("--include-pending-neo4j", action="store_true", help="Also prune patch files that have not been recorded as imported into Neo4j.")
    graph_prune.add_argument("--show-limit", type=int, default=20)
    graph_prune.set_defaults(func=cmd_graph_prune)

    graph_quality = sub.add_parser("graph-quality")
    graph_quality.add_argument("--query", action="append", help="Query to evaluate. Repeat for multiple queries.")
    graph_quality.add_argument("--eval-file", help="Optional retrieval eval JSON file with questions[].query.")
    graph_quality.add_argument("--limit", type=int, default=8)
    graph_quality.add_argument("--query-limit", type=int, default=5)
    graph_quality.add_argument("--json", action="store_true")
    graph_quality.set_defaults(func=cmd_graph_quality)

    graph_extract = sub.add_parser("graph-extract")
    graph_extract.add_argument("selector")
    graph_extract.add_argument("--latest-dream", action=argparse.BooleanOptionalAction, default=True)
    graph_extract.set_defaults(func=cmd_graph_extract)

    graph_structure = sub.add_parser("graph-structure")
    graph_structure.add_argument("selector")
    graph_structure.add_argument("--latest-dream", action=argparse.BooleanOptionalAction, default=True)
    graph_structure.add_argument("--runner", default="deterministic")
    graph_structure.add_argument("--runner-model")
    graph_structure.add_argument("--runner-timeout", type=int, default=1800)
    graph_structure.set_defaults(func=cmd_graph_structure)

    graph_status = sub.add_parser("graph-status")
    graph_status.add_argument("--limit", type=int, default=10)
    graph_status.add_argument("--intent")
    graph_status.add_argument("--tag")
    graph_status.add_argument("--min-helpful-score", type=float)
    graph_status.set_defaults(func=cmd_graph_status)

    graph_backfill_command_families = sub.add_parser("graph-backfill-command-families")
    graph_backfill_command_families.add_argument("--json", action="store_true")
    graph_backfill_command_families.add_argument("--write-patch", action="store_true")
    graph_backfill_command_families.set_defaults(func=cmd_graph_backfill_command_families)

    graph_validate = sub.add_parser("graph-validate")
    graph_validate.add_argument("path")
    graph_validate.set_defaults(func=cmd_graph_validate)

    graph_schema = sub.add_parser("graph-schema-context")
    graph_schema.add_argument("--format", choices=["markdown", "json"], default="markdown")
    graph_schema.set_defaults(func=cmd_graph_schema_context)

    graph_candidates = sub.add_parser("graph-candidates")
    graph_candidates.add_argument("patch")
    graph_candidates.set_defaults(func=cmd_graph_candidates)

    graph_match = sub.add_parser("graph-match-candidates")
    graph_match.add_argument("candidates")
    graph_match.add_argument("--threshold", type=float, default=0.72)
    graph_match.add_argument("--reuse-threshold", type=float, default=0.92)
    graph_match.add_argument("--limit-per-entity", type=int, default=5)
    graph_match.add_argument("--patch-limit", type=int, default=50)
    graph_match.add_argument("--include-neo4j", action="store_true")
    add_neo4j_args(graph_match)
    graph_match.set_defaults(func=cmd_graph_match_candidates)

    graph_reconcile = sub.add_parser("graph-reconcile")
    graph_reconcile.add_argument("candidates")
    graph_reconcile.add_argument("--matches", required=True)
    graph_reconcile.set_defaults(func=cmd_graph_reconcile)

    graph_query = sub.add_parser("graph-query")
    graph_query.add_argument("query_command", choices=["sessions", "entities", "entity", "related", "recent"])
    graph_query.add_argument("query", nargs="*")
    graph_query.add_argument("--type")
    graph_query.add_argument("--limit", type=int, default=20)
    graph_query.add_argument("--patch-limit", type=int, default=25)
    graph_query.add_argument("--evidence-limit", type=int, default=5)
    graph_query.set_defaults(func=cmd_graph_query)

    schema_proposals = sub.add_parser("schema-proposals")
    schema_sub = schema_proposals.add_subparsers(dest="schema_command", required=True)

    schema_list = schema_sub.add_parser("list")
    schema_list.add_argument("--status")
    schema_list.add_argument("--kind", choices=["entity_type", "relation_type", "alias", "merge"])
    schema_list.add_argument("--limit", type=int, default=50)
    schema_list.add_argument("--json", action="store_true")
    schema_list.set_defaults(func=cmd_schema_proposals)

    schema_create = schema_sub.add_parser("create")
    schema_create.add_argument("kind", choices=["entity_type", "relation_type", "alias", "merge"])
    schema_create.add_argument("proposed_name")
    schema_create.add_argument("--canonical-name")
    schema_create.add_argument("--confidence", type=float)
    schema_create.add_argument("--reason")
    schema_create.add_argument("--example", action="append")
    schema_create.add_argument("--actor", default="manual")
    schema_create.add_argument("--json", action="store_true")
    schema_create.set_defaults(func=cmd_schema_proposals)

    schema_review = schema_sub.add_parser("review")
    schema_review.add_argument("proposal_id")
    schema_review.add_argument("--actor", default="deterministic:schema-review")
    schema_review.add_argument("--json", action="store_true")
    schema_review.set_defaults(func=cmd_schema_proposals)

    schema_decide = schema_sub.add_parser("decide")
    schema_decide.add_argument("proposal_id")
    schema_decide.add_argument("action", choices=["approved", "rejected", "merged", "promoted"])
    schema_decide.add_argument("--canonical-name")
    schema_decide.add_argument("--reason")
    schema_decide.add_argument("--actor", default="manual")
    schema_decide.add_argument("--json", action="store_true")
    schema_decide.set_defaults(func=cmd_schema_proposals)

    schema_registry = schema_sub.add_parser("registry")
    schema_registry.add_argument("--kind", choices=["entity_type", "relation_type", "alias", "merge"])
    schema_registry.add_argument("--limit", type=int, default=200)
    schema_registry.add_argument("--json", action="store_true")
    schema_registry.set_defaults(func=cmd_schema_proposals)

    neo4j_status = sub.add_parser("neo4j-status")
    add_neo4j_args(neo4j_status)
    neo4j_status.set_defaults(func=cmd_neo4j_status)

    neo4j_schema = sub.add_parser("neo4j-install-schema")
    add_neo4j_args(neo4j_schema)
    neo4j_schema.set_defaults(func=cmd_neo4j_install_schema)

    neo4j_create_database = sub.add_parser("neo4j-create-database")
    neo4j_create_database.add_argument("name")
    neo4j_create_database.add_argument("--timeout", type=int, default=30)
    add_neo4j_args(neo4j_create_database)
    neo4j_create_database.set_defaults(func=cmd_neo4j_create_database)

    neo4j_import = sub.add_parser("neo4j-import")
    neo4j_import.add_argument("patch")
    neo4j_import.add_argument("--dry-run", action="store_true")
    neo4j_import.add_argument("--batch-size", type=int, default=500)
    neo4j_import.add_argument("--timeout", type=int, default=60)
    add_neo4j_args(neo4j_import)
    neo4j_import.set_defaults(func=cmd_neo4j_import)

    neo4j_sync_pending = sub.add_parser("neo4j-sync-pending")
    neo4j_sync_pending.add_argument("--limit", type=int)
    neo4j_sync_pending.add_argument("--dry-run", action="store_true")
    neo4j_sync_pending.add_argument("--batch-size", type=int, default=500)
    neo4j_sync_pending.add_argument("--timeout", type=int, default=60)
    add_neo4j_args(neo4j_sync_pending)
    neo4j_sync_pending.set_defaults(func=cmd_neo4j_sync_pending)

    neo4j_repair_semantic = sub.add_parser("neo4j-repair-semantic-projection")
    neo4j_repair_semantic.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True)
    neo4j_repair_semantic.add_argument("--batch-size", type=int, default=500)
    neo4j_repair_semantic.add_argument("--timeout", type=int, default=60)
    neo4j_repair_semantic.add_argument("--json", action="store_true")
    add_neo4j_args(neo4j_repair_semantic)
    neo4j_repair_semantic.set_defaults(func=cmd_neo4j_repair_semantic_projection)

    neo4j_import_status = sub.add_parser("neo4j-import-status")
    neo4j_import_status.add_argument("--limit", type=int, default=10)
    add_neo4j_args(neo4j_import_status)
    neo4j_import_status.set_defaults(func=cmd_neo4j_import_status)

    return parser


_GRAPH_QUERY_OPTIONS_WITH_VALUE = {
    "--type",
    "--limit",
    "--patch-limit",
    "--evidence-limit",
}


def _normalize_graph_query_args(argv: list[str]) -> list[str]:
    if len(argv) < 2 or argv[0] != "graph-query" or argv[1] not in {"sessions", "entities", "entity", "related", "recent"}:
        return argv

    if not argv[2:] or not argv[2].startswith("-"):
        return argv

    query_command = argv[1]
    rest = argv[2:]
    normalized_rest: list[str] = []
    options: list[str] = []
    query: str | None = None

    i = 0
    while i < len(rest):
        token = rest[i]
        if token.startswith("-"):
            if token in _GRAPH_QUERY_OPTIONS_WITH_VALUE and i + 1 < len(rest):
                options.extend([token, rest[i + 1]])
                i += 2
                continue
            options.append(token)
            i += 1
            continue

        if query is None:
            query = token
            i += 1
            continue

        options.append(token)
        i += 1

    if query is None:
        return argv

    normalized_rest.extend([query])
    normalized_rest.extend(options)
    return [argv[0], query_command, *normalized_rest]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(_normalize_graph_query_args(list(argv) if argv is not None else list(sys.argv[1:])))
    return args.func(args)
