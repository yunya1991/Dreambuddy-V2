"""Panewslab (PAData) data collector — 为易经战略层五维提供全景市场数据。

覆盖板块（对应 data.panewslab.com 首页锚点）：
  overview         市场总览（总市值/BTC市值/情绪/DeFi TVL/稳定币/RWA + 30日趋势）
  cycle            周期判断（12 项抄底指标 + 4 个 omnitools 扩散广度/流动性脉冲）
  etf              ETF 与机构（BTC/ETH ETF 资金流 + 上市公司 BTC 持仓）
  stable_rwa       稳定币与 RWA（RWA 协议 TVL 分类 + 稳定币流动性脉冲）
  derivatives      现货与衍生品（CoinGlass 现货 200 币 + 合约 100 币）
  exchanges        交易所（BTC/ETH/USDT 余额 + 透明度 + 巨鲸转账）
  holdings         链上资金（机构 BTC 持仓聚合 + 巨鲸转账 + DeFi 广度 proxy）
  macro_us         美股与宏观（SP500/纳斯达克/VIX/美债10Y/美元指数/联邦基金利率）
  all              以上 8 个板块一次性抓取（默认）

接口来源：
  - https://data.panewslab.com/api/*  （PAData 自身聚合：CoinGlass/CoinGecko/DefiLlama/财政部）
  - https://metrics.omnitools.ai/api/features/*  （扩散广度/流动性脉冲特征）
  - https://meme-metrics.omnitools.ai/api/features/meme-risk-appetite-v2  （MEME 风险偏好）

fail-open：除 429 抛 RateLimitError 外，所有 HTTP/解析异常 → 静默降级（部分 route 返回空 Record 或跳过），
确保交易热路径不被阻塞（对应 H1 FAIL-OPEN 铁律）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from data_center.collectors._base import BaseCollector
from data_center.core.contract import DataRecord, validate_record
from data_center.core.errors import RateLimitError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_PANEWSLAB_BASE = "https://data.panewslab.com"
_OMNITOOLS_BASE = "https://metrics.omnitools.ai"
_MEME_OMNITOOLS_BASE = "https://meme-metrics.omnitools.ai"

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://data.panewslab.com/",
    "Accept": "application/json, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 8 大板块 → 抓取路由
_VALID_ROUTES = {
    "overview", "cycle", "etf", "stable_rwa",
    "derivatives", "exchanges", "holdings", "macro_us",
    "all",
}

# 美股与宏观固定 series id（data.panewslab.com 首页 data-series）
_MACRO_SERIES = [
    ("market-close", "SP500",      "标普500"),
    ("market-close", "NASDAQCOM",  "纳斯达克综合"),
    ("fred",         "VIXCLS",     "VIX 波动率"),
    ("fred",         "DGS10",      "美国10年期国债收益率"),
    ("fred",         "DTWEXBGS",   "广义贸易加权美元指数"),
    ("fred",         "DFF",        "有效联邦基金利率"),
]

# 扩散广度/链上特征（omnitools 直连）
_OMNITOOLS_FEATURES = [
    ("defi-fundamental-breadth",   "DeFi 基本面扩散广度"),
    ("stablecoin-liquidity-pulse", "稳定币流动性脉冲"),
    ("public-chain-activity-breadth", "公链活跃扩散广度"),
]
_MEME_FEATURE = ("meme-risk-appetite-v2", "跨链 MEME 风险偏好指数")


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


class PanewslabCollector(BaseCollector):
    """PAData 数据中心采集器（SDK 轨）。

    usage:
        dc.fetch("chain", source="panewslab", route="all")
        dc.fetch("chain", source="panewslab", route="overview")
    """

    source = "panewslab"
    category = "chain"

    # ------------------------------------------------------------------
    # 基础能力
    # ------------------------------------------------------------------
    def is_available(self) -> bool:
        # 公共 API 无需 Key → 默认 true，网络由 _get() 内部降级
        return True

    def fetch(self, params: dict) -> list[DataRecord]:
        route = (params.get("route") or "all").strip().lower()
        if route not in _VALID_ROUTES:
            return []
        try:
            if route == "all":
                recs: list[DataRecord] = []
                for r in ("overview", "cycle", "etf", "stable_rwa",
                          "derivatives", "exchanges", "holdings", "macro_us"):
                    try:
                        recs.extend(self._dispatch_one(r))
                    except RateLimitError:
                        raise
                    except Exception:
                        # 单板块失败不影响其他板块
                        continue
                return recs
            return self._dispatch_one(route)
        except RateLimitError:
            raise
        except Exception:
            # fail-open：所有未预期异常 → 空列表
            return []

    # ------------------------------------------------------------------
    # 路由分发
    # ------------------------------------------------------------------
    def _dispatch_one(self, route: str) -> list[DataRecord]:
        if route == "overview":       return [self._fetch_overview()]
        if route == "cycle":          return [self._fetch_cycle()]
        if route == "etf":            return [self._fetch_etf()]
        if route == "stable_rwa":     return [self._fetch_stable_rwa()]
        if route == "derivatives":    return [self._fetch_derivatives()]
        if route == "exchanges":      return [self._fetch_exchanges()]
        if route == "holdings":       return [self._fetch_holdings()]
        if route == "macro_us":       return [self._fetch_macro_us()]
        return []

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _get(url: str, timeout: int = 20) -> Any:
        """GET JSON。非 200 抛 RuntimeError；429 抛 RateLimitError；解析失败抛 ParseError。"""
        resp = requests.get(url, headers=_DEFAULT_HEADERS, timeout=timeout)
        if resp.status_code == 429:
            raise RateLimitError(f"Panewslab 429: {url}")
        if not resp.ok:
            raise RuntimeError(f"Panewslab HTTP {resp.status_code}: {url}")
        try:
            return resp.json()
        except (ValueError, TypeError) as e:
            from data_center.core.errors import ParseError
            raise ParseError(f"Panewslab 非 JSON: {url[:80]} → {e}")

    # ==================================================================
    # 板块实现
    # ==================================================================

    # --- 1. 市场总览 ---------------------------------------------------
    def _fetch_overview(self) -> DataRecord:
        trends = self._get(f"{_PANEWSLAB_BASE}/api/overview-trends?v=2")
        quotes = self._get(f"{_PANEWSLAB_BASE}/api/market/quotes")
        ts = _now_iso()

        cur = trends.get("current", {}) or {}
        global_ = cur.get("global", {}) or {}
        series = trends.get("series", {}) or {}
        coins_src = quotes.get("coins", []) or []

        # Top 10 币种
        top10 = []
        for c in coins_src[:10]:
            top10.append({
                "symbol": c.get("symbol"),
                "price": c.get("price"),
                "change24_pct": c.get("change24"),
                "market_cap_usd": c.get("marketCap"),
                "volume_24h_usd": c.get("volume"),
            })

        # 30 日趋势（缩略时序列：取 btc + global_cap 前 3 个点 + 后 3 个点）
        btc_series = series.get("btc", []) or []
        global_series = series.get("global", []) or []

        metrics: dict = {
            "global_market_cap_usd":    global_.get("marketCap"),
            "global_change24_pct":      global_.get("change24"),
            "btc_dominance_pct":        global_.get("btcDominance"),
            "as_of":                    trends.get("asOf"),
            "source_name":              trends.get("source"),
            "trend_stale":              bool(trends.get("stale")),
            "quotes_stale":             bool(quotes.get("stale")),
            "quotes_as_of":             quotes.get("asOf"),
            "coins_count":              len(coins_src),
        }
        # Top10 扁平到 metrics（符合 contract 仅 number/string）
        for i, c in enumerate(top10):
            if c.get("symbol"):
                metrics[f"top{i+1}_symbol"] = c["symbol"] or ""
                if c.get("price") is not None:       metrics[f"top{i+1}_price"] = float(c["price"])
                if c.get("change24_pct") is not None: metrics[f"top{i+1}_chg24pct"] = float(c["change24_pct"])
                if c.get("market_cap_usd") is not None: metrics[f"top{i+1}_mcap"] = float(c["market_cap_usd"])

        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="overview_market",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "btc_price", "series": [
                    {"ts": p.get("timestamp"), "v": p.get("value")}
                    for p in btc_series
                ]},
                {"name": "global_cap", "series": [
                    {"ts": p.get("timestamp"), "v": p.get("value")}
                    for p in global_series
                ]},
                {"name": "coins_top10", "items": top10},
            ],
            raw={
                "overview_trends": trends,
                "market_quotes": {"coins_count": len(coins_src), "coins": coins_src[:30]},
            },
        )
        validate_record(rec)
        return rec

    # --- 2. 周期判断 ---------------------------------------------------
    def _fetch_cycle(self) -> DataRecord:
        bottom = self._get(f"{_PANEWSLAB_BASE}/api/features/bottom-signals")
        ts = _now_iso()

        # 抄底指标汇总
        items = bottom.get("items", []) or []
        summary = bottom.get("summary", {}) or {}
        hit_count = sum(1 for it in items if it.get("hit") is True)
        total_count = len(items)

        # omnitools 扩散广度（并行友好，这里顺序拉；失败跳过）
        breadth = {}
        for slug, _name in _OMNITOOLS_FEATURES:
            try:
                breadth[slug] = self._get(f"{_OMNITOOLS_BASE}/api/features/{slug}")
            except Exception:
                continue
        try:
            breadth[_MEME_FEATURE[0]] = self._get(
                f"{_MEME_OMNITOOLS_BASE}/api/features/{_MEME_FEATURE[0]}"
            )
        except Exception:
            pass

        metrics: dict = {
            "bottom_hit_count":      hit_count,
            "bottom_total_count":    total_count,
            "bottom_hit_ratio_pct":  round(100 * hit_count / total_count, 2) if total_count else 0.0,
            "as_of":                 bottom.get("asOf"),
            "source":                bottom.get("source"),
        }
        # 逐个抄底指标：slug → (value, hit) 扁平
        for it in items:
            slug = it.get("slug")
            if not slug:
                continue
            v = it.get("value")
            if isinstance(v, (int, float, str)):
                metrics[f"bottom_{slug}_value"] = v
            metrics[f"bottom_{slug}_hit"] = bool(it.get("hit"))
            range_status = it.get("rangeStatus")
            if range_status:
                metrics[f"bottom_{slug}_range"] = str(range_status)

        # omnitools 特征入 metrics（currentRange / hit / thresholdValue）
        for slug, feat in breadth.items():
            if not isinstance(feat, dict):
                continue
            for k in ("currentRange", "rangeStatus"):
                if feat.get(k) is not None:
                    metrics[f"feat_{slug}_{k}"] = str(feat[k])
            tv = feat.get("thresholdValue")
            if isinstance(tv, (int, float)):
                metrics[f"feat_{slug}_threshold"] = float(tv)
            if feat.get("hit") is not None:
                metrics[f"feat_{slug}_hit"] = bool(feat["hit"])

        # timeseries：逐项指标详细信息
        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="cycle_signals",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "bottom_signals", "items": [
                    {"slug": i.get("slug"), "name": i.get("name"),
                     "value": i.get("value"), "hit": i.get("hit"),
                     "threshold": i.get("thresholdValue"),
                     "explanation": i.get("explanation"),
                     "source": i.get("source")}
                    for i in items
                ]},
                {"name": "omnitools_features", "items": [
                    {"slug": s, "name": f.get("name"),
                     "current_range": f.get("currentRange"),
                     "range_status": f.get("rangeStatus"),
                     "hit": f.get("hit")}
                    for s, f in breadth.items() if isinstance(f, dict)
                ]},
            ],
            raw={
                "bottom_signals_summary": summary,
                "bottom_signals_items_count": len(items),
                "omnitools_features": list(breadth.keys()),
                "raw_items": items[:30],
                "raw_breadth": {k: {kk: vv for kk, vv in v.items() if kk in
                                   ("slug","name","explanation","thresholdValue","hit","currentRange","rangeStatus")}
                                for k, v in breadth.items() if isinstance(v, dict)},
            },
        )
        validate_record(rec)
        return rec

    # --- 3. ETF 与机构 -------------------------------------------------
    def _fetch_etf(self) -> DataRecord:
        etf = self._get(f"{_PANEWSLAB_BASE}/api/coinglass/etf?v=3")
        treasury = self._get(f"{_PANEWSLAB_BASE}/api/treasury/bitcoin")
        ts = _now_iso()

        mk = etf.get("markets", {}) or {}
        btc = mk.get("btc", {}) or {}
        eth = mk.get("eth", {}) or {}
        companies = treasury.get("companies", []) or []

        # Top10 机构持仓
        top10_cos = sorted(
            companies, key=lambda c: float(c.get("holdings") or 0), reverse=True
        )[:10]

        metrics: dict = {
            "btc_etf_total_aum_usd":       btc.get("totalNetAssetsUsd"),
            "btc_etf_daily_flow_usd":      btc.get("dailyFlowUsd"),
            "btc_etf_as_of":               btc.get("asOf"),
            "eth_etf_total_aum_usd":       eth.get("totalNetAssetsUsd"),
            "eth_etf_daily_flow_usd":      eth.get("dailyFlowUsd"),
            "eth_etf_as_of":               eth.get("asOf"),
            "etf_stale":                   bool(etf.get("stale")),
            "treasury_companies_count":    len(companies),
            "treasury_stale":              bool(treasury.get("stale")),
            "treasury_as_of":              treasury.get("asOf"),
        }
        total_holdings = sum(float(c.get("holdings") or 0) for c in companies)
        metrics["treasury_total_btc_holdings"] = round(total_holdings, 4)
        for i, c in enumerate(top10_cos):
            name = (c.get("name") or c.get("symbol") or f"c{i}").replace(" ", "")[:16]
            metrics[f"co{i+1}_{name}_btc"] = round(float(c.get("holdings") or 0), 4)
            current_val = c.get("currentValueUsd")
            if isinstance(current_val, (int, float)):
                metrics[f"co{i+1}_{name}_value_usd"] = float(current_val)

        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="etf_institutional",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "btc_etf_series", "series": [
                    {"ts": p.get("date") or p.get("asOf"), "aum_usd": p.get("netAssetsUsd"),
                     "flow_usd": p.get("flowUsd")}
                    for p in (btc.get("series") or [])[:90]
                ]},
                {"name": "eth_etf_series", "series": [
                    {"ts": p.get("date") or p.get("asOf"), "aum_usd": p.get("netAssetsUsd"),
                     "flow_usd": p.get("flowUsd")}
                    for p in (eth.get("series") or [])[:90]
                ]},
                {"name": "top10_treasury", "items": [
                    {"name": c.get("name"), "symbol": c.get("symbol"),
                     "holdings_btc": c.get("holdings"),
                     "current_value_usd": c.get("currentValueUsd"),
                     "supply_share_pct": c.get("supplySharePercent")}
                    for c in top10_cos
                ]},
            ],
            raw={
                "etf_markets_keys": list(mk.keys()),
                "etf_source": etf.get("source"),
                "etf_funds_count": len(etf.get("funds", []) or []),
                "treasury_source": treasury.get("source"),
                "treasury_companies_count": len(companies),
            },
        )
        validate_record(rec)
        return rec

    # --- 4. 稳定币与 RWA ----------------------------------------------
    def _fetch_stable_rwa(self) -> DataRecord:
        rwa = self._get(f"{_PANEWSLAB_BASE}/api/defillama/rwa-tvl")
        # 稳定币脉冲（omnitools，失败降级）
        stable_pulse: dict = {}
        try:
            stable_pulse = self._get(
                f"{_OMNITOOLS_BASE}/api/features/stablecoin-liquidity-pulse"
            )
        except Exception:
            pass
        ts = _now_iso()

        totals = rwa.get("totals", {}) or {}
        cats = rwa.get("categories", []) or []
        top_prot = rwa.get("topProtocols", []) or []

        metrics: dict = {
            "rwa_tvl_usd":           totals.get("tvl"),
            "rwa_protocols":         totals.get("protocols"),
            "rwa_change1d_pct":      totals.get("change1dPct"),
            "rwa_change7d_pct":      totals.get("change7dPct"),
            "rwa_stale":             bool(rwa.get("stale")),
            "rwa_fetched_at":        rwa.get("fetchedAt"),
            "rwa_categories_count":  len(cats),
        }
        # top 5 RWA 分类
        cats_sorted = sorted(cats, key=lambda c: float(c.get("tvl") or 0), reverse=True)[:5]
        for i, c in enumerate(cats_sorted):
            name = (c.get("name") or f"cat{i}").replace(" ", "")[:20]
            metrics[f"rwa_cat{i+1}_{name}_tvl"] = float(c.get("tvl") or 0)
            metrics[f"rwa_cat{i+1}_{name}_chg7d"] = float(c.get("change7dPct") or 0)

        # 稳定币脉冲：如果有 rangeStatus / currentRange
        if isinstance(stable_pulse, dict):
            for k in ("currentRange", "rangeStatus"):
                if stable_pulse.get(k) is not None:
                    metrics[f"stable_pulse_{k}"] = str(stable_pulse[k])
            if stable_pulse.get("hit") is not None:
                metrics["stable_pulse_hit"] = bool(stable_pulse["hit"])

        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="stablecoin_rwa",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "rwa_categories", "items": [
                    {"name": c.get("name"), "tvl_usd": c.get("tvl"),
                     "protocols": c.get("protocols"),
                     "change7d_pct": c.get("change7dPct")}
                    for c in cats_sorted
                ]},
                {"name": "rwa_top_protocols", "items": [
                    {"name": p.get("name"), "tvl_usd": p.get("tvl"),
                     "category": p.get("category"),
                     "change7d_pct": p.get("change7dPct")}
                    for p in top_prot[:15]
                ]},
            ],
            raw={
                "rwa_source": rwa.get("source"),
                "rwa_source_url": rwa.get("sourceUrl"),
                "rwa_coverage": rwa.get("coverage"),
                "stablecoin_pulse": {
                    k: stable_pulse.get(k) for k in
                    ("slug","name","explanation","thresholdValue","currentRange","rangeStatus","hit")
                    if isinstance(stable_pulse, dict)
                },
            },
        )
        validate_record(rec)
        return rec

    # --- 5. 现货与衍生品 ----------------------------------------------
    def _fetch_derivatives(self) -> DataRecord:
        spot = self._get(f"{_PANEWSLAB_BASE}/api/coinglass/spot-markets")
        fut = self._get(f"{_PANEWSLAB_BASE}/api/coinglass/markets")
        ts = _now_iso()

        spot_coins = spot.get("coins", []) or []
        fut_coins = fut.get("coins", []) or []
        totals = fut.get("totals", {}) or {}

        metrics: dict = {
            "fut_volume_24h_usd":        totals.get("volumeUsd24h"),
            "fut_open_interest_usd":     totals.get("openInterestUsd"),
            "fut_liq_total_24h_usd":     totals.get("liquidationUsd24h"),
            "fut_liq_long_24h_usd":      totals.get("longLiquidationUsd24h"),
            "fut_liq_short_24h_usd":     totals.get("shortLiquidationUsd24h"),
            "fut_coins_count":           len(fut_coins),
            "spot_coins_count":          len(spot_coins),
            "spot_stale":                bool(spot.get("stale")),
            "fut_as_of":                 fut.get("asOf"),
            "spot_as_of":                spot.get("asOf"),
        }
        # Top 10 现货
        for i, c in enumerate(spot_coins[:10]):
            sym = c.get("symbol") or f"s{i}"
            price = c.get("priceUsd")
            mcap = c.get("marketCapUsd")
            if price is not None: metrics[f"spot{i+1}_{sym}_price"] = float(price)
            if mcap is not None:  metrics[f"spot{i+1}_{sym}_mcap"]  = float(mcap)
            chg24 = c.get("priceChangePercent24h")
            if chg24 is not None: metrics[f"spot{i+1}_{sym}_chg24"] = float(chg24)
            netflow = c.get("netFlowUsd24h")
            if netflow is not None: metrics[f"spot{i+1}_{sym}_nf24"] = float(netflow)

        # Top 10 合约
        for i, c in enumerate(fut_coins[:10]):
            sym = c.get("symbol") or f"f{i}"
            vol24 = c.get("volumeUsd24h")
            oi = c.get("openInterestUsd")
            if vol24 is not None: metrics[f"fut{i+1}_{sym}_vol24"] = float(vol24)
            if oi is not None:    metrics[f"fut{i+1}_{sym}_oi"]    = float(oi)
            liq = c.get("liquidationUsd24h")
            if liq is not None:   metrics[f"fut{i+1}_{sym}_liq24"] = float(liq)

        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="derivatives_spot",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "spot_markets", "items": [
                    {"symbol": c.get("symbol"), "price_usd": c.get("priceUsd"),
                     "market_cap_usd": c.get("marketCapUsd"),
                     "chg24_pct": c.get("priceChangePercent24h"),
                     "chg7d_pct": c.get("priceChangePercent7d"),
                     "volume_usd_24h": c.get("volumeUsd24h"),
                     "netflow_usd_24h": c.get("netFlowUsd24h")}
                    for c in spot_coins[:50]
                ]},
                {"name": "futures_markets", "items": [
                    {"symbol": c.get("symbol"), "price_usd": c.get("priceUsd"),
                     "volume_usd_24h": c.get("volumeUsd24h"),
                     "open_interest_usd": c.get("openInterestUsd"),
                     "liquidation_usd_24h": c.get("liquidationUsd24h"),
                     "long_liq_usd_24h": c.get("longLiquidationUsd24h"),
                     "short_liq_usd_24h": c.get("shortLiquidationUsd24h")}
                    for c in fut_coins[:50]
                ]},
            ],
            raw={
                "spot_source": spot.get("source"),
                "spot_coverage": spot.get("coverage"),
                "futures_source": fut.get("source"),
                "futures_coverage": fut.get("coverage"),
            },
        )
        validate_record(rec)
        return rec

    # --- 6. 交易所 -----------------------------------------------------
    def _fetch_exchanges(self) -> DataRecord:
        exchanges = self._get(f"{_PANEWSLAB_BASE}/api/coinglass/exchanges?v=4")
        whales = self._get(f"{_PANEWSLAB_BASE}/api/coinglass/whales")
        ts = _now_iso()

        balances = exchanges.get("balances", []) or []
        summary = exchanges.get("summary", {}) or {}
        transparency = exchanges.get("transparency", []) or []
        transfers = whales.get("transfers", []) or []

        metrics: dict = {
            "exchanges_as_of":       exchanges.get("asOf"),
            "whales_as_of":          whales.get("asOf"),
            "whales_transfer_count": len(transfers),
            "transparency_count":    len(transparency),
        }
        # 总览 summary（扁平 number/string）
        for k, v in summary.items():
            if isinstance(v, (int, float, str, bool)):
                metrics[f"ex_summary_{k}"] = v
        # 每种资产的交易所总额和 30d 变化
        for b in balances:
            sym = b.get("symbol") or "X"
            total = b.get("total")
            chg30d = b.get("changePercent30d")
            if isinstance(total, (int, float)):
                metrics[f"ex_bal_{sym}_total"] = float(total)
            if isinstance(chg30d, (int, float)):
                metrics[f"ex_bal_{sym}_chg30d_pct"] = float(chg30d)

        # 巨鲸转账：按 symbol 聚合 24h 总量（只统计最近 1 天的）
        whale_by_symbol: dict[str, float] = {}
        whale_to_ex_usd = 0.0
        whale_from_ex_usd = 0.0
        for t in transfers:
            amt = float(t.get("amountUsd") or 0)
            sym = (t.get("symbol") or "UNK")
            whale_by_symbol[sym] = whale_by_symbol.get(sym, 0.0) + amt
            to_ = str(t.get("to") or "")
            from_ = str(t.get("from") or "")
            if any(ex in to_ for ex in ("Binance", "Coinbase", "Kraken", "OKX", "Huobi", "Bybit")):
                whale_to_ex_usd += amt
            if any(ex in from_ for ex in ("Binance", "Coinbase", "Kraken", "OKX", "Huobi", "Bybit")):
                whale_from_ex_usd += amt
        metrics["whale_24h_to_ex_usd"] = round(whale_to_ex_usd, 2)
        metrics["whale_24h_from_ex_usd"] = round(whale_from_ex_usd, 2)
        metrics["whale_netflow_to_ex_usd"] = round(whale_from_ex_usd - whale_to_ex_usd, 2)
        top_whale_syms = sorted(whale_by_symbol.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for i, (sym, amt) in enumerate(top_whale_syms):
            metrics[f"whale{i+1}_{sym}_usd"] = round(amt, 2)

        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="exchanges_whales",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "exchange_balance_series", "items": [
                    {"symbol": b.get("symbol"), "total": b.get("total"),
                     "change30d_pct": b.get("changePercent30d"),
                     "series_len": len(b.get("series") or [])}
                    for b in balances
                ]},
                {"name": "transparency_scores", "items": [
                    {"exchange": t.get("name"), "score": t.get("score"),
                     "grade": t.get("grade"), "rank": t.get("rank")}
                    for t in transparency[:20]
                ]},
                {"name": "whale_transfers_latest", "items": [
                    {"symbol": t.get("symbol"), "amount_usd": t.get("amountUsd"),
                     "quantity": t.get("quantity"), "from": t.get("from"),
                     "to": t.get("to"), "chain": t.get("chain"), "as_of": t.get("asOf")}
                    for t in transfers[:30]
                ]},
            ],
            raw={
                "exchanges_source": exchanges.get("source"),
                "exchanges_coverage": exchanges.get("coverage"),
                "whales_source": whales.get("source"),
                "whales_coverage": whales.get("coverage"),
            },
        )
        validate_record(rec)
        return rec

    # --- 7. 链上资金 ---------------------------------------------------
    def _fetch_holdings(self) -> DataRecord:
        """链上资金：聚合机构BTC持仓 + 巨鲸转账 + DeFi/公链扩散广度 proxy。

        entities/activity 精细地址级数据由前端 mock，不暴露 API；
        这里用可公开访问的等价数据源聚合，避免对 Playwright 的强依赖。
        """
        treasury = self._get(f"{_PANEWSLAB_BASE}/api/treasury/bitcoin")
        whales = self._get(f"{_PANEWSLAB_BASE}/api/coinglass/whales")
        ts = _now_iso()

        companies = treasury.get("companies", []) or []
        transfers = whales.get("transfers", []) or []

        # 按国家聚合持仓
        by_country: dict[str, float] = {}
        for c in companies:
            country = c.get("country") or "Unknown"
            by_country[country] = by_country.get(country, 0.0) + float(c.get("holdings") or 0)

        # omnitools 两个广度指标（proxy 链上基本面 & 活跃度）
        breadth_raw: dict = {}
        for slug, _ in (("defi-fundamental-breadth", "DeFi"),
                        ("public-chain-activity-breadth", "公链")):
            try:
                breadth_raw[slug] = self._get(f"{_OMNITOOLS_BASE}/api/features/{slug}")
            except Exception:
                continue

        metrics: dict = {
            "holdings_treasury_count":    len(companies),
            "holdings_treasury_btc_sum":  round(sum(float(c.get("holdings") or 0) for c in companies), 4),
            "holdings_transfers_count":   len(transfers),
            "holdings_as_of_treasury":    treasury.get("asOf"),
            "holdings_as_of_whales":      whales.get("asOf"),
        }
        # Top5 国家持仓
        top_countries = sorted(by_country.items(), key=lambda kv: kv[1], reverse=True)[:5]
        for i, (country, amt) in enumerate(top_countries):
            metrics[f"holdings_country{i+1}_{country}_btc"] = round(amt, 4)

        # breadth：取 rangeStatus / 命中情况
        for slug, feat in breadth_raw.items():
            if not isinstance(feat, dict):
                continue
            for k in ("currentRange", "rangeStatus", "coverageStatus", "coverageLabel"):
                if feat.get(k) is not None:
                    metrics[f"holdings_{slug}_{k}"] = str(feat[k])
            tv = feat.get("thresholdValue")
            if isinstance(tv, (int, float)):
                metrics[f"holdings_{slug}_threshold"] = float(tv)
            if feat.get("hit") is not None:
                metrics[f"holdings_{slug}_hit"] = bool(feat["hit"])

        rec = DataRecord(
            source="panewslab",
            category="chain",
            sub_category="holdings_onchain_funds",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=[
                {"name": "treasury_by_country", "items": [
                    {"country": c, "holdings_btc": round(a, 4)}
                    for c, a in top_countries
                ]},
                {"name": "top20_whale_transfers", "items": [
                    {"symbol": t.get("symbol"), "amount_usd": t.get("amountUsd"),
                     "from": t.get("from"), "to": t.get("to"),
                     "chain": t.get("chain"), "as_of": t.get("asOf")}
                    for t in transfers[:20]
                ]},
                {"name": "breadth_features", "items": [
                    {"slug": s, **{k: f.get(k) for k in
                     ("name","currentRange","rangeStatus","coverageStatus","hit") if isinstance(f, dict)}}
                    for s, f in breadth_raw.items() if isinstance(f, dict)
                ]},
            ],
            raw={
                "treasury_source": treasury.get("source"),
                "treasury_coverage": treasury.get("coverage"),
                "whales_source": whales.get("source"),
                "whales_coverage": whales.get("coverage"),
                "breadth_features": list(breadth_raw.keys()),
            },
        )
        validate_record(rec)
        return rec

    # --- 8. 美股与宏观 -------------------------------------------------
    def _fetch_macro_us(self) -> DataRecord:
        ts = _now_iso()
        series_results: list[dict] = []
        metrics: dict = {}

        for endpoint, sid, label in _MACRO_SERIES:
            url = f"{_PANEWSLAB_BASE}/api/macro/{endpoint}?id={sid}&v=11"
            try:
                data = self._get(url)
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("status") != "live":
                continue
            value = data.get("value")
            obs = data.get("observations") or []
            metrics[f"us_{sid}_value"] = value if isinstance(value, (int, float, str)) else str(value)
            chg = data.get("change")
            if isinstance(chg, (int, float)):
                metrics[f"us_{sid}_chg"] = float(chg)
            chg_pct = data.get("changePct")
            if isinstance(chg_pct, (int, float)):
                metrics[f"us_{sid}_chg_pct"] = float(chg_pct)
            metrics[f"us_{sid}_as_of"] = data.get("asOf")
            metrics[f"us_{sid}_name"] = str(data.get("name") or label)
            metrics[f"us_{sid}_obs_count"] = len(obs) if isinstance(obs, list) else 0
            series_results.append({
                "id": sid, "label": label,
                "name": data.get("name"), "source": data.get("source"),
                "value": value, "change": data.get("change"),
                "change_pct": data.get("changePct"), "as_of": data.get("asOf"),
                "obs_count": len(obs) if isinstance(obs, list) else 0,
                "observations_tail": (obs[-10:] if isinstance(obs, list) and len(obs) > 10 else obs)
                                     if isinstance(obs, list) else [],
            })

        metrics["us_series_live_count"] = len(series_results)

        rec = DataRecord(
            source="panewslab",
            category="macro",
            sub_category="macro_us_stocks",
            timestamp=ts,
            metrics=metrics,
            events=[],
            timeseries=series_results,
            raw={
                "series_attempted": [s[1] for s in _MACRO_SERIES],
                "series_live": [s["id"] for s in series_results],
            },
        )
        validate_record(rec)
        return rec
