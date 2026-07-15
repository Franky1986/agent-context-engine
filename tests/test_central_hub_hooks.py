#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SKILL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_ROOT / "backend" / "src"))

from agent_context_engine.infrastructure.config import (
    active_root_path,
    central_backup_dir,
    central_hub_path,
    project_backup_dir,
    storage_root,
)
from agent_context_engine.application.integrations import (
    _merge_shell_hook_client,
    _disable_shell_hook_client,
    _read_activated_projects,
    _write_activated_projects,
)


class StorageRootHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ace-hub-test-"))
        self.old_storage = os.environ.get("AGENT_CONTEXT_ENGINE_STORAGE_ROOT")
        os.environ["AGENT_CONTEXT_ENGINE_STORAGE_ROOT"] = str(self.tmp)

    def tearDown(self) -> None:
        if self.old_storage is None:
            os.environ.pop("AGENT_CONTEXT_ENGINE_STORAGE_ROOT", None)
        else:
            os.environ["AGENT_CONTEXT_ENGINE_STORAGE_ROOT"] = self.old_storage
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_storage_root_uses_env_override(self) -> None:
        self.assertEqual(storage_root().resolve(), self.tmp.resolve())

    def test_active_root_and_hub_paths(self) -> None:
        self.assertEqual(active_root_path().resolve(), (self.tmp / ".agent-context-engine" / "active-root").resolve())
        self.assertEqual(central_hub_path("codex").resolve(), (self.tmp / ".agent-context-engine" / "hooks" / "codex" / "hook_adapter.sh").resolve())

    def test_project_backup_dir_is_sha256_of_absolute_path(self) -> None:
        project = Path("/tmp/example-project")
        resolved = project.expanduser().resolve()
        expected = central_backup_dir() / hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()
        self.assertEqual(project_backup_dir(project).resolve(), expected.resolve())

    def test_codex_wrapper_checks_hook_config_completeness(self) -> None:
        wrapper_text = (SKILL_ROOT / "scripts" / "codex-ace").read_text(encoding="utf-8")
        self.assertIn('expected_events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"]', wrapper_text)
        self.assertIn('expected_path = str(Path(sys.argv[2]).expanduser().resolve() / ".codex" / "hooks" / "hook_adapter.sh")', wrapper_text)
        self.assertIn('expected_command = "\'" + expected_path.replace("\'", "\'\\\"\'\\\"\'") + "\'"', wrapper_text)
        self.assertIn('json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))', wrapper_text)
        self.assertIn('[[ -f "$CENTRAL_HUB" ]] && [[ -x "$CENTRAL_HUB" ]]', wrapper_text)
        self.assertIn('local binding_path="$PROJECT_DIR/.codex/agent-memory-binding.json"', wrapper_text)
        self.assertIn('installation_root != expected_root', wrapper_text)
        self.assertIn('resolved.name == "memory" and resolved.parent.name == ".agent-context-engine"', wrapper_text)
        self.assertIn('_INSTALL_LANGUAGE="$(_profile_language)"', wrapper_text)
        self.assertIn('(data.get("monitor") or {}).get("language")', wrapper_text)
        self.assertIn('LAUNCH_CWD="$(pwd)"', wrapper_text)
        self.assertIn('PROJECT_DIR="$LAUNCH_CWD"', wrapper_text)
        self.assertNotIn('SEARCH_DIR="$LAUNCH_CWD"', wrapper_text)
        template_text = (SKILL_ROOT / "templates" / "codex-hooks" / "hook_adapter.sh").read_text(encoding="utf-8")
        self.assertIn('PAYLOAD_HASH="$(shasum -a 256 "$PAYLOAD_TMP"', template_text)
        self.assertIn('memory/runtime/hook-dedupe/${CLIENT}', template_text)
        self.assertIn('<"$PAYLOAD_TMP"', template_text)

    def test_claude_wrapper_checks_hook_config_completeness(self) -> None:
        wrapper_text = (SKILL_ROOT / "scripts" / "claude-ace").read_text(encoding="utf-8")
        self.assertIn('expected_events = ["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Notification", "Stop"]', wrapper_text)
        self.assertIn('expected_path = str(Path(sys.argv[2]).expanduser().resolve() / ".claude" / "hooks" / "hook_adapter.sh")', wrapper_text)
        self.assertIn('local binding_path="$PROJECT_DIR/.claude/agent-memory-binding.json"', wrapper_text)
        self.assertIn('installation_root != expected_root', wrapper_text)
        self.assertIn('PROJECT_DIR="$LAUNCH_CWD"', wrapper_text)
        self.assertNotIn('SEARCH_DIR="$LAUNCH_CWD"', wrapper_text)
        template_text = (SKILL_ROOT / "templates" / "claude-hooks" / "hook_adapter.sh").read_text(encoding="utf-8")
        self.assertIn('PAYLOAD_HASH="$(shasum -a 256 "$PAYLOAD_TMP"', template_text)
        self.assertIn('memory/runtime/hook-dedupe/${CLIENT}', template_text)
        self.assertIn('<"$PAYLOAD_TMP"', template_text)

    def test_antigravity_and_gemini_wrappers_check_hook_config_completeness(self) -> None:
        antigravity_wrapper = (SKILL_ROOT / "scripts" / "agy-ace").read_text(encoding="utf-8")
        self.assertIn('expected_events = ["PreInvocation", "PreToolUse", "PostToolUse", "PostInvocation", "Stop"]', antigravity_wrapper)
        self.assertIn('expected_path = str(Path(sys.argv[2]).expanduser().resolve() / ".agents" / "hooks" / "hook_adapter.sh")', antigravity_wrapper)
        self.assertIn('expected_commands = {event: f"{expected_command} {event}" for event in expected_events}', antigravity_wrapper)
        self.assertIn('local binding_path="$PROJECT_DIR/.agents/agent-memory-binding.json"', antigravity_wrapper)
        self.assertIn('[[ -f "$CENTRAL_HUB" ]] && [[ -x "$CENTRAL_HUB" ]]', antigravity_wrapper)
        self.assertIn('installation_root != expected_root', antigravity_wrapper)
        self.assertIn('PROJECT_DIR="$LAUNCH_CWD"', antigravity_wrapper)
        self.assertNotIn('SEARCH_DIR="$LAUNCH_CWD"', antigravity_wrapper)

        gemini_wrapper = (SKILL_ROOT / "scripts" / "gemini-ace").read_text(encoding="utf-8")
        self.assertIn('expected_events = ["SessionStart", "BeforeAgent", "BeforeTool", "AfterTool", "Notification", "AfterAgent"]', gemini_wrapper)
        self.assertIn('expected_path = str(Path(sys.argv[2]).expanduser().resolve() / ".gemini" / "hooks" / "hook_adapter.sh")', gemini_wrapper)
        self.assertIn('expected_commands = {event: f"{expected_command} {event}" for event in expected_events}', gemini_wrapper)
        self.assertIn('local binding_path="$PROJECT_DIR/.gemini/agent-memory-binding.json"', gemini_wrapper)
        self.assertIn('[[ -f "$CENTRAL_HUB" ]] && [[ -x "$CENTRAL_HUB" ]]', gemini_wrapper)
        self.assertIn('PROJECT_DIR="$LAUNCH_CWD"', gemini_wrapper)
        self.assertNotIn('SEARCH_DIR="$LAUNCH_CWD"', gemini_wrapper)

    def test_opencode_wrapper_uses_active_root_and_requires_plugin_bridge(self) -> None:
        wrapper_text = (SKILL_ROOT / "scripts" / "opencode-ace").read_text(encoding="utf-8")
        helper_text = (SKILL_ROOT / "scripts" / "lib" / "ace-wrapper-root.sh").read_text(encoding="utf-8")
        self.assertIn('ace_resolve_wrapper_root "$SCRIPT_DIR" "$0" "opencode-ace"', wrapper_text)
        self.assertIn('active_root_file="$storage_root/.agent-context-engine/active-root"', helper_text)
        self.assertIn('.opencode/plugins/agent-memory.js', wrapper_text)
        self.assertIn('opencode-enable', wrapper_text)

    def test_cursor_wrapper_is_activation_helper(self) -> None:
        wrapper_text = (SKILL_ROOT / "scripts" / "cursor-ace").read_text(encoding="utf-8")
        self.assertIn('ace_resolve_wrapper_root "$SCRIPT_DIR" "$0" "cursor-ace"', wrapper_text)
        self.assertIn('cursor-enable --target "$PROJECT_DIR" --installation-root "$ACE_ROOT"', wrapper_text)
        self.assertIn('cursor-status --target "$PROJECT_DIR"', wrapper_text)
        self.assertIn('restart Cursor once or reload the window', wrapper_text)
        self.assertNotIn('exec cursor', wrapper_text)

    def test_interactive_wrappers_use_installation_language_for_prompts(self) -> None:
        for wrapper_name in ["codex-ace", "claude-ace", "cursor-ace", "agy-ace", "gemini-ace"]:
            with self.subTest(wrapper=wrapper_name):
                wrapper_text = (SKILL_ROOT / "scripts" / wrapper_name).read_text(encoding="utf-8")
                self.assertIn('_INSTALL_LANGUAGE="$(_profile_language)"', wrapper_text)
                self.assertIn('(data.get("monitor") or {}).get("language")', wrapper_text)
                self.assertIn('AGENT_CONTEXT_ENGINE_LANGUAGE', wrapper_text)
                self.assertIn('[YyJj]) return 0', wrapper_text)
                self.assertIn('""|[Nn]) return 1', wrapper_text)
                self.assertIn('_msg_invalid_reply', wrapper_text)

    def test_all_wrappers_check_system_mode_before_activation_or_repair(self) -> None:
        helper_text = (SKILL_ROOT / "scripts" / "lib" / "ace-wrapper-root.sh").read_text(encoding="utf-8")
        self.assertIn("printf 'partial\\n'", helper_text)
        for wrapper_name in ["codex-ace", "claude-ace", "cursor-ace", "agy-ace", "gemini-ace", "opencode-ace"]:
            with self.subTest(wrapper=wrapper_name):
                wrapper_text = (SKILL_ROOT / "scripts" / wrapper_name).read_text(encoding="utf-8")
                self.assertIn("ace_system_mode", wrapper_text)
                self.assertIn("ace_print_suspended_warning", wrapper_text)
        opencode_text = (SKILL_ROOT / "scripts" / "opencode-ace").read_text(encoding="utf-8")
        self.assertIn("activation and repair are blocked while the system is suspended", opencode_text)

    def test_central_shell_wrappers_normalize_default_memory_root_for_hub_metadata(self) -> None:
        for wrapper_name in ["codex-ace", "claude-ace", "agy-ace", "gemini-ace"]:
            with self.subTest(wrapper=wrapper_name):
                wrapper_text = (SKILL_ROOT / "scripts" / wrapper_name).read_text(encoding="utf-8")
                self.assertIn('resolved.name == "memory" and resolved.parent.name == ".agent-context-engine"', wrapper_text)
                self.assertIn('resolved = resolved.parent.parent', wrapper_text)

    def test_instance_named_wrapper_symlink_uses_own_installation(self) -> None:
        local_install = self.tmp / "isolated-install"
        global_install = self.tmp / "global-install"
        bin_dir = self.tmp / "bin"
        for install in (local_install, global_install):
            (install / "scripts" / "lib").mkdir(parents=True)
        (local_install / "scripts" / "codex-ace").write_bytes((SKILL_ROOT / "scripts" / "codex-ace").read_bytes())
        (local_install / "scripts" / "lib" / "ace-wrapper-root.sh").write_bytes(
            (SKILL_ROOT / "scripts" / "lib" / "ace-wrapper-root.sh").read_bytes()
        )
        os.chmod(local_install / "scripts" / "codex-ace", 0o755)
        bin_dir.mkdir()
        wrapper = bin_dir / "client-a-codex-ace"
        wrapper.symlink_to(local_install / "scripts" / "codex-ace")
        active_root = self.tmp / ".agent-context-engine" / "active-root"
        active_root.parent.mkdir(parents=True)
        active_root.write_text(str(global_install) + "\n", encoding="utf-8")

        env = {**os.environ, "HOME": str(self.tmp), "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        env.pop("AGENT_CONTEXT_ENGINE_ROOT", None)
        result = subprocess.run(
            [wrapper.name],
            cwd=self.tmp,
            text=True,
            input="n\n",
            capture_output=True,
            check=False,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"cannot find agent-context-engine CLI under {local_install}", result.stderr)

    def test_shared_wrapper_symlink_follows_home_active_root(self) -> None:
        local_install = self.tmp / "old-install"
        global_install = self.tmp / "new-install"
        bin_dir = self.tmp / "bin"
        (local_install / "scripts" / "lib").mkdir(parents=True)
        global_install.mkdir()
        (local_install / "scripts" / "codex-ace").write_bytes((SKILL_ROOT / "scripts" / "codex-ace").read_bytes())
        (local_install / "scripts" / "lib" / "ace-wrapper-root.sh").write_bytes(
            (SKILL_ROOT / "scripts" / "lib" / "ace-wrapper-root.sh").read_bytes()
        )
        os.chmod(local_install / "scripts" / "codex-ace", 0o755)
        bin_dir.mkdir()
        wrapper = bin_dir / "codex-ace"
        wrapper.symlink_to(local_install / "scripts" / "codex-ace")
        active_root = self.tmp / ".agent-context-engine" / "active-root"
        active_root.parent.mkdir(parents=True)
        active_root.write_text(str(global_install) + "\n", encoding="utf-8")

        env = {**os.environ, "HOME": str(self.tmp), "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        env.pop("AGENT_CONTEXT_ENGINE_ROOT", None)
        result = subprocess.run(
            [wrapper.name],
            cwd=self.tmp,
            text=True,
            input="n\n",
            capture_output=True,
            check=False,
            env=env,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"cannot find agent-context-engine CLI under {global_install}", result.stderr)


class CodexCentralHubActivationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ace-hub-activation-"))
        self.storage = self.tmp / "storage"
        self.storage.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.home_patch = mock.patch.object(Path, "home", return_value=self.home)
        self.home_patch.start()
        self.install = self.tmp / "install"
        self.install.mkdir()
        # Create the minimal installation layout expected by the hub/template.
        (self.install / "scripts").mkdir()
        (self.install / "scripts" / "agent_context_engine.py").write_text("# placeholder\n", encoding="utf-8")
        (self.install / "templates" / "codex-hooks").mkdir(parents=True)
        (self.install / "templates" / "codex-hooks" / "hook_adapter.sh").write_text(
            '#!/usr/bin/env bash\necho "dynamic template"\n', encoding="utf-8"
        )
        (self.install / "templates" / "codex-hooks" / "hook_hub.sh").write_text(
            '#!/usr/bin/env bash\nexec "$ROOT/templates/codex-hooks/hook_adapter.sh" "$@"\n', encoding="utf-8"
        )
        (self.install / "templates" / "codex-hooks" / "hooks.json").write_text(
            json.dumps({
                "hooks": {
                    "SessionStart": [{"hooks": [{"type": "command", "command": "./.codex/hooks/hook_adapter.sh"}]}],
                    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "./.codex/hooks/hook_adapter.sh"}]}],
                    "PreToolUse": [{"hooks": [{"type": "command", "command": "./.codex/hooks/hook_adapter.sh"}]}],
                    "PostToolUse": [{"hooks": [{"type": "command", "command": "./.codex/hooks/hook_adapter.sh"}]}],
                    "Stop": [{"hooks": [{"type": "command", "command": "./.codex/hooks/hook_adapter.sh"}]}],
                }
            }),
            encoding="utf-8",
        )
        (self.install / "templates" / "claude-hooks").mkdir(parents=True)
        (self.install / "templates" / "claude-hooks" / "hook_adapter.sh").write_text(
            '#!/usr/bin/env bash\necho "dynamic template"\n', encoding="utf-8"
        )
        (self.install / "templates" / "claude-hooks" / "hook_hub.sh").write_text(
            '#!/usr/bin/env bash\nexec "$ROOT/templates/claude-hooks/hook_adapter.sh" "$@"\n', encoding="utf-8"
        )
        (self.install / "templates" / "claude-hooks" / "settings.json").write_text(
            json.dumps({
                "hooks": {
                    "SessionStart": [{"hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/hook_adapter.sh"}]}],
                    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/hook_adapter.sh"}]}],
                    "PreToolUse": [{"hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/hook_adapter.sh"}]}],
                    "PostToolUse": [{"hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/hook_adapter.sh"}]}],
                    "Stop": [{"hooks": [{"type": "command", "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/hook_adapter.sh"}]}],
                }
            }),
            encoding="utf-8",
        )
        for runner in ("gemini", "antigravity"):
            runner_templates = self.install / "templates" / f"{runner}-hooks"
            runner_templates.mkdir(parents=True)
            (runner_templates / "hook_adapter.sh").write_text(
                f'#!/usr/bin/env bash\necho "dynamic template {runner}"\n',
                encoding="utf-8",
            )

        self.old_storage = os.environ.get("AGENT_CONTEXT_ENGINE_STORAGE_ROOT")
        self.old_root = os.environ.get("AGENT_CONTEXT_ENGINE_ROOT")
        os.environ["AGENT_CONTEXT_ENGINE_STORAGE_ROOT"] = str(self.storage)
        os.environ["AGENT_CONTEXT_ENGINE_ROOT"] = str(self.install)

        # Reload config module so storage_root() picks up the env override.
        import importlib
        from agent_context_engine import infrastructure
        importlib.reload(infrastructure.config)

    def tearDown(self) -> None:
        if self.old_storage is None:
            os.environ.pop("AGENT_CONTEXT_ENGINE_STORAGE_ROOT", None)
        else:
            os.environ["AGENT_CONTEXT_ENGINE_STORAGE_ROOT"] = self.old_storage
        if self.old_root is None:
            os.environ.pop("AGENT_CONTEXT_ENGINE_ROOT", None)
        else:
            os.environ["AGENT_CONTEXT_ENGINE_ROOT"] = self.old_root
        self.home_patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_central_hub_creation(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        actions = _ensure_central_hub_and_active_root(self.install)
        self.assertTrue(any("active-root" in a for a in actions))
        self.assertTrue(any("central hub" in a for a in actions))
        self.assertEqual(active_root_path().read_text(encoding="utf-8").strip(), str(self.install.resolve()))
        hub = central_hub_path("codex")
        self.assertTrue(hub.exists())
        self.assertTrue(os.access(hub, os.X_OK))

    def test_central_hub_creation_keeps_isolated_active_root_local(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        user_active_root = self.home / ".agent-context-engine" / "active-root"
        user_active_root.parent.mkdir(parents=True, exist_ok=True)
        user_active_root.write_text("/previous/default/install\n", encoding="utf-8")

        actions = _ensure_central_hub_and_active_root(self.install, metadata_root=self.storage)

        self.assertFalse(any("updated user active-root" in a for a in actions))
        self.assertEqual(user_active_root.read_text(encoding="utf-8").strip(), "/previous/default/install")
        self.assertEqual((self.storage / ".agent-context-engine" / "active-root").read_text(encoding="utf-8").strip(), str(self.install.resolve()))

    def test_isolated_hubs_execute_own_active_root_without_environment(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root

        _ensure_central_hub_and_active_root(self.install, metadata_root=self.storage)
        global_root = self.tmp / "wrong-global-install"
        global_root.mkdir()
        global_active_root = self.home / ".agent-context-engine" / "active-root"
        global_active_root.parent.mkdir(parents=True, exist_ok=True)
        global_active_root.write_text(str(global_root) + "\n", encoding="utf-8")
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env.pop("AGENT_CONTEXT_ENGINE_ROOT", None)
        env.pop("AGENT_CONTEXT_ENGINE_STORAGE_ROOT", None)
        env.pop("AGENT_MEMORY_STORAGE_ROOT", None)

        for runner in ("codex", "claude", "gemini", "antigravity"):
            with self.subTest(runner=runner):
                project = self.tmp / f"direct-{runner}-project"
                adapter = project / ".hooks" / runner / "hook_adapter.sh"
                adapter.parent.mkdir(parents=True)
                adapter.symlink_to(self.storage / ".agent-context-engine" / "hooks" / runner / "hook_adapter.sh")

                result = subprocess.run([str(adapter)], cwd=project, text=True, capture_output=True, check=False, env=env)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("dynamic template", result.stdout)

    def test_default_memory_root_writes_home_active_root(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        default_memory_root = self.home / ".agent-context-engine" / "memory"

        _ensure_central_hub_and_active_root(self.install, metadata_root=default_memory_root)

        self.assertEqual(
            (self.home / ".agent-context-engine" / "active-root").read_text(encoding="utf-8").strip(),
            str(self.install.resolve()),
        )
        self.assertFalse((default_memory_root / ".agent-context-engine" / "active-root").exists())

    def test_default_memory_root_migrates_legacy_nested_active_root(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root

        default_memory_root = self.home / ".agent-context-engine" / "memory"
        legacy_active_root = default_memory_root / ".agent-context-engine" / "active-root"
        legacy_active_root.parent.mkdir(parents=True)
        legacy_active_root.write_text("/previous/install\n", encoding="utf-8")

        actions = _ensure_central_hub_and_active_root(
            self.install,
            metadata_root=default_memory_root,
        )

        canonical_active_root = self.home / ".agent-context-engine" / "active-root"
        self.assertEqual(legacy_active_root.read_text(encoding="utf-8").strip(), str(self.install.resolve()))
        if os.name != "nt":
            self.assertTrue(legacy_active_root.is_symlink())
            self.assertEqual(legacy_active_root.resolve(), canonical_active_root.resolve())
        self.assertTrue(any("legacy nested active-root" in action for action in actions))

    def test_codex_activation_creates_symlink_and_registry(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "project"
        project.mkdir()
        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="codex", action="enable", root=self.install, target_root=project)

        config_path = project / ".codex" / "hooks.json"
        self.assertTrue(config_path.exists())
        data = json.loads(config_path.read_text(encoding="utf-8"))
        commands = [
            hook.get("command")
            for group in data["hooks"]["SessionStart"]
            for hook in group.get("hooks", [])
            if isinstance(hook, dict)
        ]
        expected_command = "'" + str((project.resolve() / ".codex" / "hooks" / "hook_adapter.sh")).replace("'", "'\"'\"'") + "'"
        self.assertIn(expected_command, commands)
        adapter_path = project / ".codex" / "hooks" / "hook_adapter.sh"
        self.assertTrue(adapter_path.is_symlink())
        self.assertEqual(adapter_path.resolve(), central_hub_path("codex").resolve())

        registry = _read_activated_projects()
        project_key = str(project.expanduser().resolve())
        self.assertIn(project_key, registry)
        self.assertEqual(registry[project_key]["codex"]["status"], "active")

    def test_codex_activation_migrates_legacy_relative_hook_command(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "codex-legacy-project"
        project.mkdir()
        hooks_json = project / ".codex" / "hooks.json"
        hooks_json.parent.mkdir(parents=True)
        hooks_json.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "./.codex/hooks/hook_adapter.sh"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="codex", action="enable", root=self.install, target_root=project)

        data = json.loads(hooks_json.read_text(encoding="utf-8"))
        commands = [
            hook.get("command")
            for group in data["hooks"]["SessionStart"]
            for hook in group.get("hooks", [])
            if isinstance(hook, dict)
        ]
        expected_command = "'" + str((project.resolve() / ".codex" / "hooks" / "hook_adapter.sh")).replace("'", "'\"'\"'") + "'"
        self.assertIn(expected_command, commands)
        self.assertNotIn("./.codex/hooks/hook_adapter.sh", commands)

    def test_claude_activation_creates_missing_settings_file(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "claude-project"
        project.mkdir()
        from agent_context_engine.application.integrations import integration_projects_status, manage_integration_hooks
        manage_integration_hooks(client="claude", action="enable", root=self.install, target_root=project)

        config_path = project / ".claude" / "settings.json"
        self.assertTrue(config_path.exists())
        adapter_path = project / ".claude" / "hooks" / "hook_adapter.sh"
        self.assertTrue(adapter_path.is_symlink())
        self.assertEqual(adapter_path.resolve(), central_hub_path("claude").resolve())

        project_key = str(project.expanduser().resolve())
        status = integration_projects_status("claude", memory_root=self.install, current_root=project)
        project_status = next(item for item in status["activated_projects"] if item["path"] == project_key)
        self.assertEqual(project_status["hooks_state"], "enabled")
        self.assertTrue(project_status["hooks_enabled"])

    def test_claude_activation_migrates_legacy_relative_hook_command(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "claude-legacy-project"
        project.mkdir()
        settings = project / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "./.claude/hooks/hook_adapter.sh"}]}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="claude", action="enable", root=self.install, target_root=project)

        data = json.loads(settings.read_text(encoding="utf-8"))
        commands = [
            hook.get("command")
            for group in data["hooks"]["SessionStart"]
            for hook in group.get("hooks", [])
            if isinstance(hook, dict)
        ]
        expected_command = "'" + str((project.resolve() / ".claude" / "hooks" / "hook_adapter.sh")).replace("'", "'\"'\"'") + "'"
        self.assertIn(expected_command, commands)
        self.assertNotIn("./.claude/hooks/hook_adapter.sh", commands)

    def test_gemini_activation_migrates_legacy_relative_hook_command(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "gemini-legacy-project"
        project.mkdir()
        settings = project / ".gemini" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    "hooks": {
                        "BeforeTool": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "./.gemini/hooks/hook_adapter.sh BeforeTool",
                                    }
                                ]
                            }
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="gemini", action="enable", root=self.install, target_root=project)

        data = json.loads(settings.read_text(encoding="utf-8"))
        commands = [
            hook.get("command")
            for group in data["hooks"]["BeforeTool"]
            for hook in group.get("hooks", [])
            if isinstance(hook, dict)
        ]
        expected_command = "'" + str((project.resolve() / ".gemini" / "hooks" / "hook_adapter.sh")).replace("'", "'\"'\"'") + "' BeforeTool"
        self.assertIn(expected_command, commands)
        self.assertNotIn("./.gemini/hooks/hook_adapter.sh BeforeTool", commands)

    def test_codex_deactivation_renames_config_and_registry(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "project"
        project.mkdir()
        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="codex", action="enable", root=self.install, target_root=project)
        manage_integration_hooks(client="codex", action="disable", root=self.install, target_root=project)

        self.assertFalse((project / ".codex" / "hooks.json").exists())
        self.assertTrue((project / ".codex" / "hooks_deactivated.json").exists())

        registry = _read_activated_projects()
        project_key = str(project.expanduser().resolve())
        self.assertEqual(registry[project_key]["codex"]["status"], "disabled")

    def test_isolated_activation_uses_installation_metadata_root(self) -> None:
        isolated_memory_root = self.tmp / "isolated-memory"
        (self.install / "memory" / "local").mkdir(parents=True, exist_ok=True)
        (self.install / "memory" / "local" / "installation-profile.json").write_text(
            json.dumps({"storage": {"memory_root": str(isolated_memory_root)}}),
            encoding="utf-8",
        )
        project = self.tmp / "isolated-project"
        project.mkdir()
        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="codex", action="enable", root=self.install, target_root=project)

        adapter_path = project / ".codex" / "hooks" / "hook_adapter.sh"
        expected_hub = isolated_memory_root / ".agent-context-engine" / "hooks" / "codex" / "hook_adapter.sh"
        self.assertTrue(adapter_path.is_symlink())
        self.assertEqual(adapter_path.resolve(), expected_hub.resolve())
        self.assertTrue(expected_hub.exists())
        self.assertEqual(
            (isolated_memory_root / ".agent-context-engine" / "active-root").read_text(encoding="utf-8").strip(),
            str(self.install.resolve()),
        )

        registry = _read_activated_projects(installation_root=self.install)
        project_key = str(project.expanduser().resolve())
        self.assertEqual(registry[project_key]["codex"]["status"], "active")

    def test_isolated_activation_backs_up_config_under_installation_metadata(self) -> None:
        isolated_memory_root = self.tmp / "isolated-backup-memory"
        (self.install / "memory" / "local").mkdir(parents=True, exist_ok=True)
        (self.install / "memory" / "local" / "installation-profile.json").write_text(
            json.dumps({"storage": {"memory_root": str(isolated_memory_root)}}),
            encoding="utf-8",
        )
        project = self.tmp / "isolated-backup-project"
        config = project / ".codex" / "hooks.json"
        config.parent.mkdir(parents=True)
        config.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
        from agent_context_engine.application.integrations import manage_integration_hooks

        manage_integration_hooks(client="codex", action="enable", root=self.install, target_root=project)

        isolated_backup_dir = project_backup_dir(config.parent, metadata_root=isolated_memory_root)
        self.assertEqual(len(list(isolated_backup_dir.glob("hooks.json.*.bak"))), 1)
        global_backup_dir = project_backup_dir(config.parent, metadata_root=self.storage)
        self.assertFalse(global_backup_dir.exists())

    def test_default_home_memory_root_uses_home_metadata_root(self) -> None:
        default_memory_root = self.home / ".agent-context-engine" / "memory"
        (self.install / "memory" / "local").mkdir(parents=True, exist_ok=True)
        (self.install / "memory" / "local" / "installation-profile.json").write_text(
            json.dumps({"storage": {"memory_root": str(default_memory_root)}}),
            encoding="utf-8",
        )
        project = self.tmp / "default-memory-project"
        project.mkdir()
        from agent_context_engine.application.integrations import manage_integration_hooks
        manage_integration_hooks(client="claude", action="enable", root=self.install, target_root=project)

        adapter_path = project / ".claude" / "hooks" / "hook_adapter.sh"
        expected_hub = self.home / ".agent-context-engine" / "hooks" / "claude" / "hook_adapter.sh"
        self.assertTrue(adapter_path.is_symlink())
        self.assertEqual(adapter_path.resolve(), expected_hub.resolve())
        self.assertEqual(
            (self.home / ".agent-context-engine" / "active-root").read_text(encoding="utf-8").strip(),
            str(self.install.resolve()),
        )
        self.assertFalse((default_memory_root / ".agent-context-engine" / "active-root").exists())

    def test_status_accepts_legacy_registry_entry_without_installation_root(self) -> None:
        from agent_context_engine.interfaces.cli.commands.installation import _ensure_central_hub_and_active_root
        from agent_context_engine.application.integrations import integration_projects_status, manage_integration_hooks

        _ensure_central_hub_and_active_root(self.install)
        project = self.tmp / "legacy-registry-project"
        project.mkdir()
        manage_integration_hooks(client="codex", action="enable", root=self.install, target_root=project)

        project_key = str(project.expanduser().resolve())
        registry = _read_activated_projects(installation_root=self.install)
        self.assertNotIn("installation_root", registry[project_key]["codex"])
        _write_activated_projects(registry, installation_root=self.install)

        status = integration_projects_status("codex", memory_root=self.install, current_root=project)
        project_status = next(item for item in status["activated_projects"] if item["path"] == project_key)
        self.assertEqual(project_status["hooks_state"], "enabled")
        self.assertTrue(project_status["hooks_enabled"])
        self.assertEqual(project_status["registry_status"], "active")


if __name__ == "__main__":
    unittest.main()
