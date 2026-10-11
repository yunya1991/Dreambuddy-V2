"""REANativeParser 单元测试。

测试:
  1. _convert_output 正确转换 S33_rea_analyze 输出
  2. _convert_output 正确转换 S33_rea_trace 输出
  3. FAIL-OPEN：import 失败/分析异常 → 空 REAParseResult
  4. evidence_level 映射（observation→L1, derivation→L2, ...）
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# sys.path 注入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ADAPTERS_DIR = os.path.join(os.path.dirname(_THIS_DIR), "adapters")
_34_DIR = os.path.dirname(_THIS_DIR)

for _p in [_THIS_DIR, _ADAPTERS_DIR, _34_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


class REANativeParserConvertTest(unittest.TestCase):
    """测试 _convert_output 静态方法（不依赖真实 33-REA import）。"""

    def _make_parser(self):
        """创建一个 REANativeParser，跳过 import。"""
        from rea_native_parser import REANativeParser
        parser = REANativeParser()
        parser._rea_module = None  # 不触发 import
        return parser

    def test_convert_analyze_output(self):
        """S33_rea_analyze 输出应正确转换为 REAParseResult。"""
        parser = self._make_parser()

        mock_output = {
            "ok": True,
            "result": {
                "summary": "架构分析: 3 模块, 5 依赖",
                "evidence": [
                    {
                        "evidence_id": "ev_1",
                        "result": "使用 recursion 和 divide_conquer 算法",
                        "level": "observation",
                        "provenance": {"file": "test.py", "line": 10},
                        "confidence": 0.9,
                        "known_gaps": ["未分析全部文件"],
                        "observations": [{"type": "ast_node"}],
                    },
                    {
                        "evidence_id": "ev_2",
                        "result": "模块间依赖清晰",
                        "level": "derivation",
                        "provenance": {"engine": "dependency_graph"},
                        "confidence": 0.7,
                        "known_gaps": [],
                        "observations": [],
                    },
                ],
                "raw": {
                    "modules": ["mod_a", "mod_b", "mod_c"],
                    "dependencies": {"mod_a": ["mod_b"], "mod_b": ["mod_c"]},
                    "cycles": [],
                    "call_graph": {
                        "callers": {"func_a": ["func_b"]},
                        "callees": {"func_a": [], "func_b": ["func_a"]},
                    },
                },
                "trace_id": "s33an_abc",
            },
        }

        result = parser._convert_output(mock_output, is_trace=False)

        # dependency_graph
        self.assertEqual(result.dependency_graph, {"mod_a": ["mod_b"], "mod_b": ["mod_c"]})
        # call_chain 从 callees keys 提取
        self.assertIn("func_a", result.call_chain)
        self.assertIn("func_b", result.call_chain)
        # algorithm_patterns 从 evidence result 提取
        self.assertIn("recursion", result.algorithm_patterns)
        self.assertIn("divide_conquer", result.algorithm_patterns)
        # known_gaps 汇总
        self.assertIn("未分析全部文件", result.known_gaps)
        # evidence_level 取最高（observation → L1）
        self.assertEqual(result.evidence_level, "L1")
        # confidence 取均值
        self.assertAlmostEqual(result.confidence, 0.8, places=1)

    def test_convert_trace_output(self):
        """S33_rea_trace 输出应正确转换为 REAParseResult。"""
        parser = self._make_parser()

        mock_output = {
            "ok": True,
            "result": {
                "feature": "用户登录",
                "call_chain": {
                    "callers": {"login": ["authenticate"]},
                    "callees": {"authenticate": ["check_pw"], "login": ["authenticate"]},
                    "all_functions": ["login", "authenticate", "check_pw"],
                    "entry_chain": ["login", "authenticate", "check_pw"],
                },
                "evidence": [
                    {
                        "evidence_id": "ev_1",
                        "result": "调用链完整",
                        "level": "observation",
                        "confidence": 0.95,
                        "known_gaps": [],
                        "observations": [],
                    },
                ],
                "known_gaps": ["未检测到外部库调用"],
                "trace_id": "s33tr_xyz",
            },
        }

        result = parser._convert_output(mock_output, is_trace=True)

        # call_chain 从 entry_chain 提取
        self.assertEqual(result.call_chain, ["login", "authenticate", "check_pw"])
        # known_gaps 汇总
        self.assertIn("未检测到外部库调用", result.known_gaps)
        # evidence_level
        self.assertEqual(result.evidence_level, "L1")

    def test_convert_failed_output(self):
        """S33 返回 ok=False 时应返回空 REAParseResult。"""
        parser = self._make_parser()
        mock_output = {"ok": False, "error": "missing_target", "result": {}}
        result = parser._convert_output(mock_output, is_trace=False)
        self.assertEqual(result.dependency_graph, {})
        self.assertEqual(result.call_chain, [])
        self.assertEqual(result.algorithm_patterns, [])
        self.assertEqual(result.raw_evidence, {"error": "missing_target"})

    def test_evidence_level_mapping(self):
        """Evidence level 映射：observation→L1, derivation→L2, inference→L3, unknown→L4。"""
        parser = self._make_parser()

        levels = [
            ("observation", "L1"),
            ("derivation", "L2"),
            ("inference", "L3"),
            ("unknown", "L4"),
        ]
        for rea_level, expected_tdr_level in levels:
            mock_output = {
                "ok": True,
                "result": {
                    "evidence": [{"level": rea_level, "confidence": 0.5, "known_gaps": [], "observations": []}],
                },
            }
            result = parser._convert_output(mock_output, is_trace=False)
            self.assertEqual(result.evidence_level, expected_tdr_level,
                             f"{rea_level} should map to {expected_tdr_level}")

    def test_fail_open_rea_unavailable(self):
        """33-REA import 失败时，analyze/trace 应返回空 REAParseResult。"""
        parser = self._make_parser()
        parser._rea_module = None  # 模拟 import 失败

        result = parser.analyze("/tmp/test", "architecture")
        self.assertEqual(result.algorithm_patterns, [])
        self.assertEqual(result.dependency_graph, {})
        self.assertIn("error", result.raw_evidence)

        result2 = parser.trace("/tmp/test", "feature")
        self.assertEqual(result2.call_chain, [])
        self.assertIn("error", result2.raw_evidence)

    def test_fail_open_analyze_exception(self):
        """S33_rea_analyze 抛异常时应返回空 REAParseResult。"""
        parser = self._make_parser()
        # mock _get_rea 返回一个会抛异常的模块
        mock_mod = MagicMock()
        mock_mod.S33_rea_analyze.side_effect = RuntimeError("boom")
        parser._rea_module = mock_mod

        result = parser.analyze("/tmp/test")
        self.assertIn("error", result.raw_evidence)
        self.assertIn("analyze_failed", result.raw_evidence["error"])

    def test_fail_open_trace_exception(self):
        """S33_rea_trace 抛异常时应返回空 REAParseResult。"""
        parser = self._make_parser()
        mock_mod = MagicMock()
        mock_mod.S33_rea_trace.side_effect = RuntimeError("trace boom")
        parser._rea_module = mock_mod

        result = parser.trace("/tmp/test", "feature")
        self.assertIn("error", result.raw_evidence)
        self.assertIn("trace_failed", result.raw_evidence["error"])


if __name__ == "__main__":
    unittest.main()
