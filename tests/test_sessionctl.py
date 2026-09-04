#!/usr/bin/env python3
"""Isolated tests for the DMS memory update and greetd re-arm helpers."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SESSIONCTL = PROJECT / "src/cachyos-sessionctl"
HANDOFF = PROJECT / "src/cachyos-session-handoff"
GAMESCOPE_START = PROJECT / "src/start-gamescope-session"


def load_sessionctl():
    loader = importlib.machinery.SourceFileLoader("cachyos_sessionctl", str(SESSIONCTL))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # dataclass field resolution reads sys.modules[cls.__module__] for the deferred annotations
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


class ParseNiriOutputsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sessionctl = load_sessionctl()

    def test_keeps_disabled_outputs_and_tolerates_odd_fields(self) -> None:
        reply = {
            "HDMI-A-2": {
                "name": "HDMI-A-2",
                "make": 7,
                "model": "Fire Stick",
                "serial": None,
                "logical": None,
            },
            "DP-1": {
                "name": "DP-1",
                "make": "Vendor",
                "model": None,
                "modes": [],
                "logical": {"x": 0, "y": 0},
            },
            "junk": "not an output",
        }
        monitors = self.sessionctl.parse_niri_outputs(reply)
        self.assertEqual([monitor.connector for monitor in monitors], ["DP-1", "HDMI-A-2"])
        self.assertEqual([monitor.enabled for monitor in monitors], [True, False])
        self.assertEqual([monitor.label for monitor in monitors], ["Vendor", "Fire Stick"])
        self.assertIsNone(monitors[1].make)

    def test_label_falls_back_to_the_connector(self) -> None:
        monitors = self.sessionctl.parse_niri_outputs({"eDP-1": {"logical": None}})
        self.assertEqual(monitors[0].label, "eDP-1")

    def test_rejects_a_reply_that_is_not_an_object(self) -> None:
        with self.assertRaises(self.sessionctl.SessionError):
            self.sessionctl.parse_niri_outputs([])


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
        self.config_home = self.root / "home/.config"
        self.display_conf = self.config_home / "cachyos-gamemode/display.conf"
        self.config.parent.mkdir(parents=True)
        self.memory.parent.mkdir(parents=True)
        self.runfile.parent.mkdir(parents=True)
        self.config_home.mkdir(parents=True)
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
        self.config.chmod(0o644)
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
                "XDG_CONFIG_HOME": str(self.config_home),
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

    def test_display_set_persists_connector_without_auto(self) -> None:
        result = self.run_sessionctl("display", "set", "gamescope", "DP-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.run_sessionctl("display", "set", "desktop", "eDP-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.display_conf.read_text(encoding="utf-8"),
            "[display]\ngamescope_output = DP-1\ndesktop_primary = eDP-1\n",
        )

        result = self.run_sessionctl("display", "prefer-output")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "DP-1,*\n")

        result = self.run_sessionctl("display", "set", "gamescope", "auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.display_conf.read_text(encoding="utf-8"),
            "[display]\ndesktop_primary = eDP-1\n",
        )
        result = self.run_sessionctl("display", "prefer-output")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_display_set_mode_persists_and_keeps_connectors(self) -> None:
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-1")
        result = self.run_sessionctl("display", "set", "mode", "1920x1080@60")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.display_conf.read_text(encoding="utf-8"),
            "[display]\ngamescope_output = HDMI-A-1\ngamescope_mode = 1920x1080@60\n",
        )
        result = self.run_sessionctl("display", "prefer-mode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "1920x1080@60\n")

        result = self.run_sessionctl("display", "set", "gamescope", "DP-1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.display_conf.read_text(encoding="utf-8"),
            "[display]\ngamescope_output = DP-1\ngamescope_mode = 1920x1080@60\n",
        )

        result = self.run_sessionctl("display", "set", "mode", "auto")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.display_conf.read_text(encoding="utf-8"),
            "[display]\ngamescope_output = DP-1\n",
        )
        result = self.run_sessionctl("display", "prefer-mode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_display_prefer_mode_is_empty_without_a_preference(self) -> None:
        result = self.run_sessionctl("display", "prefer-mode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.display_conf.exists())

    def test_display_set_rejects_invalid_modes(self) -> None:
        for value in (
            "1920x1080",
            "1920x1080@",
            "0x1080@60",
            "1920x0@60",
            "1920x1080@0",
            "3840x2160@60Hz",
        ):
            with self.subTest(value=value):
                result = self.run_sessionctl("display", "set", "mode", value)
                self.assertEqual(result.returncode, 1)
                self.assertIn("not a Gamescope mode", result.stderr)
        self.assertFalse(self.display_conf.exists())

    def test_display_prefer_output_is_empty_without_a_preference(self) -> None:
        result = self.run_sessionctl("display", "prefer-output")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertFalse(self.display_conf.exists())

    def test_display_set_rejects_unsafe_connectors(self) -> None:
        for value in ("*", "DP-1,*", "DP 1", "DP-1=x", '"DP-1"', "/dev/dri/card0", "", "eDP"):
            with self.subTest(value=value):
                result = self.run_sessionctl("display", "set", "gamescope", value)
                self.assertEqual(result.returncode, 1)
                self.assertIn("not a DRM connector name", result.stderr)
        self.assertFalse(self.display_conf.exists())

    def test_display_set_accepts_common_connector_names(self) -> None:
        for value in ("eDP-1", "DP-1", "HDMI-A-1", "DVI-D-2"):
            with self.subTest(value=value):
                result = self.run_sessionctl("display", "set", "gamescope", value)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_display_prefer_output_fails_on_a_corrupt_file(self) -> None:
        self.display_conf.parent.mkdir(parents=True)
        self.display_conf.write_text("[display]\ngamescope_output = DP-1,*\n", encoding="utf-8")
        result = self.run_sessionctl("display", "prefer-output")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not a DRM connector name", result.stderr)

    def test_status_json_reports_display_preferences(self) -> None:
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-1")
        self.make_fake_niri(self.enabled("DP-1"))
        result = self.run_sessionctl("status", "--json", environment=self.niri_environment())
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["active"], "niri")
        self.assertEqual(report["remembered"], "niri.desktop")
        self.assertEqual(
            report["display"],
            {
                "gamescope_output": "HDMI-A-1",
                "gamescope_prefer_output": "HDMI-A-1,*",
                "gamescope_mode": None,
                "desktop_primary": None,
                "monitors": [
                    {"connector": "DP-1", "label": "Model DP-1", "enabled": True, "present": True},
                    {"connector": "HDMI-A-1", "label": "HDMI-A-1", "enabled": False, "present": False},
                ],
            },
        )

    def test_status_json_reports_a_pinned_gamescope_mode(self) -> None:
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-1")
        self.run_sessionctl("display", "set", "mode", "1920x1080@60")
        result = self.run_sessionctl("status", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        display = json.loads(result.stdout)["display"]
        self.assertEqual(display["gamescope_mode"], "1920x1080@60")
        self.assertEqual(display["gamescope_prefer_output"], "HDMI-A-1,*")

    def test_status_json_lists_connected_monitors_including_disabled(self) -> None:
        self.make_fake_niri(self.enabled("HDMI-A-2") | self.disabled("DP-1"))
        result = self.run_sessionctl("status", "--json", environment=self.niri_environment())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout)["display"]["monitors"],
            [
                {"connector": "DP-1", "label": "Model DP-1", "enabled": False, "present": True},
                {"connector": "HDMI-A-2", "label": "Model HDMI-A-2", "enabled": True, "present": True},
            ],
        )

    def test_status_json_monitors_is_null_outside_niri(self) -> None:
        log = self.make_fake_niri(self.enabled("DP-1"))
        result = self.run_sessionctl(
            "status", "--json", environment=self.niri_environment("KDE")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIsNone(json.loads(result.stdout)["display"]["monitors"])
        self.assertEqual(self.niri_calls(log), [])

    def test_status_json_degrades_monitors_when_niri_fails(self) -> None:
        self.make_failing_niri()
        result = self.run_sessionctl("status", "--json", environment=self.niri_environment())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIsNone(json.loads(result.stdout)["display"]["monitors"])

    def test_display_list_marks_off_monitors_and_the_pinned_role(self) -> None:
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-2")
        self.run_sessionctl("display", "set", "desktop", "DP-1")
        self.make_fake_niri(self.enabled("DP-1") | self.disabled("HDMI-A-2"))
        result = self.run_sessionctl("display", "list", environment=self.niri_environment())
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = {line.split()[0]: line for line in result.stdout.splitlines()[1:]}
        self.assertRegex(rows["DP-1"], r"\bon\b.*Model DP-1.*\bdesktop\b")
        self.assertRegex(rows["HDMI-A-2"], r"\boff\b.*Model HDMI-A-2.*\bgamescope\b")

    def test_display_list_fails_loudly_when_niri_fails(self) -> None:
        self.make_failing_niri()
        result = self.run_sessionctl("display", "list", environment=self.niri_environment())
        self.assertEqual(result.returncode, 1)
        self.assertIn("niri", result.stderr)

    def test_display_list_is_a_single_line_outside_niri(self) -> None:
        log = self.make_fake_niri(self.enabled("DP-1"))
        result = self.run_sessionctl(
            "display", "list", environment=self.niri_environment("KDE")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1)
        self.assertEqual(self.niri_calls(log), [])

    def make_fake_niri(
        self,
        first_outputs: dict[str, object],
        later_outputs: dict[str, object] | None = None,
    ) -> Path:
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir(exist_ok=True)
        replies = self.root / "niri-replies"
        replies.mkdir(exist_ok=True)
        (replies / "next.json").write_text(json.dumps(first_outputs), encoding="utf-8")
        if later_outputs is not None:
            (replies / "after.json").write_text(json.dumps(later_outputs), encoding="utf-8")
        log = self.root / "niri.log"
        (bin_dir / "niri").write_text(
            f"""#!/usr/bin/env sh
printf '%s\\n' "$*" >> {log}
case "$*" in
    "msg --json outputs")
        cat {replies}/next.json
        [ -e {replies}/after.json ] && mv -f {replies}/after.json {replies}/next.json
        ;;
    "msg action focus-monitor "*) ;;
    *) exit 2 ;;
esac
exit 0
""",
            encoding="utf-8",
        )
        (bin_dir / "niri").chmod(0o755)
        return log

    def make_failing_niri(self) -> Path:
        bin_dir = self.root / "fake-bin"
        bin_dir.mkdir(exist_ok=True)
        log = self.root / "niri.log"
        (bin_dir / "niri").write_text(
            f"#!/usr/bin/env sh\nprintf '%s\\n' \"$*\" >> {log}\nexit 2\n",
            encoding="utf-8",
        )
        (bin_dir / "niri").chmod(0o755)
        return log

    def niri_environment(self, desktop: str = "niri") -> dict[str, str]:
        return self.environment | {
            "PATH": f"{self.root / 'fake-bin'}:{self.environment['PATH']}",
            "XDG_CURRENT_DESKTOP": desktop,
        }

    def niri_calls(self, log: Path) -> list[str]:
        if not log.exists():
            return []
        return log.read_text(encoding="utf-8").splitlines()

    @staticmethod
    def output(name: str, enabled: bool) -> dict[str, object]:
        return {
            "name": name,
            "make": "Fixture",
            "model": f"Model {name}",
            "serial": None,
            "logical": {"x": 0, "y": 0} if enabled else None,
        }

    @classmethod
    def enabled(cls, *names: str) -> dict[str, object]:
        return {name: cls.output(name, True) for name in names}

    @classmethod
    def disabled(cls, *names: str) -> dict[str, object]:
        return {name: cls.output(name, False) for name in names}

    def test_restore_desktop_is_a_no_op_outside_niri(self) -> None:
        log = self.make_fake_niri(self.enabled("DP-1"))
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment("KDE")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.niri_calls(log), [])

    def test_restore_desktop_focuses_the_internal_panel_by_default(self) -> None:
        log = self.make_fake_niri(self.enabled("HDMI-A-1", "eDP-1", "DP-2"))
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.niri_calls(log),
            ["msg --json outputs", "msg action focus-monitor eDP-1"],
        )

    def test_restore_desktop_falls_back_to_the_first_name_without_a_panel(self) -> None:
        log = self.make_fake_niri(self.enabled("HDMI-A-1", "DP-2", "DP-1"))
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("msg action focus-monitor DP-1", self.niri_calls(log))

    def test_restore_desktop_prefers_the_saved_primary_when_connected(self) -> None:
        self.run_sessionctl("display", "set", "desktop", "DP-2")
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-1")
        log = self.make_fake_niri(self.enabled("HDMI-A-1", "eDP-1", "DP-2"))
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("msg action focus-monitor DP-2", self.niri_calls(log))

    def test_restore_desktop_ignores_a_disconnected_saved_primary(self) -> None:
        self.run_sessionctl("display", "set", "desktop", "DP-9")
        log = self.make_fake_niri(self.enabled("DP-1", "eDP-1") | self.disabled("DP-3"))
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("msg action focus-monitor eDP-1", self.niri_calls(log))

    def test_restore_desktop_waits_while_only_disabled_outputs_are_reported(self) -> None:
        log = self.make_fake_niri(
            self.disabled("DP-1"), later_outputs=self.enabled("DP-1")
        )
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.niri_calls(log),
            ["msg --json outputs", "msg --json outputs", "msg action focus-monitor DP-1"],
        )

    def test_restore_desktop_retries_until_niri_reports_outputs(self) -> None:
        log = self.make_fake_niri({}, later_outputs=self.enabled("DP-1"))
        result = self.run_sessionctl(
            "display", "restore-desktop", environment=self.niri_environment()
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.niri_calls(log),
            ["msg --json outputs", "msg --json outputs", "msg action focus-monitor DP-1"],
        )

    def test_status_reports_display_lines(self) -> None:
        self.run_sessionctl("display", "set", "desktop", "eDP-1")
        result = self.run_sessionctl("status")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Gamescope output:   auto", result.stdout)
        self.assertIn("Desktop primary:    eDP-1", result.stdout)

    def plant_install(self) -> None:
        bindir = self.root / "usr/local/bin"
        libexec = self.root / "usr/libexec"
        polkit = self.root / "usr/share/polkit-1/actions"
        sessions = self.root / "usr/share/wayland-sessions"
        plugin = self.config_home / "DankMaterialShell/plugins/cachyosGameMode"
        autostart = self.config_home / "autostart"
        for directory in (bindir, libexec, polkit, sessions, plugin, autostart):
            directory.mkdir(parents=True, exist_ok=True)
        copies = {
            PROJECT / "src/cachyos-sessionctl": bindir / "cachyos-sessionctl",
            PROJECT / "src/cachyos-session-handoff": libexec / "cachyos-session-handoff",
            PROJECT / "src/start-gamescope-session": bindir / "start-gamescope-session",
            PROJECT / "src/steamos-session-select": bindir / "steamos-session-select",
            PROJECT / "polkit/org.cachyos.gamemode.policy": polkit
            / "org.cachyos.gamemode.policy",
            PROJECT / "dms-plugin/cachyosGameMode/plugin.json": plugin / "plugin.json",
            PROJECT
            / "autostart/cachyos-gamemode-restore-display.desktop": autostart
            / "cachyos-gamemode-restore-display.desktop",
        }
        for source, destination in copies.items():
            shutil.copy(source, destination)
        pkexec = bindir / "pkexec"
        pkexec.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        for executable in (
            bindir / "cachyos-sessionctl",
            bindir / "start-gamescope-session",
            bindir / "steamos-session-select",
            bindir / "pkexec",
            libexec / "cachyos-session-handoff",
        ):
            executable.chmod(0o755)
        (sessions / "niri.desktop").write_text("[Desktop Entry]\nName=niri\n")
        (sessions / "gamescope-session.desktop").write_text(
            "[Desktop Entry]\nName=Gamescope\n"
        )
        (self.root / "etc/os-release").write_text("ID=cachyos\n", encoding="utf-8")

    def doctor_environment(
        self, *path_prefix: Path, desktop: str = "niri"
    ) -> dict[str, str]:
        prefixes = path_prefix or (self.root / "usr/local/bin",)
        return self.environment | {
            "PATH": ":".join((*(str(path) for path in prefixes), self.environment["PATH"])),
            "XDG_CURRENT_DESKTOP": desktop,
        }

    def run_doctor(
        self, *arguments: str, environment: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return self.run_sessionctl(
            "doctor", *arguments, environment=environment or self.doctor_environment()
        )

    @staticmethod
    def doctor_by_id(result: subprocess.CompletedProcess[str]) -> dict[str, dict]:
        report = json.loads(result.stdout)
        return {item["id"]: item for item in report["checks"]}

    def test_doctor_reports_failures_without_install(self) -> None:
        result = self.run_doctor("--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertFalse(report["ok"])
        self.assertGreater(report["fail"], 0)
        checks = self.doctor_by_id(result)
        self.assertEqual(checks["config"]["status"], "ok")
        self.assertEqual(checks["memory"]["status"], "ok")
        for check_id in (
            "session-desktops",
            "bin-sessionctl",
            "bin-handoff",
            "bin-shim",
            "bin-steamos",
            "polkit",
            "plugin-files",
        ):
            self.assertEqual(checks[check_id]["status"], "fail", check_id)
        self.assertEqual(checks["autostart"]["status"], "warn")
        self.assertEqual(checks["os"]["status"], "warn")
        self.assertNotIn("display-manager", checks)
        self.assertNotIn("autologin", checks)

    def test_doctor_passes_a_planted_install(self) -> None:
        self.plant_install()
        result = self.run_doctor("--json")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertTrue(report["ok"])
        self.assertEqual(report["fail"], 0)
        checks = self.doctor_by_id(result)
        for check_id in (
            "config",
            "config-perms",
            "session-desktops",
            "bin-sessionctl",
            "bin-handoff",
            "bin-shim",
            "bin-steamos",
            "polkit",
            "pkexec",
            "memory",
            "plugin-files",
            "autostart",
            "gamescope-output",
            "short-session",
            "os",
        ):
            self.assertEqual(checks[check_id]["status"], "ok", checks[check_id])
        self.assertNotIn("display-manager", checks)
        self.assertNotIn("plugin-enabled", checks)
        self.assertNotIn("plugin-widget", checks)

    def test_doctor_fails_when_config_is_missing(self) -> None:
        self.config.unlink()
        result = self.run_doctor("--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.doctor_by_id(result)["config"]["status"], "fail")

    def test_doctor_rejects_world_writable_config(self) -> None:
        self.plant_install()
        self.config.chmod(0o666)
        result = self.run_doctor("--json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.doctor_by_id(result)["config-perms"]["status"], "fail")

    def test_doctor_fails_when_shim_is_shadowed_on_path(self) -> None:
        self.plant_install()
        shadowed = self.root / "usr/bin"
        shadowed.mkdir(parents=True)
        shutil.copy(
            self.root / "usr/local/bin/start-gamescope-session",
            shadowed / "start-gamescope-session",
        )
        (shadowed / "start-gamescope-session").chmod(0o755)
        result = self.run_doctor(
            "--json",
            environment=self.doctor_environment(
                shadowed, self.root / "usr/local/bin"
            ),
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(self.doctor_by_id(result)["bin-shim"]["status"], "fail")

    def test_doctor_warns_about_the_short_session_guard(self) -> None:
        self.plant_install()
        guard = self.config_home / "inhibit-short-session-tracker"
        guard.write_text("", encoding="utf-8")
        result = self.run_doctor("--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        check = self.doctor_by_id(result)["short-session"]
        self.assertEqual(check["status"], "warn")
        self.assertIn(str(guard), check["hint"])

    def test_doctor_warns_when_gamescope_output_is_unplugged(self) -> None:
        self.plant_install()
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-1")
        self.make_fake_niri(self.enabled("eDP-1"))
        result = self.run_doctor(
            "--json",
            environment=self.doctor_environment(
                self.root / "fake-bin", self.root / "usr/local/bin"
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.doctor_by_id(result)["gamescope-output"]["status"], "warn")

    def test_doctor_accepts_a_pinned_monitor_that_is_off_on_the_desktop(self) -> None:
        self.plant_install()
        self.run_sessionctl("display", "set", "gamescope", "HDMI-A-2")
        log = self.make_fake_niri(self.enabled("eDP-1") | self.disabled("HDMI-A-2"))
        result = self.run_doctor(
            "--json",
            environment=self.doctor_environment(
                self.root / "fake-bin", self.root / "usr/local/bin"
            ),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        check = self.doctor_by_id(result)["gamescope-output"]
        self.assertEqual(check["status"], "ok", check)
        self.assertIn("off on the desktop", check["summary"])
        self.assertEqual(self.niri_calls(log), ["msg --json outputs"])

    def test_doctor_ignores_missing_autostart_outside_niri(self) -> None:
        self.plant_install()
        autostart = (
            self.config_home / "autostart/cachyos-gamemode-restore-display.desktop"
        )
        autostart.unlink()
        result = self.run_doctor(
            "--json", environment=self.doctor_environment(desktop="KDE")
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.doctor_by_id(result)["autostart"]["status"], "ok")

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

    STALE_DESKTOP_ENVIRONMENT = {
        "WAYLAND_DISPLAY": "wayland-1",
        "DISPLAY": ":0",
        "XAUTHORITY": "/tmp/old-xauthority",
        "NIRI_SOCKET": "/run/user/1000/niri.sock",
        "SWAYSOCK": "/run/user/1000/sway.sock",
        "HYPRLAND_INSTANCE_SIGNATURE": "old-session",
        "OUTPUT_CONNECTOR": "HDMI-A-2,*",
    }
    UNSET_CHECK = """
for name in WAYLAND_DISPLAY DISPLAY XAUTHORITY NIRI_SOCKET SWAYSOCK HYPRLAND_INSTANCE_SIGNATURE OUTPUT_CONNECTOR; do
    eval 'test -z "${'"$name"'+x}"' || exit 10
done
"""

    def run_gamescope_start(self, checker_body: str) -> subprocess.CompletedProcess[str]:
        checker = self.root / "check-gamescope-environment"
        checker.write_text(f"#!/usr/bin/env sh\n{checker_body}\n", encoding="utf-8")
        checker.chmod(0o755)
        environment = self.environment | self.STALE_DESKTOP_ENVIRONMENT | {
            "CACHYOS_GAMEMODE_TEST_START": str(checker),
        }
        return subprocess.run(
            [str(GAMESCOPE_START)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )

    def test_gamescope_launcher_clears_stale_desktop_environment(self) -> None:
        result = self.run_gamescope_start(self.UNSET_CHECK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gamescope_launcher_exports_the_saved_output_connector(self) -> None:
        self.run_sessionctl("display", "set", "gamescope", "DP-1")
        result = self.run_gamescope_start('[ "$OUTPUT_CONNECTOR" = "DP-1,*" ] || exit 11')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gamescope_launcher_leaves_output_connector_unset_on_auto(self) -> None:
        self.run_sessionctl("display", "set", "desktop", "eDP-1")
        result = self.run_gamescope_start(self.UNSET_CHECK)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_gamescope_launcher_starts_despite_a_corrupt_preference(self) -> None:
        self.display_conf.parent.mkdir(parents=True)
        self.display_conf.write_text("not an ini file\n", encoding="utf-8")
        result = self.run_gamescope_start(self.UNSET_CHECK)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("using Gamescope defaults", result.stderr)

    def run_gamescope_start_with_fake_binary(
        self, starter_body: str
    ) -> tuple[subprocess.CompletedProcess[str], Path]:
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        argv_log = self.root / "gamescope.argv"
        gamescope = fake_bin / "gamescope"
        gamescope.write_text(
            "#!/usr/bin/env sh\n"
            f"printf '%s\\n' \"$*\" > '{argv_log}'\n",
            encoding="utf-8",
        )
        gamescope.chmod(0o755)
        starter = self.root / "start-official"
        starter.write_text(f"#!/usr/bin/env sh\n{starter_body}\n", encoding="utf-8")
        starter.chmod(0o755)
        environment = self.environment | self.STALE_DESKTOP_ENVIRONMENT | {
            "CACHYOS_GAMEMODE_TEST_START": str(starter),
            "PATH": f"{fake_bin}:{self.environment.get('PATH', '')}",
        }
        result = subprocess.run(
            [str(GAMESCOPE_START)],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        return result, argv_log

    def test_gamescope_launcher_injects_output_mode_flags(self) -> None:
        self.run_sessionctl("display", "set", "mode", "1920x1080@60")
        result, argv_log = self.run_gamescope_start_with_fake_binary("exec gamescope extra")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv_log.read_text(encoding="utf-8"), "-W 1920 -H 1080 -r 60 extra\n")

    def test_gamescope_launcher_does_not_inject_mode_flags_on_auto(self) -> None:
        result, argv_log = self.run_gamescope_start_with_fake_binary("exec gamescope extra")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv_log.read_text(encoding="utf-8"), "extra\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
