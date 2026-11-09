"""三层防线统计原语测试 — SPEC-D1 §2.5 + docs/PATTERN-STATS-PREREG-v0.1（冻结口径）。

覆盖：Holm 批内校正 / CSCV 批级 PBO / SPA 胜出者检验 / DSR 佐证 / 单样本 p 值。
参考实现：23-四层闭环 framework_comparison.holm_bonferroni、
45-评测系统 backtest.pbo_cscv / deflated_sharpe_ratio。
"""

import pytest
from data_center.processing.pattern_stats import (
    cscv_pbo,
    deflated_sharpe,
    holm_adjust,
    one_sample_pvalue,
    spa_pvalues,
)


def _alt(base: float, n: int, eps: float = 0.01) -> list[float]:
    """均值=base、sd≈eps 的交替序列（Sharpe 排序 = 均值排序）。"""
    return [base + eps * (1 if i % 2 == 0 else -1) for i in range(n)]


# ── Holm ──────────────────────────────────────────────────


def test_holm_reference_vector():
    """参考向量（与 23 域 holm_bonferroni 同口径，含单调性约束）。"""
    out = holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03})
    assert out == {"a": pytest.approx(0.03), "b": pytest.approx(0.06), "c": pytest.approx(0.06)}


def test_holm_single_and_monotonic():
    assert holm_adjust({"x": 0.04}) == {"x": pytest.approx(0.04)}
    # 单调性：较大的原始 p 校正后不得小于前面已校正值
    out = holm_adjust({"a": 0.001, "b": 0.5})
    assert out["a"] == pytest.approx(0.002)
    assert out["b"] == pytest.approx(0.5)


def test_holm_empty_and_cap():
    assert holm_adjust({}) == {}
    out = holm_adjust({"a": 0.9, "b": 0.95})
    assert all(0.0 <= v <= 1.0 for v in out.values())


# ── CSCV / PBO ────────────────────────────────────────────


def test_cscv_consistent_leader_zero_pbo():
    """三个 cell 均值恒定排序 A>B>C → IS 最优恒为 A 且 OOS 也最优 → PBO=0。"""
    series = [_alt(1.0, 8), _alt(0.3, 8), _alt(-0.5, 8)]
    assert cscv_pbo(series, S=4) == 0.0


def test_cscv_mirror_flip_full_pbo():
    """A/B 前后半镜像 + C 恒 0 → 任一 IS 切分最优者 OOS 必掉队 → PBO=1。"""
    a = _alt(1.0, 4) + _alt(-1.0, 4)
    b = _alt(-1.0, 4) + _alt(1.0, 4)
    c = _alt(0.0, 8)
    assert cscv_pbo([a, b, c], S=4) == 1.0


def test_cscv_infeasible_returns_none():
    assert cscv_pbo([], S=4) is None
    assert cscv_pbo([_alt(1.0, 8)], S=4) is None
    assert cscv_pbo([_alt(1.0, 8), _alt(0.5, 8)], S=4) is None  # <3 series 退化
    assert cscv_pbo([_alt(1.0, 4), _alt(0.5, 4), _alt(0.2, 4)], S=8) is None  # 块<2
    # 长度不齐 → FAIL-OPEN None
    assert cscv_pbo([_alt(1.0, 8), _alt(0.5, 8), [0.1] * 6], S=4) is None


def test_cscv_auto_s():
    """S=None 自动推导：len=8 → S=4（⌊8/2⌋ 取偶）；len<8 → None。"""
    series = [_alt(1.0, 8), _alt(0.3, 8), _alt(-0.5, 8)]
    assert cscv_pbo(series) == 0.0
    short = [_alt(1.0, 6), _alt(0.3, 6), _alt(-0.5, 6)]
    assert cscv_pbo(short) is None  # ⌊6/2⌋=3 <4 → 不可算


# ── SPA ───────────────────────────────────────────────────


def test_spa_strong_vs_null():
    """强信号 cell 应显著，与基准无差异 cell 不显著（seed 固定确定性）。"""
    strong = [0.05 + 0.002 * (1 if i % 2 == 0 else -1) for i in range(20)]
    null = [0.001 + 0.01 * (1 if i % 2 == 0 else -1) for i in range(20)]
    out = spa_pvalues({"strong": strong, "null": null}, mu0=0.001, n_boot=2000, seed=42)
    assert out["strong"] < 0.05
    assert out["null"] > 0.5


def test_spa_deterministic_and_empty():
    cells = {"x": [0.02, 0.03, 0.025, 0.028, 0.022, 0.031, 0.027, 0.024]}
    a = spa_pvalues(cells, mu0=0.0, n_boot=500, seed=7)
    b = spa_pvalues(cells, mu0=0.0, n_boot=500, seed=7)
    assert a == b
    assert spa_pvalues({}, mu0=0.0, n_boot=100, seed=1) == {}
    # 单点 cell 不崩溃（t 退化为符号/0）
    out = spa_pvalues({"one": [0.05]}, mu0=0.0, n_boot=100, seed=1)
    assert 0.0 <= out["one"] <= 1.0


# ── DSR ───────────────────────────────────────────────────


def test_dsr_single_trial_equals_psr():
    """n_trials=1 → 退化为对 0 的 PSR：sharpe=1, n=101 → z=10 → ≈1。"""
    assert deflated_sharpe(1.0, 101, 1) > 0.999
    assert deflated_sharpe(0.0, 101, 1) == pytest.approx(0.5)


def test_dsr_monotonic_in_trials():
    """试验次数越多，期望最大 Sharpe 基准越高 → DSR 单调下降。"""
    assert deflated_sharpe(1.0, 101, 10) > deflated_sharpe(1.0, 101, 1000)


def test_dsr_invalid_raises():
    with pytest.raises(ValueError):
        deflated_sharpe(1.0, 1, 10)  # n_obs<2
    # n_trials≤1 按参考实现（45 backtest.py）退化为 PSR vs 0，不抛
    assert deflated_sharpe(1.0, 101, 0) > 0.999


# ── 单样本 p 值 ────────────────────────────────────────────


def test_one_sample_pvalue_signal_vs_noise():
    signal = [0.03, 0.05] * 5
    noise = [0.01, -0.01] * 5
    assert one_sample_pvalue(signal, 0.0) < 0.001
    assert one_sample_pvalue(noise, 0.0) == pytest.approx(1.0)


def test_one_sample_pvalue_degenerate():
    assert one_sample_pvalue([0.05], 0.0) == 1.0  # n<2
    assert one_sample_pvalue([], 0.0) == 1.0
    assert one_sample_pvalue([0.04] * 10, 0.0) == 0.0  # sd=0 且均值≠μ0 → 极限显著
    assert one_sample_pvalue([0.0] * 10, 0.0) == 1.0  # sd=0 且均值=μ0
    assert one_sample_pvalue("garbage", 0.0) == 1.0  # FAIL-OPEN
