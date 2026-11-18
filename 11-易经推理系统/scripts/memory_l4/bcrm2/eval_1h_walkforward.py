#!/usr/bin/env python3
"""P1: 1H 已收盘 K 线 5 折 walk-forward 评测。

对应 SPEC：docs/SPEC-20261118-1H-walkforward-validation.md

职责边界：
- 复用 bcrm2.walk_forward_backtester.WalkForwardBacktester（特征/标签/5 折重训/交易模拟）；
- 本脚本只新增：数据门禁 G0、always-long 基线、生产阈值后验子样本、G2-G4 判定、结果落盘。

用法：
    python scripts/memory_l4/bcrm2/eval_1h_walkforward.py --coins BTC ETH SOL
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# 与 run_baseline_comparison.py 一致：把 11-易经推理系统 作为包根
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.bcrm2.data_fetcher import get_klines  # noqa: E402
from scripts.memory_l4.bcrm2.walk_forward_backtester import (  # noqa: E402
    WalkForwardBacktester,
)

BAR_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1H": 3_600_000, "4H": 14_400_000}


# ============================================================
# 数据与门禁
# ============================================================


def _drop_unclosed(df, timeframe: str):
    """剔除未收盘的最后一根 bar（OKX 最新一根是进行中的 bar）。"""
    dur = BAR_MS.get(timeframe)
    if not dur or df is None or len(df) == 0:
        return df
    now_ms = int(time.time() * 1000)
    while len(df) > 0 and int(df.index[-1].timestamp() * 1000) + dur > now_ms:
        df = df.iloc[:-1]
    return df


def load_klines(symbol: str, timeframe: str, max_bars: int, min_bars: int, force_refresh: bool):
    """加载已收盘 K 线；不足时多轮断点续传补齐（每轮从本地最旧 bar 向上游扩展）。"""
    if not force_refresh:
        df = _drop_unclosed(
            get_klines(symbol, timeframe, max_bars=max_bars, max_age_bars=2), timeframe
        )
        if df is not None and len(df) >= min_bars:
            return df

    df = None
    for attempt in range(3):
        # refresh=True 走断点续传：本地已有最新数据时，after_ts=最旧 bar，只补更早历史
        df = get_klines(symbol, timeframe, max_bars=max_bars, max_age_bars=2, refresh=True)
        df = _drop_unclosed(df, timeframe)
        n = 0 if df is None else len(df)
        print(f"  [{symbol}] 补数第 {attempt + 1} 轮: {n} 根 (目标 {min_bars})")
        if df is not None and len(df) >= min_bars:
            break
    return df


def check_data(df, symbol: str, min_bars: int) -> dict:
    """G0 数据门禁。"""
    if df is None or len(df) == 0:
        return {"ok": False, "reason": "empty"}
    dup = int(df.index.duplicated().sum())
    mono = bool(df.index.is_monotonic_increasing)
    nan = int(df[["open", "high", "low", "close"]].isna().sum().sum())
    info = {
        "symbol": symbol,
        "bars": int(len(df)),
        "start": str(df.index[0]),
        "end": str(df.index[-1]),
        "duplicates": dup,
        "monotonic": mono,
        "nan_ohlc": nan,
        "hash": hashlib.sha256(
            np.round(df[["open", "high", "low", "close"]].values, 8).tobytes()
            + str(df.index[0]).encode()
            + str(df.index[-1]).encode()
        ).hexdigest()[:16],
    }
    problems = []
    if len(df) < min_bars:
        problems.append(f"bars<{min_bars}")
    if dup:
        problems.append("duplicate_index")
    if not mono:
        problems.append("not_monotonic")
    if nan:
        problems.append("nan_ohlc")
    info["ok"] = not problems
    info["reason"] = ",".join(problems) or "ok"
    return info


# ============================================================
# 指标
# ============================================================


def bootstrap_ci(pnls, n_boot: int = 2000, seed: int = 42):
    """单笔期望的 95% bootstrap 置信区间（下界用于 G3 显著性门禁）。"""
    n = len(pnls)
    if n < 10:
        return [None, None]
    arr = np.asarray(pnls, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = arr[idx].mean(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def stats_from_trades(trades, label: str = "") -> dict:
    """按 Trade 列表计算胜率/期望/PF/MDD（pnl_pct 单位为 %）。"""
    pnls = [float(t.pnl_pct) for t in trades]
    n = len(pnls)
    if n == 0:
        return {
            "label": label,
            "n": 0,
            "win_rate": 0.0,
            "expectancy_pct": 0.0,
            "expectancy_ci95": [None, None],
            "profit_factor": 0.0,
            "max_drawdown_pct": 0.0,
            "total_return_pct": 0.0,
        }
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    mdd = float(np.max(peak - cum)) if n else 0.0
    return {
        "label": label,
        "n": n,
        "win_rate": round(len(wins) / n, 4),
        "expectancy_pct": round(float(np.mean(pnls)), 4),
        "expectancy_ci95": bootstrap_ci(pnls),
        "profit_factor": round(gross_win / gross_loss, 4) if gross_loss > 0 else float("inf"),
        "max_drawdown_pct": round(mdd, 4),
        "total_return_pct": round(float(sum(pnls)), 4),
    }


def always_long_trades(
    df,
    windows,
    tp_atr: float,
    sl_atr: float,
    max_hold: int,
    fee_rate: float,
    slippage_rate: float,
):
    """always-long 基线：同测试窗口、同 TP/SL/时间离场（不启用模型与跟踪止盈）。"""
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values  # noqa: E741
    c = df["close"].values
    out = []
    for test_start, test_end in windows:
        i = test_start
        while i < test_end - 1:
            entry = float(o[i + 1])
            atr_est = entry * 0.015  # 与 walk_forward_backtester 的入场 ATR 近似一致
            tp = entry + atr_est * tp_atr
            sl = entry - atr_est * sl_atr
            exit_price = None
            exit_i = None
            reason = "time"
            for j in range(i + 1, min(i + 1 + max_hold, test_end)):
                if h[j] >= tp:
                    exit_price, exit_i, reason = tp, j, "tp"
                    break
                if l[j] <= sl:
                    exit_price, exit_i, reason = sl, j, "sl"
                    break
            if exit_price is None:
                exit_i = min(i + max_hold, test_end - 1)
                exit_price = float(c[exit_i])
            fee = entry * fee_rate + exit_price * fee_rate
            slip = (entry + exit_price) * slippage_rate
            pnl_pct = ((exit_price - entry) - fee - slip) / entry * 100
            out.append({"entry_i": i, "exit_i": exit_i, "pnl_pct": pnl_pct, "reason": reason})
            i = exit_i + 1
    return out


def baseline_stats(trades, label="always_long") -> dict:
    class _T:
        def __init__(self, pnl):
            self.pnl_pct = pnl

    return stats_from_trades([_T(t["pnl_pct"]) for t in trades], label=label)


def baseline_by_fold(trades, windows) -> list:
    out = []
    for k, (ts, te) in enumerate(windows):
        sub = [t for t in trades if ts <= t["entry_i"] < te]
        out.append(
            stats_from_trades(
                [type("T", (), {"pnl_pct": t["pnl_pct"]}) for t in sub], f"B1_fold{k}"
            )
        )
    return out


def buy_hold_windows(df, windows, fee_rate: float, slippage_rate: float) -> list:
    """B0：每个测试窗口一次性买入并持有，仅一次往返成本。"""
    o = df["open"].values
    c = df["close"].values
    out = []
    for k, (ts, te) in enumerate(windows):
        entry, exit_price = float(o[ts]), float(c[te - 1])
        cost = (entry + exit_price) * (fee_rate + slippage_rate)
        pnl_pct = ((exit_price - entry) - cost) / entry * 100
        out.append({"label": f"B0_fold{k}", "pnl_pct": round(pnl_pct, 4)})
    return out


# ============================================================
# 门禁判定
# ============================================================


def random_direction_baseline(bt, df, windows, seeds: int = 20, conf: float = 0.99):
    """B3：随机方向 + 与模型完全相同的离场栈（直接复用 _simulate_trades）。

    模型交易含 trailing stop/TP、时间离场与手续费；B3 用同一模拟器生成，
    仅把方向替换为种子化随机 50/50，用于剥离方向 alpha。
    """
    per_seed = []
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        trades = []
        for ts, te in windows:
            preds = [
                {
                    "action": "OPEN",
                    "direction": int(rng.integers(0, 2)),
                    "final_confidence": conf,
                    "hexagram": {},
                }
                for _ in range(te - ts)
            ]
            trades.extend(bt._simulate_trades(df, preds, ts, te, None))
        per_seed.append(stats_from_trades(trades, f"B3_seed{seed}"))
    keys = (
        "n",
        "win_rate",
        "expectancy_pct",
        "profit_factor",
        "max_drawdown_pct",
        "total_return_pct",
    )
    avg = {k: round(float(np.mean([s[k] for s in per_seed])), 4) for k in keys}
    avg["label"] = f"random_direction_x{seeds}"
    avg["seeds"] = seeds
    return avg, per_seed


def evaluate_gates(primary: dict, baseline: dict, b3: dict, folds: list, n_folds: int) -> dict:
    g2 = (
        primary["n"] >= 150
        and sum(1 for f in folds if f["n"] >= 20) >= 4
        and all(f["n"] >= 10 for f in folds)
    )
    ci_low = primary.get("expectancy_ci95", [None, None])[0]
    g3 = (
        primary["expectancy_pct"] > 0
        and ci_low is not None
        and ci_low > 0
        and primary["profit_factor"] >= 1.2
        and primary["max_drawdown_pct"] <= 15.0
        and (
            b3["max_drawdown_pct"] <= 0
            or primary["max_drawdown_pct"] <= b3["max_drawdown_pct"] * 1.10
        )
        and primary["expectancy_pct"] >= b3["expectancy_pct"] + 0.05
    )
    positive = sum(1 for f in folds if f["expectancy_pct"] > 0)
    max_share = max((f["n"] for f in folds), default=0) / primary["n"] if primary["n"] else 0.0
    g4 = positive >= max(3, n_folds - 2) and max_share < 0.60

    if not g2:
        verdict = "INSUFFICIENT"
    elif g3 and g4:
        verdict = "PASS"
    elif g3:
        verdict = "CONDITIONAL"
    else:
        verdict = "FAIL"
    return {
        "G2_sample": bool(g2),
        "G3_economics": bool(g3),
        "G4_robustness": bool(g4),
        "expectancy_ci95_low": ci_low,
        "b3_expectancy_pct": b3["expectancy_pct"],
        "b1_expectancy_pct": baseline["expectancy_pct"],
        "folds_positive": positive,
        "max_fold_trade_share": round(max_share, 4),
        "verdict": verdict,
    }


# ============================================================
# 主流程
# ============================================================


def git_sha() -> str:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(PROJECT_ROOT))
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def run_coin(args, symbol, ref_cache) -> dict:
    df = load_klines(symbol, args.timeframe, args.max_bars, args.min_bars, args.force_refresh)
    data_info = check_data(df, symbol, args.min_bars)
    if not data_info["ok"]:
        return {"symbol": symbol, "data": data_info, "error": data_info["reason"]}

    ref_df = None
    ref_info = {"used": False}
    if symbol.upper() != "BTC":
        if ref_cache.get("BTC") is None:
            ref_cache["BTC"] = load_klines(
                "BTC", args.timeframe, args.max_bars, args.min_bars, args.force_refresh
            )
        ref_df = ref_cache["BTC"]
        if ref_df is not None and len(ref_df) > 200:
            ref_df = ref_df.reindex(df.index, method="ffill")
            ref_info = {
                "used": True,
                "bars": int(len(ref_df)),
                "start": str(ref_df.index[0]),
                "end": str(ref_df.index[-1]),
                "stale": bool(ref_df.isna().all(axis=1).any()),
            }
        else:
            ref_df = None

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=args.n_folds,
        train_ratio=args.train_ratio,
        min_train_bars=args.min_train_bars,
        min_test_bars=args.min_test_bars,
        conf_threshold=args.conf,
        tp_atr=args.tp_atr,
        sl_atr=args.sl_atr,
        max_hold_bars=args.max_hold,
        fee_rate=args.fee,
        slippage_rate=args.slippage,
        feature_selection=not args.no_feature_selection,
        macro_config={} if args.no_macro else None,
    )
    # 关闭五角校验，保证 5 折对比可复现、无额外反馈状态
    bt.enable_pentagon = False
    bt._triangle_verifier = None

    t0 = time.time()
    result = bt.run(
        df,
        ref_df=ref_df,
        verbose=args.verbose,
        # G0.5 泄漏门禁：主口径只启用因果滚动特征；
        # market_cap 使用全序列 median/std 决定模块开关，属未来数据泄漏，先禁用。
        auto_mcap_config=False,
        enable_mcap=False,
        enable_merrill=False,
        enable_cycle=False,
    )
    elapsed = round(time.time() - t0, 1)

    windows = [(f.test_start, f.test_end) for f in result.folds]
    folds = []
    for k, f in enumerate(result.folds):
        st = stats_from_trades(f.trades, f"fold{k}")
        st.update(
            {
                "test_start": int(f.test_start),
                "test_end": int(f.test_end),
                "n_train": int(f.n_train),
            }
        )
        folds.append(st)

    primary = stats_from_trades(result.all_trades, f"T_res={args.conf}")

    prod_trades = [
        t for t in result.all_trades if float(getattr(t, "confidence", 0.0)) >= args.prod_conf
    ]
    prod = stats_from_trades(prod_trades, f"T_prod={args.prod_conf}(post-hoc)")

    b_trades = always_long_trades(
        df, windows, args.tp_atr, args.sl_atr, args.max_hold, args.fee, args.slippage
    )
    baseline = baseline_stats(b_trades)
    baseline["folds"] = baseline_by_fold(b_trades, windows)
    baseline["buy_hold"] = buy_hold_windows(df, windows, args.fee, args.slippage)

    b3, b3_seeds = random_direction_baseline(bt, df, windows, seeds=args.b3_seeds)
    b3["per_seed"] = b3_seeds

    gates = evaluate_gates(primary, baseline, b3, folds, args.n_folds)

    return {
        "symbol": symbol,
        "data": data_info,
        "ref": ref_info,
        "elapsed_sec": elapsed,
        "primary": primary,
        "prod_threshold": prod,
        "baseline": baseline,
        "b3_random": b3,
        "folds": folds,
        "gates": gates,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--timeframe", default="1H")
    ap.add_argument("--max-bars", type=int, default=30000)
    ap.add_argument("--min-bars", type=int, default=12000)
    ap.add_argument("--n-folds", type=int, default=5)
    ap.add_argument("--train-ratio", type=float, default=0.7)
    ap.add_argument("--min-train-bars", type=int, default=1000)
    ap.add_argument("--min-test-bars", type=int, default=200)
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--prod-conf", type=float, default=0.7955)
    ap.add_argument("--tp-atr", type=float, default=3.0)
    ap.add_argument("--sl-atr", type=float, default=2.0)
    ap.add_argument("--max-hold", type=int, default=60)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.001)
    ap.add_argument("--no-feature-selection", action="store_true")
    ap.add_argument("--no-macro", action="store_true")
    ap.add_argument("--b3-seeds", type=int, default=20)
    ap.add_argument("--force-refresh", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = {
        "coins": args.coins,
        "timeframe": args.timeframe,
        "max_bars": args.max_bars,
        "min_bars": args.min_bars,
        "n_folds": args.n_folds,
        "train_ratio": args.train_ratio,
        "conf": args.conf,
        "prod_conf": args.prod_conf,
        "tp_atr": args.tp_atr,
        "sl_atr": args.sl_atr,
        "max_hold": args.max_hold,
        "fee": args.fee,
        "slippage": args.slippage,
        "feature_selection": not args.no_feature_selection,
        "macro": not args.no_macro,
        "b3_seeds": args.b3_seeds,
        "causal_only_modules": True,
    }

    print("=" * 72)
    print("  P1 1H 5 折 walk-forward 评测")
    print(f"  coins={args.coins} bars={args.max_bars} folds={args.n_folds} conf={args.conf}")
    print("=" * 72)

    ref_cache = {}
    results = {}
    for coin in args.coins:
        print(f"\n[{coin}] 开始...")
        try:
            results[coin] = run_coin(args, coin, ref_cache)
        except Exception as e:  # noqa: BLE001 单币失败不阻断其余币
            import traceback

            traceback.print_exc()
            results[coin] = {"symbol": coin, "error": f"{type(e).__name__}: {e}"}
        r = results[coin]
        if "error" in r:
            print(f"[{coin}] 失败: {r['error']}")
        else:
            p, g = r["primary"], r["gates"]
            print(
                f"[{coin}] N={p['n']} WR={p['win_rate']:.1%} E={p['expectancy_pct']:+.3f}% "
                f"PF={p['profit_factor']:.2f} MDD={p['max_drawdown_pct']:.2f}% → {g['verdict']}"
            )
            print(
                f"        基线 WR={r['baseline']['win_rate']:.1%} E={r['baseline']['expectancy_pct']:+.3f}%"
            )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "config": cfg,
        "config_hash": config_hash(cfg),
        "results": results,
        "summary": {c: r.get("gates", {}).get("verdict", "ERROR") for c, r in results.items()},
    }

    out = (
        Path(args.out)
        if args.out
        else PROJECT_ROOT / "data" / "eval" / "walkforward_1h_20261118.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\n结果已保存: {out}")
    print(f"汇总: {payload['summary']}")


if __name__ == "__main__":
    main()
