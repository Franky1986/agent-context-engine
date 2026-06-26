from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ....infrastructure.config import json_dumps
from ....application.risk_api import (
    explain_risk_events,
    get_risk_event,
    list_risk_events,
    risk_review_action,
    scan_risk_command,
    scan_risk_file,
    scan_risk_text,
)
from ....infrastructure.text import markdown_escape


def local_time(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def cmd_risk_scan_file(args: argparse.Namespace) -> int:
    path = Path(args.path).expanduser().resolve()
    data = scan_risk_file(str(path))
    print(json_dumps(data) if args.json else json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_risk_scan_text(args: argparse.Namespace) -> int:
    text = sys.stdin.read()
    data = scan_risk_text(text)
    print(json_dumps(data) if args.json else json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_risk_scan_command(args: argparse.Namespace) -> int:
    data = scan_risk_command(args.command)
    print(json_dumps(data) if args.json else json.dumps(data, ensure_ascii=False, indent=2))
    return 2 if data.get("block") and args.exit_code else 0


def cmd_risk_list(args: argparse.Namespace) -> int:
    rows = list_risk_events(
        status=args.status,
        category=args.category,
        client=args.client,
        session=args.session,
        limit=args.limit,
    )
    if args.json:
        print(json_dumps(rows))
        return 0
    for row in rows:
        categories = row.get("categories")
        if not isinstance(categories, list):
            categories = []
        print(f"{local_time(row['created_at'])} {row['status']} {row['risk_level']} {row['risk_event_id']} {row['source_kind']} {row['source_ref'] or ''}")
        print(
            "  decision="
            + f"{row['decision']} "
            + f"categories={json.dumps(categories, ensure_ascii=False)} "
            + f"impact={row['impact']}"
        )
        if row["preview"]:
            print(f"  preview={markdown_escape(row['preview'], 220)}")
    if not rows:
        print("No risk events.")
    return 0


def cmd_risk_explain(args: argparse.Namespace) -> int:
    rows = explain_risk_events(
        session=args.session,
        status=args.status,
        category=args.category,
        limit=args.limit,
    )
    if args.json:
        print(json_dumps(rows))
        return 0
    for row in rows:
        print(
            f"{local_time(row['created_at'])} seq={row['event_seq']} {row['status']} "
            f"{row['risk_level']} {row['risk_event_id']}"
        )
        print(f"  session={row['session_id']} approval={row['approval_state'] or '-'} command_hash={(row['command_hash'] or '')[:16] or '-'}")
        print(
            f"  classifier={row['runner'] or '-'} model={row['model'] or '-'} "
            f"status={row['classifier_status'] or '-'} decision={row['classifier_decision'] or '-'} "
            f"tokens={row['total_tokens'] if row['total_tokens'] is not None else '-'} duration_ms={row['duration_ms'] if row['duration_ms'] is not None else '-'}"
        )
        print(f"  flags={row['poisoning_flags_json']} deterministic={row['deterministic_flags_json']}")
        print(f"  reason={markdown_escape(row['reason'], 260)}")
        if row["classifier_reason"] and row["classifier_reason"] != row["reason"]:
            print(f"  classifier_reason={markdown_escape(row['classifier_reason'], 260)}")
        if row["impact"]:
            print(f"  impact={markdown_escape(row['impact'], 260)}")
        if row["preview"]:
            print(f"  preview={markdown_escape(row['preview'], 220)}")
        if row["taint_context_json"] and row["taint_context_json"] != "[]":
            print(f"  taint_context={markdown_escape(row['taint_context_json'], 360)}")
    if not rows:
        print("No risk events.")
    return 0


def cmd_risk_show(args: argparse.Namespace) -> int:
    data = get_risk_event(args.risk_event_id)
    if not data:
        print("Risk event not found.")
        return 1
    print(json_dumps(data) if args.json else json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def cmd_risk_review(args: argparse.Namespace) -> int:
    try:
        data = risk_review_action(
            args.risk_event_id,
            action=args.action,
            reason=args.reason,
            reviewer=args.reviewer,
            force=args.force,
        )
    except ValueError as exc:
        print(str(exc))
        return 1
    print(json_dumps(data) if args.json else json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data.get("ok") else 2


def cmd_quarantine_list(args: argparse.Namespace) -> int:
    args.status = "quarantined"
    return cmd_risk_list(args)


def cmd_quarantine_show(args: argparse.Namespace) -> int:
    args.risk_event_id = args.id
    return cmd_risk_show(args)
