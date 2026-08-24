"""P3.1 冷启动中心坐标统计 — 从 BTC 真实标签统计 8 态 (L, T) 中心坐标

用法:
  python calibrate_regime_centers.py --csv ../../data/klines/BTC_1D_full.csv --out regime_centers_cold.json

输出 JSON:
  {"TREND_UP_STRONG": [2.5, 3.5], "TREND_UP_MILD": [1.0, 2.0], ...}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_THIS = Path(__file__).resolve()
_MEMORY_L4 = _THIS.parent.parent.parent
if str(_MEMORY_L4) not in sys.path:
    sys.path.insert(0, str(_MEMORY_L4))

from bcrm2.indicators import IndicatorBank
from bcrm2.score_composer import ScoreComposer
from bcrm2.regime_mapper import RegimeMapper, REGIME_CENTERS
from bcrm2.labels.regime_labeler import generate_8state_label, REGIME_ORDER


def calibrate(csv_path: Path, min_samples: int = 50) -> dict:
    df = pd.read_csv(csv_path)
    ts_cols = [c for c in df.columns if c.lower() in {"timestamp", "datetime", "date"}]
    if ts_cols:
        df[ts_cols[0]] = pd.to_datetime(df[ts_cols[0]])
        df = df.set_index(ts_cols[0])
    df = df.sort_index()
    for c in ("open", "high", "low", "close", "volume"):
        if c in df.columns:
            df[c] = df[c].astype(float)

    bank = IndicatorBank()
    indicators = bank.compute_all(df)
    composer = ScoreComposer()
    level_raw, trend_raw = composer.compose(indicators, df)

    labels = generate_8state_label(df, forward_days=20, lookback=252)
    valid = labels.notna()

    centers = {}
    print(f"{'Regime':<20s} {'N':>6s} {'L_mean':>8s} {'T_mean':>8s} {'L_med':>8s} {'T_med':>8s}  vs_init")
    for regime in REGIME_ORDER:
        mask = (labels == regime) & valid
        n = int(mask.sum())
        if n < min_samples:
            # 退化：用初始值
            centers[regime] = list(REGIME_CENTERS[regime])
            print(f"{regime:<20s} {n:>6d}  (insufficient, using init)")
            continue
        L_vals = level_raw[mask].values
        T_vals = trend_raw[mask].values
        L_mean = float(np.mean(L_vals))
        T_mean = float(np.mean(T_vals))
        L_med = float(np.median(L_vals))
        T_med = float(np.median(T_vals))
        centers[regime] = [round(L_mean, 2), round(T_mean, 2)]

        init_L, init_T = REGIME_CENTERS[regime]
        dL = L_mean - init_L
        dT = T_mean - init_T
        flag = " ***" if (abs(dL) > 0.5 or abs(dT) > 0.5) else ""
        print(f"{regime:<20s} {n:>6d} {L_mean:>8.2f} {T_mean:>8.2f} {L_med:>8.2f} {T_med:>8.2f}  "
              f"init=({init_L:+.1f},{init_T:+.1f}) d=({dL:+.2f},{dT:+.2f}){flag}")

    return centers


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="P3.1 冷启动中心坐标统计")
    p.add_argument("--csv", required=True, help="BTC OHLCV CSV 路径")
    p.add_argument("--out", default="regime_centers_cold.json", help="输出 JSON 路径")
    p.add_argument("--min-samples", type=int, default=50)
    args = p.parse_args(argv)

    csv_path = Path(args.csv).resolve()
    out_path = Path(args.out).resolve()
    print(f"[P3.1] 读取 {csv_path} ...")
    centers = calibrate(csv_path, min_samples=args.min_samples)
    out_path.write_text(json.dumps(centers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[P3.1] 冷启动中心已写入 {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
