"""50 决策侧 SL/TP 波动率口径测试（Wilder ATR% → 间距百分比）。"""

from __future__ import annotations

import sys
from pathlib import Path

_50_ROOT = Path(__file__).resolve().parents[1]
if str(_50_ROOT) not in sys.path:
    sys.path.insert(0, str(_50_ROOT))

from core.volatility import (  # noqa: E402
    SL_ATR_MULT,
    TP_CAP_PCT,
    TP_SL_RATIO,
    resolve_sl_tp_pct,
    sl_floor_pct,
    wilder_atr_pct,
)


def _candles(*triples: tuple[float, float, float]) -> list[dict[str, float]]:
    return [{"h": h, "l": low, "c": c} for h, low, c in triples]


def test_wilder_atr_pct_matches_manual_average():
    """period=2 且 TR 恒定时 ATR% = TR / last_close × 100。"""
    rows = _candles((10, 8, 9), (11, 9, 10), (12, 10, 11), (13, 11, 12))
    # TR 均为 2 → ATR=2，last close=12 → 2/12×100
    assert round(wilder_atr_pct(rows, period=2), 4) == round(2 / 12 * 100, 4)


def test_wilder_atr_pct_smooths_after_initial_period():
    """超出前 period 根后按 Wilder 递推：(ATR×(n-1)+TR)/n。"""
    rows = _candles((10, 8, 9), (11, 9, 10), (12, 10, 11), (20, 11, 19))
    # 初始 ATR=(2+2)/2=2；第 4 根 TR=max(20-11,|20-11|,|11-11|)=9
    # ATR=(2×1+9)/2=5.5；last close=19 → 5.5/19×100
    assert round(wilder_atr_pct(rows, period=2), 4) == round(5.5 / 19 * 100, 4)


def test_wilder_atr_pct_returns_zero_on_insufficient_sample():
    rows = _candles((10, 8, 9), (11, 9, 10), (12, 10, 11))
    assert wilder_atr_pct(rows, period=14) == 0.0
    assert wilder_atr_pct([], period=14) == 0.0


def test_resolve_sl_tp_uses_class_floor_when_atr_low():
    out = resolve_sl_tp_pct("crypto", 0.5)  # 0.5% 低波动 → 2×ATR=1% < 下限 3%
    assert out["sl_pct"] == 3.0
    assert out["tp_pct"] == 6.0
    assert out["source"] == "atr"


def test_resolve_sl_tp_scales_with_atr_and_keeps_1_2_ratio():
    out = resolve_sl_tp_pct("crypto", 2.5)
    assert out["sl_pct"] == round(SL_ATR_MULT * 2.5, 2) == 5.0
    assert out["tp_pct"] == round(TP_SL_RATIO * 5.0, 2) == 10.0


def test_resolve_sl_tp_caps_stay_inside_22_bounds():
    """极端波动也必须落在 22 的 0<sl<10 / 0<tp<20 边界内。"""
    out = resolve_sl_tp_pct("crypto", 25.0)
    assert 0 < out["sl_pct"] < 10
    assert 0 < out["tp_pct"] < 20
    assert out["tp_pct"] <= TP_CAP_PCT


def test_resolve_sl_tp_falls_back_to_floor_when_atr_missing():
    out = resolve_sl_tp_pct("us_index", 0.0)
    assert out["source"] == "atr_missing"
    assert out["sl_pct"] == sl_floor_pct("us_index") == 2.0
    assert out["tp_pct"] == 4.0


def test_resolve_sl_tp_ignores_dirty_atr_value():
    """异常值（>30%）视为脏数据，退回类别下限而不是放大间距。"""
    out = resolve_sl_tp_pct("crypto", 88.0)
    assert out["source"] == "atr_missing"
    assert out["sl_pct"] == 3.0


def test_unknown_asset_class_uses_default_floor():
    assert sl_floor_pct("unknown_class") == 2.5
