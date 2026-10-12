"""
P1-2 RED: ResultAggregator 组件契约测试
来源: SPEC v0.3 §2.B — 从 kline_event_handler.py 拆出结果聚合+bridge回调+反馈职责

拆分目标:
- trigger_build_position(symbol, action, d_star, ri, position_mult, tier, source_tag)->None
- apply_macro_event_filter(kline_data, action, d_star, ...)->tuple[str, str, float]
- store_pre_trade_snapshot(symbol, action, d_star, ess_dir, ri, position_mult)->None
- get_evolution_feedback()->dict (L3/L4 反馈)
- attach_trader(trader)->None
"""
from __future__ import annotations

import pytest


class TestResultAggregatorContract:
    """ResultAggregator 接口契约 — RED 阶段断言模块尚未创建"""

    def test_module_importable(self):
        from dreambuddy_evolution.engines.result_aggregator import ResultAggregator  # noqa: F401

    def test_class_instantiates_with_defaults(self):
        from dreambuddy_evolution.engines.result_aggregator import ResultAggregator
        aggregator = ResultAggregator()
        assert aggregator is not None


class TestGetEvolutionFeedback:
    """get_evolution_feedback 返回 L3/L4 反馈 dict"""

    def test_returns_dict_with_required_keys(self):
        from dreambuddy_evolution.engines.result_aggregator import ResultAggregator
        aggregator = ResultAggregator()
        feedback = aggregator.get_evolution_feedback()
        assert isinstance(feedback, dict)
        # FAIL-OPEN 时也应有这三个 key
        assert "l3_stats" in feedback
        assert "l4_v_all" in feedback
        assert "l4_ess_adjustments" in feedback


class TestApplyMacroEventFilter:
    """apply_macro_event_filter 返回过滤后的 (action, d_star, ri)"""

    def test_returns_tuple_when_no_filter_data(self):
        from dreambuddy_evolution.engines.result_aggregator import ResultAggregator
        aggregator = ResultAggregator()
        kline_data = {"symbol": "BTC-USDT-SWAP"}
        result = aggregator.apply_macro_event_filter(
            kline_data=kline_data,
            action="long",
            d_star="long",
            ri=0.5,
        )
        # 应返回 (action, d_star, ri) 元组
        assert isinstance(result, tuple)
        assert len(result) == 3
