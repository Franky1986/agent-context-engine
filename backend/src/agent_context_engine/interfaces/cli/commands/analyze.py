from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ....application.monitoring.monitor.analysis import (
    build_session_analysis_report_for_selector,
    write_session_analysis_report_html,
)
from ....infrastructure.config import json_dumps, session_short


def _try_open_with_system_command(path: Path) -> bool:
    """Try to open a local file in the system browser using direct commands."""
    uri = path.as_uri()
    command_candidates: list[list[str]] = []

    if sys.platform.startswith("darwin"):
        if shutil.which("open") is not None:
            command_candidates.append(["open", str(path)])
    elif sys.platform.startswith("linux"):
        if shutil.which("xdg-open") is not None:
            command_candidates.append(["xdg-open", uri])
        elif shutil.which("gio") is not None:
            command_candidates.append(["gio", "open", uri])
    elif sys.platform.startswith("win"):
        command_candidates.append(["cmd", "/c", f'start "" "{uri}"'])

    for command in command_candidates:
        executable = command[0].split(" ")[0]
        if executable and " " in executable:
            # Safety for the Windows fallback shell form.
            executable = "cmd"
        if executable and shutil.which(executable) is None and executable != "cmd":
            continue

        try:
            result = subprocess.run(
                command,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3,
            )
            if result.returncode == 0:
                return True
        except Exception:
            continue

    return False


def _open_html_report(path: Path) -> None:
    if os.environ.get("AGENT_MEMORY_NO_REPORT_OPEN") == "1":
        print("HTML report open disabled via AGENT_MEMORY_NO_REPORT_OPEN=1", file=sys.stderr)
        return

    # Use direct command first to avoid noisy osascript failures in headless shells.
    if _try_open_with_system_command(path):
        return

    print(
        "Unable to open HTML report automatically in this environment. "
        f"Open manually: {path.as_posix()}",
        file=sys.stderr,
    )


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        report, session_id = build_session_analysis_report_for_selector(
            args.selector,
            include_entities=args.include_entities,
            include_relations=args.include_relations,
            include_risks=args.include_risks,
            entity_limit=args.entity_limit,
            relation_limit=args.relation_limit,
            relation_offset=args.relation_offset,
            entity_offset=args.entity_offset,
            dream_limit=args.dream_limit,
            risk_limit=args.risk_limit,
            firewall_limit=args.firewall_limit,
        )
    except ValueError as exc:
        print(str(exc))
        return 1

    report_path: Path | None = None
    if args.html:
        report_path = write_session_analysis_report_html(report, session_id)
        if args.open:
            _open_html_report(report_path)

    if args.json:
        print(json_dumps(report))
        if args.html and report_path is not None:
            print(f"html_report_path={report_path}", file=sys.stderr)
        return 0

    print(f"Session: {session_short(session_id)} client={report['session']['client']} project={report['session']['project']}")
    topic = report["topic"]
    print(f"Topic [{topic['source']}]: {topic['value']}")
    print(f"Status: status={report['session']['status']} summary={report['session']['summary_status']} dream={report['session']['dream_status']}")
    print(f"Timeline: events={report['events']['total']} first_seq={report['events']['first_seq']} last_seq={report['events']['last_seq']}")
    print(f"Events: first={report['events']['first_event_at'] or '-'} last={report['events']['last_event_at'] or '-'}")
    if report["events"]["event_counts"]:
        print(f"Event kinds: {', '.join(f'{name}={count}' for name, count in sorted(report['events']['event_counts'].items()))}")
    print(
        f"Tool calls: total={sum(report['events']['tool']['calls_by_status'].values())} outputs={report['events']['tool']['outputs']} file_accesses={report['events']['tool']['file_accesses']}"
    )
    print(
        f"Turns: {report['metrics']['turns']} duration_ms={report['metrics']['duration_ms']} tokens={report['metrics']['total_tokens']} "
        f"(in={report['metrics']['input_tokens']} out={report['metrics']['output_tokens']})"
    )
    print("")
    print(f"Quality score: {report['quality']['score']}")
    if report["quality"]["issues"]:
        print("Quality notes:")
        for item in report["quality"]["issues"]:
            print(f" - {item}")
    print("")
    print("Graph summary:")
    print(f" - entities: {report['entities']['total']} (types={len(report['entities']['types'])})")
    for item in report["entities"]["types"][:8]:
        print(f"   • {item['type']}: count={item['count']} first={item['first_seen_at']} last={item['last_seen_at']}")
    print(f" - relations: {report['relations']['total']} (types={len(report['relations']['types'])})")
    for item in report["relations"]["types"][:8]:
        print(f"   • {item['type']}: count={item['count']} first={item['first_seen_at']} last={item['last_seen_at']}")
    if args.include_entities and report["entities"]["items"]:
        print("Entity sample:")
        for row in report["entities"]["items"][:3]:
            print(
                f"  - {row['type']}:{row['name']} key={row['key']} confidence={row['confidence']} "
                f"evidence={row['evidence_count']} relations={row['relation_count']}"
            )
    if args.include_relations and report["relations"]["items"]:
        print("Relation sample:")
        for row in report["relations"]["items"][:3]:
            print(
                f"  - {row['from_name']} ({row['from_type']}) -[{row['relation_type']}]-> {row['to_name']} ({row['to_type']}) "
                f"evidence={row['evidence_count']}"
            )
    print("")
    print(f"Dream runs: {report['dreams']['count']}")
    for row in report["dreams"]["items"]:
        print(f" - {row['dream_run_id']} runner={row['runner']} status={row['status']} events={row['input_event_count']} started={row['started_at']}")
    print(f"Risk events: {report['risks']['total']} by status={report['risks']['statuses'] or {}}")
    if report["risks"]["items"]:
        print("Latest risk examples:")
        for row in report["risks"]["items"][:3]:
            print(
                f" - {row['risk_event_id']} status={row['status']} decision={row['decision']} "
                f"category={row['categories_json'] or '[]'} at={row['created_at']}"
            )
    print(f"Firewall: {len(report['firewall']['rules_from_session'])} rules created in session, "
          f"{len(report['firewall']['overrides'])} scoped overrides, taint_resets={report['firewall']['session_taint_resets']}")
    for item in report["firewall"]["rules_from_session"][:3]:
        print(f" - {item['name']} [{item['status']}] kind={item['rule_kind']} scope={item['scope_type']} expires={item['expires_at'] or '-'}")
    if report_path is not None:
        print(f"HTML report: {report_path}")
    return 0
