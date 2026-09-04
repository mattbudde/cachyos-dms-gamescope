#!/usr/bin/env python3
"""Static checks for the integration's declarative assets."""

from __future__ import annotations

import configparser
import json
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class AssetTest(unittest.TestCase):
    def test_dms_manifest_has_expected_contract(self) -> None:
        manifest_path = PROJECT / "dms-plugin/cachyosGameMode/plugin.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["id"], "cachyosGameMode")
        self.assertEqual(manifest["type"], "composite")
        self.assertEqual(
            manifest["components"]["launcher"],
            "./GameModeLauncher.qml",
        )
        self.assertEqual(
            manifest["components"]["widget"],
            "./GameModeBar.qml",
        )
        self.assertIn("dankbar-widget", manifest["capabilities"])
        self.assertEqual(manifest["requires_dms"], ">=1.5.0")
        self.assertIn("process", manifest["permissions"])

    def test_polkit_policy_is_valid_and_narrow(self) -> None:
        policy_path = PROJECT / "polkit/org.cachyos.gamemode.policy"
        root = ElementTree.parse(policy_path).getroot()
        action = root.find("action")
        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.attrib["id"], "org.cachyos.gamemode.switch-session")
        annotation = action.find("annotate")
        self.assertIsNotNone(annotation)
        assert annotation is not None
        self.assertEqual(
            annotation.text,
            "/usr/libexec/cachyos-session-handoff",
        )
        defaults = action.find("defaults")
        self.assertIsNotNone(defaults)
        assert defaults is not None
        self.assertEqual(defaults.findtext("allow_active"), "yes")
        self.assertEqual(defaults.findtext("allow_inactive"), "no")

    def test_restore_display_autostart_only_runs_under_niri(self) -> None:
        entry_path = PROJECT / "autostart/cachyos-gamemode-restore-display.desktop"
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(entry_path.read_text(encoding="utf-8"))
        entry = parser["Desktop Entry"]
        self.assertEqual(entry["Type"], "Application")
        self.assertEqual(entry["OnlyShowIn"], "niri;")
        self.assertEqual(
            entry["Exec"],
            "/usr/local/bin/cachyos-sessionctl display restore-desktop",
        )

    def test_monitor_picker_reads_status_json_not_quickshell_screens(self) -> None:
        widget = (PROJECT / "dms-plugin/cachyosGameMode/GameModeBar.qml").read_text(
            encoding="utf-8"
        )
        self.assertFalse("Quickshell.screens" in widget, "picker still enumerates Quickshell.screens")
        self.assertTrue("display.monitors" in widget, "picker does not read report.display.monitors")


if __name__ == "__main__":
    unittest.main(verbosity=2)
