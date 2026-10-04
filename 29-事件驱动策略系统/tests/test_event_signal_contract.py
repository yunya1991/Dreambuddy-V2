"""test_event_signal_contract.py — Phase 2 EventSignal 契约标准化

SPEC: SPEC-事件驱动策略独立化-共享事件层与弹性约束.md §六 Phase 2

验证:
1. EventSignal 契约：字段/枚举校验/边界/roundtrip
2. 弹性系数计算：4 种组合（顺势+1.0 / 逆势-0.7 / 无约束0.0）
3. neutral_event_signal() 工厂
4. FAIL-OPEN: from_dict 异常返回 neutral
5. EventDrivenStrategy.evaluate() 返回 EventSignal 且 elasticity 正确
"""
from __future__ import annotations

import pytest


class TestEventSignalContract:
    """EventSignal 数据契约"""

    def test_event_signal_fields_exist(self):
        """EventSignal 包含所有必需字段"""
        from event_driven.event_driven_strategy import EventSignal
        sig = EventSignal(
            signal="long",
            strength=0.80,
            elasticity=1.0,
            event_type="fomc",
            event_phase="repricing",
            window_start="2026-10-28",
            window_end="2026-11-02",
            confidence=0.90,
            scores={"priced_in": 0.85},
            reason="利空出尽",
            forward_guidance="dovish",
        )
        assert sig.signal == "long"
        assert sig.strength == 0.80
        assert sig.elasticity == 1.0
        assert sig.event_type == "fomc"
        assert sig.event_phase == "repricing"
        assert sig.window_start == "2026-10-28"
        assert sig.window_end == "2026-11-02"
        assert sig.confidence == 0.90
        assert sig.scores == {"priced_in": 0.85}
        assert sig.reason == "利空出尽"
        assert sig.forward_guidance == "dovish"

    def test_event_signal_frozen(self):
        """EventSignal 是 frozen dataclass（不可变）"""
        from event_driven.event_driven_strategy import EventSignal
        sig = EventSignal(
            signal="neutral", strength=0.0, elasticity=0.0,
            event_type="none", event_phase="neutral",
            window_start=None, window_end=None,
            confidence=0.0, scores={}, reason="", forward_guidance="",
        )
        with pytest.raises(Exception):
            sig.signal = "long"  # type: ignore[misc]

    def test_signal_enum_validation(self):
        """signal 必须是 long/short/neutral 之一"""
        from event_driven.event_driven_strategy import EventSignal
        for valid in ("long", "short", "neutral"):
            sig = EventSignal(
                signal=valid, strength=0.5, elasticity=0.0,
                event_type="none", event_phase="neutral",
                window_start=None, window_end=None,
                confidence=0.5, scores={}, reason="", forward_guidance="",
            )
            assert sig.signal == valid

    def test_strength_and_confidence_boundary(self):
        """strength 和 confidence 必须在 [0, 1]"""
        from event_driven.event_driven_strategy import EventSignal
        # 边界值合法
        sig = EventSignal(
            signal="long", strength=0.0, elasticity=0.0,
            event_type="none", event_phase="neutral",
            window_start=None, window_end=None,
            confidence=1.0, scores={}, reason="", forward_guidance="",
        )
        assert sig.strength == 0.0
        assert sig.confidence == 1.0

    def test_elasticity_boundary(self):
        """elasticity 必须在 [-1, 1]"""
        from event_driven.event_driven_strategy import EventSignal
        sig = EventSignal(
            signal="long", strength=0.5, elasticity=-1.0,
            event_type="none", event_phase="neutral",
            window_start=None, window_end=None,
            confidence=0.5, scores={}, reason="", forward_guidance="",
        )
        assert sig.elasticity == -1.0

    def test_to_dict_roundtrip(self):
        """to_dict / from_dict roundtrip"""
        from event_driven.event_driven_strategy import EventSignal
        sig = EventSignal(
            signal="short", strength=0.70, elasticity=-0.7,
            event_type="nfp", event_phase="expectation_jump",
            window_start="2026-10-02", window_end="2026-10-07",
            confidence=0.85, scores={"priced_in": 0.30},
            reason="非农超预期", forward_guidance="hawkish",
        )
        d = sig.to_dict()
        restored = EventSignal.from_dict(d)
        assert restored.signal == sig.signal
        assert restored.strength == sig.strength
        assert restored.elasticity == sig.elasticity
        assert restored.event_type == sig.event_type
        assert restored.event_phase == sig.event_phase
        assert restored.window_start == sig.window_start
        assert restored.window_end == sig.window_end
        assert restored.confidence == sig.confidence
        assert restored.reason == sig.reason

    def test_from_dict_fail_open(self):
        """from_dict 异常 → FAIL-OPEN 返回 neutral_event_signal"""
        from event_driven.event_driven_strategy import EventSignal
        restored = EventSignal.from_dict({"invalid": "data"})
        assert restored.signal == "neutral"
        assert restored.strength == 0.0
        assert restored.elasticity == 0.0

    def test_neutral_event_signal_factory(self):
        """neutral_event_signal() 工厂返回中性信号"""
        from event_driven.event_driven_strategy import (
            EventSignal, neutral_event_signal,
        )
        sig = neutral_event_signal()
        assert isinstance(sig, EventSignal)
        assert sig.signal == "neutral"
        assert sig.strength == 0.0
        assert sig.elasticity == 0.0
        assert sig.event_type == "none"
        assert sig.confidence == 0.0

    def test_event_driven_signal_alias(self):
        """EventDrivenSignal 是 EventSignal 的别名（向后兼容）"""
        from event_driven.event_driven_strategy import (
            EventDrivenSignal, EventSignal,
        )
        assert EventDrivenSignal is EventSignal


class TestElasticityComputation:
    """弹性系数计算：事件方向 × 趋势方向"""

    def test_elasticity_bullish_event_uptrend(self):
        """利多事件 × 上升趋势 → +1.0（顺势共振）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {
            "ess_top_direction": "long",
            "close": [100.0 + i for i in range(20)],
        }
        assert strat._compute_elasticity("long", kline_data) == 1.0

    def test_elasticity_bearish_event_downtrend(self):
        """利空事件 × 下降趋势 → +1.0（顺势共振）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {
            "ess_top_direction": "short",
            "close": [100.0 - i for i in range(20)],
        }
        assert strat._compute_elasticity("short", kline_data) == 1.0

    def test_elasticity_bullish_event_downtrend(self):
        """利多事件 × 下降趋势 → -0.7（逆势反弹，做空机会）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {
            "ess_top_direction": "short",
            "close": [100.0 - i for i in range(20)],
        }
        assert strat._compute_elasticity("long", kline_data) == -0.7

    def test_elasticity_bearish_event_uptrend(self):
        """利空事件 × 上升趋势 → -0.7（逆势回调，做多机会）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {
            "ess_top_direction": "long",
            "close": [100.0 + i for i in range(20)],
        }
        assert strat._compute_elasticity("short", kline_data) == -0.7

    def test_elasticity_neutral_signal(self):
        """事件 neutral → 0.0（无弹性约束）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {"ess_top_direction": "long", "close": [100.0] * 20}
        assert strat._compute_elasticity("neutral", kline_data) == 0.0

    def test_elasticity_no_trend_direction(self):
        """无趋势方向（ess_top_direction 缺失）→ 用 close 斜率兜底"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        # 上升 close 序列 → 趋势 long
        kline_data = {"close": [100.0 + i for i in range(20)]}
        assert strat._compute_elasticity("long", kline_data) == 1.0

    def test_elasticity_flat_close_no_direction(self):
        """close 序列水平且无 ess → 趋势 neutral → elasticity 0.0"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {"close": [100.0] * 20}
        assert strat._compute_elasticity("long", kline_data) == 0.0


class TestEventDrivenStrategyReturnsEventSignal:
    """EventDrivenStrategy.evaluate() 返回 EventSignal"""

    def test_evaluate_returns_event_signal(self):
        """evaluate() 返回 EventSignal 实例，包含 elasticity"""
        from event_driven.event_driven_strategy import (
            EventDrivenStrategy, EventSignal,
        )
        strat = EventDrivenStrategy()
        kline_data = {
            "event_context": {
                "in_fomc_cycle": True,
                "cycle_phase": "repricing",
                "hike_prob": 0.10,
            },
            "cpi_actual": 3.0,
            "close": [100.0 + i for i in range(20)],
            "ess_top_direction": "long",
        }
        sig = strat.evaluate(kline_data)
        assert isinstance(sig, EventSignal)
        assert hasattr(sig, "elasticity")
        assert hasattr(sig, "strength")
        assert hasattr(sig, "event_type")

    def test_evaluate_neutral_when_no_event(self):
        """无事件触发时返回 neutral EventSignal，elasticity=0.0"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kline_data = {"event_context": {}, "close": [100.0] * 20}
        sig = strat.evaluate(kline_data)
        assert sig.signal == "neutral"
        assert sig.elasticity == 0.0
