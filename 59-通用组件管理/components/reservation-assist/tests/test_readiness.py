"""就绪实验判定：证据门槛、异常演练、CLI 判定与读取。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import unittest
from datetime import datetime
from pathlib import Path

import _support
import security
from adapters.base import CN_TZ
from store import Store

BASE = int(datetime(2026, 11, 18, 0, 0, tzinfo=CN_TZ).timestamp() * 1000)


def login_samples(count: int = 30) -> list[dict]:
    return [
        {
            "adapter": "railway",
            "kind": "login",
            "at": BASE + i * 2 * 3600 * 1000,
            "ok": 1,
            "detail": {},
        }
        for i in range(count)
    ]


def ok_drills(count: int = 20) -> list[dict]:
    return [
        {
            "adapter": "railway",
            "kind": "submit",
            "at": BASE + i * 1000,
            "ok": 1,
            "detail": {"captcha": "none"},
        }
        for i in range(count)
    ]


class ReadinessTest(unittest.TestCase):
    def test_empty_evidence_not_ready(self):
        report = security.evaluate_readiness("railway", [], [])
        self.assertFalse(report["ready"])
        failed = {item["name"] for item in report["checks"] if not item["ok"]}
        self.assertEqual(failed, {"login_days", "login_samples", "submit_drills"})

    def test_full_evidence_ready(self):
        report = security.evaluate_readiness("railway", login_samples(), ok_drills())
        self.assertTrue(report["ready"], report["checks"])
        self.assertEqual(len(report["login_days"]), 3)

    def test_missing_samples_not_ready(self):
        report = security.evaluate_readiness("railway", login_samples(29), ok_drills(19))
        names = {item["name"] for item in report["checks"] if not item["ok"]}
        self.assertEqual(names, {"login_samples", "submit_drills"})

    def test_wrong_target_blocks(self):
        drills = ok_drills()
        drills[7]["ok"] = 0
        drills[7]["detail"] = {"result": "wrong_target", "captcha": "none"}
        report = security.evaluate_readiness("railway", login_samples(), drills)
        self.assertFalse(report["ready"])
        self.assertIn(
            "no_wrong_target_or_duplicate", {c["name"] for c in report["checks"] if not c["ok"]}
        )

    def test_manual_captcha_blocks(self):
        drills = ok_drills()
        drills[0]["detail"] = {"result": "ok", "captcha": "manual"}
        report = security.evaluate_readiness("railway", login_samples(), drills)
        self.assertFalse(report["ready"])
        self.assertIn("no_unhandled_captcha", {c["name"] for c in report["checks"] if not c["ok"]})

    def test_cli_check_reads_store(self):
        workdir = _support.temp_dir()
        try:
            db = Store(Path(workdir) / "state.db")
            for item in login_samples():
                db.add_drill("railway", "login", True, {"state": "ok"}, at=item["at"])
            for item in ok_drills():
                db.add_drill("railway", "submit", True, {"captcha": "none"}, at=item["at"])
            db.close()

            env = dict(os.environ, RA_STATE_DIR=workdir)
            proc = subprocess.run(
                [
                    sys.executable,
                    str(_support.SCRIPTS / "ra.py"),
                    "drill",
                    "check",
                    "--adapter",
                    "railway",
                    "--json",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertTrue(payload["readiness"]["ready"])
            self.assertEqual(payload["command"], "drill.check")

            empty = subprocess.run(
                [
                    sys.executable,
                    str(_support.SCRIPTS / "ra.py"),
                    "drill",
                    "check",
                    "--adapter",
                    "damai",
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            self.assertEqual(empty.returncode, 3)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
