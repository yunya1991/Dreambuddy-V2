"""P1.2 BOCPD 变点 5 日渐进调整 — TDD 测试

Spec §2.4 规则4：
  - BOCPD 检测到变点概率 P > 0.70
  - 且量能 ≥ 1.5× 均量（双重门槛）
  - 记录变点日的价格方向 sign（后续 5 日收益方向）
  - Trend 在接下来 5 个交易日每天渐进调整 sign × 0.06，合计 ±0.30

覆盖：
  T1. test_bocpd_detects_regime_change       — 平稳+突变序列，突变点附近 cp_prob > 0.5
  T2. test_bocpd_trend_adjustment_progressive — 已知变点：5 日渐进 ±0.06，5 日后停止，合计 ±0.30
  T3. test_bocpd_disabled_when_no_close       — 不传 close/volume 时 bocpd_cp_prob 全 0（兼容旧调用）
  T4. test_bocpd_volume_threshold             — P>0.7 但量能 < 1.5× 均量时不触发调整
  T5. test_bocpd_compose_no_regression        — bocpd_enabled=False 时输出与 Phase 0 完全一致
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

from bcrm2.temporal_smoother import TemporalSmoother, SmootherOutput  # noqa: E402


# ====================================================================
# 辅助：构造简单的 level/trend 序列（供 transform 使用）
# ====================================================================
def _make_level_trend(n: int = 60, seed: int = 7):
    """生成 n 根带波动的 level/trend（[-4,+4] 范围内）。"""
    rng = np.random.default_rng(seed)
    level = np.cumsum(rng.normal(0, 0.2, n)) + 0.5
    trend = np.cumsum(rng.normal(0, 0.15, n))
    level = np.clip(level, -3.5, 3.5)
    trend = np.clip(trend, -3.5, 3.5)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.Series(level, index=idx), pd.Series(trend, index=idx)


# ====================================================================
# T1. BOCPD 检测到 regime 切换
# ====================================================================
def test_bocpd_detects_regime_change():
    """
    构造 200 根平稳 + 50 根突变（大幅下跌）的 log-return 序列。
    断言在突变点附近 bocpd_prob > 0.5。
    """
    rng = np.random.default_rng(42)
    n_stable, n_shift = 200, 50
    # 平稳期：极小波动，均值 ~0
    ret_stable = rng.normal(0.0, 0.002, n_stable)
    # 突变期：大幅下跌，均值 -0.04（相对平稳期是 20σ 级别异常）
    ret_shift = rng.normal(-0.04, 0.005, n_shift)
    rets = np.concatenate([ret_stable, ret_shift])

    # 由收益反推 close（保证 close 全正）
    close = 100.0 * np.exp(np.cumsum(rets))
    idx = pd.date_range("2020-01-01", periods=len(close), freq="D")
    close_s = pd.Series(close, index=idx)
    volume_s = pd.Series(np.ones(len(close)), index=idx)

    smoother = TemporalSmoother(bocpd_enabled=True)
    probs = smoother._compute_bocpd_probs(close_s, volume_s)

    # 第一个突变 return 位于 rets[200] → 对应 close 索引 201
    # 突变点附近（close 201~210）应出现高变点概率
    window = probs[201:211]
    assert window.max() > 0.5, (
        f"突变点附近最大变点概率 {window.max():.4f}，期望 > 0.5"
    )

    # 平稳期中位数应较低（z-score 噪声偶有 2σ 毛刺，但中位数远 < 0.5）
    stable_median = float(np.median(probs[:195]))
    assert stable_median < 0.5, (
        f"平稳期变点概率中位数 {stable_median:.4f}，期望 < 0.5"
    )


# ====================================================================
# T2. 渐进调整：5 日每天 ±0.06，5 日后停止，合计 ±0.30
# ====================================================================
def test_bocpd_trend_adjustment_progressive():
    """
    构造已知变点（i=10，P=0.9），close 单调上涨 → sign=+1。
    断言：
      - 变点前（含变点日）trend 无调整
      - 变点后 5 天每天 += 0.06（0.06,0.12,0.18,0.24,0.30）
      - 5 天后调整停止（值保持 0.30）
      - 总调整量 = +0.30
    """
    n = 50
    trend0 = np.zeros(n)
    # close 单调上涨 → 未来 5 日收益为正 → sign=+1
    close = np.arange(1, n + 1, dtype=float)
    volume = np.ones(n)
    volume[10] = 5.0  # 变点日量能 5× 均量（≥ 1.5×）
    bocpd_probs = np.zeros(n)
    bocpd_probs[10] = 0.9  # > 0.7 触发

    smoother = TemporalSmoother(bocpd_enabled=True)
    out = smoother._apply_bocpd_trend_adjustment(trend0, close, volume, bocpd_probs)

    # 变点前（含变点日 i=10）无调整
    assert np.allclose(out[:11], 0.0), f"变点前 trend 被调整: {out[:11]}"
    # 变点后 5 天（i+1..i+5 = 11..15）每天 += 0.06
    assert np.allclose(out[11:16], [0.06, 0.12, 0.18, 0.24, 0.30]), (
        f"渐进调整不符: {out[11:16]}"
    )
    # 5 天后调整停止（值保持）
    assert np.allclose(out[16:], 0.30), f"5 天后未停止: {out[16:]}"
    # 总调整量 = +0.30
    assert abs(out[15] - out[10] - 0.30) < 1e-9, "总调整量 != 0.30"

    # —— 对称校验：close 单调下跌 → sign=-1，每天 -= 0.06
    close_down = np.arange(n, 0, -1, dtype=float)  # n, n-1, ..., 1
    out_down = smoother._apply_bocpd_trend_adjustment(
        np.zeros(n), close_down, volume, bocpd_probs)
    assert np.allclose(out_down[11:16], [-0.06, -0.12, -0.18, -0.24, -0.30]), (
        f"负向渐进调整不符: {out_down[11:16]}"
    )
    assert abs(out_down[15] - out_down[10] + 0.30) < 1e-9, "负向总调整量 != -0.30"


# ====================================================================
# T3. 不传 close/volume 时 bocpd_cp_prob 全 0（兼容旧调用）
# ====================================================================
def test_bocpd_disabled_when_no_close():
    """bocpd_enabled=True 但不传 close/volume → bocpd_cp_prob 全 0，且不报错。"""
    level, trend = _make_level_trend(60)
    smoother = TemporalSmoother(bocpd_enabled=True)
    out = smoother.transform(level, trend)

    assert isinstance(out, SmootherOutput)
    bocpd = np.asarray(out.bocpd_cp_prob, dtype=float)
    assert bocpd.shape[0] == 60
    assert np.all(bocpd == 0.0), f"未传 close/volume 时 bocpd 应全 0，实际 max={bocpd.max()}"


# ====================================================================
# T4. 量能门槛：P>0.7 但量能 < 1.5× 均量时不触发调整
# ====================================================================
def test_bocpd_volume_threshold():
    """
    bocpd_probs[10]=0.9（>0.7）但 volume 恒定 → 量比=1.0 < 1.5 → 不触发调整。
    """
    n = 50
    trend0 = np.zeros(n)
    close = np.arange(1, n + 1, dtype=float)  # 若触发 sign=+1
    volume = np.ones(n)  # 恒定 → 量比 = 1.0 < 1.5
    bocpd_probs = np.zeros(n)
    bocpd_probs[10] = 0.9

    smoother = TemporalSmoother(bocpd_enabled=True)
    out = smoother._apply_bocpd_trend_adjustment(trend0, close, volume, bocpd_probs)

    # 量能不足 → 完全无调整
    assert np.allclose(out, 0.0), f"量能不足时不应调整，实际 max|Δ|={np.abs(out).max()}"


# ====================================================================
# T5. bocpd_enabled=False 时输出与 Phase 0 完全一致
# ====================================================================
def test_bocpd_compose_no_regression():
    """
    bocpd_enabled=False 时即使传入 close/volume，输出也应与 Phase 0（不传 close/volume）
    完全一致：bocpd_cp_prob 全 0，trend/level/hmm/ema 完全相同。
    """
    level, trend = _make_level_trend(80)
    n = len(level)
    idx = level.index
    close = pd.Series(np.linspace(100, 120, n), index=idx)
    volume = pd.Series(np.ones(n) * 1e6, index=idx)

    # A: bocpd_enabled=False 且传入 close/volume（应被忽略）
    smoother_off = TemporalSmoother(bocpd_enabled=False, random_state=42)
    out_a = smoother_off.transform(level, trend, close, volume)

    # B: Phase 0 行为（默认不传 close/volume）
    smoother_p0 = TemporalSmoother(random_state=42)
    out_b = smoother_p0.transform(level, trend)

    # bocpd 全 0
    assert np.all(np.asarray(out_a.bocpd_cp_prob) == 0.0)

    # 所有字段完全一致
    np.testing.assert_array_equal(
        np.asarray(out_a.level_smooth), np.asarray(out_b.level_smooth))
    np.testing.assert_array_equal(
        np.asarray(out_a.trend_smooth), np.asarray(out_b.trend_smooth))
    np.testing.assert_array_equal(
        np.asarray(out_a.hmm_state), np.asarray(out_b.hmm_state))
    np.testing.assert_array_equal(
        np.asarray(out_a.ema_level), np.asarray(out_b.ema_level))
    np.testing.assert_array_equal(
        np.asarray(out_a.bocpd_cp_prob), np.asarray(out_b.bocpd_cp_prob))
