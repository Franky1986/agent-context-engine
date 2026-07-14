from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
import io
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from agent_context_engine.application.system_control import (  # noqa: E402
    apply_direct_user_system_command,
    command_allowed_while_suspended,
    parse_direct_user_system_command,
    system_admission_open,
    system_control_anchor_path,
    system_control_audit_path,
    system_control_path,
    system_control_status,
)
from agent_context_engine.domain.risk import scan_tool_input  # noqa: E402


class FakeScheduler:
    def __init__(self, *, loaded: bool = True, disable_ok: bool = True, restore_ok: bool = True) -> None:
        self.loaded = loaded
        self.disable_ok = disable_ok
        self.restore_ok = restore_ok
        self.disable_calls = 0
        self.restore_calls = 0

    def status(self, installation_root: Path) -> dict[str, Any]:
        return {
            "implementation": "fake",
            "supported": True,
            "installed": True,
            "loaded": self.loaded,
            "label": "test-scheduler",
        }

    def disable(self, installation_root: Path, previous_state: dict[str, Any]) -> dict[str, Any]:
        self.disable_calls += 1
        if self.disable_ok:
            self.loaded = False
        return {"ok": self.disable_ok, "action": "disabled", "detail": "fake disable"}

    def restore(self, installation_root: Path, previous_state: dict[str, Any]) -> dict[str, Any]:
        self.restore_calls += 1
        if self.restore_ok and previous_state.get("loaded"):
            self.loaded = True
        return {"ok": self.restore_ok, "action": "restored", "detail": "fake restore"}


def make_install(base: Path, name: str, *, memory: Path | None = None) -> Path:
    root = base / name
    root.mkdir()
    memory_root = memory or root / "memory"
    profile_path = root / "memory" / "local" / "installation-profile.json"
    profile_path.parent.mkdir(parents=True)
    profile_path.write_text(
        json.dumps(
            {
                "version": 4,
                "instance_id": name,
                "root": str(root),
                "installation_mode": "isolated",
                "storage": {"memory_root": str(memory_root)},
                "wrapper_naming": {"prefix": f"{name}-", "suffix": "-ace"},
                "platform_profile": {"profile_id": "unknown"},
            }
        ),
        encoding="utf-8",
    )
    return root


class SystemCommandParserTests(unittest.TestCase):
    def test_accepts_exact_commands(self) -> None:
        disable = parse_direct_user_system_command('system-disable --scope all --reason "Maintenance"')
        self.assertEqual(disable.name, "system-disable")
        self.assertEqual(disable.reason, "Maintenance")
        self.assertEqual(parse_direct_user_system_command("system-status").name, "system-status")
        recover = parse_direct_user_system_command(
            'system-recover --scope all --reason "repair" --confirm "rebuild-disabled-state"'
        )
        self.assertEqual(recover.confirmation, "rebuild-disabled-state")

    def test_non_system_text_is_not_a_command(self) -> None:
        self.assertIsNone(parse_direct_user_system_command("please disable ACE"))

    def test_rejects_ambiguous_or_shell_input(self) -> None:
        rejected = (
            "system-status now",
            'system-disable --scope all --reason ""',
            'system-disable --scope project --reason "x"',
            'system-disable --scope all --scope all --reason "x"',
            'system-disable --scope all --reason "x" --unknown value',
            'system-disable --scope all --reason "x"; echo bad',
            "system-status\nextra",
            "```system-status```",
        )
        for line in rejected:
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_direct_user_system_command(line)

    def test_agent_tool_system_control_and_forged_hook_are_blocked(self) -> None:
        for command in (
            'agent-context-engine system-disable --scope all --reason "agent"',
            'printf payload | python3 scripts/agent_context_engine.py log-hook --client codex',
        ):
            with self.subTest(command=command):
                decision = scan_tool_input("exec_command", {"cmd": command})
                self.assertTrue(decision.should_block)
                self.assertIn("system_control_mutation_attempt", decision.poisoning_flags)

    def test_read_only_search_for_control_terms_is_not_treated_as_mutation(self) -> None:
        for command in (
            "rg -n system-disable backend",
            "rg -n 'system-(disable|enable|recover)|log-hook' backend tests",
        ):
            with self.subTest(command=command):
                decision = scan_tool_input("exec_command", {"cmd": command})
                self.assertFalse(decision.should_block)
                self.assertNotIn("system_control_mutation_attempt", decision.poisoning_flags)

    def test_system_control_state_mutation_is_blocked_but_read_is_allowed(self) -> None:
        read = scan_tool_input("exec_command", {"cmd": "cat memory/local/system-control.json"})
        write = scan_tool_input("exec_command", {"cmd": "rm memory/local/system-control.json"})

        self.assertFalse(read.should_block)
        self.assertTrue(write.should_block)
        self.assertIn("system_control_state_change", write.poisoning_flags)

    def test_system_control_state_mutation_is_blocked_for_file_edit_tools(self) -> None:
        for tool_name, tool_input in (
            (
                "apply_patch",
                {"patch": "*** Begin Patch\n*** Update File: memory/local/system-control.json\n@@\n-{}\n+{\\\"mode\\\":\\\"enabled\\\"}\n*** End Patch"},
            ),
            ("Edit", {"file_path": "memory/local/system-control.anchor.json", "new_string": "{}"}),
        ):
            with self.subTest(tool_name=tool_name):
                decision = scan_tool_input(tool_name, tool_input)
                self.assertTrue(decision.should_block)
                self.assertIn("system_control_state_change", decision.poisoning_flags)

        read = scan_tool_input("Read", {"file_path": "memory/local/system-control.json"})
        self.assertFalse(read.should_block)

    def test_unknown_write_tool_and_parent_directory_mutation_are_blocked(self) -> None:
        unknown_write = scan_tool_input(
            "FutureWorkspaceMutator",
            {"target_path": "memory/local/system-control.json", "content": "{}"},
        )
        unknown_generic_path_write = scan_tool_input(
            "FutureWorkspaceMutator",
            {"path": "memory/local/system-control.json", "content": "{}"},
        )
        parent_move = scan_tool_input(
            "MoveDirectory",
            {"source_path": "memory/local", "destination_path": "memory/local-old"},
        )
        hook_state_write = scan_tool_input(
            "FutureWorkspaceMutator",
            {"target_path": "memory/local/hooks-state.json", "content": '{"enabled":false}'},
        )
        shell_parent_remove = scan_tool_input("exec_command", {"cmd": "rm -rf memory/local"})
        parent_read = scan_tool_input("Read", {"directory_path": "memory/local"})

        for decision in (unknown_write, unknown_generic_path_write, parent_move, shell_parent_remove, hook_state_write):
            self.assertTrue(decision.should_block)
        self.assertIn("system_control_state_change", unknown_write.poisoning_flags)
        self.assertIn("system_control_state_change", parent_move.poisoning_flags)
        self.assertIn("system_control_state_change", shell_parent_remove.poisoning_flags)
        self.assertIn("hook_integrity_change", hook_state_write.poisoning_flags)
        self.assertFalse(parent_read.should_block)

    def test_suspended_cli_admission_is_default_deny_with_exact_safe_subcommands(self) -> None:
        allowed = (
            argparse.Namespace(command="system-status"),
            argparse.Namespace(command="tool-output"),
            argparse.Namespace(command="personal", personal_command="list"),
            argparse.Namespace(command="risk", risk_command="show"),
            argparse.Namespace(command="firewall", firewall_command="list"),
            argparse.Namespace(command="schema-proposals", schema_command="registry"),
            argparse.Namespace(command="install-discovery", plan_json=None),
        )
        blocked = (
            argparse.Namespace(command="personal", personal_command="init"),
            argparse.Namespace(command="personal", personal_command="propose"),
            argparse.Namespace(command="personal", personal_command="accept"),
            argparse.Namespace(command="risk", risk_command="review"),
            argparse.Namespace(command="firewall", firewall_command="suggest"),
            argparse.Namespace(command="schema-proposals", schema_command="create"),
            argparse.Namespace(command="install-discovery", plan_json="/tmp/install-plan.json"),
            argparse.Namespace(command="future-new-command"),
        )

        for args in allowed:
            with self.subTest(allowed=args):
                self.assertTrue(command_allowed_while_suspended(args))
        for args in blocked:
            with self.subTest(blocked=args):
                self.assertFalse(command_allowed_while_suspended(args))


class SystemControlTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = make_install(self.base, "isolated-a")
        self.scheduler = FakeScheduler()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def apply(self, line: str, *, event_name: str = "UserPromptSubmit") -> str:
        with mock.patch.dict(
            apply_direct_user_system_command.__globals__,
            {"_instrumented_hook_descriptor_open": lambda: True},
        ):
            result = apply_direct_user_system_command(
                line,
                event_name=event_name,
                installation_root=self.root,
                session_id="session-1",
                event_seq=4,
                scheduler=self.scheduler,
            )
        self.assertIsNotNone(result)
        return str(result)

    def test_missing_state_defaults_enabled_without_writing(self) -> None:
        status = system_control_status(installation_root=self.root)
        self.assertEqual(status["mode"], "enabled")
        self.assertTrue(status["admission_open"])
        self.assertEqual(status["integrity"], "virgin_uninitialized")
        self.assertEqual(status["provenance_assurance"], "instrumented_runner_event_unverified")
        self.assertFalse(system_control_path(installation_root=self.root).exists())

    def test_disable_and_enable_preserve_hook_state_and_restore_scheduler(self) -> None:
        hooks_path = self.root / "memory" / "local" / "hooks-state.json"
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text('{"enabled":true,"runners":{"claude":{"enabled":false}}}\n', encoding="utf-8")
        original_hooks = hooks_path.read_bytes()

        disabled_message = self.apply('system-disable --scope all --reason "Maintenance"')
        disabled = system_control_status(installation_root=self.root)
        self.assertIn("system mode: disabled", disabled_message)
        self.assertEqual(disabled["mode"], "disabled")
        self.assertFalse(system_admission_open(installation_root=self.root))
        self.assertEqual(self.scheduler.disable_calls, 1)
        self.assertEqual(hooks_path.read_bytes(), original_hooks)

        self.apply('system-enable --scope all --reason "Done"')
        enabled = system_control_status(installation_root=self.root)
        self.assertEqual(enabled["mode"], "enabled")
        self.assertTrue(enabled["admission_open"])
        self.assertEqual(self.scheduler.restore_calls, 1)
        self.assertTrue(self.scheduler.loaded)
        self.assertEqual(hooks_path.read_bytes(), original_hooks)

    def test_disable_is_idempotent(self) -> None:
        self.apply('system-disable --scope all --reason "Maintenance"')
        self.apply('system-disable --scope all --reason "Still maintenance"')
        self.assertEqual(self.scheduler.disable_calls, 1)

    def test_deleting_initialized_state_fails_closed(self) -> None:
        self.apply('system-disable --scope all --reason "Maintenance"')
        path = system_control_path(installation_root=self.root)
        self.assertTrue(system_control_anchor_path(installation_root=self.root).exists())

        path.unlink()

        status = system_control_status(installation_root=self.root)
        self.assertEqual(status["mode"], "partial")
        self.assertFalse(status["state_valid"])
        self.assertFalse(status["admission_open"])
        self.assertEqual(status["integrity"], "invalid")
        self.assertIn("missing after initialization", status["last_error"])

    def test_replacing_initialized_state_without_anchor_update_fails_closed(self) -> None:
        self.apply('system-disable --scope all --reason "Maintenance"')
        path = system_control_path(installation_root=self.root)
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["mode"] = "enabled"
        path.write_text(json.dumps(payload), encoding="utf-8")

        status = system_control_status(installation_root=self.root)
        self.assertEqual(status["mode"], "partial")
        self.assertFalse(status["state_valid"])
        self.assertFalse(status["admission_open"])
        self.assertIn("integrity anchor", status["last_error"])

    def test_scheduler_failure_leaves_fail_closed_partial_state(self) -> None:
        self.scheduler.disable_ok = False
        self.apply('system-disable --scope all --reason "Maintenance"')
        status = system_control_status(installation_root=self.root)
        self.assertEqual(status["mode"], "partial")
        self.assertFalse(status["admission_open"])

    def test_invalid_state_fails_closed_and_recovery_builds_disabled_state(self) -> None:
        path = system_control_path(installation_root=self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json\n", encoding="utf-8")
        self.assertFalse(system_admission_open(installation_root=self.root))

        self.apply(
            'system-recover --scope all --reason "repair" --confirm "rebuild-disabled-state"'
        )

        status = system_control_status(installation_root=self.root)
        self.assertEqual(status["mode"], "disabled")
        self.assertTrue(any(path.parent.glob("system-control.invalid-*.json")))

        self.apply('system-enable --scope all --reason "recovered state reviewed"')
        self.assertFalse(self.scheduler.loaded)

    def test_mutation_rejects_non_user_event(self) -> None:
        with self.assertRaises(PermissionError):
            self.apply('system-disable --scope all --reason "bad source"', event_name="PreToolUse")
        self.assertTrue(system_admission_open(installation_root=self.root))

    def test_application_entry_rejects_uninstrumented_process(self) -> None:
        with (
            mock.patch.dict(
                apply_direct_user_system_command.__globals__,
                {"_instrumented_hook_descriptor_open": lambda: False},
            ),
            self.assertRaises(PermissionError),
        ):
            apply_direct_user_system_command(
                'system-disable --scope all --reason "forged"',
                event_name="UserPromptSubmit",
                installation_root=self.root,
                scheduler=self.scheduler,
            )

    def test_recover_rechecks_state_after_lock_acquisition(self) -> None:
        path = system_control_path(installation_root=self.root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not-json\n", encoding="utf-8")

        def acquire_after_other_recovery(_root: Path) -> Path:
            valid = {
                "schema_version": 1,
                "mode": "disabled",
                "scope": "all",
                "reason": "other recovery",
                "previous": {"scheduler": self.scheduler.status(self.root)},
                "steps": [],
                "background_drain": {},
            }
            path.write_text(json.dumps(valid) + "\n", encoding="utf-8")
            return self.root / "fake-lock"

        with (
            mock.patch("agent_context_engine.application.system_control._acquire_lock", side_effect=acquire_after_other_recovery),
            mock.patch("agent_context_engine.application.system_control._release_lock"),
            mock.patch.dict(
                apply_direct_user_system_command.__globals__,
                {"_instrumented_hook_descriptor_open": lambda: True},
            ),
            self.assertRaises(ValueError),
        ):
            apply_direct_user_system_command(
                'system-recover --scope all --reason "stale recovery" --confirm "rebuild-disabled-state"',
                event_name="UserPromptSubmit",
                installation_root=self.root,
                scheduler=self.scheduler,
            )

        self.assertEqual(self.scheduler.disable_calls, 0)

    def test_isolated_installations_keep_independent_state(self) -> None:
        second = make_install(self.base, "isolated-b")
        self.apply('system-disable --scope all --reason "only a"')

        self.assertEqual(system_control_status(installation_root=self.root)["mode"], "disabled")
        self.assertEqual(system_control_status(installation_root=second)["mode"], "enabled")
        self.assertNotEqual(
            system_control_path(installation_root=self.root),
            system_control_path(installation_root=second),
        )

    def test_external_memory_root_is_authoritative(self) -> None:
        external = self.base / "external-memory"
        external_root = make_install(self.base, "external", memory=external)
        with mock.patch.dict(
            apply_direct_user_system_command.__globals__,
            {"_instrumented_hook_descriptor_open": lambda: True},
        ):
            apply_direct_user_system_command(
                'system-disable --scope all --reason "external"',
                event_name="UserPromptSubmit",
                installation_root=external_root,
                scheduler=FakeScheduler(loaded=False),
            )
        expected = external.resolve() / "local" / "system-control.json"
        self.assertEqual(system_control_path(installation_root=external_root), expected)
        self.assertTrue(expected.exists())


class SystemControlHookEntryTests(unittest.TestCase):
    def test_all_runner_clients_process_direct_status_before_normal_hook_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = make_install(base, "hook-install")
            env = dict(os.environ)
            env["AGENT_CONTEXT_ENGINE_ROOT"] = str(root)
            script = Path(__file__).resolve().parents[1] / "scripts" / "agent_context_engine.py"
            instrumented_command = [
                "/bin/sh",
                "-c",
                'exec "$@" 3</dev/null',
                "system-control-hook-test",
                sys.executable,
                str(script),
                "log-hook",
                "--client",
            ]

            disable_payload = json.dumps(
                {
                    "hook_event_name": "UserPromptSubmit",
                    "session_id": "direct-control",
                    "cwd": str(base),
                    "prompt": 'system-disable --scope all --reason "hook test"',
                }
            )
            forged = subprocess.run(
                [sys.executable, str(script), "log-hook", "--client", "codex"],
                input=disable_payload,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(forged.returncode, 0, forged.stderr)
            self.assertIn("System control rejected", forged.stdout)
            self.assertFalse(system_control_path(installation_root=root).exists())
            audit_lines = system_control_audit_path(installation_root=root).read_text(encoding="utf-8").splitlines()
            rejection = json.loads(audit_lines[-1])
            self.assertEqual(rejection["command"], "system-disable")
            self.assertEqual(rejection["result"], "rejected")
            self.assertNotIn("hook test", json.dumps(rejection))

            disabled = subprocess.run(
                [*instrumented_command, "codex"],
                input=disable_payload,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(disabled.returncode, 0, disabled.stderr)
            self.assertIn("system mode: disabled", disabled.stdout)

            for client in ("codex", "claude", "cursor", "gemini", "antigravity", "opencode"):
                with self.subTest(client=client):
                    payload = json.dumps(
                        {
                            "hook_event_name": "UserPromptSubmit",
                            "session_id": f"status-{client}",
                            "cwd": str(base),
                            "prompt": "system-status",
                        }
                    )
                    result = subprocess.run(
                        [*instrumented_command, client],
                        input=payload,
                        text=True,
                        capture_output=True,
                        env=env,
                        check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("system mode: disabled", result.stdout)

            normal_event = subprocess.run(
                [*instrumented_command, "codex"],
                input=json.dumps(
                    {
                        "hook_event_name": "UserPromptSubmit",
                        "session_id": "normal-while-disabled",
                        "cwd": str(base),
                        "prompt": "ordinary prompt",
                    }
                ),
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            self.assertEqual(normal_event.returncode, 0, normal_event.stderr)
            self.assertEqual(normal_event.stdout, "")
            self.assertFalse((root / "memory" / "status" / "agent-memory.sqlite3").exists())


class SystemControlBoundaryTests(unittest.TestCase):
    def test_scheduler_rechecks_admission_before_each_step(self) -> None:
        from agent_context_engine.application import scheduler as scheduler_module

        executed: list[str] = []
        connection = mock.MagicMock()
        ports = scheduler_module.SchedulerPorts(
            connect_db=lambda init=True: connection,
            acquire_lock=lambda _name, _scope: object(),
            release_lock=lambda _lock: None,
            replay_hook_queue=lambda: 0,
            prune_logs=lambda _args: 0,
            sync_transcripts=lambda: 0,
            summarize_sessions=lambda: 0,
            summarize_windows=lambda _args: 0,
            recover_stale_dreams=lambda: 0,
            enqueue_pending_dreams=lambda _args: 0,
            process_dream_queue=lambda _args: 0,
            neo4j_sync_pending=lambda _args: 0,
        )

        class TwoStepScheduler(scheduler_module.SchedulerUseCase):
            def _step_plan(self, args: argparse.Namespace) -> list[scheduler_module.SchedulerStep]:
                return [
                    scheduler_module.SchedulerStep("first", lambda _args: executed.append("first") or 0),
                    scheduler_module.SchedulerStep("second", lambda _args: executed.append("second") or 0),
                ]

        usecase = TwoStepScheduler(ports)
        args = argparse.Namespace(grace_minutes=5, runner="codex", runner_timeout=60)
        with (
            mock.patch.object(scheduler_module, "system_admission_open", side_effect=[True, True, False]),
            mock.patch.object(TwoStepScheduler, "repair_abandoned_runs", return_value={"runs": 0, "steps": 0}),
            mock.patch.object(TwoStepScheduler, "scheduler_counts", return_value={}),
            mock.patch.object(scheduler_module.scheduler_repo, "insert_scheduler_run"),
            mock.patch.object(scheduler_module.scheduler_repo, "insert_scheduler_step", return_value=1),
            mock.patch.object(scheduler_module.scheduler_repo, "mark_scheduler_step_finished"),
            mock.patch.object(scheduler_module.scheduler_repo, "mark_scheduler_run_finished"),
        ):
            result = usecase.run(args)

        self.assertEqual(result, 0)
        self.assertEqual(executed, ["first"])

    def test_dream_queue_rechecks_admission_before_claim(self) -> None:
        from agent_context_engine.application import dream_queue

        connection = mock.MagicMock()
        with (
            mock.patch.object(dream_queue, "_connect", return_value=connection),
            mock.patch.object(dream_queue, "recover_stale_running_dreams"),
            mock.patch.object(dream_queue, "recover_stale_dream_queue_jobs"),
            mock.patch.object(dream_queue, "system_admission_open", return_value=False),
            mock.patch.object(dream_queue, "_claim_next_queued_job") as claim,
        ):
            result = dream_queue.process_dream_queue(argparse.Namespace(dream_queue_limit=1))

        self.assertEqual(result, 0)
        claim.assert_not_called()

    def test_hook_queue_rechecks_admission_before_worker_lock(self) -> None:
        from agent_context_engine.interfaces.hooks import main as hooks_main

        with (
            mock.patch.object(hooks_main, "system_admission_open", return_value=False),
            mock.patch.object(hooks_main, "acquire_lock") as acquire,
        ):
            result = hooks_main.cmd_replay_hook_queue(
                argparse.Namespace(client=None, limit=10, recover_limit=10, stop_on_error=False, worker=True)
            )

        self.assertEqual(result, 0)
        acquire.assert_not_called()

    def test_monitor_post_is_locked_while_suspended(self) -> None:
        from agent_context_engine.interfaces.http.server import MonitorHandler

        handler = MonitorHandler.__new__(MonitorHandler)
        handler.path = "/api/ask"
        body = json.dumps({"question": "start LLM work"}).encode("utf-8")
        handler.headers = {"content-length": str(len(body))}
        handler.rfile = io.BytesIO(body)
        captured: dict[str, Any] = {}
        handler.send_json = lambda payload, status=200: captured.update(payload=payload, status=status)  # type: ignore[method-assign]

        with mock.patch("agent_context_engine.interfaces.http.server.system_admission_open", return_value=False):
            handler.do_POST()

        self.assertEqual(captured["status"], 423)
        self.assertEqual(captured["payload"]["error_code"], "system_suspended")

    def test_macos_scheduler_disable_and_restore_preserve_plist(self) -> None:
        from agent_context_engine.adapters import system_scheduler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "mac-install"
            root.mkdir()
            plist = Path(tmp) / "scheduler.plist"
            plist.write_text("plist", encoding="utf-8")
            profile = root / "memory" / "local" / "installation-profile.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "root": str(root),
                        "platform_profile": {"profile_id": "macos"},
                        "launchagent": {
                            "label": "com.agent-context-engine.test",
                            "path": str(plist),
                            "env_file": "memory/local/agent-context-engine.env",
                        },
                    }
                ),
                encoding="utf-8",
            )
            scheduler = system_scheduler.PlatformSystemScheduler()
            completed = subprocess.CompletedProcess(["launchctl"], 0, "", "")
            with (
                mock.patch.object(system_scheduler.shutil, "which", return_value="/bin/launchctl"),
                mock.patch.object(system_scheduler, "launchagent_loaded", side_effect=[True, True, False]),
                mock.patch.object(system_scheduler.subprocess, "run", return_value=completed) as run,
            ):
                previous = scheduler.status(root)
                disabled = scheduler.disable(root, previous)
                restored = scheduler.restore(root, previous)

            self.assertTrue(disabled["ok"])
            self.assertTrue(restored["ok"])
            self.assertTrue(plist.exists())
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn("bootout", commands[0])
            self.assertIn("bootstrap", commands[1])

    def test_windows_scheduler_disable_and_restore_use_owned_task(self) -> None:
        from agent_context_engine.adapters import system_scheduler

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "windows-install"
            root.mkdir()
            profile = root / "memory" / "local" / "installation-profile.json"
            profile.parent.mkdir(parents=True)
            profile.write_text(
                json.dumps(
                    {
                        "root": str(root),
                        "platform_profile": {"profile_id": "windows"},
                        "launchagent": {"label": "AgentContextEngine-Test"},
                    }
                ),
                encoding="utf-8",
            )
            query = subprocess.CompletedProcess(
                ["schtasks"],
                0,
                '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Settings><Enabled>true</Enabled></Settings></Task>',
                "",
            )
            changed = subprocess.CompletedProcess(["schtasks"], 0, "SUCCESS", "")
            with (
                mock.patch.object(system_scheduler, "_windows_scheduler_available", return_value=True),
                mock.patch.object(system_scheduler.subprocess, "run", side_effect=[query, changed, changed]) as run,
            ):
                scheduler = system_scheduler.PlatformSystemScheduler()
                previous = scheduler.status(root)
                disabled = scheduler.disable(root, previous)
                restored = scheduler.restore(root, previous)

            self.assertTrue(previous["loaded"])
            self.assertTrue(previous["enabled_known"])
            self.assertTrue(disabled["ok"])
            self.assertTrue(restored["ok"])
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn("/Disable", commands[1])
            self.assertIn("/Enable", commands[2])


if __name__ == "__main__":
    unittest.main()
