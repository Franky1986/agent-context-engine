from __future__ import annotations

import argparse
import errno
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
import time
from pathlib import Path
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from ...infrastructure.config import MEMORY_DIR, ROOT, SKILL_ROOT
from ...application.instance_profile import (
    load_installation_profile,
    merge_installation_profile,
    monitor_restart_command,
    record_monitor_runtime,
    resolve_monitor_profile,
    resolve_storage_profile,
)
from ...application.monitoring.monitor.analysis import build_session_analysis_report_for_selector, write_session_analysis_report_html
from ...application.diagnostics import run_doctor_checks
from ...application.installation import ensure_monitor_frontend_build, frontend_build_status
from ...application.risk_api import risk_review_action
from ...application.system_control import system_admission_open
from .routes.artifact_api import monitor_dream_graph, monitor_graph_artifact_detail
from .routes.ask_api import (
    monitor_ask,
    neo4j_graph,
    runner_model,
    sqlite_graph,
)
from .routes.graph_tables import graph_entities, graph_entity_detail, graph_relation_detail, graph_relations, graph_table_options, graph_type_detail, graph_type_rows
from .html import MONITOR_HTML
from .routes.dream_v2_api import monitor_dream_v2_apply, monitor_dream_v2_evaluate, monitor_dream_v2_fixture_evaluate, monitor_dream_v2_projection_dry_run, monitor_dream_v2_review
from .version import MONITOR_VERSION, PRODUCT_VERSION
from .routes.memory_api import (
    monitor_integrations,
    monitor_installation_check,
    monitor_personal_file,
    monitor_personal_files,
    monitor_reconcile_runtime,
    monitor_repo_index,
    monitor_retrieve,
    monitor_retrieval_run,
    monitor_retrieval_runs,
    monitor_save_personal_file,
    monitor_save_repo_index,
    monitor_search,
    monitor_status,
)
from .request_db import begin_request, close_request
from ...application.monitoring.monitor.risk import (
    monitor_create_firewall_override,
    monitor_firewall_rule,
    monitor_firewall_rule_version,
    monitor_firewall_rules,
    monitor_firewall_suggest,
    monitor_firewall_suggestions,
    monitor_firewall_state,
    monitor_revoke_firewall_override,
    monitor_risk_event,
    monitor_risk_events,
    monitor_set_firewall_state,
)
from ...application.monitoring.monitor.session import (
    elapsed_ms,
    monitor_dream_queue,
    monitor_dreams,
    monitor_filter_options,
    monitor_session_detail,
    monitor_sessions,
    monitor_stats,
    parse_time,
)
from .routes.storage_api import monitor_neo4j_inspect, monitor_storage_inspect
from .openapi import openapi_spec
from .serialization import add_local_time_fields


REPORTS_DIR = Path(MEMORY_DIR) / "analysis_reports"
REPORT_FILE_RE = re.compile(r"^analysis_(?P<session_slug>.+)_(?P<timestamp>\d{8}T\d{6}Z)\.html$")
FRONTEND_DIST_DIR = Path(SKILL_ROOT) / "frontend" / "dist"


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True


def _persist_monitor_runtime_state(
    *,
    host: str,
    port: int,
    runner: str,
    language: str,
    status: str,
    url: str,
    shutdown_token: str = "",
) -> None:
    try:
        profile = load_installation_profile(ROOT)
        instance_id = str(profile.get("instance_id") or ROOT.name)
        storage = resolve_storage_profile(ROOT)
        now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
        monitor_update = {
            "host": host,
            "port": port,
            "language": language,
            "last_seen_at": now_iso,
            "last_known_url": url,
        }
        if status == "running":
            monitor_update.update(
                {
                    "last_started_at": now_iso,
                    "last_started_by": "monitor",
                    "last_known_pid": os.getpid(),
                }
            )
        elif status in {"stopped", "stale"}:
            monitor_update.update(
                {
                    "last_stopped_at": now_iso,
                    "last_known_pid": 0,
                }
            )
        merge_installation_profile(ROOT, monitor=monitor_update)
        record_monitor_runtime(
            instance_id=instance_id,
            installation_root=ROOT,
            memory_root=Path(str(storage.get("memory_root") or ROOT / "memory")),
            configured_host=host,
            configured_port=port,
            active_host=host if status == "running" else "",
            active_port=port if status == "running" else 0,
            pid=os.getpid() if status == "running" else 0,
            status=status,
            runner=runner,
            language=language,
            monitor_version=MONITOR_VERSION,
            product_version=PRODUCT_VERSION,
            started_at=now_iso if status == "running" else "",
            stopped_at=now_iso if status in {"stopped", "stale"} else "",
            last_known_url=url,
            shutdown_token=shutdown_token if status == "running" else "",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"warn  monitor runtime persistence skipped: {exc}")


def _parse_report_filename(filename: str) -> tuple[str, str] | None:
    match = REPORT_FILE_RE.match(filename)
    if not match:
        return None
    session_slug = match.group("session_slug")
    ts = match.group("timestamp")
    try:
        created_at = datetime.strptime(ts, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None
    return session_slug, created_at


def _extract_report_metadata(path: Path, filename: str) -> dict[str, str]:
    session_slug, created_at = ("", "")
    parsed = _parse_report_filename(filename)
    if parsed:
        session_slug, created_at = parsed
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        text = ""
    m_topic = re.search(r"Topic \[[^\]]+\]: ([^<]+)</div>", text)
    m_title = re.search(r"<title>Session(?: Analysis|-Analyse)\s+([^<]+)</title>", text)
    topic = m_topic.group(1).strip() if m_topic else ""
    title_session = m_title.group(1).strip() if m_title else session_slug
    session_label = title_session.replace("Session Analysis ", "").replace("Session-Analyse ", "")
    size = path.stat().st_size if path.exists() else 0
    if session_label:
        session_slug = session_label
    if not created_at:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        created_at = mtime.isoformat().replace("+00:00", "Z")
    return {
        "filename": filename,
        "session_slug": session_slug,
        "created_at": created_at,
        "topic": topic,
        "size_bytes": size,
    }


def _list_reports(limit: int, offset: int, session_filter: str | None = None, query: str | None = None) -> dict[str, Any]:
    if limit <= 0:
        limit = 25
    if offset < 0:
        offset = 0
    reports: list[dict[str, Any]] = []
    if REPORTS_DIR.exists():
        for path in REPORTS_DIR.iterdir():
            if not path.is_file():
                continue
            if path.suffix != ".html":
                continue
            filename = path.name
            if not REPORT_FILE_RE.match(filename):
                continue
            if not filename.startswith("analysis_"):
                continue
            info = _extract_report_metadata(path, filename)
            sf = (session_filter or "").strip().lower()
            if sf and sf not in (info["session_slug"] or "").lower():
                continue
            q = (query or "").strip().lower()
            if q:
                haystack = (info["session_slug"] + " " + info["topic"] + " " + info["filename"]).lower()
                if q not in haystack:
                    continue
            reports.append(info)
    reports.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    total = len(reports)
    page = reports[offset : offset + limit]
    return {"total": total, "offset": offset, "limit": limit, "reports": page}


def _find_report_path(filename: str) -> Path | None:
    if not REPORT_FILE_RE.fullmatch(filename):
        return None
    path = REPORTS_DIR / filename
    if not path.exists() or not path.is_file():
        return None
    return path


def _read_report_file(path: Path) -> bytes:
    return path.read_bytes()


def _frontend_index_path() -> Path | None:
    path = FRONTEND_DIST_DIR / "index.html"
    if path.exists() and path.is_file():
        return path
    return None


def _frontend_asset_path(request_path: str) -> Path | None:
    if not FRONTEND_DIST_DIR.exists():
        return None
    relative = request_path.lstrip("/")
    if not relative or relative.startswith("api/"):
        return None
    candidate = (FRONTEND_DIST_DIR / relative).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST_DIR.resolve())
    except ValueError:
        return None
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _inject_monitor_bootstrap(html: str, token: str, language: str) -> str:
    bootstrap = f"<script>window.MONITOR_TOKEN = {json.dumps(token)}; window.MONITOR_LANGUAGE = {json.dumps(language)};</script>"
    if "</head>" in html:
        return html.replace("</head>", bootstrap + "</head>", 1)
    if "<script" in html:
        return html.replace("<script", bootstrap + "<script", 1)
    return bootstrap + html


def _monitor_query_expansion_mode() -> str:
    mode = (os.environ.get("AGENT_MEMORY_QUERY_EXPANSION_MODE") or "auto").strip().lower()
    if mode in {"auto", "deterministic", "off", "llm"}:
        return mode
    return "auto"


def _coerce_monitor_query_expansion(value: str | None) -> str:
    mode = (value or "").strip().lower()
    if mode in {"auto", "deterministic", "off", "llm"}:
        return mode
    return _monitor_query_expansion_mode()




class MonitorHandler(BaseHTTPRequestHandler):
    server_version = "AgentContextEngineMonitor/0.1"

    @staticmethod
    def _monitor_token_from_headers(headers: Any) -> str:
        return headers.get("x-agent-context-engine-monitor-token", "") or headers.get("x-agent-memory-monitor-token", "")

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    @property
    def monitor_args(self) -> argparse.Namespace:
        return self.server.monitor_args  # type: ignore[attr-defined]

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(add_local_time_fields(value), ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, content: bytes, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_static_file(self, path: Path) -> None:
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        begin_request()
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                token = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                language = qs.get("lang", [getattr(self.monitor_args, "language", "en")])[0]
                language = "de" if language == "de" else "en"
                frontend_index = _frontend_index_path()
                if frontend_index:
                    html = frontend_index.read_text(encoding="utf-8")
                    body = _inject_monitor_bootstrap(html, token, language).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                    self.send_header("Pragma", "no-cache")
                    self.send_header("Expires", "0")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                html = MONITOR_HTML.replace("__DEFAULT_MONITOR_LANG__", language)
                html = html.replace("<script>", f"<script>window.MONITOR_TOKEN = {json.dumps(token)};\n", 1)
                body = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/openapi.json":
                self.send_json(openapi_spec())
                return
            frontend_asset = _frontend_asset_path(parsed.path)
            if frontend_asset:
                self.send_static_file(frontend_asset)
                return
            if parsed.path == "/api/status":
                self.send_json(
                    monitor_status(
                        self.monitor_args.runner,
                        monitor_context={
                            "pid": os.getpid(),
                            "argv": sys.argv,
                            "host": self.monitor_args.host,
                            "port": int(self.monitor_args.port),
                            "language": getattr(self.monitor_args, "language", "en"),
                            "started_at_epoch": float(getattr(self.server, "monitor_started_at_epoch", time.time())),
                        },
                    )
                )
                return
            if parsed.path == "/api/integrations":
                self.send_json(monitor_integrations())
                return
            if parsed.path == "/api/installation-check":
                self.send_json(monitor_installation_check())
                return
            if parsed.path == "/api/diagnostics":
                lines, exit_code = run_doctor_checks(
                    check_codex_features=qs.get("codex_features", [""])[0] in {"1", "true", "yes"},
                    relocation_report_requested=qs.get("relocation", [""])[0] in {"1", "true", "yes"},
                )
                self.send_json({"ok": exit_code == 0, "exit_code": exit_code, "lines": lines})
                return
            if parsed.path == "/api/storage":
                self.send_json(monitor_storage_inspect())
                return
            if parsed.path == "/api/storage/neo4j":
                self.send_json(monitor_neo4j_inspect(self.monitor_args))
                return
            if parsed.path == "/api/search":
                self.send_json(monitor_search(qs.get("q", [""])[0], int(qs.get("limit", ["10"])[0])))
                return
            if parsed.path == "/api/retrieve":
                if not system_admission_open(installation_root=ROOT):
                    self.send_json(
                        {
                            "error": "Agent Context Engine is suspended; LLM-backed retrieval is unavailable.",
                            "error_code": "system_suspended",
                            "status_path": "/api/status",
                        },
                        423,
                    )
                    return
                self.send_json(
                    monitor_retrieve(
                        qs.get("q", [""])[0],
                        int(qs.get("limit", ["10"])[0]),
                        kind=qs.get("kind", [""])[0] or None,
                        include_risky=qs.get("include_risky", [""])[0] in {"1", "true", "yes"},
                        expansion_mode=_coerce_monitor_query_expansion(qs.get("query_expansion", [None])[0]),
                        runner=self.monitor_args.runner,
                        runner_model_value=self.monitor_args.runner_model,
                        runner_timeout=self.monitor_args.runner_timeout,
                    )
                )
                return
            if parsed.path == "/api/retrieval-runs":
                self.send_json(monitor_retrieval_runs(int(qs.get("limit", ["30"])[0])))
                return
            if parsed.path == "/api/retrieval-run":
                self.send_json(monitor_retrieval_run(qs.get("id", [""])[0]))
                return
            if parsed.path == "/api/personal":
                self.send_json(monitor_personal_files())
                return
            if parsed.path == "/api/personal-file":
                self.send_json(monitor_personal_file(qs.get("path", [""])[0]))
                return
            if parsed.path == "/api/repo-index":
                self.send_json(monitor_repo_index())
                return
            if parsed.path == "/api/dreams":
                self.send_json(
                    monitor_dreams(
                        int(qs.get("limit", ["25"])[0]),
                        status=qs.get("status", [""])[0] or None,
                        runner=qs.get("runner", [""])[0] or None,
                        session_id=qs.get("session", [""])[0] or None,
                    )
                )
                return
            if parsed.path == "/api/dream-queue":
                self.send_json(
                    monitor_dream_queue(
                        int(qs.get("limit", ["25"])[0]),
                        status=qs.get("status", [""])[0] or None,
                        session_id=qs.get("session", [""])[0] or None,
                    )
                )
                return
            if parsed.path == "/api/dream-v2-evaluate":
                self.send_json(monitor_dream_v2_evaluate(int(qs.get("limit", ["20"])[0])))
                return
            if parsed.path == "/api/sessions":
                self.send_json(
                    monitor_sessions(
                        limit=int(qs.get("limit", ["25"])[0]),
                        offset=int(qs.get("offset", ["0"])[0]),
                        query=qs.get("q", [""])[0] or None,
                        client_type=qs.get("client", [""])[0] or None,
                        project_id=qs.get("project", [""])[0] or None,
                        workdir=qs.get("workdir", [""])[0] or None,
                        kind=qs.get("kind", [""])[0] or None,
                    )
                )
                return
            if parsed.path == "/api/session":
                include = qs.get("include", [None])[0] if "include" in qs else None
                self.send_json(
                    monitor_session_detail(
                        qs.get("id", [""])[0],
                        event_limit=int(qs.get("event_limit", ["200"])[0]),
                        event_offset=int(qs.get("event_offset", ["0"])[0]),
                        include=include,
                    )
                )
                return
            if parsed.path == "/api/graph-artifact":
                self.send_json(monitor_graph_artifact_detail(qs.get("id", [""])[0]))
                return
            if parsed.path == "/api/dream-graph":
                self.send_json(monitor_dream_graph(qs.get("dream_run_id", [""])[0]))
                return
            if parsed.path == "/api/graph-table-options":
                self.send_json(graph_table_options())
                return
            if parsed.path == "/api/graph-types":
                self.send_json(
                    graph_type_rows(
                        limit=int(qs.get("limit", ["50"])[0]),
                        offset=int(qs.get("offset", ["0"])[0]),
                        query=qs.get("q", [""])[0] or None,
                        kind=qs.get("kind", [""])[0] or None,
                    )
                )
                return
            if parsed.path == "/api/graph-type":
                self.send_json(
                    graph_type_detail(
                        qs.get("kind", [""])[0],
                        qs.get("name", [""])[0],
                        limit=int(qs.get("limit", ["100"])[0]),
                    )
                )
                return
            if parsed.path == "/api/graph-entity":
                self.send_json(graph_entity_detail(qs.get("id", [""])[0], memory_view=qs.get("memory_view", ["both"])[0]))
                return
            if parsed.path == "/api/graph-relation":
                self.send_json(graph_relation_detail(qs.get("id", [""])[0], memory_view=qs.get("memory_view", ["both"])[0]))
                return
            if parsed.path == "/api/graph-entities":
                self.send_json(
                    graph_entities(
                        limit=int(qs.get("limit", ["50"])[0]),
                        offset=int(qs.get("offset", ["0"])[0]),
                        query=qs.get("q", [""])[0] or None,
                        entity_type=qs.get("type", [""])[0] or None,
                        memory_view=qs.get("memory_view", ["both"])[0],
                        sort=qs.get("sort", ["last_seen_at"])[0],
                        direction=qs.get("dir", ["desc"])[0],
                    )
                )
                return
            if parsed.path == "/api/graph-relations":
                self.send_json(
                    graph_relations(
                        limit=int(qs.get("limit", ["50"])[0]),
                        offset=int(qs.get("offset", ["0"])[0]),
                        query=qs.get("q", [""])[0] or None,
                        relation_type=qs.get("type", [""])[0] or None,
                        memory_view=qs.get("memory_view", ["both"])[0],
                        sort=qs.get("sort", ["last_seen_at"])[0],
                        direction=qs.get("dir", ["desc"])[0],
                    )
                )
                return
            if parsed.path == "/api/reports":
                self.send_json(
                    _list_reports(
                        limit=int(qs.get("limit", ["25"])[0]),
                        offset=int(qs.get("offset", ["0"])[0]),
                        session_filter=qs.get("session", [""])[0] or None,
                        query=qs.get("q", [""])[0] or None,
                    )
                )
                return
            if parsed.path == "/api/report-file":
                filename = qs.get("filename", [""])[0]
                path = _find_report_path(filename)
                if not path:
                    self.send_json({"error": "report not found"}, 404)
                    return
                self.send_html(_read_report_file(path))
                return
            if parsed.path == "/api/filter-options":
                self.send_json(monitor_filter_options())
                return
            if parsed.path == "/api/stats":
                self.send_json(
                    monitor_stats(
                        range_name=qs.get("range", ["2d"])[0],
                        start=qs.get("start", [""])[0] or None,
                        end=qs.get("end", [""])[0] or None,
                        client_type=qs.get("client", [""])[0] or None,
                        project_id=qs.get("project", [""])[0] or None,
                        workdir=qs.get("workdir", [""])[0] or None,
                    )
                )
                return
            if parsed.path in {"/api/risk-events", "/api/risks"}:
                self.send_json(
                    monitor_risk_events(
                        limit=int(qs.get("limit", ["100"])[0]),
                        status=qs.get("status", [""])[0] or None,
                        client_type=qs.get("client", [""])[0] or None,
                        category=qs.get("category", [""])[0] or None,
                    )
                )
                return
            if parsed.path == "/api/firewall-state":
                self.send_json(monitor_firewall_state())
                return
            if parsed.path == "/api/firewall-rules":
                self.send_json(
                    monitor_firewall_rules(
                        status=qs.get("status", [""])[0] or None,
                        rule_kind=qs.get("kind", [""])[0] or None,
                        limit=int(qs.get("limit", ["100"])[0]),
                    )
                )
                return
            if parsed.path == "/api/firewall-rule":
                self.send_json(monitor_firewall_rule(qs.get("id", [""])[0]))
                return
            if parsed.path == "/api/firewall-suggestions":
                self.send_json(monitor_firewall_suggestions(limit=int(qs.get("limit", ["20"])[0])))
                return
            if parsed.path in {"/api/risk-event", "/api/risk"}:
                self.send_json(monitor_risk_event(qs.get("id", [""])[0], include_raw=qs.get("raw", [""])[0] in {"1", "true", "yes"}))
                return
            if parsed.path == "/api/graph":
                query = qs.get("q", [""])[0]
                view = qs.get("view", ["search"])[0]
                source = qs.get("source", ["sqlite"])[0]
                limit = int(qs.get("limit", ["80"])[0])
                memory_view = qs.get("memory_view", ["both"])[0]
                self.send_json(neo4j_graph(query, view, limit, self.monitor_args) if source == "neo4j" else sqlite_graph(query, view, limit, memory_view=memory_view))
                return
            self.send_json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, 500)
        finally:
            close_request()

    def do_POST(self) -> None:
        begin_request()
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            if self.path == "/api/runtime/shutdown":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json({"status": "stopping"}, 202)
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if not system_admission_open(installation_root=ROOT):
                self.send_json(
                    {
                        "error": "Agent Context Engine is suspended; the monitor is read-only.",
                        "error_code": "system_suspended",
                        "status_path": "/api/status",
                    },
                    423,
                )
                return
            payload = json.loads(raw) if raw else {}
            if self.path == "/api/analyze-session":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                selector = str(payload.get("selector") or payload.get("session_id") or "").strip()
                if not selector:
                    self.send_json({"error": "selector is required"}, 400)
                    return

                def _int_arg(name: str, default: int) -> int:
                    try:
                        return int(payload.get(name, default))
                    except (TypeError, ValueError):
                        return default

                report, session_id = build_session_analysis_report_for_selector(
                    selector,
                    include_entities=bool(payload.get("include_entities", True)),
                    include_relations=bool(payload.get("include_relations", True)),
                    include_risks=bool(payload.get("include_risks", True)),
                    entity_limit=_int_arg("entity_limit", 0),
                    entity_offset=_int_arg("entity_offset", 0),
                    relation_limit=_int_arg("relation_limit", 0),
                    relation_offset=_int_arg("relation_offset", 0),
                    dream_limit=_int_arg("dream_limit", 5),
                    risk_limit=_int_arg("risk_limit", 10),
                    firewall_limit=_int_arg("firewall_limit", 20),
                )
                path = write_session_analysis_report_html(report, session_id)
                self.send_json(
                    {
                        "ok": True,
                        "session_id": session_id,
                        "filename": path.name,
                        "report_url": f"/api/report-file?filename={urllib.parse.quote(path.name)}",
                        "entities_total": report["entities"]["total"],
                        "relations_total": report["relations"]["total"],
                        "risks_total": report["risks"]["total"],
                        "dreams_total": report["dreams"]["count"],
                    }
                )
                return
            if self.path == "/api/ask":
                question = str(payload.get("question") or "")
                self.send_json(
                    monitor_ask(
                        question,
                        self.monitor_args,
                        query_expansion_mode=_coerce_monitor_query_expansion(None),
                    )
                )
                return
            if self.path == "/api/risk-review":
                self.send_json(
                    risk_review_action(
                        str(payload.get("id") or ""),
                        action=str(payload.get("action") or ""),
                        reason=str(payload.get("reason") or ""),
                        reviewer=str(payload.get("reviewer") or "monitor"),
                        force=bool(payload.get("force")),
                    )
                )
                return
            if self.path == "/api/dream-v2-review":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json({"status": "ok", "result": monitor_dream_v2_review(payload)})
                return
            if self.path == "/api/dream-v2-apply":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json({"status": "ok", "result": monitor_dream_v2_apply(payload)})
                return
            if self.path == "/api/dream-v2-projection-dry-run":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json({"status": "ok", "result": monitor_dream_v2_projection_dry_run()})
                return
            if self.path == "/api/dream-v2-fixture-evaluate":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json({"status": "ok", "result": monitor_dream_v2_fixture_evaluate(payload)})
                return
            if self.path == "/api/firewall-state":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                if not bool(payload.get("enabled")):
                    self.send_json(
                        {
                            "error": (
                                "Disabling the firewall is not available through the monitor API. "
                                "Use a direct user chat control line such as `firewall disable session 30m` instead."
                            ),
                            "error_code": "firewallDisableProtected",
                        },
                        403,
                    )
                    return
                self.send_json(
                    monitor_set_firewall_state(
                        enabled=bool(payload.get("enabled")),
                        actor=str(payload.get("actor") or "monitor"),
                        reason=str(payload.get("reason") or ""),
                        disabled_minutes=int(payload.get("disabled_minutes") or 30),
                        permanent_disable=bool(payload.get("permanent_disable")),
                    )
                )
                return
            if self.path == "/api/personal-file":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json(
                    monitor_save_personal_file(
                        str(payload.get("path") or ""),
                        str(payload.get("content") or ""),
                    )
                )
                return
            if self.path == "/api/repo-index":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token"}, 403)
                    return
                self.send_json(monitor_save_repo_index(str(payload.get("content") or "")))
                return
            if self.path == "/api/integrations-hooks":
                self.send_json(
                    {
                        "error": (
                            "Changing Agent Context Engine hooks is not available through the monitor API. "
                            "Use a direct user chat control line such as `hooks-disable --runner opencode` "
                            "or `hooks-enable --runner opencode` for control-plane changes."
                        ),
                        "error_code": "integrationHooksProtected",
                    },
                    403,
                )
                return
            if self.path == "/api/runtime/reconcile":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json({"status": "ok", "result": monitor_reconcile_runtime()})
                return
            if self.path == "/api/firewall-override":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json(
                    {
                        "error": (
                            "Creating firewall overrides is not available through the monitor API. "
                            "Use a direct user chat control line such as `firewall disable session 30m` instead."
                        ),
                        "error_code": "firewallOverrideCreateProtected",
                    },
                    403,
                )
                return
            if self.path == "/api/firewall-suggest":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json(monitor_firewall_suggest(payload))
                return
            if self.path == "/api/firewall-rule-version":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token"}, 403)
                    return
                self.send_json(monitor_firewall_rule_version(payload))
                return
            self.send_json({"error": "not found"}, 404)
        except PermissionError as exc:
            self.send_json({"error": str(exc), "answer": f"Error: {exc}"}, 409)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc), "answer": f"Error: {exc}"}, 500)
        finally:
            close_request()

    def do_DELETE(self) -> None:
        begin_request()
        length = int(self.headers.get("content-length", "0"))
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        try:
            if not system_admission_open(installation_root=ROOT):
                self.send_json(
                    {
                        "error": "Agent Context Engine is suspended; the monitor is read-only.",
                        "error_code": "system_suspended",
                        "status_path": "/api/status",
                    },
                    423,
                )
                return
            payload = json.loads(raw) if raw else {}
            if self.path == "/api/firewall-override":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token", "error_code": "invalidMonitorToken"}, 403)
                    return
                self.send_json(
                    {
                        "error": (
                            "Revoking firewall overrides is not available through the monitor API. "
                            "Use a direct user chat control line such as `firewall enable session` instead."
                        ),
                        "error_code": "firewallOverrideRevokeProtected",
                    },
                    403,
                )
                return
            if self.path == "/api/firewall-rule":
                token = self._monitor_token_from_headers(self.headers)
                expected = getattr(self.server, "monitor_token", "")  # type: ignore[attr-defined]
                if not expected or not secrets.compare_digest(token, expected):
                    self.send_json({"error": "invalid monitor token"}, 403)
                    return
                self.send_json(
                    {
                        "error": (
                            "Disabling firewall rules is not available through the monitor API. "
                            "Use a direct user chat control line or reviewed firewall versioning instead."
                        ),
                        "error_code": "firewallRuleDisableProtected",
                    },
                    403,
                )
                return
            self.send_json({"error": "not found"}, 404)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc), "answer": f"Error: {exc}"}, 500)
        finally:
            close_request()


def cmd_monitor(args: argparse.Namespace) -> int:
    if not getattr(args, "runner", None):
        profile = resolve_monitor_profile(ROOT)
        restart_command = monitor_restart_command(ROOT)
        print("# Monitor")
        print("")
        print("Starts the local Agent Context Engine monitor.")
        print("")
        print("Use:")
        print(f"- `{restart_command}`")
        print(f"- URL after start: `http://{profile['host']}:{profile['port']}/?lang={profile['language']}`")
        return 0
    if args.runner not in {"codex", "claude", "cursor", "antigravity", "gemini", "opencode"}:
        print("--runner must be one of: codex, claude, cursor, antigravity, gemini, opencode")
        return 1
    frontend_status = frontend_build_status(ROOT)
    try:
        for action in ensure_monitor_frontend_build(
            ROOT,
            install_dependencies=bool(getattr(args, "install_frontend_deps", False)),
            force=bool(frontend_status.get("needs_build")),
        ):
            print(f"monitor prep: {action}")
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"warn  monitor frontend: {exc}")
    host = args.host
    port = int(args.port)
    server: ReusableThreadingHTTPServer | None = None
    attempts = 4 if args.replace_existing else 1
    for attempt in range(attempts):
        if args.replace_existing:
            replace_existing_monitor_port(host, port)
        try:
            server = ReusableThreadingHTTPServer((host, port), MonitorHandler)
            break
        except OSError as exc:
            if exc.errno != errno.EADDRINUSE or not args.replace_existing or attempt >= attempts - 1:
                print(f"cannot start agent-context-engine monitor on {host}:{port}: {exc}")
                return 1
            time.sleep(0.35)
    if server is None:
        print(f"cannot start agent-context-engine monitor on {host}:{port}")
        return 1
    server.monitor_args = args  # type: ignore[attr-defined]
    server.monitor_token = secrets.token_urlsafe(24)  # type: ignore[attr-defined]
    server.monitor_started_at_epoch = time.time()  # type: ignore[attr-defined]
    language = getattr(args, "language", "en")
    language = "de" if language == "de" else "en"
    url = f"http://{host}:{args.port}/?runner={urllib.parse.quote(args.runner)}&lang={urllib.parse.quote(language)}"
    _persist_monitor_runtime_state(
        host=host,
        port=port,
        runner=args.runner,
        language=language,
        status="running",
        url=url,
        shutdown_token=server.monitor_token,  # type: ignore[attr-defined]
    )
    print(f"agent-context-engine monitor {MONITOR_VERSION}: {url}")
    print(f"runner={args.runner} model={runner_model(args.runner, args.runner_model) or '-'} root={ROOT}")
    if args.open:
        threading.Timer(0.2, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        try:
            _persist_monitor_runtime_state(
                host=host,
                port=port,
                runner=args.runner,
                language=language,
                status="stopped",
                url=url,
            )
        except Exception:  # noqa: BLE001
            pass
        try:
            server.server_close()
        except Exception:  # noqa: BLE001
            pass
    return 0


def replace_existing_monitor_port(host: str, port: int) -> None:
    if host not in {"", "0.0.0.0", "127.0.0.1", "localhost", "::", "::1"}:
        return
    def _normalize_host(target_host: str) -> str:
        return "localhost" if target_host in {"127.0.0.1", "localhost", "::1"} else target_host

    lsof = shutil.which("lsof")
    if lsof:
        proc = subprocess.run(
            [lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            text=True,
            capture_output=True,
            timeout=3,
            check=False,
        )
    else:
        proc = None

    pids: set[int] = set()
    if proc and proc.stdout:
        pids.update(int(line) for line in proc.stdout.splitlines() if line.strip().isdigit())

    if not pids:
        ss = shutil.which("ss")
        if ss:
            list_proc = subprocess.run(
                [ss, "-ltnp"],
                text=True,
                capture_output=True,
                timeout=3,
                check=False,
            )
            for line in list_proc.stdout.splitlines():
                if f":{port}" not in line:
                    continue
                match = re.search(r"pid=([0-9]+)", line)
                if match:
                    try:
                        pids.add(int(match.group(1)))
                    except ValueError:
                        continue

    if not pids:
        return

    pids_list = sorted(pid for pid in pids if pid != os.getpid())
    if not pids_list:
        return
    host_label = _normalize_host(host)
    print(f"replacing existing listener on {host_label}:{port}: pids={','.join(str(pid) for pid in pids_list)}")
    for pid in pids_list:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"cannot replace listener pid={pid}: permission denied")
    deadline = time.time() + 2.0
    remaining = set(pids_list)
    while remaining and time.time() < deadline:
        for pid in list(remaining):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                remaining.discard(pid)
            except PermissionError:
                print(f"cannot verify listener pid={pid}: permission denied")
                remaining.discard(pid)
        if remaining:
            time.sleep(0.1)
    for pid in remaining:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"cannot force-replace listener pid={pid}: permission denied")
