from __future__ import annotations

import argparse

from .adapters import cmd_graph_query as _cmd_graph_query


def cmd_graph_query(args: argparse.Namespace) -> int:
    return _cmd_graph_query(args)
