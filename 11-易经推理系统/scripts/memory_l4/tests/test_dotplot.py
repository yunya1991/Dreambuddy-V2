"""P1.3 点阵图 12×8 支持度矩阵 — TDD 测试

Spec §2.4 Panel 2 + tasks.md L295-303：
  离线：对 8 态每种标签样本构建 ECDF 查找表 cdf_lut
  在线：查询指标值在 regime X 的分位数 q → 支持度 = 1 - 2*|q - 0.5|
        中位数=1.0，极端分位=0.0

覆盖：
  T1. test_ecdf_build_basic                — ECDF 构建：中位数附近 q≈0.5
  T2. test_query_cdf_interpolation         — 线性插值查询
  T3. test_support_from_quantile_formula   — 支持度公式 V 形
  T4. test_compute_dotplot_matrix_shape    — 12×8 矩阵形状 + marginal Σ=1
  T5. test_dotplot_support_range           — 支持度 ∈ [0, 1]
  T6. test_indicator_support_online_query  — 在线查询一致性
  T7. test_save_load_lut_roundtrip         — JSON 持久化往返
  T8. test_min_samples_fallback            — 样本不足 fallback 到全样本
  T9. test_unbuilt_lut_returns_neutral      — 未构建时返回 0.5 中性
  T10. test_known_regime_higher_support    — 已知 regime 样本中位数值时支持度最高
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

from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER, DOTPLOT_INDICATORS  # noqa: E402


# ====================================================================
# T1. ECDF 构建基础
# ====================================================================
def test_ecdf_build_basic():
    """ECDF 构建：已知样本序列，查询中位数应返回 ~0.5。"""
    values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    xs, ys = RegimeMapper._build_cdf_lut(values)
    assert len(xs) == 5
    assert len(ys) == 5
    # (i+1)/(n+1) = [1/6, 2/6, 3/6, 4/6, 5/6] ≈ [0.167, 0.333, 0.5, 0.667, 0.833]
    assert ys[0] == pytest.approx(1.0 / 6.0, abs=1e-6)
    assert ys[2] == pytest.approx(3.0 / 6.0, abs=1e-6)
    assert ys[-1] == pytest.approx(5.0 / 6.0, abs=1e-6)
    # 排序
    assert np.all(np.diff(xs) >= 0)


def test_ecdf_empty_returns_neutral():
    """空输入：ECDF 返回单点中性值 0.5。"""
    xs, ys = RegimeMapper._build_cdf_lut(np.array([]))
    assert len(xs) == 1
    assert len(ys) == 1
    assert ys[0] == pytest.approx(0.5, abs=1e-6)


# ====================================================================
# T2. CDF 查询：线性插值
# ====================================================================
def test_query_cdf_interpolation():
    """中间值：二分定位 + 线性插值。"""
    xs = np.array([10.0, 20.0, 30.0, 40.0, 50.0])
    ys = np.array([0.1, 0.3, 0.5, 0.7, 0.9])
    # value=25 → 在 xs[1]=20 和 xs[2]=30 之间
    q = RegimeMapper._query_cdf(25.0, xs, ys)
    expected = 0.3 + (0.5 - 0.3) * (25.0 - 20.0) / (30.0 - 20.0)
    assert q == pytest.approx(expected, abs=1e-6)


def test_query_cdf_below_min():
    """value 低于 xs[0]：保守下伸 = ys[0] × 0.5。"""
    xs = np.array([10.0, 20.0, 30.0])
    ys = np.array([0.2, 0.5, 0.8])
    q = RegimeMapper._query_cdf(5.0, xs, ys)
    assert q == pytest.approx(0.2 * 0.5, abs=1e-6)


def test_query_cdf_above_max():
    """value 高于 xs[-1]：保守上伸 = 1 - (1-ys[-1])×0.5。"""
    xs = np.array([10.0, 20.0, 30.0])
    ys = np.array([0.2, 0.5, 0.8])
    q = RegimeMapper._query_cdf(100.0, xs, ys)
    assert q == pytest.approx(1.0 - (1.0 - 0.8) * 0.5, abs=1e-6)


def test_query_cdf_exact_boundary():
    """value 正好等于 xs[k]：返回 ys[k]（等值命中分位数中位数）。"""
    xs = np.array([10.0, 20.0, 30.0])
    ys = np.array([0.2, 0.5, 0.8])
    # v=10.0 命中 xs[0]，等值区间 [0,1) → median(ys[0:1]) = 0.2
    assert RegimeMapper._query_cdf(10.0, xs, ys) == pytest.approx(0.2, abs=1e-6)
    # v=30.0 命中 xs[-1]，等值区间 [2,3) → median(ys[2:3]) = 0.8
    assert RegimeMapper._query_cdf(30.0, xs, ys) == pytest.approx(0.8, abs=1e-6)
    # v=20.0 命中 xs[1]，等值区间 [1,2) → median(ys[1:2]) = 0.5
    q20 = RegimeMapper._query_cdf(20.0, xs, ys)
    assert q20 == pytest.approx(0.5, abs=1e-6)


def test_query_cdf_tied_values_median():
    """多个等值样本：value 命中并列区间 → 返回该区间分位数中位数。

    例如 xs=[0,0,0,1,2]，ys=[1/6,2/6,3/6,4/6,5/6]，查询 v=0.0：
    等值区间 [0,3)，ys[0:3]=[1/6,2/6,3/6]，中位数=2/6≈0.333
    """
    xs = np.array([0.0, 0.0, 0.0, 1.0, 2.0])
    ys = np.array([1/6, 2/6, 3/6, 4/6, 5/6])
    q = RegimeMapper._query_cdf(0.0, xs, ys)
    assert q == pytest.approx(2.0 / 6.0, abs=1e-6)


# ====================================================================
# T3. 支持度公式：V 形
# ====================================================================
def test_support_from_quantile_formula():
    """支持度 = 1 - 2*|q-0.5|，clip [0,1]。"""
    # 中位数 → 1.0
    assert RegimeMapper._support_from_quantile(0.5) == pytest.approx(1.0, abs=1e-9)
    # 0.05 → 1 - 2*0.45 = 0.10
    assert RegimeMapper._support_from_quantile(0.05) == pytest.approx(0.10, abs=1e-9)
    # 0.95 → 0.10
    assert RegimeMapper._support_from_quantile(0.95) == pytest.approx(0.10, abs=1e-9)
    # 0.0 → 0.0
    assert RegimeMapper._support_from_quantile(0.0) == pytest.approx(0.0, abs=1e-9)
    # 1.0 → 0.0
    assert RegimeMapper._support_from_quantile(1.0) == pytest.approx(0.0, abs=1e-9)
    # 越界 clip
    assert RegimeMapper._support_from_quantile(-0.5) == pytest.approx(0.0, abs=1e-9)
    assert RegimeMapper._support_from_quantile(1.5) == pytest.approx(0.0, abs=1e-9)


# ====================================================================
# T4. compute_dotplot_support 返回 12×8 矩阵 + marginal Σ=1
# ====================================================================
def _make_synthetic_data(n: int = 200, seed: int = 42):
    """构造 n 根 BTC 1D 风格的 OHLCV + 12 指标 + 8 态标签。"""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    # 模拟价格：累积收益 + 周期
    rets = rng.normal(0, 0.02, n)
    rets[50:70] += 0.01  # 一段牛市
    rets[120:140] -= 0.015  # 一段熊市
    close = 50000 * np.exp(np.cumsum(rets))
    high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
    volume = rng.lognormal(10, 0.5, n)
    df = pd.DataFrame({"open": close, "high": high, "low": low, "close": close, "volume": volume}, index=idx)

    from bcrm2.indicators import IndicatorBank
    bank = IndicatorBank()
    indicators = bank.compute_all(df)

    # 简单 8 态标签：基于 90 日收益方向 + 波动率分桶
    lr90 = indicators["__raw_log_ret_90d"]
    vol_pct = indicators["vol_60d_pct"]
    labels = pd.Series("RANGE_BOUND", index=idx)
    bull_mask = lr90 > 0.10
    bear_mask = lr90 < -0.10
    high_vol = vol_pct > 0.7
    labels[bull_mask & ~high_vol] = "TREND_UP_MILD"
    labels[bull_mask & high_vol] = "TREND_UP_STRONG"
    labels[bear_mask & ~high_vol] = "CONSOLIDATION"
    labels[bear_mask & high_vol] = "VOLATILE_DROP"
    # 确保所有 8 态都有样本（避免 fallback 测试被全部触发）
    for i, r in enumerate(REGIME_ORDER):
        # 每 25 天分配一个不同的 regime，保证每个都有 ≥10 样本
        slot_start = (i * 25) % n
        slot_end = min(slot_start + 15, n)
        labels.iloc[slot_start:slot_end] = r
    return df, indicators, labels


def test_compute_dotplot_matrix_shape():
    """compute_dotplot_support 返回 12×8 矩阵，rows/cols 顺序正确。"""
    df, indicators, labels = _make_synthetic_data(n=200)
    mapper = RegimeMapper()
    result = mapper.compute_dotplot_support(indicators, labels, min_samples=5)

    assert result["rows"] == DOTPLOT_INDICATORS
    assert len(result["rows"]) == 12
    assert result["cols"] == list(REGIME_ORDER)
    assert len(result["cols"]) == 8
    # matrix 12×8
    mat = result["matrix"]
    assert len(mat) == 12
    for row in mat:
        assert len(row) == 8
    # marginal Σ=1
    mp = result["marginal_probs"]
    assert len(mp) == 8
    assert sum(mp) == pytest.approx(1.0, abs=1e-6)
    # marginal 全部 > 0
    assert all(p > 0 for p in mp)
    # target_index 默认最后一日
    assert result["target_index"] == 199
    # sample_counts 每个 regime > 0
    for r in REGIME_ORDER:
        assert result["sample_counts"][r] > 0


def test_compute_dotplot_target_index_custom():
    """指定 target_index 早期日：不报错，matrix 仍合法。"""
    df, indicators, labels = _make_synthetic_data(n=200)
    mapper = RegimeMapper()
    result = mapper.compute_dotplot_support(indicators, labels, min_samples=5, target_index=100)
    assert result["target_index"] == 100
    assert len(result["matrix"]) == 12


def test_compute_dotplot_target_index_out_of_range():
    """target_index 越界：抛 ValueError。"""
    df, indicators, labels = _make_synthetic_data(n=100)
    mapper = RegimeMapper()
    with pytest.raises(ValueError, match="超出范围"):
        mapper.compute_dotplot_support(indicators, labels, target_index=500)


# ====================================================================
# T5. 支持度范围 [0, 1]
# ====================================================================
def test_dotplot_support_range():
    """所有支持度值 ∈ [0, 1]。"""
    df, indicators, labels = _make_synthetic_data(n=200, seed=7)
    mapper = RegimeMapper()
    result = mapper.compute_dotplot_support(indicators, labels, min_samples=5)
    for row in result["matrix"]:
        for v in row:
            assert 0.0 <= v <= 1.0, f"支持度 {v} 超出 [0,1]"


# ====================================================================
# T6. indicator_support 在线查询一致性
# ====================================================================
def test_indicator_support_online_query_consistency():
    """compute_dotplot_support 计算的值与 indicator_support 在线查询一致。"""
    df, indicators, labels = _make_synthetic_data(n=150, seed=11)
    mapper = RegimeMapper()
    result = mapper.compute_dotplot_support(indicators, labels, min_samples=5)
    target_idx = result["target_index"]

    # 随机挑 3 个指标 × 3 个 regime 验证
    test_cases = [
        ("ma200_above_3d", "TREND_UP_STRONG"),
        ("log_ret_90d", "VOLATILE_DROP"),
        ("vol_60d_pct", "FOMO_RALLY"),
    ]
    for ind_name, regime in test_cases:
        v = float(indicators[ind_name].iloc[target_idx])
        online = mapper.indicator_support(v, ind_name, regime)
        # 矩阵中对应位置
        i = DOTPLOT_INDICATORS.index(ind_name)
        j = list(REGIME_ORDER).index(regime)
        offline = result["matrix"][i][j]
        assert online == pytest.approx(offline, abs=1e-9), \
            f"{ind_name}/{regime}: online={online} offline={offline}"


def test_indicator_support_row():
    """indicator_support_row 返回长度 12 的支持度列表。"""
    df, indicators, labels = _make_synthetic_data(n=100, seed=3)
    mapper = RegimeMapper()
    mapper.compute_dotplot_support(indicators, labels, min_samples=5)
    target_idx = 99
    row_dict = {name: float(indicators[name].iloc[target_idx]) for name in DOTPLOT_INDICATORS}
    support_row = mapper.indicator_support_row(row_dict, "RANGE_BOUND")
    assert len(support_row) == 12
    for v in support_row:
        assert 0.0 <= v <= 1.0


# ====================================================================
# T7. save/load LUT JSON 往返
# ====================================================================
def test_save_load_lut_roundtrip(tmp_path):
    """保存 cdf_lut 到 JSON，重新加载后查询结果一致。"""
    df, indicators, labels = _make_synthetic_data(n=150, seed=21)
    mapper1 = RegimeMapper()
    mapper1.compute_dotplot_support(indicators, labels, min_samples=5)

    lut_path = tmp_path / "dotplot_lut.json"
    mapper1.save_dotplot_lut(lut_path)
    assert lut_path.exists()

    mapper2 = RegimeMapper()
    assert mapper2.cdf_lut is None
    mapper2.load_dotplot_lut(lut_path)
    assert mapper2.cdf_lut is not None

    # 查询若干个 (indicator, regime) 对比
    test_pairs = [
        ("ma200_above_3d", "TREND_UP_STRONG", 1.0),
        ("dow_hhhl_score", "VOLATILE_DROP", -1.0),
        ("vol_60d_pct", "FOMO_RALLY", 0.8),
        ("log_ret_90d", "RANGE_BOUND", 0.0),
    ]
    for ind_name, regime, v in test_pairs:
        s1 = mapper1.indicator_support(v, ind_name, regime)
        s2 = mapper2.indicator_support(v, ind_name, regime)
        assert s1 == pytest.approx(s2, abs=1e-9), \
            f"{ind_name}/{regime}/v={v}: mapper1={s1} mapper2={s2}"


def test_save_lut_without_build_raises(tmp_path):
    """cdf_lut 未构建时调用 save_dotplot_lut 抛 RuntimeError。"""
    mapper = RegimeMapper()
    with pytest.raises(RuntimeError, match="cdf_lut 未构建"):
        mapper.save_dotplot_lut(tmp_path / "x.json")


# ====================================================================
# T8. 样本不足 fallback 到全样本
# ====================================================================
def test_min_samples_fallback():
    """某 regime 样本数 < min_samples：用全样本构建 ECDF，不报错。"""
    df, indicators, labels = _make_synthetic_data(n=100, seed=5)
    # 把 FOMO_RALLY 几乎全清空
    labels[labels == "FOMO_RALLY"] = "RANGE_BOUND"
    labels.iloc[5:7] = "FOMO_RALLY"  # 仅 2 个样本
    mapper = RegimeMapper()
    # min_samples=20，FOMO_RALLY 只有 2 样本 → fallback
    result = mapper.compute_dotplot_support(indicators, labels, min_samples=20)
    assert result["sample_counts"]["FOMO_RALLY"] == 2
    # FOMO_RALLY 列仍然有支持度值（来自全样本 ECDF）
    j = list(REGIME_ORDER).index("FOMO_RALLY")
    for i in range(12):
        v = result["matrix"][i][j]
        assert 0.0 <= v <= 1.0


# ====================================================================
# T9. 未构建 cdf_lut 时 indicator_support 返回中性 0.5
# ====================================================================
def test_unbuilt_lut_returns_neutral():
    """未调用 compute_dotplot_support：indicator_support 返回中性 0.5。"""
    mapper = RegimeMapper()
    assert mapper.cdf_lut is None
    s = mapper.indicator_support(123.0, "ma200_above_3d", "TREND_UP_STRONG")
    assert s == pytest.approx(0.5, abs=1e-9)


def test_indicator_support_unknown_regime_returns_neutral():
    """cdf_lut 已构建但查询未知 regime：返回中性 0.5。"""
    df, indicators, labels = _make_synthetic_data(n=50, seed=9)
    mapper = RegimeMapper()
    mapper.compute_dotplot_support(indicators, labels, min_samples=5)
    s = mapper.indicator_support(1.0, "ma200_above_3d", "UNKNOWN_REGIME")
    assert s == pytest.approx(0.5, abs=1e-9)


def test_indicator_support_unknown_indicator_returns_neutral():
    """cdf_lut 已构建但查询未知 indicator：返回中性 0.5。"""
    df, indicators, labels = _make_synthetic_data(n=50, seed=9)
    mapper = RegimeMapper()
    mapper.compute_dotplot_support(indicators, labels, min_samples=5)
    s = mapper.indicator_support(1.0, "unknown_indicator", "TREND_UP_STRONG")
    assert s == pytest.approx(0.5, abs=1e-9)


# ====================================================================
# T10. 已知 regime 样本中位数附近 → 支持度最高
# ====================================================================
def test_median_quantile_highest_support():
    """指标值等于 ECDF 中位分位数时（q=0.5）→ 支持度 = 1.0。

    手动构建一个对称 ECDF：xs=[1,2,3,4,5], ys=[1/6,2/6,3/6,4/6,5/6]
    查询 v=3.0 命中 xs[2]，等值区间 [2,3) → median(ys[2:3])=3/6=0.5 → 支持度=1.0
    """
    mapper = RegimeMapper()
    mapper.cdf_lut = {
        "TREND_UP_STRONG": {
            "test_indicator": (
                np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
                np.array([1/6, 2/6, 3/6, 4/6, 5/6]),
            ),
        }
    }
    # 中位数值 3.0 → 命中 xs[2] → q=0.5 → 支持度=1.0
    s_mid = mapper.indicator_support(3.0, "test_indicator", "TREND_UP_STRONG")
    assert s_mid == pytest.approx(1.0, abs=1e-6)
    # 极端最小值 1.0 → 命中 xs[0] → q=1/6≈0.167 → 支持度=1-2*0.333=0.333
    s_min = mapper.indicator_support(1.0, "test_indicator", "TREND_UP_STRONG")
    assert s_min == pytest.approx(1.0 - 2.0 * abs(1.0/6.0 - 0.5), abs=1e-6)
    # 极端最大值 5.0 → 命中 xs[-1] → q=5/6≈0.833 → 支持度=0.333
    s_max = mapper.indicator_support(5.0, "test_indicator", "TREND_UP_STRONG")
    assert s_max == pytest.approx(1.0 - 2.0 * abs(5.0/6.0 - 0.5), abs=1e-6)
    # 中位数支持度应高于极端值
    assert s_mid > s_min
    assert s_mid > s_max


def test_extreme_value_lower_support():
    """远超 regime 样本范围的极端值 → 支持度较低（≤ 0.5）。"""
    df, indicators, labels = _make_synthetic_data(n=200, seed=44)
    mapper = RegimeMapper()
    mapper.compute_dotplot_support(indicators, labels, min_samples=5)

    # ma_alignment_score 范围通常 [-1, 1]，给 999.0 极端值
    support = mapper.indicator_support(999.0, "ma_alignment_score", "TREND_UP_STRONG")
    # 极端值分位数接近 1.0，支持度 ≤ 0.5
    assert support <= 0.5, f"极端值支持度 {support} > 0.5"
