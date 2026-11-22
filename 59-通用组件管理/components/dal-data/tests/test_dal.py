"""dal-data 组件：输出封装、参数透传与写入门禁测试（不触网、不调真实 DAL）。"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

COMPONENT = Path(__file__).resolve().parents[1]
SCRIPTS = COMPONENT / "skill" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dal  # noqa: E402


def _proc(stdout: str = "{}", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class EnvelopeTest(unittest.TestCase):
    def test_envelope_shape(self):
        payload = dal._envelope("read", {"rows": 1})
        self.assertEqual(payload["schema_version"], "1.0")
        self.assertEqual(payload["command"], "dal-data.read")
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["data"], {"rows": 1})


class EmitTest(unittest.TestCase):
    def test_success_wraps_json(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = dal._emit("scopes", _proc('{"scopes": ["macro"]}'))
        self.assertEqual(code, 0)
        body = json.loads(buffer.getvalue())
        self.assertEqual(body["data"], {"scopes": ["macro"]})

    def test_failure_marks_not_ok(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = dal._emit("read", _proc("", returncode=1, stderr="E_DATA"))
        self.assertEqual(code, 1)
        body = json.loads(buffer.getvalue())
        self.assertFalse(body["ok"])
        self.assertIn("E_DATA", body["data"])


class GateTest(unittest.TestCase):
    def test_fetch_rejects_bad_json(self):
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = dal.main(["fetch", "--scope", "market", "--params", "not-json"])
        self.assertEqual(code, 2)
        self.assertIn("E_INPUT", json.loads(buffer.getvalue())["data"])


class PassthroughTest(unittest.TestCase):
    def test_read_builds_bridge_argv(self):
        captured = {}

        def fake_run(script, argv, timeout=600):
            captured["script"] = script
            captured["argv"] = argv
            return _proc('{"ok": true}')

        with mock.patch.object(dal, "_run", side_effect=fake_run), redirect_stdout(StringIO()):
            code = dal.main(
                [
                    "read",
                    "--sub-category",
                    "macro",
                    "--metric-name",
                    "DGS10",
                    "--start-ts",
                    "1",
                    "--end-ts",
                    "2",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(captured["script"], dal.DATA_BRIDGE)
        self.assertEqual(
            captured["argv"],
            [
                "read",
                "--table",
                "mm_metrics",
                "--sub-category",
                "macro",
                "--metric-name",
                "DGS10",
                "--limit",
                "100",
                "--start-ts",
                "1",
                "--end-ts",
                "2",
            ],
        )

    def test_tables_uses_bridge(self):
        captured = {}

        def fake_run(script, argv, timeout=600):
            captured["script"] = script
            captured["argv"] = argv
            return _proc('{"tables": [{"table": "mm_metrics"}]}')

        with mock.patch.object(dal, "_run", side_effect=fake_run), redirect_stdout(StringIO()):
            code = dal.main(["tables"])
        self.assertEqual(code, 0)
        self.assertEqual(captured["script"], dal.DATA_BRIDGE)
        self.assertEqual(captured["argv"], ["tables"])

    def test_status_uses_cloud_sync(self):
        captured = {}

        def fake_run(script, argv, timeout=600):
            captured["script"] = script
            captured["argv"] = argv
            return _proc('{"manifest": {}}')

        with mock.patch.object(dal, "_run", side_effect=fake_run), redirect_stdout(StringIO()):
            code = dal.main(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(captured["script"], dal.CLOUD_SYNC)
        self.assertEqual(captured["argv"], ["--check", "--json"])

    def test_status_reports_stale_as_success(self):
        def fake_run(script, argv, timeout=600):
            return _proc('{"fresh": false, "stale_seconds": 1800}', returncode=1)

        buffer = StringIO()
        with mock.patch.object(dal, "_run", side_effect=fake_run), redirect_stdout(buffer):
            code = dal.main(["status"])
        self.assertEqual(code, 0)
        body = json.loads(buffer.getvalue())
        self.assertTrue(body["ok"])
        self.assertFalse(body["data"]["fresh"])


if __name__ == "__main__":
    unittest.main()
