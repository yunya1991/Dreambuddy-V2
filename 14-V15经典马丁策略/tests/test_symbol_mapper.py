#!/usr/bin/env python3
"""
SymbolMapper 统一交易对适配层 — 测试套件
验证：
1. 交易对格式转换（coin ↔ spot ↔ swap）
2. 资产元数据查询（类别、合约参数覆盖）
3. 多交易所预留扩展
4. 币种池过滤与马丁策略适配
5. 与 v15_trader / capital_manager / strategy_params 的集成
"""
import sys
import os
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR / "lib"))
sys.path.insert(0, str(BASE_DIR / "core"))

from symbol_mapper import (
    SymbolMapper, AssetInfo, AssetCategory, Exchange, MarketCapTier,
    get_mapper, reset_mapper,
    to_spot, to_swap, from_spot, from_swap,
    get_category, is_supported, get_contract_overrides,
    is_martin_safe, filter_martin_safe,
)


class TestSymbolMapperConversion(unittest.TestCase):
    """交易对格式转换"""

    def setUp(self):
        reset_mapper()
        self.m = SymbolMapper()

    def test_to_spot_okx(self):
        self.assertEqual(self.m.to_spot("BTC"), "BTC-USDT")
        self.assertEqual(self.m.to_spot("btc"), "BTC-USDT")  # 大小写归一
        self.assertEqual(self.m.to_spot("XAUT"), "XAUT-USDT")

    def test_to_swap_okx(self):
        self.assertEqual(self.m.to_swap("BTC"), "BTC-USDT-SWAP")
        self.assertEqual(self.m.to_swap("eth"), "ETH-USDT-SWAP")
        self.assertEqual(self.m.to_swap("PAXG"), "PAXG-USDT-SWAP")

    def test_from_spot_okx(self):
        self.assertEqual(self.m.from_spot("BTC-USDT"), "BTC")
        self.assertEqual(self.m.from_spot("doge-USDT"), "DOGE")

    def test_from_swap_okx(self):
        self.assertEqual(self.m.from_swap("BTC-USDT-SWAP"), "BTC")
        self.assertEqual(self.m.from_swap("xaut-USDT-SWAP"), "XAUT")

    def test_from_any_auto_detect(self):
        self.assertEqual(self.m.from_any("BTC-USDT-SWAP"), "BTC")
        self.assertEqual(self.m.from_any("ETH-USDT"), "ETH")

    def test_binance_format_preset(self):
        # 预留 Binance 格式
        self.assertEqual(self.m.to_spot("BTC", "binance"), "BTCUSDT")
        self.assertEqual(self.m.to_swap("BTC", "binance"), "BTCUSDT-PERP")

    def test_unknown_coin_still_formats(self):
        # 未知币种也应能格式化（不抛异常）
        self.assertEqual(self.m.to_spot("UNKNOWNXYZ"), "UNKNOWNXYZ-USDT")
        self.assertEqual(self.m.to_swap("UNKNOWNXYZ"), "UNKNOWNXYZ-USDT-SWAP")

    def test_module_level_helpers(self):
        self.assertEqual(to_spot("BTC"), "BTC-USDT")
        self.assertEqual(to_swap("ETH"), "ETH-USDT-SWAP")
        self.assertEqual(from_swap("BTC-USDT-SWAP"), "BTC")
        self.assertEqual(from_spot("BTC-USDT"), "BTC")


class TestAssetMetadata(unittest.TestCase):
    """资产元数据查询"""

    def setUp(self):
        reset_mapper()
        self.m = SymbolMapper()

    def test_get_category_crypto(self):
        self.assertEqual(self.m.get_category("BTC"), AssetCategory.CRYPTO)
        self.assertEqual(self.m.get_category("ETH"), AssetCategory.CRYPTO)
        self.assertEqual(self.m.get_category("SOL"), AssetCategory.CRYPTO)

    def test_get_category_precious_metal(self):
        self.assertEqual(self.m.get_category("XAUT"), AssetCategory.PRECIOUS_METAL)
        self.assertEqual(self.m.get_category("PAXG"), AssetCategory.PRECIOUS_METAL)

    def test_get_category_unknown_defaults_crypto(self):
        self.assertEqual(self.m.get_category("UNKNOWNXYZ"), AssetCategory.CRYPTO)

    def test_is_supported_okx(self):
        self.assertTrue(self.m.is_supported("BTC", "okx"))
        self.assertTrue(self.m.is_supported("XAUT", "okx"))
        self.assertTrue(self.m.is_supported("PAXG", "okx"))

    def test_is_supported_binance_not_registered(self):
        # 默认币种未注册 binance 支持
        self.assertFalse(self.m.is_supported("BTC", "binance"))

    def test_is_supported_unknown(self):
        self.assertFalse(self.m.is_supported("UNKNOWNXYZ", "okx"))

    def test_get_contract_overrides_precious_metal(self):
        # 贵金属有合约参数覆盖
        ov = self.m.get_contract_overrides("XAUT")
        self.assertEqual(ov["lot_sz"], 0.01)
        self.assertEqual(ov["ct_val"], 1.0)

        ov2 = self.m.get_contract_overrides("PAXG")
        self.assertEqual(ov2["lot_sz"], 0.001)

    def test_get_contract_overrides_crypto_none(self):
        # 加密货币默认无覆盖（由 API 动态获取）
        ov = self.m.get_contract_overrides("BTC")
        self.assertIsNone(ov["lot_sz"])
        self.assertIsNone(ov["ct_val"])


class TestRegistryManagement(unittest.TestCase):
    """注册表管理"""

    def setUp(self):
        reset_mapper()
        self.m = SymbolMapper()

    def test_list_coins_all(self):
        coins = self.m.list_coins()
        self.assertIn("BTC", coins)
        self.assertIn("XAUT", coins)
        self.assertGreater(len(coins), 30)

    def test_list_coins_by_category(self):
        metals = self.m.list_coins(category=AssetCategory.PRECIOUS_METAL)
        self.assertEqual(set(metals), {"XAUT", "PAXG"})

        cryptos = self.m.list_coins(category=AssetCategory.CRYPTO)
        self.assertIn("BTC", cryptos)
        self.assertNotIn("XAUT", cryptos)

    def test_register_custom_asset(self):
        # 模拟注册股票代币
        stock = AssetInfo(
            symbol="TSLA", name="Tesla Stock Token",
            category=AssetCategory.STOCK,
            exchanges={"okx": False, "binance": True},
            lot_sz_override=0.1,
        )
        self.m.register(stock)

        self.assertTrue(self.m.is_supported("TSLA", "binance"))
        self.assertFalse(self.m.is_supported("TSLA", "okx"))
        self.assertEqual(self.m.get_category("TSLA"), AssetCategory.STOCK)
        ov = self.m.get_contract_overrides("TSLA")
        self.assertEqual(ov["lot_sz"], 0.1)

    def test_filter_supported(self):
        coins = ["BTC", "XAUT", "UNKNOWNXYZ", "ETH"]
        supported = self.m.filter_supported(coins, "okx")
        self.assertIn("BTC", supported)
        self.assertIn("XAUT", supported)
        self.assertIn("ETH", supported)
        self.assertNotIn("UNKNOWNXYZ", supported)

    def test_to_swap_batch(self):
        swaps = self.m.to_swap_batch(["BTC", "ETH", "XAUT"])
        self.assertEqual(swaps, ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "XAUT-USDT-SWAP"])

    def test_summary(self):
        s = self.m.summary()
        self.assertGreater(s["total"], 30)
        self.assertIn("precious_metal", s["by_category"])
        self.assertEqual(s["by_category"]["precious_metal"], 2)
        self.assertGreater(s["okx_supported"], 30)


class TestMartinSafeFilter(unittest.TestCase):
    """马丁策略风控过滤：市值等级 + 上线时间"""

    def setUp(self):
        reset_mapper()
        self.m = SymbolMapper()

    def test_market_cap_tier_large(self):
        self.assertEqual(self.m.get_market_cap_tier("BTC"), MarketCapTier.LARGE)
        self.assertEqual(self.m.get_market_cap_tier("ETH"), MarketCapTier.LARGE)
        self.assertEqual(self.m.get_market_cap_tier("OKB"), MarketCapTier.LARGE)

    def test_market_cap_tier_mid(self):
        self.assertEqual(self.m.get_market_cap_tier("INJ"), MarketCapTier.MID)
        self.assertEqual(self.m.get_market_cap_tier("AAVE"), MarketCapTier.MID)
        self.assertEqual(self.m.get_market_cap_tier("ZEC"), MarketCapTier.MID)
        self.assertEqual(self.m.get_market_cap_tier("HYPE"), MarketCapTier.MID)

    def test_market_cap_tier_small(self):
        self.assertEqual(self.m.get_market_cap_tier("PEPE"), MarketCapTier.SMALL)
        self.assertEqual(self.m.get_market_cap_tier("SHIB"), MarketCapTier.SMALL)
        self.assertEqual(self.m.get_market_cap_tier("APE"), MarketCapTier.SMALL)

    def test_market_cap_tier_unknown(self):
        self.assertIsNone(self.m.get_market_cap_tier("UNKNOWNXYZ"))

    def test_listing_date(self):
        ld = self.m.get_listing_date("BTC")
        self.assertEqual(ld, "2013-04-28")
        self.assertIsNone(self.m.get_listing_date("UNKNOWNXYZ"))

    def test_is_martin_safe_large_passes(self):
        self.assertTrue(self.m.is_martin_safe("BTC"))
        self.assertTrue(self.m.is_martin_safe("ETH"))
        self.assertTrue(self.m.is_martin_safe("SOL"))

    def test_is_martin_safe_mid_passes(self):
        self.assertTrue(self.m.is_martin_safe("INJ"))
        self.assertTrue(self.m.is_martin_safe("AAVE"))
        self.assertTrue(self.m.is_martin_safe("HYPE"))

    def test_is_martin_safe_small_rejected(self):
        self.assertFalse(self.m.is_martin_safe("PEPE"))
        self.assertFalse(self.m.is_martin_safe("SHIB"))
        self.assertFalse(self.m.is_martin_safe("WLD"))
        self.assertFalse(self.m.is_martin_safe("SUSHI"))
        self.assertFalse(self.m.is_martin_safe("APE"))

    def test_is_martin_safe_unknown_rejected(self):
        self.assertFalse(self.m.is_martin_safe("UNKNOWNXYZ"))

    def test_is_martin_safe_large_only_tier(self):
        # min_tier=large 时，MID 币种被剔除
        self.assertTrue(self.m.is_martin_safe("BTC", min_tier=MarketCapTier.LARGE))
        self.assertFalse(self.m.is_martin_safe("INJ", min_tier=MarketCapTier.LARGE))

    def test_is_martin_safe_small_tier_allows_all(self):
        # min_tier=small 时，所有等级通过（但仍需满足时间检测）
        self.assertTrue(self.m.is_martin_safe("PEPE", min_tier=MarketCapTier.SMALL))
        self.assertTrue(self.m.is_martin_safe("BTC", min_tier=MarketCapTier.SMALL))

    def test_is_martin_safe_min_history_days(self):
        # HYPE 上线 2024-11-29，距今 >365 天，但 <10000 天
        # 用极大阈值测试时间过滤
        self.assertFalse(self.m.is_martin_safe("HYPE", min_tier=MarketCapTier.MID, min_history_days=10000))
        # 正常阈值应通过（时间层面）
        self.assertTrue(self.m.is_martin_safe("HYPE", min_tier=MarketCapTier.MID, min_history_days=365))

    def test_filter_martin_safe_batch(self):
        coins = ["BTC", "PEPE", "ETH", "SHIB", "INJ", "WLD", "SOL"]
        safe = self.m.filter_martin_safe(coins)
        self.assertIn("BTC", safe)
        self.assertIn("ETH", safe)
        self.assertIn("INJ", safe)
        self.assertIn("SOL", safe)
        self.assertNotIn("PEPE", safe)
        self.assertNotIn("SHIB", safe)
        self.assertNotIn("WLD", safe)

    def test_small_cap_martin_disabled(self):
        """小市值币种应默认 martin_enabled=False"""
        info = self.m.get_asset_info("PEPE")
        self.assertFalse(info.martin_enabled)
        info2 = self.m.get_asset_info("APE")
        self.assertFalse(info2.martin_enabled)

    def test_hype_martin_enabled(self):
        """HYPE 已从SMALL提升至MID，martin_enabled应为True"""
        info = self.m.get_asset_info("HYPE")
        self.assertEqual(info.market_cap_tier, MarketCapTier.MID)
        self.assertTrue(info.martin_enabled)
        self.assertTrue(self.m.is_martin_safe("HYPE"))

    def test_module_level_is_martin_safe(self):
        self.assertTrue(is_martin_safe("BTC"))
        self.assertFalse(is_martin_safe("PEPE"))

    def test_module_level_filter_martin_safe(self):
        safe = filter_martin_safe(["BTC", "PEPE", "ETH"])
        self.assertEqual(safe, ["BTC", "ETH"])


class TestV15Integration(unittest.TestCase):
    """V15 系统集成：币种池过滤与适配层接入"""

    def test_v15_trader_coins_filtered(self):
        """v15_trader 的 COINS 列表应通过 SymbolMapper 过滤"""
        import v15_trader
        # 至少包含原始币种
        self.assertIn("BTC", v15_trader.COINS)
        self.assertIn("ETH", v15_trader.COINS)
        # 所有币种都应是 OKX 支持的
        for coin in v15_trader.COINS:
            self.assertTrue(
                is_supported(coin, "okx"),
                f"币种 {coin} 在 v15_trader.COINS 中但未被 SymbolMapper 标记为 OKX 支持",
            )

    def test_v15_trader_coins_count_expanded(self):
        """扩展后币种池应大于原始8个"""
        import v15_trader
        self.assertGreaterEqual(len(v15_trader.COINS), 8)

    def test_v15_trader_has_precious_metal(self):
        """扩展后应包含贵金属代币"""
        import v15_trader
        self.assertIn("XAUT", v15_trader.COINS)
        self.assertIn("PAXG", v15_trader.COINS)

    def test_capital_manager_coins_filtered(self):
        """capital_manager 的 V15_COINS 列表应通过 SymbolMapper 过滤"""
        import capital_manager
        for coin in capital_manager.V15_COINS:
            self.assertTrue(
                is_supported(coin, "okx"),
                f"币种 {coin} 在 capital_manager.V15_COINS 中但未被 SymbolMapper 标记为 OKX 支持",
            )

    def test_capital_manager_to_swap_integration(self):
        """capital_manager 应使用 to_swap 而非硬编码"""
        import inspect
        import capital_manager
        # 不应再有硬编码的 f"{symbol}-USDT-SWAP" 拼接（除注释外）
        # 检查 get_current_positions 函数体
        get_pos_src = inspect.getsource(capital_manager.get_current_positions)
        self.assertNotIn('f"{symbol}-USDT-SWAP"', get_pos_src)
        self.assertIn("to_swap", get_pos_src)

    def test_v15_trader_to_spot_integration(self):
        """v15_trader.get_v15_decision 应使用 to_spot"""
        import inspect
        import v15_trader
        src = inspect.getsource(v15_trader.get_v15_decision)
        self.assertNotIn('f"{coin}-USDT"', src)
        self.assertIn("to_spot", src)

    def test_v15_trader_to_swap_integration(self):
        """v15_trader.execute_open_position 应使用 to_swap"""
        import inspect
        import v15_trader
        src = inspect.getsource(v15_trader.execute_open_position)
        self.assertNotIn('f"{coin}-USDT-SWAP"', src)
        self.assertIn("to_swap", src)

    def test_strategy_params_to_swap_integration(self):
        """strategy_params.get_coin_strategy_params 应使用 to_swap"""
        import inspect
        import strategy_params
        src = inspect.getsource(strategy_params.get_coin_strategy_params)
        self.assertNotIn('f"{symbol}-USDT-SWAP"', src)
        self.assertIn("to_swap", src)


class TestNoHardcodedPairs(unittest.TestCase):
    """回归测试：确保不再有新的硬编码拼接"""

    def test_v15_trader_no_hardcoded_swap(self):
        import v15_trader
        import inspect
        # 检查所有函数源码，不应有 f"...-USDT-SWAP" 硬编码（除降级 fallback）
        for name, fn in inspect.getmembers(v15_trader, inspect.isfunction):
            if fn.__module__ != v15_trader.__name__:
                continue
            src = inspect.getsource(fn)
            # 允许 fallback def 中出现，但不允许业务逻辑中出现
            # 简化检查：业务函数不应直接拼接
            if name in ("execute_open_position", "get_v15_decision"):
                self.assertNotIn('f"{coin}-USDT-SWAP"', src)
                self.assertNotIn('f"{coin}-USDT"', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
