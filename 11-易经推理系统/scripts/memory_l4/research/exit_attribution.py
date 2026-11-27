"""P1 离场归因（只读）：reverse / s3_prep / bdsm 对胜率与 MDD 的贡献。

对每笔真实平仓计算：
1. 交易中 MAE/MFE（方向调整后的最大不利/有利偏移）；
2. 反事实 A：同一入场，改用回测离场栈（TP=3ATR/SL=2ATR/max_hold=60）的收益；
3. 反事实 B：实际退出后继续持有 1/3/6/12 根 bar 的价格漂移（正=退出过早）；
4. MDD 替换测算：把目标离场家族的收益替换为反事实 A，重算交易序列权益回撤。

口径：收益统一用方向调整的价格收益率（不含杠杆/费用），保证实际与反事实可比；
生产 pnl_pct（含杠杆，账户口径）单独汇总。MDD 为按 exit_time 排序的交易序列权益，
忽略持仓重叠，仅用于相对比较。

用法：
    python3 -u scripts/memory_l4/research/exit_attribution.py --days 30
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.bcrm2.eval_1h_walkforward import load_klines  # noqa: E402
from scripts.memory_l4.research.parity_probe import (  # noqa: E402
    DEFAULT_DB,
    exit_family,
    replay_exit,
    wilder_atr,
)

HOLD_HORIZONS = (1, 3, 6, 12)
TARGET_FAMILIES = ("reverse", "s3_prep_exit", "bdsm_exit")


def dir_sign(direction) -> int:
    return -1 if str(direction).lower() in {"short", "-1", "sell"} else 1


def load_all_closed(db_path: Path, days: int) -> list[dict]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT symbol,direction,entry_time,exit_time,entry_price,exit_price,"
            "pnl_pct,hold_bars,exit_reason,confidence FROM trades "
            "WHERE exit_time IS NOT NULL ORDER BY exit_time"
        ).fetchall()
    finally:
        con.close()
    cutoff = datetime.now(timezone.utc) - pd.Timedelta(days=days)
    out = []
    for r in rows:
        d = dict(r)
        ts = pd.Timestamp(str(d["exit_time"]).replace("Z", "+00:00"))
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts
        if ts < cutoff:
            continue
        out.append(d)
    return out


def attribute_trade(t, df, atr, args) -> dict | None:
    entry_ts = pd.Timestamp(str(t["entry_time"]).replace("Z", "+00:00"))
    exit_ts = pd.Timestamp(str(t["exit_time"]).replace("Z", "+00:00"))
    entry_ts = entry_ts.tz_localize("UTC") if entry_ts.tzinfo is None else entry_ts
    exit_ts = exit_ts.tz_localize("UTC") if exit_ts.tzinfo is None else exit_ts
    entry_price = float(t.get("entry_price") or 0)
    exit_price = float(t.get("exit_price") or 0)
    if entry_price <= 0 or exit_price <= 0:
        return None
    sign = dir_sign(t["direction"])
    ei = int(df.index.searchsorted(entry_ts))
    xi = int(df.index.searchsorted(exit_ts, side="right")) - 1
    if ei <= 200 or ei >= len(df) - 2 or xi < ei:
        return None
    xi = min(xi, len(df) - 1)

    window = df.iloc[ei : xi + 1]
    if window.empty:
        return None
    high, low = window["high"].to_numpy(), window["low"].to_numpy()
    favorable = np.where(sign == 1, high - entry_price, entry_price - low) / entry_price
    adverse = np.where(sign == 1, low - entry_price, entry_price - high) / entry_price
    mfe = float(np.nanmax(favorable))
    mae = float(np.nanmin(adverse))

    actual_ret = sign * (exit_price - entry_price) / entry_price
    rep = replay_exit(
        df, atr, ei, t["direction"], entry_price, args.tp_atr, args.sl_atr, args.max_hold
    )
    cf_ret = sign * (rep["price"] - entry_price) / entry_price if rep else None

    drift = {}
    for k in HOLD_HORIZONS:
        j = xi + k
        if j < len(df):
            drift[str(k)] = sign * (float(df["close"].iloc[j]) - exit_price) / exit_price
        else:
            drift[str(k)] = None

    return {
        "symbol": t["symbol"],
        "direction": t["direction"],
        "entry_time": t["entry_time"],
        "exit_time": t["exit_time"],
        "family": exit_family(t.get("exit_reason")),
        "exit_reason": t.get("exit_reason"),
        "confidence": t.get("confidence"),
        "hold_bars_prod": t.get("hold_bars"),
        "actual_ret": actual_ret,
        "pnl_pct_prod": t.get("pnl_pct"),
        "mfe": mfe,
        "mae": mae,
        "cf_ret": cf_ret,
        "cf_family": rep["family"] if rep else None,
        "cf_hold_bars": (rep["idx"] - ei) if rep else None,
        "post_exit_drift": drift,
    }


def summarize_family(records: list[dict]) -> dict:
    n = len(records)
    if not n:
        return {"n": 0}
    actual = np.array([r["actual_ret"] for r in records])
    cf = np.array([r["cf_ret"] for r in records if r["cf_ret"] is not None])
    pnl_prod = [r["pnl_pct_prod"] for r in records if r["pnl_pct_prod"] is not None]
    out = {
        "n": n,
        "win_rate_actual": round(float((actual > 0).mean()), 4),
        "mean_actual_ret_pct": round(float(actual.mean()) * 100, 4),
        "sum_actual_ret_pct": round(float(actual.sum()) * 100, 4),
        "sum_pnl_pct_prod": round(float(sum(pnl_prod)), 4) if pnl_prod else None,
        "mean_mfe_pct": round(float(np.mean([r["mfe"] for r in records])) * 100, 4),
        "mean_mae_pct": round(float(np.mean([r["mae"] for r in records])) * 100, 4),
    }
    if len(cf):
        out["win_rate_counterfactual"] = round(float((cf > 0).mean()), 4)
        out["mean_cf_ret_pct"] = round(float(cf.mean()) * 100, 4)
        out["delta_cf_minus_actual_pct"] = round(float(cf.mean() - actual.mean()) * 100, 4)
    for k in HOLD_HORIZONS:
        vals = [r["post_exit_drift"][str(k)] for r in records]
        vals = [v for v in vals if v is not None]
        if vals:
            out[f"drift_{k}bar_mean_pct"] = round(float(np.mean(vals)) * 100, 4)
            out[f"drift_{k}bar_positive_share"] = round(float(np.mean([v > 0 for v in vals])), 4)
    return out


def max_drawdown(returns: list[float]) -> float:
    if not returns:
        return 0.0
    equity = np.cumprod(1 + np.asarray(returns))
    peak = np.maximum.accumulate(equity)
    return float(((equity - peak) / peak).min())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbols", nargs="+", default=None, help="可选：只归因指定标的")
    ap.add_argument("--timeframe", default="1H")
    ap.add_argument("--max-bars", type=int, default=8000)
    ap.add_argument("--min-bars", type=int, default=1000)
    ap.add_argument("--tp-atr", type=float, default=3.0)
    ap.add_argument("--sl-atr", type=float, default=2.0)
    ap.add_argument("--max-hold", type=int, default=60)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    trades = load_all_closed(Path(args.db), args.days)
    if args.symbols:
        trades = [t for t in trades if t["symbol"] in set(args.symbols)]
    by_symbol = defaultdict(list)
    for t in trades:
        by_symbol[t["symbol"]].append(t)

    records, failures = [], {}
    for symbol, rows in sorted(by_symbol.items()):
        df = load_klines(symbol, args.timeframe, args.max_bars, args.min_bars, False)
        if df is None or len(df) == 0:
            failures[symbol] = {"n": len(rows), "error": "empty_klines"}
            print(f"[{symbol}] 无 K 线，{len(rows)} 笔无法归因", flush=True)
            continue
        atr = wilder_atr(df)
        ok = 0
        for t in rows:
            try:
                rec = attribute_trade(t, df, atr, args)
            except Exception as exc:  # 单笔失败不中断
                rec = None
                failures.setdefault(symbol, {})["last_error"] = str(exc)[:200]
            if rec:
                records.append(rec)
                ok += 1
        print(f"[{symbol}] 归因 {ok}/{len(rows)}", flush=True)

    grouped = defaultdict(list)
    for r in records:
        grouped[r["family"]].append(r)
    per_family = {fam: summarize_family(rs) for fam, rs in sorted(grouped.items())}

    records.sort(key=lambda r: r["exit_time"])
    actual_returns = [r["actual_ret"] for r in records]
    mdd_actual = max_drawdown(actual_returns)
    replaced = []
    replaced_all = []
    for r in records:
        use_cf = r["family"] in TARGET_FAMILIES and r["cf_ret"] is not None
        replaced.append(r["cf_ret"] if use_cf else r["actual_ret"])
        replaced_all.append(r["cf_ret"] if r["cf_ret"] is not None else r["actual_ret"])
    mdd_replaced = max_drawdown(replaced)
    mdd_all_cf = max_drawdown(replaced_all)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": args.db,
        "days": args.days,
        "n_closed": len(trades),
        "n_attributed": len(records),
        "failures": failures,
        "target_families": list(TARGET_FAMILIES),
        "method": {
            "returns": "方向调整价格收益率（不含杠杆/费用），实际与反事实同口径",
            "counterfactual_A": "同入场 + 回测离场栈 TP=3ATR/SL=2ATR/max_hold=60",
            "counterfactual_B": "实际退出后持有 1/3/6/12 根 bar 的方向调整漂移",
            "mdd": "按 exit_time 排序的交易序列复利权益；忽略持仓重叠，仅相对比较",
        },
        "overall": {
            "win_rate_actual": (
                round(float(np.mean([r > 0 for r in actual_returns])), 4)
                if actual_returns
                else None
            ),
            "mdd_actual_pct": round(mdd_actual * 100, 4),
            "mdd_replace_target_families_pct": round(mdd_replaced * 100, 4),
            "mdd_all_counterfactual_pct": round(mdd_all_cf * 100, 4),
        },
        "per_family": per_family,
        "records": records,
    }
    out = (
        Path(args.out)
        if args.out
        else (PROJECT_ROOT / "data" / "eval" / f"exit_attribution_{datetime.now():%Y%m%d}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\n=== 离场家族归因 ===", flush=True)
    for fam, s in sorted(per_family.items(), key=lambda kv: -kv[1].get("n", 0)):
        if not s.get("n"):
            continue
        print(
            f"{fam:16s} n={s['n']:2d} WR={s['win_rate_actual']:.2%} "
            f"实际均值={s['mean_actual_ret_pct']:+.3f}% "
            f"反事实={s.get('mean_cf_ret_pct')} "
            f"drift6={s.get('drift_6bar_mean_pct')} MFE={s['mean_mfe_pct']}",
            flush=True,
        )
    print(f"[overall] {payload['overall']}", flush=True)
    print(f"[out] {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
