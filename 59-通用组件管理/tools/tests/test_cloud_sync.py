"""P5-3b：cloud sync 封装（复用既有 dbsync）测试。"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

TOOLS_DIR = Path(__file__).resolve().parents[1]
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import cloud_sync  # noqa: E402


class SyncManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "dreambuddy_core.db"
        self.db.write_bytes(b"sqlite-bytes")
        self.cog = self.dir / "cog" / "cognitive_memory.db"
        self.cog.parent.mkdir(parents=True, exist_ok=True)
        self.cog.write_bytes(b"cog")
        for name, value in (("DAL_DIR", self.dir), ("COG_DB", self.cog)):
            patcher = mock.patch.object(cloud_sync, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_fresh_manifest(self):
        report = cloud_sync.manifest()
        self.assertTrue(report["fresh"])
        self.assertEqual(len(report["targets"]), 2)

    def test_stale_manifest(self):
        old = time.time() - cloud_sync.STALE_SECONDS - 60
        import os

        os.utime(self.db, (old, old))
        os.utime(self.cog, (old, old))
        self.assertFalse(cloud_sync.manifest()["fresh"])

    def test_check_cli_stale_exit_1(self):
        import io
        import os

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "dreambuddy_core.db"
            db.write_bytes(b"x")
            old = time.time() - cloud_sync.STALE_SECONDS - 60
            os.utime(db, (old, old))
            with (
                mock.patch.object(cloud_sync, "DAL_DIR", Path(tmp)),
                mock.patch.object(cloud_sync, "COG_DB", Path(tmp) / "absent.db"),
                redirect_stdout(io.StringIO()),
            ):
                code = cloud_sync.main(["--check"])
        self.assertEqual(code, 1)


class SyncRunTest(unittest.TestCase):
    def test_run_sync_invokes_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "mirror.sh"
            script.write_text("#!/bin/bash\necho synced\n", encoding="utf-8")
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="synced\n", stderr=""
            )
            with (
                mock.patch.object(cloud_sync, "SCRIPT", script),
                mock.patch.object(cloud_sync.subprocess, "run", return_value=completed) as runner,
            ):
                report = cloud_sync.run_sync(timeout=5)
        self.assertTrue(report["ok"])
        self.assertEqual(runner.call_args.kwargs["timeout"], 5)
        self.assertEqual(report["tail"], ["synced"])

    def test_missing_script_raises(self):
        with mock.patch.object(cloud_sync, "SCRIPT", Path("/nonexistent/mirror.sh")):
            with self.assertRaises(FileNotFoundError):
                cloud_sync.run_sync()

    def test_cli_run_prints_nested_manifest(self):
        import io

        report = {"ok": True, "tail": ["synced"], "manifest": {"targets": [], "fresh": True}}
        with mock.patch.object(cloud_sync, "run_sync", return_value=report):
            with redirect_stdout(io.StringIO()):
                code = cloud_sync.main([])
        self.assertEqual(code, 0)

    def test_cli_reports_missing_script(self):
        with mock.patch.object(cloud_sync, "SCRIPT", Path("/nonexistent/mirror.sh")):
            code = cloud_sync.main(["--json"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
