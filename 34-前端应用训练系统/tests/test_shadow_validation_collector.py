"""ShadowValidationCollector 单元测试 — P4 DSH 层进化链采集器.

测试覆盖:
  TR-5.1  类存在且实现 TrainingDataProvider 接口
  TR-5.2  get_source_name() 返回 "shadow_validation"
  TR-5.3  get_quality_threshold() 返回 "B"
  TR-5.4  fetch_cases() 采集 TrainingCase
  TR-5.5  node_sequence 含 entry/exit/outcome 节点
  TR-5.6  layer_tags 包含 "DSH"
  TR-5.7  FAIL-OPEN: 目录不存在返回空列表
  TR-5.8  FAIL-OPEN: 损坏的 jsonl 行跳过
"""
import json
import os
import sys
import tempfile
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ShadowValidationCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="shadow_val_test_")
        cls._samples_dir = os.path.join(cls._tmpdir, "shadow_validation")
        os.makedirs(cls._samples_dir)

        # 样本1: 有 win/loss 的样本
        with open(os.path.join(cls._samples_dir, "CD-TEST-001_samples.jsonl"), "w") as f:
            f.write(json.dumps({
                "entry_time": "2026-01-12 00:00:00", "exit_time": "2026-01-14 00:00:00",
                "entry_price": 91778.6, "exit_price": 95671.0,
                "pnl_pct": 0.0424, "win": True, "hold_bars": 12,
                "gene_id": "CD-TEST-001", "direction": "long"
            }) + "\n")
            f.write(json.dumps({
                "entry_time": "2026-01-13 12:00:00", "exit_time": "2026-01-15 12:00:00",
                "entry_price": 93412.2, "exit_price": 92000.0,
                "pnl_pct": -0.0151, "win": False, "hold_bars": 12,
                "gene_id": "CD-TEST-001", "direction": "long"
            }) + "\n")
            # 损坏的行
            f.write("{invalid json}\n")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def test_class_exists_and_implements_interface(self):
        from shadow_validation_collector import ShadowValidationCollector
        from interfaces.training_data_provider import TrainingDataProvider
        self.assertIsInstance(ShadowValidationCollector(), TrainingDataProvider)

    def test_get_source_name(self):
        from shadow_validation_collector import ShadowValidationCollector
        self.assertEqual(ShadowValidationCollector().get_source_name(), "shadow_validation")

    def test_get_quality_threshold(self):
        from shadow_validation_collector import ShadowValidationCollector
        self.assertEqual(ShadowValidationCollector().get_quality_threshold(), "B")

    def test_fetch_cases_returns_training_cases(self):
        from shadow_validation_collector import ShadowValidationCollector
        c = ShadowValidationCollector(samples_dir=self._samples_dir)
        cases = c.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)

    def test_node_sequence_has_entry_exit_outcome(self):
        from shadow_validation_collector import ShadowValidationCollector
        c = ShadowValidationCollector(samples_dir=self._samples_dir)
        cases = c.fetch_cases(limit=100)
        all_actions = ",".join(a for case in cases for a in case.actions)
        self.assertIn("entry", all_actions.lower())
        self.assertIn("exit", all_actions.lower())
        self.assertTrue(any("win" in a.lower() or "loss" in a.lower() or "outcome" in a.lower()
                           for case in cases for a in case.actions))

    def test_layer_tags_contains_dsh(self):
        from shadow_validation_collector import ShadowValidationCollector
        c = ShadowValidationCollector(samples_dir=self._samples_dir)
        for case in c.fetch_cases(limit=10):
            self.assertIn("DSH", case.layer_tags)

    def test_fail_open_dir_missing(self):
        from shadow_validation_collector import ShadowValidationCollector
        c = ShadowValidationCollector(samples_dir="/nonexistent/dir")
        self.assertEqual(c.fetch_cases(limit=10), [])

    def test_fail_open_corrupt_json(self):
        """损坏的 JSON 行应跳过不崩溃。"""
        from shadow_validation_collector import ShadowValidationCollector
        c = ShadowValidationCollector(samples_dir=self._samples_dir)
        cases = c.fetch_cases(limit=100)
        # 应采集到2条 (跳过损坏行)
        self.assertEqual(len(cases), 2)


if __name__ == "__main__":
    unittest.main()
