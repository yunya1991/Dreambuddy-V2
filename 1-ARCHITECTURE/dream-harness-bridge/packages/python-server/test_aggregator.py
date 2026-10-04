#!/usr/bin/env python3
"""TDD RED: aggregator 生产版聚合器测试

测试覆盖:
  1. 模块存在性 (import aggregator)
  2. 空输入聚合
  3. 单输出聚合
  4. 多输出聚合 (summaries + signals + charts + modules)
  5. 共识方向投票 (long/short/neutral)
  6. 平均置信度计算
  7. top_signals 选取 (按置信度排序)
"""
from __future__ import annotations
import os, sys, unittest
from typing import List

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from subagent_types import SubagentOutput, Signal, ChartSpec


class TestAggregatorExistence(unittest.TestCase):
    """模块存在性"""

    def test_import_aggregator(self):
        """RED: aggregator 模块不存在 → ModuleNotFoundError"""
        import aggregator  # noqa: F401

    def test_aggregate_function_exists(self):
        from aggregator import aggregate_subagent_outputs
        self.assertTrue(callable(aggregate_subagent_outputs))


class TestAggregatorEmpty(unittest.TestCase):
    """空输入聚合"""

    def test_empty_returns_neutral(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs([])
        self.assertEqual(result["consensus_direction"], "neutral")
        self.assertEqual(result["total_signals"], 0)
        self.assertEqual(result["total_charts"], 0)
        self.assertEqual(result["modules"], [])
        self.assertEqual(result["summaries"], [])

    def test_empty_has_all_fields(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs([])
        expected_keys = {"summaries", "all_signals", "all_charts",
                         "modules", "total_signals", "consensus_direction",
                         "long_count", "short_count", "total_charts",
                         "avg_confidence", "top_signals"}
        self.assertEqual(set(result.keys()), expected_keys)


class TestAggregatorSingle(unittest.TestCase):
    """单输出聚合"""

    def test_single_output(self):
        from aggregator import aggregate_subagent_outputs
        out = SubagentOutput(
            module="macro",
            summary="GDP 温和增长",
            signals=[Signal("gdp", 2.5, "long", 0.7)],
            charts=[ChartSpec("line", "GDP 趋势", [1, 2, 3])],
        )
        result = aggregate_subagent_outputs([out])
        self.assertEqual(len(result["modules"]), 1)
        self.assertEqual(result["modules"][0], "macro")
        self.assertEqual(result["summaries"][0], "GDP 温和增长")
        self.assertEqual(result["total_signals"], 1)
        self.assertEqual(result["total_charts"], 1)
        self.assertEqual(result["long_count"], 1)
        self.assertEqual(result["consensus_direction"], "long")


class TestAggregatorMulti(unittest.TestCase):
    """多输出聚合"""

    def _make_outputs(self) -> List[SubagentOutput]:
        return [
            SubagentOutput(
                module="macro",
                summary="宏观偏多",
                signals=[
                    Signal("gdp", 2.5, "long", 0.7),
                    Signal("cpi", 3.1, "neutral", 0.5),
                ],
                charts=[ChartSpec("line", "GDP", [1, 2])],
            ),
            SubagentOutput(
                module="flow",
                summary="资金流入",
                signals=[
                    Signal("etf", 150, "long", 0.65),
                    Signal("leverage", 2.8, "short", 0.4),
                ],
                charts=[ChartSpec("bar", "ETF 流入", [10, 20])],
            ),
            SubagentOutput(
                module="onchain",
                summary="链上活跃",
                signals=[
                    Signal("mvrv", 1.8, "long", 0.6),
                ],
                charts=[],
            ),
        ]

    def test_multi_modules_collected(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs(self._make_outputs())
        self.assertEqual(len(result["modules"]), 3)
        self.assertIn("macro", result["modules"])
        self.assertIn("flow", result["modules"])
        self.assertIn("onchain", result["modules"])

    def test_multi_signals_merged(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs(self._make_outputs())
        self.assertEqual(result["total_signals"], 5)
        self.assertEqual(result["long_count"], 3)
        self.assertEqual(result["short_count"], 1)

    def test_multi_charts_collected(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs(self._make_outputs())
        self.assertEqual(result["total_charts"], 2)

    def test_multi_summaries_list(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs(self._make_outputs())
        self.assertEqual(len(result["summaries"]), 3)
        self.assertIn("宏观偏多", result["summaries"])

    def test_multi_consensus_long(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs(self._make_outputs())
        self.assertEqual(result["consensus_direction"], "long")


class TestAggregatorConsensus(unittest.TestCase):
    """共识方向投票"""

    def test_consensus_short_majority(self):
        from aggregator import aggregate_subagent_outputs
        out = SubagentOutput(
            module="risk",
            summary="高风险",
            signals=[
                Signal("var", 0.05, "short", 0.8),
                Signal("stress", 0.12, "short", 0.7),
                Signal("corr", 0.85, "neutral", 0.5),
            ],
        )
        result = aggregate_subagent_outputs([out])
        self.assertEqual(result["consensus_direction"], "short")
        self.assertEqual(result["short_count"], 2)

    def test_consensus_tie_neutral(self):
        from aggregator import aggregate_subagent_outputs
        out = SubagentOutput(
            module="flow",
            summary="多空均衡",
            signals=[
                Signal("a", 1, "long", 0.5),
                Signal("b", 2, "short", 0.5),
            ],
        )
        result = aggregate_subagent_outputs([out])
        self.assertEqual(result["consensus_direction"], "neutral")

    def test_consensus_no_signals_neutral(self):
        from aggregator import aggregate_subagent_outputs
        out = SubagentOutput(
            module="macro", summary="无信号", signals=[], charts=[])
        result = aggregate_subagent_outputs([out])
        self.assertEqual(result["consensus_direction"], "neutral")
        self.assertEqual(result["long_count"], 0)
        self.assertEqual(result["short_count"], 0)


class TestAggregatorAvgConfidence(unittest.TestCase):
    """平均置信度 (生产扩展)"""

    def test_avg_confidence_calculated(self):
        from aggregator import aggregate_subagent_outputs
        out = SubagentOutput(
            module="macro",
            summary="测试",
            signals=[
                Signal("a", 1, "long", 0.8),
                Signal("b", 2, "long", 0.6),
                Signal("c", 3, "short", 0.4),
            ],
        )
        result = aggregate_subagent_outputs([out])
        # avg_confidence = (0.8 + 0.6 + 0.4) / 3 = 0.6
        self.assertAlmostEqual(result["avg_confidence"], 0.6, places=2)

    def test_avg_confidence_empty_zero(self):
        from aggregator import aggregate_subagent_outputs
        result = aggregate_subagent_outputs([])
        self.assertEqual(result["avg_confidence"], 0.0)


class TestAggregatorTopSignals(unittest.TestCase):
    """top_signals 选取 (生产扩展, 供 synthesizer 使用)"""

    def test_top_signals_sorted_by_confidence(self):
        from aggregator import aggregate_subagent_outputs
        out = SubagentOutput(
            module="macro",
            summary="测试",
            signals=[
                Signal("low", 1, "long", 0.3),
                Signal("high", 2, "long", 0.9),
                Signal("mid", 3, "short", 0.6),
            ],
        )
        result = aggregate_subagent_outputs([out])
        top = result["top_signals"]
        self.assertGreaterEqual(len(top), 3)
        # 按置信度降序
        self.assertEqual(top[0]["name"], "high")
        self.assertEqual(top[1]["name"], "mid")
        self.assertEqual(top[2]["name"], "low")

    def test_top_signals_limit(self):
        from aggregator import aggregate_subagent_outputs
        outs = [SubagentOutput(
            module=f"m{i}", summary=f"s{i}",
            signals=[Signal(f"sig_{i}_{j}", j, "long", j * 0.1)
                     for j in range(5)],
        ) for i in range(3)]
        result = aggregate_subagent_outputs(outs)
        # 默认 top 5
        self.assertLessEqual(len(result["top_signals"]), 5)


if __name__ == "__main__":
    unittest.main()
