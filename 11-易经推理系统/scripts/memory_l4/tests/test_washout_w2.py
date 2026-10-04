"""W2: WashoutFeatureExtractor 8 维传统金融特征提取器 TDD 测试（RED 阶段）.

Spec: docs/superpowers/specs/2026-09-21-washout-detector-design.md §4.4 / §9.2

TDD 流程：本文件先于生产代码编写，每一项测试保证 RED（先失败）再 GREEN。

测试清单（共 14 项）：
  T1  / test_extract_volume_ratio_20d_normal
        — 正常 vol/vol_ma20 计算正确（vol=2000, ma20=1050 → ≈1.905）
  T2  / test_extract_volume_ratio_zero_vol_returns_neutral
        — vol=0 或 vol_ma20=0 → 1.0 中性
  T3  / test_extract_support_holds_count_3_holds
        — 4 个 swing low 抬高 + 当前价守住 → count=3
  T4  / test_extract_support_holds_count_break_returns_0
        — 当前价跌破最近 swing low → 0
  T5  / test_extract_atr_compress_ratio_narrowing
        — 前 15d 高振幅 + 后 5d 低振幅 → ratio < 1
  T6  / test_extract_atr_compress_ratio_widening
        — 前 15d 低振幅 + 后 5d 高振幅 → ratio > 1
  T7  / test_extract_oi_change_rate_7d
        — OI_t=110, OI_{t-7d}=100 → 0.1
  T8  / test_extract_cycle_position_365d_low
        — 365d 价格从 100→200，当前 110 → ≈0.10 < 0.3
  T9  / test_extract_cycle_position_365d_high
        — 365d 价格从 100→200，当前 190 → ≈0.90 > 0.7
  T10 / test_extract_rebound_ratio_5d_strong
        — 5d: low=95, high=105, current=102 → 0.7 > 0.5
  T11 / test_extract_news_negative_score_no_news
        — 无 news_list → 0.0
  T12 / test_extract_news_negative_score_negative_news
        — 3 负面/5 总数 → 0.6
  T13 / test_extract_btc_correlation_30d
        — 币价与 BTC 同步 → corr ≈ 1.0
  T14 / test_extract_all_features_dim_switch_off
        — 关闭 enable_volume_dim → extract_all 不含 volume_ratio_20d
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent  # 11-易经推理系统/
sys.path.insert(0, str(_PROJECT_ROOT))


# ============================================================
# 导入（RED 阶段：模块不存在时 ImportError）
# ============================================================
from scripts.memory_l4.bcrm2.washout_features import (  # noqa: E402
    WashoutFeatureExtractor,
)


# ============================================================
# Helpers: 构造 OHLCV DataFrame
# ============================================================
def _make_ohlcv(closes, highs=None, lows=None, vols=None) -> pd.DataFrame:
    """从 close 序列构造 OHLCV DataFrame，index 为日期。"""
    n = len(closes)
    closes_arr = np.asarray(closes, dtype=float)
    if highs is None:
        highs_arr = closes_arr * 1.005
    else:
        highs_arr = np.asarray(highs, dtype=float)
    if lows is None:
        lows_arr = closes_arr * 0.995
    else:
        lows_arr = np.asarray(lows, dtype=float)
    if vols is None:
        vols_arr = np.full(n, 1000.0)
    else:
        vols_arr = np.asarray(vols, dtype=float)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"close": closes_arr, "high": highs_arr, "low": lows_arr, "volume": vols_arr},
        index=idx,
    )


# ============================================================
# T1: 正常 vol/vol_ma20 计算
# ============================================================
def test_extract_volume_ratio_20d_normal():
    """vol=2000, vol_ma20=1050 → ratio ≈ 1.905。"""
    n = 20
    closes = [100.0] * n
    vols = [1000.0] * 19 + [2000.0]
    df = _make_ohlcv(closes, vols=vols)
    extractor = WashoutFeatureExtractor()
    ratio = extractor.extract_volume_ratio_20d(df)
    # vol_ma20 = (1000*19 + 2000) / 20 = 1050, vol_last=2000 → 2000/1050 ≈ 1.9048
    assert isinstance(ratio, float)
    assert abs(ratio - 2000.0 / 1050.0) < 1e-6


# ============================================================
# T2: vol=0 → 中性 1.0
# ============================================================
def test_extract_volume_ratio_zero_vol_returns_neutral():
    """vol 全为 0 → vol_ma20=0 → 返回中性值 1.0。"""
    n = 20
    closes = [100.0] * n
    vols = [0.0] * n
    df = _make_ohlcv(closes, vols=vols)
    extractor = WashoutFeatureExtractor()
    ratio = extractor.extract_volume_ratio_20d(df)
    assert ratio == 1.0


# ============================================================
# T3: 4 个 swing low 抬高 → 3 次守住
# ============================================================
def test_extract_support_holds_count_3_holds():
    """构造 30d 价格，4 个 swing low 抬高（95→96→97→98），当前价 99 > 98 → count=3。"""
    n = 30
    closes = [99.0] * n
    closes[-1] = 99.5  # 当前价高于最近 swing low
    lows = [99.5] * n
    # swing low 位置：2, 7, 12, 17（每 5d 一个，留 13d 尾段避免边界）
    swing_low_vals = [95.0, 96.0, 97.0, 98.0]
    for i, v in enumerate(swing_low_vals):
        pos = 2 + i * 5
        if pos < n:
            lows[pos] = v
    df = _make_ohlcv(closes, lows=lows)
    extractor = WashoutFeatureExtractor()
    count = extractor.extract_support_holds_count(df)
    assert count == 3.0


# ============================================================
# T4: 破支撑 → 0
# ============================================================
def test_extract_support_holds_count_break_returns_0():
    """当前价跌破最近 swing low → count=0。"""
    n = 30
    closes = [99.0] * n
    closes[-1] = 97.0  # 跌破最近 swing low 98
    lows = [99.5] * n
    swing_low_vals = [95.0, 96.0, 97.0, 98.0]
    for i, v in enumerate(swing_low_vals):
        pos = 2 + i * 5
        if pos < n:
            lows[pos] = v
    df = _make_ohlcv(closes, lows=lows)
    extractor = WashoutFeatureExtractor()
    count = extractor.extract_support_holds_count(df)
    assert count == 0.0


# ============================================================
# T5: ATR 收窄 → ratio < 1
# ============================================================
def test_extract_atr_compress_ratio_narrowing():
    """前 15d 高振幅(±5%) + 后 5d 低振幅(±0.5%) → ATR_5d < ATR_20d → ratio < 1。"""
    n = 20
    closes = [100.0] * n
    highs = [100.0] * n
    lows = [100.0] * n
    # 前 15d 高振幅
    for i in range(15):
        highs[i] = 105.0
        lows[i] = 95.0
    # 后 5d 低振幅
    for i in range(15, 20):
        highs[i] = 100.5
        lows[i] = 99.5
    df = _make_ohlcv(closes, highs=highs, lows=lows)
    extractor = WashoutFeatureExtractor()
    ratio = extractor.extract_atr_compress_ratio(df)
    assert isinstance(ratio, float)
    assert ratio < 1.0


# ============================================================
# T6: ATR 扩大 → ratio > 1
# ============================================================
def test_extract_atr_compress_ratio_widening():
    """前 15d 低振幅(±0.5%) + 后 5d 高振幅(±5%) → ATR_5d > ATR_20d → ratio > 1。"""
    n = 20
    closes = [100.0] * n
    highs = [100.0] * n
    lows = [100.0] * n
    # 前 15d 低振幅
    for i in range(15):
        highs[i] = 100.5
        lows[i] = 99.5
    # 后 5d 高振幅
    for i in range(15, 20):
        highs[i] = 105.0
        lows[i] = 95.0
    df = _make_ohlcv(closes, highs=highs, lows=lows)
    extractor = WashoutFeatureExtractor()
    ratio = extractor.extract_atr_compress_ratio(df)
    assert isinstance(ratio, float)
    assert ratio > 1.0


# ============================================================
# T7: OI 7d 变化率
# ============================================================
def test_extract_oi_change_rate_7d():
    """OI_t=110, OI_{t-7d}=100 → (110-100)/100 = 0.1。"""
    # 用 30d OHLCV 保证 df 有足够长度
    closes = [100.0] * 30
    df = _make_ohlcv(closes)
    macro_data = {
        "oi_series": [100.0] * 7 + [110.0],  # 长度 8，第 8 个 = OI_t
    }
    extractor = WashoutFeatureExtractor()
    rate = extractor.extract_oi_change_rate_7d(df, macro_data)
    assert isinstance(rate, float)
    assert abs(rate - 0.1) < 1e-9


# ============================================================
# T8: cycle_position 365d 低位 → < 0.3
# ============================================================
def test_extract_cycle_position_365d_low():
    """价格从 100 → 200，当前 110 → (110-100)/(200-100) = 0.10 < 0.3。"""
    n = 50  # 至少 30d 满足 min_periods
    closes = np.linspace(100.0, 200.0, n)
    closes[-1] = 110.0  # 当前价回到低位
    df = _make_ohlcv(list(closes))
    extractor = WashoutFeatureExtractor()
    pos = extractor.extract_cycle_position_365d(df)
    assert isinstance(pos, float)
    assert pos < 0.3


# ============================================================
# T9: cycle_position 365d 高位 → > 0.7
# ============================================================
def test_extract_cycle_position_365d_high():
    """价格从 100 → 200，当前 190 → (190-100)/(200-100) = 0.90 > 0.7。"""
    n = 50
    closes = np.linspace(100.0, 200.0, n)
    closes[-1] = 190.0  # 当前价在高位
    df = _make_ohlcv(list(closes))
    extractor = WashoutFeatureExtractor()
    pos = extractor.extract_cycle_position_365d(df)
    assert isinstance(pos, float)
    assert pos > 0.7


# ============================================================
# T10: rebound_ratio 5d 反弹强 → > 0.5
# ============================================================
def test_extract_rebound_ratio_5d_strong():
    """5d: low=95, high=105, current=102 → (102-95)/(105-95) = 0.7 > 0.5。"""
    n = 5
    closes = [100.0, 100.0, 100.0, 100.0, 102.0]
    highs = [105.0] * 5
    lows = [95.0] * 5
    df = _make_ohlcv(closes, highs=highs, lows=lows)
    extractor = WashoutFeatureExtractor()
    r = extractor.extract_rebound_ratio_5d(df)
    assert isinstance(r, float)
    assert r > 0.5
    assert abs(r - 0.7) < 1e-6


# ============================================================
# T11: 无新闻 → 0.0
# ============================================================
def test_extract_news_negative_score_no_news():
    """macro_data 无 news_list 或空 → 0.0。"""
    closes = [100.0] * 30
    df = _make_ohlcv(closes)
    extractor = WashoutFeatureExtractor()
    # 无 news_list key
    score = extractor.extract_news_negative_score(df, {})
    assert score == 0.0
    # news_list 为空
    score2 = extractor.extract_news_negative_score(df, {"news_list": []})
    assert score2 == 0.0


# ============================================================
# T12: 负面新闻占比
# ============================================================
def test_extract_news_negative_score_negative_news():
    """5 条新闻中 3 条负面 → 0.6。"""
    closes = [100.0] * 30
    df = _make_ohlcv(closes)
    news_list = [
        {"sentiment": "negative"},
        {"sentiment": "negative"},
        {"sentiment": "negative"},
        {"sentiment": "positive"},
        {"sentiment": "neutral"},
    ]
    macro_data = {"news_list": news_list}
    extractor = WashoutFeatureExtractor()
    score = extractor.extract_news_negative_score(df, macro_data)
    assert isinstance(score, float)
    assert abs(score - 0.6) < 1e-9


# ============================================================
# T13: btc_correlation 30d 同步 → ≈ 1.0
# ============================================================
def test_extract_btc_correlation_30d():
    """币价与 BTC 完全同步（相同涨跌）→ corr ≈ 1.0。"""
    rng = np.random.default_rng(42)
    n = 35
    base = 100.0 * np.cumprod(1.0 + rng.normal(0, 0.01, n))
    closes = list(base)
    df = _make_ohlcv(closes)
    macro_data = {"btc_close": list(base)}  # 完全同步
    extractor = WashoutFeatureExtractor()
    corr = extractor.extract_btc_correlation_30d(df, macro_data)
    assert isinstance(corr, float)
    assert corr > 0.9  # 完全同步应接近 1


# ============================================================
# T14: 子开关关闭 → 该维度不提取
# ============================================================
def test_extract_all_features_dim_switch_off():
    """关闭 enable_volume_dim → extract_all 不含 volume_ratio_20d。"""
    n = 20
    closes = [100.0] * n
    vols = [1000.0] * 19 + [2000.0]
    df = _make_ohlcv(closes, vols=vols)
    macro_data = {"oi_series": [100.0] * 7 + [110.0]}
    # 关闭 enable_volume_dim
    extractor = WashoutFeatureExtractor(
        config={"enable_volume_dim": False}
    )
    feats = extractor.extract_all(df, macro_data)
    assert "volume_ratio_20d" not in feats
    # 其他维度仍存在
    assert "support_holds_count" in feats
    assert "atr_compress_ratio" in feats
    assert "oi_change_rate_7d" in feats
    assert "cycle_position_365d" in feats
    assert "rebound_ratio_5d" in feats
    assert "news_negative_score" in feats
    assert "btc_correlation_30d" in feats
