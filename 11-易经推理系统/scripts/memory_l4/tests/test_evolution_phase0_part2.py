"""Phase 0 Day 2 TDD 测试 — TemporalSmoother + RegimeMapper

覆盖：
  T5. test_temporal_smoother_shape_3state        — Output 5 field + HMM 状态 ∈ {0,1,2}
  T6. test_regime_probs_sum_to_1_stable           — 单帧软分配严格 = 1，序列 len-致
  T7. test_calibrate_centers_on_labels            — 冷启动校准：用真实标签统计 (L,T) 均值
  T8. test_end_to_end_sample200                   — 200 根合成 OHLCV 全链：Bank→Composer→Smoother→Mapper
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_THIS_DIR = Path(__file__).resolve().parent
_BCRM2_ROOT = _THIS_DIR.parent
assert _BCRM2_ROOT.name == "memory_l4"
if str(_BCRM2_ROOT) not in sys.path:
    sys.path.insert(0, str(_BCRM2_ROOT))

# 故意导入 — 如果模块不存在会 ImportError（RED）
from bcrm2.temporal_smoother import TemporalSmoother, SmootherOutput  # noqa: E402
from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER, REGIME_CENTERS  # noqa: E402

# D1 已测通过的模块可直接复用
from bcrm2.indicators import IndicatorBank  # noqa: E402
from bcrm2.score_composer import ScoreComposer  # noqa: E402


# Fixture：300+200 合成 OHLCV（复用 Day 1）
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


def _compose_scores(df):
    """小 helper：Indicators + ScoreComposer 一步到位。"""
    inds = IndicatorBank().compute_all(df)
    L, T = ScoreComposer().compose(inds, df)
    return inds, L, T


# ================================================================
# T5. TemporalSmoother 输出形状 + 3 态
# ================================================================
def test_temporal_smoother_shape_3state(synth_ohlcv_500):
    """TemporalSmoother.transform 返回 SmootherOutput：5 条 Series；
    level_smooth/trend_smooth 无 NaN；hmm_state 值仅为 0/1/2；
    bocpd_cp_prob 在未接入前应全 0。
    """
    _, level, trend = _compose_scores(synth_ohlcv_500)
    smoother = TemporalSmoother(n_hmm_states=3, ema_alpha=0.25, random_state=42)
    out = smoother.transform(level, trend)

    assert isinstance(out, SmootherOutput), "output 应是 SmootherOutput dataclass"
    n = len(synth_ohlcv_500)
    for field in ("level_smooth", "trend_smooth", "hmm_state", "ema_level", "bocpd_cp_prob"):
        s = getattr(out, field)
        assert len(s) == n, f"{field} 长度={len(s)} ≠ {n}"
        assert s.isna().sum() == 0, f"{field} 含 {s.isna().sum()} 个 NaN"

    # hmm_state 必须是 0/1/2
    states = out.hmm_state.unique()
    for st in states:
        assert st in (0, 1, 2), f"出现非法 HMM state: {st}，仅允许 0=Bear/1=Neutral/2=Bull"

    # bocpd 在 Phase 0 应全为 0（未接入 BOCPD）
    assert (out.bocpd_cp_prob.values == 0.0).all(), "Phase 0 bocpd_cp_prob 应全 0"

    # 连续性：smooth vs raw 不应大幅偏离（p95 ≤ 0.6）
    dL_smooth = np.abs(np.diff(out.level_smooth.values))
    dT_smooth = np.abs(np.diff(out.trend_smooth.values))
    assert np.percentile(dL_smooth + dT_smooth, 95) <= 0.9, \
        "HMM/EMA 平滑后不应引入突变：p95 |ΔL+ΔT| 应 ≤ 0.9"


# ================================================================
# T6. RegimeMapper 概率归一 & 稳定输出
# ================================================================
def test_regime_probs_sum_to_1_stable():
    """逐帧 map_frame：1) 8 概率 Σ = 1；2) Top-3 长度为 3；
    3) Consensus 范围 [0,1]；4) 完全相同输入两次 → 输出一致（确定性）。"""
    mapper = RegimeMapper()  # 使用冷启动默认中心

    # 人工构造一些有代表性的 L, T 点
    probes = [
        ("FOMO_RALLY zone",       +3.5, +2.5),
        ("TREND_UP_STRONG zone",  +2.0, +3.5),
        ("RANGE_BOUND zone",       0.0,  0.0),
        ("VOLATILE_DROP zone",    +1.5, -3.0),
    ]

    for tag, L, T in probes:
        result = mapper.map_frame(L, T, feature_row=None)
        probs = result["regime_probs"]
        # 8 态
        assert len(probs) == 8, f"{tag}：regime_probs 长度应=8，实际 {len(probs)}"
        # 所有标签都应在 REGIME_ORDER 中
        for k in probs:
            assert k in REGIME_ORDER, f"{tag}：非法标签 {k}"
        # Σ = 1
        s = float(sum(probs.values()))
        assert abs(s - 1.0) < 1e-9, f"{tag}：概率总和={s} ≠ 1"
        # 全部非负
        assert all(v >= -1e-12 for v in probs.values()), f"{tag}：含负概率"

        top3 = result["top3"]  # List[(regime_str, prob)]，按 prob desc 排列
        assert len(top3) == 3, f"{tag}：Top-3 长度={len(top3)}，期望 3"
        assert top3[0][1] >= top3[1][1] >= top3[2][1], f"{tag}：Top-3 未按概率降序"

        consensus = result["consensus"]
        assert 0.0 <= consensus <= 1.0, f"{tag}：consensus={consensus} 不在 [0,1]"

        # 确定性：相同输入第二次调用结果一致
        result2 = mapper.map_frame(L, T, feature_row=None)
        assert abs(result["consensus"] - result2["consensus"]) < 1e-12, \
            f"{tag}：两次调用 consensus 不一致"

    # 全序列 transform：批量接口 regime_probs 每行 Σ = 1
    n = 120
    rng = np.random.default_rng(7)
    L_seq = pd.Series(np.clip(np.cumsum(rng.normal(0, 0.15, n)), -4, 4))
    T_seq = pd.Series(np.clip(np.cumsum(rng.normal(0, 0.18, n)), -4, 4))
    seq = mapper.transform_sequence(L_seq, T_seq)
    assert len(seq) == n, f"transform_sequence 长度 {len(seq)} ≠ {n}"
    for i, frame in enumerate(seq):
        s = float(sum(frame["regime_probs"].values()))
        assert abs(s - 1.0) < 1e-9, f"frame {i} 概率总和 ≠ 1"


# ================================================================
# T7. 冷启动中心标定：基于 generate_8state_label + ScoreComposer
# ================================================================
def test_calibrate_centers_on_labels(synth_ohlcv_500):
    """
    在 500 根合成数据上跑：
      1) generate_8state_label 拿到标签
      2) ScoreComposer 拿到 (L, T)
      3) RegimeMapper.calibrate_centers(label, L, T) → 得到 centers
      4) 每个出现样本≥30 根的标签，它的 mean(L/T) 应「在该类中心附近」
         （abs(L_center - L_mean_by_label) ≤ 0.8，Trend 同理）
    冷启动校准后再构建 Mapper，probes 的 FOMO 点 Top-1 应命中 FOMO_RALLY 标签。
    """
    from bcrm2.labels.regime_labeler import generate_8state_label

    _, L, T = _compose_scores(synth_ohlcv_500)
    labels = generate_8state_label(synth_ohlcv_500, forward_days=10, lookback=80,
                                   use_rolling_quantile=True, target_balance=True)

    # 标签可能在前 lookback + 最后 forward_days 有 NaN；仅用有效样本
    valid = labels.notna()
    assert valid.sum() >= 50, f"有效标签仅 {valid.sum()} 条，不足测试"

    new_centers = RegimeMapper.calibrate_centers(labels[valid], L[valid], T[valid])

    # 每个标签中心必须是 (L, T) 两个 float
    for regime in REGIME_ORDER:
        assert regime in new_centers, f"new_centers 缺失 {regime}"
        ll, tt = new_centers[regime]
        assert isinstance(float(ll), float) and isinstance(float(tt), float)

    # 有足够样本（≥30）的类：类内均值 与 中心 的差距 ≤ 0.8
    covered = []
    for regime in REGIME_ORDER:
        mask = labels[valid] == regime
        if mask.sum() >= 30:
            covered.append(regime)
            Lm = L[valid][mask].mean()
            Tm = T[valid][mask].mean()
            Lc, Tc = new_centers[regime]
            assert abs(Lc - Lm) <= 0.8, f"{regime} L_center {Lc:.2f} 远离类均值 {Lm:.2f}"
            assert abs(Tc - Tm) <= 0.8, f"{regime} T_center {Tc:.2f} 远离类均值 {Tm:.2f}"

    # 覆盖至少 2 类（合成 500 根通常含 TREND_UP_MILD + CONSOLIDATION）
    assert len(covered) >= 2, f"仅覆盖 {len(covered)} 类，样本不足"

    # 用新中心构建 Mapper：已覆盖类的「类均值典型点」Top-1 应命中该类本身
    mapper = RegimeMapper(centers=new_centers)
    for regime in covered:
        Lm = L[valid][labels[valid] == regime].mean()
        Tm = T[valid][labels[valid] == regime].mean()
        res = mapper.map_frame(float(Lm), float(Tm), feature_row=None)
        assert res["top3"][0][0] == regime, \
            f"类内均值点 ({Lm:.2f},{Tm:.2f}) Top-1 = {res['top3'][0][0]}，应为 {regime}"


# ================================================================
# T8. 200 根 E2E：Bank → Composer → Smoother → Mapper 无异常
# ================================================================
def test_end_to_end_sample200(synth_ohlcv_500):
    """取前 200 根，全链路，结果：trajectory 长度=200，每帧含 L_smooth/T_smooth、
    8 概率 Σ=1、Top-3、consensus、hmm_state、BOCPD 相位（全 0）。"""
    df = synth_ohlcv_500.iloc[:200].copy()

    indicators, L, T = _compose_scores(df)
    so = TemporalSmoother(n_hmm_states=3, random_state=42).transform(L, T)

    mapper = RegimeMapper()
    frames = mapper.transform_sequence(so.level_smooth, so.trend_smooth,
                                        indicators=indicators)

    assert len(frames) == 200, f"trajectory 长度={len(frames)}，期望 200"

    # 逐帧结构 + 基本质量
    avg_consensus = 0.0
    top1_counts = {r: 0 for r in REGIME_ORDER}
    for i, f in enumerate(frames):
        # 必填键
        for k in ("level_smooth", "trend_smooth", "regime_probs", "top3",
                  "consensus", "hmm_state", "bocpd_cp_prob"):
            assert k in f, f"frame {i} 缺失 {k}"
        # 概率总和
        assert abs(sum(f["regime_probs"].values()) - 1.0) < 1e-9
        # L/T 在 [-4, +4]
        assert -4.0001 <= f["level_smooth"] <= 4.0001
        assert -4.0001 <= f["trend_smooth"] <= 4.0001
        # consensus 在 [0, 1]
        assert 0.0 <= f["consensus"] <= 1.0
        avg_consensus += f["consensus"]
        top1_counts[f["top3"][0][0]] += 1

    avg_consensus /= len(frames)
    # 平均共识度不应为 0（所有帧都像均匀分布就异常）
    assert avg_consensus >= 0.20, f"平均 consensus = {avg_consensus:.3f}，过低"
    # 至少覆盖 2 类 Top-1（否则分布坍缩）
    covered = sum(1 for v in top1_counts.values() if v > 0)
    assert covered >= 2, f"仅 {covered} 类 Top-1，应至少 2 类"
