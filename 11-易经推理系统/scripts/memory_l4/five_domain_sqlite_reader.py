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
        # 扩展：新增 theblockbeats_dataview（律动 dataview 直抓，情绪/衍生品/链上资金流/稳定币溢价/宏观卡片）
        rows = conn.execute(
            "SELECT source, sub_category, metrics, raw, timestamp, id "
            "FROM records WHERE source IN "
            "('fred','yfinance','ccxt','defillama','etherscan','tavily',"
            "'theblockbeats_dataview','panewslab','stablecoin_transparency',"
            "'odaily_newsflash') "
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

    # ── D8 DeFi TVL + D7 稳定币 proxy（双轨分拆）────────────────────────
    #   · defi_tvl_bln：保留 DeFiLlama chains_summary.{Ethereum+TRON} TVL 求和（≈ 49.8B @ 8/28）
    #     用于 defi 板块 & 以太坊生态观察 proxy；
    #   · stablecoin_mcap_bln：改为 stablecoin_transparency 采集的 USDT + USDC 官网真实供应量求和
    #     （≈ 183.35B + 73.60B = 256.95B @ 8/28，阈值 80B 触发线性区间）
    #     回退：若 stablecoin_transparency 未落库，再回退旧 DeFi TVL 估计，避免下游 NAN。
    dl_m = _metric("defillama", "chains_summary")
    result["defi_tvl_bln"] = dl_m.get("total_tvl_bln")
    dl_raw = _raw("defillama", "chains_summary")
    chains_map = dl_raw.get("chains", {}) if isinstance(dl_raw, dict) else {}
    eth_tvl = tron_tvl = 0.0
    if chains_map:
        try:
            eth_tvl = float(chains_map.get("Ethereum", {}).get("tvl_bln", 0.0) or 0.0)
            tron_tvl = float(chains_map.get("TRON", {}).get("tvl_bln", 0.0) or 0.0)
        except Exception:
            eth_tvl = tron_tvl = 0.0
    # 旧口径仅保留为「ETH+TRON DeFi TVL」地维度 DeFi 板块专用观测指标
    result["eth_tron_defi_tvl_bln"] = round(eth_tvl + tron_tvl, 4) if (eth_tvl or tron_tvl) else None

    # — stablecoin_transparency 真实供应量（USDT+USDC 双寡头≈ 95% 稳定币市场份额）—
    usdt_m = _metric("stablecoin_transparency", "tether_current")
    usdc_m = _metric("stablecoin_transparency", "usdc_current")
    usdt_bln = usdt_m.get("usdt_circulating_usd_bln")
    usdc_bln = usdc_m.get("usdc_circulating_usd_bln")
    stable_sum = None
    try:
        vals = [float(v) for v in (usdt_bln, usdc_bln) if isinstance(v, (int, float))]
        if vals:
            stable_sum = round(sum(vals), 4)
    except Exception:
        stable_sum = None
    if stable_sum is not None and stable_sum > 0:
        result["stablecoin_mcap_bln"] = stable_sum
        # 保留逐币透明度指标给地维度 defi 子观测
        if isinstance(usdt_bln, (int, float)):
            result["usdt_circulating_bln"] = round(float(usdt_bln), 4)
        if isinstance(usdc_bln, (int, float)):
            result["usdc_circulating_bln"] = round(float(usdc_bln), 4)
        # 稳定币 1d/7d/30d 变化率（加权平均，作为地维度 RWA/DeFi 扩张/收缩代理）
        rates = []
        for m in (usdt_m, usdc_m):
            for k in ("change_1d_pct", "change_7d_pct", "change_30d_pct"):
                v = m.get(k)
                if isinstance(v, (int, float)):
                    rates.append((k, float(v)))
        for k, v in rates:
            result.setdefault(k, v)
        # stablecoin_change_rate（FiveDomainFetcher 同名字段，加权 1d 涨跌幅）
        chg1 = [r[1] for r in rates if r[0] == "change_1d_pct"]
        if chg1:
            result["stablecoin_change_rate"] = round(sum(chg1) / len(chg1), 4)
    else:
        # 回退：stablecoin_transparency 源未采集时，旧 {ETH+TRON} TVL 近似 ≈49.8B
        #       （语义不准确但 fail-open 不抛 NAN）
        if eth_tvl or tron_tvl:
            result["stablecoin_mcap_bln"] = round(float(eth_tvl) + float(tron_tvl), 4)
        else:
            result["stablecoin_mcap_bln"] = None

    # ── D9 ETH Gas（etherscan，需 API key，当前可能缺）──
    result["gas_eth_gwei"] = _metric("etherscan", "gas").get("propose_gas")

    # ── D10 政策情绪（tavily，需 API key，当前可能缺）──
    result["policy_sentiment_score"] = None

    # ── §BLOCKBEATS: 律动 dataview 直抓五维扩展 ──────────────────────────────
    # 来源: data_center/collectors/news/theblockbeats_dataview.py → dataview_html_parser
    # 产出字段：bottom_pulse_index(天-情绪0-100) / bottom_signal_*(天/将/地) /
    #          top10_inflow_di(地-链上资金流Top10) / echarts_card_meta_*(道/将 宏观/衍生品卡片元信息)
    bb_pulse = _metric("theblockbeats_dataview", "bottom_pulse_index")
    # 脉动指数 0-100 → 归一 [0,1] 的综合情绪打分，同时作为 policy_sentiment_score 的 fallback
    pulse_score_raw = bb_pulse.get("score")
    if isinstance(pulse_score_raw, (int, float)):
        result["blockbeats_pulse_index"] = float(pulse_score_raw)
        # 归一 [0,1]：<20 极恐慌(低) >80 极贪婪(高)，50 中性=0.5
        result["blockbeats_sentiment_norm"] = round(float(pulse_score_raw) / 100.0, 4)
        if result.get("policy_sentiment_score") is None:
            result["policy_sentiment_score"] = result["blockbeats_sentiment_norm"]

    # 抄底逃顶信号：按五维汇总成 avg_score（每个维度一个信号得分）
    signal_map: Dict[str, list[float]] = {}  # dim -> [score]
    for sub in (
        "bottom_signal_tian", "bottom_signal_jiang",
        "bottom_signal_di", "bottom_signal_dao",
    ):
        m = _metric("theblockbeats_dataview", sub)
        dim = m.get("five_dimension")
        sc = m.get("score")
        if isinstance(dim, str) and isinstance(sc, (int, float)):
            signal_map.setdefault(dim, []).append(float(sc))
    for dim, vals in signal_map.items():
        if vals:
            avg = round(sum(vals) / len(vals), 4)
            result[f"blockbeats_signal_{dim}_avg"] = avg
    # 整体信号综合（天=情绪/将=衍生品/地=链上资金，各占 1/3）
    wei = {"tian": 0.4, "jiang": 0.35, "di": 0.25}
    if any(signal_map.get(d) for d in wei):
        tot_w, tot_s = 0.0, 0.0
        for d, w in wei.items():
            vals = signal_map.get(d) or []
            if vals:
                tot_w += w
                tot_s += w * (sum(vals) / len(vals))
        if tot_w > 0:
            result["blockbeats_signal_overall"] = round(tot_s / tot_w, 4)

    # 地维度：Top10 净流入（汇总 + 榜首币种 + 总净流入 USD）
    # 直接从 records 行级读所有 top10_inflow_di 同批次（按 id 区间，取最新一批 >= (latest_id - 20)）
    try:
        conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn2.row_factory = sqlite3.Row
        # 找到最新的一条 top10_inflow_di id
        top = conn2.execute(
            "SELECT id, timestamp FROM records "
            "WHERE source='theblockbeats_dataview' AND sub_category='top10_inflow_di' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        inflow_rows = []
        if top:
            min_id = max(0, top["id"] - 50)  # 同批次不会间隔超过 50 条（共26条/次）
            inflow_rows = conn2.execute(
                "SELECT metrics, id FROM records "
                "WHERE source='theblockbeats_dataview' AND sub_category='top10_inflow_di' "
                "AND id >= ? AND id <= ? ORDER BY id DESC",
                (min_id, top["id"]),
            ).fetchall()
        conn2.close()
        if inflow_rows:
            syms, amts = [], []
            total_usd = 0.0
            seen = set()
            for r in inflow_rows:
                m = _safe_json(r["metrics"])
                sym = m.get("symbol")
                usd = m.get("inflow_usd")
                rank = m.get("rank")
                if not sym or sym in seen:
                    continue
                seen.add(sym)
                syms.append(str(sym))
                amts.append(m.get("inflow_text"))
                if isinstance(usd, (int, float)):
                    total_usd += float(usd)
                if rank == 1:
                    result["blockbeats_inflow_top1_symbol"] = str(sym)
                    result["blockbeats_inflow_top1_usd"] = float(usd) if isinstance(usd, (int, float)) else None
            if syms:
                result["blockbeats_inflow_top10_symbols"] = ",".join(syms[:10])
                result["blockbeats_inflow_top10_amounts"] = ",".join(str(a) for a in amts[:10] if a)
                result["blockbeats_inflow_top10_total_usd"] = round(total_usd, 2)
    except Exception:
        pass  # SQLite 或表异常：保持不变

    # ── §ODAILY：星球日报快讯 72h 指数衰减加权（Spec P0-2 §4.2 + P0-3 §5.2.3 字段闭环） ─
    # 9 个派生字段：
    #   odaily_policy_sentiment_3d        float [0,1]  最近72h指数衰减加权情绪
    #   odaily_important_ratio_3d         float [0,1]  官方重要打标比例（isImportant=true / total）
    #   odaily_crypto_reg_ratio_3d        float [0,1]  crypto_regulation 条数占比
    #   odaily_reg_policy_ratio_3d        float [0,1]  (monetary + us_policy + crypto_reg) / total
    #   odaily_security_hits_3d           int          security_incident 总命中数（含权重衰减）
    #   odaily_geopolitics_hits_3d        int          geopolitics 总命中数（含权重衰减，floor）
    #   odaily_batch_size_3d              int          72h 内有效记录数（权重和上取整）
    #   odaily_avg_decay_hl_hrs_3d        float        衰减加权平均半衰期（小时）
    #   odaily_narrative_hot_3d           float [0,1]  叙事热度：0.6*important + 0.4*crypto_reg_ratio（归一 [0,1]）
    #
    # policy_sentiment_score 优先级（Spec 硬约束 §5.2.4 极值保护）：
    #   odaily_policy_sentiment_3d ∈ [0.2, 0.8]  → odaily 覆盖写 ✓
    #   否则 → 保持 blockbeats → pn_cycle_sentiment_norm → None 回退链不变
    try:
        import math
        # 1. 收集所有 odaily_newsflash 记录 + 按 timestamp(ms) 计算 age_hrs
        now_ms = 0
        od_rows = []
        for (src, sub), rec in latest.items():
            if src != "odaily_newsflash" or not rec["metrics"]:
                continue
            # sqlite3.Row 没有 .get()：先 dict() 转换确保后续 .get 可用
            rowd = dict(rec)
            m = _safe_json(rowd.get("metrics"))
            ts = 0
            # timestamp 从 latest 原始值解析（ISO 格式）
            ts_raw = rowd.get("timestamp")
            if isinstance(ts_raw, str):
                try:
                    from datetime import datetime as _dt
                    tt = _dt.fromisoformat(ts_raw.replace("Z", "+00:00"))
                    ts = int(tt.timestamp() * 1000)
                except Exception:
                    ts = 0
            if ts > now_ms:
                now_ms = ts
            # 同时用 publish_ms 作为新闻发布时间（更准确），若缺失 fallback ts
            pub_raw = rowd.get("raw")
            pub_ms = 0
            if isinstance(pub_raw, (dict, str)):
                rd = _safe_json(pub_raw) if isinstance(pub_raw, str) else pub_raw
                if isinstance(rd.get("publishTimestamp"), (int, float)):
                    pub_ms = int(rd["publishTimestamp"])
            if pub_ms <= 0:
                pub_ms = ts
            decay = m.get("od_decay_hl_hrs") if isinstance(m, dict) else None
            if not isinstance(decay, (int, float)):
                decay = 24
            od_rows.append({
                "m": m if isinstance(m, dict) else {},
                "pub_ms": pub_ms,
                "decay_hrs": float(decay),
            })
        if now_ms == 0 and od_rows:
            now_ms = max(r["pub_ms"] for r in od_rows)
        HR_TO_MS = 3600_000
        WINDOW_HRS = 72.0
        # 2. 逐行算指数衰减权重 w = 2^(-age/hl)，age_hrs>72 保留极小值=2^-3=0.125
        total_w = 0.0
        sent_wsum = 0.0
        decay_wsum = 0.0
        imp_wsum = 0.0
        crh_wsum = 0.0
        regp_wsum = 0.0
        sec_wsum = 0.0
        geo_wsum = 0.0
        for r in od_rows:
            age_hrs = max(0.0, (now_ms - r["pub_ms"]) / HR_TO_MS) if now_ms > r["pub_ms"] else 0.0
            if age_hrs <= WINDOW_HRS + 1e-9:
                hl = max(1.0, r["decay_hrs"])
                w = math.pow(2.0, -age_hrs / hl)
                total_w += w
                m = r["m"]
                s = m.get("od_policy_sentiment_0_1")
                if isinstance(s, (int, float)):
                    sent_wsum += w * float(s)
                decay_wsum += w * r["decay_hrs"]
                imp = 1.0 if str(m.get("od_is_important", "")).lower() == "true" else 0.0
                imp_wsum += w * imp
                et = str(m.get("od_event_type", "") or "")
                if et == "crypto_regulation":
                    crh_wsum += w
                if et in {"monetary_policy", "us_policy", "crypto_regulation"}:
                    regp_wsum += w
                if et == "security_incident":
                    sec_wsum += w
                if et == "geopolitics":
                    geo_wsum += w
        # 3. 组装 9 字段（total_w <= 1e-9 表示无数据 → 全部 None）
        if total_w > 1e-9:
            sent_3d = max(0.0, min(1.0, sent_wsum / total_w))
            result["odaily_policy_sentiment_3d"] = round(sent_3d, 4)
            result["odaily_important_ratio_3d"] = round(imp_wsum / total_w, 4)
            result["odaily_crypto_reg_ratio_3d"] = round(crh_wsum / total_w, 4)
            result["odaily_reg_policy_ratio_3d"] = round(regp_wsum / total_w, 4)
            result["odaily_security_hits_3d"] = int(round(sec_wsum))
            result["odaily_geopolitics_hits_3d"] = int(math.floor(geo_wsum))
            result["odaily_batch_size_3d"] = int(math.ceil(total_w))
            result["odaily_avg_decay_hl_hrs_3d"] = round(decay_wsum / total_w, 2)
            narrative_hot = 0.6 * (imp_wsum / total_w) + 0.4 * (crh_wsum / total_w)
            result["odaily_narrative_hot_3d"] = round(max(0.0, min(1.0, narrative_hot)), 4)
            # ── 极值保护：仅当 odaily ∈ [0.2, 0.8] 才覆盖 policy_sentiment_score ──
            if 0.2 <= sent_3d <= 0.8:
                result["policy_sentiment_score"] = round(sent_3d, 4)
    except Exception as e:  # noqa: BLE003  FAIL-OPEN 保持不变
        import logging as _logging
        _logging.getLogger("FiveDomainSqliteReader.odaily").warning(
            "§ODAILY 派生异常 %s: %s，保持不变（FAIL-OPEN）",
            type(e).__name__, str(e)[:160],
        )

    # ── PANEWSLAB（律动 PAData 聚合）8 板块五维增强 ─────────────────────────
    # 对齐 FiveDomainFetcher._enrich_coin_with_panewslab 语义。
    # panewslab_m = {sub_category -> metrics_dict}
    panewslab_m: Dict[str, Dict[str, Any]] = {}
    for (src, sub), rec in latest.items():
        if src == "panewslab" and rec["metrics"]:
            panewslab_m[sub] = _safe_json(rec["metrics"])
    if panewslab_m:
        # ─ 共享 macro（全类消费），同时补强 FRED/VIX ─
        macro = panewslab_m.get("macro_us_stocks", {})
        if macro:
            if result.get("fedfunds_rate") is None and isinstance(macro.get("us_DFF_value"), (int, float)):
                result["fedfunds_rate"] = float(macro["us_DFF_value"])
            if result.get("vix_close") is None and isinstance(macro.get("us_VIXCLS_value"), (int, float)):
                result["vix_close"] = float(macro["us_VIXCLS_value"])
            for k_src, k_dst in [
                ("us_SP500_value",       "pn_us_sp500"),
                ("us_NASDAQCOM_value",   "pn_us_nasdaq"),
                ("us_DGS10_value",       "pn_us_10y_yield"),
                ("us_DTWEXBGS_value",    "pn_us_dollar_index"),
                ("us_DFF_value",         "pn_us_fedfunds"),
                ("us_VIXCLS_value",      "pn_us_vix"),
            ]:
                v = macro.get(k_src)
                if isinstance(v, (int, float)):
                    result[k_dst] = float(v)
                elif isinstance(v, str):
                    result[k_dst] = v
        # ─ crypto 专用 proxy ─
        overview = panewslab_m.get("overview_market", {})
        cycle = panewslab_m.get("cycle_signals", {})
        etf = panewslab_m.get("etf_institutional", {})
        srwa = panewslab_m.get("stablecoin_rwa", {})
        deriv = panewslab_m.get("derivatives_spot", {})
        exch = panewslab_m.get("exchanges_whales", {})
        hold = panewslab_m.get("holdings_onchain_funds", {})

        # overview（加密市场总览）
        if isinstance(overview.get("global_market_cap_usd"), (int, float)):
            result["pn_global_market_cap_usd"] = float(overview["global_market_cap_usd"])
        btc_dom = overview.get("btc_dominance_pct")
        if isinstance(btc_dom, (int, float)):
            result["pn_btc_dominance_pct"] = float(btc_dom)
            result["pn_btc_dom_focus"] = float(btc_dom) / 100.0
        gchg = overview.get("global_change24_pct")
        if isinstance(gchg, (int, float)):
            result["pn_global_change24_pct"] = float(gchg)

        # cycle（周期/抄底信号）→ D10 政策情绪 / 市场广度 proxy
        hit_ratio = cycle.get("bottom_hit_ratio_pct")
        if isinstance(hit_ratio, (int, float)):
            result["pn_cycle_bottom_hit_ratio_pct"] = float(hit_ratio)
            result["pn_cycle_sentiment_norm"] = float(hit_ratio) / 100.0
            if result.get("policy_sentiment_score") in (None, 0.5):
                result["policy_sentiment_score"] = float(hit_ratio) / 100.0
        hc = cycle.get("bottom_hit_count")
        tc = cycle.get("bottom_total_count")
        if isinstance(hc, (int, float)): result["pn_cycle_bottom_hit_count"] = int(hc)
        if isinstance(tc, (int, float)): result["pn_cycle_bottom_total_count"] = int(tc)
        omni_hits = [float(v) for k, v in cycle.items()
                     if isinstance(k, str) and k.endswith("_hit") and isinstance(v, bool)]
        if omni_hits:
            result["pn_cycle_omnitools_hit_count"] = int(sum(omni_hits))
            result["pn_cycle_omnitools_hit_ratio"] = round(sum(omni_hits)/len(omni_hits), 4)

        # ETF/机构
        btc_flow = etf.get("btc_etf_daily_flow_usd")
        if isinstance(btc_flow, (int, float)):
            result["pn_btc_etf_daily_flow_usd"] = float(btc_flow)
            result["pn_btc_etf_flow_norm"] = float(max(-1.0, min(1.0, float(btc_flow) / 2e8)))
        btc_aum = etf.get("btc_etf_total_aum_usd")
        if isinstance(btc_aum, (int, float)): result["pn_btc_etf_total_aum_usd"] = float(btc_aum)
        btc_hold = etf.get("treasury_total_btc_holdings")
        if isinstance(btc_hold, (int, float)): result["pn_treasury_btc_total"] = float(btc_hold)
        eth_flow = etf.get("eth_etf_daily_flow_usd")
        if isinstance(eth_flow, (int, float)): result["pn_eth_etf_daily_flow_usd"] = float(eth_flow)

        # 稳定币 + RWA（补强 stablecoin_mcap_bln / stablecoin_change_rate）
        tvl = srwa.get("rwa_tvl_usd")
        if isinstance(tvl, (int, float)):
            result["pn_rwa_tvl_usd"] = float(tvl)
            if result.get("stablecoin_mcap_bln") is None:
                result["stablecoin_mcap_bln"] = round(float(tvl) * 5.0 / 1e9, 4)
        pulse = srwa.get("stable_pulse_rangeStatus")
        if pulse:
            result["pn_stablecoin_pulse_range"] = str(pulse)
            rng_map = {"FLOOD": 0.85, "OVERFLOW": 0.95, "FULL": 0.7, "FILLING": 0.55,
                       "HALF": 0.5, "DRAIN": 0.35, "DRAINED": 0.2}
            if pulse in rng_map:
                result["pn_stablecoin_pulse_norm"] = rng_map[pulse]
        rwa_chg7d = srwa.get("rwa_change7d_pct")
        if isinstance(rwa_chg7d, (int, float)):
            result["pn_rwa_change7d_pct"] = float(rwa_chg7d)
            if result.get("stablecoin_change_rate") is None:
                result["stablecoin_change_rate"] = float(rwa_chg7d) * 0.5 / 100.0

        # 衍生品/现货：波动率周期 proxy（ATR percentile 补强）+ 杠杆率
        oi = deriv.get("fut_open_interest_usd")
        cap = overview.get("global_market_cap_usd")
        if isinstance(oi, (int, float)):
            result["pn_fut_open_interest_usd"] = float(oi)
            if isinstance(cap, (int, float)) and float(cap) > 0:
                result["pn_leverage_ratio_oi_cap"] = round(float(oi) / float(cap), 6)
        fv = deriv.get("fut_volume_24h_usd")
        if isinstance(fv, (int, float)): result["pn_fut_volume_24h_usd"] = float(fv)
        ll = deriv.get("fut_liq_long_24h_usd")
        sl = deriv.get("fut_liq_short_24h_usd")
        if isinstance(ll, (int, float)) and isinstance(sl, (int, float)):
            tot = float(ll) + float(sl)
            if tot > 0:
                result["pn_fut_long_liq_ratio"] = round(float(ll) / tot, 4)
                result["pn_fut_liquidation_total_usd"] = round(tot, 2)
        liq24 = deriv.get("fut_liq_total_24h_usd")
        if isinstance(liq24, (int, float)):
            result["pn_fut_liquidation_24h_usd"] = float(liq24)
            if isinstance(cap, (int, float)) and float(cap) > 0:
                lr = float(liq24) / float(cap)
                atr_proxy = max(0.0, min(1.0, lr * 500))
                result["pn_liq_atr_percentile_proxy"] = round(atr_proxy, 4)
                if not result.get("atr_percentile_proxy"):
                    result["atr_percentile_proxy"] = atr_proxy

        # 交易所 + 巨鲸净流（地维度：抛压/吸筹 proxy）
        nf = exch.get("whale_netflow_to_ex_usd")
        if isinstance(nf, (int, float)):
            result["pn_whale_netflow_to_ex_usd"] = float(nf)
            if isinstance(cap, (int, float)) and float(cap) > 0:
                result["pn_whale_netflow_cap_pct"] = round(float(nf) / float(cap) * 100, 6)
        to_ex = exch.get("whale_24h_to_ex_usd")
        from_ex = exch.get("whale_24h_from_ex_usd")
        if isinstance(to_ex, (int, float)): result["pn_whale_24h_to_ex_usd"] = float(to_ex)
        if isinstance(from_ex, (int, float)): result["pn_whale_24h_from_ex_usd"] = float(from_ex)
        btc_chg30 = exch.get("ex_bal_BTC_chg30d_pct")
        if isinstance(btc_chg30, (int, float)): result["pn_ex_bal_btc_chg30d_pct"] = float(btc_chg30)

        # holdings：链上资金广度
        tbtc = hold.get("holdings_treasury_btc_sum")
        if isinstance(tbtc, (int, float)): result["pn_holdings_treasury_btc"] = float(tbtc)
        trs_count = hold.get("holdings_treasury_count")
        if isinstance(trs_count, (int, float)): result["pn_holdings_treasury_count"] = int(trs_count)
        dh = hold.get("holdings_defi-fundamental-breadth_hit")
        ch = hold.get("holdings_public-chain-activity-breadth_hit")
        hits = [v for v in (dh, ch) if isinstance(v, bool)]
        if hits:
            result["pn_holdings_breadth_hit_ratio"] = round(sum(1 for h in hits if h) / len(hits), 4)
        for ks, kd in [("holdings_defi-fundamental-breadth_rangeStatus", "pn_defi_breadth_range"),
                       ("holdings_public-chain-activity-breadth_rangeStatus", "pn_chain_breadth_range")]:
            v = hold.get(ks)
            if v: result[kd] = str(v)

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


def read_three_classes_from_sqlite(db_path: str = DEFAULT_DB_PATH) -> Dict[str, Dict[str, Any]]:
    """从 SQLite 读已落库五维+Panewslab 数据，组装成三类资产 coin_data。

    返回结构：
      {
        "crypto_usdt":      {cycle4y_t_rel, merrill_phase, ..., 所有 pn_* proxy},
        "us_stock":         {...，仅 D1/T1/VIX/美股/VIX 宏观 proxy，pn_us_* / pn_cycle_*},
        "precious_metal":   {...，同 us_stock 范围},
      }

    任何异常 fail-open 返回 {}（调用方走自身硬编码兜底）。
    """
    fallback: Dict[str, Dict[str, Any]] = {}
    if not db_path or not os.path.exists(db_path):
        return fallback
    try:
        macro = read_macro_from_sqlite(db_path)
    except Exception:
        return fallback

    # ── 按类模板初始化：含宏观 + Spring 兜底占位（调用方有值会再覆写） ──
    # 注意：实际 cycle4y_t_rel/merrill_phase / spring_force_score / 各 Dn 字段
    # 由 PollingTrader 主逻辑（FiveDomainFetcher 硬编码块）再覆盖；这里只负责
    # 「从 records 表能拿到的数据 + 所有 pn_* proxy」的字段，其他保持 None
    # 以避免替代掉调用方已经内联的逻辑（仅作增量注入，字节等价 Fail-Open）。

    shared_pn_prefixes_ok_stock = (
        "pn_us_", "pn_cycle_bottom_", "pn_cycle_sentiment_",
        "pn_cycle_omnitools_",
    )

    def _build(template_cls: str) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        # 基础宏观（所有类共有）
        for key in (
            "vix_close", "fedfunds_rate", "m2_yoy_pct",
            "fed_balance_sheet_trillion", "us_cpi_yoy_pct",
            "us_indpro_yoy_pct", "policy_sentiment_score",
            "liquidity_score", "merrill_phase", "atr_percentile_proxy",
            "stablecoin_change_rate", "stablecoin_mcap_bln",
        ):
            d[key] = macro.get(key)
        # Spec §5.2.3：odaily_* 字段对所有资产类注入（政策情绪→dao/tian boost）
        for k, v in macro.items():
            if k.startswith("odaily_"):
                d[k] = v
        if template_cls == "crypto_usdt":
            # 全部 pn_* 字段
            for k, v in macro.items():
                if k.startswith("pn_"):
                    d[k] = v
        else:
            # us_stock / precious_metal：仅 macro_us + cycle proxy 共享
            for k, v in macro.items():
                if any(k.startswith(p) for p in shared_pn_prefixes_ok_stock):
                    d[k] = v
        return d

    return {
        "crypto_usdt":    _build("crypto_usdt"),
        "us_stock":       _build("us_stock"),
        "precious_metal": _build("precious_metal"),
    }


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
