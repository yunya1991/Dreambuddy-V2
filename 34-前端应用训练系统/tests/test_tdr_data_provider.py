"""TDR TrainingDataProvider 单元测试。

测试:
  1. fetch_since 增量查询返回正确案例
  2. layer_tags 扁平化（List[LayerTag] → List[str]）
  3. FAIL-OPEN：TDR 不可用时返回空列表
"""
import os
import sys
import json
import time
import tempfile
import unittest

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)  # 34-前端应用训练系统/
_PROJECT_ROOT = os.path.dirname(_34_DIR)
_SCRIPTS_DIR = os.path.join(_PROJECT_ROOT, "scripts")

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR, _SCRIPTS_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TDRTrainingDataProviderTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """使用临时目录作为 TDR DB，避免污染真实数据。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="tdr_test_")
        os.environ["SPL_DB_DIR"] = cls._tmpdir

    @classmethod
    def tearDownClass(cls):
        """清理临时 DB。"""
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)
        os.environ.pop("SPL_DB_DIR", None)

    def setUp(self):
        """每个测试前清空 solution_cases 表，避免测试间数据污染。"""
        from case_bank_server import _connect
        conn = _connect()
        conn.execute("DELETE FROM solution_cases")
        conn.commit()
        conn.close()

    def _store_test_case(self, intent="test", learned=None, quality="B",
                         layer_tags=None, created_at=None):
        """存储一条测试案例到 TDR。"""
        from case_bank_server import store_case
        case = {
            "intent": intent,
            "actions": ["action1", "action2"],
            "outcome_text": "test outcome",
            "learned": learned or ["lesson1"],
            "quality": quality,
            "confidence": 0.5,
            "layer_tags": layer_tags or [{"layer": "DSH", "training_data": {}}],
            "source": "test",
        }
        return store_case(case)

    def test_fetch_since_returns_cases(self):
        """fetch_since 应返回 created_at > since 的案例。"""
        from case_bank_server import fetch_since, store_case

        # 存 2 条案例
        store_case({
            "intent": "case_a", "actions": ["a1"], "outcome_text": "oa",
            "learned": ["l1"], "quality": "B", "source": "test",
        })
        store_case({
            "intent": "case_b", "actions": ["b1"], "outcome_text": "ob",
            "learned": ["l2"], "quality": "A", "source": "test",
        })

        result = fetch_since(since_ts=0, limit=10)
        self.assertTrue(result["ok"])
        self.assertEqual(result["count"], 2)

    def test_fetch_since_incremental(self):
        """增量查询：只返回 since 之后的新案例。"""
        from case_bank_server import fetch_since, store_case

        # 存第一条案例
        r1 = store_case({
            "intent": "old_case", "actions": ["a"], "outcome_text": "o",
            "learned": ["l"], "quality": "B", "source": "test",
        })
        self.assertTrue(r1["ok"])

        # 获取 old_case 的 created_at（DB 已清空，只有这一条）
        all_cases = fetch_since(since_ts=0, limit=1)
        self.assertEqual(all_cases["count"], 1)
        old_ts = all_cases["cases"][0]["created_at"]

        # 确保 created_at 不同毫秒
        time.sleep(0.01)

        # 存新案例
        r2 = store_case({
            "intent": "new_case", "actions": ["b"], "outcome_text": "o2",
            "learned": ["l2"], "quality": "A", "source": "test",
        })
        self.assertTrue(r2["ok"])

        # 增量查询：只应返回 created_at > old_ts 的案例
        result = fetch_since(since_ts=old_ts, limit=10)
        self.assertTrue(result["ok"])
        intents = [c["intent"] for c in result["cases"]]
        self.assertIn("new_case", intents)
        self.assertNotIn("old_case", intents)

    def test_adapter_layer_tags_flatten(self):
        """适配器应将 layer_tags 从 List[dict] 扁平化为 List[str]。"""
        from tdr_data_provider import TDRTrainingDataProvider

        # 先存一条带 layer_tags 的案例
        self._store_test_case(
            intent="flatten_test",
            layer_tags=[
                {"layer": "DSH", "training_data": {"patterns": ["recursion"]}},
                {"layer": "C", "training_data": {"reflection": "gap1"}},
            ],
        )

        provider = TDRTrainingDataProvider()
        cases = provider.fetch_cases(limit=10)

        # 找到 flatten_test
        test_cases = [c for c in cases if c.intent == "flatten_test"]
        self.assertTrue(len(test_cases) > 0, "should find flatten_test case")
        case = test_cases[0]
        self.assertIsInstance(case.layer_tags, list)
        self.assertIn("DSH", case.layer_tags)
        self.assertIn("C", case.layer_tags)
        # 确保不是 dict 而是 str
        for tag in case.layer_tags:
            self.assertIsInstance(tag, str)

    def test_adapter_quality_threshold(self):
        """get_quality_threshold 应返回默认 'B'。"""
        from tdr_data_provider import TDRTrainingDataProvider
        provider = TDRTrainingDataProvider()
        self.assertEqual(provider.get_quality_threshold(), "B")

    def test_adapter_source_name(self):
        """get_source_name 应返回 'tdr'。"""
        from tdr_data_provider import TDRTrainingDataProvider
        provider = TDRTrainingDataProvider()
        self.assertEqual(provider.get_source_name(), "tdr")

    def test_fail_open_tdr_unavailable(self):
        """TDR 不可用时，fetch_cases 应返回空列表而非抛异常。"""
        from tdr_data_provider import TDRTrainingDataProvider
        provider = TDRTrainingDataProvider()
        # 模拟 TDR 不可用：设置 _tdr 为空 dict
        provider._tdr = {}
        cases = provider.fetch_cases(limit=10)
        self.assertEqual(cases, [])

    def test_training_case_fields_mapped(self):
        """TrainingCase 字段应正确映射。"""
        from tdr_data_provider import TDRTrainingDataProvider

        self._store_test_case(
            intent="field_map",
            learned=["learned1", "learned2"],
            quality="A",
        )

        provider = TDRTrainingDataProvider()
        cases = provider.fetch_cases(limit=50)
        test_cases = [c for c in cases if c.intent == "field_map"]
        self.assertTrue(len(test_cases) > 0)
        case = test_cases[0]
        self.assertEqual(case.intent, "field_map")
        self.assertEqual(case.learned, ["learned1", "learned2"])
        self.assertEqual(case.quality, "A")
        self.assertEqual(case.source, "test")
        self.assertIn("id", case.metadata)


if __name__ == "__main__":
    unittest.main()
