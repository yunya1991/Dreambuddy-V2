"""site-blog 发布脚本：纯函数与写入门禁测试（不联网、不部署、不碰站点产物）。"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

COMPONENT = Path(__file__).resolve().parents[1]
SCRIPTS = COMPONENT / "skill" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publish  # noqa: E402


class SlugTest(unittest.TestCase):
    def test_normalizes_to_kebab(self):
        self.assertEqual(publish._slug("Gold  Liquidity 理财"), "gold-liquidity")

    def test_truncates_long_slug(self):
        self.assertLessEqual(len(publish._slug("a" * 200)), 80)

    def test_empty_returns_empty(self):
        self.assertEqual(publish._slug(""), "")


class ComponentNameTest(unittest.TestCase):
    def test_keeps_case_for_run_id(self):
        self.assertEqual(publish._component("20261122T101500"), "20261122T101500")

    def test_strips_path_separators(self):
        self.assertEqual(publish._component("a/b c"), "a-b-c")


class ValidateTest(unittest.TestCase):
    def test_requires_title_date_summary(self):
        for missing in ("title", "date", "summary"):
            meta = {"title": "t", "date": "2026-11-22", "summary": "s"}
            meta.pop(missing)
            with self.assertRaises(ValueError):
                publish._validate(meta, "blog.md")

    def test_rejects_bad_date(self):
        with self.assertRaises(ValueError):
            publish._validate({"title": "t", "date": "2026/11/22", "summary": "s"}, "blog.md")

    def test_accepts_complete_meta(self):
        publish._validate({"title": "t", "date": "2026-11-22", "summary": "s"}, "blog.md")


class GateTest(unittest.TestCase):
    def test_requires_allow_write(self):
        buffer = StringIO()
        with mock.patch.object(sys, "argv", ["publish.py", "publish", "--file", "/nonexistent.md"]):
            with redirect_stdout(buffer):
                code = publish.main()
        self.assertEqual(code, 2)
        self.assertIn("E_GATE", json.loads(buffer.getvalue())["error"])

    def test_rejects_missing_file(self):
        buffer = StringIO()
        argv = ["publish.py", "publish", "--file", "/nonexistent.md", "--allow-write"]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(buffer):
            code = publish.main()
        self.assertEqual(code, 2)
        self.assertIn("不存在", json.loads(buffer.getvalue())["error"])

    def test_unified_cli_env_authorization_without_subcommand(self):
        """dreambuddy run 会消费 --allow-write 并通过环境变量授权；子命令可省略。"""
        buffer = StringIO()
        argv = ["publish.py", "--file", "/nonexistent.md", "--json"]
        with (
            mock.patch.dict(os.environ, {"DREAMBUDDY_ALLOW_WRITE": "1"}),
            mock.patch.object(sys, "argv", argv),
            redirect_stdout(buffer),
        ):
            code = publish.main()
        self.assertEqual(code, 2)
        self.assertIn("不存在", json.loads(buffer.getvalue())["error"])

    def test_rejects_invalid_front_matter(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False, encoding="utf-8"
        ) as handle:
            handle.write("---\ntitle: t\n---\n正文\n")
            path = handle.name
        buffer = StringIO()
        argv = ["publish.py", "publish", "--file", path, "--allow-write"]
        with mock.patch.object(sys, "argv", argv), redirect_stdout(buffer):
            code = publish.main()
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
