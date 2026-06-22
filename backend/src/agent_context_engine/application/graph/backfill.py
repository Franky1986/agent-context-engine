from __future__ import annotations

import argparse
import json
from typing import Any
import sqlite3

from ...infrastructure.db import connect
from ...infrastructure.config import json_dumps
from .adapters import (
    backfill_command_families as _backfill_command_families,
    command_family,
    command_family_key,
    command_family_properties,
    display_path,
    write_command_family_import_patch,
)


def backfill_command_families(conn: sqlite3.Connection) -> dict[str, int]:
    return _backfill_command_families(
        conn,
        command_family_func=command_family,
        command_family_key_func=command_family_key,
        command_family_properties_func=command_family_properties,
    )


def cmd_graph_backfill_command_families(args: argparse.Namespace) -> int:
    conn = connect()
    counts = backfill_command_families(conn)
    patch_info: dict[str, Any] | None = None
    if args.write_patch:
        path, patch_counts = write_command_family_import_patch(conn)
        patch_info = {"path": display_path(path), **patch_counts}
    if args.json:
        print(json_dumps({"backfill": counts, "patch": patch_info}))
    else:
        print(
            "command families backfilled "
            f"commands={counts['commands']} families={counts['families']} "
            f"relations={counts['relations']} evidence={counts['evidence']}"
        )
        if patch_info:
            print(
                f"wrote {patch_info['path']} entities={patch_info['entities']} "
                f"relations={patch_info['relations']} evidence={patch_info['evidence']}"
            )
    return 0
