"""TddTestCollector 单元测试 — P0 DSH 层训练数据采集器.

测试覆盖:
  TR-1.1  TddTestCollector 类存在且实现 TrainingDataProvider 接口
  TR-1.2  get_source_name() 返回 "tdd_test"
  TR-1.3  get_quality_threshold() 返回 "B"
  TR-1.4  fetch_cases() 从测试 .py 文件采集 TrainingCase
  TR-1.5  TrainingCase.intent 格式: class_name.func_name 或 func_name (去test_前缀)
  TR-1.6  TrainingCase.actions (node_sequence) 包含 AST 解析的函数调用链
  TR-1.7  参数化测试(@parametrize)生成多条 TrainingCase
  TR-1.8  layer_tags 包含 "DSH"
  TR-1.9  过滤框架调用 (pytest/mock/patch/MagicMock 等不出现在 node_sequence)
  TR-1.10 FAIL-OPEN: 目录不存在返回空列表
  TR-1.11 FAIL-OPEN: AST 解析异常跳过该文件不崩溃
  TR-1.12 node_sequence 含 assert 终节点
"""
import os
import sys
import tempfile
import textwrap
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TddTestCollectorTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """创建临时目录和样本测试 .py 文件。"""
        cls._tmpdir = tempfile.mkdtemp(prefix="tdd_collector_test_")

        # 样本1: 普通测试函数 + 调用链 + assert
        cls._file1 = os.path.join(cls._tmpdir, "test_score_b.py")
        with open(cls._file1, "w") as f:
            f.write(textwrap.dedent('''
                def compute_score_b(cont, conf):
                    return 0.6 * cont + 0.4 * conf

                def clamp(val, lo, hi):
                    return max(lo, min(hi, val))

                def test_formula_basic():
                    score = compute_score_b(0.75, 0.70)
                    assert abs(score - 0.73) < 0.01

                def test_clamp_high():
                    score = compute_score_b(0.9, 0.9)
                    clamped = clamp(score, 0, 0.8)
                    assert clamped == 0.8
            '''))

        # 样本2: 参数化测试 @pytest.mark.parametrize
        cls._file2 = os.path.join(cls._tmpdir, "test_parametrize.py")
        with open(cls._file2, "w") as f:
            f.write(textwrap.dedent('''
                import pytest

                def compute_score_b_with_event_boost(cont, conf, strength):
                    base = 0.6 * cont + 0.4 * conf
                    boost = min(0.10, max(0.0, strength * 0.1))
                    return base + boost, boost

                @pytest.mark.parametrize("cont,conf,strength,expected_score_b,expected_boost", [
                    (0.75, 0.70, 0.0, 0.73, 0.0),
                    (0.75, 0.70, 1.0, 0.844, 0.10),
                    (0.75, 0.70, None, 0.73, 0.0),
                ])
                def test_formula_and_clamp(cont, conf, strength, expected_score_b, expected_boost):
                    score, boost = compute_score_b_with_event_boost(cont, conf, strength)
                    assert abs(boost - expected_boost) < 1e-3
                    assert abs(score - expected_score_b) < 1e-3
            '''))

        # 样本3: 测试类 + 多方法 + mock 调用(应被过滤)
        cls._file3 = os.path.join(cls._tmpdir, "test_exit_manager.py")
        with open(cls._file3, "w") as f:
            f.write(textwrap.dedent('''
                from unittest.mock import MagicMock, patch

                class ExitManager:
                    def __init__(self, strategies):
                        self.strategies = strategies

                    def evaluate(self, coin, inference, pos_info):
                        for s in self.strategies:
                            result = s.check(coin, inference, pos_info)
                            if result != "pass":
                                return result
                        return "pass"

                class TestExitManager:
                    def test_priority_chain_first_non_pass_wins(self):
                        always_pass = MagicMock()
                        always_pass.check.return_value = "pass"
                        force_close = MagicMock()
                        force_close.check.return_value = "force_close"
                        mgr = ExitManager(strategies=[always_pass, force_close])
                        decision = mgr.evaluate("BTC", {}, {})
                        assert decision == "force_close"

                    def test_all_pass_returns_pass(self):
                        s = MagicMock()
                        s.check.return_value = "pass"
                        mgr = ExitManager(strategies=[s])
                        decision = mgr.evaluate("BTC", {}, {})
                        assert decision == "pass"
            '''))

        # 样本4: 非 test_ 前缀文件(不应被采集)
        cls._file4 = os.path.join(cls._tmpdir, "helper_utils.py")
        with open(cls._file4, "w") as f:
            f.write(textwrap.dedent('''
                def helper_function():
                    return 42
            '''))

        # 样本5: 空文件
        cls._file5 = os.path.join(cls._tmpdir, "test_empty.py")
        with open(cls._file5, "w") as f:
            f.write("")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    # ===== TR-1.1: 类存在且实现接口 =====
    def test_class_exists_and_implements_interface(self):
        """TddTestCollector 应存在且实现 TrainingDataProvider。"""
        from tdd_test_collector import TddTestCollector
        from interfaces.training_data_provider import TrainingDataProvider
        collector = TddTestCollector()
        self.assertIsInstance(collector, TrainingDataProvider)

    # ===== TR-1.2: get_source_name =====
    def test_get_source_name(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector()
        self.assertEqual(collector.get_source_name(), "tdd_test")

    # ===== TR-1.3: get_quality_threshold =====
    def test_get_quality_threshold(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector()
        self.assertEqual(collector.get_quality_threshold(), "B")

    # ===== TR-1.4: fetch_cases 采集 TrainingCase =====
    def test_fetch_cases_returns_training_cases(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0, "应至少采集1条 TrainingCase")
        # 不应采集非 test_ 前缀文件的函数
        for c in cases:
            self.assertNotIn("helper_function", c.intent)

    # ===== TR-1.5: intent 格式 (去 test_ 前缀) =====
    def test_intent_strips_test_prefix(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        intents = [c.intent for c in cases]
        # test_formula_basic → formula_basic 或 test_domain.formula_basic
        has_formula = any("formula_basic" in i for i in intents)
        self.assertTrue(has_formula, f"intent 应含 formula_basic, got: {intents}")
        # 不应以 test_ 开头
        for i in intents:
            self.assertFalse(i.startswith("test_"), f"intent 不应以 test_ 开头: {i}")

    # ===== TR-1.6: node_sequence 包含 AST 调用链 =====
    def test_node_sequence_contains_call_chain(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        # 找 test_formula_basic 对应的 case
        formula_cases = [c for c in cases if "formula_basic" in c.intent]
        self.assertGreater(len(formula_cases), 0, "应找到 formula_basic case")
        case = formula_cases[0]
        # node_sequence 应含 compute_score_b 调用
        actions_str = ",".join(case.actions)
        self.assertIn("compute_score_b", actions_str,
                      f"node_sequence 应含 compute_score_b 调用, got: {case.actions}")

    # ===== TR-1.7: 参数化测试生成多条 TrainingCase =====
    def test_parametrize_generates_multiple_cases(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        # test_formula_and_clamp 有3个 parametrize 场景 → 3条 case
        clamp_cases = [c for c in cases if "formula_and_clamp" in c.intent]
        self.assertGreaterEqual(len(clamp_cases), 3,
                                f"参数化应生成≥3条 case, got {len(clamp_cases)}")

    # ===== TR-1.8: layer_tags 包含 DSH =====
    def test_layer_tags_contains_dsh(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        self.assertGreater(len(cases), 0)
        for c in cases:
            self.assertIn("DSH", c.layer_tags, f"layer_tags 应含 DSH: {c.layer_tags}")

    # ===== TR-1.9: 过滤框架调用 =====
    def test_filters_framework_calls(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        # MagicMock/patch/pytest 不应出现在 node_sequence 中
        framework_tokens = ["MagicMock", "patch", "pytest", "mock"]
        for c in cases:
            for action in c.actions:
                for token in framework_tokens:
                    self.assertNotIn(token, action,
                                     f"框架调用 {token} 不应在 node_sequence 中: {action}")

    # ===== TR-1.10: FAIL-OPEN 目录不存在 =====
    def test_fail_open_dir_missing(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[("/nonexistent/dir", "none")])
        cases = collector.fetch_cases(limit=10)
        self.assertEqual(cases, [])

    # ===== TR-1.11: FAIL-OPEN AST 解析异常不崩溃 =====
    def test_fail_open_syntax_error(self):
        """语法错误的文件应被跳过,不崩溃。"""
        from tdd_test_collector import TddTestCollector
        # 创建含语法错误的目录
        bad_dir = tempfile.mkdtemp(prefix="tdd_bad_")
        bad_file = os.path.join(bad_dir, "test_syntax_error.py")
        with open(bad_file, "w") as f:
            f.write("def test_bad(:\n    pass\n")  # 语法错误
        try:
            collector = TddTestCollector(scan_dirs=[(bad_dir, "bad")])
            cases = collector.fetch_cases(limit=10)
            self.assertEqual(cases, [], "语法错误文件应跳过返回空列表")
        finally:
            import shutil
            shutil.rmtree(bad_dir, ignore_errors=True)

    # ===== TR-1.12: node_sequence 含 assert 终节点 =====
    def test_node_sequence_contains_assert(self):
        from tdd_test_collector import TddTestCollector
        collector = TddTestCollector(scan_dirs=[(self._tmpdir, "test_domain")])
        cases = collector.fetch_cases(limit=100)
        # 至少有一条 case 的 node_sequence 含 assert 节点
        has_assert = any(
            any("assert" in a.lower() for a in c.actions)
            for c in cases
        )
        self.assertTrue(has_assert, "至少一条 case 的 node_sequence 应含 assert 终节点")


if __name__ == "__main__":
    unittest.main()
