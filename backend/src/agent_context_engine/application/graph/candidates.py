from __future__ import annotations

import argparse

from .adapters import (
    cmd_graph_query as _cmd_graph_query,
    cmd_graph_candidates as _cmd_graph_candidates,
    cmd_graph_match_candidates as _cmd_graph_match_candidates,
    cmd_graph_reconcile as _cmd_graph_reconcile,
)


def cmd_graph_query(args: argparse.Namespace) -> int:
    return _cmd_graph_query(args)


def cmd_graph_candidates(args: argparse.Namespace) -> int:
    return _cmd_graph_candidates(args)


def cmd_graph_match_candidates(args: argparse.Namespace) -> int:
    return _cmd_graph_match_candidates(args)


def cmd_graph_reconcile(args: argparse.Namespace) -> int:
    return _cmd_graph_reconcile(args)
