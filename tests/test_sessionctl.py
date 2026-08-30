#!/usr/bin/env python3
"""Isolated tests for the DMS memory update and greetd re-arm helpers."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SESSIONCTL = PROJECT / "src/cachyos-sessionctl"
HANDOFF = PROJECT / "src/cachyos-session-handoff"
GAMESCOPE_START = PROJECT / "src/start-gamescope-session"


class IntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="cachyos-gamemode-test-")
        self.root = Path(self.temporary.name)
        self.config = self.root / "etc/cachyos-gamemode.conf"
        self.memory = (
            self.root
            / "var/cache/dms-greeter/.local/state/memory.json"
        )
        self.runfile = self.root / "run/greetd.run"
        self.config.parent.mkdir(parents=True)
        self.memory.parent.mkdir(parents=True)
        self.runfile.parent.mkdir(parents=True)
        self.config.write_text(
            "\n".join(
                (
                    "[session]",
                    "login_user = test-user",
                    "desktop_session = niri.desktop",
                    "gamescope_session = gamescope-session.desktop",
                    "dms_cache_dir = /var/cache/dms-greeter",
                    "greetd_runfile = /run/greetd.run",
                    "greetd_service = greetd.service",
                    "",
                )
            ),
            encoding="utf-8",
        )
        self.original = {
            "lastSuccessfulUser": "test-user",
            "lastSessionDesktopId": "niri.desktop",
            "lastSessionId": "/usr/share/wayland-sessions/niri.desktop",
            "unrelatedSetting": 42,
        }
        self.write_memory(self.original)
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "CACHYOS_GAMEMODE_TESTING": "1",
                "CACHYOS_GAMEMODE_TEST_ROOT": str(self.root),
                "XDG_CURRENT_DESKTOP": "niri",
            }
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_memory(self, value: dict[str, object]) -> None:
        self.memory.write_text(json.dumps(value) + "\n", encoding="utf-8")

    def read_memory(self) -> dict[str, object]:
        return json.loads(self.memory.read_text(encoding="utf-8"))

    def run_sessionctl(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(SESSIONCTL), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=environment or self.environment,
        )

    def make_handoff(self, exit_status: int) -> Path:
        path = self.root / "fake-handoff"
        path.write_text(
            f"#!/usr/bin/env sh\nexit {exit_status}\n",
            encoding="utf-8",
        )
        path.chmod(0o755)
        return path

    def test_set_gamescope_preserves_other_memory(self) -> None:
        result = self.run_sessionctl("set", "gamescope")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = self.read_memory()
        self.assertEqual(value["lastSessionDesktopId"], "gamescope-session.desktop")
        self.assertEqual(
            value["lastSessionId"],
            "/usr/share/wayland-sessions/gamescope-session.desktop",
        )
        self.assertEqual(value["unrelatedSetting"], 42)

    def test_set_desktop_selects_configured_session(self) -> None:
        self.write_memory(
            {
                **self.original,
                "lastSessionDesktopId": "gamescope-session.desktop",
                "lastSessionExec": "stale-command",
            }
        )
        result = self.run_sessionctl("set", "desktop")
        self.assertEqual(result.returncode, 0, result.stderr)
        value = self.read_memory()
        self.assertEqual(value["lastSessionDesktopId"], "niri.desktop")
        self.assertNotIn("lastSessionExec", value)

    def test_failed_live_handoff_rolls_memory_back(self) -> None:
        environment = self.environment | {
            "CACHYOS_GAMEMODE_TEST_HANDOFF": str(self.make_handoff(7))
        }
        result = self.run_sessionctl(
            "switch", "gamescope", "--yes", environment=environment
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("status 7", result.stderr)
        self.assertEqual(self.read_memory(), self.original)

    def test_successful_live_handoff_keeps_new_memory(self) -> None:
        environment = self.environment | {
            "CACHYOS_GAMEMODE_TEST_HANDOFF": str(self.make_handoff(0))
        }
        result = self.run_sessionctl(
            "switch", "gamescope", "--yes", environment=environment
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.read_memory()["lastSessionDesktopId"],
            "gamescope-session.desktop",
        )

    def test_switch_requires_an_explicit_confirmation_mode(self) -> None:
        result = self.run_sessionctl("switch", "gamescope")
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires --confirm or --yes", result.stderr)
        self.assertEqual(self.read_memory(), self.original)

    def test_unsafe_session_id_is_rejected(self) -> None:
        content = self.config.read_text(encoding="utf-8")
        self.config.write_text(
            content.replace("niri.desktop", "../niri.desktop"),
            encoding="utf-8",
        )
        result = self.run_sessionctl("set", "desktop")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unsafe desktop session id", result.stderr)
        self.assertEqual(self.read_memory(), self.original)

    def test_compact_status_reports_active_and_remembered(self) -> None:
        result = self.run_sessionctl("status", "--compact")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Active: niri", result.stdout)
        self.assertIn("next/remembered: niri.desktop", result.stdout)

    @unittest.skipIf(os.geteuid() == 0, "root helper test mode is intentionally disabled")
    def test_privileged_helper_rearms_runfile_in_test_mode(self) -> None:
        self.runfile.touch()
        result = subprocess.run(
            [str(HANDOFF), "gamescope"],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.runfile.exists())
        self.assertIn("would restart greetd.service", result.stdout)

    def test_gamescope_launcher_clears_stale_desktop_environment(self) -> None:
        checker = self.root / "check-gamescope-environment"
        checker.write_text(
            """#!/usr/bin/env sh
for name in WAYLAND_DISPLAY DISPLAY XAUTHORITY NIRI_SOCKET SWAYSOCK HYPRLAND_INSTANCE_SIGNATURE; do
    eval 'test -z "${'"$name"'+x}"' || exit 10
done
""",
            encoding="utf-8",
        )
        checker.chmod(0o755)
        environment = self.environment | {
            "CACHYOS_GAMEMODE_TEST_START": str(checker),
            "WAYLAND_DISPLAY": "wayland-1",
            "DISPLAY": ":0",
            "XAUTHORITY": "/tmp/old-xauthority",
            "NIRI_SOCKET": "/run/user/1000/niri.sock",
            "SWAYSOCK": "/run/user/1000/sway.sock",
            "HYPRLAND_INSTANCE_SIGNATURE": "old-session",
        }
        result = subprocess.run(
            [str(GAMESCOPE_START)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
