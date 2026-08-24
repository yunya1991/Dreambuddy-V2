"""Phase 1 · v4 模块：RollingRegimeStats（方案 A 范围映射用的滚动统计锚点）

输出列（16 列）：
  Level/Trend 分位数与波动性（2 窗口 × 2 维度 × 5 分位 = 实际 20 取 12 列 + 额外 std 2 列）：
    L_p10_60d, L_p50_60d, L_p90_60d, L_std_60d
    T_p10_60d, T_p50_60d, T_p90_60d, T_std_60d
    L_p10_252d, L_p50_252d, L_p90_252d
    T_p10_252d, T_p50_252d, T_p90_252d
  Consensus / 熵滚动均值：
    consensus_ma_20d, regime_entropy_20d
  成交量 zscore：
    volume_zscore_252d
"""
from __future__ import annotations

from typing import Optional, Tuple

import numpy as np
import pandas as pd


def _rolling_quantile(s: pd.Series, window: int, q: float) -> pd.Series:
    return s.rolling(window=window, min_periods=max(5, window // 10)).quantile(q)


def _entropy(p: np.ndarray) -> float:
    eps = 1e-12
    p = np.clip(p, eps, 1 - eps)
    return float(-(p * np.log(p)).sum())


class RollingRegimeStats:
    def __init__(self):
        self._phase0_instances = None

    # ============================================================
    # 核心：要么用传进来的预计算 (level, trend, consensus, probs)，
    #      要么内部跑一遍 Phase 0 流水线生成。
    # ============================================================
    def _ensure_level_trend_consensus(
        self,
        df: pd.DataFrame,
        precomputed: Optional[dict],
    ) -> Tuple[pd.Series, pd.Series, pd.Series, np.ndarray]:
        if precomputed is not None:
            return (
                precomputed["level"],
                precomputed["trend"],
                precomputed["consensus"],
                precomputed.get("probs"),
            )
        # 内部跑 Phase 0（延迟 import 防止循环）
        from bcrm2.indicators import IndicatorBank
        from bcrm2.score_composer import ScoreComposer
        from bcrm2.temporal_smoother import TemporalSmoother
        from bcrm2.regime_mapper import RegimeMapper

        inds = IndicatorBank().compute_all(df)
        L_raw, T_raw = ScoreComposer().compose(inds, df)
        smooth = TemporalSmoother().transform(L_raw, T_raw)
        L = smooth.level_smooth
        T = smooth.trend_smooth
        rm = RegimeMapper()
        Cs = np.full(len(df), np.nan, dtype=float)
        probs = np.full((len(df), 8), np.nan, dtype=float)
        for i in range(len(df)):
            frame = rm.map_frame(float(L.iloc[i]), float(T.iloc[i]))
            Cs[i] = float(frame["consensus"])
            probs[i] = [frame["regime_probs"].get(k, 0.0) for k in
                        ["RANGE_BOUND", "CONSOLIDATION", "ACCUMULATION", "RECOVERY_MILD",
                         "TREND_UP_MILD", "TREND_UP_STRONG", "FOMO_RALLY", "VOLATILE_DROP"]]
        C = pd.Series(Cs, index=df.index)
        return L, T, C, probs

    def compute(
        self,
        df: pd.DataFrame,
        precomputed_ltc: Optional[dict] = None,
    ) -> pd.DataFrame:
        L, T, C, probs = self._ensure_level_trend_consensus(df, precomputed_ltc)
        out = pd.DataFrame(index=df.index)

        # 60d 分位/std
        for prefix, s in (("L_", L), ("T_", T)):
            out[f"{prefix}p10_60d"] = _rolling_quantile(s, 60, 0.10)
            out[f"{prefix}p50_60d"] = _rolling_quantile(s, 60, 0.50)
            out[f"{prefix}p90_60d"] = _rolling_quantile(s, 60, 0.90)
            out[f"{prefix}std_60d"] = s.rolling(60, min_periods=10).std()
        # 252d 分位（方案 A 范围锚点主要用这一组）
        for prefix, s in (("L_", L), ("T_", T)):
            out[f"{prefix}p10_252d"] = _rolling_quantile(s, 252, 0.10)
            out[f"{prefix}p50_252d"] = _rolling_quantile(s, 252, 0.50)
            out[f"{prefix}p90_252d"] = _rolling_quantile(s, 252, 0.90)

        # Consensus / 熵 20d 均值
        out["consensus_ma_20d"] = C.rolling(20, min_periods=5).mean()
        if probs is not None:
            ent = np.array([_entropy(probs[i]) for i in range(len(probs))])
            ent_s = pd.Series(ent, index=df.index)
            out["regime_entropy_20d"] = ent_s.rolling(20, min_periods=5).mean()
        else:
            out["regime_entropy_20d"] = np.nan

        # 成交量 252d zscore
        if "volume" in df.columns:
            v = df["volume"].astype(float)
            mu = v.rolling(252, min_periods=20).mean()
            sd = v.rolling(252, min_periods=20).std().replace(0, np.nan)
            out["volume_zscore_252d"] = (v - mu) / sd
        else:
            out["volume_zscore_252d"] = np.nan

        return out


# ============================================================
# FeatureRegistry 注册
# ============================================================
from bcrm2.feature_registry import FeatureRegistry  # noqa: E402

FeatureRegistry.register(name="rolling_regime_stats", factory=RollingRegimeStats)

