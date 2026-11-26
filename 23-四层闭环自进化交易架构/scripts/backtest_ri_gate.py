"""ri 放量门槛与 d_star wait 口径的验证脚本（模拟 + 实际事件分布 + 真实 K 线）。

用法:
    python scripts/backtest_ri_gate.py            # A/B 模拟回测
    python scripts/backtest_ri_gate.py --events   # 叠加 runtime/chain_events 实际 N2 分布
    python scripts/backtest_ri_gate.py --klines   # 真实 1H K 线 walk-forward（需外网/云端）

结论口径:
  A. 放量门槛：固定 2.0 的触发率若 <0.5%，说明该门槛在 1H 不可达，需按波动率自适应
  B. d_star：两种 wait 定义的收益差需 > 一个手续费量级才算显著；否则以动作分布与风险为主
  D. wait 口径：legacy(R_smooth×R_refl) 若恒 WAIT，则量纲失配；校准口径需用中性区 margin，
     以 MDD/胜率而非单看收益择优（F4 结论：margin=0.30 的 MDD 最优）
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


def part_klines(symbols=("BTC", "ETH", "SOL"), bars: int = 1000) -> None:
    """D. 真实 1H K 线 walk-forward：逐 bar 重算 R（chip/liq 缺数据=0，仅趋势项），
    对齐真实前向收益比较 wait 口径与中性区 margin。"""
    try:
        import ccxt
    except ImportError:
        print("== D. 真实 K 线 ==\nccxt 不可用（请在云端 venv 执行）")
        return

    def r_dims(close, i, win=200):
        seg = close[max(0, i - win + 1) : i + 1]
        if len(seg) < 60:
            return None
        ma200 = float(seg.mean())
        trend_bias = max(-1.0, min(1.0, (close[i] / ma200 - 1.0) / 0.08))
        x = np.arange(len(seg), dtype=float)
        slope, intercept = np.polyfit(x, seg, 1)
        yhat = slope * x + intercept
        ss_res = float(((seg - yhat) ** 2).sum())
        ss_tot = float(((seg - seg.mean()) ** 2).sum())
        r2 = 0.0 if ss_tot < 1e-18 else max(0.0, min(1.0, 1 - ss_res / ss_tot))
        combined = 0.2 * trend_bias  # 筹码/清算缺数据 → 仅趋势项
        return (
            max(0.0, min(1.0, 0.5 - 0.38 * combined)),
            max(0.0, min(1.0, 0.5 + 0.38 * combined)),
            1.0 - r2,
            0.65,
        )

    ex = ccxt.okx({"enableRateLimit": True, "timeout": 20000})
    closes = {}
    for s in symbols:
        rows = ex.fetch_ohlcv(f"{s}/USDT:USDT", "1h", limit=bars)
        closes[s] = np.array([r[4] for r in rows], dtype=float)

    grid = [("legacy sm*rf", "A", 0.0), ("flip 1-sm", "B", 0.0)] + [
        (f"flip+{int(m * 100)}%", "B", m) for m in (0.10, 0.20, 0.25, 0.30, 0.35)
    ]
    fee = 0.0005
    for h in (4, 24):
        rec = {g[0]: {"a": [], "p": []} for g in grid}
        base = []
        for c in closes.values():
            for i in range(200, len(c) - h):
                d = r_dims(c, i)
                if d is None:
                    continue
                up, dn, sm, rf = d
                ret = c[i + h] / c[i] - 1.0
                base.append(ret)
                for label, mode, mg in grid:
                    w = sm * rf if mode == "A" else (1.0 - sm) * rf
                    bc = min(up, dn)
                    best = "long" if up < dn else "short"
                    if mode == "A":
                        act = "wait" if w <= bc else best
                    else:
                        act = best if bc <= w * (1.0 - mg) else "wait"
                    rec[label]["a"].append(act)
                    rec[label]["p"].append(
                        0.0
                        if act == "wait"
                        else (ret - 2 * fee if act == "long" else -ret - 2 * fee)
                    )
        n = len(base)
        print(
            f"\n== D. 真实 K 线 walk-forward h={h}h | n={n} | 基准 {np.mean(base) * 100:+.3f}% =="
        )
        for label, _, _ in grid:
            a = Counter(rec[label]["a"])
            p = np.array(rec[label]["p"])
            tr = p[p != 0.0]
            eq, peak, mdd = 1.0, 1.0, 0.0
            for x in p:
                eq *= 1 + x
                peak = max(peak, eq)
                mdd = max(mdd, 1 - eq / peak)
            print(
                f"{label:<12} | WAIT {100 * a['wait'] / n:5.1f}% L {100 * a['long'] / n:5.1f}% "
                f"S {100 * a['short'] / n:5.1f}% | 每样本 {100 * p.mean():+7.4f}% "
                f"| 胜率 {100 * float((tr > 0).mean()) if tr.size else 0:5.1f}% "
                f"| 累计 {100 * (eq - 1):+9.2f}% | MDD {100 * mdd:5.2f}%"
            )


def refl_proxy(close, i: int, win: int = 48) -> float:
    """R_reflexivity 代理：近期 1H 收益 lag-1 自相关（趋势自我强化程度）。"""
    seg = close[max(0, i - win * 2 + 1) : i + 1]
    if len(seg) < win + 2:
        return 0.5
    lr = np.diff(np.log(np.clip(seg, 1e-12, None)))
    a, b = lr[:-1], lr[1:]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.5
    ac = float(np.corrcoef(a, b)[0, 1])
    if not math.isfinite(ac):
        return 0.5
    return max(0.0, min(1.0, 0.5 + 0.5 * ac))


def _fallback_pct(v: float) -> float:
    return max(0.0, min(1.0, (v - 0.35) / 0.50))


def part_klines_norm(symbols=("BTC", "ETH", "SOL"), bars: int = 1000) -> None:
    """E. R_reflexivity 历史分位归一化对照（真实 1H K 线，因果 ECDF）。

    对照：legacy / calibrated 原始 / 归一化 scale∈{1.0,1.5,2.0,2.5} / margin∈{0.05,0.10,0.15}
    """
    import bisect

    try:
        import ccxt
    except ImportError:
        print("== E. 归一化回测 ==\nccxt 不可用（请在云端 venv 执行）")
        return

    def r_dims(close, i, win=200):
        seg = close[max(0, i - win + 1) : i + 1]
        if len(seg) < 60:
            return None
        ma200 = float(seg.mean())
        trend_bias = max(-1.0, min(1.0, (close[i] / ma200 - 1.0) / 0.08))
        x = np.arange(len(seg), dtype=float)
        slope, intercept = np.polyfit(x, seg, 1)
        yhat = slope * x + intercept
        ss_res = float(((seg - yhat) ** 2).sum())
        ss_tot = float(((seg - seg.mean()) ** 2).sum())
        r2 = 0.0 if ss_tot < 1e-18 else max(0.0, min(1.0, 1 - ss_res / ss_tot))
        combined = 0.2 * trend_bias
        return (
            max(0.0, min(1.0, 0.5 - 0.38 * combined)),
            max(0.0, min(1.0, 0.5 + 0.38 * combined)),
            1.0 - r2,
        )

    grid = [
        ("legacy sm*rf", "A", 0.0, 1.0, False),
        ("flip raw +10%", "B", 0.10, 1.0, False),
        ("norm x1.0 +10%", "B", 0.10, 1.0, True),
        ("norm x1.1 +10%", "B", 0.10, 1.1, True),
        ("norm x1.2 +10%", "B", 0.10, 1.2, True),
        ("norm x1.3 +10%", "B", 0.10, 1.3, True),
        ("norm x1.5 +10%", "B", 0.10, 1.5, True),
        ("norm x1.75 +10%", "B", 0.10, 1.75, True),
        ("norm x2.0 +5%", "B", 0.05, 2.0, True),
        ("norm x2.0 +10%", "B", 0.10, 2.0, True),
        ("norm x2.0 +15%", "B", 0.15, 2.0, True),
    ]
    fee = 0.0005
    ex = ccxt.okx({"enableRateLimit": True, "timeout": 20000})

    for h in (4, 24):
        agg = {
            g[0]: {
                "n": 0,
                "wait": 0,
                "long": 0,
                "short": 0,
                "p": [],
                "eq": 1.0,
                "peak": 1.0,
                "mdd": 0.0,
            }
            for g in grid
        }
        base = []
        for s in symbols:
            rows = ex.fetch_ohlcv(f"{s}/USDT:USDT", "1h", limit=bars)
            c = np.array([r[4] for r in rows], dtype=float)
            hist: list[float] = []  # 因果历史（当前 bar 之后才入池）
            for i in range(200, len(c) - h):
                d = r_dims(c, i)
                if d is None:
                    continue
                up, dn, sm = d
                raw = refl_proxy(c, i)
                pct = (
                    bisect.bisect_right(hist, raw) / len(hist)
                    if len(hist) >= 50
                    else _fallback_pct(raw)
                )
                bisect.insort(hist, raw)
                if len(hist) > 500:  # 滚动 500 bar 窗口，避免早期 regime 永久主导分位
                    hist.pop(0)
                ret = c[i + h] / c[i] - 1.0
                base.append(ret)
                bc = min(up, dn)
                best = "long" if up < dn else "short"
                for label, mode, mg, scale, use_norm in grid:
                    if mode == "A":
                        w = sm * raw
                        act = "wait" if w <= bc else best
                    else:
                        w = min((1.0 - sm) * (pct * scale if use_norm else raw), 0.99)
                        act = best if bc <= w * (1.0 - mg) else "wait"
                    a = agg[label]
                    a["n"] += 1
                    if act == "wait":
                        a["wait"] += 1
                        a["p"].append(0.0)
                    else:
                        a[act] += 1
                        pnl = ret - 2 * fee if act == "long" else -ret - 2 * fee
                        a["p"].append(pnl)
                        a["eq"] *= 1 + pnl
                        a["peak"] = max(a["peak"], a["eq"])
                        a["mdd"] = max(a["mdd"], 1 - a["eq"] / a["peak"])

        n = len(base)
        print(
            f"\n== E. 分位归一化 walk-forward h={h}h | n={n} | 基准 {np.mean(base) * 100:+.3f}% =="
        )
        for label, *_ in grid:
            a = agg[label]
            nn = max(a["n"], 1)
            p = np.array(a["p"])
            tr = p[p != 0.0]
            print(
                f"{label:<15} | WAIT {100 * a['wait'] / nn:5.1f}% L {100 * a['long'] / nn:5.1f}% "
                f"S {100 * a['short'] / nn:5.1f}% | 每样本 {100 * p.mean():+7.4f}% "
                f"| 胜率 {100 * float((tr > 0).mean()) if tr.size else 0:5.1f}% "
                f"| 累计 {100 * (a['eq'] - 1):+9.2f}% | MDD {100 * a['mdd']:5.2f}%"
            )


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--events", action="store_true", help="叠加实际 chain_events N2 分布")
    ap.add_argument("--klines", action="store_true", help="真实 K 线 walk-forward（需外网）")
    ap.add_argument("--klines-norm", action="store_true", help="R_reflexivity 分位归一化对照")
    args = ap.parse_args()
    part_a()
    part_b()
    if args.events:
        part_events(os.path.join(os.path.dirname(__file__), "..", "runtime"))
    if args.klines:
        part_klines()
    if args.klines_norm:
        part_klines_norm()
