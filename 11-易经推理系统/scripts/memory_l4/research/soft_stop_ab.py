"""P2-a 软止损对照回测（只读研究，不改生产参数）。

问题（来自 P1 §17）：生产 soft_stop_loss 用固定 5% 阈值（+1% 缓冲），
12 笔全亏、单笔 -5.31%，是同入场下 2ATR 止损（-2.90%）的 1.8 倍。

设计：
- 每币只训练一次（5 折 walk-forward，与 eval_1h_walkforward 同配置）；
- 用每折保存的 predictions 重放同一批信号，仅改止损规则，做到严格配对：
    atr2   = 默认 sl_atr=2.0（本回测器 ATR 近似为入场价 1.5%，即约 3% 止损）
    fixed5 = 固定 5%（生产软止损名义值）
    fixed6 = 固定 6%（生产 5% + 1% 缓冲的实际触发口径）
- 主指标（预注册）：合并 E（单笔期望）与 MDD；辅指标 WR/PF/逐折 E。
- 判定：固定止损显著更差 ⇔ 配对 ΔE 的 95% CI 上界 < 0，或 MDD 超过 ATR 臂 ×1.10。
  ≥2/3 币成立才建议评审后替换生产软止损；否则维持现状。

用法：
    python3 -u scripts/memory_l4/research/soft_stop_ab.py --coins BTC ETH SOL
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.bcrm2.eval_1h_walkforward import (  # noqa: E402
    bootstrap_ci,
    check_data,
    git_sha,
    load_klines,
    stats_from_trades,
)
from scripts.memory_l4.bcrm2.walk_forward_backtester import (  # noqa: E402
    WalkForwardBacktester,
)

ARMS = {"atr2": None, "fixed5": 0.05, "fixed6": 0.06}


def simulate_arm(bt, df, folds, fixed_pct):
    """同一批 predictions，仅切换止损规则；返回 (全部交易, 逐折交易)。"""
    bt.sl_fixed_pct = fixed_pct
    all_trades, per_fold = [], []
    for f in folds:
        trades = bt._simulate_trades(df, f.predictions, f.test_start, f.test_end, None)
        per_fold.append(trades)
        all_trades.extend(trades)
    return all_trades, per_fold


def paired_delta(arm_a, arm_b):
    """按 entry_bar 配对，返回 B−A 的逐笔差值与 95% CI（单位 %）。"""
    map_a = {t.entry_bar: t.pnl_pct for t in arm_a}
    map_b = {t.entry_bar: t.pnl_pct for t in arm_b}
    common = sorted(set(map_a) & set(map_b))
    if not common:
        return {"n_paired": 0, "mean_delta_pct": None, "ci95": [None, None]}
    deltas = [map_b[i] - map_a[i] for i in common]
    return {
        "n_paired": len(common),
        "coverage_vs_atr": round(len(common) / max(1, len(arm_a)), 4),
        "mean_delta_pct": round(sum(deltas) / len(deltas), 4),
        "ci95": bootstrap_ci(deltas),
        "share_worse": round(sum(1 for d in deltas if d < 0) / len(deltas), 4),
    }


def pure_stop_variants(df, model_trades, args, sl_pcts=(0.03, 0.05, 0.06)):
    """纯止损重放：只用模型入场（entry_bar/entry_price/direction），
    离场只保留 TP/SL/max_hold（无 trailing、无易经层），用于放大止损深度的功效。

    sl=0.03 对应本回测器 2ATR 近似（1.5%×2）。同根双触发保守取 SL。
    """
    h = df["high"].values
    l = df["low"].values  # noqa: E741
    c = df["close"].values
    n_bars = len(df)
    out = {}
    for sl_pct in sl_pcts:
        pnls, reasons = [], Counter()
        for t in model_trades:
            ei = int(t.entry_bar) + 1
            if ei >= n_bars - 1:
                continue
            entry = float(t.entry_price)
            if entry <= 0:
                continue
            sign = 1 if int(t.direction) == 1 else -1
            tp_dist = entry * 0.015 * args.tp_atr
            sl_dist = entry * sl_pct
            tp_price = entry + sign * tp_dist
            sl_price = entry - sign * sl_dist
            exit_price, reason = None, "time"
            last = min(ei + args.max_hold, n_bars - 1)
            for j in range(ei, last + 1):
                hit_sl = (l[j] <= sl_price) if sign == 1 else (h[j] >= sl_price)
                hit_tp = (h[j] >= tp_price) if sign == 1 else (l[j] <= tp_price)
                if hit_sl:
                    exit_price, reason = sl_price, "sl"
                    break
                if hit_tp:
                    exit_price, reason = tp_price, "tp"
                    break
            if exit_price is None:
                exit_price = float(c[last])
            fee = entry * args.fee + exit_price * args.fee
            slip = (entry + exit_price) * args.slippage
            pnl = (sign * (exit_price - entry) - fee - slip) / entry * 100
            pnls.append(pnl)
            reasons[reason] += 1

        class _T:
            def __init__(self, p):
                self.pnl_pct = p

        st = stats_from_trades([_T(p) for p in pnls], f"pure_sl{sl_pct:.0%}")
        st["exit_reasons"] = dict(reasons)
        st["sl_pct"] = sl_pct
        out[f"{sl_pct:.0%}"] = st
    # 配对：与 3%（≈2ATR）比较，同一入场序列、同一索引顺序
    base = out.get("3%")
    if base and base["n"]:
        for name, st in out.items():
            if name == "3%":
                continue
            st["delta_e_vs_3pct_pp"] = round(st["expectancy_pct"] - base["expectancy_pct"], 4)
            st["delta_mdd_vs_3pct_pp"] = round(st["max_drawdown_pct"] - base["max_drawdown_pct"], 4)
    return out


def run_coin(args, symbol, ref_cache) -> dict:
    df = load_klines(symbol, args.timeframe, args.max_bars, args.min_bars, False)
    data_info = check_data(df, symbol, args.min_bars)
    if not data_info["ok"]:
        return {"symbol": symbol, "error": data_info["reason"]}

    ref_df = None
    if symbol.upper() != "BTC":
        if ref_cache.get("BTC") is None:
            ref_cache["BTC"] = load_klines(
                "BTC", args.timeframe, args.max_bars, args.min_bars, False
            )
        ref_df = ref_cache["BTC"]
        if ref_df is not None and len(ref_df) > 200:
            ref_df = ref_df.reindex(df.index, method="ffill")
        else:
            ref_df = None

    bt = WalkForwardBacktester(
        symbol=symbol,
        n_folds=args.n_folds,
        train_ratio=args.train_ratio,
        min_train_bars=1000,
        min_test_bars=200,
        conf_threshold=args.conf,
        tp_atr=args.tp_atr,
        sl_atr=args.sl_atr,
        max_hold_bars=args.max_hold,
        fee_rate=args.fee,
        slippage_rate=args.slippage,
        feature_selection=True,
        macro_config=None,
    )
    bt.enable_pentagon = False
    bt._triangle_verifier = None

    t0 = time.time()
    result = bt.run(
        df,
        ref_df=ref_df,
        verbose=False,
        auto_mcap_config=False,
        enable_mcap=False,
        enable_merrill=False,
        enable_cycle=False,
    )
    train_sec = round(time.time() - t0, 1)
    print(f"[{symbol}] 训练+基线完成 {train_sec}s folds={len(result.folds)}", flush=True)

    arms, folds_out = {}, []
    for name, fixed in ARMS.items():
        trades, per_fold = simulate_arm(bt, df, result.folds, fixed)
        arms[name] = {
            "sl_fixed_pct": fixed,
            "exit_reasons": dict(Counter(t.exit_reason for t in trades)),
            "overall": stats_from_trades(trades, name),
            "folds": [stats_from_trades(ts, f"{name}_fold{k}") for k, ts in enumerate(per_fold)],
        }
        if name == "atr2":
            arms[name]["reproduce_baseline_n"] = len(result.all_trades)
            arms[name]["resim_n"] = len(trades)
        print(
            f"[{symbol}] {name}: N={arms[name]['overall']['n']} "
            f"WR={arms[name]['overall']['win_rate']:.2%} "
            f"E={arms[name]['overall']['expectancy_pct']}% "
            f"MDD={arms[name]['overall']['max_drawdown_pct']}%",
            flush=True,
        )

    # 逐折 E 列表（用于配对折比较）
    for k in range(len(result.folds)):
        folds_out.append(
            {
                "fold": k,
                **{
                    name: {
                        "n": arms[name]["folds"][k]["n"],
                        "e": arms[name]["folds"][k]["expectancy_pct"],
                        "mdd": arms[name]["folds"][k]["max_drawdown_pct"],
                    }
                    for name in ARMS
                },
            }
        )

    comparisons = {}
    atr_trades, _ = simulate_arm(bt, df, result.folds, None)
    atr_mdd = arms["atr2"]["overall"]["max_drawdown_pct"]
    for name in ("fixed5", "fixed6"):
        fixed_trades, _ = simulate_arm(bt, df, result.folds, ARMS[name])
        cmp = paired_delta(atr_trades, fixed_trades)
        fixed_mdd = arms[name]["overall"]["max_drawdown_pct"]
        ci_upper = cmp["ci95"][1]
        folds_worse = sum(1 for f in folds_out if f[name]["e"] < f["atr2"]["e"])
        cmp.update(
            {
                "delta_mdd_pp": round(fixed_mdd - atr_mdd, 4),
                "mdd_ratio": round(fixed_mdd / atr_mdd, 4) if atr_mdd > 0 else None,
                "folds_worse_than_atr": folds_worse,
                "n_folds": len(folds_out),
                "worse": bool(
                    (ci_upper is not None and ci_upper < 0)
                    or (atr_mdd > 0 and fixed_mdd > atr_mdd * 1.10)
                ),
            }
        )
        comparisons[name] = cmp

    # 纯止损重放：模型回测里 SL 几乎不绑定（多数 trailing/易经离场），
    # 用同一批入场但只保留 TP/SL/超时，获得止损深度的统计功效。
    pure = pure_stop_variants(df, atr_trades, args)
    for name, st in pure.items():
        print(
            f"[{symbol}] 纯止损 {name}: N={st['n']} WR={st['win_rate']:.2%} "
            f"E={st['expectancy_pct']}% MDD={st['max_drawdown_pct']}% {st['exit_reasons']}",
            flush=True,
        )

    return {
        "symbol": symbol,
        "data": {"hash": data_info.get("hash"), "bars": data_info.get("bars")},
        "train_sec": train_sec,
        "arms": arms,
        "folds": folds_out,
        "comparisons": comparisons,
        "pure_stop": pure,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--timeframe", default="1H")
    ap.add_argument("--max-bars", type=int, default=30000)
    ap.add_argument("--min-bars", type=int, default=12000)
    ap.add_argument("--n-folds", type=int, default=5)
    ap.add_argument("--train-ratio", type=float, default=0.7)
    ap.add_argument("--conf", type=float, default=0.4)
    ap.add_argument("--tp-atr", type=float, default=3.0)
    ap.add_argument("--sl-atr", type=float, default=2.0)
    ap.add_argument("--max-hold", type=int, default=60)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.001)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "arms": dict(ARMS),
        "design": "同一批 5 折 predictions 重放，仅改止损；配对按 entry_bar",
        "gates": "固定臂更差 ⇔ 配对ΔE 95%CI 上界<0 或 MDD>ATR×1.10；≥2/3 币成立才建议替换",
        "limitations": [
            "回测器 ATR 近似为入场价 1.5%，atr2 约等于 3% 固定止损，非真实 Wilder ATR",
            "固定臂覆盖五角止损收紧；生产软止损还受其他离场层影响",
            "单训练种子；E1 已显示种子噪声约 0.01–0.03 个百分点/笔",
        ],
        "results": {},
    }
    ref_cache = {}
    for coin in args.coins:
        try:
            payload["results"][coin] = run_coin(args, coin, ref_cache)
        except Exception as exc:
            payload["results"][coin] = {"symbol": coin, "error": str(exc)[:400]}
            print(f"[{coin}] 失败: {exc}", flush=True)

    worse5 = [
        c
        for c, r in payload["results"].items()
        if (r.get("comparisons", {}).get("fixed5", {}) or {}).get("worse")
    ]
    payload["summary"] = {
        "coins_fixed5_worse": worse5,
        "n_coins": len(payload["results"]),
        "recommendation": (
            "REVIEW_REPLACE_FIXED_SOFT_STOP"
            if len(worse5) >= 2
            else "INSUFFICIENT_EVIDENCE_KEEP_CURRENT"
        ),
    }
    out = (
        Path(args.out)
        if args.out
        else (PROJECT_ROOT / "data" / "eval" / f"soft_stop_ab_{datetime.now():%Y%m%d}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[summary] {payload['summary']}", flush=True)
    print(f"[out] {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
