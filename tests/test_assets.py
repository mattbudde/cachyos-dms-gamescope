#!/usr/bin/env python3
"""Static checks for the integration's declarative assets."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
