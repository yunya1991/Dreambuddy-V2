"""L4_meme 层：meme 温度驱动 D4 情绪力 + 筹码结构折扣。

口径（2026-11-20 用户确认）：40/scripts/p3_meme_platform_monitor.py 产出的
meme_platform.json → meme_layer 供 50 域 macro_force 消费：
  - meme_temperature 0.5 为中性；>0.5 过热 → 情绪转空，<0.5 冰点 → 转多
  - structure_risk 只做信号折扣（不产生方向）
  - meme_layer.degraded 或缺失 → 行为与旧版完全一致（fail-open）
"""

from __future__ import annotations

import pytest
from core.macro_force import (
    MEME_STRUCT_DISCOUNT,
    MEME_TEMP_SENTIMENT_WEIGHT,
    compute_macro_forces,
)


def _cycle_state():
    return {
        "real_cycle": {"last_change": "down", "confidence": "high"},
        "technical_anchor": {
            "assets": {"a0": {"above": True}, "a1": {"above": True}, "b0": {"above": False}},
            "regime": "bull",
        },
    }


def _sector(meme_gap=0.0):
    return {
        "layers": {"L1_anchor": ["BTC/USDT"], "L4_meme": ["DOGE/USDT"]},
        "assets": {
            "BTC/USDT": {"layer": "L1_anchor", "momentum_3m_pct": 5.0},
            "DOGE/USDT": {"layer": "L4_meme", "momentum_3m_pct": 20.0},
        },
        "layer_median_momentum_3m_pct": {"L1_anchor": 5.0, "L4_meme": 20.0},
        "transmission": {"state": "expanding", "meme_vs_major_gap_pct": meme_gap},
    }


def _resonance():
    return {
        "assets": {
            "DOGE/USDT": {
                "corr0": 1.0,
                "lag_profile": [1.0, 0.9, 0.4],
                "beta": 1.0,
                "down_corr": 1.0,
                "granger_p": 0.01,
            }
        }
    }


def _meme_platform(temp=None, structure=None, degraded=False):
    layer = {"degraded": degraded}
    if temp is not None:
        layer["meme_temperature"] = temp
    if structure is not None:
        layer["structure_risk"] = structure
    return {"meme_layer": layer}


def _d4(temp=None, structure=None, degraded=False, meme_gap=0.0):
    forces = compute_macro_forces(
        _cycle_state(),
        _resonance(),
        _sector(meme_gap),
        {},
        _meme_platform(temp, structure, degraded),
    )
    return forces["DOGE"].d4_sentiment


def test_neutral_temperature_keeps_baseline():
    # gap=0 → 基线 d4 = 0；温度 0.5 不改变
    assert _d4(temp=0.5) == pytest.approx(0.0, abs=1e-9)


def test_hot_temperature_turns_bearish():
    # dev=0.4 → temp_factor=-1；blended=-0.35；D4 权重 2.0 → -0.7
    assert _d4(temp=0.9) == pytest.approx(-0.7, abs=1e-6)


def test_cold_temperature_turns_bullish():
    assert _d4(temp=0.1) == pytest.approx(0.7, abs=1e-6)


def test_deadband_ignores_small_deviation():
    # 0.55 偏离 0.05 < 上/下门限，视为无信号
    assert _d4(temp=0.55) == pytest.approx(0.0, abs=1e-9)


def test_structure_risk_discounts_signal():
    full = _d4(temp=0.9)
    discounted = _d4(temp=0.9, structure=1.0)
    assert discounted == pytest.approx(full * (1 - MEME_STRUCT_DISCOUNT), abs=1e-6)
    assert abs(discounted) < abs(full)


def test_weight_matches_constant():
    # 热温度下 blended = -(MEME_TEMP_SENTIMENT_WEIGHT) × 2.0
    assert _d4(temp=0.9) == pytest.approx(-MEME_TEMP_SENTIMENT_WEIGHT * 2.0, abs=1e-6)


def test_degraded_layer_falls_back_to_gap_only():
    # gap=+7 → 基线 -7/15*2 = -0.9333
    assert _d4(degraded=True, meme_gap=7.0) == pytest.approx(-7.0 / 15.0 * 2.0, abs=1e-6)

    forces = compute_macro_forces(
        _cycle_state(), _resonance(), _sector(), {}, _meme_platform(degraded=True)
    )
    assert "meme_layer_degraded" in forces["DOGE"].degraded


def test_missing_platform_keeps_backward_compat():
    forces = compute_macro_forces(_cycle_state(), _resonance(), _sector(7.0), {})
    assert forces["DOGE"].d4_sentiment == pytest.approx(-7.0 / 15.0 * 2.0, abs=1e-6)
    assert forces["DOGE"].degraded == []
