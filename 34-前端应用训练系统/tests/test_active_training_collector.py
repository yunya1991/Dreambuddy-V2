"""ActiveTrainingCollector 调度器单元测试。

测试:
  1. 注册多个 Provider 并批量采集
  2. 增量采集：per-source last_collected 时间戳
  3. 质量门控：低于阈值的案例被跳过
  4. 批量写入 TDR
  5. 采集报告正确统计
  6. FAIL-OPEN：单个 Provider 失败不影响其他
"""
import os
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_CORE_DIR = os.path.join(os.path.dirname(_THIS_DIR), "core")
_34_DIR = os.path.dirname(_THIS_DIR)
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _ADAPTERS_DIR, _CORE_DIR, _34_DIR, _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class ActiveTrainingCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="active_collector_test_")
        os.environ["SPL_DB_DIR"] = cls._tmpdir

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)
        os.environ.pop("SPL_DB_DIR", None)

    def setUp(self):
        from case_bank_server import _connect
        conn = _connect()
        conn.execute("DELETE FROM solution_cases")
        conn.commit()
        conn.close()

    def _make_mock_provider(self, name, cases, threshold="B"):
        """创建 mock TrainingDataProvider。"""
        provider = MagicMock()
        provider.get_source_name.return_value = name
        provider.get_quality_threshold.return_value = threshold
        provider.fetch_cases.return_value = cases
        return provider

    def _make_test_case(self, source="test", quality="B", intent="test_case"):
        from interfaces.training_data_provider import TrainingCase
        return TrainingCase(
            intent=intent,
            actions=["a1"],
            outcome_text="test outcome",
            learned=["l1"],
            layer_tags=["DSH"],
            quality=quality,
            confidence=0.5,
            source=source,
        )

    def test_register_multiple_providers(self):
        """注册多个 Provider 并批量采集。"""
        from active_training_collector import ActiveTrainingCollector

        collector = ActiveTrainingCollector()
        p1 = self._make_mock_provider("tdr", [self._make_test_case("tdr", "B", "c1")])
        p2 = self._make_mock_provider("cognitive", [self._make_test_case("cognitive", "A", "c2")])

        collector.register_provider(p1)
        collector.register_provider(p2)

        report = collector.run_collection()

        self.assertEqual(report["total_collected"], 2)
        self.assertEqual(report["total_ingested"], 2)
        self.assertIn("tdr", report["per_source"])
        self.assertIn("cognitive", report["per_source"])

    def test_quality_gate_skips_low_quality(self):
        """质量门控：低于阈值的案例被跳过。"""
        from active_training_collector import ActiveTrainingCollector

        # Provider 阈值 B，但返回 C 级案例
        cases = [
            self._make_test_case("cognitive", "A", "good"),
            self._make_test_case("cognitive", "C", "bad"),  # 低于 B → 跳过
        ]
        provider = self._make_mock_provider("cognitive", cases, threshold="B")

        collector = ActiveTrainingCollector()
        collector.register_provider(provider)

        report = collector.run_collection()

        # 只采集 A 级案例
        self.assertEqual(report["total_collected"], 2)
        self.assertEqual(report["total_ingested"], 1)  # C 级被门控跳过

    def test_incremental_collection(self):
        """增量采集：使用 since 时间戳。"""
        from active_training_collector import ActiveTrainingCollector

        provider = self._make_mock_provider(
            "skill", [self._make_test_case("skill", "B", "s1")]
        )

        collector = ActiveTrainingCollector()
        collector.register_provider(provider)

        # 设置上次采集时间
        collector.set_last_collected("skill", "1000")

        collector.run_collection()

        # 验证 fetch_cases 被调用时传入 since 参数
        call_args = provider.fetch_cases.call_args
        self.assertIsNotNone(call_args)
        self.assertEqual(call_args[1].get("since") or (call_args[0][1] if len(call_args[0]) > 1 else None), "1000")

    def test_fail_open_single_provider_failure(self):
        """单个 Provider 失败不影响其他。"""
        from active_training_collector import ActiveTrainingCollector

        bad_provider = MagicMock()
        bad_provider.get_source_name.return_value = "broken"
        bad_provider.get_quality_threshold.return_value = "B"
        bad_provider.fetch_cases.side_effect = Exception("DB error")

        good_provider = self._make_mock_provider(
            "tdr", [self._make_test_case("tdr", "B", "ok")]
        )

        collector = ActiveTrainingCollector()
        collector.register_provider(bad_provider)
        collector.register_provider(good_provider)

        report = collector.run_collection()

        # broken 失败但 tdr 正常
        self.assertEqual(report["total_collected"], 1)
        self.assertEqual(report["total_ingested"], 1)
        self.assertEqual(report["per_source"]["broken"]["error"], True)

    def test_writes_to_tdr(self):
        """采集的案例应写入 TDR。"""
        from active_training_collector import ActiveTrainingCollector
        from case_bank_server import fetch_since

        cases = [self._make_test_case("tdr", "A", "tdr_case")]
        provider = self._make_mock_provider("tdr", cases)

        collector = ActiveTrainingCollector()
        collector.register_provider(provider)

        collector.run_collection()

        # 验证 TDR 中有数据
        result = fetch_since(since_ts=0, limit=10)
        self.assertTrue(result["ok"])
        self.assertGreater(result["count"], 0)
        intents = [c["intent"] for c in result["cases"]]
        self.assertIn("tdr_case", intents)

    def test_collection_report_structure(self):
        """采集报告包含正确的统计结构。"""
        from active_training_collector import ActiveTrainingCollector

        provider = self._make_mock_provider(
            "tdr", [self._make_test_case("tdr", "B", "r1")]
        )

        collector = ActiveTrainingCollector()
        collector.register_provider(provider)

        report = collector.run_collection()

        self.assertIn("total_collected", report)
        self.assertIn("total_ingested", report)
        self.assertIn("total_skipped", report)
        self.assertIn("per_source", report)
        self.assertIn("collected_at", report)


if __name__ == "__main__":
    unittest.main()
