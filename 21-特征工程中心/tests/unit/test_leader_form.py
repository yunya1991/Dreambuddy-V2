"""P1-C 龙头形态特征（SPEC-EMERGENCE-FINANCIAL-ENV §6.2）单元测试。

覆盖：列契约 / 均线栈四态 / 均线预热 null / Pivot 用前一根 bar（无前视）/
OBV 顶背离 / 布林挤压与 %B 除零 / FeatureHub 注册。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "21-特征工程中心"))

from feature_hub.modules import leader_form  # noqa: E402

EXPECTED_COLUMNS = {
    "ma_5",
    "ma_13",
    "ma_65",
    "ma_128",
    "ma_200",
    "ma_dist_5",
    "ma_dist_13",
    "ma_dist_65",
    "ma_dist_128",
    "ma_dist_200",
    "ma_stack_perfect_bull",
    "ma_stack_perfect_bear",
    "ma_stack_compressed",
    "ma_stack_mixed",
    "above_ma200",
    "pivot_p",
    "pivot_r1",
    "pivot_s1",
    "pivot_r2",
    "pivot_s2",
    "dist_to_pivot",
    "dist_to_r1",
    "dist_to_s1",
    "vol_ratio_5_20",
    "obv_slope_20",
    "obv_divergence",
    "rsi14",
    "macd_dif",
    "macd_dea",
    "macd_hist",
    "boll_pctb",
    "boll_bandwidth",
    "boll_squeeze",
}


def _ohlcv(close, volume=None, spread=0.5) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    n = len(close)
    volume = np.full(n, 1000.0) if volume is None else np.asarray(volume, dtype=float)
    return pd.DataFrame(
        {
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": volume,
        },
        index=pd.date_range("2023-01-01", periods=n, freq="D"),
    )


def test_columns_match_spec():
    out = leader_form.compute(_ohlcv(np.linspace(100, 200, 300)))
    assert set(out.columns) == EXPECTED_COLUMNS
    assert len(out) == 300
    assert out.index.equals(_ohlcv(np.linspace(100, 200, 300)).index)


def test_ma_stack_perfect_bull():
    out = leader_form.compute(_ohlcv(np.linspace(100, 300, 300)))
    assert out["ma_stack_perfect_bull"].iloc[-1] == 1.0
    assert out["above_ma200"].iloc[-1] == 1.0


def test_ma_stack_perfect_bear():
    out = leader_form.compute(_ohlcv(np.linspace(300, 100, 300)))
    assert out["ma_stack_perfect_bear"].iloc[-1] == 1.0
    assert out["above_ma200"].iloc[-1] == 0.0


def test_ma_stack_compressed_on_flat_market():
    out = leader_form.compute(_ohlcv(np.full(260, 100.0), spread=0.0))
    assert out["ma_stack_compressed"].iloc[-1] == 1.0
    assert out["boll_bandwidth"].iloc[-1] == pytest.approx(0.0)


def test_ma_stack_one_hot_is_exclusive():
    out = leader_form.compute(_ohlcv(np.linspace(100, 300, 300)))
    block = out[[f"ma_stack_{s}" for s in leader_form.MA_STACK_STATES]].dropna()
    assert (block.sum(axis=1) == 1.0).all()


def test_ma_stack_state_is_none_during_warmup():
    out = leader_form.compute(_ohlcv(np.linspace(100, 300, 260)))
    block = out[[f"ma_stack_{s}" for s in leader_form.MA_STACK_STATES]]
    assert block.iloc[:199].isna().all().all()  # ma_200 未成形
    assert block.iloc[199:].notna().all().all()


def test_pivot_uses_previous_bar_only():
    df = _ohlcv(np.linspace(100, 120, 30), spread=1.0)
    out = leader_form.compute(df)
    i = 10
    prev_h, prev_l, prev_c = df["high"].iloc[i - 1], df["low"].iloc[i - 1], df["close"].iloc[i - 1]
    expected_p = (prev_h + prev_l + prev_c) / 3
    assert out["pivot_p"].iloc[i] == pytest.approx(expected_p)
    assert out["pivot_r1"].iloc[i] == pytest.approx(2 * expected_p - prev_l)
    assert out["pivot_s1"].iloc[i] == pytest.approx(2 * expected_p - prev_h)
    assert out["pivot_r2"].iloc[i] == pytest.approx(expected_p + (prev_h - prev_l))
    assert out["pivot_s2"].iloc[i] == pytest.approx(expected_p - (prev_h - prev_l))
    assert out["dist_to_pivot"].iloc[i] == pytest.approx(
        (df["close"].iloc[i] - expected_p) / expected_p
    )


def test_pivot_first_bar_is_null():
    out = leader_form.compute(_ohlcv(np.linspace(100, 110, 10)))
    assert np.isnan(out["pivot_p"].iloc[0])


def test_obv_bearish_divergence_on_new_high_without_obv_confirmation():
    # 前 80 天稳步上涨 → 巨量下跌（OBV 大幅回落）→ 缩量收复并创新高
    close = list(np.linspace(100, 160, 80)) + [140.0] + list(np.linspace(141, 165, 20))
    volume = [1000.0] * 80 + [1e6] + [1.0] * 20
    out = leader_form.compute(_ohlcv(close, volume))
    assert out["obv_divergence"].iloc[-1] == -1.0


def test_obv_slope_positive_on_rising_market():
    out = leader_form.compute(_ohlcv(np.linspace(100, 200, 120)))
    assert out["obv_slope_20"].iloc[-1] > 0


def test_boll_pctb_is_null_on_zero_width_band():
    out = leader_form.compute(_ohlcv(np.full(120, 100.0), spread=0.0))
    assert np.isnan(out["boll_pctb"].iloc[-1])  # span=0 不产生 inf/伪 0.5
    assert out["boll_squeeze"].iloc[-1] == 1.0  # 带宽 0 处 20 日低位


def test_vol_ratio_is_one_on_constant_volume():
    out = leader_form.compute(_ohlcv(np.linspace(100, 150, 60)))
    assert out["vol_ratio_5_20"].iloc[-1] == pytest.approx(1.0)


def test_rsi14_is_100_on_monotonic_rise_and_zero_on_fall():
    up = leader_form.compute(_ohlcv(np.linspace(100, 200, 120)))
    down = leader_form.compute(_ohlcv(np.linspace(200, 100, 120)))
    assert up["rsi14"].iloc[-1] == pytest.approx(100.0)
    assert down["rsi14"].iloc[-1] == pytest.approx(0.0)


def test_rsi14_is_50_on_flat_market_and_nan_during_warmup():
    out = leader_form.compute(_ohlcv(np.full(60, 100.0), spread=0.0))
    assert out["rsi14"].iloc[-1] == pytest.approx(50.0)
    assert out["rsi14"].iloc[: leader_form.RSI_PERIOD].isna().all()
    assert out["rsi14"].iloc[leader_form.RSI_PERIOD :].notna().all()


def test_macd_sign_follows_trend_and_warmup():
    up = leader_form.compute(_ohlcv(np.linspace(100, 200, 120)))
    down = leader_form.compute(_ohlcv(np.linspace(200, 100, 120)))
    assert up["macd_dif"].iloc[-1] > 0 and up["macd_hist"].iloc[-1] > 0
    assert down["macd_dif"].iloc[-1] < 0 and down["macd_hist"].iloc[-1] < 0
    warm = leader_form.MACD_SLOW + leader_form.MACD_SIGNAL - 2
    assert up["macd_hist"].iloc[:warm].isna().all()  # DIF 26 根 + DEA 再 9 根预热
    assert up["macd_hist"].iloc[warm:].notna().all()


def test_registered_in_feature_hub_loader():
    from feature_hub.modules.loader import _MODULE_IMPORTS, _default_sets

    assert _MODULE_IMPORTS["leader_form"] == "feature_hub.modules.leader_form"
    assert _default_sets()["leader_form_only"] == ["leader_form"]
    assert callable(leader_form.compute)
