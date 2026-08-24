"""P3.3 坐标连续性 + 拐点滞后统计

用法:
  python eval_continuity.py --csv ../../data/klines/BTC_1D_full.csv

指标:
  - 连续性 = mean(|ΔL| + |ΔT|) per day
  - 4 个人工拐点的 Sperandeo 123 第 3 条满足滞后天数
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_MEMORY_L4 = _THIS.parent.parent.parent
if str(_MEMORY_L4) not in sys.path:
    sys.path.insert(0, str(_MEMORY_L4))

from bcrm2.indicators import IndicatorBank
from bcrm2.score_composer import ScoreComposer
from bcrm2.temporal_smoother import TemporalSmoother
from bcrm2.regime_mapper import RegimeMapper, REGIME_ORDER


def _read_csv(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    ts_cols = [c for c in df.columns if c.lower() in {"timestamp", "datetime", "date"}]
    if ts_cols:
        df[ts_cols[0]] = pd.to_datetime(df[ts_cols[0]])
        df = df.set_index(ts_cols[0])
    else:
        df.index = pd.to_datetime(df.index)
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = df[c].astype(float)
    return df.sort_index()


def evaluate_continuity(df: pd.DataFrame) -> dict:
    bank = IndicatorBank()
    indicators = bank.compute_all(df)
    composer = ScoreComposer()
    level_raw, trend_raw = composer.compose(indicators, df)
    smoother = TemporalSmoother(n_hmm_states=3, random_state=42)
    so = smoother.transform(level_raw, trend_raw)

    L = so.level_smooth.values
    T = so.trend_smooth.values
    n = len(L)
    dL = np.abs(np.diff(L))
    dT = np.abs(np.diff(T))
    daily_jump = dL + dT
    mean_jump = float(np.mean(daily_jump))
    p50_jump = float(np.median(daily_jump))
    p90_jump = float(np.percentile(daily_jump, 90))
    pct_le_05 = float(np.mean(daily_jump <= 0.5))

    # Sperandeo 123 拐点滞后
    adj = ScoreComposer.apply_sperandeo_adjustment(
        level_smooth=so.level_smooth.values,
        trend_smooth=so.trend_smooth.values,
        high=df["high"].values, low=df["low"].values, close=df["close"].values,
        swing_window=5,
    )

    key_dates = [
        ("ATH_69k", "2021-11-10", "top"),       # 顶 → 下降趋势反转（bull→bear）
        ("FTX_low", "2022-11-21", "bottom"),    # 底 → 上升趋势反转（bear→bull）
        ("halving_2024", "2024-04-20", "bottom"),  # 底 → 上升趋势反转
    ]
    turning_points = []
    for tag, target_date, direction in key_dates:
        ts = pd.Timestamp(target_date, tz=df.index.tz)
        pos = df.index.get_indexer([ts], method="nearest")[0]
        actual_date = df.index[pos].strftime("%Y-%m-%d")

        # 在 target_date 后 30 天内查找 Sperandeo 调整非零的日期
        search_end = min(pos + 30, n)
        lag_days = None
        confirm_date = None
        for i in range(pos, search_end):
            if abs(adj[i]) >= 0.34:  # 第 3 条满足 (±0.34)
                lag_days = i - pos
                confirm_date = df.index[i].strftime("%Y-%m-%d")
                break

        turning_points.append({
            "tag": tag,
            "target_date": target_date,
            "actual_date": actual_date,
            "direction": direction,
            "L": round(float(L[pos]), 3),
            "T": round(float(T[pos]), 3),
            "sperandeo_confirm_date": confirm_date,
            "lag_days": lag_days,
        })

    return {
        "continuity": {
            "mean_daily_jump": round(mean_jump, 4),
            "median_daily_jump": round(p50_jump, 4),
            "p90_daily_jump": round(p90_jump, 4),
            "pct_le_0.5": round(pct_le_05, 4),
            "n_samples": n,
        },
        "turning_points": turning_points,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="P3.3 连续性 + 拐点滞后评估")
    p.add_argument("--csv", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)

    csv_path = Path(args.csv).resolve()
    df = _read_csv(csv_path)
    print(f"[P3.3] 读取 {csv_path} ({len(df)} 条) ...")

    result = evaluate_continuity(df)

    print("\n=== 连续性 ===")
    c = result["continuity"]
    print(f"  mean |ΔL|+|ΔT| / day : {c['mean_daily_jump']:.4f}  (目标 ≤ 0.20)")
    print(f"  median               : {c['median_daily_jump']:.4f}")
    print(f"  p90                  : {c['p90_daily_jump']:.4f}")
    print(f"  pct ≤ 0.5            : {c['pct_le_0.5']:.2%}")

    print("\n=== 拐点滞后 ===")
    for tp in result["turning_points"]:
        lag = tp["lag_days"]
        lag_str = f"{lag} 天" if lag is not None else "未确认"
        ok = "PASS" if (lag is not None and lag <= 10) else "FAIL"
        print(f"  {tp['tag']:16s} [{tp['actual_date']}] L={tp['L']:+.2f} T={tp['T']:+.2f}  "
              f"确认={tp['sperandeo_confirm_date'] or '-'}  滞后={lag_str}  → {ok}")

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[P3.3] 结果已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
