from __future__ import annotations

import argparse

from ....application.maintenance import (
    GRAPH_PRUNE_KINDS,
    run_graph_prune,
    run_prune_event_logs,
    run_prune_logs,
    run_purge_tool_outputs,
)


def cmd_graph_prune(args: argparse.Namespace) -> int:
    lines, exit_code = run_graph_prune(
        kinds=args.kind,
        include_pending_neo4j=args.include_pending_neo4j,
        archive=args.archive,
        delete=args.delete,
        show_limit=args.show_limit,
    )
    for line in lines:
        print(line)
    return exit_code


def cmd_prune_logs(args: argparse.Namespace) -> int:
    lines, exit_code = run_prune_logs(days=args.days, all=args.all, dry_run=args.dry_run)
    for line in lines:
        print(line)
    return exit_code


def cmd_purge_tool_outputs(args: argparse.Namespace) -> int:
    lines, exit_code = run_purge_tool_outputs(dry_run=args.dry_run)
    for line in lines:
        print(line)
    return exit_code


def cmd_prune_event_logs(args: argparse.Namespace) -> int:
    lines, exit_code = run_prune_event_logs(dry_run=args.dry_run)
    for line in lines:
        print(line)
    return exit_code
