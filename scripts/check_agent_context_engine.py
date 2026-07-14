#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]


def default_root_for_skill(skill_root: Path) -> Path:
    if skill_root.name in {"agent-memory", "agent-context-engine"} and skill_root.parent.name == "skills" and skill_root.parent.parent.name == "docs":
        return skill_root.parents[2]
    return skill_root


REPO_ROOT = default_root_for_skill(SKILL_ROOT)
AGENT_MEMORY = SKILL_ROOT / "scripts" / "agent-context-engine"
TEST_FILE = SKILL_ROOT / "tests" / "test_agent_context_engine.py"
EVAL_FILE = SKILL_ROOT / "evals" / "retrieval-core-questions.json"
PACKAGE_ROOT = SKILL_ROOT / "backend" / "src" / "agent_context_engine"
MONITORING_CONTRACT_DOC = REPO_ROOT / "docs" / "progress" / "2026-06-04-wave4g-monitoring-html-dto-contract.md"


def _resolved_memory_root() -> Path:
    path = REPO_ROOT / "memory" / "local" / "installation-profile.json"
    if not path.exists():
        return REPO_ROOT / ".agent-context-engine" / "instances" / "default" / "memory"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return REPO_ROOT / ".agent-context-engine" / "instances" / "default" / "memory"
    storage = payload.get("storage")
    if not isinstance(storage, dict):
        return REPO_ROOT / ".agent-context-engine" / "instances" / "default" / "memory"
    memory_root = str(storage.get("memory_root") or "").strip()
    if not memory_root:
        return REPO_ROOT / ".agent-context-engine" / "instances" / "default" / "memory"
    candidate = Path(memory_root).expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate.resolve()


DB_PATH = _resolved_memory_root() / "status" / "agent-memory.sqlite3"


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def run_command(name: str, command: list[str], *, timeout: int = 120, env: dict[str, str] | None = None) -> CheckResult:
    command_env = {**os.environ, **(env or {})}
    command_env["AGENT_MEMORY_TEST_SKIP_MONITOR_OPEN"] = "1"
    proc = subprocess.run(
        command,
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
        env=command_env,
    )
    output = "\n".join(part for part in [proc.stdout.strip(), proc.stderr.strip()] if part)
    if len(output) > 4000:
        output = output[:4000].rstrip() + "\n... output truncated ..."
    return CheckResult(name, proc.returncode == 0, output)


def python_files() -> list[str]:
    paths = [
        path
        for root in (SKILL_ROOT / "backend" / "src", SKILL_ROOT / "scripts")
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    return [str(path) for path in paths]


def check_import_audit() -> CheckResult:
    legacy_modules = {
        "agent_context_engine.commands",
        "agent_context_engine.classifier",
        "agent_context_engine.file_access",
        "agent_context_engine.neo4j_sync",
        "agent_context_engine.personal",
        "agent_context_engine.query_expansion",
        "agent_context_engine.retrieval",
        "agent_context_engine.risk",
        "agent_context_engine.schema_proposals",
        "agent_context_engine.summaries",
        "agent_context_engine.toolrefs",
    }
    legacy_root_names = {module.rsplit(".", 1)[1] for module in legacy_modules}
    hits: list[str] = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")) + [SKILL_ROOT / "scripts" / "agent_context_engine.py", TEST_FILE]:
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in legacy_modules:
                        hits.append(f"{path.relative_to(REPO_ROOT)}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if node.level == 0 and module in legacy_modules:
                    hits.append(f"{path.relative_to(REPO_ROOT)}: from {module} import ...")
                if node.level == 1 and path.parent == PACKAGE_ROOT and module in legacy_root_names:
                    hits.append(f"{path.relative_to(REPO_ROOT)}: relative legacy import {'.' * node.level}{module}")
                elif node.level == 2 and path.parent.parent == PACKAGE_ROOT and module in legacy_root_names:
                    hits.append(f"{path.relative_to(REPO_ROOT)}: relative legacy import {'.' * node.level}{module}")
    if hits:
        return CheckResult("import-audit", False, "\n".join(hits))
    return CheckResult("import-audit", True, "no legacy root imports found")


def check_retrieval_evals() -> CheckResult:
    if not EVAL_FILE.exists():
        return CheckResult("retrieval-evals", True, "no eval file present")
    spec = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
    failures: list[str] = []
    for item in spec.get("questions", []):
        query = str(item.get("query") or "")
        expected_terms = [str(term) for term in item.get("expected_terms") or []]
        proc = subprocess.run(
            [str(AGENT_MEMORY), "retrieve", query, "--limit", "5", "--chars", "500", "--json"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        haystack = f"{proc.stdout}\n{proc.stderr}"
        if proc.returncode != 0:
            failures.append(f"{item.get('id')}: retrieve exited {proc.returncode}: {proc.stderr.strip()[:300]}")
            continue
        if not any(term in haystack for term in expected_terms):
            failures.append(f"{item.get('id')}: expected one of {expected_terms!r}")
    if failures:
        return CheckResult("retrieval-evals", False, "\n".join(failures))
    return CheckResult("retrieval-evals", True, f"{len(spec.get('questions', []))} retrieval questions passed")


def _collect_contract_sections(contract_text: str) -> dict[str, dict[str, list[str] | None]]:
    sections: dict[str, dict[str, list[str] | None]] = {}
    current: str | None = None
    for raw_line in contract_text.splitlines():
        line = raw_line.strip()
        header = re.match(r"^### `(/api/[A-Za-z0-9_\\-]+)`", line)
        if header:
            current = header.group(1)
            sections[current] = {"ui_fields": None, "producer_fields": None}
            continue
        if line.startswith("### "):
            current = None
            continue
        if not current:
            continue
        if re.match(r"^-\s*UI:", line):
            fields = [item.strip() for item in re.findall(r"`([^`]+)`", line.split(":", 1)[1]) if item.strip()]
            sections[current]["ui_fields"] = fields
            continue
        if re.match(r"^-\s*Producer", line):
            fields = [item.strip() for item in re.findall(r"`([^`]+)`", line.split(":", 1)[1]) if item.strip()]
            sections[current]["producer_fields"] = fields
            continue
    return sections


def check_monitoring_contract_gate() -> CheckResult:
    if not MONITORING_CONTRACT_DOC.exists():
        return CheckResult(
            "monitoring-contract-gate",
            False,
            f"missing doc: {MONITORING_CONTRACT_DOC.relative_to(REPO_ROOT)}",
        )
    contract_text = MONITORING_CONTRACT_DOC.read_text(encoding="utf-8")
    sections = _collect_contract_sections(contract_text)
    contract_endpoints = sorted(sections.keys())
    server_text = (PACKAGE_ROOT / "interfaces" / "http" / "server.py").read_text(encoding="utf-8")
    server_routes = sorted(
        {
            path
            for path in re.findall(r"(?:parsed|self)\.path == \"([^\"]+)\"", server_text)
            if path.startswith("/api/")
        }
        | {
            path
            for group in re.findall(r"(?:parsed|self)\.path in \{([^}]+)\}", server_text)
            for path in re.findall(r"\"([^\"]+)\"", group)
            if path.startswith("/api/")
        }
    )
    missing = [endpoint for endpoint in contract_endpoints if endpoint not in server_routes]
    if missing:
        return CheckResult(
            "monitoring-contract-gate",
            False,
            "Missing server routes for contract endpoints:\n" + "\n".join(f"  - {item}" for item in missing),
        )
    shape_violations: list[str] = []
    for endpoint in contract_endpoints:
        section = sections.get(endpoint)
        if not section:
            shape_violations.append(f"{endpoint}: missing endpoint subsection (### `{endpoint}`)")
            continue
        if not section["ui_fields"]:
            shape_violations.append(f"{endpoint}: missing UI field list in contract section")
        if not section["producer_fields"]:
            shape_violations.append(f"{endpoint}: missing Producer field list in contract section")
    if shape_violations:
        return CheckResult(
            "monitoring-contract-gate",
            False,
            "Monitoring contract payload coverage incomplete:\n" + "\n".join(f"  - {item}" for item in shape_violations),
        )
    return CheckResult(
        "monitoring-contract-gate",
        True,
        f"monitoring contract routes covered: {len(contract_endpoints)} endpoint(s); payload sections complete",
    )


def check_docs_spec_index() -> CheckResult:
    return run_command(
        "docs-spec-index",
        [sys.executable, str(SKILL_ROOT / "scripts" / "update_docs_index.py"), "--check"],
        timeout=30,
    )


def check_test_coverage_matrix() -> CheckResult:
    text = TEST_FILE.read_text(encoding="utf-8")
    tests = re.findall(r"def (test_[A-Za-z0-9_]+)\(", text)
    required = {
        "session-management": ["session", "startup_hint", "folder_search", "resume"],
        "hook-ingestion": ["hook", "pretool", "tool"],
        "dream-process": ["dream"],
        "graph-entities-relations": ["graph", "entity", "relation", "neo4j"],
        "firewall-risk": ["firewall", "risk", "approval", "taint"],
        "retrieval-memory": ["retriev", "indexing"],
        "monitor-api": ["monitor"],
        "runner-adapters": ["codex", "claude", "cursor"],
        "schema-proposals": ["schema_proposal"],
    }
    lines: list[str] = []
    missing: list[str] = []
    for area, terms in required.items():
        matched = [name for name in tests if any(term in name for term in terms)]
        if not matched:
            missing.append(area)
        lines.append(f"{area}: {len(matched)} tests")
        for name in matched[:6]:
            lines.append(f"  - {name}")
        if len(matched) > 6:
            lines.append(f"  - ... {len(matched) - 6} more")
    if missing:
        return CheckResult("coverage-matrix", False, "missing areas: " + ", ".join(missing) + "\n" + "\n".join(lines))
    return CheckResult("coverage-matrix", True, "\n".join(lines))


def _table_count(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f"select count(*) as count from {table}").fetchone()
    return int(row["count"] or 0)


def check_runtime_db_health() -> CheckResult:
    if not DB_PATH.exists():
        return CheckResult("runtime-db-health", False, f"missing sqlite db: {DB_PATH.relative_to(REPO_ROOT)}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    required_tables = [
        "sessions",
        "events",
        "dream_runs",
        "graph_entities",
        "graph_relations",
        "graph_evidence",
        "graph_artifacts",
        "risk_events",
        "firewall_state",
        "retrieval_runs",
    ]
    try:
        existing = {row["name"] for row in conn.execute("select name from sqlite_master where type='table'")}
        missing = [table for table in required_tables if table not in existing]
        if missing:
            return CheckResult("runtime-db-health", False, "missing tables: " + ", ".join(missing))
        counts = {table: _table_count(conn, table) for table in required_tables}
        latest_valid_graph = conn.execute(
            """
            select graph_artifact_id, artifact_type, status, entity_count, relation_count, evidence_count, created_at
            from graph_artifacts
            where status = 'valid'
            order by created_at desc
            limit 1
            """
        ).fetchone()
        latest_dream = conn.execute(
            """
            select dream_run_id, status, input_event_count, started_at, finished_at
            from dream_runs
            order by started_at desc
            limit 1
            """
        ).fetchone()
        checks = {
            "sessions": counts["sessions"] > 0,
            "events": counts["events"] > 0,
            "dream_runs": counts["dream_runs"] > 0,
            "graph_entities": counts["graph_entities"] > 0,
            "graph_relations": counts["graph_relations"] > 0,
            "graph_evidence": counts["graph_evidence"] > 0,
            "valid_graph_artifact": latest_valid_graph is not None,
        }
        failed = [name for name, ok in checks.items() if not ok]
        lines = [f"{table}: {count}" for table, count in counts.items()]
        if latest_dream:
            lines.append(
                "latest_dream: "
                f"{latest_dream['dream_run_id']} status={latest_dream['status']} events={latest_dream['input_event_count']}"
            )
        if latest_valid_graph:
            lines.append(
                "latest_valid_graph: "
                f"{latest_valid_graph['graph_artifact_id']} type={latest_valid_graph['artifact_type']} "
                f"entities={latest_valid_graph['entity_count']} relations={latest_valid_graph['relation_count']} evidence={latest_valid_graph['evidence_count']}"
            )
        if failed:
            return CheckResult("runtime-db-health", False, "failed checks: " + ", ".join(failed) + "\n" + "\n".join(lines))
        return CheckResult("runtime-db-health", True, "\n".join(lines))
    finally:
        conn.close()


def current_root_runtime_initialized() -> bool:
    installed_markers = [
        REPO_ROOT / ".codex" / "hooks.json",
        REPO_ROOT / ".claude" / "settings.json",
        REPO_ROOT / ".agents" / "hooks.json",
        REPO_ROOT / ".gemini" / "settings.json",
        REPO_ROOT / "memory" / "knowledge" / "repos.md",
        REPO_ROOT / "docs" / "knowledge" / "repos.md",
        REPO_ROOT / "memory" / "local" / "installation-profile.json",
    ]
    return any(path.exists() for path in installed_markers)


def check_runtime_cli(name: str, command: list[str]) -> CheckResult:
    if not current_root_runtime_initialized():
        return CheckResult(name, True, "skipped: current root has no local runtime installation")
    return run_command(name, command)


def check_openapi_generation() -> CheckResult:
    command = [sys.executable, str(SKILL_ROOT / "scripts" / "generate_openapi.py"), "--check"]
    result = run_command("openapi-generation", command, timeout=60)
    if result.ok:
        return result
    if "No module named 'yaml'" in result.detail:
        venv_python = REPO_ROOT / ".venv" / "bin" / "python"
        if venv_python.exists():
            return run_command("openapi-generation", [str(venv_python), str(SKILL_ROOT / "scripts" / "generate_openapi.py"), "--check"], timeout=60)
        return CheckResult(
            "openapi-generation",
            True,
            "skipped: PyYAML is not installed in the current shell environment; rerun after `install --bootstrap-runtime` or inside `.venv`",
        )
    return result


def check_fresh_install_smoke() -> CheckResult:
    with tempfile.TemporaryDirectory(prefix="agent-memory-install-") as tmp:
        target = Path(tmp) / "target"
        link_dir = Path(tmp) / "bin"
        home_root = Path(tmp) / "home"
        instance_name = "smoke"
        memory_root = home_root / ".agent-context-engine" / "memory"
        env = os.environ.copy()
        env["HOME"] = str(home_root)
        env.setdefault("AGENT_MEMORY_TEST_SKIP_FRONTEND_BUILD", "1")
        env.setdefault("AGENT_MEMORY_TEST_SKIP_MONITOR_START", "1")
        env.setdefault("AGENT_MEMORY_TEST_SKIP_MONITOR_OPEN", "1")
        env.setdefault("AGENT_MEMORY_TEST_SKIP_RUNTIME_BOOTSTRAP", "1")
        env.setdefault("AGENT_MEMORY_TEST_SKIP_POST_INSTALL_CHECKS", "1")
        install = subprocess.run(
            [
                sys.executable,
                str(SKILL_ROOT / "scripts" / "agent_context_engine.py"),
                "install",
                "--target",
                str(target),
                "--instance-name",
                instance_name,
                "--language",
                "en",
                "--no-interactive",
                "--link-codex-ace",
                "--link-claude-ace",
                "--link-agy-ace",
                "--link-gemini-ace",
                "--link-opencode-ace",
                "--no-install-launchagent",
                "--link-dir",
                str(link_dir),
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        if install.returncode != 0:
            return CheckResult("fresh-install-smoke", False, install.stderr.strip() or install.stdout.strip())
        expected = [
            target / "AGENTS.md",
            target / "CLAUDE.md",
            target / ".codex" / "hooks.json",
            target / ".codex" / "hooks" / "hook_adapter.sh",
            target / ".claude" / "settings.json",
            target / ".claude" / "hooks" / "hook_adapter.sh",
            target / ".agents" / "hooks.json",
            target / ".agents" / "hooks" / "hook_adapter.sh",
            target / ".gemini" / "settings.json",
            target / ".gemini" / "hooks" / "hook_adapter.sh",
            target / ".cursor" / "rules" / "everyChat.mdc",
            target / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine",
            link_dir / "smoke-codex-ace",
            link_dir / "smoke-claude-ace",
            link_dir / "smoke-cursor-ace",
            link_dir / "smoke-agy-ace",
            link_dir / "smoke-gemini-ace",
            link_dir / "smoke-opencode-ace",
        ]
        missing = [str(path) for path in expected if not path.exists() and not path.is_symlink()]
        if missing:
            return CheckResult("fresh-install-smoke", False, "missing paths:\n" + "\n".join(missing))
        doctor = subprocess.run(
            [str(target / "docs" / "skills" / "agent-context-engine" / "scripts" / "agent-context-engine"), "doctor"],
            cwd=target,
            env=env,
            text=True,
            capture_output=True,
            timeout=45,
            check=False,
        )
        if doctor.returncode != 0:
            return CheckResult("fresh-install-smoke", False, doctor.stderr.strip() or doctor.stdout.strip())
        db_path = memory_root / "status" / "agent-memory.sqlite3"
        if not db_path.exists():
            return CheckResult("fresh-install-smoke", False, f"doctor did not create sqlite db: {db_path}")
        return CheckResult(
            "fresh-install-smoke",
            True,
            "\n".join(
                [
                    f"target={target}",
                    "links=smoke-codex-ace, smoke-claude-ace, smoke-cursor-ace, smoke-agy-ace, smoke-gemini-ace, smoke-opencode-ace",
                    "doctor=ok",
                ]
            ),
        )


def check_doctor_for_current_root() -> CheckResult:
    if not current_root_runtime_initialized():
        return CheckResult(
            "doctor",
            True,
            "skipped: current root is an uninitialized standalone clone; fresh-install-smoke verifies install + doctor",
        )
    return run_command("doctor", [str(AGENT_MEMORY), "doctor"])


def sync_instance_metadata_after_check(success: bool) -> None:
    if not success or not current_root_runtime_initialized():
        return
    backend_src = REPO_ROOT / "backend" / "src"
    if str(backend_src) not in sys.path:
        sys.path.insert(0, str(backend_src))
    try:
        from agent_context_engine.application.instance_profile import sync_instance_metadata
    except Exception:
        return
    try:
        sync_instance_metadata(REPO_ROOT, check_succeeded=True)
    except Exception:
        return


def main() -> int:
    parser = argparse.ArgumentParser(prog="check-agent-context-engine")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-doctor", action="store_true")
    parser.add_argument("--skip-runtime-db", action="store_true", help="Skip checks that require an existing populated local memory database")
    parser.add_argument("--skip-monitoring-contract-gate", action="store_true")
    parser.add_argument("--include-retrieval-evals", action="store_true")
    parser.add_argument("--include-install-integration-tests", action="store_true")
    parser.add_argument("--unit-suite-timeout", type=int, default=int(os.environ.get("AGENT_MEMORY_CHECK_UNIT_SUITE_TIMEOUT", "600")))
    parser.add_argument("--install-integration-timeout", type=int, default=int(os.environ.get("AGENT_MEMORY_CHECK_INSTALL_INTEGRATION_TIMEOUT", "1800")))
    args = parser.parse_args()

    checks: list[CheckResult] = []
    checks.append(run_command("py-compile", [sys.executable, "-m", "py_compile", *python_files()], env={"PYTHONPYCACHEPREFIX": str(Path(tempfile.gettempdir()) / "ace-pyc") }))
    checks.append(check_import_audit())
    if not args.skip_monitoring_contract_gate:
        checks.append(check_monitoring_contract_gate())
    checks.append(check_openapi_generation())
    checks.append(check_docs_spec_index())
    checks.append(check_test_coverage_matrix())
    checks.append(check_fresh_install_smoke())
    if not args.skip_tests:
        checks.append(
            run_command(
                "unit-suite",
                [sys.executable, str(TEST_FILE)],
                timeout=max(60, int(args.unit_suite_timeout)),
                env={"AGENT_MEMORY_SKIP_INSTALL_INTEGRATION_TESTS": "1"},
            )
        )
        if args.include_install_integration_tests:
            checks.append(
                run_command(
                    "install-integration-suite",
                    [sys.executable, str(TEST_FILE)],
                    timeout=max(60, int(args.install_integration_timeout)),
                    env={"AGENT_MEMORY_ONLY_INSTALL_INTEGRATION_TESTS": "1"},
                )
            )
        else:
            checks.append(
                CheckResult(
                    "install-integration-suite",
                    True,
                    "skipped: run `./scripts/check --skip-runtime-db --include-install-integration-tests`",
                )
            )
    if not args.skip_doctor:
        checks.append(check_doctor_for_current_root())
    if not args.skip_runtime_db:
        checks.append(check_runtime_db_health())
    checks.append(check_runtime_cli("cli-status", [str(AGENT_MEMORY), "status", "--limit", "1"]))
    checks.append(check_runtime_cli("cli-last", [str(AGENT_MEMORY), "last", "--limit", "1"]))
    checks.append(check_runtime_cli("cli-retrieval-runs", [str(AGENT_MEMORY), "retrieval-runs", "--limit", "1", "--json"]))
    checks.append(check_runtime_cli("cli-graph-status", [str(AGENT_MEMORY), "graph-status"]))
    if args.include_retrieval_evals:
        checks.append(check_retrieval_evals())

    for check in checks:
        status = "ok" if check.ok else "FAIL"
        print(f"{status}  {check.name}")
        if check.detail:
            for line in check.detail.splitlines():
                print(f"    {line}")
    success = all(check.ok for check in checks)
    sync_instance_metadata_after_check(success)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
