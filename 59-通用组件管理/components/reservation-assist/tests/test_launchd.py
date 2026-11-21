"""launchd 渲染与安装：占位符、无人值守禁提交、plist 合法性、卸载。"""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

import _support

import launchd


class LaunchdTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = _support.temp_dir()

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_render_replaces_placeholders(self):
        text = launchd.render(
            home="/var/tmp/ra-home", python="/usr/bin/python3", component_root="/var/tmp/ra-app"
        )
        self.assertEqual(launchd.validate(text), [])
        self.assertNotIn("__", text)
        self.assertIn("/var/tmp/ra-app/skill/scripts/ra.py", text)
        self.assertIn("/var/tmp/ra-home/.reservation-assist", text)

    def test_validate_rejects_unattended_submit(self):
        text = launchd.render().replace("<string>0</string>", "<string>1</string>")
        self.assertTrue(launchd.validate(text))

    def test_validate_rejects_unresolved_placeholder(self):
        self.assertTrue(launchd.validate("__HOME__/x"))

    def test_inbox_template_polls_every_two_minutes(self):
        text = launchd.render(template=launchd.TEMPLATES[launchd.INBOX_LABEL])
        self.assertEqual(launchd.validate(text, launchd.INBOX_LABEL), [])
        self.assertIn("<string>inbox</string>", text)
        self.assertIn("<integer>120</integer>", text)

    def test_install_writes_valid_plist_and_uninstall_removes(self):
        agents = Path(self.dir) / "Agents"
        targets = launchd.install(agents_dir=agents, load=False)
        self.assertEqual(len(targets), 2)
        for target in targets:
            self.assertTrue(target.is_file())
            self.assertEqual(target.stat().st_mode & 0o777, 0o644)
            self.assertFalse(launchd.validate(target.read_text(encoding="utf-8"), target.stem))

            if shutil.which("plutil"):
                lint = subprocess.run(
                    ["plutil", "-lint", str(target)], capture_output=True, text=True
                )
                self.assertEqual(lint.returncode, 0, lint.stderr)

        self.assertTrue(launchd.uninstall(agents_dir=agents))
        for target in targets:
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
