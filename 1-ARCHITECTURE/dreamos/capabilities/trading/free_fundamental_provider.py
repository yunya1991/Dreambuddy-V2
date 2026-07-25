"""
免费基本面数据源 — 不依赖 Tavily，使用公开免费 API

免费数据源清单:
    - Hyperliquid 公开 API: funding_rate, open_interest（衍生品）
    - CoinGecko 公开 API: market_cap, volume_24h, price_change_*, ath（市场/估值）
    - alternative.me: Fear & Greed Index（情绪）
    - Blockchain.info: n_tx, hash_rate, difficulty（链上基础数据）

用途:
    当 Tavily API Key 无效或缺失时，作为降级数据源，
    为 F 节点提供至少一部分真实基本面数据。
"""

from __future__ import annotations

import time
import logging
from typing import Dict, Any, Optional

import requests

logger = logging.getLogger(__name__)


class FreeFundamentalProvider:
    """免费基本面数据采集器

    全部使用公开免费 API，无需任何 API Key。
    数据精度不如付费源，但胜在真实、稳定、零成本。

    用法:
        provider = FreeFundamentalProvider()
        data = provider.collect_all(symbol="BTC")
    """

    CACHE_TTL = 1800  # 30 分钟缓存

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # symbol → (timestamp, data)
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "DreamOS-FreeFundamental/1.0",
            "Accept": "application/json",
        })

    def _http_get(self, url: str, params: Optional[Dict] = None, timeout: int = 10) -> Optional[Dict]:
        try:
            r = self._session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"免费数据源请求失败 [{url}]: {e}")
            return None

    def _http_post_json(self, url: str, payload: Dict, timeout: int = 10) -> Optional[Any]:
        try:
            r = self._session.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.debug(f"免费数据源 POST 失败 [{url}]: {e}")
            return None

    # ============================================================
    # 各数据源采集
    # ============================================================

    def collect_hyperliquid(self, symbol: str) -> Dict[str, Any]:
        """Hyperliquid 公开 API — 衍生品数据

        获取: funding_rate, open_interest, mark_price
        适用: BTC, ETH, SOL 等主流币种
        """
        result: Dict[str, Any] = {"_source": "hyperliquid"}
        try:
            data = self._http_post_json(
                "https://api.hyperliquid.xyz/info",
                {"type": "metaAndAssetCtxs"},
                timeout=8,
            )
            if not data or len(data) < 2:
                return {"_source": "hyperliquid_failed"}

            meta = data[0]
            ctxs = data[1]
            sym_upper = symbol.upper()

            for i, m in enumerate(meta.get("universe", [])):
                if m.get("name") == sym_upper and i < len(ctxs):
                    ctx = ctxs[i]
                    funding_h = float(ctx.get("funding", 0))  # 每小时 funding rate
                    result["funding_rate"] = funding_h
                    result["funding_rate_daily"] = funding_h * 24  # 折算日利率
                    result["funding_rate_annual"] = funding_h * 24 * 365  # 折算年利率
                    result["open_interest"] = float(ctx.get("openInterest", 0))
                    result["open_interest_usd"] = (
                        float(ctx.get("openInterest", 0)) * float(ctx.get("markPx", 0))
                    )
                    result["mark_price"] = float(ctx.get("markPx", 0))
                    result["_source"] = "hyperliquid"
                    break
            else:
                result["_source"] = "hyperliquid_symbol_not_found"
        except Exception as e:
            result["_source"] = f"hyperliquid_error:{type(e).__name__}"

        return result

    def collect_coingecko(self, symbol: str) -> Dict[str, Any]:
        """CoinGecko 公开 API — 市场/估值数据

        获取: market_cap, volume_24h, price_change_*, ath, circulating_supply
        免费 tier: 10-30 次/分钟，足够基本面采集
        """
        result: Dict[str, Any] = {"_source": "coingecko_failed"}

        coin_id_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "BNB": "binancecoin",
            "XRP": "ripple",
            "DOGE": "dogecoin",
            "ADA": "cardano",
            "AVAX": "avalanche-2",
            "LINK": "chainlink",
            "DOT": "polkadot",
            "MATIC": "polygon-ecosystem-token",
            "LTC": "litecoin",
            "ARB": "arbitrum",
            "OP": "optimism",
            "SUI": "sui",
            "SEI": "sei-network",
            "TON": "the-open-network",
        }
        coin_id = coin_id_map.get(symbol.upper())
        if not coin_id:
            return {"_source": "coingecko_unsupported_symbol"}

        try:
            data = self._http_get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                params={
                    "localization": "false",
                    "tickers": "false",
                    "community_data": "false",
                    "developer_data": "false",
                    "sparkline": "false",
                },
                timeout=10,
            )
            if not data:
                return result

            md = data.get("market_data", {})
            price = float(md.get("current_price", {}).get("usd", 0) or 0)
            market_cap = float(md.get("market_cap", {}).get("usd", 0) or 0)
            volume_24h = float(md.get("total_volume", {}).get("usd", 0) or 0)
            ath = float(md.get("ath", {}).get("usd", 0) or 0)
            ath_change_pct = float(md.get("ath_change_percentage", {}).get("usd", 0) or 0)
            circulating = float(md.get("circulating_supply", 0) or 0)
            total_supply = float(md.get("total_supply", 0) or 0)

            # 价格变动（有些是嵌套对象，有些是直接数值，兼容两种）
            def _get_pct(key):
                val = md.get(key, 0)
                if isinstance(val, dict):
                    return float(val.get("usd", 0) or 0)
                return float(val or 0)

            # 基础市场数据
            result["market_cap"] = market_cap
            result["market_cap_rank"] = data.get("market_cap_rank", 0)
            result["volume_24h"] = volume_24h
            result["volume_market_cap_ratio"] = volume_24h / market_cap if market_cap > 0 else 0
            result["circulating_supply"] = circulating
            result["total_supply"] = total_supply
            result["supply_ratio"] = circulating / total_supply if total_supply > 0 else 1.0

            # 价格变动
            result["price_change_24h_pct"] = _get_pct("price_change_percentage_24h")
            result["price_change_7d_pct"] = _get_pct("price_change_percentage_7d")
            result["price_change_30d_pct"] = _get_pct("price_change_percentage_30d")
            result["price_change_1y_pct"] = _get_pct("price_change_percentage_1y")

            # ATH 相关
            result["all_time_high"] = ath
            result["ath_drop_pct"] = ath_change_pct  # 负值表示距ATH跌幅
            result["current_price"] = price

            # 市值占比（仅 BTC 有意义的计算）
            if symbol.upper() == "BTC":
                result["market_dominance"] = self._btc_dominance()
            else:
                result["market_dominance"] = 0.0

            result["_source"] = "coingecko"
        except Exception as e:
            result["_source"] = f"coingecko_error:{type(e).__name__}"

        return result

    def _btc_dominance(self) -> float:
        """BTC 市值占比（单独请求）"""
        try:
            data = self._http_get(
                "https://api.coingecko.com/api/v3/global",
                timeout=8,
            )
            if data:
                return float(data.get("data", {}).get("market_cap_percentage", {}).get("btc", 0))
        except Exception:
            pass
        return 0.0

    def collect_fear_greed(self) -> Dict[str, Any]:
        """alternative.me Fear & Greed Index — 情绪数据

        完全免费，无需 Key。
        """
        result: Dict[str, Any] = {"_source": "alternative_me_failed"}
        try:
            data = self._http_get(
                "https://api.alternative.me/fng/?limit=30",
                timeout=8,
            )
            if not data or not data.get("data"):
                return result

            history = data["data"]
            latest = history[0]
            result["fear_greed_index"] = int(latest.get("value", 50))
            result["fear_greed_classification"] = latest.get("value_classification", "Neutral")

            # 计算近 7 天趋势
            if len(history) >= 7:
                avg_7d = sum(int(h.get("value", 50)) for h in history[:7]) / 7
                result["fear_greed_7d_avg"] = round(avg_7d, 1)
                result["fear_greed_trend_7d"] = round(
                    result["fear_greed_index"] - avg_7d, 1
                )

            # 近 30 天极值
            if len(history) >= 30:
                values_30d = [int(h.get("value", 50)) for h in history[:30]]
                result["fear_greed_30d_high"] = max(values_30d)
                result["fear_greed_30d_low"] = min(values_30d)

            result["_source"] = "alternative_me"
        except Exception as e:
            result["_source"] = f"alternative_me_error:{type(e).__name__}"

        return result

    def collect_blockchain(self) -> Dict[str, Any]:
        """Blockchain.info — BTC 链上基础数据

        完全免费，无需 Key。仅限 BTC。
        """
        result: Dict[str, Any] = {"_source": "blockchain_info_failed"}
        try:
            data = self._http_get(
                "https://blockchain.info/stats?format=json",
                timeout=10,
            )
            if not data:
                return result

            result["chain_tx_count"] = int(data.get("n_tx", 0))
            result["hash_rate"] = float(data.get("hash_rate", 0))
            result["difficulty"] = float(data.get("difficulty", 0))
            result["total_btc_sent_sat"] = float(data.get("total_btc_sent", 0))
            result["miners_revenue"] = float(data.get("miners_revenue_usd", 0))
            result["market_price"] = float(data.get("market_price_usd", 0))
            result["trade_volume_usd"] = float(data.get("trade_volume_usd", 0))
            result["_source"] = "blockchain_info"
        except Exception as e:
            result["_source"] = f"blockchain_info_error:{type(e).__name__}"

        return result

    # ============================================================
    # OKX 公开 API — 衍生品深度数据
    # ============================================================

    _OKX_SYMBOL_MAP = {
        "BTC": "BTC-USDT-SWAP",
        "ETH": "ETH-USDT-SWAP",
        "SOL": "SOL-USDT-SWAP",
        "BNB": "BNB-USDT-SWAP",
        "XRP": "XRP-USDT-SWAP",
        "DOGE": "DOGE-USDT-SWAP",
        "ADA": "ADA-USDT-SWAP",
        "AVAX": "AVAX-USDT-SWAP",
        "LINK": "LINK-USDT-SWAP",
        "DOT": "DOT-USDT-SWAP",
        "MATIC": "MATIC-USDT-SWAP",
        "LTC": "LTC-USDT-SWAP",
        "ARB": "ARB-USDT-SWAP",
        "OP": "OP-USDT-SWAP",
        "SUI": "SUI-USDT-SWAP",
    }

    def _okx_inst_id(self, symbol: str) -> Optional[str]:
        return self._OKX_SYMBOL_MAP.get(symbol.upper())

    def collect_okx(self, symbol: str) -> Dict[str, Any]:
        """OKX 公开 API — 衍生品深度数据

        获取:
          - 资金费率历史（趋势/分位数）
          - 强平订单（多头/空头清算量）
          - 持仓量（OKX 维度）
          - 标记价 + 基差

        全部为公开端点，无需认证。
        """
        result: Dict[str, Any] = {"_source": "okx_failed"}
        inst_id = self._okx_inst_id(symbol)
        if not inst_id:
            return {"_source": "okx_unsupported_symbol"}

        ccy = symbol.upper()
        uly = f"{ccy}-USDT"

        # 1. 资金费率历史
        fr_history = self._okx_funding_rate_history(inst_id)
        if fr_history is not None:
            result.update(fr_history)

        # 2. 强平订单
        liq = self._okx_liquidation(uly)
        if liq is not None:
            result.update(liq)

        # 3. 当前资金费率 + 标记价
        mark = self._okx_mark_price(inst_id)
        if mark is not None:
            result.update(mark)

        # 4. OKX 持仓量
        oi = self._okx_open_interest(uly)
        if oi is not None:
            result.update(oi)

        result["_source"] = "okx"
        return result

    def _okx_funding_rate_history(self, inst_id: str) -> Optional[Dict[str, Any]]:
        """资金费率历史 — 趋势/分位数分析"""
        try:
            data = self._http_get(
                "https://www.okx.com/api/v5/public/funding-rate-history",
                params={"instId": inst_id, "limit": "30"},
                timeout=8,
            )
            if not data or data.get("code") != "0":
                return None

            items = data["data"]
            if not items:
                return None

            rates = [float(item.get("fundingRate", 0) or 0) for item in items]
            current = rates[0] if rates else 0
            avg = sum(rates) / len(rates) if rates else 0
            sorted_rates = sorted(rates)
            # 分位数
            p25 = sorted_rates[int(len(sorted_rates) * 0.25)] if len(sorted_rates) > 4 else 0
            p75 = sorted_rates[int(len(sorted_rates) * 0.75)] if len(sorted_rates) > 4 else 0

            return {
                "okx_funding_rate_current": current,
                "okx_funding_rate_avg_30": avg,
                "okx_funding_rate_p25": p25,
                "okx_funding_rate_p75": p75,
                "okx_funding_rate_daily": current * 3,  # OKX 每 8h 结算一次
                "okx_funding_rate_annual": current * 3 * 365,
                "okx_funding_rate_trend": current - avg,  # 正=费率上升, 负=下降
                "okx_funding_rate_extreme": abs(current) > abs(p75) * 2 if p75 != 0 else False,
            }
        except Exception:
            return None

    def _okx_liquidation(self, uly: str) -> Optional[Dict[str, Any]]:
        """强平订单 — 多空清算量"""
        try:
            data = self._http_get(
                "https://www.okx.com/api/v5/public/liquidation-orders",
                params={"instType": "SWAP", "uly": uly, "state": "filled"},
                timeout=8,
            )
            if not data or data.get("code") != "0":
                return None

            items = data["data"]
            long_liq_sz = 0.0
            short_liq_sz = 0.0
            long_liq_count = 0
            short_liq_count = 0

            for item in items:
                for detail in item.get("details", []):
                    pos_side = detail.get("posSide", "")
                    sz = float(detail.get("sz", 0) or 0)
                    bk_px = float(detail.get("bkPx", 0) or 0)
                    sz_usd = sz * bk_px  # 粗略估算 USD 价值
                    if pos_side == "long":
                        long_liq_sz += sz_usd
                        long_liq_count += 1
                    elif pos_side == "short":
                        short_liq_sz += sz_usd
                        short_liq_count += 1

            total_liq = long_liq_sz + short_liq_sz
            # liquidation_pressure: 0-100, 多头强平占比越高压力越大（空头被迫平仓=看多）
            if total_liq > 0:
                liq_pressure = min(100, (total_liq / 1e6) * 10)  # 每 1M USD = 10 点
            else:
                liq_pressure = 0

            return {
                "okx_liquidation_long_usd": long_liq_sz,
                "okx_liquidation_short_usd": short_liq_sz,
                "okx_liquidation_total_usd": total_liq,
                "okx_liquidation_long_count": long_liq_count,
                "okx_liquidation_short_count": short_liq_count,
                # 映射到 F 节点字段
                "liquidation_long": long_liq_sz,
                "liquidation_short": short_liq_sz,
                "liquidation_pressure": liq_pressure,
            }
        except Exception:
            return None

    def _okx_mark_price(self, inst_id: str) -> Optional[Dict[str, Any]]:
        """标记价 + 当前资金费率"""
        try:
            data = self._http_get(
                "https://www.okx.com/api/v5/public/mark-price",
                params={"instId": inst_id},
                timeout=8,
            )
            if not data or data.get("code") != "0" or not data["data"]:
                return None

            item = data["data"][0]
            mark_px = float(item.get("markPx", 0) or 0)
            funding_rate = float(item.get("swapFundingRate", 0) or 0)

            return {
                "okx_mark_price": mark_px,
                "okx_current_funding_rate": funding_rate,
            }
        except Exception:
            return None

    def _okx_open_interest(self, uly: str) -> Optional[Dict[str, Any]]:
        """OKX 持仓量"""
        try:
            data = self._http_get(
                "https://www.okx.com/api/v5/public/open-interest",
                params={"instType": "SWAP", "uly": uly},
                timeout=8,
            )
            if not data or data.get("code") != "0" or not data["data"]:
                return None

            total_oi = 0.0
            total_oi_ccy = 0.0
            for item in data["data"]:
                total_oi += float(item.get("oi", 0) or 0)  # USD
                total_oi_ccy += float(item.get("oiCcy", 0) or 0)  # 币

            return {
                "okx_open_interest_usd": total_oi,
                "okx_open_interest_ccy": total_oi_ccy,
            }
        except Exception:
            return None

    # ============================================================
    # DefiLlama 公开 API — DeFi 链上资金流数据
    # ============================================================

    # symbol → DefiLlama chain 名称
    _LLAMA_CHAIN_MAP = {
        "BTC": "Bitcoin",
        "ETH": "Ethereum",
        "SOL": "Solana",
        "BNB": "BSC",
        "AVAX": "Avalanche",
        "ARB": "Arbitrum",
        "OP": "Optimism",
        "DOT": "Polkadot",
        "MATIC": "Polygon",
        "LTC": "Litecoin",
        "XRP": "XRP",
        "DOGE": "Dogecoin",
        "ADA": "Cardano",
        "SUI": "Sui",
        "SEI": "Sei",
        "TON": "Toncoin",
    }

    def _llama_chain_name(self, symbol: str) -> Optional[str]:
        return self._LLAMA_CHAIN_MAP.get(symbol.upper())

    def collect_defillama(self, symbol: str) -> Dict[str, Any]:
        """DefiLlama 公开 API — DeFi 链上资金流数据

        获取:
          - 稳定币总市值及变化率（F2 购买力指标）
          - DEX 交易量及变化率（F4 链上活跃度）
          - 链上 TVL 及变化率（F4 资金沉淀）

        全部免费，无需 Key。
        """
        result: Dict[str, Any] = {"_source": "defillama_failed"}

        # 1. 稳定币总市值（全局购买力指标）— 对所有币种都有意义
        sc = self._defillama_stablecoins()
        if sc is not None:
            result.update(sc)

        # 2. DEX 交易量 + 链上 TVL — 按链映射
        chain = self._llama_chain_name(symbol)
        if chain:
            dex = self._defillama_dex_volume(chain)
            if dex is not None:
                result.update(dex)

            tvl = self._defillama_chain_tvl(chain)
            if tvl is not None:
                result.update(tvl)
        else:
            result["_defillama_chain_unsupported"] = symbol

        if any(not k.startswith("_") for k in result):
            result["_source"] = "defillama"
        return result

    def _defillama_stablecoins(self) -> Optional[Dict[str, Any]]:
        """稳定币总市值及 7d/30d 变化率（F2 stablecoin_supply_change 数据源）

        F2 节点阈值: >2% 看多（购买力增加），<-2% 看空。
        """
        try:
            # stablecoins 子域名，返回历史每日总市值
            data = self._http_get(
                "https://stablecoins.llama.fi/stablecoincharts/all",
                timeout=12,
            )
            if not data or len(data) < 31:
                return None

            def _total_usd(item: Dict) -> float:
                """获取 USD 计价的稳定币总流通市值"""
                # totalCirculatingUSD 是按 peg 拆分的 dict，需汇总
                val = item.get("totalCirculatingUSD")
                if isinstance(val, dict):
                    return sum(float(v) for v in val.values())
                if val is not None:
                    return float(val)
                # 兜底：手动汇总 totalCirculating（各 peg 原币数量）
                total = 0.0
                for peg_vals in item.get("totalCirculating", {}).values():
                    total += float(peg_vals)
                return total

            latest = data[-1]
            total_now = _total_usd(latest)

            idx_7d = max(0, len(data) - 8)
            idx_30d = max(0, len(data) - 31)
            total_7d_ago = _total_usd(data[idx_7d])
            total_30d_ago = _total_usd(data[idx_30d])

            change_7d = (
                (total_now - total_7d_ago) / total_7d_ago * 100
                if total_7d_ago > 0 else 0
            )
            change_30d = (
                (total_now - total_30d_ago) / total_30d_ago * 100
                if total_30d_ago > 0 else 0
            )

            return {
                "stablecoin_supply_total": total_now,
                "stablecoin_supply_change": round(change_30d, 2),
                "stablecoin_supply_change_7d": round(change_7d, 2),
            }
        except Exception as e:
            logger.debug(f"DefiLlama 稳定币采集失败: {e}")
            return None

    def _defillama_dex_volume(self, chain: str) -> Optional[Dict[str, Any]]:
        """DEX 交易量及变化率（F4 chain_volume 数据源）

        F4 节点阈值: chain_volume_change >20% 看多（链上活动增加）。
        """
        try:
            # 全局 DEX 聚合交易量
            data = self._http_get(
                "https://api.llama.fi/overview/dexs?dataType=dailyVolume",
                timeout=12,
            )
            if not data:
                return None

            # 全局 DEX 24h / 7d 交易量
            total_24h = float(data.get("total24h", 0) or 0)
            total_7d = float(data.get("total7d", 0) or 0)

            # 计算 7d 平均日交易量，对比 24h
            avg_7d = total_7d / 7 if total_7d > 0 else 0
            # 24h vs 7d 均值的变化率
            change_vs_7d = (
                (total_24h - avg_7d) / avg_7d * 100
                if avg_7d > 0 else 0
            )

            return {
                "chain_volume": total_24h,
                "chain_volume_7d_avg": round(avg_7d, 0),
                "chain_volume_change": round(change_vs_7d, 2),
            }
        except Exception as e:
            logger.debug(f"DefiLlama DEX 交易量采集失败: {e}")
            return None

    def _defillama_chain_tvl(self, chain: str) -> Optional[Dict[str, Any]]:
        """链上 TVL 及变化率（F4 资金沉淀指标）

        用 TVL 变化近似 exchange_balance_change（资金沉淀↔交易所余额反向关系）。
        """
        try:
            data = self._http_get(
                f"https://api.llama.fi/v2/historicalChainTvl/{chain}",
                timeout=12,
            )
            if not data or len(data) < 31:
                return None

            tvl_now = float(data[-1].get("tvl", 0))
            idx_7d = max(0, len(data) - 8)
            idx_30d = max(0, len(data) - 31)
            tvl_7d_ago = float(data[idx_7d].get("tvl", 0))
            tvl_30d_ago = float(data[idx_30d].get("tvl", 0))

            tvl_change_7d = (
                (tvl_now - tvl_7d_ago) / tvl_7d_ago * 100
                if tvl_7d_ago > 0 else 0
            )
            tvl_change_30d = (
                (tvl_now - tvl_30d_ago) / tvl_30d_ago * 100
                if tvl_30d_ago > 0 else 0
            )

            # TVL 增长 = 链上资金沉淀增加 ≈ 交易所余额减少（场外积累）
            # 取反向近似：tvl_change 越高 → exchange_balance_change 越低
            exchange_balance_change_est = -tvl_change_7d

            return {
                "chain_tvl": tvl_now,
                "tvl_change_7d": round(tvl_change_7d, 2),
                "tvl_change_30d": round(tvl_change_30d, 2),
                # 派生：TVL 增长反向近似交易所余额变化
                "exchange_balance_change": round(exchange_balance_change_est, 2),
            }
        except Exception as e:
            logger.debug(f"DefiLlama TVL 采集失败: {e}")
            return None

    # ============================================================
    # 币安 Web3 公开 API — 社交情绪 & 聪明钱信号
    # 全部无需 Key，仅需特定 Header
    # ============================================================

    # symbol → 币安 Web3 搜索用的链上合约（BSC 上的锚定币，用于社交情绪查询）
    # BTC/ETH 在 BSC 上有 BTCB/WETH 锚定币，社交热度数据可用
    _BINANCE_HYPE_SYMBOLS = {"BTC", "ETH", "SOL", "BNB"}

    def collect_binance_social_hype(self, symbol: str) -> Dict[str, Any]:
        """币安 Web3 Social Hype Leaderboard — 社交情绪数据

        获取目标 symbol 的社交热度、情绪分类、KOL 数量。
        F5 节点: crypto_friendly_score / sentiment_index 数据源。
        F2 节点: 可作为市场情绪参考。

        API: crypto-market-rank API1 (Social Hype Leaderboard)
        """
        result: Dict[str, Any] = {"_source": "binance_hype_failed"}
        if symbol.upper() not in self._BINANCE_HYPE_SYMBOLS:
            result["_source"] = "binance_hype_unsupported_symbol"
            return result

        try:
            data = self._http_get(
                "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/market/token/pulse/social/hype/rank/leaderboard",
                params={
                    "chainId": "56",
                    "sentiment": "All",
                    "targetLanguage": "en",
                    "timeRange": 1,
                    "socialLanguage": "ALL",
                },
                timeout=12,
            )
            if not data or not data.get("success"):
                return result

            items = data.get("data", {}).get("leaderBoardList", [])
            sym_upper = symbol.upper()

            for item in items:
                sym = item.get("metaInfo", {}).get("symbol", "").upper()
                if sym != sym_upper:
                    continue

                hype_info = item.get("socialHypeInfo", {})
                social_hype = float(hype_info.get("socialHype", 0) or 0)
                sentiment_str = hype_info.get("sentiment", "Neutral")
                kol_count = int(hype_info.get("kolCount", 0) or 0)
                summary = hype_info.get("socialSummaryBrief", "")

                # 情绪映射到数值 [-1, 1]
                sentiment_map = {
                    "Positive": 0.5,
                    "Very Positive": 0.8,
                    "Negative": -0.5,
                    "Very Negative": -0.8,
                    "Neutral": 0.0,
                }
                sentiment_score = sentiment_map.get(sentiment_str, 0.0)

                # 社交热度分位数（对比排行榜中其他币种）
                all_hypes = [
                    float(it.get("socialHypeInfo", {}).get("socialHype", 0) or 0)
                    for it in items
                ]
                hype_rank = sum(1 for h in all_hypes if h > social_hype) + 1
                hype_percentile = (
                    (len(all_hypes) - hype_rank) / len(all_hypes) * 100
                    if all_hypes else 0
                )

                result["binance_social_hype"] = social_hype
                result["binance_hype_rank"] = hype_rank
                result["binance_hype_percentile"] = round(hype_percentile, 1)
                result["binance_sentiment"] = sentiment_str
                result["binance_sentiment_score"] = sentiment_score
                result["binance_kol_count"] = kol_count
                result["binance_social_summary"] = summary[:200]
                result["_source"] = "binance_hype"
                break
            else:
                result["_source"] = "binance_hype_symbol_not_found"

            return result
        except Exception as e:
            result["_source"] = f"binance_hype_error:{type(e).__name__}"
            return result

    def collect_binance_smart_money(self) -> Dict[str, Any]:
        """币安 Web3 Smart Money Signal — 聪明钱买卖信号

        聚合 Solana + BSC 两条链的 Smart Money 信号，
        统计 buy/sell 数量比，映射到 [-1, 1] 的方向值。
        F2 节点: smart_money_direction 数据源（>0.3 看多, <-0.3 看空）。

        API: trading-signal skill
        """
        result: Dict[str, Any] = {"_source": "binance_sm_failed"}
        try:
            total_buy = 0
            total_sell = 0
            total_sm_buy = 0  # smartMoneyCount 加权
            total_sm_sell = 0
            total_signals = 0

            # 聚合 Solana + BSC 两条链
            for chain_id in ("CT_501", "56"):
                data = self._http_post_json(
                    "https://web3.binance.com/bapi/defi/v1/public/wallet-direct/buw/wallet/web/signal/smart-money",
                    payload={
                        "smartSignalType": "",
                        "page": 1,
                        "pageSize": 100,
                        "chainId": chain_id,
                    },
                    timeout=12,
                )
                if not data or not data.get("success"):
                    continue

                items = data.get("data", [])
                for item in items:
                    direction = item.get("direction", "")
                    sm_count = int(item.get("smartMoneyCount", 0) or 0)
                    total_signals += 1
                    if direction == "buy":
                        total_buy += 1
                        total_sm_buy += sm_count
                    elif direction == "sell":
                        total_sell += 1
                        total_sm_sell += sm_count

            if total_signals == 0:
                return result

            # 聪明钱方向: [-1, 1]
            # 用 smartMoneyCount 加权（更准确的聪明钱权重）
            total_sm = total_sm_buy + total_sm_sell
            if total_sm > 0:
                sm_direction = (total_sm_buy - total_sm_sell) / total_sm
            elif total_signals > 0:
                # 退化：用信号数量比
                sm_direction = (total_buy - total_sell) / total_signals
            else:
                sm_direction = 0.0

            result["smart_money_direction"] = round(sm_direction, 4)
            result["binance_sm_buy_signals"] = total_buy
            result["binance_sm_sell_signals"] = total_sell
            result["binance_sm_buy_smart_money"] = total_sm_buy
            result["binance_sm_sell_smart_money"] = total_sm_sell
            result["binance_sm_total_signals"] = total_signals
            result["_source"] = "binance_smart_money"
            return result
        except Exception as e:
            result["_source"] = f"binance_sm_error:{type(e).__name__}"
            return result

    # ============================================================
    # 综合采集
    # ============================================================

    def collect_all(self, symbol: str = "BTC") -> Dict[str, Any]:
        """采集所有免费数据源并整合

        Args:
            symbol: 币种符号（如 BTC, ETH）

        Returns:
            整合后的扁平数据字典，带 _source 元信息
        """
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[0] < self.CACHE_TTL:
            return cached[1]

        result: Dict[str, Any] = {}
        sources: Dict[str, str] = {}

        # 1. Hyperliquid 衍生品数据
        hl = self.collect_hyperliquid(symbol)
        sources["derivatives"] = hl.get("_source", "unknown")
        for k, v in hl.items():
            if not k.startswith("_"):
                result[k] = v

        # 2. CoinGecko 市场/估值数据
        cg = self.collect_coingecko(symbol)
        sources["market"] = cg.get("_source", "unknown")
        for k, v in cg.items():
            if not k.startswith("_"):
                result[k] = v

        # 3. Fear & Greed 情绪（BTC 宏观情绪，对所有币种都有参考价值）
        fng = self.collect_fear_greed()
        sources["sentiment"] = fng.get("_source", "unknown")
        for k, v in fng.items():
            if not k.startswith("_"):
                result[k] = v

        # 4. Blockchain.info 链上数据（仅限 BTC）
        if symbol.upper() == "BTC":
            bc = self.collect_blockchain()
            sources["onchain"] = bc.get("_source", "unknown")
            for k, v in bc.items():
                if not k.startswith("_"):
                    result[k] = v
        else:
            sources["onchain"] = "skipped_non_btc"

        # 5. OKX 衍生品深度数据（资金费率历史、强平、OI、标记价）
        okx = self.collect_okx(symbol)
        okx_ok = okx.get("_source") == "okx"
        sources["okx_derivatives"] = okx.get("_source", "unknown")
        if okx_ok:
            for k, v in okx.items():
                if not k.startswith("_"):
                    # OKX 的 liquidation_* 字段直接覆盖（比 Hyperliquid 更详细）
                    # OKX 的 funding_rate 如果比 Hyperliquid 更好，也覆盖
                    result[k] = v

        # 6. DefiLlama DeFi 链上资金流数据（稳定币/DEX/TVL）
        #    补充 F2 stablecoin_supply_change、F4 chain_volume/exchange_balance_change
        dl = self.collect_defillama(symbol)
        dl_ok = dl.get("_source") == "defillama"
        sources["defillama"] = dl.get("_source", "unknown")
        if dl_ok:
            for k, v in dl.items():
                if not k.startswith("_"):
                    result[k] = v

        # 7. 币安 Web3 Social Hype（社交情绪，F5 sentiment/crypto_friendly_score）
        bh = self.collect_binance_social_hype(symbol)
        bh_ok = bh.get("_source") == "binance_hype"
        sources["binance_social"] = bh.get("_source", "unknown")
        if bh_ok:
            for k, v in bh.items():
                if not k.startswith("_"):
                    result[k] = v

        # 8. 币安 Web3 Smart Money Signal（聪明钱买卖方向，F2 smart_money_direction）
        #    市场级信号，不分币种，只采集一次
        bsm = self.collect_binance_smart_money()
        bsm_ok = bsm.get("_source") == "binance_smart_money"
        sources["binance_smart_money"] = bsm.get("_source", "unknown")
        if bsm_ok:
            for k, v in bsm.items():
                if not k.startswith("_"):
                    result[k] = v

        # 元信息
        result["_free_fundamental_sources"] = sources
        result["_free_fundamental_field_count"] = len(
            [k for k in result if not k.startswith("_")]
        )
        result["_free_fundamental_collected_at"] = time.time()

        # 缓存
        self._cache[symbol] = (time.time(), result)

        real_count = sum(
            1 for s in sources.values()
            if s not in ("unknown",) and not s.endswith("_failed")
            and not s.startswith("skipped_") and not s.endswith("_not_found")
        )
        logger.info(
            f"免费基本面采集: {symbol} | {result['_free_fundamental_field_count']} 字段 | "
            f"{real_count}/8 数据源成功 | sources={sources}"
        )

        return result

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()
