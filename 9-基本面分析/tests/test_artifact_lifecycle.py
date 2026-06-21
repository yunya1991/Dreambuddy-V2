import importlib.util
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = (
        Path(__file__).resolve().parent.parent
        / "ops"
        / "nanoclaw"
        / "core_task1"
        / "scripts"
        / "artifact_lifecycle.py"
    )
    spec = importlib.util.spec_from_file_location("artifact_lifecycle", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


class TestArtifactLifecycle(unittest.TestCase):
    def test_collect_expired_files_excludes_gitkeep_and_keeps_recent(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            raw_dir = root / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / ".gitkeep").write_text("", encoding="utf-8")
            old_fp = raw_dir / "old.json"
            new_fp = raw_dir / "new.json"
            old_fp.write_text("{}", encoding="utf-8")
            new_fp.write_text("{}", encoding="utf-8")
            old_ts = mod.time.time() - 15 * 24 * 3600
            new_ts = mod.time.time()
            mod.os.utime(old_fp, (old_ts, old_ts))
            mod.os.utime(new_fp, (new_ts, new_ts))
            files = mod.collect_expired_files(raw_dir, days=7, keep_last=1, now_ts=mod.time.time())
            paths = {p.name for p in files}
            self.assertIn("old.json", paths)
            self.assertNotIn("new.json", paths)
            self.assertNotIn(".gitkeep", paths)

    def test_archive_and_restore_roundtrip(self) -> None:
        mod = _load_module()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_dir = root / "outputs"
            data_dir.mkdir(parents=True, exist_ok=True)
            fp = data_dir / "brief_v2_20260101_0100.md"
            fp.write_text("x", encoding="utf-8")
            ts = mod.time.time() - 40 * 24 * 3600
            mod.os.utime(fp, (ts, ts))
            archive_dir = root / "archive"
            res = mod.archive_expired(
                project_root=root,
                policies=[{"path": "outputs", "days": 30, "keep_last": 0}],
                archive_root=archive_dir,
                dry_run=False,
                now_ts=mod.time.time(),
            )
            self.assertTrue(res.get("ok"))
            self.assertEqual(int(res.get("moved_files") or 0), 1)
            self.assertFalse(fp.exists())
            tar_path = Path(str(res.get("archive_file") or ""))
            self.assertTrue(tar_path.exists())
            rst = mod.restore_archive(project_root=root, archive_file=tar_path, overwrite=False)
            self.assertTrue(rst.get("ok"))
            self.assertTrue(fp.exists())


if __name__ == "__main__":
    unittest.main()
