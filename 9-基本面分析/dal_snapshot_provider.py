"""
dal_snapshot_provider.py — 9-基本面分析 的 19-DAL 数据源。

从 19-数据访问层 MarketMacroRepository.mm_metrics 读取真实指标，
组装成与 legacy DataCollector 相同的 {metrics:{core,breakdown}, events, timeseries} 结构，
消除 breadth/intermarket/onchain/valuation 等模块的 Mock 数据。

设计原则：
  - fail-open：DAL 不可用或字段缺失时返回 None，由调用方回退 legacy DataCollector
  - 仅数值型指标从 mm_metrics 读取；news/narrative 保留 legacy（文本内容）
  - 派生字段（NVT、广度评分等）用已有指标计算，无数据则用合理默认值
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 自动注入 19-数据访问层路径，使 dreambuddy_dal 可被 import（避免 ModuleNotFoundError）
# dal_snapshot_provider.py 位于 9-基本面分析/，向上 1 层到 dreambuddy-v2/，再加 19-数据访问层/
_DAL_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "19-数据访问层")
)
if os.path.isdir(_DAL_ROOT) and _DAL_ROOT not in sys.path:
    sys.path.insert(0, _DAL_ROOT)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class DalSnapshotProvider:
    """从 19-DAL 读取基本面快照数据。"""

    def __init__(self, repo: Optional[Any] = None) -> None:
        self._repo = repo

    def get_repo(self) -> Optional[Any]:
        if self._repo is None:
            try:
                from dreambuddy_dal import get_market_macro_repo
                self._repo = get_market_macro_repo(backend="sqlite_unified")
            except Exception as exc:
                logger.warning("[DalSnapshotProvider] 无法获取 DAL repo: %s", exc)
                self._repo = None
        return self._repo

    # ------------------------------------------------------------------
    # 底层查询辅助
    # ------------------------------------------------------------------
    def _latest(self, sub_category: str, metric_name: str) -> Optional[Tuple[float, str]]:
        """返回 (value, source) 或 None。"""
        repo = self.get_repo()
        if repo is None:
            return None
        try:
            row = repo.query_latest_metric(sub_category, metric_name)
            if row is None:
                return None
            return (float(row[1]), str(row[0]))
        except Exception as exc:
            logger.debug("[DalSnapshotProvider] query_latest %s.%s 失败: %s", sub_category, metric_name, exc)
            return None

    def _history(self, sub_category: str, metric_name: str, days: int = 30) -> List[Dict]:
        """返回 [{value, timestamp}] 时间序列。"""
        repo = self.get_repo()
        if repo is None:
            return []
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)
            rows = repo.query_metric_by_time(sub_category, metric_name, start, end)
            return [
                {"value": float(r[2]), "timestamp": r[3].isoformat()}
                for r in rows
            ]
        except Exception:
            return []

    def _metric(self, sub_category: str, metric_name: str, default: float = 0.0) -> float:
        r = self._latest(sub_category, metric_name)
        return r[0] if r is not None else default

    # ------------------------------------------------------------------
    # 1. flow — 资金流
    # ------------------------------------------------------------------
    def collect_flow(self) -> Optional[Dict]:
        total_flow = self._metric("etf_flow", "total_flow", 0.0)
        if total_flow == 0.0 and self._latest("etf_flow", "total_flow") is None:
            return None  # 无数据，回退 legacy
        etf_breakdown = {}
        for col in ["FBTC", "IBIT", "GBTC", "EZBC", "BTCO", "BITB", "ARKB", "MSBT", "HODL", "BRRR", "BTCW"]:
            v = self._latest("etf_flow", col)
            if v is not None:
                etf_breakdown[col] = v[0]
        usdt_pct = self._metric("stablecoins_top_10", "USDT_pct", 0.0)
        usdc_pct = self._metric("stablecoins_top_10", "usdc_pct_of_total", 0.0)
        fund_flow_score = _clamp(total_flow / 1000.0, -1.0, 1.0)

        # --- 新增：从 DAL 读取衍生品/稳定币/巨鲸真实数据 ---
        # 真实资金费率（Binance Futures，百分比），回退到 fear_greed_enhanced funding 情绪分
        funding_rate_pct = self._metric("funding_rate", "funding_rate_pct", None)
        if funding_rate_pct is None:
            funding_rate_pct = self._metric("fear_greed_enhanced", "funding", 0.0)
        # 清算压力（panewslab derivatives_spot 24h 清算总额，归一化 0-100）
        liq_total_usd = self._metric("derivatives_spot", "fut_liq_total_24h_usd", 0.0)
        liquidation_pressure = round(_clamp(liq_total_usd / 1e9 * 20, 0, 100), 2)
        # 真实多空比（Binance Futures），回退到清算多/空比近似
        long_short_ratio = self._metric("long_short_ratio", "long_short_ratio", None)
        if long_short_ratio is None:
            liq_long = self._metric("derivatives_spot", "fut_liq_long_24h_usd", 0.0)
            liq_short = self._metric("derivatives_spot", "fut_liq_short_24h_usd", 0.0)
            long_short_ratio = round(liq_long / liq_short, 4) if liq_short > 0 else None
        # 巨鲸净流向交易所（负值=提币积累，正值=充值抛售）
        whale_netflow_usd = self._metric("exchanges_whales", "whale_netflow_to_ex_usd", 0.0)
        whale_activity = round(_clamp(abs(whale_netflow_usd) / 1e8, 0, 100), 2)
        # 稳定币 7 日变化率
        usdt_chg_7d = self._metric("tether_current", "change_7d_pct", 0.0)
        usdc_chg_7d = self._metric("usdc_current", "change_7d_pct", 0.0)
        etf_breakdown["usdt_supply_change"] = round(usdt_chg_7d, 4)
        etf_breakdown["usdc_supply_change"] = round(usdc_chg_7d, 4)
        etf_breakdown["whale_netflow_to_ex_usd"] = round(whale_netflow_usd, 2)
        etf_breakdown["liquidations_24h_usd"] = round(liq_total_usd, 2)

        # 聪明钱方向：ETF 流入 + 巨鲸提币 + 稳定币扩张 → 流入
        smart_money_score = fund_flow_score
        if whale_netflow_usd < 0:
            smart_money_score += 0.2
        if usdt_chg_7d > 0 or usdc_chg_7d > 0:
            smart_money_score += 0.1
        smart_money_score = _clamp(smart_money_score, -1, 1)
        smart_money_direction = (
            "显著流入" if smart_money_score > 0.3
            else "流入" if smart_money_score > 0.1
            else "流出" if smart_money_score < -0.3
            else "显著流出" if smart_money_score < -0.1
            else "中性"
        )

        ts_data = self._history("etf_flow", "total_flow", days=30)
        return {
            "metrics": {
                "core": {
                    "fund_flow_score": round(fund_flow_score, 4),
                    "etf_total_flow": round(total_flow, 2),
                    "stablecoin_dominance_usdt": round(usdt_pct, 2),
                    "stablecoin_dominance_usdc": round(usdc_pct, 2),
                    "funding_rate": round(funding_rate_pct, 6),
                    "liquidation_pressure": liquidation_pressure,
                    "long_short_ratio": long_short_ratio,
                    "whale_activity": whale_activity,
                    "smart_money_direction": smart_money_direction,
                    "flow_regime": "流入" if total_flow > 50 else "流出" if total_flow < -50 else "中性",
                },
                "breakdown": etf_breakdown,
            },
            "events": [{
                "title": f"BTC ETF 净流入 {total_flow:+.1f}M USD",
                "content": f"稳定币占比 USDT {usdt_pct:.1f}% / USDC {usdc_pct:.1f}%；巨鲸净流 {whale_netflow_usd/1e6:+.0f}M USD",
                "category": "资金流", "impact_score": 0.6,
                "sentiment": round(smart_money_score, 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": ts_data,
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 2. macro — 宏观
    # ------------------------------------------------------------------
    def collect_macro(self) -> Optional[Dict]:
        cpi_index = self._metric("CPIAUCSL", "value", 0.0)
        cpi_yoy = self._metric("cpi", "actual", 0.0) or (cpi_index / 100.0 if cpi_index else 0.0)
        fed_funds = self._metric("FEDFUNDS", "value", 0.0)
        cut_prob = self._metric("fedwatch", "cut_prob", 0.0)
        hold_prob = self._metric("fedwatch", "hold_prob", 0.0)
        hike_prob = self._metric("fedwatch", "hike_prob", 0.0)
        rate_change = self._metric("fomc_decision", "rate_change", 0.0)
        if cpi_index == 0.0 and fed_funds == 0.0 and cut_prob == 0.0:
            return None
        # 政策评分：降息概率高 + 加息概率低 → 宽松（+）；反之紧缩（-）
        policy_score = _clamp((cut_prob - hike_prob) * 0.5 + (1.0 if rate_change < 0 else -1.0 if rate_change > 0 else 0.0) * 0.3, -1.0, 1.0)
        # 利率周期：按当前市场概率判断，而非历史决议
        if cut_prob > hold_prob and cut_prob > hike_prob:
            rate_cycle = "降息"
        elif hike_prob > hold_prob and hike_prob > cut_prob:
            rate_cycle = "加息"
        else:
            rate_cycle = "持平"
        ts_data = self._history("FEDFUNDS", "value", days=90)
        return {
            "metrics": {
                "core": {
                    "policy_score": round(policy_score, 4),
                    "cpi_yoy": round(cpi_yoy, 3),
                    "fed_funds_rate": round(fed_funds, 3),
                    "rate_cycle": rate_cycle,
                    "cut_probability": round(cut_prob, 4),
                    "hold_probability": round(hold_prob, 4),
                    "hike_probability": round(hike_prob, 4),
                },
                "breakdown": {
                    "m2_supply": self._metric("M2SL", "value", 0.0),
                    "ppi": self._metric("PPIACO", "value", 0.0),
                    "industrial_production": self._metric("INDPRO", "value", 0.0),
                    "dot_plot_median": self._metric("fomc_decision", "dot_plot_median", 0.0) or self._metric("fomc_decision", "rate", 0.0),
                    "balance_sheet": self._metric("WALCL", "value", 0.0),
                },
            },
            "events": [{
                "title": f"联邦基金利率 {fed_funds:.2f}%，CPI {cpi_yoy:.2f}",
                "content": f"降息概率 {cut_prob:.0%} / 持平 {hold_prob:.0%} / 加息 {hike_prob:.0%}",
                "category": "宏观", "impact_score": 0.75,
                "sentiment": round(policy_score, 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": ts_data,
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 3. calendar — 经济日历
    # ------------------------------------------------------------------
    def collect_calendar(self) -> Optional[Dict]:
        cpi_actual = self._metric("cpi", "actual", 0.0)
        cpi_forecast = self._metric("cpi", "forecast", 0.0)
        cpi_surprise = self._metric("cpi", "surprise", 0.0)
        nfp_surprise = self._metric("nfp", "surprise", 0.0)
        ppi_surprise = self._metric("ppi", "surprise", 0.0)
        if cpi_actual == 0.0 and nfp_surprise == 0.0 and ppi_surprise == 0.0:
            return None
        impact = _clamp(abs(cpi_surprise) * 2 + abs(nfp_surprise) * 0.001 + abs(ppi_surprise), 0.0, 1.0)
        return {
            "metrics": {
                "core": {
                    "impact_score": round(impact, 4),
                    "cpi_surprise": round(cpi_surprise, 4),
                    "nfp_surprise": round(nfp_surprise, 2),
                    "ppi_surprise": round(ppi_surprise, 4),
                    "cpi_actual": round(cpi_actual, 3),
                    "cpi_forecast": round(cpi_forecast, 3),
                },
                "breakdown": {
                    "cpi_previous": self._metric("cpi", "previous", 0.0),
                },
            },
            "events": [{
                "title": f"CPI 意外 {cpi_surprise:+.2f}，NFP 意外 {nfp_surprise:+.0f}",
                "content": f"CPI 实际 {cpi_actual:.2f} vs 预期 {cpi_forecast:.2f}",
                "category": "经济日历", "impact_score": round(impact, 3),
                "sentiment": round(-cpi_surprise * 0.5, 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("cpi", "surprise", days=180),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 4. sentiment — 情绪
    # ------------------------------------------------------------------
    def collect_sentiment(self) -> Optional[Dict]:
        fg = self._latest("crypto_fear_greed", "value")
        if fg is None:
            return None
        fg_value = fg[0]
        classification = "恐惧" if fg_value < 25 else "极度恐惧" if fg_value < 45 else "中性" if fg_value < 55 else "贪婪" if fg_value < 75 else "极度贪婪"
        # 增强恐惧贪婪的 4 个子维度（0-100），用于热力图
        vol_score = self._metric("fear_greed_enhanced", "volatility", fg_value)
        mom_score = self._metric("fear_greed_enhanced", "momentum", fg_value)
        fund_score = self._metric("fear_greed_enhanced", "funding", fg_value)
        cap_score = self._metric("fear_greed_enhanced", "capital_flow", fg_value)
        # 社交声量：优先 social_volume（真实新闻计数派生），回退 crypto_fear_greed.count
        social_volume = self._metric("social_volume", "social_volume", None)
        if social_volume is None:
            social_volume = self._metric("crypto_fear_greed", "count", 0.0)
        heatmap_data = [
            {"category": "波动", "score": round(vol_score, 1)},
            {"category": "动量", "score": round(mom_score, 1)},
            {"category": "资金费率", "score": round(fund_score, 1)},
            {"category": "资金流向", "score": round(cap_score, 1)},
            {"category": "贪婪恐惧", "score": round(fg_value, 1)},
        ]
        return {
            "metrics": {
                "core": {
                    "sentiment_index": round(fg_value, 2),
                    "fear_greed_index": round(fg_value, 2),
                    "sentiment_classification": classification,
                    "sentiment_regime": "恐惧" if fg_value < 45 else "贪婪" if fg_value > 55 else "中性",
                    "social_volume": round(social_volume, 0),
                },
                "breakdown": {},
            },
            "heatmap_data": heatmap_data,
            "events": [{
                "title": f"恐惧贪婪指数 {fg_value:.0f}（{classification}）",
                "content": "市场情绪实时读数",
                "category": "情绪", "impact_score": 0.5,
                "sentiment": round((fg_value - 50) / 50, 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("crypto_fear_greed", "value", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 5. onchain — 链上
    # ------------------------------------------------------------------
    def collect_onchain(self) -> Optional[Dict]:
        hash_rate = self._metric("btc_basics", "hashrate", 0.0)
        market_cap = self._metric("btc_basics", "market_cap_usd", 0.0)
        tx_count = self._metric("btc_basics", "tx_count_24h", 0.0)
        active_addresses = self._metric("btc_basics", "active_addresses", 0.0)
        ex_bal_btc = self._metric("exchanges_whales", "ex_bal_BTC_total", 0.0)
        ex_bal_chg_30d = self._metric("exchanges_whales", "ex_bal_BTC_chg30d_pct", 0.0)
        ex_inflow_24h = self._metric("exchanges_whales", "ex_summary_inflowUsd24h", 0.0)
        whale_transfers = self._metric("exchanges_whales", "whales_transfer_count", 0.0)
        # 巨鲸净流向交易所（CryptoQuant/panewslab）
        whale_netflow_usd = self._metric("exchanges_whales", "whale_netflow_to_ex_usd", 0.0)
        if hash_rate == 0.0 and market_cap == 0.0 and ex_bal_btc == 0.0 and active_addresses == 0.0:
            return None
        # 交易所净流向：30 天余额下降 → 流出（看涨）；上升 → 流入（看跌）
        exchange_net_flow = -ex_bal_chg_30d * 10  # 简化派生
        hash_rate_eh = hash_rate / 1e9 if hash_rate > 1e6 else hash_rate
        network_health = "优秀" if hash_rate_eh > 400 else "良好" if hash_rate_eh > 200 else "偏弱"
        accumulation_signal = "积累" if exchange_net_flow < -50 else "分发" if exchange_net_flow > 50 else "中性"
        # 巨鲸净流 BTC 估算（按 ~8.5万 USD/BTC）
        whale_netflow_btc = round(whale_netflow_usd / 85000, 2) if whale_netflow_usd else 0.0
        # UTXO 年龄分布：优先 utxo_age_distribution 真实分桶，回退到 profit-supply 派生
        short_term_holder_supply = self._metric("utxo_age_distribution", "short_term_holder_supply_pct", None)
        hodl_waves_1y_plus = self._metric("utxo_age_distribution", "hodl_waves_1y_plus_pct", None)
        if short_term_holder_supply is None or hodl_waves_1y_plus is None:
            profit_supply_pct = self._metric("cycle_signals", "bottom_profit-supply_value", 50.0)
            short_term_holder_supply = round(_clamp(profit_supply_pct * 0.55, 10, 70), 1)
            hodl_waves_1y_plus = round(_clamp(100 - short_term_holder_supply - 25, 15, 70), 1)
        else:
            profit_supply_pct = self._metric("utxo_age_distribution", "profit_supply_pct", 50.0)
        return {
            "metrics": {
                "core": {
                    "exchange_net_flow": round(exchange_net_flow, 2),
                    "hash_rate": round(hash_rate_eh, 2),
                    "market_cap_usd": round(market_cap, 0),
                    "tx_count_24h": round(tx_count, 0),
                    "active_addresses": round(active_addresses, 0),
                    "exchange_reserve_btc": round(ex_bal_btc, 2),
                    "whale_netflow_to_ex_usd": round(whale_netflow_usd, 2),
                    "whale_netflow_btc": whale_netflow_btc,
                    "onchain_trend": accumulation_signal,
                    "network_health": network_health,
                    "accumulation_signal": accumulation_signal,
                },
                "breakdown": {
                    "exchange_inflow_usd_24h": round(ex_inflow_24h, 2),
                    "exchange_reserve_change_30d_pct": round(ex_bal_chg_30d, 4),
                    "whale_transfers": round(whale_transfers, 0),
                    "hodl_waves_1y_plus": hodl_waves_1y_plus,
                    "short_term_holder_supply": short_term_holder_supply,
                    "profit_supply_pct": round(profit_supply_pct, 2),
                },
            },
            "events": [{
                "title": f"哈希率 {hash_rate_eh:.0f} EH/s，网络{network_health}",
                "content": f"交易所 BTC 余额 {ex_bal_btc:.0f}，30d 变化 {ex_bal_chg_30d:+.2f}% → {accumulation_signal}；巨鲸净流 {whale_netflow_usd/1e6:+.0f}M USD",
                "category": "链上", "impact_score": 0.65,
                "sentiment": round(_clamp(-ex_bal_chg_30d * 5, -1, 1), 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("btc_basics", "hashrate", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 6. intermarket — 跨市场
    # ------------------------------------------------------------------
    def collect_intermarket(self) -> Optional[Dict]:
        dxy = self._metric("DX-Y.NYB", "value", 0.0)
        spx = self._metric("^GSPC", "price", 0.0) or self._metric("^GSPC", "value", 0.0) or self._metric("SPY", "price", 0.0) or self._metric("SPY", "value", 0.0)
        gold = self._metric("GC=F", "value", 0.0) or self._metric("gold", "value", 0.0)
        us10y = self._metric("^TNX", "value", 0.0) or self._metric("^TNX", "close", 0.0)
        vix = self._metric("^VIX", "value", 0.0)
        btc = self._metric("BTC-USD", "value", 0.0)
        ndx = self._metric("^IXIC", "price", 0.0) or self._metric("^IXIC", "value", 0.0) or self._metric("QQQ", "price", 0.0) or self._metric("QQQ", "value", 0.0)
        wti = self._metric("CL=F", "value", 0.0) or self._metric("CL=F", "price", 0.0)
        if dxy == 0.0 and spx == 0.0 and gold == 0.0:
            return None
        # DXY-BTC 相关性：线性插值（DXY>102 → 负相关，<102 → 正相关）
        dxy_correlation = _clamp(-(dxy - 102.0) / 5.0, -1.0, 1.0)
        risk_on = (spx > 0 and gold > 0) and (vix < 20)
        return {
            "metrics": {
                "core": {
                    "dxy_correlation": round(dxy_correlation, 4),
                    "spx_price": round(spx, 2),
                    "gold_price": round(gold, 2),
                    "us10y_yield": round(us10y, 3),
                    "vix": round(vix, 2),
                    "btc_price": round(btc, 2),
                    "risk_regime": "risk_on" if risk_on else "risk_off",
                    "dxy": round(dxy, 2),
                    "ndx": round(ndx, 2),
                    "wti": round(wti, 2),
                },
                "breakdown": {
                    "dxy": round(dxy, 2),
                },
            },
            "events": [{
                "title": f"DXY {dxy:.1f} / VIX {vix:.1f} / 黄金 {gold:.0f}",
                "content": f"标普 {spx:.0f}，美债10Y {us10y:.2f}%，BTC {btc:,.0f}",
                "category": "跨市场", "impact_score": 0.55,
                "sentiment": round(0.5 if risk_on else -0.5, 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("DX-Y.NYB", "value", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 7. valuation — 估值
    # ------------------------------------------------------------------
    def collect_valuation(self) -> Optional[Dict]:
        market_cap = self._metric("btc_basics", "market_cap_usd", 0.0)
        tx_count = self._metric("btc_basics", "tx_count_24h", 0.0)
        output_volume_btc = self._metric("btc_basics", "output_volume_btc", 0.0)
        btc_price = self._metric("bitcoin", "current_price_usd", 0.0)
        if btc_price == 0.0:
            # 从 BTC-USD 行情回退
            btc_price = self._metric("BTC-USD", "value", 0.0)
        total_btc = self._metric("btc_basics", "total_btc", 0.0)
        # 真实链上估值指标（CryptoQuant/panewslab cycle_signals）
        mvrv_ratio = self._metric("cycle_signals", "bottom_mvrv_value", 0.0)
        nupl = self._metric("cycle_signals", "bottom_nupl_value", 0.0)
        puell_multiple = self._metric("cycle_signals", "bottom_puell-multiple_value", 0.0)
        # 抄底信号统计
        bottom_hit_count = self._metric("cycle_signals", "bottom_hit_count", 0.0)
        bottom_total_count = self._metric("cycle_signals", "bottom_total_count", 0.0)
        bottom_hit_ratio_pct = self._metric("cycle_signals", "bottom_hit_ratio_pct", 0.0)
        two_year_ma = self._metric("cycle_signals", "bottom_two-year-ma_value", 0.0)
        reserve_risk = self._metric("cycle_signals", "bottom_reserve-risk_value", 0.0)
        # P0 修复：market_cap=0 时不 return None（避免整个模块回退 legacy 导致字段集不兼容）
        # 改为：尝试用 price * supply 估算；估算失败则相关字段标记 None，保持字段集一致
        market_cap_missing = (market_cap == 0.0)
        if market_cap_missing:
            if btc_price > 0 and total_btc > 0:
                market_cap = btc_price * total_btc
                logger.info("[valuation] market_cap 缺失，用 btc_price*total_btc 估算: %.0f", market_cap)
            else:
                logger.warning("[valuation] market_cap 无法获取，相关字段标记为 None")

        # NVT = 市值 / 每日链上交易量(USD)
        nvt_ratio = None
        nvt_z_score = None
        if market_cap > 0:
            if output_volume_btc > 0 and btc_price > 0:
                daily_volume_usd = output_volume_btc * btc_price
            elif tx_count > 0:
                avg_tx_usd = 100000.0
                daily_volume_usd = tx_count * avg_tx_usd
            else:
                daily_volume_usd = 1.0
            nvt_ratio = market_cap / daily_volume_usd if daily_volume_usd > 0 else None
            if nvt_ratio is not None:
                nvt_z_score = _clamp((nvt_ratio - 20.0) / 15.0, -3.0, 3.0)
        # MVRV：优先用 cycle_signals 真实值，否则用 btc_metrics 代理
        if not (0.5 < mvrv_ratio < 10):
            mvrv_ratio = 2.5
        # 已实现价格 = (市值 / MVRV) / 流通量 = 已实现市值 / 流通量
        realized_cap = market_cap / mvrv_ratio if (market_cap > 0 and mvrv_ratio > 0) else 0.0
        realized_price = round(realized_cap / total_btc, 2) if total_btc > 0 else 0.0
        valuation_zone = (
            "高估" if nvt_z_score is not None and nvt_z_score > 1.5
            else "低估" if nvt_z_score is not None and nvt_z_score < -1.0
            else "合理" if nvt_z_score is not None
            else "数据不足"
        )
        return {
            "metrics": {
                "core": {
                    "mvrv_ratio": round(mvrv_ratio, 4),
                    "nvt_ratio": round(nvt_ratio, 2) if nvt_ratio is not None else None,
                    "nvt_z_score": round(nvt_z_score, 4) if nvt_z_score is not None else None,
                    "market_cap_usd": round(market_cap, 0) if market_cap > 0 else None,
                    "nupl": round(nupl, 4),
                    "puell_multiple": round(puell_multiple, 4),
                    "realized_price": realized_price,
                    "valuation_zone": valuation_zone,
                },
                "breakdown": {
                    "tx_count_24h": round(tx_count, 0),
                    "output_volume_btc": round(output_volume_btc, 2),
                    "bottom_hit_count": round(bottom_hit_count, 0),
                    "bottom_total_count": round(bottom_total_count, 0),
                    "bottom_hit_ratio_pct": round(bottom_hit_ratio_pct, 2),
                    "two_year_ma": round(two_year_ma, 4),
                    "reserve_risk": round(reserve_risk, 6),
                },
            },
            "events": [{
                "title": f"估值区间：{valuation_zone}" + (f"（NVT z={nvt_z_score:+.2f}）" if nvt_z_score is not None else ""),
                "content": f"MVRV {mvrv_ratio:.2f}，NUPL {nupl:.3f}" + (f"，市值 {market_cap/1e12:.2f}T USD" if market_cap > 0 else "，市值数据缺失"),
                "category": "估值", "impact_score": 0.6,
                "sentiment": round(-nvt_z_score * 0.3, 3) if nvt_z_score is not None else 0.0,
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("btc_basics", "market_cap_usd", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 8. breadth — 市场广度
    # ------------------------------------------------------------------
    def collect_breadth(self) -> Optional[Dict]:
        btc_dominance = self._metric("overview_market", "btc_dominance_pct", 0.0)
        global_change = self._metric("overview_market", "global_change24_pct", 0.0)
        # DeFi TVL：优先 all_protocols.total_tvl_bln（全链协议总锁仓），回退 chains_summary.total_tvl_bln
        tvl_bln = self._metric("all_protocols", "total_tvl_bln", 0.0)
        if tvl_bln == 0.0:
            tvl_bln = self._metric("chains_summary", "total_tvl_bln", 0.0)
        if btc_dominance == 0.0 and global_change == 0.0:
            return None
        # 广度线：全球涨跌 * 系数
        advance_decline_line = round(_clamp(global_change * 10, -60, 70), 2)
        breadth_confirmation = "确认趋势" if advance_decline_line > 30 else "存在分歧" if advance_decline_line > 0 else "广度恶化"
        return {
            "metrics": {
                "core": {
                    "advance_decline_line": advance_decline_line,
                    "btc_dominance": round(btc_dominance, 2),
                    "breadth_confirmation": breadth_confirmation,
                    "global_change_24h": round(global_change, 4),
                    "defi_tvl_bln": round(tvl_bln, 2),
                    "market_participation_index": round(_clamp(50 + advance_decline_line * 0.3, 0, 100), 2),
                },
                "breakdown": {
                    "advance_count": round(_clamp(50 + advance_decline_line * 0.5, 0, 100), 2),
                    "decline_count": round(_clamp(50 - advance_decline_line * 0.5, 0, 100), 2),
                },
            },
            "events": [{
                "title": f"BTC 占比 {btc_dominance:.1f}%，全球 24h {global_change:+.2f}%",
                "content": f"广度状态：{breadth_confirmation}，DeFi TVL {tvl_bln:.0f}B",
                "category": "广度", "impact_score": 0.55,
                "sentiment": round(_clamp(advance_decline_line / 60, -1, 1), 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("overview_market", "btc_dominance_pct", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 9. news — 新闻情绪（从 DAL newsflash 真实数据派生）
    # ------------------------------------------------------------------
    def collect_news(self) -> Optional[Dict]:
        news_count = self._metric("social_volume", "news_count_24h", 0)
        social_volume = self._metric("social_volume", "social_volume", 0)
        total_records = self._metric("social_volume", "total_news_records", 0)
        if news_count == 0 and social_volume == 0:
            return None

        # 从 newsflash_* 表统计情绪分布
        repo = self.get_repo()
        positive_count = 0
        negative_count = 0
        neutral_count = 0
        sentiments: List[float] = []
        if repo is not None:
            try:
                end_dt = datetime.now(timezone.utc)
                start_dt = end_dt - timedelta(hours=48)  # 48h 窗口，确保捕获最近 newsflash
                start_ts = int(start_dt.timestamp())
                end_ts = int(end_dt.timestamp())
                # newsflash 的 sub_category 形如 newsflash_513701，用 LIKE 匹配
                import sqlite3 as _sql
                import os as _os
                db_path = _os.environ.get("DAL_DB_PATH", "")
                if db_path:
                    _conn = _sql.connect(db_path)
                    _rows = _conn.execute(
                        """SELECT metric_value FROM mm_metrics
                           WHERE metric_name='od_policy_sentiment_0_1'
                             AND sub_category LIKE 'newsflash_%'
                             AND timestamp BETWEEN ? AND ?
                           ORDER BY timestamp DESC LIMIT 200""", (start_ts, end_ts)
                    ).fetchall()
                    _conn.close()
                    for _r in _rows:
                        val = _r[0]
                        if val is None or not isinstance(val, (int, float)):
                            continue
                        sentiments.append(float(val))
                        if val > 0.55:
                            positive_count += 1
                        elif val < 0.45:
                            negative_count += 1
                        else:
                            neutral_count += 1
            except Exception:
                pass

        total = positive_count + negative_count + neutral_count
        if total == 0:
            total = 1  # 防除零
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else 0.5
        sentiment_score = (positive_count - negative_count) / total

        # 按影响分类（高影响 = 情绪极值）
        high_impact = sum(1 for s in sentiments if abs(s - 0.5) > 0.3)

        return {
            "metrics": {
                "core": {
                    "total_articles": int(news_count),
                    "positive_count": positive_count,
                    "negative_count": negative_count,
                    "neutral_count": neutral_count,
                    "sentiment": round(avg_sentiment, 3),
                    "avg_sentiment": round(avg_sentiment, 3),
                    "avg_impact": round(high_impact / max(total, 1), 3),
                    "high_impact_count": high_impact,
                    "negative_ratio": round(negative_count / total, 3),
                    "positive_ratio": round(positive_count / total, 3),
                    "neutral_ratio": round(neutral_count / total, 3),
                    "bearish_ratio": round(negative_count / total, 3),
                    "sentiment_sum": round(sum(sentiments), 2),
                    "category_count": min(total, 5),
                    "top_category": "综合",
                    "sentiment_score": round(sentiment_score, 3),
                },
                "breakdown": {
                    "social_volume": int(social_volume),
                    "total_news_records": int(total_records),
                },
            },
            "events": [],
            "timeseries": self._history("social_volume", "news_count_24h", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # 10. narrative — 市场叙事（从 DAL fear_greed_enhanced 派生）
    # ------------------------------------------------------------------
    def collect_narrative(self) -> Optional[Dict]:
        fg_value = self._metric("crypto_fear_greed", "value", 0.0)
        # 4 个子维度作为叙事来源
        sub_metrics = {
            "capital_flow": self._metric("fear_greed_enhanced", "capital_flow", 50.0),
            "funding": self._metric("fear_greed_enhanced", "funding", 50.0),
            "momentum": self._metric("fear_greed_enhanced", "momentum", 50.0),
            "volatility": self._metric("fear_greed_enhanced", "volatility", 50.0),
        }
        if fg_value == 0.0 and all(v == 50.0 for v in sub_metrics.values()):
            return None

        bullish = sum(1 for v in sub_metrics.values() if v > 60)
        bearish = sum(1 for v in sub_metrics.values() if v < 40)
        neutral = len(sub_metrics) - bullish - bearish
        total = len(sub_metrics)
        avg_sentiment = sum(v / 100.0 for v in sub_metrics.values()) / total
        consensus = (fg_value / 100.0 + avg_sentiment) / 2.0

        # 叙事标签
        narratives = []
        for name, val in sub_metrics.items():
            if val > 60:
                narratives.append({"theme": name, "sentiment": "bullish", "score": val})
            elif val < 40:
                narratives.append({"theme": name, "sentiment": "bearish", "score": val})
            else:
                narratives.append({"theme": name, "sentiment": "neutral", "score": val})

        return {
            "metrics": {
                "core": {
                    "total_narratives": total,
                    "bullish_narratives": bullish,
                    "bearish_narratives": bearish,
                    "neutral_narratives": neutral,
                    "avg_sentiment": round(avg_sentiment, 3),
                    "avg_momentum": round(sub_metrics["momentum"], 1),
                    "consensus": round(consensus, 3),
                    "market_consensus": round(consensus, 3),
                },
                "breakdown": {
                    n["theme"]: n["score"] for n in narratives
                },
            },
            "events": [{
                "title": f"恐惧贪婪指数 {fg_value:.0f}，{bullish} 项看多 {bearish} 项看空",
                "content": f"叙事分布：{bullish} 多 / {neutral} 中 / {bearish} 空",
                "category": "叙事", "impact_score": 0.6,
                "sentiment": round(_clamp(consensus * 2 - 1, -1, 1), 3),
                "source": "19-DAL", "published_at": _now_iso(),
            }],
            "timeseries": self._history("crypto_fear_greed", "value", days=30),
            "timestamp": _now_iso(),
        }

    # ------------------------------------------------------------------
    # FeatureHub 桥接：将 DAL 数据转为 DataFrame 并运行特征工程
    # ------------------------------------------------------------------
    def _build_ohlcv_dataframe(self, days: int = 60) -> Optional[Any]:
        """从 DAL 获取 BTC/USDT OHLCV 数据并构建 DataFrame。

        Returns:
            pd.DataFrame with columns [open, high, low, close, volume] 或 None
        """
        try:
            import pandas as pd
        except ImportError:
            return None

        repo = self.get_repo()
        if repo is None:
            return None

        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)
            # BTC/USDT 在 mm_metrics 中的 sub_category
            sub = "BTC/USDT"
            cols = {"open": "open", "high": "high", "low": "low", "close": "last", "volume": "volume"}
            series = {}
            for df_col, metric_name in cols.items():
                try:
                    rows = repo.query_metric_by_time(sub, metric_name, start, end)
                    if rows:
                        # r[3] 已是 datetime 对象
                        series[df_col] = {
                            r[3]: float(r[2])
                            for r in rows
                        }
                except Exception:
                    continue

            if not series:
                return None

            df = pd.DataFrame(series)
            df = df.sort_index().dropna(how="all")
            # 至少需要 close 和 volume
            if "close" not in df.columns or df["close"].dropna().empty:
                return None
            return df
        except Exception as exc:
            logger.debug("[DalSnapshotProvider] _build_ohlcv_dataframe 失败: %s", exc)
            return None

    def _build_metrics_dataframe(
        self, metric_specs: Dict[str, str], days: int = 60
    ) -> Optional[Any]:
        """从 DAL 获取多个基本面指标时序并构建 DataFrame。

        Args:
            metric_specs: {列名: "sub_category.metric_name"} 映射
            days: 回溯天数

        Returns:
            pd.DataFrame 或 None
        """
        try:
            import pandas as pd
        except ImportError:
            return None

        repo = self.get_repo()
        if repo is None:
            return None

        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)
            series = {}
            for col_name, spec in metric_specs.items():
                if "." not in spec:
                    continue
                sub_category, metric_name = spec.split(".", 1)
                try:
                    rows = repo.query_metric_by_time(sub_category, metric_name, start, end)
                    if rows:
                        # r[3] 已是 datetime 对象
                        series[col_name] = {
                            r[3]: float(r[2])
                            for r in rows
                        }
                except Exception:
                    continue

            if not series:
                return None
            df = pd.DataFrame(series).sort_index().dropna(how="all")
            return df if not df.empty else None
        except Exception as exc:
            logger.debug("[DalSnapshotProvider] _build_metrics_dataframe 失败: %s", exc)
            return None

    def compute_features(
        self,
        metric_specs: Optional[Dict[str, str]] = None,
        days: int = 60,
    ) -> Dict[str, float]:
        """运行 FeatureHub 特征工程，返回最新特征值字典。

        包含两类特征：
          1. fundamental_ratios：基于 BTC/USDT OHLCV 的价格代理比率（8列）
          2. fundamental_features：基于基本面指标时序的衍生特征（12列）

        Args:
            metric_specs: 基本面指标映射 {列名: "sub_category.metric_name"}
            days: 回溯天数

        Returns:
            {特征名: 最新值} 字典，失败返回空 dict（fail-open）
        """
        features: Dict[str, float] = {}
        try:
            from feature_hub.pipeline.feature_pipeline import FeaturePipeline
            from feature_hub.modules.loader import load_default_sets
        except Exception as exc:
            logger.debug("[DalSnapshotProvider] FeatureHub 导入失败: %s", exc)
            return features

        try:
            pipe = FeaturePipeline()
            load_default_sets(pipe)
        except Exception as exc:
            logger.debug("[DalSnapshotProvider] FeaturePipeline 初始化失败: %s", exc)
            return features

        # 1. 价格代理比率特征（fundamental_ratios，需要 OHLCV）
        ohlcv_df = self._build_ohlcv_dataframe(days=days)
        if ohlcv_df is not None and not ohlcv_df.empty:
            try:
                fv = pipe.run("fundamental_full", ohlcv_df, symbol="BTC/USDT")
                feat_df = getattr(fv, "df", None)
                if feat_df is not None and not feat_df.empty:
                    latest = feat_df.iloc[-1]
                    for k in feat_df.columns:
                        v = latest[k]
                        if isinstance(v, (int, float)) and not (isinstance(v, float) and (v != v)):
                            features[f"price_{k}"] = round(float(v), 6)
            except Exception as exc:
                logger.debug("[DalSnapshotProvider] fundamental_ratios 计算失败: %s", exc)

        # 2. 基本面时序衍生特征（fundamental_features，需要指标时序）
        if metric_specs:
            metrics_df = self._build_metrics_dataframe(metric_specs, days=days)
            if metrics_df is not None and not metrics_df.empty:
                try:
                    from feature_hub.modules import fundamental_features
                    feat_df = fundamental_features.compute(metrics_df)
                    if not feat_df.empty:
                        latest_row = feat_df.iloc[-1]
                        for k in feat_df.columns:
                            v = latest_row[k]
                            if isinstance(v, (int, float)) and not (isinstance(v, float) and (v != v)):
                                features[f"fund_{k}"] = round(float(v), 6)
                except Exception as exc:
                    logger.debug("[DalSnapshotProvider] fundamental_features 计算失败: %s", exc)

        return features


# 模块 → provider 方法映射（与 legacy MODULE_COLLECTORS 对齐）
DAL_COLLECTORS = {
    "flow": "collect_flow",
    "macro": "collect_macro",
    "calendar": "collect_calendar",
    "sentiment": "collect_sentiment",
    "onchain": "collect_onchain",
    "intermarket": "collect_intermarket",
    "valuation": "collect_valuation",
    "breadth": "collect_breadth",
    "news": "collect_news",
    "narrative": "collect_narrative",
}
