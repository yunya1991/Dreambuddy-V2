"""外部源自动沉淀流水线测试：inbox 合并幂等 + 合并协议 + 内存门禁 + 增量选取。

对应 SPEC-33-外部源自动沉淀流水线 §8.4 合并协议与 §8.6 验收门禁 G1/G4/G5。
"""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

REA_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REA_DIR / "scripts"))

import merge_external_inbox as merge  # noqa: E402
import verify_external_sources as verify  # noqa: E402


def _main_doc() -> dict:
    return {
        "version": "2.1",
        "generated_at": "2026-11-01",
        "sources": [
            {
                "id": "existing",
                "category": "finance_models",
                "priority": "P2",
                "level": "qualified",
                "source_type": "github_repo",
                "location": "https://github.com/acme/existing",
                "label": "acme/existing",
                "license": "MIT",
                "stars": 900,
                "verified": True,
                "discovered_from": "2-KNOWLEDGE/a.md",
            }
        ],
    }


class TestMergeProtocol(unittest.TestCase):
    def test_new_entry_added_and_id_unique(self):
        main = _main_doc()
        payload = {
            "sources": [
                {
                    "id": "existing",
                    "location": "https://github.com/acme/other",
                    "category": "dsh",
                    "priority": "P3",
                    "discovered_from": "b.md",
                }
            ]
        }
        stats = merge.merge_payload(main, [payload], "2026-11-02")
        self.assertEqual(stats["added"], 1)
        self.assertEqual(stats["id_conflict"], 1)
        self.assertEqual(main["sources"][-1]["id"], "existing-2")
        self.assertEqual(main["sources"][-1]["level"], "candidate")

    def test_idempotent_second_run_changes_nothing(self):
        main = _main_doc()
        payload = {
            "sources": [
                {"id": "neo", "location": "https://github.com/neo/repo", "discovered_from": "b.md"}
            ]
        }
        merge.merge_payload(main, [payload], "2026-11-02")
        h1 = merge.content_hash(main)
        stats2 = merge.merge_payload(main, [copy.deepcopy(payload)], "2026-11-03")
        h2 = merge.content_hash(main)
        self.assertEqual(stats2["added"], 0)
        self.assertEqual(stats2["skipped"], 1)
        self.assertEqual(h1, h2, "重复合并必须幂等（G5）")

    def test_trailing_slash_and_case_are_same_key(self):
        main = _main_doc()
        payload = {
            "sources": [{"location": "https://github.com/Acme/Existing/", "category": "dsh"}]
        }
        stats = merge.merge_payload(main, [payload], "2026-11-02")
        self.assertEqual(stats["added"], 0)
        self.assertEqual(len(main["sources"]), 1)

    def test_category_conflict_higher_priority_wins(self):
        main = _main_doc()
        payload = {
            "sources": [
                {
                    "location": "https://github.com/acme/existing",
                    "category": "dsh",
                    "priority": "P0",
                }
            ]
        }
        stats = merge.merge_payload(main, [payload], "2026-11-02")
        self.assertEqual(stats["category_conflict"], 1)
        self.assertEqual(main["sources"][0]["category"], "dsh")
        self.assertEqual(main["sources"][0]["category_from_inbox"], "dsh")

    def test_category_conflict_same_priority_keeps_cloud(self):
        main = _main_doc()
        payload = {
            "sources": [
                {
                    "location": "https://github.com/acme/existing",
                    "category": "dsh",
                    "priority": "P2",
                }
            ]
        }
        merge.merge_payload(main, [payload], "2026-11-02")
        self.assertEqual(main["sources"][0]["category"], "finance_models")

    def test_metadata_conflict_cloud_wins_and_local_hint(self):
        main = _main_doc()
        payload = {
            "sources": [
                {
                    "location": "https://github.com/acme/existing",
                    "license": "GPL-3.0",
                    "stars": 42,
                }
            ]
        }
        merge.merge_payload(main, [payload], "2026-11-02")
        entry = main["sources"][0]
        self.assertEqual(entry["license"], "MIT")  # 云端校验值优先
        self.assertEqual(entry["stars"], 900)
        self.assertEqual(entry["local_hint"]["license"], "GPL-3.0")
        self.assertEqual(entry["local_hint"]["stars"], 42)

    def test_also_seen_in_collects_second_discovery(self):
        main = _main_doc()
        payload = {
            "sources": [
                {
                    "location": "https://github.com/acme/existing",
                    "discovered_from": "2-KNOWLEDGE/b.md",
                }
            ]
        }
        merge.merge_payload(main, [payload], "2026-11-02")
        entry = main["sources"][0]
        self.assertEqual(entry["discovered_from"], "2-KNOWLEDGE/a.md")
        self.assertEqual(entry["also_seen_in"], ["2-KNOWLEDGE/b.md"])

    def test_retired_never_deleted(self):
        main = _main_doc()
        payload = {"sources": [{"location": "https://github.com/acme/existing", "retired": True}]}
        stats = merge.merge_payload(main, [payload], "2026-11-02")
        entry = main["sources"][0]
        self.assertEqual(len(main["sources"]), 1)
        self.assertTrue(entry["retired"])
        self.assertEqual(entry["retired_at"], "2026-11-02")
        self.assertEqual(stats["retired"], 1)

    def test_version_monotonic_bump(self):
        self.assertEqual(merge._bump_version("2.1"), "2.11")
        self.assertEqual(merge._bump_version("2.11"), "2.12")

    def test_load_and_archive_inbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "inbox"
            inbox.mkdir()
            (inbox / "external_sources.local.json").write_text(
                '{"sources": [{"location": "https://github.com/x/y"}]}', encoding="utf-8"
            )
            files = merge.load_inbox_files(inbox)
            self.assertEqual(len(files), 1)
            moved = merge.archive_inboxes([f for f, _ in files], inbox / "archive")
            self.assertEqual(len(moved), 1)
            self.assertFalse((inbox / "external_sources.local.json").exists())

    def test_bad_inbox_json_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            inbox = Path(tmp) / "inbox"
            inbox.mkdir()
            (inbox / "broken.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(merge.load_inbox_files(inbox), [])


class TestMemoryGate(unittest.TestCase):
    def setUp(self):
        self._old = {
            k: os.environ.get(k) for k in ("REA_MEM_FAKE_AVAILABLE_MB", "REA_MEM_FAKE_TOTAL_MB")
        }

    def tearDown(self):
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_gate_blocks_and_writes_alert(self):
        os.environ["REA_MEM_FAKE_AVAILABLE_MB"] = "100"
        os.environ["REA_MEM_FAKE_TOTAL_MB"] = "8000"
        with tempfile.TemporaryDirectory() as tmp:
            ok = verify.mem_gate(alert_dir=Path(tmp), stage="test")
            self.assertFalse(ok)
            alerts = list(Path(tmp).glob("ALERT_mem_*.json"))
            self.assertEqual(len(alerts), 1)
            self.assertEqual(alerts[0].name.split("_")[0], "ALERT")

    def test_gate_blocks_on_percent_threshold(self):
        os.environ["REA_MEM_FAKE_AVAILABLE_MB"] = "1000"
        os.environ["REA_MEM_FAKE_TOTAL_MB"] = "20000"  # 5% < 10%
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(verify.mem_gate(alert_dir=Path(tmp), stage="test"))

    def test_gate_passes_with_enough_memory(self):
        os.environ["REA_MEM_FAKE_AVAILABLE_MB"] = "4000"
        os.environ["REA_MEM_FAKE_TOTAL_MB"] = "8000"
        self.assertTrue(verify.mem_gate(stage="test"))


class TestVerifySelection(unittest.TestCase):
    def test_pick_targets_skips_fresh_verified_and_retired(self):
        sources = [
            {
                "id": "a",
                "location": "https://github.com/a/a",
                "verified": False,
                "source_type": "github_repo",
            },
            {
                "id": "b",
                "location": "https://github.com/b/b",
                "verified": True,
                "last_checked_at": "2026-10-30",
                "source_type": "github_repo",
            },
            {
                "id": "c",
                "location": "https://github.com/c/c",
                "verified": True,
                "last_checked_at": "2026-09-01",
                "source_type": "github_repo",
            },
            {
                "id": "d",
                "location": "https://github.com/d/d",
                "retired": True,
                "source_type": "github_repo",
            },
        ]
        picked = verify.pick_targets(sources, limit=10, stale_days=30)
        ids = [s["id"] for s in picked]
        self.assertEqual(sorted(ids), ["a", "c"])

    def test_pick_targets_respects_limit(self):
        sources = [
            {"id": f"x{i}", "location": f"https://github.com/x{i}/x", "source_type": "github_repo"}
            for i in range(10)
        ]
        self.assertEqual(len(verify.pick_targets(sources, limit=3, stale_days=30)), 3)

    def test_q2_verdict(self):
        meta_ok = {"language": "Python", "license": {"spdx_id": "MIT"}, "stargazers_count": 500}
        self.assertTrue(verify.q2_verdict(meta_ok)[0])
        self.assertFalse(verify.q2_verdict({**meta_ok, "language": "Go"})[0])
        self.assertFalse(verify.q2_verdict({**meta_ok, "license": {"spdx_id": "GPL-3.0"}})[0])
        self.assertFalse(verify.q2_verdict({**meta_ok, "stargazers_count": 10})[0])
        self.assertFalse(verify.q2_verdict({**meta_ok, "archived": True})[0])

    def test_q2_notebook_counts_as_python(self):
        meta = {
            "language": "Jupyter Notebook",
            "license": {"spdx_id": "MIT"},
            "stargazers_count": 500,
        }
        self.assertTrue(verify.q2_verdict(meta)[0])

    def test_q2_noassertion_falls_back_to_prior_license(self):
        meta = {
            "language": "Python",
            "license": {"spdx_id": "NOASSERTION"},
            "stargazers_count": 500,
        }
        self.assertTrue(verify.q2_verdict(meta, prior={"license": "MIT"})[0])
        self.assertFalse(verify.q2_verdict(meta, prior={"license": "unknown"})[0])

    def test_q2_api_language_not_masking_prior_python(self):
        # API 报 Go 而清单人工登记 Python：以 API 结果为准（不放行）
        meta = {"language": "Go", "license": {"spdx_id": "MIT"}, "stargazers_count": 500}
        self.assertFalse(verify.q2_verdict(meta, prior={"language": "Python"})[0])

    def test_q2_empty_language_falls_back_to_prior(self):
        meta = {"license": {"spdx_id": "MIT"}, "stargazers_count": 500}
        self.assertTrue(verify.q2_verdict(meta, prior={"language": "Python"})[0])
        self.assertFalse(verify.q2_verdict(meta)[0])

    def test_stale_days(self):
        self.assertEqual(verify._stale_days(None) >= 10**5, True)
        self.assertEqual(verify._stale_days("not-a-date") >= 10**5, True)


if __name__ == "__main__":
    unittest.main()
