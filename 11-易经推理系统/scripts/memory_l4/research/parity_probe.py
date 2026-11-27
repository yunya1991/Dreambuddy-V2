"""P0-B 生产—回测 parity 探针（只读）。

回答两个问题：
1. 身份/关联证据是否足够支撑逐笔 parity（source_system/trade_id/signal_id 覆盖率）；
2. 真实成交的离场，能否被回测离场栈（TP=3ATR / SL=2ATR / max_hold=60）复现。

方法：以生产实际 entry_time/entry_price/direction 为锚，从入场 bar 起按回测规则
重放 1H K 线，比较 exit 原因族、exit 时间、exit 价格。生产 pnl_pct 可能含杠杆，
与回测价格收益率不直接可比，因此主判定用「原因族 + 时间 + 价格」而非 pnl。

用法：
    python3 scripts/memory_l4/research/parity_probe.py --coins BTC ETH SOL
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.bcrm2.eval_1h_walkforward import load_klines  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "scripts" / "data" / "bcrm_trades.db"
BACKTEST_EXIT_FAMILIES = {"tp", "sl", "timeout"}


def _parse_ts(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def exit_family(reason: str) -> str:
    """把生产 exit_reason 归到原因族；未知保留原文前缀，便于暴露回测没有的离场。"""
    r = str(reason or "").lower()
    if not r:
        return "unknown"
    if "ranked_tp" in r or "take_profit" in r or r.startswith("tp"):
        return "tp"
    if "soft_stop" in r or "stop_loss" in r or r.startswith("sl"):
        return "sl"
    if "timeout" in r or "max_hold" in r:
        return "timeout"
    if "signal_reverse" in r or "trend_reverse" in r:
        return "reverse"
    if "bdsm" in r:
        return "bdsm_exit"
    if "evolution" in r:
        return "evolution_exit"
    if "s3_prep" in r:
        return "s3_prep_exit"
    return r.split(":")[0]


def wilder_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(
        axis=1
    )
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def replay_exit(df, atr, entry_idx, direction, entry_price, tp_atr, sl_atr, max_hold):
    """回测离场栈重放：TP/SL 同根优先 SL（与 walk_forward_backtester 一致）。"""
    if entry_idx >= len(df) or entry_price <= 0:
        return None
    a = float(atr.iloc[entry_idx - 1]) if entry_idx > 0 else float("nan")
    if not np.isfinite(a) or a <= 0:
        return None
    is_long = str(direction).lower() in {"long", "1", "buy"}
    tp_roi = tp_atr * a / entry_price
    sl_roi = sl_atr * a / entry_price
    tp_price = entry_price * (1 + tp_roi) if is_long else entry_price * (1 - tp_roi)
    sl_price = entry_price * (1 - sl_roi) if is_long else entry_price * (1 + sl_roi)

    last = min(entry_idx + max_hold, len(df) - 1)
    for i in range(entry_idx, last + 1):
        high, low = float(df["high"].iloc[i]), float(df["low"].iloc[i])
        hit_tp = high >= tp_price if is_long else low <= tp_price
        hit_sl = low <= sl_price if is_long else high >= sl_price
        if hit_sl:  # 同根双触发保守取 SL
            return {"idx": i, "family": "sl", "price": sl_price, "tp_roi": tp_roi, "sl_roi": sl_roi}
        if hit_tp:
            return {"idx": i, "family": "tp", "price": tp_price, "tp_roi": tp_roi, "sl_roi": sl_roi}
    return {
        "idx": last,
        "family": "timeout",
        "price": float(df["close"].iloc[last]),
        "tp_roi": tp_roi,
        "sl_roi": sl_roi,
    }


def load_closed_trades(db_path: Path, symbol: str, days: int) -> list[dict]:
    if not db_path.exists():
        return []
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(trades)")}
        want = [
            "symbol",
            "direction",
            "entry_time",
            "exit_time",
            "entry_price",
            "exit_price",
            "pnl_pct",
            "exit_reason",
            "confidence",
            "model_version",
        ]
        want += [
            c for c in ("source_system", "mode", "trade_id", "signal_id", "git_sha") if c in cols
        ]
        rows = con.execute(
            f"SELECT {', '.join(want)} FROM trades WHERE symbol=? AND exit_time IS NOT NULL"
            " ORDER BY id DESC",
            (symbol,),
        ).fetchall()
    finally:
        con.close()
    cutoff = datetime.now(timezone.utc) - pd.Timedelta(days=days)
    out = []
    for r in rows:
        d = dict(r)
        ts = _parse_ts(d.get("exit_time"))
        if ts is None or ts < cutoff:
            continue
        d["source_system"] = d.get("source_system") or ""
        out.append(d)
    return out


def probe_coin(symbol, df, trades, args) -> dict:
    atr = wilder_atr(df)
    records, skipped = [], 0
    for t in trades:
        entry_ts = _parse_ts(t.get("entry_time"))
        exit_ts = _parse_ts(t.get("exit_time"))
        entry_price = float(t.get("entry_price") or 0)
        if entry_ts is None or exit_ts is None or entry_price <= 0:
            skipped += 1
            continue
        idx = int(df.index.searchsorted(entry_ts))
        if idx <= 200 or idx >= len(df) - 1:
            skipped += 1
            continue
        rep = replay_exit(
            df,
            atr,
            idx,
            t.get("direction"),
            entry_price,
            args.tp_atr,
            args.sl_atr,
            args.max_hold,
        )
        if rep is None:
            skipped += 1
            continue
        prod_family = exit_family(t.get("exit_reason"))
        prod_price = float(t.get("exit_price") or 0)
        rep_time = df.index[rep["idx"]]
        time_diff_h = (exit_ts - rep_time.to_pydatetime()).total_seconds() / 3600.0
        price_diff_pct = (prod_price - rep["price"]) / rep["price"] * 100 if rep["price"] else None
        records.append(
            {
                "entry_time": t.get("entry_time"),
                "exit_time": t.get("exit_time"),
                "direction": t.get("direction"),
                "source_system": t["source_system"] or "UNKNOWN",
                "prod_family": prod_family,
                "replay_family": rep["family"],
                "family_match": prod_family == rep["family"],
                "time_diff_hours": round(time_diff_h, 3),
                "price_diff_pct": round(price_diff_pct, 4) if price_diff_pct is not None else None,
                "prod_exit_price": prod_price,
                "replay_exit_price": rep["price"],
                "prod_pnl_pct": t.get("pnl_pct"),
                "identity": {
                    "trade_id": bool(t.get("trade_id")),
                    "signal_id": bool(t.get("signal_id")),
                    "git_sha": bool(t.get("git_sha")),
                },
            }
        )

    fam = Counter(r["prod_family"] for r in records)
    matched = [r for r in records if r["family_match"]]
    within_2h = [r for r in matched if abs(r["time_diff_hours"]) <= 2]
    return {
        "symbol": symbol,
        "closed_in_window": len(trades),
        "replayed": len(records),
        "skipped": skipped,
        "prod_exit_families": dict(fam),
        "families_not_in_backtest": sorted(set(fam) - BACKTEST_EXIT_FAMILIES),
        "family_match_rate": round(len(matched) / len(records), 4) if records else None,
        "family_and_time_match_rate": round(len(within_2h) / len(records), 4) if records else None,
        "identity_coverage": {
            "source_known": sum(1 for r in records if r["source_system"] != "UNKNOWN"),
            "trade_id": sum(1 for r in records if r["identity"]["trade_id"]),
            "signal_id": sum(1 for r in records if r["identity"]["signal_id"]),
            "git_sha": sum(1 for r in records if r["identity"]["git_sha"]),
        },
        "records": records,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--timeframe", default="1H")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--max-bars", type=int, default=8000)
    ap.add_argument("--min-bars", type=int, default=1000)
    ap.add_argument("--tp-atr", type=float, default=3.0)
    ap.add_argument("--sl-atr", type=float, default=2.0)
    ap.add_argument("--max-hold", type=int, default=60)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": args.db,
        "backtest_exit_stack": {
            "families": sorted(BACKTEST_EXIT_FAMILIES),
            "tp_atr": args.tp_atr,
            "sl_atr": args.sl_atr,
            "max_hold": args.max_hold,
            "same_bar_priority": "sl",
            "entry": "本探针锚定生产实际 entry_price/entry_time，仅对齐离场规则",
        },
        "limitations": [
            "历史成交无 signal_id/model_version，无法做信号级 replay，只能做离场级 replay",
            "生产 pnl_pct 可能含杠杆，不与回测价格收益率直接比较",
            "ATR=Wilder14；与回测实现若有细节差异会影响数值，不影响原因族结论",
        ],
        "results": {},
    }

    for coin in args.coins:
        trades = load_closed_trades(Path(args.db), coin, args.days)
        if not trades:
            payload["results"][coin] = {"symbol": coin, "closed_in_window": 0}
            print(f"[{coin}] 窗口内无已平仓记录")
            continue
        df = load_klines(coin, args.timeframe, args.max_bars, args.min_bars, False)
        if df is None or len(df) == 0:
            payload["results"][coin] = {"symbol": coin, "error": "empty_klines"}
            continue
        res = probe_coin(coin, df, trades, args)
        payload["results"][coin] = res
        print(
            f"[{coin}] 平仓={res['closed_in_window']} 重放={res['replayed']} "
            f"原因族一致率={res['family_match_rate']} "
            f"回测外离场={res['families_not_in_backtest']}"
        )

    out = (
        Path(args.out)
        if args.out
        else (PROJECT_ROOT / "data" / "eval" / f"parity_probe_{datetime.now():%Y%m%d}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[out] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
