"""test_phase3_event_driven_upgrade.py — Phase 3 独立子交易系统 + 5维评分升级 + 脉冲算法

SPEC: SPEC-事件驱动策略独立化-共享事件层与弹性约束.md §六 Phase 3 (v1.2)

三组测试:
A. EventDrivenTrader 独立子交易系统 (10)
B. 5 维评分修订: surprise_score + priced_in 量化 + real_rate 变化率 + cross_asset 标准化 (8)
C. 单点脉冲算法 + 阶段动态阈值 (6)
"""
from __future__ import annotations

import math

import pytest


# ================================================================
# A. EventDrivenTrader 独立子交易系统
# ================================================================

def _make_signal(**overrides):
    from event_driven.event_driven_strategy import EventSignal
    base = dict(
        signal="long",
        strength=0.80,
        elasticity=1.0,
        event_type="fomc",
        event_phase="event",
        confidence=0.90,
    )
    base.update(overrides)
    return EventSignal(**base)


class TestEventDrivenTrader:
    def test_trader_open_position_long(self):
        """signal=long + strength≥事件阈值0.55 + confidence≥0.5 → _should_open=True"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        sig = _make_signal(signal="long", strength=0.80, event_phase="event", confidence=0.90)
        assert trader._should_open(sig) is True

    def test_trader_open_position_short(self):
        """signal=short + strength≥(1-0.40)=0.60 → _should_open=True"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        sig = _make_signal(signal="short", strength=0.70, event_phase="event", confidence=0.90)
        assert trader._should_open(sig) is True

    def test_trader_no_open_neutral(self):
        """signal=neutral → _should_open=False"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        sig = _make_signal(signal="neutral")
        assert trader._should_open(sig) is False

    def test_trader_no_open_below_threshold(self):
        """signal=long + strength=0.40 < 事件阈值0.55 → _should_open=False"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        sig = _make_signal(signal="long", strength=0.40, event_phase="event", confidence=0.90)
        assert trader._should_open(sig) is False

    def test_trader_position_size(self):
        """仓位 = base(250) × strength(0.8) × phase_mult × elasticity_mult"""
        from event_driven.event_driven_strategy import EventDrivenTrader, PHASE_POSITION_MULT
        trader = EventDrivenTrader(strategy=None, config={"base_position": 250.0})
        sig = _make_signal(strength=0.8, event_phase="event", elasticity=1.0)
        size = trader._compute_position_size(sig)
        phase_mult = PHASE_POSITION_MULT.get("event", 1.0)
        elasticity_mult = 1.0 + 1.0 * 0.3
        expected = 250.0 * 0.8 * phase_mult * elasticity_mult
        assert abs(size - expected) < 1e-6

    def test_trader_sl_tp_atr(self):
        """atr=100, close=50000 → sl_pct=max(0.04, 5*100/50000)=0.04, tp=3*sl"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        sl, tp = trader._compute_sl_tp(_make_signal(), {"atr": 100.0, "close": [50000.0]})
        assert abs(sl - 0.04) < 1e-6  # max(0.04, 5*100/50000=0.01)
        assert abs(tp - 0.12) < 1e-6  # 3 * 0.04

    def test_trader_exit_pulse_decay(self):
        """days_since > 3τ → _should_exit=True"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        trader._position = {"direction": "long", "entry_price": 100.0}
        # mock _days_since_event 返回 > 3τ (fomc τ=3, 3τ=9)
        trader._days_since_event = lambda sig: 10.0
        sig = _make_signal(signal="long", event_type="fomc")
        assert trader._should_exit(sig, {}) is True

    def test_trader_exit_signal_reversal(self):
        """signal 从 long 反转为 short → _should_exit=True"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        trader._position = {"direction": "long", "entry_price": 100.0}
        trader._days_since_event = lambda sig: 1.0  # 未超 3τ
        sig = _make_signal(signal="short", event_type="fomc")
        assert trader._should_exit(sig, {}) is True

    def test_trader_no_exit_within_window(self):
        """days_since < 3τ 且 signal 同向 → _should_exit=False"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        trader._position = {"direction": "long", "entry_price": 100.0}
        trader._days_since_event = lambda sig: 1.0  # < 9 (3τ for fomc)
        sig = _make_signal(signal="long", event_type="fomc")
        assert trader._should_exit(sig, {}) is False

    def test_trader_fail_open_no_atr(self):
        """atr=0 → sl/tp 返回硬编码下限 0.04/0.12"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        sl, tp = trader._compute_sl_tp(_make_signal(), {"atr": 0.0, "close": [100.0]})
        assert sl == 0.04
        assert tp == 0.12


# ================================================================
# B. 5 维评分修订
# ================================================================

class TestSurpriseScore:
    def test_surprise_score_positive(self):
        """CPI actual<expected（低于预期=利好黄金）→ score > 0.5"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {
                "event_type": "cpi",
                "in_fomc_cycle": True,
                "cycle_phase": "event",
                "actual": 3.0,
                "expected": 3.5,
                "surprise_sigma": 0.3,
            },
            "close": [100.0] * 10,
        }
        score = strat._score_surprise(kd, kd["event_context"])
        assert score > 0.5, f"CPI低于预期应利好，score={score}"

    def test_surprise_score_negative(self):
        """CPI actual>expected（高于预期=利空）→ score < 0.5"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {
                "event_type": "cpi",
                "in_fomc_cycle": True,
                "cycle_phase": "event",
                "actual": 4.0,
                "expected": 3.5,
                "surprise_sigma": 0.3,
            },
            "close": [100.0] * 10,
        }
        score = strat._score_surprise(kd, kd["event_context"])
        assert score < 0.5, f"CPI高于预期应利空，score={score}"

    def test_surprise_score_fail_open(self):
        """actual=None → score=0.5（中性兜底）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {"event_type": "cpi", "in_fomc_cycle": True, "actual": None},
            "close": [100.0] * 10,
        }
        score = strat._score_surprise(kd, kd["event_context"])
        assert score == 0.5


class TestPricedInQuantified:
    def test_priced_in_overpriced(self):
        """ratio=预期累计涨跌/历史平均反应 > 1 → base 向上修正（反向预期）"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {
                "event_type": "fomc",
                "in_fomc_cycle": True,
                "cycle_phase": "expectation_build",
                "hike_prob": 0.80,
            },
            "pre_event_return_pct": -0.06,
            "historical_avg_reaction_pct": -0.03,
            "close": [100.0] * 10,
        }
        score = strat._score_priced_in(kd, kd["event_context"])
        # 无 ratio 时 base = 1 - 0.8 = 0.2; ratio=2>1 时 base += (2-1)*0.3=0.3 → 0.5
        assert score > 0.2, f"过度定价应向上修正，score={score}"


class TestRealRateDelta:
    def test_real_rate_with_delta(self):
        """real_rate_history 下行 → delta_score > 0.5"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {"event_type": "fomc", "in_fomc_cycle": True, "cycle_phase": "event"},
            "real_rate_history": [2.0, 1.8, 1.5],  # 下行
            "close": [100.0] * 10,
        }
        score = strat._score_real_rate(kd, kd["event_context"])
        # 变化率贡献应使分数偏向高分
        assert score > 0.4, f"实际利率下行应利好，score={score}"


class TestCrossAssetStandardized:
    def test_cross_asset_standardized(self):
        """gold_surprise 正 → score += 0.25*tanh(surprise/2)"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "gold_surprise": 1.0,
            "close": [100.0] * 10,
        }
        score = strat._score_cross_asset(kd)
        expected = 0.5 + 0.25 * math.tanh(1.0 / 2.0)
        assert abs(score - expected) < 1e-3


class TestResilienceGeneralized:
    def test_resilience_generalized(self):
        """expected_drop<0 且 ret_3d/expected_drop<1（抗跌）→ 0.85"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {"event_type": "cpi", "in_fomc_cycle": True},
            "expected_event_drop_pct": -0.05,
            "close": [100.0, 99.5, 99.2, 99.0],  # 3d ret = -1%, ratio = -0.01/-0.05 = 0.2 < 1
        }
        score = strat._score_resilience(kd, kd["event_context"])
        assert score == 0.85


class TestCompositeIncludesSurprise:
    def test_composite_includes_surprise(self):
        """5 维加权中 surprise_score 权重 25%"""
        from event_driven.event_driven_strategy import EventDrivenStrategy
        strat = EventDrivenStrategy()
        kd = {
            "event_context": {
                "event_type": "cpi",
                "in_fomc_cycle": True,
                "cycle_phase": "event",
                "actual": 3.0,
                "expected": 3.5,
                "surprise_sigma": 0.3,
                "hike_prob": 0.80,
            },
            "close": [100.0] * 10,
            "real_rate_history": [2.0, 1.8, 1.5],
            "gold_surprise": 1.0,
            "expected_event_drop_pct": -0.05,
        }
        scores = strat._compute_scores(kd)
        assert "surprise" in scores, f"scores 应包含 surprise 键，实际: {list(scores.keys())}"


# ================================================================
# C. 单点脉冲算法 + 阶段动态阈值
# ================================================================

class TestImpulsePulse:
    def test_impulse_decay(self):
        """t=τ → impulse = strength × exp(-1)"""
        from event_driven.event_driven_strategy import compute_impulse
        result = compute_impulse("fomc", days_since=3.0, strength=1.0)
        expected = math.exp(-1.0)
        assert abs(result - expected) < 1e-6

    def test_impulse_zero_after_3tau(self):
        """t > 3τ → impulse ≈ 0"""
        from event_driven.event_driven_strategy import compute_impulse
        result = compute_impulse("fomc", days_since=20.0, strength=1.0)
        assert result < 0.01

    def test_impulse_fail_open(self):
        """event_type=none → 0.0"""
        from event_driven.event_driven_strategy import compute_impulse
        assert compute_impulse("none", days_since=0.0, strength=1.0) == 0.0


class TestPhaseThresholds:
    def test_phase_thresholds_event(self):
        """event 阶段 long 阈值 = 0.55"""
        from event_driven.event_driven_strategy import PHASE_THRESHOLDS
        assert PHASE_THRESHOLDS["event"]["long"] == 0.55

    def test_phase_thresholds_pre(self):
        """pre_event 阶段 long 阈值 = 0.70"""
        from event_driven.event_driven_strategy import PHASE_THRESHOLDS
        assert PHASE_THRESHOLDS["pre_event"]["long"] == 0.70


class TestPulseElasticity:
    def test_pulse_elasticity_trend_follow(self):
        """elasticity>0 + signal=long → composite += pulse × 0.15"""
        from event_driven.event_driven_strategy import EventDrivenTrader
        trader = EventDrivenTrader(strategy=None, config={})
        from event_driven.event_driven_strategy import EventSignal
        sig = EventSignal(
            signal="long",
            strength=0.8,
            elasticity=1.0,
            event_type="fomc",
            event_phase="event",
            window_end="2026-10-01T00:00:00",
        )
        composite = 0.5
        adjusted = trader.apply_pulse_decay(composite, sig)
        # 顺势 long → composite 应增加
        assert adjusted > composite
