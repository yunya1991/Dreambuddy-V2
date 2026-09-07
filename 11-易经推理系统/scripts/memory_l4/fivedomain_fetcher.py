#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FiveDomainFetcher — 用数据获取中心（data_center）一次性采集五维所需全部外部数据。

输出: `Dict[asset_class, Dict[str, Any]]`，key 集合对齐 FiveDomainFeatureComputer
需要的 coin_data（分层结构）：crypto_usdt / us_stock / precious_metal。

数据来源映射（对齐 FIVE_DOMAIN_DATA_COLLECTION_DESIGN.md §二）：
  D1 联邦基金利率     → fred FEDFUNDS
  D2 M2 同比           → fred M2NS（如果需要 M2SL 也可在派生层自选）
  D3 联储总资产        → fred WALCL / 1e12 → trillion USD
  D4 CPI 同比          → fred CPIAUCSL（用与上月环比 = proxy yoy 简化）
  D5 PPI               → fred PPIACO（预留键，当前编排层只在 raw 里放）
  D6 工业产出          → fred INDPRO（↑/↓ = 美林增长 proxy）
  D7 稳定币总市值 proxy → defillama chains_summary top 链 TVL（Tron/Ethereum 最聚集稳定币）
  D8 DeFi TVL          → defillama chains_summary 总 TVL
  D9 ETH Gas           → etherscan kind=gas 的 propose_gas
  D10 政策景气度       → tavily 新闻简易情感词典打分

派生项（编排层本地计算，不占外部采集）：
  T1 美林时钟阶段 merrill_phase = 通胀↑/↓ × 增长↑/↓ 的四象限
  T4 流动性评分 liquidity_score = 0.4×利率反转 + 0.4×M2 + 0.2×WALCL 归一化

Panewslab（律动 PAData）增强（P3-2 接入）：
  route=all 覆盖 8 大板块 → 产出 30+ 五维代理指标：
    道维度：机构净流入(BTC ETF 流量/稳定币总市值)、政策景气度(抄底信号命中率/MEME风险偏好)
    天维度：美林时钟代理(恐慌指数VIX/FED利率)、季节性(抄底信号hit率)、波动率周期(合约OI/爆仓比)
    地维度：市场广度(DeFi广度/扩散指数hit率)、交易所净流入(巨鲸净流)、支撑阻力(MA200距离proxy)
    宏观通用：美股 SP500、纳斯达克、美债10Y、美元指数、联邦基金利率(对齐 FRED)
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# 兼容：11-易经推理系统/scripts/memory_l4 目录下运行，需要把 18-数据获取中心 加到 sys.path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_THIS_DIR, "..", "..", ".."))
_DATA_CENTER_PKG_ROOT = os.path.join(_REPO, "18-数据获取中心")
if _DATA_CENTER_PKG_ROOT not in sys.path:
    sys.path.insert(0, _DATA_CENTER_PKG_ROOT)


ASSET_CLASSES = ("crypto_usdt", "us_stock", "precious_metal")

# 政策情绪简易词典（Tavily 标题+内容匹配，后续可换模型）
_POS_WORDS = ("宽松", "降息", "批准", "支持", "利好", "流入", "复苏", "升级",
              "easing", "cut", "approve", "inflow", "bullish", "support")
_NEG_WORDS = ("紧缩", "加息", "起诉", "处罚", "监管", "限制", "禁止", "流出", "暴跌",
              "tightening", "hike", "sue", "penalty", "crackdown", "restrict", "outflow")


class FiveDomainFetcher:
    """编排层：拉取数据 → 按类装配 coin_data → 衍生 merrill_phase / liquidity_score。

    Args:
        data_center: 任何具备 `fetch(category, source=..., **params) -> List[DataRecord]`
            方法的对象。生产环境用 `DataCenter()`，测试可传 FakeDC。
        policy_queries: 政策新闻查询词，默认对齐 D10（SEC/Fed/中国监管）。
    """

    DEFAULT_POLICY_QUERIES: Tuple[str, ...] = (
        "Fed FOMC monetary policy latest",
        "SEC CFTC crypto regulation update latest",
        "China crypto policy news latest",
    )

    def __init__(self, data_center: Any = None, policy_queries: Tuple[str, ...] = DEFAULT_POLICY_QUERIES):
        if data_center is None:
            from data_center.core.dispatcher import DataCenter
            data_center = DataCenter()
        self.dc = data_center
        self.policy_queries = tuple(policy_queries)
        # 采集结果缓存（按日期）：避免 1 天内重复打 API
        self._cache: Dict[str, Any] = {}

    # ==================================================================
    # 对外入口
    # ==================================================================
    def fetch_coin_data(self) -> Dict[str, Dict[str, Any]]:
        """一次性采集并返回三类资产的 coin_data。"""
        raw = self._collect_raw()
        result: Dict[str, Dict[str, Any]] = {}
        for cls in ASSET_CLASSES:
            result[cls] = self._build_class_coin(cls, raw)
        return result

    # ==================================================================
    # 内部：批量采集 raw（D1~D10, T2）
    # ==================================================================
    def _collect_raw(self) -> Dict[str, Any]:
        raw: Dict[str, Any] = {}
        # ── FRED 6 系列 ──
        for s in ("FEDFUNDS", "M2NS", "WALCL", "CPIAUCSL", "PPIACO", "INDPRO"):
            raw[f"fred:{s}"] = self._safe_first_metric(
                self.dc.fetch("macro", source="fred", series=s)
            )
        # ── VIX ──
        raw["yfinance:^VIX"] = self._safe_first_metric(
            self.dc.fetch("finance", source="yfinance", symbol="^VIX")
        )
        # ── DeFiLlama chains ──
        raw["defillama:chains"] = self._safe_first(
            self.dc.fetch("chain", source="defillama", route="chains")
        )
        # ── etherscan gas ──
        raw["etherscan:gas"] = self._safe_first_metric(
            self.dc.fetch("chain", source="etherscan", kind="gas")
        )
        # ── 政策新闻 D10 ──
        policy_events: List[Any] = []
        for q in self.policy_queries:
            try:
                recs = self.dc.fetch("news", source="tavily", query=q, max_results=5)
            except Exception:
                recs = []
            for r in recs or []:
                items = (r.raw or {}).get("results") or []
                policy_events.extend(items)
        raw["policy:events"] = policy_events
        # ── Panewslab 8 板块（律动 PAData 聚合：CoinGecko/CoinGlass/DefiLlama/Treasury）
        raw.update(self._collect_panewslab_raw())
        return raw

    # ==================================================================
    # Panewslab：8 大板块一次性采集（route=all，fail-open 任何异常不阻塞上层）
    # ==================================================================
    def _collect_panewslab_raw(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        try:
            recs = self.dc.fetch("chain", source="panewslab", route="all") or []
        except Exception:
            return out
        for r in recs:
            sub = getattr(r, "sub_category", None)
            if not sub:
                continue
            m = dict(getattr(r, "metrics", None) or {})
            raw = dict(getattr(r, "raw", None) or {})
            ts = getattr(r, "timestamp", None)
            # 按 sub_category 存两份：metrics + raw 摘要
            out[f"panewslab:{sub}:m"] = m
            out[f"panewslab:{sub}:r"] = raw
            out[f"panewslab:{sub}:t"] = ts
        return out

    # ==================================================================
    # 内部：按资产类装配 coin_data
    # ==================================================================
    def _build_class_coin(self, asset_cls: str, raw: Dict[str, Any]) -> Dict[str, Any]:
        coin: Dict[str, Any] = {}

        # D1 联邦基金利率（FRED value 是百分比，如 5.25）
        coin["fedfunds_rate"] = self._val(raw.get("fred:FEDFUNDS"), "value")
        # D2 M2NS value = M2 十亿美元 → 除以 1000 是万亿。这里简化把原始值作为 M2 指数存
        m2 = self._val(raw.get("fred:M2NS"), "value")
        coin["m2_yoy_pct"] = None  # FRED M2NS 是绝对值，同比需历史对比，这里留空后续增强
        if m2 is not None:
            coin["m2_index_bln"] = m2
        # D3 WALCL → trillion（WALCL 原始是美元，除以 1e12 得万亿）
        walcl = self._val(raw.get("fred:WALCL"), "value")
        coin["fed_balance_sheet_trillion"] = round(walcl / 1e12, 4) if isinstance(walcl, (int, float)) else None
        # D4 CPIAUCSL 同比（简化：当前只记录指数值）
        coin["us_cpi_yoy_pct"] = self._val(raw.get("fred:CPIAUCSL"), "value")
        # D5 PPI 预留
        coin["us_ppi_yoy_pct"] = self._val(raw.get("fred:PPIACO"), "value")
        # D6 工业产出
        coin["us_indpro_yoy_pct"] = self._val(raw.get("fred:INDPRO"), "value")

        # ── 链上：只对 crypto_usdt 有意义 ──
        chains_rec = raw.get("defillama:chains")
        if asset_cls == "crypto_usdt":
            if chains_rec is not None:
                coin["defi_tvl_bln"] = (chains_rec.metrics or {}).get("total_tvl_bln")
                # D7 稳定币总市值 proxy = Ethereum+TRON TVL（最集中稳定币）
                try:
                    chains_map = (chains_rec.raw or {}).get("chains", {})
                    eth_tvl = chains_map.get("Ethereum", {}).get("tvl_bln", 0.0)
                    tron_tvl = chains_map.get("TRON", {}).get("tvl_bln", 0.0)
                    coin["stablecoin_mcap_bln"] = round(eth_tvl + tron_tvl, 4)
                except Exception:
                    coin["stablecoin_mcap_bln"] = None
            else:
                coin["defi_tvl_bln"] = None
                coin["stablecoin_mcap_bln"] = None
            gas_metrics = raw.get("etherscan:gas") or {}
            coin["gas_eth_gwei"] = gas_metrics.get("propose_gas") if isinstance(gas_metrics, dict) else None
        else:
            coin["defi_tvl_bln"] = None
            coin["stablecoin_mcap_bln"] = None
            coin["gas_eth_gwei"] = None

        # D10 政策景气度（只填到 crypto，其它类留 None — 后续可按资产类扩展 query）
        if asset_cls == "crypto_usdt":
            coin["policy_sentiment_score"] = self._sentiment_score(raw.get("policy:events") or [])
        else:
            coin["policy_sentiment_score"] = None

        # T2 VIX（对三类都共享）
        vix_metrics = raw.get("yfinance:^VIX") or {}
        # YFinanceCollector 输出 metrics["price"]；fallback 兼容 raw
        vix_price = None
        if isinstance(vix_metrics, dict):
            vix_price = vix_metrics.get("price") or vix_metrics.get("value")
        coin["vix_close"] = vix_price

        # T1 美林时钟（通胀（CPI proxy）× 增长（INDPRO proxy））
        coin["merrill_phase"] = self._compute_merrill(
            coin.get("us_cpi_yoy_pct"), coin.get("us_indpro_yoy_pct")
        )

        # T4 流动性评分
        coin["liquidity_score"] = self._compute_liquidity_score(
            coin.get("fedfunds_rate"),
            coin.get("m2_yoy_pct"),
            coin.get("fed_balance_sheet_trillion"),
        )

        # Panewslab 增强：30+ 五维代理指标按资产类注入
        self._enrich_coin_with_panewslab(coin, asset_cls, raw)

        return coin

    # ==================================================================
    # Panewslab：8 板块 metrics → coin_data 五维 proxy（按资产类差异化）
    # ==================================================================
    def _enrich_coin_with_panewslab(
        self, coin: Dict[str, Any], asset_cls: str, raw: Dict[str, Any]
    ) -> None:
        """把 panewslab 8 大类数据按需注入 coin_data。

        字段分两类：
          1) 现有 proxy 字段补强（当 FRED/VIX 缺失时）
          2) 新增的 panewslab_* 字段（供 FiveDomainFeatureComputer 子指标加分）
        """
        def _m(sub: str) -> Dict[str, Any]:
            return raw.get(f"panewslab:{sub}:m") or {}  # type: ignore[return-value]

        # ============================================================
        # macro_us：美股/宏观（三类共享，主要 us_stock 消费；crypto 也依赖 FED 利率）
        # ============================================================
        macro = _m("macro_us_stocks")
        if macro:
            # FRED/DGS10 / DTWEXBGS 等补强（如果原 collector 缺 key，直接用 panewslab 值替代）
            if coin.get("fedfunds_rate") is None and macro.get("us_DFF_value") is not None:
                coin["fedfunds_rate"] = float(macro["us_DFF_value"])
            # VIX 补强：当 yfinance ^VIX API 挂时用 panewslab 的 VIXCLS 值
            if coin.get("vix_close") is None and macro.get("us_VIXCLS_value") is not None:
                vix = macro["us_VIXCLS_value"]
                coin["vix_close"] = float(vix) if isinstance(vix, (int, float)) else None
            # 新增 macro proxy 字段（全类共享：道/天维度用）
            for k_src, k_dst in [
                ("us_SP500_value",      "pn_us_sp500"),
                ("us_NASDAQCOM_value",  "pn_us_nasdaq"),
                ("us_DGS10_value",      "pn_us_10y_yield"),
                ("us_DTWEXBGS_value",   "pn_us_dollar_index"),
                ("us_DFF_value",        "pn_us_fedfunds"),
                ("us_VIXCLS_value",     "pn_us_vix"),
                ("us_SP500_chg_pct",    "pn_us_sp500_chg_pct"),
                ("us_NASDAQCOM_chg_pct", "pn_us_nasdaq_chg_pct"),
            ]:
                v = macro.get(k_src)
                if isinstance(v, (int, float)):
                    coin[k_dst] = float(v)
                elif isinstance(v, str):
                    coin[k_dst] = v

        # ============================================================
        # overview_market：市场总览（crypto 主用）
        # ============================================================
        overview = _m("overview_market")
        if overview and asset_cls == "crypto_usdt":
            # 补强 defi_tvl_bln / stablecoin_mcap_bln
            total_cap = overview.get("global_market_cap_usd")
            if isinstance(total_cap, (int, float)):
                coin["pn_global_market_cap_usd"] = float(total_cap)
            btc_dom = overview.get("btc_dominance_pct")
            if isinstance(btc_dom, (int, float)):
                coin["pn_btc_dominance_pct"] = float(btc_dom)
                # BTC 占比 proxy：道维度资金集中度（>60=集中→利好BTC<50=分歧→减分）
                coin["pn_btc_dom_focus"] = float(btc_dom) / 100.0
            gchg = overview.get("global_change24_pct")
            if isinstance(gchg, (int, float)):
                coin["pn_global_change24_pct"] = float(gchg)
            # stablecoin_mcap_bln 补强：overview 里有 stablecoin 汇总更好
            # 但 overview-trends 只给 global_cap，stablecoin 在 stable_rwa 板块里

        # ============================================================
        # cycle_signals：周期判断（crypto 最敏感；美股也部分参考）
        # ============================================================
        cycle = _m("cycle_signals")
        if cycle:
            hit_ratio = cycle.get("bottom_hit_ratio_pct")
            if isinstance(hit_ratio, (int, float)):
                coin["pn_cycle_bottom_hit_ratio_pct"] = float(hit_ratio)
                # 映射 0-100 到 [0,1]，作为 政策景气度 额外参考（道维度加分）
                coin["pn_cycle_sentiment_norm"] = float(hit_ratio) / 100.0
                # D10 政策情绪 score 的补强（当 tavily 失败时用抄底命中率代理）
                if (coin.get("policy_sentiment_score") is None
                        or coin.get("policy_sentiment_score") == 0.5):
                    coin["policy_sentiment_score"] = float(hit_ratio) / 100.0
            hit_count = cycle.get("bottom_hit_count")
            if isinstance(hit_count, (int, float)):
                coin["pn_cycle_bottom_hit_count"] = int(hit_count)
            total_count = cycle.get("bottom_total_count")
            if isinstance(total_count, (int, float)):
                coin["pn_cycle_bottom_total_count"] = int(total_count)
            # omnitools 扩散广度命中数 / 指标命中数 = 市场广度指数（0-1）
            omni_hits = [
                float(v) for k, v in cycle.items()
                if isinstance(k, str) and k.endswith("_hit") and isinstance(v, bool)
            ]
            if omni_hits:
                coin["pn_cycle_omnitools_hit_count"] = int(sum(omni_hits))
                coin["pn_cycle_omnitools_hit_ratio"] = round(
                    sum(omni_hits) / len(omni_hits), 4
                )

        # ============================================================
        # etf_institutional：ETF/机构持仓（crypto 专用）
        # ============================================================
        etf = _m("etf_institutional")
        if etf and asset_cls == "crypto_usdt":
            btc_flow = etf.get("btc_etf_daily_flow_usd")
            if isinstance(btc_flow, (int, float)):
                coin["pn_btc_etf_daily_flow_usd"] = float(btc_flow)
                # 道维度子指标2机构净流入 proxy（FED稳定币 + ETF流量）
                # ETF 净流入/流出 ±2 亿 → 映射 stablecoin_change_rate ±3% 级
                coin["pn_btc_etf_flow_norm"] = float(
                    max(-1.0, min(1.0, float(btc_flow) / 2e8))
                )
            aum = etf.get("btc_etf_total_aum_usd")
            if isinstance(aum, (int, float)):
                coin["pn_btc_etf_total_aum_usd"] = float(aum)
            # 机构 BTC 总持仓（Treasury 公司持仓）
            btc_hold = etf.get("treasury_total_btc_holdings")
            if isinstance(btc_hold, (int, float)):
                coin["pn_treasury_btc_total"] = float(btc_hold)
            # ETH ETF
            eth_flow = etf.get("eth_etf_daily_flow_usd")
            if isinstance(eth_flow, (int, float)):
                coin["pn_eth_etf_daily_flow_usd"] = float(eth_flow)

        # ============================================================
        # stablecoin_rwa：稳定币 + RWA（crypto 专用）
        # ============================================================
        srwa = _m("stablecoin_rwa")
        if srwa and asset_cls == "crypto_usdt":
            # 稳定币市值：用 RWA 的 TVL 作为 proxy（粗略量级）
            tvl = srwa.get("rwa_tvl_usd")
            if isinstance(tvl, (int, float)):
                coin["pn_rwa_tvl_usd"] = float(tvl)
            # 补强 stablecoin_mcap_bln：直接用 RWA TVL 的量级代理
            if coin.get("stablecoin_mcap_bln") is None and isinstance(tvl, (int, float)):
                # RWA TVL 28B → 稳定币总市值约 150B，按 ~5x 粗估补强
                coin["stablecoin_mcap_bln"] = round(float(tvl) * 5.0 / 1e9, 4)
            # 稳定币脉冲：range_status / current_range → 分数
            pulse = srwa.get("stable_pulse_rangeStatus")
            if pulse:
                coin["pn_stablecoin_pulse_range"] = str(pulse)
                rng_map = {"FLOOD": 0.85, "OVERFLOW": 0.95, "FULL": 0.7,
                           "FILLING": 0.55, "HALF": 0.5, "DRAIN": 0.35,
                           "DRAINED": 0.2}
                if pulse in rng_map:
                    coin["pn_stablecoin_pulse_norm"] = rng_map[pulse]
            # RWA 7日变化：上涨=资金在入场→加分
            rwa_chg7d = srwa.get("rwa_change7d_pct")
            if isinstance(rwa_chg7d, (int, float)):
                coin["pn_rwa_change7d_pct"] = float(rwa_chg7d)
                # 作为 stablecoin_change_rate 补强（±10% → ±5%）
                if coin.get("stablecoin_change_rate") is None:
                    coin["stablecoin_change_rate"] = float(rwa_chg7d) * 0.5 / 100.0

        # ============================================================
        # derivatives_spot：现货+衍生品（crypto 专用）
        # ============================================================
        deriv = _m("derivatives_spot")
        if deriv and asset_cls == "crypto_usdt":
            oi = deriv.get("fut_open_interest_usd")
            if isinstance(oi, (int, float)):
                coin["pn_fut_open_interest_usd"] = float(oi)
                # OI / 全球市值 → 杠杆率 proxy（越小→越安全，越大→泡沫）
                cap = (raw.get("panewslab:overview_market:m") or {}).get("global_market_cap_usd")
                if isinstance(cap, (int, float)) and float(cap) > 0:
                    coin["pn_leverage_ratio_oi_cap"] = round(float(oi) / float(cap), 6)
            fut_vol = deriv.get("fut_volume_24h_usd")
            if isinstance(fut_vol, (int, float)):
                coin["pn_fut_volume_24h_usd"] = float(fut_vol)
            # 爆仓比：long_liquidation / short_liquidation → 多空平仓比
            ll = deriv.get("fut_liq_long_24h_usd")
            sl = deriv.get("fut_liq_short_24h_usd")
            if isinstance(ll, (int, float)) and isinstance(sl, (int, float)):
                tot = float(ll) + float(sl)
                if tot > 0:
                    coin["pn_fut_long_liq_ratio"] = round(float(ll) / tot, 4)
                    coin["pn_fut_liquidation_total_usd"] = round(tot, 2)
            # 地维度波动率周期 proxy：合约爆仓/总市值比 → 越高=大波动
            liq = deriv.get("fut_liq_total_24h_usd")
            if isinstance(liq, (int, float)):
                coin["pn_fut_liquidation_24h_usd"] = float(liq)
                if isinstance(cap, (int, float)) and float(cap) > 0:
                    liq_ratio = float(liq) / float(cap)
                    # 映射 0%~0.2% → 0~1 ATR percentile 代理
                    atr_proxy = max(0.0, min(1.0, liq_ratio * 500))
                    coin["pn_liq_atr_percentile_proxy"] = round(atr_proxy, 4)
                    # 补强 atr_percentile（若无后置层 regime 的真实值时用）
                    if not coin.get("atr_percentile"):
                        coin["atr_percentile"] = atr_proxy

        # ============================================================
        # exchanges_whales：交易所余额 + 巨鲸（crypto 专用）
        # ============================================================
        exch = _m("exchanges_whales")
        if exch and asset_cls == "crypto_usdt":
            netflow = exch.get("whale_netflow_to_ex_usd")
            if isinstance(netflow, (int, float)):
                coin["pn_whale_netflow_to_ex_usd"] = float(netflow)
                # 地维度：交易所净流入(+)=抛压(减分)；净流出(-)=吸筹(加分)
                # 映射 ±500M → [-1, 1] → 支撑阻力强度
                cap = (raw.get("panewslab:overview_market:m") or {}).get("global_market_cap_usd")
                if isinstance(cap, (int, float)) and float(cap) > 0:
                    pct_of_cap = float(netflow) / float(cap)
                    coin["pn_whale_netflow_cap_pct"] = round(pct_of_cap * 100, 6)
            to_ex = exch.get("whale_24h_to_ex_usd")
            from_ex = exch.get("whale_24h_from_ex_usd")
            if isinstance(to_ex, (int, float)):
                coin["pn_whale_24h_to_ex_usd"] = float(to_ex)
            if isinstance(from_ex, (int, float)):
                coin["pn_whale_24h_from_ex_usd"] = float(from_ex)
            # 交易所 BTC 余额 30 日变化 → 地维度支撑强度
            btc_chg30 = exch.get("ex_bal_BTC_chg30d_pct")
            if isinstance(btc_chg30, (int, float)):
                coin["pn_ex_bal_btc_chg30d_pct"] = float(btc_chg30)

        # ============================================================
        # holdings_onchain_funds：链上资金（crypto 专用）
        # ============================================================
        hold = _m("holdings_onchain_funds")
        if hold and asset_cls == "crypto_usdt":
            tbtc = hold.get("holdings_treasury_btc_sum")
            if isinstance(tbtc, (int, float)):
                coin["pn_holdings_treasury_btc"] = float(tbtc)
            trs_count = hold.get("holdings_treasury_count")
            if isinstance(trs_count, (int, float)):
                coin["pn_holdings_treasury_count"] = int(trs_count)
            trs_count = hold.get("holdings_treasury_count")
            if isinstance(trs_count, (int, float)):
                coin["pn_holdings_treasury_count"] = int(trs_count)
            # DeFi / 公链 广度命中
            defi_hit = hold.get("holdings_defi-fundamental-breadth_hit")
            chain_hit = hold.get("holdings_public-chain-activity-breadth_hit")
            hits = [v for v in (defi_hit, chain_hit) if isinstance(v, bool)]
            if hits:
                coin["pn_holdings_breadth_hit_ratio"] = (
                    round(sum(1 for h in hits if h) / len(hits), 4)
                )
            # 链上基本面广度 coverageStatus
            for k_src, k_dst in [
                ("holdings_defi-fundamental-breadth_rangeStatus",
                 "pn_defi_breadth_range"),
                ("holdings_public-chain-activity-breadth_rangeStatus",
                 "pn_chain_breadth_range"),
            ]:
                v = hold.get(k_src)
                if v:
                    coin[k_dst] = str(v)

        return coin

    # ==================================================================
    # helpers
    # ==================================================================
    @staticmethod
    def _safe_first(recs: List[Any]) -> Any:
        return recs[0] if isinstance(recs, list) and recs else None

    @classmethod
    def _safe_first_metric(cls, recs: List[Any]) -> Optional[Dict[str, Any]]:
        first = cls._safe_first(recs)
        if first is None:
            return None
        m = getattr(first, "metrics", None)
        return dict(m) if isinstance(m, dict) else None

    @staticmethod
    def _val(metric: Optional[Dict[str, Any]], key: str) -> Any:
        if not isinstance(metric, dict):
            return None
        return metric.get(key)

    # ------------------------------------------------------------------
    # 衍生：美林时钟（4 象限，对齐 _MERRILL_PHASE_SCORES key）
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_merrill(cpi: Any, indpro: Any) -> Optional[str]:
        if not isinstance(cpi, (int, float)) or not isinstance(indpro, (int, float)):
            return None
        # 通胀方向：CPI > 100 视为历史上升中（简化 proxy）
        # 这里更稳妥：用 CPI 指数相对 250 的大致基准 → 粗判通胀是否偏高
        infl_up = cpi >= 250.0
        # 增长方向：INDPRO 相对 100 → >100 视为↑
        grow_up = indpro >= 100.0
        if grow_up and not infl_up: return "RECOVERY"    # 复苏
        if grow_up and infl_up:     return "OVERHEAT"    # 过热
        if not grow_up and infl_up: return "STAGFLATION" # 滞胀
        return "REFLATION"                              # 衰退/再通

    # ------------------------------------------------------------------
    # 衍生：流动性评分 [0,1]（对齐 FiveDomainFeatureComputer._compute_liquidity_cycle_score）
    # 利率低→加分；M2 高→加分；联储表扩张→加分
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_liquidity_score(
        fedfunds: Any, m2_yoy: Any, bs_trillion: Any
    ) -> Optional[float]:
        scores = []
        # 利率：0%→1.0, 6%→0.0, 线性
        if isinstance(fedfunds, (int, float)):
            scores.append(max(0.0, min(1.0, (6.0 - float(fedfunds)) / 6.0)))
        # M2 同比：-5%→0.0, +10%→1.0（简化）
        if isinstance(m2_yoy, (int, float)):
            scores.append(max(0.0, min(1.0, (float(m2_yoy) + 5.0) / 15.0)))
        # 联储表：4T→0.2, 9T→1.0
        if isinstance(bs_trillion, (int, float)):
            scores.append(max(0.0, min(1.0, (float(bs_trillion) - 4.0) / 5.0)))
        if not scores:
            return None
        # 利率权重 50%，M2 25%，联储表 25%
        if len(scores) == 1:
            return float(scores[0])
        if len(scores) == 2:
            # 缺哪一项就加权剩下的
            return float(0.5 * scores[0] + 0.5 * scores[1])
        return float(0.5 * scores[0] + 0.25 * scores[1] + 0.25 * scores[2])

    # ------------------------------------------------------------------
    # 衍生：D10 政策情绪 → [0,1]
    # ------------------------------------------------------------------
    @classmethod
    def _sentiment_score(cls, events: List[Any]) -> float:
        if not events:
            return 0.5  # 缺数据中性
        pos = 0
        total = 0
        for e in events:
            if not isinstance(e, dict):
                continue
            text = f"{e.get('title','')} {e.get('content','')}".lower()
            if not text.strip():
                continue
            total += 1
            p = sum(1 for w in _POS_WORDS if w.lower() in text)
            n = sum(1 for w in _NEG_WORDS if w.lower() in text)
            if p > n: pos += 1
            elif p < n: pass  # 中性不加分
            else: pos += 0.5   # 打平加半
        if total == 0:
            return 0.5
        return round(max(0.0, min(1.0, pos / total)), 4)
