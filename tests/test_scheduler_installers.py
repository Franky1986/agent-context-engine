from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))


from agent_context_engine.application.platform.profile import PlatformFamily, platform_profile_for_family
from agent_context_engine.application.scheduler_installation import resolve_platform_scheduler_installer


class SchedulerInstallerSelectionTests(unittest.TestCase):
    def test_macos_profile_uses_launchagent_installer(self) -> None:
        installer = resolve_platform_scheduler_installer(platform_profile_for_family(PlatformFamily.MACOS))
        self.assertEqual(installer.adapter_name, "launchagent")
        self.assertEqual(installer.support_level, "supported")

    def test_windows_profile_is_experimental(self) -> None:
        installer = resolve_platform_scheduler_installer(platform_profile_for_family(PlatformFamily.WINDOWS))
        self.assertEqual(installer.adapter_name, "windows_task_scheduler")
        self.assertEqual(installer.support_level, "experimental")

    def test_linux_profile_remains_scaffolded(self) -> None:
        installer = resolve_platform_scheduler_installer(platform_profile_for_family(PlatformFamily.LINUX))
        self.assertEqual(installer.adapter_name, "systemd_user")
        self.assertEqual(installer.support_level, "scaffolded")
