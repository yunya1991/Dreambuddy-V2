"""ri 放量门槛与 d_star wait 口径的验证脚本（模拟 + 实际事件分布）。

用法:
    python scripts/backtest_ri_gate.py            # 模拟回测
    python scripts/backtest_ri_gate.py --events   # 叠加 runtime/chain_events 实际 N2 分布

结论口径:
  A. 放量门槛：固定 2.0 的触发率若 <0.5%，说明该门槛在 1H 不可达，需按波动率自适应
  B. d_star：两种 wait 定义的收益差需 > 一个手续费量级才算显著；否则以动作分布与风险为主
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import Counter

import numpy as np

TRADING_HOURS = 24


def gen_prices(n: int, sigma_1h: float, seed: int, drift: float = 0.0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, sigma_1h, n)
    return 100.0 * np.exp(np.cumsum(rets)), np.abs(rets)


def adaptive_threshold(close, lookback_days: int = 20) -> float:
    lr = np.diff(np.log(np.clip(close, 1e-12, None)))
    w = lr[-min(lr.size, TRADING_HOURS * lookback_days) :]
    sigma_day = float(np.std(w)) * math.sqrt(TRADING_HOURS)
    return float(max(1.30, min(2.50, 1.20 + 25.0 * sigma_day)))


def vol_ratios(vol) -> np.ndarray:
    out = []
    for i in range(len(vol) - 20):
        w = vol[i : i + 20]
        v20 = w.mean()
        out.append(w[:5].mean() / v20 if v20 > 0 else 0.0)
    return np.array(out)


def part_a() -> None:
    print("== A. 放量触发率（1H, 5000 bars/组, 100 seeds 均值）==")
    for sigma in (0.001, 0.003, 0.006):
        fixed, adapt = [], []
        for seed in range(100):
            close, vol = gen_prices(5000, sigma, seed)
            r = vol_ratios(vol)
            thr = adaptive_threshold(close)
            fixed.append((r >= 2.0).mean())
            adapt.append((r >= thr).mean())
        print(
            f"sigma_1h={sigma:.4f} | fixed2.0={np.mean(fixed) * 100:5.2f}% "
            f"| adaptive={np.mean(adapt) * 100:5.2f}% (thr≈{adaptive_threshold(gen_prices(5000, sigma, 0)[0]):.2f})"
        )


def proxy_R(close):
    ma5 = np.convolve(close, np.ones(5) / 5, mode="valid")
    ma20 = np.convolve(close, np.ones(20) / 20, mode="valid")
    m = min(len(ma5), len(ma20))
    trend = (ma5[-m:] - ma20[-m:]) / np.maximum(ma20[-m:], 1e-9)
    lr = np.diff(np.log(np.clip(close, 1e-12, None)))
    voln = np.array([np.std(lr[max(0, i - 20) : i + 1]) for i in range(len(lr))])
    m = min(m, len(voln))
    trend, voln = trend[-m:], voln[-m:]
    r_up = np.clip(0.5 - 40 * trend + 10 * voln, 0.05, 0.95)
    r_down = np.clip(0.5 + 40 * trend + 10 * voln, 0.05, 0.95)
    r_smooth = np.clip(1.0 - 30 * np.abs(trend) - 5 * voln, 0.05, 0.95)
    return r_up, r_down, r_smooth


def run_policy(close, wait_mode: str, fee: float = 0.0005):
    r_up, r_down, r_smooth = proxy_R(close)
    r_refl = 0.65
    wait = r_smooth * r_refl if wait_mode == "A" else (1 - r_smooth) * r_refl
    fwd = close[1:] / close[:-1] - 1
    m = min(len(r_up), len(fwd))
    r_up, r_down, wait, fwd = r_up[-m:], r_down[-m:], wait[-m:], fwd[-m:]
    total, trades, waits = 0.0, 0, 0
    equity, peak, mdd = 1.0, 1.0, 0.0
    for i in range(m):
        costs = {"long": r_up[i], "short": r_down[i], "wait": wait[i]}
        act = min(costs, key=costs.get)
        ret = 0.0
        if act == "long":
            ret = fwd[i] - 2 * fee
        elif act == "short":
            ret = -fwd[i] - 2 * fee
        if act != "wait":
            trades += 1
        else:
            waits += 1
        total += ret
        equity *= 1 + ret
        peak = max(peak, equity)
        mdd = max(mdd, 1 - equity / peak)
    return total, trades, waits / max(m, 1), mdd


def part_b() -> None:
    print("== B. d_star wait 口径对比（含 5bps/边手续费, 合成趋势+震荡）==")
    rows = {"A": [], "B": []}
    for seed in range(100):
        n = 3000
        c1, _ = gen_prices(int(n * 0.4), 0.003, seed, drift=0.0012)
        c2, _ = gen_prices(int(n * 0.6), 0.004, seed + 500, drift=0.0)
        close = np.concatenate([c1, c2 * (c1[-1] / c2[0])])
        for mode in ("A", "B"):
            rows[mode].append(run_policy(close, mode))
    for mode in ("A", "B"):
        arr = np.array([r[0] for r in rows[mode]])
        print(
            f"wait={mode} | 累计收益均值 {arr.mean() * 100:6.2f}% (std {arr.std() * 100:5.2f}) "
            f"| 交易 {np.mean([r[1] for r in rows[mode]]):6.0f} "
            f"| WAIT {np.mean([r[2] for r in rows[mode]]) * 100:5.1f}% "
            f"| 平均MDD {np.mean([r[3] for r in rows[mode]]) * 100:5.2f}%"
        )


def part_events(runtime_dir: str) -> None:
    paths = sorted(glob.glob(os.path.join(runtime_dir, "chain_events-*.jsonl")))
    rows = []
    for p in paths:
        with open(p, encoding="utf-8") as f:
            for line in f:
                if '"N2"' not in line:
                    continue
                r = json.loads(line)
                if r.get("stage") == "N2" and (r.get("data") or {}).get("R_up") is not None:
                    rows.append(r["data"])
    if not rows:
        print("== C. 实际事件 ==\n无 N2 事件")
        return

    def act(d, mode):
        up, dn = float(d.get("R_up") or 0.5), float(d.get("R_down") or 0.5)
        sm, rf = float(d.get("R_smooth") or 0.0), float(d.get("R_reflexivity") or 0.5)
        w = sm * rf if mode == "A" else (1 - sm) * rf
        return min((("long", up), ("short", dn), ("wait", w)), key=lambda x: x[1])[0]

    print(f"== C. 实际 N2 事件（n={len(rows)}）==")
    for mode in ("A", "B"):
        c = Counter(act(d, mode) for d in rows)
        print(f"mode {mode}: " + ", ".join(f"{k}={v / len(rows) * 100:.1f}%" for k, v in c.items()))
    flip = sum(1 for d in rows if act(d, "A") != act(d, "B"))
    print(f"flip_rate={flip / len(rows) * 100:.1f}%")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", action="store_true", help="叠加实际 chain_events N2 分布")
    args = ap.parse_args()
    part_a()
    part_b()
    if args.events:
        part_events(os.path.join(os.path.dirname(__file__), "..", "runtime"))
