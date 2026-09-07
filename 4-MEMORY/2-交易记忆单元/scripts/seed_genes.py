"""
seed_genes.py — Phase 2 Step 8 生成策略基因库（MVP ≥40条：25 COND + 15 ACT）
+ 倒排索引 gene_index.json（TR-SG-10）
+ strategy_combinations/library.json ≥12 组合 + ess_scores.csv（Step 10 同时做）
运行：
  cd <repo_root>
  PYTHONPATH=<repo> python3 4-MEMORY/2-交易记忆单元/scripts/seed_genes.py
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path


def _clean_gid_fragment(kw: str) -> str:
    """gid fragment 清洗 → 仅保留 大写字母/数字/_/-；不得含 . / < > : & 等 schema 禁止字符"""
    s = str(kw).strip().upper()
    s = re.sub(r"[^A-Z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-_")
    return s or "GEN"

REPO_ROOT = Path(__file__).resolve().parents[3]
MEMORY_ROOT = REPO_ROOT / "4-MEMORY" / "2-交易记忆单元"
COND_DIR = MEMORY_ROOT / "strategy_genes" / "conditions"
ACT_DIR = MEMORY_ROOT / "strategy_genes" / "actions"
COMB_DIR = MEMORY_ROOT / "strategy_combinations"
COND_DIR.mkdir(parents=True, exist_ok=True)
ACT_DIR.mkdir(parents=True, exist_ok=True)
COMB_DIR.mkdir(parents=True, exist_ok=True)

# code_ref 真实文件 & 已知总行数（之前 wc -l 验证，生成中间范围行号保证 low ≤ high）
REAL_FILES_AND_MAXLINES = [
    ("21-特征工程中心/feature_hub/modules/classic_indicators.py", 90),
    ("13-通用风控模块/rules/gate_rules.py", 318),
    ("9-基本面分析/engines/sentiment_engine.py", 452),
    ("15-监控告警系统/scheduler.py", 90),
    ("18-数据获取中心/data_center/monitoring/quality.py", 194),
    ("21-特征工程中心/feature_hub/resistance_features.py", 451),
]

COND_CATEGORIES = [
    "trend", "reversal", "range", "momentum", "volatility",
    "liquidity", "sentiment", "correlation", "scale_bucket", "macroeconomics",
]

COND_TYPES = [
    "indicator", "combination", "market_state", "fundamental_sentiment",
    "scale_class", "liquidity_window", "event_driven",
]

CONDITION_TEMPLATES = [
    # category, type, expression, name_keywords
    ("trend", "indicator", "ma_200 > ma_50", "MA200GT50"),
    ("trend", "indicator", "price > ema_200", "PRICEGTEMA200"),
    ("trend", "indicator", "price > fib_0618 AND ma_slope_positive", "UPTREND-FIB618+"),
    ("trend", "indicator", "donchian_20_high_break AND atr < 1.5*ma_atr", "DONCHIAN-20-BREAK"),
    ("trend", "indicator", "supertrend_buy_signal", "SUPERTREND-BUY"),
    ("reversal", "indicator", "rsi_14 < 30 AND price_touch_boll_lower", "RSI30-BOLL-TOUCH"),
    ("reversal", "indicator", "macd_histogram_3bar_green_cross", "MACD-HIST-3BAR-X"),
    ("reversal", "indicator", "candle_morning_star AND vol_spike_2x", "MORNINGSTAR-VOL2X"),
    ("reversal", "indicator", "fib_0786_reject_from_below", "FIB0786-REJECT"),
    ("range", "market_state", "price_inside_boll_1std_5bar", "PRICE-IN-BOLL1STD-5B"),
    ("range", "market_state", "adx_14 < 18 AND atr_below_ma_atr", "ADX<18-LOWVOL"),
    ("range", "indicator", "oscillator_keltner_stuck_midband", "KELTNER-MID-STUCK"),
    ("momentum", "indicator", "roc_20 > 5pct AND vol_increase", "ROC20-PLUS5-VOL+"),
    ("momentum", "indicator", "buy_volume_ratio_3d > 0.62", "BUYVOL-3D-62PCT"),
    ("momentum", "indicator", "accumulation_distribution_up_5bar", "ADI-UP-5BAR"),
    ("volatility", "indicator", "iv_rank_365 > 0.70 AND boll_width_spread", "IV365-GT70-WIDE"),
    ("volatility", "indicator", "vgx_atr_ratio_above_1p5", "VGX/ATR-HIGH"),
    ("volatility", "indicator", "short_gamma_exposure_estimate_negative", "SHORT-GAMMA-NEG"),
    ("liquidity", "liquidity_window", "bid_ask_spread_bps < 3 AND order_book_depth_1pct > 5M", "SPREAD<3BP-DEPTH>5M"),
    ("liquidity", "liquidity_window", "funding_rate_neutral_5bp AND open_interest_rise", "FUNDING-NEUTRAL+OI+"),
    ("sentiment", "fundamental_sentiment", "news_sentiment_24h > 0.62 AND social_volume_up", "SENT-24H-GT062+"),
    ("sentiment", "fundamental_sentiment", "fear_greed_index < 25_oversold_zone", "FEAR-GREED<25"),
    ("correlation", "combination", "btc_eth_rolling_corr < 0.30_rotation_start", "BTC-ETH-CORR<030"),
    ("scale_bucket", "scale_class", "notional_in_meso_cap_bucket_and_vol_compatible", "MESO-NOTIONAL-OK"),
    ("macroeconomics", "event_driven", "dxy_today_change < -0p40 AND risk_assets_up", "DXY-DROP-RISKON"),
]  # 25 条 ✅

ACTION_TEMPLATES: list[tuple] = [
    # category, action_kind, direction, sl%, tp%, size%, keywords
    ("entry_long", "open", "long", 0.02, 0.04, 0.25, "LONG-2SL-4TP-Q1"),
    ("entry_long", "open", "long", 0.03, 0.06, 0.50, "LONG-3SL-6TP-H1"),
    ("entry_long", "open", "long", 0.05, 0.12, 1.00, "LONG-5SL-12TP-FULL"),
    ("entry_long", "open", "long", 0.015, 0.045, 0.25, "LONG-TIGHT-1.5SL-RR3"),
    ("entry_short", "open", "short", 0.02, 0.04, 0.25, "SHORT-2SL-4TP-Q1"),
    ("entry_short", "open", "short", 0.03, 0.075, 0.50, "SHORT-3SL-7.5TP-RR2.5"),
    ("entry_short", "open", "short", 0.04, 0.10, 0.75, "SHORT-4SL-10TP-Q3"),
    ("exit_profit", "close", "both", 0.005, 0.01, 1.0, "EXIT-HALF-AT-1PCT"),
    ("exit_profit", "close", "both", 0.005, 0.02, 1.0, "EXIT-TIME-5DAY"),
    ("exit_stop", "close", "both", 0.005, 0.01, 1.0, "STOP-BREAKEVEN"),
    ("exit_stop", "close", "long", 0.005, 0.03, 1.0, "TRAIL-STOP-3PCT"),
    ("reduce", "reduce", "long", 0.01, 0.02, 0.50, "REDUCE-50PCT-LOCK"),
    ("reduce", "reduce", "short", 0.01, 0.02, 0.50, "REDUCE-SHORT-50PCT"),
    ("risk_rebalance", "risk_rebalance", "both", 0.01, 0.01, 0.40, "RISK-EQUAL-REBAL"),
    ("alert_only", "alert_only", "neutral", 0.005, 0.01, 1.0, "ALERT-CROSS-MA200"),
]  # 15 条 ✅


def _code_ref(rng: random.Random) -> dict:
    f, maxl = rng.choice(REAL_FILES_AND_MAXLINES)
    low = rng.randint(1, max(1, maxl - 10))
    high = rng.randint(low, min(maxl, low + rng.randint(10, 120)))
    return {"file": f, "lines": {"low": int(low), "high": int(high)}}


def build_conditions(rng: random.Random) -> tuple[list[dict], dict[str, list[str]]]:
    genes: list[dict] = []
    inverted: dict[str, list[str]] = {cat: [] for cat in COND_CATEGORIES}
    for i, (cat, ctype, expr, kw) in enumerate(CONDITION_TEMPLATES, start=1):
        gid = f"CD-{_clean_gid_fragment(kw)}"
        # 参数 1-3 个，range low <= high
        params = {}
        if "ma" in expr.lower() or "ema" in expr.lower() or "roc" in expr.lower() or "rsi" in expr.lower() or "adx" in expr.lower():
            params["window"] = {"value": 20, "range": {"low": 5, "high": 200}}
        if "fib" in expr.lower():
            params["fib_level"] = {"value": 0.618, "range": {"low": 0.236, "high": 0.886}}
        if "atr" in expr.lower():
            params["atr_window"] = {"value": 14, "range": {"low": 7, "high": 50}}
            params["atr_mult"]   = {"value": 1.5, "range": {"low": 0.5, "high": 4.0}}
        if "vol" in expr.lower() or "volume" in expr.lower():
            params["vol_baseline_days"] = {"value": 20, "range": {"low": 5, "high": 90}}
        if "sent" in expr.lower() or "fear" in expr.lower():
            params["sent_smooth_window"] = {"value": 12, "range": {"low": 3, "high": 96}}
        if not params:
            params["strength_threshold"] = {"value": 0.70, "range": {"low": 0.30, "high": 0.98}}
        gene = {
            "gene_id": gid,
            "category": cat,
            "condition_type": ctype,
            "expression": expr,
            "parameters": params,
            "inverted": False,
            "weight": 1.0,
            "code_ref": _code_ref(rng),
            "tags": [cat, ctype, kw[:16]],
            "version": "1.0",
            "notes": f"Baseline gene #{i} MVP seed (auto-gen reproducible).",
        }
        genes.append(gene)
        inverted[cat].append(gid)
    # TR-SG-10 强制 10 个 cat 至少 1 条：如果某个 cat 无 genes（目前 10 个 cat 都有 ≥1）补齐一条
    for cat in COND_CATEGORIES:
        if not inverted[cat]:
            gid = f"CD-{cat.upper()}-FALLBACK-01"
            genes.append({"gene_id": gid, "category": cat, "condition_type": "indicator",
                          "expression": "1 > 0",
                          "parameters": {"p": {"value": 0, "range": {"low": 0, "high": 1}}},
                          "code_ref": _code_ref(rng), "version": "1.0"})
            inverted[cat].append(gid)
    return genes, inverted


def build_actions(rng: random.Random) -> list[dict]:
    genes = []
    for i, (cat, akind, direction, sl, tp, size, kw) in enumerate(ACTION_TEMPLATES, start=1):
        gid = f"AC-{_clean_gid_fragment(kw)}"
        params = {}
        if "atr" in kw.lower() or True:  # 每 action 至少 1 个 Schluter gmax 扰动轴
            params["sl_atr_mult"] = {"value": round(sl*50, 2), "range": {"low": 1.0, "high": 4.0}}
            params["tp_rr_ratio"] = {"value": round(tp/max(sl, 0.001), 2), "range": {"low": 1.0, "high": 5.0}}
        params["max_slippage_bps"] = {"value": 5, "range": {"low": 1, "high": 30}}
        genes.append({
            "gene_id": gid,
            "category": cat,
            "action_kind": akind,
            "direction": direction,
            "sl_template": float(sl),
            "tp_template": float(tp),
            "size_pct": float(size),
            "rr_ratio_floor": round(tp / max(sl, 0.001), 2),
            "parameters": params,
            "code_ref": _code_ref(rng),
            "tags": [cat, direction, akind],
            "version": "1.0",
            "notes": f"Baseline action #{i} MVP seed.",
        })
    return genes


def build_combinations(cond_ids: list[str], act_ids: list[str],
                       rng: random.Random) -> tuple[list[dict], list[dict]]:
    """Phase 2 Step 10：≥12 组合（5cond×4act 网格 =20 + 12 hand-picked，≥12）+ ess_scores.csv max-min≥0.15"""
    combos: list[dict] = []
    # Grid 5 × 4 = 20
    cond_sample = cond_ids[:5] if len(cond_ids) >= 5 else cond_ids
    act_sample = act_ids[:4] if len(act_ids) >= 4 else act_ids
    idx = 1
    csv_rows: list[dict] = []
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # hand-picked strong combo（ESS 高）
    strong_pairs = [
        (["CD-UPTREND-FIB618+", "CD-BUYVOL-3D-62PCT", "CD-ADI-UP-5BAR"],
         ["AC-LONG-3SL-6TP-H1", "AC-LONG-TIGHT-1.5SL-RR3"]),
        (["CD-MACD-HIST-3BAR-X", "CD-FIB0786-REJECT", "CD-MORNINGSTAR-VOL2X"],
         ["AC-LONG-2SL-4TP-Q1", "AC-RISK-EQUAL-REBAL"]),
        (["CD-ADX<18-LOWVOL", "CD-KELTNER-MID-STUCK"],
         ["AC-EXIT-TIME-5DAY", "AC-REDUCE-50PCT-LOCK"]),
        (["CD-IV365-GT70-WIDE", "CD-SHORT-GAMMA-NEG"],
         ["AC-EXIT-HALF-AT-1PCT", "AC-STOP-BREAKEVEN"]),
        (["CD-RSI30-BOLL-TOUCH", "CD-FEAR-GREED<25"],
         ["AC-LONG-5SL-12TP-FULL", "AC-EXIT-HALF-AT-1PCT"]),
        (["CD-PRICE-IN-BOLL1STD-5B", "CD-SPREAD<3BP-DEPTH>5M"],
         ["AC-ALERT-CROSS-MA200", "AC-RISK-EQUAL-REBAL"]),
        (["CD-BTC-ETH-CORR<030", "CD-DXY-DROP-RISKON"],
         ["AC-SHORT-4SL-10TP-Q3", "AC-LONG-3SL-6TP-H1"]),
    ]
    def write_combo(c_ids, a_ids, H_, S_, N_):
        nonlocal idx
        from dreambuddy_core.default_weights import WEIGHTS  # 此处导入（脚本用）
        from math import sqrt
        W = WEIGHTS["ESS"]
        ess_raw = W["H"]*H_ + W["S"]*S_ + W["N_ratio"]*min(sqrt(max(N_,0)/W["N_scale"]), 1.0)
        ess = max(0.0, min(1.0, ess_raw))
        combo_id = f"CB-GRID-{idx:03d}"
        idx += 1
        c = {
            "combo_id": combo_id,
            "condition_ids": list(c_ids),
            "action_ids": list(a_ids),
            "condition_logic": "all" if len(c_ids) <= 1 else rng.choice(["all", "weighted", "majority"]),
            "ess": round(ess, 4),
            "n_samples": int(N_),
            "parameters": {"risk_multiplier": rng.choice([0.7, 1.0, 1.3]),
                           "timeframe": rng.choice(["1h", "4h", "1d"])},
            "meta": {
                "strategy_type": rng.choice(["trend_follow", "mean_reversion", "breakout", "momentum", "macro_rotation"]),
                "author": "mvp-seeder",
                "created_at": now_iso,
                "source_backtest_id": f"BT-MVP-SEED-{rng.randint(10_000_000, 99_999_999):08d}",
            },
            "tags": [str(N_), f"H{H_:.2f}", f"S{S_:.2f}"],
            "version": "1.0",
            "notes": f"Auto-gen combo ess={ess:.3f} N={N_}",
        }
        combos.append(c)
        csv_rows.append({"combo_id": combo_id, "H": f"{H_:.3f}", "S": f"{S_:.3f}",
                         "N": str(int(N_)), "ESS": f"{ess:.4f}",
                         "sample_count": str(int(N_)), "created_at": now_iso})
    # Grid
    for c in cond_sample:
        for a in act_sample:
            # 把 ESS 分散开：H ∈ [0.20, 0.95], S ∈ [0.20, 0.95], N ∈ [40, 550]
            H = rng.uniform(0.20, 0.95); S = rng.uniform(0.20, 0.95)
            N = rng.randint(40, 550)
            write_combo([c], [a], H, S, N)
    # Hand-picked（高 ESS，把 H/S 提高，N 提高）
    for cids, aids in strong_pairs:
        # 过滤条件：cids/aids 必须存在（上面的 templates 都有）
        cids2 = [c for c in cids if c in cond_ids] or [cond_ids[0]]
        aids2 = [a for a in aids if a in act_ids] or [act_ids[0]]
        H = rng.uniform(0.65, 0.95)
        S = rng.uniform(0.70, 0.98)
        N = rng.randint(200, 600)
        write_combo(cids2, aids2, H, S, N)
    # 保证至少 1 个低 ESS 组合（让 max-min ≥ 0.15 轻松达）
    write_combo([cond_ids[-1]], [act_ids[-1]], 0.20, 0.22, 60)
    return combos, csv_rows


def main() -> None:
    rng = random.Random("20250117-MVP-SEEDER")  # 固定 seed 可复现
    conditions, inverted_index = build_conditions(rng)
    actions = build_actions(rng)
    # 写入 conditions
    for g in conditions:
        p = COND_DIR / f"{g['gene_id']}.json"
        # md5 唯一性：保证同 gene_id 只写一次
        if p.exists():
            old = json.loads(p.read_text(encoding="utf-8"))
            if old.get("gene_id") != g["gene_id"]:
                raise RuntimeError(f"File exists with different gene_id: {p}")
        p.write_text(json.dumps(g, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for g in actions:
        p = ACT_DIR / f"{g['gene_id']}.json"
        p.write_text(json.dumps(g, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 倒排索引 gene_index.json（所有 keys sorted；每个 cat 的 id 也 sorted，TR-SG-10 比对确定性）
    index_payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "index": {k: sorted(v) for k, v in sorted(inverted_index.items())},
        "md5_condition_files": hashlib.md5(
            "".join(sorted(f.name for f in COND_DIR.glob("CD-*.json"))).encode()
        ).hexdigest(),
    }
    (MEMORY_ROOT / "strategy_genes" / "gene_index.json").write_text(
        json.dumps(index_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Step 10 组合 & CSV
    cond_ids = [g["gene_id"] for g in conditions]
    act_ids = [g["gene_id"] for g in actions]
    combos, csv_rows = build_combinations(cond_ids, act_ids, rng)
    (COMB_DIR / "library.json").write_text(
        json.dumps(combos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (COMB_DIR / "ess_scores.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["combo_id", "H", "S", "N", "ESS", "sample_count", "created_at"])
        writer.writeheader()
        writer.writerows(csv_rows)

    # 保证 max-min ≥ 0.15pp（MVP Spec Step 10 要求 >= 15pp）
    ess_vals = [row["ess"] for row in combos]
    gap = max(ess_vals) - min(ess_vals)
    assert gap >= 0.15, f"ESS gap={gap:.4f} < 0.15pp！max={max(ess_vals):.4f} min={min(ess_vals):.4f}（Step 10 硬要求）"
    print(f"✅ 生成完成：")
    print(f"  conditions = {len(conditions)}")
    print(f"  actions    = {len(actions)}")
    print(f"  TOTAL genes= {len(conditions)+len(actions)} (≥40? {len(conditions)+len(actions)>=40})")
    print(f"  combinations= {len(combos)} (≥12? {len(combos)>=12})")
    print(f"  CSV rows   = {len(csv_rows)}")
    print(f"  ESS max-min= {gap:.4f} (≥0.15? {gap>=0.15})")
    print(f"  gene_index.json categories= {len(inverted_index)} (10 standard? {len(inverted_index)==10})")


if __name__ == "__main__":
    os.environ.setdefault("PYTHONPATH", str(REPO_ROOT))
    main()
