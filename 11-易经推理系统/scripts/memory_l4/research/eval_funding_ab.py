"""E1 资金费率 A/B 对照（只读实验）。

A = 426ccb 基线口径；B = A + 4 个资金费率特征。
仅在本进程内包装 FeatureRegistry.compute_all / FeatureSelector.fit 注入与观测，
不修改生产代码、不写生产库、不重启服务。

用法：
    python3 scripts/memory_l4/research/eval_funding_ab.py --coins BTC ETH SOL
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # 11-易经推理系统
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.memory_l4.bcrm2.eval_1h_walkforward import (  # noqa: E402
    check_data,
    config_hash,
    git_sha,
    load_klines,
    stats_from_trades,
)
from scripts.memory_l4.bcrm2.feature_registry import FeatureRegistry  # noqa: E402
from scripts.memory_l4.bcrm2.feature_selector import FeatureSelector  # noqa: E402
from scripts.memory_l4.bcrm2.walk_forward_backtester import (  # noqa: E402
    WalkForwardBacktester,
)
from scripts.memory_l4.research.funding_rate_data import (  # noqa: E402
    DEFAULT_OUT_DIR,
    build_features,
    load_funding,
)

BASELINE_JSON = PROJECT_ROOT / "data" / "eval" / "walkforward_1h_20261122.json"
_ACTIVE_FUNDING: pd.DataFrame | None = None
_SELECTED_FUNDING: list[list[str]] = []

_ORIG_COMPUTE_ALL = FeatureRegistry.compute_all.__func__
_ORIG_SELECTOR_FIT = FeatureSelector.fit


def _patched_compute_all(cls, *args, **kwargs):
    feats, by_gua = _ORIG_COMPUTE_ALL(cls, *args, **kwargs)
    if _ACTIVE_FUNDING is not None:
        df = kwargs.get("df") if "df" in kwargs else (args[0] if args else None)
        if df is not None:
            injected = _ACTIVE_FUNDING.reindex(df.index).ffill()
            feats = pd.concat([feats, injected], axis=1)
            by_gua["funding_rate"] = list(injected.columns)
    return feats, by_gua


def _patched_selector_fit(self, X, y):
    out = _ORIG_SELECTOR_FIT(self, X, y)
    selected = list(getattr(self, "selected_features", []) or [])
    _SELECTED_FUNDING.append([c for c in selected if str(c).startswith("fr_")])
    return out


FeatureRegistry.compute_all = classmethod(_patched_compute_all)
FeatureSelector.fit = _patched_selector_fit


def _load_baseline() -> dict:
    if not BASELINE_JSON.exists():
        return {}
    return json.loads(BASELINE_JSON.read_text(encoding="utf-8"))


def _make_bt(args, symbol: str) -> WalkForwardBacktester:
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
    bt.enable_pentagon = False
    bt._triangle_verifier = None
    return bt


def _run_arm(args, symbol, df, ref_df, funding_feats, use_funding: bool):
    global _ACTIVE_FUNDING
    _ACTIVE_FUNDING = funding_feats if use_funding else None
    _SELECTED_FUNDING.clear()
    try:
        res = _make_bt(args, symbol).run(
            df,
            ref_df=ref_df,
            verbose=args.verbose,
            auto_mcap_config=False,
            enable_mcap=False,
            enable_merrill=False,
            enable_cycle=False,
        )
        selected = list(_SELECTED_FUNDING)
    finally:
        _ACTIVE_FUNDING = None
    return res, selected


def _arm_payload(result) -> dict:
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
    return {
        "primary": stats_from_trades(result.all_trades, "all"),
        "folds": folds,
        "trades": result.all_trades,
    }


def _block_bootstrap_delta(trades_a, trades_b, index, block_days=7, n_boot=2000, seed=42):
    """按自然日 7 天块重采样，返回 ΔE 的 95% CI 与单侧 p 值。"""
    if not trades_a or not trades_b:
        return {"delta_e": None, "ci95": [None, None], "p_one_sided": None, "blocks": 0}

    base = index[0].normalize()

    def _group(trades):
        out: dict[int, list[float]] = {}
        for t in trades:
            d = index[int(t.exit_bar)].normalize()
            b = int((d - base).days // block_days)
            out.setdefault(b, []).append(float(t.pnl_pct))
        return out

    ga, gb = _group(trades_a), _group(trades_b)
    block_ids = sorted(set(ga) | set(gb))
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_boot):
        pick = rng.choice(block_ids, size=len(block_ids), replace=True)
        pa = [p for b in pick for p in ga.get(int(b), [])]
        pb = [p for b in pick for p in gb.get(int(b), [])]
        if pa and pb:
            deltas.append(float(np.mean(pb) - np.mean(pa)))
    if not deltas:
        return {"delta_e": None, "ci95": [None, None], "p_one_sided": None, "blocks": 0}
    arr = np.asarray(deltas)
    p_one = float((1 + np.sum(arr <= 0)) / (len(arr) + 1))
    return {
        "delta_e": round(float(np.mean(arr)), 4),
        "ci95": [
            round(float(np.percentile(arr, 2.5)), 4),
            round(float(np.percentile(arr, 97.5)), 4),
        ],
        "p_one_sided": round(p_one, 6),
        "blocks": len(block_ids),
    }


def _holm(pvals: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    items = sorted(((k, p) for k, p in pvals.items() if p is not None), key=lambda x: x[1])
    out: dict[str, bool] = dict.fromkeys(pvals, False)
    m = len(items)
    still = True
    for i, (k, p) in enumerate(items):
        if still and p <= alpha / (m - i):
            out[k] = True
        else:
            still = False
    return out


def _truncate_to_baseline(df, baseline: dict, symbol: str, max_bars: int):
    end_str = (baseline.get("results", {}).get(symbol, {}) or {}).get("data", {}).get("end")
    if not end_str:
        return df, False
    end = pd.Timestamp(end_str)
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    truncated = df[df.index <= end.tz_convert(df.index.tz)]
    if len(truncated) < max_bars:
        return truncated, False
    return truncated.iloc[-max_bars:], True


def run_coin(args, symbol: str, ref_cache, baseline: dict) -> dict:
    df = load_klines(
        symbol,
        args.timeframe,
        args.max_bars + args.pad_bars,
        args.min_bars,
        args.force_refresh,
    )
    if df is None or len(df) == 0:
        return {"symbol": symbol, "error": "empty_klines"}

    df, exact = _truncate_to_baseline(df, baseline, symbol, args.max_bars)
    data_info = check_data(df, symbol, args.min_bars)
    if not data_info["ok"]:
        return {"symbol": symbol, "data": data_info, "error": data_info["reason"]}
    base_hash = (baseline.get("results", {}).get(symbol, {}) or {}).get("data", {}).get("hash")
    data_info["baseline_hash"] = base_hash
    data_info["baseline_comparable"] = bool(exact and base_hash == data_info["hash"])

    ref_df = None
    if symbol.upper() != "BTC":
        if ref_cache.get("BTC") is None:
            btc = load_klines(
                "BTC",
                args.timeframe,
                args.max_bars + args.pad_bars,
                args.min_bars,
                args.force_refresh,
            )
            btc, _ = _truncate_to_baseline(btc, baseline, "BTC", args.max_bars)
            ref_cache["BTC"] = btc
        ref_df = ref_cache["BTC"]
        if ref_df is not None and len(ref_df) > 200:
            ref_df = ref_df.reindex(df.index, method="ffill")

    funding_path = Path(args.funding_dir) / f"{symbol.upper()}_8h.csv"
    if not funding_path.exists():
        return {"symbol": symbol, "error": f"funding_missing:{funding_path}"}
    funding_feats, funding_diag = build_features(df.index, load_funding(funding_path))

    print(f"[{symbol}] A 基线臂 ...", flush=True)
    res_a, _ = _run_arm(args, symbol, df, ref_df, None, use_funding=False)
    arm_a = _arm_payload(res_a)

    print(f"[{symbol}] B 资金费率臂 ...", flush=True)
    res_b, selected = _run_arm(args, symbol, df, ref_df, funding_feats, use_funding=True)
    arm_b = _arm_payload(res_b)

    boot = _block_bootstrap_delta(arm_a["trades"], arm_b["trades"], df.index)
    pa, pb = arm_a["primary"], arm_b["primary"]
    d_e = round(pb["expectancy_pct"] - pa["expectancy_pct"], 4)
    folds_pos = sum(
        1
        for fa, fb in zip(arm_a["folds"], arm_b["folds"], strict=False)
        if fb["expectancy_pct"] > fa["expectancy_pct"]
    )
    mdd_ratio = (
        round(pb["max_drawdown_pct"] / pa["max_drawdown_pct"], 4)
        if pa["max_drawdown_pct"] > 0
        else None
    )
    pf_delta = round(pb["profit_factor"] - pa["profit_factor"], 4)

    g1 = pa["n"] >= 150 and pb["n"] >= 150
    g2 = d_e > 0 and boot["ci95"][0] is not None and boot["ci95"][0] > 0
    g3 = folds_pos >= 4
    g4 = (mdd_ratio is None or mdd_ratio <= 1.10) and pf_delta >= -0.05
    if not g1:
        verdict = "INSUFFICIENT"
    elif g2 and g3 and g4:
        verdict = "IMPROVED"
    elif d_e <= 0 or (boot["ci95"][0] is not None and boot["ci95"][0] <= 0):
        verdict = "NO_GAIN"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "symbol": symbol,
        "data": data_info,
        "funding": {
            "path": str(funding_path),
            **funding_diag,
            "features": list(funding_feats.columns),
        },
        "A": {"primary": pa, "folds": arm_a["folds"]},
        "B": {"primary": pb, "folds": arm_b["folds"]},
        "B_selected_funding_by_fold": selected,
        "delta": {
            "delta_e": d_e,
            "bootstrap": boot,
            "folds_positive": folds_pos,
            "mdd_ratio": mdd_ratio,
            "pf_delta": pf_delta,
            "gates": {"G1": g1, "G2": g2, "G3": g3, "G4": g4},
            "verdict": verdict,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", nargs="+", default=["BTC", "ETH", "SOL"])
    ap.add_argument("--timeframe", default="1H")
    ap.add_argument("--max-bars", type=int, default=30000)
    ap.add_argument("--pad-bars", type=int, default=600)
    ap.add_argument("--min-bars", type=int, default=12000)
    ap.add_argument("--n-folds", type=int, default=5)
    ap.add_argument("--train-ratio", type=float, default=0.7)
    ap.add_argument("--min-train-bars", type=int, default=1000)
    ap.add_argument("--min-test-bars", type=int, default=200)
    ap.add_argument("--conf", type=float, default=0.40)
    ap.add_argument("--tp-atr", type=float, default=3.0)
    ap.add_argument("--sl-atr", type=float, default=2.0)
    ap.add_argument("--max-hold", type=int, default=60)
    ap.add_argument("--fee", type=float, default=0.0005)
    ap.add_argument("--slippage", type=float, default=0.001)
    ap.add_argument("--no-feature-selection", action="store_true")
    ap.add_argument("--no-macro", action="store_true")
    ap.add_argument("--force-refresh", action="store_true")
    ap.add_argument("--funding-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cfg = {
        "experiment": "E1_funding_rate_ab",
        "coins": args.coins,
        "timeframe": args.timeframe,
        "max_bars": args.max_bars,
        "n_folds": args.n_folds,
        "train_ratio": args.train_ratio,
        "conf": args.conf,
        "tp_atr": args.tp_atr,
        "sl_atr": args.sl_atr,
        "max_hold": args.max_hold,
        "fee": args.fee,
        "slippage": args.slippage,
        "feature_selection": not args.no_feature_selection,
        "macro": not args.no_macro,
        "features_B": ["fr_bps", "fr_z90", "fr_cum7d_bps", "fr_hours_since"],
        "baseline": "walkforward_1h_20261122.json@426ccb0b",
    }

    baseline = _load_baseline()
    print("=" * 72)
    print("  E1 资金费率 A/B 对照（只读）")
    print(f"  coins={args.coins} folds={args.n_folds} conf={args.conf}")
    print("=" * 72)

    ref_cache = {}
    results = {}
    for coin in args.coins:
        try:
            results[coin] = run_coin(args, coin, ref_cache, baseline)
        except Exception as exc:  # noqa: BLE001 单币失败不阻断
            import traceback

            traceback.print_exc()
            results[coin] = {"symbol": coin, "error": f"{type(exc).__name__}: {exc}"}
        r = results[coin]
        if "error" in r:
            print(f"[{coin}] 失败: {r['error']}", flush=True)
        else:
            print(
                f"[{coin}] A E={r['A']['primary']['expectancy_pct']:+.4f}% "
                f"B E={r['B']['primary']['expectancy_pct']:+.4f}% "
                f"ΔE={r['delta']['delta_e']:+.4f} CI={r['delta']['bootstrap']['ci95']} "
                f"→ {r['delta']['verdict']}",
                flush=True,
            )

    pvals = {
        c: r.get("delta", {}).get("bootstrap", {}).get("p_one_sided")
        for c, r in results.items()
        if "delta" in r
    }
    holm = _holm(pvals)
    improved = sum(1 for c, r in results.items() if r.get("delta", {}).get("verdict") == "IMPROVED")
    overall = (
        "INVALID"
        if any("error" in r for r in results.values())
        else ("SUPPORTED" if improved >= 2 else "NOT_SUPPORTED")
    )

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": git_sha(),
        "config": cfg,
        "config_hash": config_hash(cfg),
        "results": results,
        "holm_significant": holm,
        "summary": {
            "per_coin": {c: r.get("delta", {}).get("verdict", "ERROR") for c, r in results.items()},
            "improved_coins": improved,
            "overall": overall,
        },
    }

    out = (
        Path(args.out)
        if args.out
        else (PROJECT_ROOT / "data" / "eval" / f"funding_ab_{datetime.now():%Y%m%d}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[out] {out}")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
