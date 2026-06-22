from __future__ import annotations

import argparse
from datetime import datetime, timezone
from typing import Any

from ....infrastructure.config import json_dumps
from ....infrastructure.db import connect
from ....application.firewall_rules import get_firewall_rule, list_firewall_rules, suggest_firewall_rules


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


def cmd_firewall_suggest(args: argparse.Namespace) -> int:
    conn = connect()
    with conn:
        data = suggest_firewall_rules(
            conn,
            since=args.since,
            until=args.until,
            session_id=args.session,
            workdir=args.workdir,
            host=args.host,
            action=args.action,
            limit=args.limit,
            store=not args.no_store,
        )
    if args.json:
        print(json_dumps(data))
        return 0
    suggestions = data.get("suggestions") or []
    if not suggestions:
        print("No firewall rule suggestions found.")
        return 0
    if data.get("suggestion_id"):
        print(f"suggestion: {data['suggestion_id']}")
    for item in suggestions[:10]:
        print(
            f"{item['count']}x action={item['action']} host={item['host'] or '-'} "
            f"workdir={item['workdir'] or '-'} first={local_time(item['first_seen_at'])} last={local_time(item['last_seen_at'])}"
        )
    if data.get("suggested_command"):
        print("\nCopy, review, edit, then send this as a direct user message to activate:")
        print(data["suggested_command"])
    return 0


def cmd_firewall_list(args: argparse.Namespace) -> int:
    conn = connect()
    rows = list_firewall_rules(conn, status=None if args.all else args.status, limit=args.limit)
    if args.json:
        print(json_dumps(rows))
        return 0
    if not rows:
        print("No firewall rules.")
        return 0
    for row in rows:
        print(
            f"{row['rule_id']} {row['status']} {row['name']} "
            f"scope={row['scope_type']} actions={row['allowed_actions_json']} "
            f"expires={local_time(row['expires_at']) if row['expires_at'] else '-'} "
            f"matches={row.get('match_count', 0)} last={local_time(row.get('last_matched_at')) if row.get('last_matched_at') else '-'}"
        )
    return 0


def cmd_firewall_show(args: argparse.Namespace) -> int:
    conn = connect()
    row = get_firewall_rule(conn, args.rule_id)
    if row is None:
        print(f"Firewall rule not found: {args.rule_id}")
        return 1
    if args.json:
        print(json_dumps(row))
        return 0
    print(f"{row['rule_id']} {row['status']} {row['name']}")
    print(f"reason: {row['reason']}")
    print(f"scope: {row['scope_type']} project={row['project_id'] or '-'} session={row['session_id'] or '-'} workdir={row['workdir_prefix'] or '-'}")
    print(f"actions: {row['allowed_actions_json']}")
    print(f"hosts: {row['allowed_hosts_json']}")
    print(f"local_paths: {row['allowed_local_paths_json']}")
    print(f"remote_paths: {row['allowed_remote_paths_json']}")
    print(f"expires: {local_time(row['expires_at']) if row['expires_at'] else '-'}")
    print("audit:")
    for item in row.get("audit", [])[:20]:
        print(f"- {local_time(item['created_at'])} {item['action']} actor={item['actor']} reason={item['reason'] or '-'}")
    return 0
