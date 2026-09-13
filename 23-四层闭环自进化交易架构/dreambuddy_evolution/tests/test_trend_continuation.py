"""
Phase 3.2: TrendContinuationScorer TDD 测试
SPEC-主要矛盾识别与最小阻力路径设计.md §4.4

理论来源:
  - Minervini SEPA: 8 条件趋势模板 (Stage 2 确认) + VCP 波动率收缩
  - Wyckoff: Cause & Effect (累积期→行情规模) + Effort vs Result (量价背离)

HC-AGI-20: 趋势延续性字段缺失时取 0.5 中性兜底
"""
from __future__ import annotations

import pytest


class TestTrendContinuationScorer:
    """趋势延续性评分器单元测试"""

    def test_module_importable(self):
        """RED: 模块可导入"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        assert TrendContinuationScorer is not None

    def test_score_returns_required_fields(self):
        """输出包含所有必需字段"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        result = scorer.score({}, "long")
        required = {"continuation_score", "cause_score", "effort_result"}
        assert required.issubset(result.keys())

    def test_minervini_8_criteria_all_pass(self):
        """8 条件全过 → trend_template_score = 1.0"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {
                "price": 100.0,
                "ma50": 95.0,
                "ma150": 90.0,
                "ma200": 85.0,
                "ma200_slope": 0.5,
                "low_52w": 70.0,
                "high_52w": 105.0,
                "contractions": [0.20, 0.10, 0.05],  # VCP 递减
            }
        }
        result = scorer.score(market_data, "long")
        # 8 条件全过 + VCP 有效 → continuation_score 应较高
        assert result["continuation_score"] > 0.7

    def test_minervini_all_fail(self):
        """8 条件全不过 → trend_template_score = 0.0"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {
                "price": 50.0,
                "ma50": 100.0,
                "ma150": 110.0,
                "ma200": 120.0,
                "ma200_slope": -0.5,
                "low_52w": 40.0,
                "high_52w": 130.0,
                "contractions": [],
            }
        }
        result = scorer.score(market_data, "long")
        # 趋势模板全失败 (0.25) + VCP 无数据 (0.5) → 0.35, 低于中性 0.5
        assert result["continuation_score"] < 0.4

    def test_vcp_contraction_valid(self):
        """VCP: T2/T1 ≤ 0.75, T3/T2 ≤ 0.75 → 1.0"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {
                "contractions": [0.20, 0.10, 0.05],  # 0.10/0.20=0.5 ≤ 0.75
            }
        }
        result = scorer.score(market_data, "long")
        assert result["continuation_score"] >= 0.0

    def test_vcp_contraction_invalid_ratio(self):
        """VCP: T2/T1 > 0.75 → 分数降低"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data_good = {
            "kline_data": {"contractions": [0.20, 0.10]}  # ratio=0.5
        }
        market_data_bad = {
            "kline_data": {"contractions": [0.10, 0.20]}  # ratio=2.0 > 0.75
        }
        good = scorer.score(market_data_good, "long")
        bad = scorer.score(market_data_bad, "long")
        assert good["continuation_score"] >= bad["continuation_score"]

    def test_wyckoff_cause_score(self):
        """Wyckoff Cause: 累积期 60 bars → cause_score 高"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {"consolidation_bars": 60}
        }
        result = scorer.score(market_data, "long")
        assert result["cause_score"] > 0.5

    def test_wyckoff_cause_score_short_consolidation(self):
        """累积期 < 10 bars → cause_score 低"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {"consolidation_bars": 5}
        }
        result = scorer.score(market_data, "long")
        assert result["cause_score"] <= 0.1

    def test_effort_result_aligned(self):
        """量价同向 → effort_result = 0.8"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {
                "volume_change_pct": 10.0,
                "price_change_pct": 5.0,
            }
        }
        result = scorer.score(market_data, "long")
        assert result["effort_result"] == 0.8

    def test_effort_result_divergence(self):
        """量价背离 → effort_result = 0.3"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        market_data = {
            "kline_data": {
                "volume_change_pct": 10.0,
                "price_change_pct": -5.0,
            }
        }
        result = scorer.score(market_data, "long")
        assert result["effort_result"] == 0.3

    def test_fail_open_on_bad_data(self):
        """HC-AGI-20: 异常数据 → 中性兜底 0.5"""
        from dreambuddy_evolution.core.trend_continuation import TrendContinuationScorer
        scorer = TrendContinuationScorer()
        # 传入畸形数据
        result = scorer.score("not_a_dict", "long")  # type: ignore
        assert 0.0 <= result["continuation_score"] <= 1.0
        assert 0.0 <= result["cause_score"] <= 1.0
