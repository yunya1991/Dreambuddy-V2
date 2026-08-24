"""Phase 0 Day 1 TDD 测试 — Evolution Engine 雏形：IndicatorBank + ScoreComposer

RED → GREEN → REFACTOR 循环首战。
覆盖：
  T1. test_indicator_bank_shape          — 12 主指标 shape + 无 NaN
  T2. test_indicator_bank_ma200_3day_confirm — 三日确认逻辑
  T3. test_score_composer_produces_9grid_range — L/T 范围在 [-4, +4]
  T4. test_score_composer_clamp_continuity  — 99% 样本 |ΔL|+|ΔT| ≤ 1.0（钳制）

数据基准：前 500 根 BTC 1D（保证 MA200 可计算，避免全量 CSV 使测试太慢）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# —— 路径处理：tests/ 与 bcrm2/ 同级在 memory_l4 下
_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4", "tests 需放在 memory_l4/tests 下"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

# 故意先导入（这一步本身就应触发 RED —— 如果模块不存在）
from bcrm2.indicators import IndicatorBank  # noqa: E402
from bcrm2.score_composer import ScoreComposer  # noqa: E402


# ====================================================================
# Fixture：500 根假 BTC K 线（纯合成数据，不依赖磁盘 CSV）
# 构造：线性 100 → 180 的升序 300 根 + 180 → 140 的降序 200 根，
#       保证 MA200、MA50、cycle 都有足够窗口计算。
# ====================================================================
@pytest.fixture
def synth_ohlcv_500() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    n_up, n_down = 300, 200
    t_up = np.linspace(100, 180, n_up)
    t_down = np.linspace(180, 140, n_down)
    close = np.concatenate([t_up, t_down])
    close *= (1 + rng.normal(0, 0.01, n_up + n_down))
    idx = pd.date_range("2020-01-01", periods=n_up + n_down, freq="D")
    df = pd.DataFrame({
        "open":  close * (1 + rng.normal(0, 0.004, n_up + n_down)),
        "high":  close * (1 + np.abs(rng.normal(0, 0.01, n_up + n_down))),
        "low":   close * (1 - np.abs(rng.normal(0, 0.01, n_up + n_down))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.5, 1.0, n_up + n_down)),
    }, index=idx)
    return df


# ====================================================================
# T1. IndicatorBank Shape
# ====================================================================
_MAIN_12 = [
    "ma200_above_3d", "ma50_above", "ma20_vs_ma50_order",
    "cycle_position_365d", "ma_alignment_score", "ma200_slope_signed",
    "dow_hhhl_score", "log_ret_90d", "log_ret_30d",
    "ma_slope_wavg", "volume_trend_conf", "vol_60d_pct",
]


def test_indicator_bank_shape(synth_ohlcv_500):
    """12 个主指标全返回 Series，长度=len(df)，无 NaN。同时返回 __raw_* 辅助列。"""
    bank = IndicatorBank()
    out = bank.compute_all(synth_ohlcv_500)

    # 12 主列存在
    for k in _MAIN_12:
        assert k in out, f"缺失主指标 {k}"

    # 长度对齐
    n = len(synth_ohlcv_500)
    for k in _MAIN_12:
        assert len(out[k]) == n, f"{k} 长度={len(out[k])}，期望={n}"

    # 无 NaN
    for k in _MAIN_12:
        assert out[k].isna().sum() == 0, f"{k} 含 {out[k].isna().sum()} 个 NaN"

    # 至少包含 3 个 __raw_ 辅助列（供后续点阵图诊断）
    raw_count = sum(1 for k in out if k.startswith("__raw_"))
    assert raw_count >= 3, f"仅 {raw_count} 个 __raw_ 辅助列，期望 ≥ 3"


# ====================================================================
# T2. MA200 三日确认逻辑（人造构造）
# ====================================================================
def test_indicator_bank_ma200_3day_confirm():
    """
    构造 210 根 flat 的 close=100 → 第 201 日跳空涨至 120（>MA200）。
    期望：
      第 201、202 日 ma200_above_3d = 0（不满足连续3日）
      第 203 日起 ma200_above_3d = +1（连续3日站上）
    """
    n = 210
    close_arr = np.full(n, 100.0)
    close_arr[200:] = 120.0  # 201 日（0-based index 200）跳至 120
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    df = pd.DataFrame({
        "open": close_arr, "high": close_arr * 1.01,
        "low": close_arr * 0.99, "close": close_arr,
        "volume": np.ones(n) * 1e6,
    }, index=idx)

    bank = IndicatorBank()
    out = bank.compute_all(df)
    s = out["ma200_above_3d"]

    # MA200 计算依赖 200 窗口，前 200 根 min_periods=100 已足够出 ma200 值
    # index 200 = 首日跳涨：未满足连续3日 → 应为 0
    assert s.iloc[200] == 0.0, f"d200 跳涨首日 ma200_above_3d={s.iloc[200]}，期望 0"
    # index 201 = 第二日仍在 MA200 上 → 仍未满足 3 日连续
    assert s.iloc[201] == 0.0, f"d201 跳涨第二日 ma200_above_3d={s.iloc[201]}，期望 0"
    # index 202 = 第三日，满足连续3日 → +1
    assert s.iloc[202] == 1.0, f"d202 跳涨第三日 ma200_above_3d={s.iloc[202]}，期望 +1"
    # index 203~209 持续 +1
    assert (s.iloc[203:].values == 1.0).all(), "d203+ 应持续 +1"


# ====================================================================
# T3. ScoreComposer 范围 [-4, +4]
# ====================================================================
def test_score_composer_produces_9grid_range(synth_ohlcv_500):
    """线性合成 → L/T 钳制到 [-4, +4]，不会溢出。"""
    bank = IndicatorBank()
    indicators = bank.compute_all(synth_ohlcv_500)

    composer = ScoreComposer()
    level, trend = composer.compose(indicators, synth_ohlcv_500)

    n = len(synth_ohlcv_500)
    assert len(level) == n, f"Level 序列长度 {len(level)} != {n}"
    assert len(trend) == n, f"Trend 序列长度 {len(trend)} != {n}"

    level_arr = np.asarray(level, dtype=float)
    trend_arr = np.asarray(trend, dtype=float)
    assert np.isnan(level_arr).sum() == 0, "Level 含 NaN"
    assert np.isnan(trend_arr).sum() == 0, "Trend 含 NaN"

    # 钳制到 [-4, +4]
    assert level_arr.min() >= -4.0001, f"Level min={level_arr.min()} < -4"
    assert level_arr.max() <=  4.0001, f"Level max={level_arr.max()} > +4"
    assert trend_arr.min() >= -4.0001, f"Trend min={trend_arr.min()} < -4"
    assert trend_arr.max() <=  4.0001, f"Trend max={trend_arr.max()} > +4"

    # 合成波动不应为 0（否则无信息量）
    assert level_arr.std() > 0.05, f"Level std={level_arr.std():.4f}，几乎没有波动"
    assert trend_arr.std() > 0.05, f"Trend std={trend_arr.std():.4f}，几乎没有波动"


# ====================================================================
# T4. ScoreComposer 钳制连续性
# ====================================================================
def test_score_composer_clamp_continuity(synth_ohlcv_500):
    """
    人造构造极端跳变：先构造「持续中性」，然后第 400 日一次性注入极强信号。
    期望：99% 样本 |ΔL|+|ΔT| ≤ 1.0，且单日跳变不超过 MAX_DAILY_DELTA(0.5)×2=1.0（钳制上限）。
    """
    # 构造 500 根：前 450 根震荡（确保 level/trend 相对平稳），最后 50 根直接跳至极端
    rng = np.random.default_rng(7)
    n_total = 500
    close_stable = 100 + np.cumsum(rng.normal(0, 0.3, n_total - 50))  # 微震荡
    close_spike = np.linspace(close_stable[-1], close_stable[-1] * 1.8, 50)
    close = np.concatenate([close_stable, close_spike])
    idx = pd.date_range("2020-01-01", periods=n_total, freq="D")

    df = pd.DataFrame({
        "open": close * 0.999,
        "high": close * (1 + np.abs(rng.normal(0, 0.005, n_total))),
        "low":  close * (1 - np.abs(rng.normal(0, 0.005, n_total))),
        "close": close,
        "volume": 1e6 * (1 + rng.uniform(-0.3, 0.5, n_total)),
    }, index=idx)

    bank = IndicatorBank()
    indicators = bank.compute_all(df)
    composer = ScoreComposer(max_daily_delta=0.5, extreme_delta=1.0)
    level, trend = composer.compose(indicators, df)

    dL = np.abs(np.diff(np.asarray(level, dtype=float)))
    dT = np.abs(np.diff(np.asarray(trend, dtype=float)))
    d_sum = dL + dT

    # 99 分位数不超过 1.0
    p99 = np.percentile(d_sum, 99)
    assert p99 <= 1.0001, f"99% 分位 |ΔL+ΔT| = {p99:.4f}，期望 ≤ 1.0"

    # 任何单日 d_sum 都不应超过 1.0（规则 1 中 max_daily_delta 0.5 → L+T 最大 1.0；
    #   极端 8% 日涨跌可 extreme_delta=1.0 → 2.0，但本合成数据最后 50 根每日涨幅 < 8%）
    max_jump = d_sum.max()
    assert max_jump <= 2.0001, f"最大单日跳变 {max_jump:.4f} > 2.0（extreme_delta*2）"
