#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FiveDomainSqliteReader — 从数据中心 SQLite 读已落库的五维数据。

持续采集调度器（CollectionScheduler）已把 FRED/VIX/链上等数据落库 records 表。
本 reader 直接读 SQLite，避免战略层每次日级重算都实时打外部 API。

输出 dict 对齐 PollingTrader._try_fetch_macro_proxies() 返回结构：
  vix_close, fedfunds_rate, m2_index_bln, m2_yoy_pct, fed_balance_sheet_trillion,
  us_cpi_yoy_pct, us_ppi_yoy_pct, us_indpro_yoy_pct,
  defi_tvl_bln, stablecoin_mcap_bln, gas_eth_gwei,
  policy_sentiment_score, merrill_phase, liquidity_score, atr_percentile_proxy,
  stablecoin_change_rate

衍生计算（merrill_phase / liquidity_score / atr_percentile_proxy）复用
FiveDomainFetcher 的 staticmethod，保证与实时采集路径语义一致。
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import Any, Dict, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DATA_CENTER_ROOT = os.path.join(_REPO, "18-数据获取中心")
DEFAULT_DB_PATH = os.path.join(_DATA_CENTER_ROOT, "data_center.db")


def _safe_json(text: Any) -> dict:
    if not isinstance(text, str):
        return {} if not isinstance(text, dict) else text
    try:
        v = json.loads(text)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def _compute_merrill(cpi: Any, indpro: Any) -> Optional[str]:
    """美林时钟 4 象限（与 FiveDomainFetcher._compute_merrill 语义一致）。"""
    if not isinstance(cpi, (int, float)) or not isinstance(indpro, (int, float)):
        return None
    infl_up = cpi >= 250.0
    grow_up = indpro >= 100.0
    if grow_up and not infl_up:
        return "RECOVERY"
    if grow_up and infl_up:
        return "OVERHEAT"
    if not grow_up and infl_up:
        return "STAGFLATION"
    return "REFLATION"


def _compute_liquidity_score(fedfunds: Any, m2_yoy: Any, bs_trillion: Any) -> Optional[float]:
    """流动性评分 [0,1]（与 FiveDomainFetcher._compute_liquidity_score 语义一致）。"""
    scores = []
    if isinstance(fedfunds, (int, float)):
        scores.append(max(0.0, min(1.0, (6.0 - float(fedfunds)) / 6.0)))
    if isinstance(m2_yoy, (int, float)):
        scores.append(max(0.0, min(1.0, (float(m2_yoy) + 5.0) / 15.0)))
    if isinstance(bs_trillion, (int, float)):
        scores.append(max(0.0, min(1.0, (float(bs_trillion) - 4.0) / 5.0)))
    if not scores:
        return None
    if len(scores) == 1:
        return float(scores[0])
    if len(scores) == 2:
        return float(0.5 * scores[0] + 0.5 * scores[1])
    return float(0.5 * scores[0] + 0.25 * scores[1] + 0.25 * scores[2])


def read_macro_from_sqlite(db_path: str = DEFAULT_DB_PATH) -> dict:
    """从 SQLite 读已落库五维数据，组装成 _try_fetch_macro_proxies 期望的 dict。

    任何异常均 fail-open 返回部分 dict（缺失键由调用方 .get(key) 兜底）。
    若 SQLite 缺失或无数据，返回空 dict。
    """
    result: Dict[str, Any] = {}
    if not db_path or not os.path.exists(db_path):
        return result

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        # 一次性拉取五维所需各源最新记录（按 id 倒序，逐 (source,sub_category) 取首条=最新）
        rows = conn.execute(
            "SELECT source, sub_category, metrics, raw, timestamp "
            "FROM records WHERE source IN "
            "('fred','yfinance','ccxt','defillama','etherscan','tavily') "
            "ORDER BY id DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return result

    # 按 (source, sub_category) 去重保留最新
    latest: Dict[tuple, sqlite3.Row] = {}
    for r in rows:
        key = (r["source"], r["sub_category"])
        if key not in latest:
            latest[key] = r
    if not latest:
        # 无任何已落库记录 → 返回空 dict（调用方据此 fallback 实时采集）
        return result

    def _metric(src: str, sub: str) -> dict:
        rec = latest.get((src, sub))
        return _safe_json(rec["metrics"]) if rec else {}

    def _raw(src: str, sub: str) -> dict:
        rec = latest.get((src, sub))
        return _safe_json(rec["raw"]) if rec else {}

    # ── D1~D6: FRED 6 系列 ──
    result["fedfunds_rate"] = _metric("fred", "FEDFUNDS").get("value")
    m2_val = _metric("fred", "M2NS").get("value")
    result["m2_index_bln"] = m2_val
    result["m2_yoy_pct"] = None  # M2NS 为绝对值，同比需历史对比，暂留空（与 Fetcher 一致）
    walcl = _metric("fred", "WALCL").get("value")
    result["fed_balance_sheet_trillion"] = (
        round(float(walcl) / 1e12, 4) if isinstance(walcl, (int, float)) else None
    )
    result["us_cpi_yoy_pct"] = _metric("fred", "CPIAUCSL").get("value")
    result["us_ppi_yoy_pct"] = _metric("fred", "PPIACO").get("value")
    result["us_indpro_yoy_pct"] = _metric("fred", "INDPRO").get("value")

    # ── T2: VIX（yfinance）──
    vix_m = _metric("yfinance", "^VIX")
    result["vix_close"] = vix_m.get("price") or vix_m.get("value")

    # ── D8 DeFi TVL + D7 稳定币 proxy（defillama chains_summary）──
    dl_m = _metric("defillama", "chains_summary")
    result["defi_tvl_bln"] = dl_m.get("total_tvl_bln")
    dl_raw = _raw("defillama", "chains_summary")
    chains_map = dl_raw.get("chains", {}) if isinstance(dl_raw, dict) else {}
    if not chains_map:
        # defillama 无落库数据 → 稳定币 proxy 也置 None（与 defi_tvl 一致）
        result["stablecoin_mcap_bln"] = None
    else:
        try:
            eth_tvl = chains_map.get("Ethereum", {}).get("tvl_bln", 0.0) or 0.0
            tron_tvl = chains_map.get("TRON", {}).get("tvl_bln", 0.0) or 0.0
            result["stablecoin_mcap_bln"] = round(float(eth_tvl) + float(tron_tvl), 4)
        except Exception:
            result["stablecoin_mcap_bln"] = None

    # ── D9 ETH Gas（etherscan，需 API key，当前可能缺）──
    result["gas_eth_gwei"] = _metric("etherscan", "gas").get("propose_gas")

    # ── D10 政策情绪（tavily，需 API key，当前可能缺）──
    result["policy_sentiment_score"] = None

    # ── 衍生：美林时钟 / 流动性评分 / VIX→ATR 分位 ──
    # 内联实现（与 FiveDomainFetcher staticmethod 语义一致），避免跨模块 import 依赖
    result["merrill_phase"] = _compute_merrill(
        result.get("us_cpi_yoy_pct"), result.get("us_indpro_yoy_pct")
    )
    result["liquidity_score"] = _compute_liquidity_score(
        result.get("fedfunds_rate"),
        result.get("m2_yoy_pct"),
        result.get("fed_balance_sheet_trillion"),
    )

    vix = result.get("vix_close")
    if isinstance(vix, (int, float)):
        try:
            import numpy as np
            result["atr_percentile_proxy"] = float(np.clip((float(vix) - 10) / 40.0, 0.0, 1.0))
        except Exception:
            result["atr_percentile_proxy"] = float(max(0.0, min(1.0, (float(vix) - 10) / 40.0)))

    return result


if __name__ == "__main__":
    # CLI 自检：打印从 SQLite 读到的五维快照
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB_PATH)
    args = ap.parse_args()
    snap = read_macro_from_sqlite(args.db)
    print(f"[FiveDomainSqliteReader] db={args.db}")
    for k in sorted(snap):
        print(f"  {k} = {snap[k]}")
