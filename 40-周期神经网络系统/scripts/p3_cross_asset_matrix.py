#!/usr/bin/env python3
"""P1 跨类传导矩阵：G1 六大类龙头 vs BTC（asset_classes.G1_ANCHORS）。

数据源：OKX USDT 永续（ccxt defaultType=swap），symbol 形如 "XAU/USDT:USDT"。
计算每标的：
  - momentum_3m_pct   近 63 根日线动量
  - ma200 / above_ma200  200 日均线锚点
  - R(s) = {corr0, lag_profile, beta, down_corr}  相对 BTC 的共振
  - granger_f / granger_p  上游（BTC）对下游的增量预测力（G2 门禁输入）
产出 40/cross_asset_matrix.json。

对齐规则（已确认决策 EQUITY_ALIGNMENT="continuous_24h"）：
  - 优先按共同时间戳对齐；共同样本不足时退化为尾部对齐并标 degraded。
fail-open：
  - 单标的拉取失败 → 该标的记为 fetch_failed，不阻塞其他标的；
  - BTC 缺失 → 全部非 BTC 标的降级为恒等传导；
  - 脚本恒返回 0，避免中断 40 日更流水线。
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# DREAMBUDDY_ROOT 统一模块根路径（R-42-04/P1-03）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_40_ROOT = os.path.dirname(_SCRIPT_DIR)
_DREAMBUDDY_ROOT = os.environ.get("DREAMBUDDY_ROOT") or os.path.dirname(_40_ROOT)
OUT = Path(_DREAMBUDDY_ROOT) / "40-周期神经网络系统" / "cross_asset_matrix.json"

for _p in (_40_ROOT, _SCRIPT_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# G10：价格唯一来源（18 统一价格源，禁止本脚本直连交易所）
sys.path.insert(0, os.path.join(_DREAMBUDDY_ROOT, "18-数据获取中心"))
from asset_classes import (  # noqa: E402
    EQUITY_ALIGNMENT,
    G1_ANCHORS,
    GOLD_DUAL_TRACK,
    TLT_IN_G1,
)
from data_center.market import price_source  # noqa: E402
from p3_resonance_matrix import (  # noqa: E402
    GRANGER_ALPHA,
    GRANGER_LAGS,
    MIN_SAMPLES,
    compute_resonance,
    granger_test,
)

DAY_MS = 86400000
TOTAL_BARS = 240  # ≥ 200 才能算 MA200
MOMENTUM_WINDOW = 63
MA_WINDOW = 200


def fetch_daily_series(symbol, total=TOTAL_BARS, max_retries=3, base_delay=1.0, ex=None):
    """日线序列 (timestamps_ms, closes)（G10 统一价格源）。

    `ex` 参数保留仅为签名兼容：价格口径已收敛到 18 `price_source`（OKX 主源 + Binance fallback），
    禁止各脚本再自建 ccxt 连接。失败返回 (None, None) 由调用方 fail-open。
    """
    try:
        result = price_source.fetch_daily(symbol, days=total)
    except price_source.PriceSourceError as exc:
        print(f"  [fail] {symbol}: {exc}")
        return None, None
    return [bar["ts_ms"] for bar in result["bars"]], [float(bar["close"]) for bar in result["bars"]]


def to_ccxt_swap_symbol(inst_id: str) -> str:
    """OKX instId → ccxt swap symbol：XAU-USDT-SWAP → XAU/USDT:USDT。"""
    base = str(inst_id).removesuffix("-USDT-SWAP")
    return f"{base}/USDT:USDT"


def momentum_3m(closes, window=MOMENTUM_WINDOW):
    """近 window 根日线动量（%）；样本不足返回 None。"""
    if not closes or len(closes) < window:
        return None
    prev = closes[-window]
    if not prev:
        return None
    return round((closes[-1] / prev - 1) * 100, 2)


def ma200_info(closes, window=MA_WINDOW):
    """200 日均线与是否站上；样本不足返回 (None, None)。"""
    if not closes or len(closes) < window:
        return None, None
    ma = float(np.mean(closes[-window:]))
    return round(ma, 6), bool(closes[-1] > ma)


def align_pair(ts_a, closes_a, ts_b, closes_b, min_samples=MIN_SAMPLES):
    """按共同时间戳对齐两条序列；不足则尾部对齐并标注 degraded。

    Returns:
        (a_aligned, b_aligned, n, degraded)
    """
    if not ts_a or not ts_b or not closes_a or not closes_b:
        return [], [], 0, ["empty_series"]
    map_a = dict(zip(ts_a, closes_a, strict=True))
    map_b = dict(zip(ts_b, closes_b, strict=True))
    common = sorted(set(map_a) & set(map_b))
    if len(common) >= min_samples:
        return ([map_a[t] for t in common], [map_b[t] for t in common], len(common), [])
    n = min(len(closes_a), len(closes_b))
    return list(closes_a[-n:]), list(closes_b[-n:]), n, ["timestamp_misaligned_tail_aligned"]


def build_asset_entry(sym, cfg, series, btc_series):
    """构造单标的跨类矩阵条目（fail-open）。"""
    entry = {
        "class": cfg.get("class"),
        "inst_id": cfg.get("inst_id"),
        "session": cfg.get("session", EQUITY_ALIGNMENT),
        "last_close": None,
        "momentum_3m_pct": None,
        "ma200": None,
        "above_ma200": None,
        "n_samples": 0,
        "corr0": 1.0,
        "lag_profile": [1.0],
        "beta": 1.0,
        "down_corr": 1.0,
        "granger_f": None,
        "granger_p": None,
        "degraded": [],
    }

    ts, closes = series if series else (None, None)
    if not closes:
        entry["degraded"] = ["fetch_failed"]
        return entry

    entry["last_close"] = round(closes[-1], 6)
    entry["momentum_3m_pct"] = momentum_3m(closes)
    entry["ma200"], entry["above_ma200"] = ma200_info(closes)
    entry["n_samples"] = len(closes)

    if sym == "BTC":
        # 龙头恒等：R(BTC, BTC) = 1
        if len(closes) < MIN_SAMPLES:
            entry["degraded"].append("resonance_fallback")
        return entry

    btc_ts, btc_closes = btc_series if btc_series else (None, None)
    if not btc_closes:
        entry["degraded"].append("btc_anchor_missing")
        return entry

    a, b, n, deg = align_pair(btc_ts, btc_closes, ts, closes)
    entry["degraded"].extend(deg)
    if n < MIN_SAMPLES:
        entry["degraded"].append("resonance_fallback")
        return entry

    r = compute_resonance(a, b)
    for key in ("corr0", "lag_profile", "beta", "down_corr"):
        entry[key] = r[key]
    if r.get("degraded"):
        entry["degraded"].append(str(r["degraded"]))

    f_stat, p_val = granger_test(a, b, lags=GRANGER_LAGS)
    entry["granger_f"] = f_stat
    entry["granger_p"] = p_val
    return entry


def main():
    now = datetime.now(timezone.utc).isoformat()
    print(f"=== p3_cross_asset_matrix start {now} ===")

    series_map = {}

    for sym in G1_ANCHORS:
        cfg = G1_ANCHORS[sym]
        try:
            ts, closes = fetch_daily_series(to_ccxt_swap_symbol(cfg["inst_id"]))
        except Exception as exc:  # noqa: BLE001  fail-open：单标的失败不阻塞
            print(f"  {sym}: ERROR {exc}")
            ts, closes = None, None
        series_map[sym] = (ts, closes)
        if closes:
            print(f"  {sym:<6} {len(closes)} bars  last={closes[-1]:.6g}")
        else:
            print(f"  {sym:<6} fetch failed (skipped)")

    btc_series = series_map.get("BTC")
    assets = {}
    for sym, cfg in G1_ANCHORS.items():
        entry = build_asset_entry(sym, cfg, series_map.get(sym), btc_series)
        assets[sym] = entry
        print(
            f"  {sym:<6} cls={entry['class']:<15} mom={entry['momentum_3m_pct']} "
            f"ma200_above={entry['above_ma200']} corr0={entry['corr0']:.3f} "
            f"granger_p={entry['granger_p']} degraded={entry['degraded']}"
        )

    output = {
        "generated_at": now,
        "anchor": "BTC",
        "min_samples": MIN_SAMPLES,
        "granger_lags": GRANGER_LAGS,
        "granger_alpha": GRANGER_ALPHA,
        "alignment": EQUITY_ALIGNMENT,
        "gold_dual_track": GOLD_DUAL_TRACK,
        "tlt_in_g1": TLT_IN_G1,
        "assets": assets,
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"saved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
