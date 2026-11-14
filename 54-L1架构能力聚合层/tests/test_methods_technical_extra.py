# -*- coding: utf-8 -*-
"""I 组第二批方法（I03–I06、I08、I10、I11、I13、I16、I18、I19、I24–I34）的数值验收。

口径来源：[docs/METHOD_LIBRARY.md §6](../docs/METHOD_LIBRARY.md)。
所有断言都验证真实数值或数学性质（常数序列、单调序列、区间约束），
另含确定性（同输入同输出）与样本门禁两类契约测试。
"""

import os
import sys

import pytest

_MODULE_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
if _MODULE_ROOT not in sys.path:
    sys.path.insert(0, _MODULE_ROOT)

import l1agg.methods.technical  # noqa: E402,F401  # 触发 I 组全部登记
from l1agg.methods import get, run  # noqa: E402

N = 120


def _ramp(n=N, start=100.0, step=0.5):
    close = [start + step * i for i in range(n)]
    return {
        "close": close,
        "high": [c + 1.0 for c in close],
        "low": [c - 1.0 for c in close],
        "volume": [1000.0 + 10.0 * i for i in range(n)],
    }


def _down(n=N, start=200.0, step=0.5):
    close = [start - step * i for i in range(n)]
    return {
        "close": close,
        "high": [c + 1.0 for c in close],
        "low": [c - 1.0 for c in close],
        "volume": [1000.0] * n,
    }


def _flat(n=N, price=100.0):
    return {
        "close": [price] * n,
        "high": [price + 1.0] * n,
        "low": [price - 1.0] * n,
        "volume": [1000.0] * n,
    }


# ============================================================
# I03–I06：均线族
# ============================================================


def test_i03_wma_constant_and_ramp():
    assert get("I03").output_schema == ("wma",)
    flat = run("I03", _flat(40))["result"]["wma"]
    assert flat == pytest.approx(100.0)
    # 线性上涨序列：WMA 赋予最新价更高权重，必然高于同周期 SMA
    close = [100.0 + 0.5 * i for i in range(40)]
    wma = run("I03", {"close": close})["result"]["wma"]
    sma20 = sum(close[-20:]) / 20.0
    assert wma > sma20
    assert wma == pytest.approx(sum(w * v for w, v in enumerate(close[-20:], start=1)) / 210.0)


def test_i04_ma_position_zero_on_flat_positive_on_ramp():
    flat = run("I04", _flat(40))["result"]["pos"]
    assert flat["20"] == pytest.approx(0.0)
    assert flat["5"] == pytest.approx(0.0)
    ramp = run("I04", _ramp(N))["result"]["pos"]
    assert ramp["20"] > 0.0


def test_i05_ma_stack_bull_and_bear():
    bull = run("I05", _ramp(N))["result"]
    assert bull["stack"] == "多头排列"
    assert bull["ma5"] > bull["ma20"] > bull["ma60"]
    bear = run("I05", _down(N))["result"]
    assert bear["stack"] == "空头排列"
    assert bear["ma5"] < bear["ma20"] < bear["ma60"]


def test_i06_ma_cross_golden_and_death():
    golden = run("I06", {"close": [100.0] * 25 + [110.0] * 10})["result"]
    assert golden["cross"] == "golden"
    assert golden["bars_since"] is not None and golden["bars_since"] >= 0
    assert golden["ma_fast"] > golden["ma_slow"]
    death = run("I06", {"close": [100.0] * 25 + [90.0] * 10})["result"]
    assert death["cross"] == "death"
    assert death["ma_fast"] < death["ma_slow"]


# ============================================================
# I08 / I10：背离与 MACD 柱
# ============================================================


def test_i08_rsi_divergence_none_on_monotone_ramp():
    out = run("I08", _ramp(N))["result"]
    # 单边上涨：价格与 RSI 同步创高，无背离
    assert out["divergence"] == "none"
    assert out["price_delta"] > 0.0
    assert out["rsi_delta"] == pytest.approx(0.0)


def test_i10_macd_hist_delta_zero_on_flat():
    out = run("I10", _flat(80))["result"]
    assert out["hist"] == pytest.approx(0.0)
    assert out["prev_hist"] == pytest.approx(0.0)
    assert out["delta"] == pytest.approx(0.0)
    assert out["expanding"] is False


# ============================================================
# I11 / I13 / I16
# ============================================================


def test_i11_kdj_flat_is_50_and_bounded_on_ramp():
    flat = run("I11", _flat(40))["result"]
    assert flat["k"] == pytest.approx(50.0)
    assert flat["d"] == pytest.approx(50.0)
    assert flat["j"] == pytest.approx(50.0)
    ramp = run("I11", _ramp(N))["result"]
    assert 0.0 <= ramp["k"] <= 100.0
    assert 0.0 <= ramp["d"] <= 100.0
    assert ramp["j"] == pytest.approx(3.0 * ramp["k"] - 2.0 * ramp["d"])


def test_i13_true_range_flat_band():
    out = run("I13", _flat(40))["result"]
    # H=101/L=99/C=100 → TR=2，tr_pct=2%
    assert out["tr"] == pytest.approx(2.0)
    assert out["tr_pct"] == pytest.approx(0.02)
    assert out["max_tr"] == pytest.approx(2.0)


def test_i16_boll_width_zero_flat_and_positive_on_oscillation():
    flat = run("I16", _flat(40))["result"]
    assert flat["width"] == pytest.approx(0.0)
    oscillate = {"close": [100.0, 102.0] * 10}
    out = run("I16", oscillate)["result"]
    assert out["width"] > 0.0
    assert out["width"] == pytest.approx((out["upper"] - out["lower"]) / out["mid"])


# ============================================================
# I18 / I19 / I34：量能族
# ============================================================


def test_i18_obv_first_zero_and_accumulates_volume():
    flat = run("I18", _flat(40))["result"]
    assert flat["obv"] == pytest.approx(0.0)
    rising = run("I18", {"close": [100.0 + i for i in range(40)], "volume": [10.0] * 40})["result"]
    # 首根 OBV=0，其后 39 根每根 +10
    assert rising["obv"] == pytest.approx(390.0)
    assert rising["obv_change"] == pytest.approx(200.0)
    assert rising["n"] == 40


def test_i19_volume_zscore_flat_zero_and_spike_positive():
    flat = run("I19", _flat(40))["result"]
    assert flat["z"] == pytest.approx(0.0)
    spike = run("I19", {"close": [100.0] * 40, "volume": [1000.0] * 39 + [2000.0]})["result"]
    assert spike["z"] > 0.0
    assert spike["volume"] == pytest.approx(2000.0)


def test_i34_turnover_ratio_matches_vwap_over_close():
    data = _flat(40)
    data["turnover"] = [c * v * 1.01 for c, v in zip(data["close"], data["volume"], strict=True)]
    out = run("I34", data)["result"]
    assert out["ratio"] == pytest.approx(1.01)
    assert out["vwap"] == pytest.approx(101.0)


# ============================================================
# I24–I29：突破 / 极值 / 回撤 / 通道 / 动量
# ============================================================


def test_i24_breakout_uses_prior_high():
    data = _ramp(N)
    out = run("I24", data)["result"]
    # 单调上涨：同时突破 20 日与 60 日前高，按方法库顺序先记 20
    assert out["breakout"] == "20"
    assert out["prior_high_20"] == pytest.approx(data["close"][-2])
    assert out["prior_high_60"] == pytest.approx(data["close"][-2])
    assert out["close"] > out["prior_high_20"]


def test_i25_extreme_days_counts_rolling_max():
    out = run("I25", _ramp(N))["result"]
    # 单调上涨：最近 20 根每根都是 trailing 20 根最高，且没有一根是最低
    assert out["new_high_days"] == 20
    assert out["new_low_days"] == 0
    down = run("I25", _down(N))["result"]
    assert down["new_low_days"] == 20


def test_i26_drawdown_from_ath():
    ramp = run("I26", _ramp(N))["result"]
    assert ramp["dd"] == pytest.approx(0.0)  # 最高价即最新价
    down = run("I26", _down(N))["result"]
    assert down["ath"] == pytest.approx(200.0)
    assert down["dd"] == pytest.approx(140.5 / 200.0 - 1.0)


def test_i27_donchian_flat_channel():
    out = run("I27", _flat(40))["result"]
    assert out["upper"] == pytest.approx(101.0)
    assert out["lower"] == pytest.approx(99.0)
    assert out["mid"] == pytest.approx(100.0)
    assert out["width_pct"] == pytest.approx(0.02)


def test_i28_momentum_uses_price_difference():
    close = [100.0 + 0.5 * i for i in range(40)]
    out = run("I28", {"close": close})["result"]
    assert out["mom"]["1"] == pytest.approx(0.5)
    assert out["mom"]["20"] == pytest.approx(10.0)
    assert out["mom_pct"]["1"] == pytest.approx(0.5 / close[-2], abs=1e-6)


def test_i29_roc_ratio():
    close = [100.0 + 0.5 * i for i in range(40)]
    out = run("I29", {"close": close})["result"]
    assert out["roc"]["1"] == pytest.approx(close[-1] / close[-2] - 1.0, abs=1e-6)
    assert out["roc"]["20"] == pytest.approx(close[-1] / close[-21] - 1.0, abs=1e-6)


# ============================================================
# I30–I33：分位 / 回归 / ADX / MFI
# ============================================================


def test_i30_vol_percentile_zero_vol_is_top_percentile():
    out = run("I30", _flat(80))["result"]
    assert out["current_vol"] == pytest.approx(0.0)
    assert out["percentile"] == pytest.approx(100.0)
    assert 0.0 <= out["percentile"] <= 100.0


def test_i31_regression_channel_recovers_line():
    close = [100.0 + 2.0 * i for i in range(60)]
    out = run("I31", {"close": close})["result"]
    assert out["slope"] == pytest.approx(2.0)
    assert out["r2"] == pytest.approx(1.0)
    assert out["mid"] == pytest.approx(close[-1])
    assert out["upper"] == pytest.approx(out["lower"])  # 完美直线残差为 0


def test_i32_adx_uptrend_saturated():
    out = run("I32", _ramp(N))["result"]
    assert out["plus_di"] > 0.0
    assert out["minus_di"] == pytest.approx(0.0)
    assert out["adx"] == pytest.approx(100.0)
    assert out["atr_smoothed"] > 0.0


def test_i33_mfi_uptrend_is_100():
    out = run("I33", _ramp(N))["result"]
    assert out["negative_flow"] == pytest.approx(0.0)
    assert out["mfi"] == pytest.approx(100.0)
    down = run("I33", _down(N))["result"]
    assert down["mfi"] == pytest.approx(0.0)


# ============================================================
# 契约：确定性 + 样本门禁
# ============================================================


def test_determinism_kdj_and_regression_channel():
    data = _ramp(N)
    assert run("I11", data) == run("I11", data)
    assert run("I31", data) == run("I31", data)


def test_determinism_vol_percentile_and_obv():
    data = _ramp(N)
    assert run("I30", data)["result"] == run("I30", data)["result"]
    assert run("I18", data)["result"] == run("I18", data)["result"]


def test_empty_input_gate_insufficient_samples():
    for method_id in ("I03", "I11", "I18", "I24", "I31", "I34"):
        out = run(method_id, {})
        assert out["gate"] == "insufficient_samples"
        assert out["result"] is None
        assert out["sample_n"] == 0
    assert run("I03", [])["gate"] == "insufficient_samples"
