"""隐私回归：redact 覆盖日志/事件/报告/--json，真实凭据 0 命中。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import _support
import security
from store import Store

PHONE = "13812345678"
ID_CARD = "110101199001011234"
COOKIE = "SESSION=abc123def456"


class PrivacyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = _support.temp_dir()

    def tearDown(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_redact_phone_keeps_last_four(self):
        out = security.redact("联系 {}".format(PHONE))
        self.assertNotIn(PHONE, out)
        self.assertIn("138****5678", out)

    def test_redact_id_card(self):
        out = security.redact("证件 {}".format(ID_CARD))
        self.assertNotIn(ID_CARD, out)
        self.assertIn("1101", out)
        self.assertIn("1234", out)

    def test_redact_cookie_and_address(self):
        out = security.redact("Cookie: {}\n地址：北京市朝阳区某某路1号".format(COOKIE))
        self.assertNotIn("abc123def456", out)
        self.assertIn("[REDACTED]", out)
        self.assertNotIn("朝阳区某某路", out)
        self.assertIn("北京***", out)

    def test_report_and_json_output_are_redacted(self):
        db = Store(Path(self.dir) / "state.db")
        db.add_task(_support.make_task())
        db.upsert_hit("task1", "f" * 64, 1763635200000)
        db.add_event(
            "info",
            "note",
            "task1",
            {
                "phone": PHONE,
                "id_card": ID_CARD,
                "cookie": COOKIE,
                "address": "北京市朝阳区某某路1号",
            },
        )
        db.close()

        env = dict(os.environ, RA_STATE_DIR=self.dir)
        proc = subprocess.run(
            [sys.executable, str(_support.SCRIPTS / "ra.py"), "report", "--json"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for secret in (PHONE, ID_CARD, "abc123def456", "朝阳区某某路"):
            self.assertNotIn(secret, proc.stdout)

        payload = json.loads(proc.stdout)
        self.assertEqual(payload["command"], "report")
        self.assertTrue(payload["limits"])
        self.assertEqual(payload["events"][0]["payload"]["phone"], "138****5678")
        self.assertEqual(payload["events"][0]["payload"]["cookie"], "[REDACTED]")
        self.assertEqual(payload["events"][0]["payload"]["address"], "北京***")

        from jsonschema import validate

        profile = json.loads(
            (
                Path(_support.COMPONENT_ROOT).parents[1] / "contracts" / "output.schema.json"
            ).read_text(encoding="utf-8")
        )["profiles"]["reservation.v1"]
        validate(instance=payload, schema=profile)


if __name__ == "__main__":
    unittest.main()
