"""Phase 1 TDD 测试 · Smoke 验收 T15

可选但推荐，覆盖：
  T15 a) test_btc_three_dates_parameter_direction
       真实 BTC 数据跑 Phase 0 + ParameterMapper：
         • ATH 69k (2025-03-14 前后) → ls_ratio_cap 中心 ≥ 0.7（牛市允许多空不平衡偏多头）
         • FTX Low (2022-11-21 前后) → ls_ratio_cap 中心 ≤ 0.5（熊市收紧，禁止乱开）
         • 减半 (2024-04-20 前后) → global_position_mult 中心 ≥ 1.15（减半后加仓）
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


_BTC_CSV = _BCRM2_ROOT / "data" / "klines" / "BTC_1D_full.csv"

pytestmark = pytest.mark.skipif(not _BTC_CSV.exists(), reason="真实 BTC CSV 不存在，跳过 T15")


# ================================================================
# 辅助：用 Phase 0 流水线跑 BTC → 取关键日期 (L,T,C,stats_row) 合成 global_ranges
# ================================================================
def _run_evolution_and_get_dates(dates_of_interest: list[str]) -> dict[str, dict]:
    from bcrm2.indicators import IndicatorBank
    from bcrm2.score_composer import ScoreComposer
    from bcrm2.temporal_smoother import TemporalSmoother
    from bcrm2.regime_mapper import RegimeMapper
    from bcrm2.rolling_regime_stats import RollingRegimeStats
    from bcrm2.parameter_mapper import ParameterMapper

    df = pd.read_csv(_BTC_CSV, parse_dates=["timestamp"], index_col="timestamp")
    # 统一去时区：避免 tz-aware vs naive Timestamp 比较 TypeError
    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is not None:
        df.index = df.index.tz_convert("UTC").tz_localize(None)
    df.sort_index(inplace=True)

    inds = IndicatorBank().compute_all(df)
    L_raw, T_raw = ScoreComposer().compose(inds, df)
    smooth = TemporalSmoother().transform(L_raw, T_raw)
    rm = RegimeMapper()
    # 逐帧求 consensus（用 RegimeMapper 逐帧 map_frame）
    consensus = pd.Series(np.nan, index=df.index, dtype=float)
    for i, idx in enumerate(df.index):
        frame = rm.map_frame(float(smooth.level_smooth.iloc[i]),
                             float(smooth.trend_smooth.iloc[i]))
        consensus.iloc[i] = float(frame["consensus"])

    # rolling_regime_stats
    stats = RollingRegimeStats().compute(df)

    pm = ParameterMapper()
    out = {}
    for d in dates_of_interest:
        ts = pd.Timestamp(d)
        # 找 ≤ d 的最后一个有效索引
        mask = stats.index <= ts
        if not mask.any():
            continue
        last_idx = stats.index[mask][-1]
        # stats_row 只要 252d 的 p10/p90
        sr = stats.loc[last_idx].to_dict()
        # stats 可能是 NaN（前 252 根滚不动），用合成默认值兜底
        if not np.isfinite(sr.get("L_p90_252d", np.nan)):
            sr = dict(L_p10_252d=-3.0, L_p90_252d=+3.0, T_p10_252d=-2.8, T_p90_252d=+2.8)
        Lv = float(smooth.level_smooth.loc[last_idx])
        Tv = float(smooth.trend_smooth.loc[last_idx])
        Cv = float(consensus.loc[last_idx])
        ranges = pm.map_global_parameters(L=Lv, T=Tv, C=Cv, stats_row=sr)
        out[d] = dict(L=Lv, T=Tv, C=Cv, ranges=ranges)
    return out


def _cent(rng):
    return 0.5 * (rng[0] + rng[1])


# ================================================================
# T15a) 关键日期参数方向正确
# ================================================================
def test_btc_three_dates_parameter_direction():
    dates = ["2024-12-16",   # 牛市 ATH $106k（L=+3.11/T=+1.48 最牛）
             "2022-11-21",   # FTX Lows 熊市底（L=-2.37）
             "2024-04-20"]   # BTC 减半（L=+2.52 牛市启动）
    res = _run_evolution_and_get_dates(dates)
    assert len(res) >= 3, f"关键日期命中不足：{list(res)}"
    # (1) 牛市 ATH → ls_ratio_cap 中心 ≥ 0.7（牛市允许多空不平衡偏多头）
    ath_cent = _cent(res["2024-12-16"]["ranges"]["ls_ratio_cap"])
    assert ath_cent >= 0.7, f"牛市 ATH ls_ratio_cap 中心 = {ath_cent:.3f} < 0.7（牛市允许多头）"
    # (2) FTX → ls_ratio_cap 中心 ≤ 0.5（熊市收紧，禁止乱开）
    ftx_cent = _cent(res["2022-11-21"]["ranges"]["ls_ratio_cap"])
    assert ftx_cent <= 0.5, f"FTX Low ls_ratio_cap 中心 = {ftx_cent:.3f} > 0.5（熊市收紧）"
    # (3) 减半 → global_position_mult 中心 ≥ 1.15（减半后加仓）
    half_cent = _cent(res["2024-04-20"]["ranges"]["global_position_mult"])
    assert half_cent >= 1.15, f"2024 减半 global_position_mult 中心 = {half_cent:.3f} < 1.15（减半后加仓）"
