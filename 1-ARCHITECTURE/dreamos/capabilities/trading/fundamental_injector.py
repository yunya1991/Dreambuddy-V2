"""
基本面数据注入器 — 连通 data_collector → state.market_data

P0 修复：Dream OS F链（F1-F5）定义了 30+ 个基本面指标字段的读取逻辑，
但没有任何上游组件向 state.market_data 注入这些字段，导致 F2-F5 恒输出 HOLD/0.3。

本模块调用 9-基本面分析/data_collector.py 的 DataCollector，
将采集结果扁平化注入到 market_data，使 F 节点能读到真实数据。

特性:
    - 1 小时缓存，避免每次交易都重新采集（含网络请求）
    - 字段名映射（data_collector 字段名 → F 节点读取的字段名）
    - source 标注（标注数据来源：tavily/blockchain/mock）
    - smart_money_direction 字符串→数值转换
"""

from __future__ import annotations

import os
import sys
import time
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# data_collector 所在目录（9-基本面分析/）
# fundamental_injector.py → trading/ → capabilities/ → dreamos/ → 1-ARCHITECTURE/ → dreambuddy-v2/
_DATA_COLLECTOR_DIR = str(
    Path(__file__).parent.parent.parent.parent.parent / "9-基本面分析"
)


# ============================================================
# 字段名映射表
# data_collector 返回的 metrics.core 字段名 → F 节点读取的字段名
# ============================================================

FIELD_NAME_MAP = {
    # F3 估值：ahr999_index → ahr999
    "ahr999_index": "ahr999",
    # F4 链上：whale_activity → whale_accumulation_score（语义近似）
    "whale_activity": "whale_accumulation_score",
    # F4 链上：transaction_volume → chain_volume（语义映射）
    "transaction_volume": "chain_volume",
}


# ============================================================
# smart_money_direction 字符串 → 数值映射
# F2 节点做数值比较（> 0.3 / < -0.3），但 data_collector 返回字符串
# ============================================================

SMART_MONEY_MAP = {
    "显著流入": 0.6,
    "温和流入": 0.3,
    "观望": 0.0,
    "温和流出": -0.3,
    "显著流出": -0.6,
}


# ============================================================
# 免费数据源字段映射
# FreeFundamentalProvider 字段名 → F 节点读取的字段名
# ============================================================

FREE_FIELD_MAP = {
    # 衍生品 (Hyperliquid) — funding_rate 单独处理（单位转换）
    "open_interest": "open_interest",
    "open_interest_usd": "open_interest_usd",
    # 市场/估值 (CoinGecko)
    "market_cap": "market_cap",
    "volume_24h": "volume_24h",
    "market_dominance": "btc_dominance",
    "all_time_high": "all_time_high",
    "ath_drop_pct": "ath_change_percentage",
    "circulating_supply": "circulating_supply",
    "price_change_24h_pct": "price_change_24h",
    "price_change_7d_pct": "price_change_7d",
    "price_change_30d_pct": "price_change_30d",
    # 情绪 (alternative.me)
    "fear_greed_index": "fear_greed_index",
    "fear_greed_classification": "fear_greed_classification",
    # 链上 (Blockchain.info)
    "chain_tx_count": "n_tx",
    "hash_rate": "hash_rate",
    "difficulty": "difficulty",
    "total_btc_sent_sat": "total_btc_sent",
    "trade_volume_usd": "trade_volume_usd",
    # DeFi 链上资金流 (DefiLlama) — identity 映射
    # F2: stablecoin_supply_change（稳定币供给变化率，>2% 看多）
    "stablecoin_supply_total": "stablecoin_supply_total",
    "stablecoin_supply_change": "stablecoin_supply_change",
    "stablecoin_supply_change_7d": "stablecoin_supply_change_7d",
    # F4: chain_volume / chain_volume_change（DEX 交易量及变化率）
    "chain_volume": "chain_volume",
    "chain_volume_7d_avg": "chain_volume_7d_avg",
    "chain_volume_change": "chain_volume_change",
    # F4: chain_tvl / tvl_change（链上 TVL 及变化率）
    "chain_tvl": "chain_tvl",
    "tvl_change_7d": "tvl_change_7d",
    "tvl_change_30d": "tvl_change_30d",
    # F4: exchange_balance_change（由 TVL 变化反向近似派生）
    "exchange_balance_change": "exchange_balance_change",
    # 币安 Web3 Smart Money（F2 smart_money_direction，直接覆盖）
    "smart_money_direction": "smart_money_direction",
    # 币安 Web3 Social Hype — identity 映射（binance_ 前缀字段）
    "binance_social_hype": "binance_social_hype",
    "binance_hype_rank": "binance_hype_rank",
    "binance_hype_percentile": "binance_hype_percentile",
    "binance_sentiment": "binance_sentiment",
    "binance_sentiment_score": "binance_sentiment_score",
    "binance_kol_count": "binance_kol_count",
}


class FundamentalDataInjector:
    """基本面数据注入器

    调用 data_collector 采集基本面数据，扁平化注入到 market_data。
    使 Dream OS F 链（F1-F5）能读到真实的基本面指标。

    用法:
        injector = FundamentalDataInjector()
        market_data = injector.inject(market_data, symbol)
    """

    CACHE_TTL = 3600  # 1 小时缓存

    # P0-2: 是否注入 Mock 数据（默认不注入，避免虚假数据污染 F 节点）
    INJECT_MOCK = os.environ.get("DREAMOS_FUNDAMENTAL_INJECT_MOCK", "0") == "1"

    def __init__(self):
        self._cache: Dict[str, tuple] = {}  # symbol → (timestamp, flat_data)
        self._collector = None
        self._tavily_available = bool(os.environ.get("TAVILY_API_KEY", ""))
        self._init_error: Optional[str] = None
        self._free_provider = None  # 免费数据源（Tavily 不可用时的降级）
        self._free_enabled = os.environ.get("DREAMOS_FREE_FUNDAMENTAL", "1") == "1"

    def _get_collector(self):
        """延迟加载 DataCollector（避免 import 失败影响系统启动）"""
        if self._collector is not None:
            return self._collector

        try:
            if _DATA_COLLECTOR_DIR not in sys.path:
                sys.path.insert(0, _DATA_COLLECTOR_DIR)
            from data_collector import DataCollector
            self._collector = DataCollector()

            # P0-2: 验证 Tavily Key 是否实际有效（而非仅检查是否存在）
            if self._tavily_available:
                self._tavily_valid = self._check_tavily_valid()
                if not self._tavily_valid:
                    logger.warning(
                        "TAVILY_API_KEY 存在但无效（Unauthorized），"
                        "flow/valuation/macro/news 模块将走 Mock 兜底"
                    )
            else:
                self._tavily_valid = False

            logger.info(
                f"基本面 DataCollector 加载成功 | Tavily: "
                f"{'valid' if self._tavily_valid else 'invalid/missing'}"
            )
            return self._collector
        except Exception as e:
            self._init_error = str(e)
            logger.warning(f"基本面 DataCollector 加载失败: {e}")
            return None

    def _check_tavily_valid(self) -> bool:
        """检测 Tavily API Key 是否实际有效"""
        try:
            if _DATA_COLLECTOR_DIR not in sys.path:
                sys.path.insert(0, _DATA_COLLECTOR_DIR)
            from data_collector import _get_tavily_client
            client = _get_tavily_client()
            if client is None:
                return False
            # 轻量搜索测试
            result = client.search("bitcoin", max_results=1)
            return bool(result and result.get("results"))
        except Exception as e:
            logger.info(f"Tavily Key 有效性检测失败: {e}")
            return False

    def _get_free_provider(self):
        """延迟加载免费数据源（Tavily 不可用时的降级方案）"""
        if not self._free_enabled:
            return None
        if self._free_provider is not None:
            return self._free_provider
        try:
            from dreamos.capabilities.trading.free_fundamental_provider import (
                FreeFundamentalProvider,
            )
            self._free_provider = FreeFundamentalProvider()
            logger.info("免费基本面数据源加载成功（Hyperliquid/CoinGecko/FGI/Blockchain.info）")
            return self._free_provider
        except Exception as e:
            logger.warning(f"免费基本面数据源加载失败: {e}")
            return None

    def inject(self, market_data: Dict[str, Any], symbol: str = "BTC") -> Dict[str, Any]:
        """注入基本面数据到 market_data

        Args:
            market_data: 技术面市场数据（K线/RSI/ATR等）
            symbol: 交易对（基本面数据以 BTC 为基准）

        Returns:
            注入了基本面字段的 market_data（原地修改）
        """
        # 检查缓存
        cached = self._cache.get(symbol)
        if cached and time.time() - cached[0] < self.CACHE_TTL:
            market_data.update(cached[1])
            return market_data

        collector = self._get_collector()
        if collector is None:
            # 加载失败，标注未注入
            market_data["_fundamental_source"] = "unavailable"
            market_data["_fundamental_error"] = self._init_error or "DataCollector 加载失败"
            return market_data

        # 采集各模块数据
        flat_data: Dict[str, Any] = {}
        module_sources: Dict[str, str] = {}

        collect_methods = [
            ("flow", "collect_flow"),
            ("valuation", "collect_valuation"),
            ("onchain", "collect_onchain"),
            ("macro", "collect_macro"),
            ("news", "collect_news"),
        ]

        for module_name, method_name in collect_methods:
            try:
                method = getattr(collector, method_name, None)
                if method is None:
                    continue

                source = self._detect_source(module_name)

                # P0-2: Mock 数据过滤 — 默认不注入 Mock 来源的数据
                if source == "mock" and not self.INJECT_MOCK:
                    module_sources[module_name] = "mock_skipped"
                    logger.info(f"基本面模块 {module_name} 跳过（Mock来源，未配置Tavily Key）")
                    continue

                result = method()
                core = result.get("metrics", {}).get("core", {})
                breakdown = result.get("metrics", {}).get("breakdown", {})

                # 扁平化 core + breakdown，应用字段名映射
                for src_key, value in {**core, **breakdown}.items():
                    if not isinstance(value, (int, float)):
                        continue  # 跳过非数值字段
                    target_key = FIELD_NAME_MAP.get(src_key, src_key)
                    flat_data[target_key] = value

                # 标注模块 source
                module_sources[module_name] = source

            except Exception as e:
                logger.warning(f"基本面模块 {module_name} 采集失败: {e}")
                module_sources[module_name] = "error"

        # smart_money_direction 字符串→数值转换
        smd = flat_data.get("smart_money_direction")
        if isinstance(smd, str):
            flat_data["smart_money_direction"] = SMART_MONEY_MAP.get(smd, 0.0)

        # exchange_inflow/outflow 从 breakdown 映射
        if "exchange_inflow_24h" in flat_data and "exchange_inflow" not in flat_data:
            flat_data["exchange_inflow"] = flat_data["exchange_inflow_24h"]
        if "exchange_outflow_24h" in flat_data and "exchange_outflow" not in flat_data:
            flat_data["exchange_outflow"] = flat_data["exchange_outflow_24h"]

        # liquidation_long/short 从 long_pressure/short_pressure 映射（breakdown中）
        if "long_pressure" in flat_data and "liquidation_long" not in flat_data:
            flat_data["liquidation_long"] = flat_data["long_pressure"]
        if "short_pressure" in flat_data and "liquidation_short" not in flat_data:
            flat_data["liquidation_short"] = flat_data["short_pressure"]

        # miner_balance_change 从 miner_outflow 映射（方向相反：outflow正值=减少持仓）
        if "miner_outflow" in flat_data and "miner_balance_change" not in flat_data:
            flat_data["miner_balance_change"] = -flat_data["miner_outflow"]

        # ── 免费数据源补充（Tavily 不可用时的降级方案） ──
        free_injected = 0
        free_sources_summary = ""
        if not getattr(self, "_tavily_valid", False):
            free_provider = self._get_free_provider()
            if free_provider is not None:
                try:
                    free_data = free_provider.collect_all(symbol)
                    free_injected = self._inject_free_fields(flat_data, free_data)
                    free_sources = free_data.get("_free_fundamental_sources", {})
                    free_sources_summary = "+".join(
                        k for k, v in free_sources.items()
                        if not v.endswith("_failed") and not v.startswith("skipped_")
                    )
                    logger.info(
                        f"免费数据源补充: {symbol} | 新增 {free_injected} 字段 | "
                        f"sources={free_sources_summary}"
                    )
                except Exception as e:
                    logger.warning(f"免费数据源补充失败: {e}")

        # 标注整体 source
        tavily_count = sum(1 for s in module_sources.values() if s == "tavily")
        blockchain_count = sum(1 for s in module_sources.values() if s == "blockchain")
        mock_count = sum(1 for s in module_sources.values() if s == "mock")

        if mock_count == 0 and tavily_count > 0:
            source_summary = "all_real"
        elif mock_count > 0 and tavily_count > 0:
            source_summary = f"mixed({tavily_count}real/{mock_count}mock)"
        elif blockchain_count > 0 and mock_count > 0:
            source_summary = f"blockchain+mock"
        elif free_injected > 0:
            source_summary = f"free_only({free_sources_summary})"
        else:
            source_summary = f"mock_or_error"

        flat_data["_fundamental_source"] = source_summary
        flat_data["_fundamental_module_sources"] = module_sources
        flat_data["_fundamental_injected_at"] = datetime.now().isoformat()
        flat_data["_fundamental_field_count"] = len(
            [k for k in flat_data if not k.startswith("_")]
        )
        flat_data["_fundamental_free_field_count"] = free_injected

        # 注入到 market_data
        market_data.update(flat_data)

        # 更新缓存
        self._cache[symbol] = (time.time(), flat_data)

        logger.info(
            f"基本面数据注入: {symbol} | {flat_data['_fundamental_field_count']} 字段 | "
            f"source={source_summary} | modules={module_sources}"
        )

        return market_data

    def _inject_free_fields(self, flat_data: Dict[str, Any], free_data: Dict[str, Any]) -> int:
        """将免费数据源字段映射注入到 flat_data

        只填充 flat_data 中尚不存在的字段（避免覆盖更优质的 Tavily 数据）。
        同时处理单位转换（如 Hyperliquid 的每小时 funding → F2 预期的比率）。

        Returns:
            实际新增的字段数
        """
        injected = 0

        for src_key, value in free_data.items():
            if src_key.startswith("_"):
                continue
            if not isinstance(value, (int, float)):
                continue

            target_key = FREE_FIELD_MAP.get(src_key, src_key)
            if target_key in flat_data:
                continue  # 已有数据，不覆盖

            flat_data[target_key] = value
            injected += 1

        # ── 单位转换 & 补充派生字段 ──
        # F2 的 funding_rate 阈值是 0.05（约 5% 日利率量级），
        # 优先使用 OKX 的资金费率（8h 结算，更接近主流交易所尺度），
        # 其次用 Hyperliquid 的（1h 结算），折算为日利率
        okx_fr_daily = free_data.get("okx_funding_rate_daily")
        hl_fr_daily = free_data.get("funding_rate_daily")
        fr_daily = okx_fr_daily if okx_fr_daily is not None else hl_fr_daily
        if fr_daily is not None:
            had_funding = "funding_rate" in flat_data
            flat_data["funding_rate"] = float(fr_daily)
            if not had_funding:
                injected += 1

        # F3 估值：基于 ATH 跌幅粗略推导估值区间（0~1，>1=高估）
        if "ath_drop_pct" in free_data:
            ath_drop = float(free_data["ath_drop_pct"])  # 负值表示距ATH跌幅
            # 距 ATH 跌幅 0% = 极度高估（mayer ~ 3+），跌幅 80%+ = 极度低估
            mayer_est = max(0.1, min(5.0, 1.0 + ath_drop / (-30)))
            if "mayer_multiple" not in flat_data:
                flat_data["mayer_multiple"] = round(mayer_est, 3)
                injected += 1
            # 简单估算 ahr999: 距 ATH 跌幅越大，ahr999 越低
            ahr999_est = max(0.1, min(3.0, 1.0 + ath_drop / (-50)))
            if "ahr999" not in flat_data:
                flat_data["ahr999"] = round(ahr999_est, 3)
                injected += 1

        # F5 情绪：fear_greed_index → 派生 sentiment 相关字段
        if "fear_greed_index" in free_data:
            fgi = float(free_data["fear_greed_index"])
            # F2 的 sentiment_index 近似
            if "sentiment_index" not in flat_data:
                flat_data["sentiment_index"] = fgi
                injected += 1
            # F5 的 crypto_friendly_score 粗略从 FGI 推导
            if "crypto_friendly_score" not in flat_data:
                flat_data["crypto_friendly_score"] = fgi
                injected += 1

        # F4 链上：hash_rate → 推导 miner_position（算力越高=矿工越活跃，中性偏多）
        if "hash_rate" in free_data and "miner_position" not in flat_data:
            flat_data["miner_position"] = 55.0  # 算力正常 = 中性偏多
            injected += 1

        # ── 币安 Web3 数据派生 ──
        # F2: smart_money_direction — 币安聪明钱方向直接覆盖（优于 0.0 默认值）
        bsm_dir = free_data.get("smart_money_direction")
        if bsm_dir is not None:
            prev_val = flat_data.get("smart_money_direction", 0)
            # 只有当现有值为 0 或未设置时才覆盖（避免覆盖 Tavily 更精确数据）
            if prev_val == 0 or "smart_money_direction" not in flat_data:
                flat_data["smart_money_direction"] = float(bsm_dir)
                if prev_val == 0 and "smart_money_direction" not in flat_data:
                    injected += 1

        # F5: 币安社交情绪 → 派生 crypto_friendly_score / sentiment_index
        # binance_sentiment_score 范围 [-1, 1]，映射到 [0, 100] 的 crypto_friendly_score
        # 币安社交情绪反映真实市场情绪，优先级高于 FGI 派生
        bss = free_data.get("binance_sentiment_score")
        if bss is not None:
            cfs = (float(bss) + 1) * 50  # -1→0, 0→50, 1→100
            # 币安情绪优先覆盖 FGI 派生值（社交情绪更直接反映市场情绪）
            had_cfs = "crypto_friendly_score" in flat_data
            flat_data["crypto_friendly_score"] = round(cfs, 1)
            if not had_cfs:
                injected += 1
            # sentiment_index 同步更新
            had_si = "sentiment_index" in flat_data
            flat_data["sentiment_index"] = round(cfs, 1)
            if not had_si:
                injected += 1

        return injected

    def _detect_source(self, module_name: str) -> str:
        """检测模块的数据来源

        - flow/valuation/macro/news/breadth/intermarket/calendar/narrative: 依赖 Tavily
        - onchain: 依赖 Blockchain.info
        - sentiment: 依赖 alternative.me
        """
        tavily_modules = {"flow", "valuation", "macro", "news", "breadth", "intermarket", "calendar", "narrative"}
        if module_name in tavily_modules:
            # P0-2: 使用 _tavily_valid（实际验证过 Key 有效性）而非 _tavily_available（仅检查存在）
            return "tavily" if getattr(self, "_tavily_valid", False) else "mock"
        if module_name == "onchain":
            return "blockchain"  # Blockchain.info 免费无 Key
        if module_name == "sentiment":
            return "alternative_me"  # alternative.me 免费
        return "unknown"

    def clear_cache(self, symbol: Optional[str] = None) -> None:
        """清除缓存"""
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()
