"""
T13c: AiCycleScorer TDD 测试
SPEC §0.5.2 — AI 周期评分

规则:
  HBM 需求 / 资本开支 / 半导体景气度 → 0.0-1.0
  >0.7 → 半导体不做空（AI 周期对冲利率压力）

HC: 开关关断时返回 0.5（中性）
HC: FAIL-OPEN 异常返回 0.5
"""
from __future__ import annotations

import pytest


@pytest.fixture
def enable_ai_cycle(monkeypatch):
    from dreambuddy_evolution.agi_config import set_switch
    set_switch("enable_agi_core", True)
    set_switch("enable_contradiction_driven_layer", True)
    set_switch("enable_ai_cycle_scorer", True)
    yield


class TestAiCycleScorer:
    """AI 周期评分单元测试 (T13c)"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        assert AiCycleScorer is not None

    def test_high_score_when_semiconductor_boom(self, enable_ai_cycle):
        """半导体景气度高 → 高分"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        kline_data = {
            "sox_change_30d": 15.0,  # SOX 30天涨幅 15%
            "semiconductor_capex_yoy": 20.0,  # 半导体资本开支同比 20%
            "hbm_demand_index": 0.85,  # HBM 需求指数
        }
        result = scorer.score(kline_data)
        assert 0.7 <= result <= 1.0

    def test_low_score_when_semiconductor_weak(self, enable_ai_cycle):
        """半导体景气度低 → 低分"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        kline_data = {
            "sox_change_30d": -10.0,
            "semiconductor_capex_yoy": -5.0,
            "hbm_demand_index": 0.2,
        }
        result = scorer.score(kline_data)
        assert result < 0.4

    def test_medium_score_when_mixed(self, enable_ai_cycle):
        """混合信号 → 中等分数"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        kline_data = {
            "sox_change_30d": 3.0,
            "semiconductor_capex_yoy": 5.0,
            "hbm_demand_index": 0.5,
        }
        result = scorer.score(kline_data)
        assert 0.4 <= result <= 0.7

    def test_neutral_when_no_data(self, enable_ai_cycle):
        """无数据 → 0.5 中性"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        result = scorer.score({})
        assert result == 0.5

    def test_switch_off_returns_neutral(self):
        """HC: 开关关断时返回 0.5"""
        from dreambuddy_evolution.agi_config import set_switch
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        set_switch("enable_agi_core", True)
        set_switch("enable_contradiction_driven_layer", False)
        set_switch("enable_ai_cycle_scorer", True)
        scorer = AiCycleScorer()
        result = scorer.score({"sox_change_30d": 20.0})
        assert result == 0.5

    def test_fail_open_on_exception(self, enable_ai_cycle):
        """HC: 异常时 FAIL-OPEN 返回 0.5"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        result = scorer.score(None)
        assert result == 0.5

    def test_score_range_0_to_1(self, enable_ai_cycle):
        """评分在 0.0-1.0 范围内"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        # 极端高
        result = scorer.score({
            "sox_change_30d": 50.0,
            "semiconductor_capex_yoy": 50.0,
            "hbm_demand_index": 1.0,
        })
        assert 0.0 <= result <= 1.0
        # 极端低
        result = scorer.score({
            "sox_change_30d": -50.0,
            "semiconductor_capex_yoy": -50.0,
            "hbm_demand_index": 0.0,
        })
        assert 0.0 <= result <= 1.0

    def test_above_0_7_indicates_hedge(self, enable_ai_cycle):
        """>0.7 时半导体可对冲利率压力"""
        from dreambuddy_evolution.engines.ai_cycle_scorer import AiCycleScorer
        scorer = AiCycleScorer()
        kline_data = {
            "sox_change_30d": 20.0,
            "semiconductor_capex_yoy": 25.0,
            "hbm_demand_index": 0.9,
        }
        result = scorer.score(kline_data)
        assert result > 0.7
