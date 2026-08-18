#!/usr/bin/env python3
"""
统一交易对适配层 (SymbolMapper)
================================

目的：
- 内部统一使用 coin 名（如 "BTC"、"XAUT"），消除散落在各模块的
  `f"{coin}-USDT"` / `f"{coin}-USDT-SWAP"` 硬编码拼接。
- 对外按交易所自动适配交易对格式：
    OKX:     {coin}-USDT       (现货)
             {coin}-USDT-SWAP  (永续合约)
    Binance: {coin}USDT        (现货，预留)
             {coin}USDT-PERP   (永续，预留)
- 维护资产元数据（类别、合约参数覆盖、最小下单量），为马丁策略
  扩展到贵金属 / 股票等 TradFi 资产提供基础。

设计原则：
1. 仅在内存中维护注册表，不依赖外部文件，避免启动期 IO。
2. 所有方法对未知币种优雅降级（返回 None 或回退到 crypto 默认）。
3. 预留多交易所扩展接口，但当前仅实现 OKX（实盘）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Dict, List, Optional


class AssetCategory(str, Enum):
    """资产大类"""
    CRYPTO = "crypto"               # 加密货币
    PRECIOUS_METAL = "precious_metal"  # 贵金属 (XAUT/PAXG 等代币化黄金)
    STOCK = "stock"                 # 股票代币
    INDEX = "index"                 # 指数代币
    COMMODITY = "commodity"         # 大宗商品


class Exchange(str, Enum):
    """支持交易所（预留扩展）"""
    OKX = "okx"
    BINANCE = "binance"


class MarketCapTier(str, Enum):
    """市值等级（用于马丁策略风控过滤）"""
    LARGE = "large"   # 大市值：Top 20，流动性深，黑天鹅风险低
    MID = "mid"       # 中等市值：Top 20-60，流动性尚可
    SMALL = "small"   # 小市值：排名靠后或高波动meme币，黑天鹅风险高


@dataclass
class AssetInfo:
    """单个资产元数据"""
    symbol: str                              # 内部 coin 名，如 "BTC"
    name: str                                # 展示名，如 "Bitcoin"
    category: AssetCategory = AssetCategory.CRYPTO
    # 各交易所支持情况，True=该交易所有此币种的USDT永续合约
    exchanges: Dict[str, bool] = field(default_factory=lambda: {"okx": True})
    # 合约参数覆盖（None=由交易所API动态获取）
    lot_sz_override: Optional[float] = None  # 最小下单张数
    tick_sz_override: Optional[float] = None  # 价格精度
    ct_val_override: Optional[float] = None   # 合约面值
    # 马丁策略适配提示
    martin_enabled: bool = True              # 是否纳入马丁策略币种池
    # ── 马丁风控字段 ──
    market_cap_tier: MarketCapTier = MarketCapTier.MID  # 市值等级
    listing_date: Optional[str] = None       # 上线日期 ISO 格式 "YYYY-MM-DD"，None=未知(按不通过处理)


class SymbolMapper:
    """
    统一交易对适配器
    ================

    用法:
        mapper = SymbolMapper()
        mapper.to_swap("BTC")              # "BTC-USDT-SWAP"
        mapper.to_spot("XAUT")             # "XAUT-USDT"
        mapper.from_swap("ETH-USDT-SWAP")  # "ETH"
        mapper.get_category("XAUT")        # AssetCategory.PRECIOUS_METAL
    """

    # OKX 交易对格式模板
    _OKX_SPOT_FMT = "{coin}-USDT"
    _OKX_SWAP_FMT = "{coin}-USDT-SWAP"
    # Binance 预留格式
    _BINANCE_SPOT_FMT = "{coin}USDT"
    _BINANCE_SWAP_FMT = "{coin}USDT-PERP"

    def __init__(self):
        self._registry: Dict[str, AssetInfo] = {}
        self._register_defaults()

    # ── 默认注册表 ──────────────────────────────────────────────

    def _register_defaults(self):
        """注册 OKX 常见支持的资产（含加密货币 + 贵金属代币）

        每个币种标注 market_cap_tier 和 listing_date：
        - LARGE: 大市值（Top 20），流动性深，黑天鹅风险低
        - MID:   中等市值（Top 20-60），流动性尚可
        - SMALL: 小市值/高波动meme币，马丁策略剔除
        - listing_date: 主流交易所上线日期，用于上线时间检测
        """

        # ── 大市值主流币（LARGE）──
        large_caps = [
            ("BTC",   "Bitcoin",        "2013-04-28"),
            ("ETH",   "Ethereum",       "2015-08-07"),
            ("SOL",   "Solana",         "2020-04-10"),
            ("BNB",   "BNB",            "2017-07-25"),
            ("XRP",   "Ripple",         "2013-08-04"),
            ("ADA",   "Cardano",        "2017-10-01"),
            ("DOGE",  "Dogecoin",       "2013-12-15"),
            ("LTC",   "Litecoin",       "2013-04-28"),
            ("LINK",  "Chainlink",      "2019-05-30"),
            ("AVAX",  "Avalanche",      "2020-09-22"),
            ("DOT",   "Polkadot",       "2020-08-18"),
            ("TRX",   "TRON",           "2018-05-31"),
            ("MATIC", "Polygon",        "2019-04-28"),
            ("ATOM",  "Cosmos",         "2019-03-14"),
            ("UNI",   "Uniswap",        "2020-09-17"),
            ("NEAR",  "NEAR Protocol",  "2020-10-13"),
            ("APT",   "Aptos",          "2022-10-17"),
            ("FIL",   "Filecoin",       "2020-10-15"),
            ("ARB",   "Arbitrum",       "2023-03-23"),
            ("OP",    "Optimism",       "2022-06-23"),
        ]
        for sym, name, ld in large_caps:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.CRYPTO,
                exchanges={"okx": True},
                market_cap_tier=MarketCapTier.LARGE,
                listing_date=ld,
            ))

        # ── 交易所平台币（LARGE）──
        self.register(AssetInfo(
            symbol="OKB", name="OKB",
            category=AssetCategory.CRYPTO,
            exchanges={"okx": True},
            market_cap_tier=MarketCapTier.LARGE,
            listing_date="2019-05-09",
        ))

        # ── 中等市值币（MID）──
        mid_caps = [
            ("INJ",  "Injective",    "2020-11-03"),
            ("SUI",  "Sui",          "2023-05-03"),
            ("SEI",  "Sei",          "2023-08-15"),
            ("TIA",  "Celestia",     "2023-10-31"),
            ("RUNE", "THORChain",    "2019-07-22"),
            ("AAVE", "Aave",         "2020-10-02"),
            ("ALGO", "Algorand",     "2019-06-19"),
            ("AXS",  "Axie Infinity","2020-11-04"),
            ("CHZ",  "Chiliz",       "2019-07-09"),
            ("COMP", "Compound",     "2020-06-18"),
            ("CRV",  "Curve DAO",    "2020-08-13"),
            ("DYDX", "dYdX",         "2021-09-09"),
            ("GALA", "Gala",         "2020-09-18"),
            ("GRT",  "The Graph",    "2020-12-17"),
            ("IMX",  "Immutable X",  "2021-11-19"),
            ("LDO",  "Lido DAO",     "2022-05-16"),
            ("MKR",  "Maker",        "2017-08-15"),
            ("RNDR", "Render",       "2021-04-07"),
            ("SAND", "The Sandbox",  "2020-08-15"),
            ("STX",  "Stacks",       "2020-05-28"),
            ("ZEC",  "Zcash",        "2016-10-28"),
            ("HYPE", "Hyperliquid",  "2024-11-29"),  # 平台币，上线>1年，潜力大
            ("PUMP", "Pump.fun",     "2024-08-15"),  # Solana meme/pump 代币，上线>300天
        ]
        for sym, name, ld in mid_caps:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.CRYPTO,
                exchanges={"okx": True},
                market_cap_tier=MarketCapTier.MID,
                listing_date=ld,
            ))

        # ── 小市值/高波动meme币（SMALL）—— 马丁策略剔除，避免黑天鹅 ──
        small_caps = [
            ("APE",   "ApeCoin",      "2022-03-17"),   # meme币，暴涨暴跌
            ("PEPE",  "Pepe",         "2023-04-18"),   # meme币，极端波动
            ("SHIB",  "Shiba Inu",    "2020-08-01"),   # meme币，极端波动
            ("SUSHI", "SushiSwap",    "2020-09-01"),   # 低市值，流动性差
            ("WLD",   "Worldcoin",    "2023-07-24"),   # 新币+高波动
        ]
        for sym, name, ld in small_caps:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.CRYPTO,
                exchanges={"okx": True},
                market_cap_tier=MarketCapTier.SMALL,
                listing_date=ld,
                martin_enabled=False,  # 默认不纳入马丁策略
            ))

        # ── 贵金属代币（OKX SWAP 支持）──
        precious_metals = [
            ("XAUT", "Tether Gold", 0.01, 0.01, 1.0, "2020-01-09"),   # XAUT 现货代币（非SWAP）
            ("PAXG", "Paxos Gold",  0.001, 0.01, 1.0, "2020-09-11"),  # PAXG-USDT-SWAP
            ("XAG",  "Silver",      0.01, 0.01, 1.0, "2020-01-01"),   # XAG-USDT-SWAP, 白银
            ("XAU",  "Gold Index",  1,    0.1,  0.001, "2020-01-01"), # XAU-USDT-SWAP, 黄金指数永续
        ]
        for sym, name, lot, tick, ctval, ld in precious_metals:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.PRECIOUS_METAL,
                exchanges={"okx": True},
                lot_sz_override=lot,
                tick_sz_override=tick,
                ct_val_override=ctval,
                market_cap_tier=MarketCapTier.LARGE,  # 黄金=大类资产
                listing_date=ld,
            ))

        # ── 美股个股永续（OKX SWAP 支持）──
        # 上市日期用股票本体上市日期（远超1年风控门槛），OKX 永续 lot_sz=0.01
        us_stocks = [
            ("MU",       "Micron Technology",  0.01, 0.01, 1.0, "1994-06-01"),   # 美光
            ("SKHYNIX",  "SK hynix",           0.01, 0.01, 1.0, "2014-01-01"),   # 海力士
            ("GOOGL",    "Alphabet (Google)",  0.01, 0.01, 1.0, "2004-08-19"),   # 谷歌
            ("NVDA",     "NVIDIA",             0.01, 0.01, 1.0, "1999-01-22"),   # 英伟达
            ("AMZN",     "Amazon",             0.01, 0.01, 1.0, "1997-05-15"),   # 亚马逊
            ("SNDK",     "SanDisk",            0.01, 0.01, 1.0, "1995-03-08"),   # 闪迪
            ("SPCX",     "SpaceX",             0.01, 0.01, 1.0, "2024-01-01"),   # SpaceX (OKX永续)
        ]
        for sym, name, lot, tick, ctval, ld in us_stocks:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.STOCK,
                exchanges={"okx": True},
                lot_sz_override=lot,
                tick_sz_override=tick,
                ct_val_override=ctval,
                market_cap_tier=MarketCapTier.LARGE,  # 美股大盘股
                listing_date=ld,
            ))

    # ── 注册 / 查询 ──────────────────────────────────────────────

    def register(self, asset: AssetInfo):
        """注册或更新一个资产"""
        self._registry[asset.symbol.upper()] = asset

    def get_asset_info(self, coin: str) -> Optional[AssetInfo]:
        """获取资产元数据，未知币种返回 None"""
        return self._registry.get(coin.upper())

    def get_category(self, coin: str) -> AssetCategory:
        """获取资产类别，未知币种默认 CRYPTO"""
        info = self.get_asset_info(coin)
        return info.category if info else AssetCategory.CRYPTO

    def is_supported(self, coin: str, exchange: str = "okx") -> bool:
        """该币种是否在指定交易所支持"""
        info = self.get_asset_info(coin)
        if not info:
            return False
        return info.exchanges.get(exchange, False)

    def is_martin_enabled(self, coin: str) -> bool:
        """是否纳入马丁策略币种池"""
        info = self.get_asset_info(coin)
        return info.martin_enabled if info else True

    def get_market_cap_tier(self, coin: str) -> Optional[MarketCapTier]:
        """获取市值等级，未知币种返回 None"""
        info = self.get_asset_info(coin)
        return info.market_cap_tier if info else None

    def get_listing_date(self, coin: str) -> Optional[str]:
        """获取上线日期 ISO 字符串，未知币种返回 None"""
        info = self.get_asset_info(coin)
        return info.listing_date if info else None

    def is_martin_safe(
        self,
        coin: str,
        min_tier: MarketCapTier = MarketCapTier.MID,
        min_history_days: int = 365,
    ) -> bool:
        """马丁策略风控检查：市值等级 + 上线时间双重过滤

        Args:
            coin: 币种符号
            min_tier: 最低市值等级（LARGE > MID > SMALL），默认 MID
            min_history_days: 最小上线天数，默认 365 天（1年）

        Returns:
            True = 通过风控检查，可纳入马丁策略
            False = 不通过（小市值 或 上线时间不足 或 未知币种）
        """
        info = self.get_asset_info(coin)
        if not info:
            return False  # 未知币种，不通过

        # 市值等级检查
        tier_order = {MarketCapTier.LARGE: 3, MarketCapTier.MID: 2, MarketCapTier.SMALL: 1}
        coin_level = tier_order.get(info.market_cap_tier, 0)
        min_level = tier_order.get(min_tier, 2)
        if coin_level < min_level:
            return False

        # 上线时间检查
        if not info.listing_date:
            return False  # 无上线日期，按不通过处理
        try:
            ld = datetime.strptime(info.listing_date, "%Y-%m-%d").date()
            days_listed = (date.today() - ld).days
            if days_listed < min_history_days:
                return False
        except (ValueError, TypeError):
            return False  # 日期解析失败，不通过

        return True

    def filter_martin_safe(
        self,
        coins: List[str],
        min_tier: MarketCapTier = MarketCapTier.MID,
        min_history_days: int = 365,
    ) -> List[str]:
        """批量过滤出通过马丁风控检查的币种"""
        return [
            c.upper() for c in coins
            if self.is_martin_safe(c, min_tier, min_history_days)
        ]

    def list_coins(
        self,
        category: Optional[AssetCategory] = None,
        exchange: str = "okx",
        martin_only: bool = False,
    ) -> List[str]:
        """列出符合条件的币种"""
        result = []
        for sym, info in self._registry.items():
            if not info.exchanges.get(exchange, False):
                continue
            if category is not None and info.category != category:
                continue
            if martin_only and not info.martin_enabled:
                continue
            result.append(sym)
        return sorted(result)

    # ── 交易对格式转换 ───────────────────────────────────────────

    def to_spot(self, coin: str, exchange: str = "okx") -> str:
        """coin → 现货交易对，如 BTC → BTC-USDT"""
        coin = coin.upper()
        if exchange == Exchange.OKX or exchange == "okx":
            return self._OKX_SPOT_FMT.format(coin=coin)
        if exchange == Exchange.BINANCE or exchange == "binance":
            return self._BINANCE_SPOT_FMT.format(coin=coin)
        # 默认 OKX 格式
        return self._OKX_SPOT_FMT.format(coin=coin)

    def to_swap(self, coin: str, exchange: str = "okx") -> str:
        """coin → 永续合约交易对，如 BTC → BTC-USDT-SWAP"""
        coin = coin.upper()
        if exchange == Exchange.OKX or exchange == "okx":
            return self._OKX_SWAP_FMT.format(coin=coin)
        if exchange == Exchange.BINANCE or exchange == "binance":
            return self._BINANCE_SWAP_FMT.format(coin=coin)
        return self._OKX_SWAP_FMT.format(coin=coin)

    def from_spot(self, inst_id: str, exchange: str = "okx") -> Optional[str]:
        """现货交易对 → coin，如 BTC-USDT → BTC"""
        inst_id = inst_id.upper()
        if exchange == Exchange.OKX or exchange == "okx":
            # BTC-USDT
            if inst_id.endswith("-USDT"):
                return inst_id[:-len("-USDT")]
        if exchange == Exchange.BINANCE or exchange == "binance":
            # BTCUSDT
            if inst_id.endswith("USDT"):
                return inst_id[:-len("USDT")]
        # 通用回退：剥离已知后缀
        for suffix in ("-USDT-SWAP", "-USDT", "USDT-PERP", "USDT"):
            if inst_id.endswith(suffix):
                return inst_id[:-len(suffix)]
        return None

    def from_swap(self, inst_id: str, exchange: str = "okx") -> Optional[str]:
        """永续合约交易对 → coin，如 BTC-USDT-SWAP → BTC"""
        inst_id = inst_id.upper()
        if exchange == Exchange.OKX or exchange == "okx":
            if inst_id.endswith("-USDT-SWAP"):
                return inst_id[:-len("-USDT-SWAP")]
        if exchange == Exchange.BINANCE or exchange == "binance":
            if inst_id.endswith("-PERP"):
                return inst_id[:-len("-PERP")]
            if inst_id.endswith("USDT-PERP"):
                return inst_id[:-len("USDT-PERP")]
        # 通用回退
        for suffix in ("-USDT-SWAP", "-USDT-PERP", "-PERP"):
            if inst_id.endswith(suffix):
                return inst_id[:-len(suffix)]
        return None

    def from_any(self, inst_id: str) -> Optional[str]:
        """任意格式交易对 → coin（自动识别）"""
        coin = self.from_swap(inst_id)
        if coin:
            return coin
        return self.from_spot(inst_id)

    # ── 合约参数覆盖 ─────────────────────────────────────────────

    def get_contract_overrides(self, coin: str) -> Dict[str, Optional[float]]:
        """
        获取合约参数覆盖值。返回 dict：
            {"lot_sz": ..., "tick_sz": ..., "ct_val": ...}
        其中 None 表示由交易所 API 动态获取。
        """
        info = self.get_asset_info(coin)
        if not info:
            return {"lot_sz": None, "tick_sz": None, "ct_val": None}
        return {
            "lot_sz": info.lot_sz_override,
            "tick_sz": info.tick_sz_override,
            "ct_val": info.ct_val_override,
        }

    # ── 批量辅助 ─────────────────────────────────────────────────

    def filter_supported(self, coins: List[str], exchange: str = "okx") -> List[str]:
        """从币种列表中筛出指定交易所支持的币种"""
        return [c.upper() for c in coins if self.is_supported(c, exchange)]

    def to_swap_batch(self, coins: List[str], exchange: str = "okx") -> List[str]:
        """批量转换为合约交易对"""
        return [self.to_swap(c, exchange) for c in coins]

    def summary(self) -> Dict:
        """返回注册表汇总统计"""
        from collections import Counter
        cat_count = Counter()
        for info in self._registry.values():
            cat_count[info.category.value] += 1
        return {
            "total": len(self._registry),
            "by_category": dict(cat_count),
            "okx_supported": sum(1 for i in self._registry.values() if i.exchanges.get("okx")),
        }


# ── 模块级单例 ──────────────────────────────────────────────────

_mapper_instance: Optional[SymbolMapper] = None


def get_mapper() -> SymbolMapper:
    """获取全局 SymbolMapper 单例"""
    global _mapper_instance
    if _mapper_instance is None:
        _mapper_instance = SymbolMapper()
    return _mapper_instance


def reset_mapper():
    """重置单例（测试用）"""
    global _mapper_instance
    _mapper_instance = None


# ── 便捷函数（替代散落的硬编码拼接）────────────────────────────

def to_spot(coin: str, exchange: str = "okx") -> str:
    """便捷函数：coin → 现货对"""
    return get_mapper().to_spot(coin, exchange)


def to_swap(coin: str, exchange: str = "okx") -> str:
    """便捷函数：coin → 合约对"""
    return get_mapper().to_swap(coin, exchange)


def from_swap(inst_id: str, exchange: str = "okx") -> Optional[str]:
    """便捷函数：合约对 → coin"""
    return get_mapper().from_swap(inst_id, exchange)


def from_spot(inst_id: str, exchange: str = "okx") -> Optional[str]:
    """便捷函数：现货对 → coin"""
    return get_mapper().from_spot(inst_id, exchange)


def get_category(coin: str) -> AssetCategory:
    """便捷函数：获取资产类别"""
    return get_mapper().get_category(coin)


def is_supported(coin: str, exchange: str = "okx") -> bool:
    """便捷函数：是否在交易所支持"""
    return get_mapper().is_supported(coin, exchange)


def get_contract_overrides(coin: str) -> Dict[str, Optional[float]]:
    """便捷函数：获取合约参数覆盖"""
    return get_mapper().get_contract_overrides(coin)


def is_martin_safe(
    coin: str,
    min_tier: MarketCapTier = MarketCapTier.MID,
    min_history_days: int = 365,
) -> bool:
    """便捷函数：马丁策略风控检查（市值等级 + 上线时间）"""
    return get_mapper().is_martin_safe(coin, min_tier, min_history_days)


def filter_martin_safe(
    coins: List[str],
    min_tier: MarketCapTier = MarketCapTier.MID,
    min_history_days: int = 365,
) -> List[str]:
    """便捷函数：批量过滤马丁风控通过的币种"""
    return get_mapper().filter_martin_safe(coins, min_tier, min_history_days)


if __name__ == "__main__":
    # 自检
    m = SymbolMapper()
    print("=== SymbolMapper 自检 ===")
    print(f"to_swap('BTC') = {m.to_swap('BTC')}")
    print(f"to_spot('XAUT') = {m.to_spot('XAUT')}")
    print(f"from_swap('ETH-USDT-SWAP') = {m.from_swap('ETH-USDT-SWAP')}")
    print(f"from_spot('DOGE-USDT') = {m.from_spot('DOGE-USDT')}")
    print(f"get_category('XAUT') = {m.get_category('XAUT')}")
    print(f"get_category('BTC') = {m.get_category('BTC')}")
    print(f"is_supported('PAXG', 'okx') = {m.is_supported('PAXG', 'okx')}")
    print(f"is_supported('BTC', 'binance') = {m.is_supported('BTC', 'binance')}")
    print(f"get_contract_overrides('XAUT') = {m.get_contract_overrides('XAUT')}")
    print(f"summary = {m.summary()}")
    print(f"\n贵金属币种: {m.list_coins(category=AssetCategory.PRECIOUS_METAL)}")
    print(f"加密币种总数: {len(m.list_coins(category=AssetCategory.CRYPTO))}")

    # ── 马丁风控检查自检 ──
    print("\n=== 马丁策略风控检查 ===")
    all_coins = m.list_coins()
    safe = m.filter_martin_safe(all_coins)
    unsafe = [c for c in all_coins if c not in safe]
    print(f"总币种数: {len(all_coins)}")
    print(f"马丁安全币种({len(safe)}): {safe}")
    print(f"马丁剔除币种({len(unsafe)}): {unsafe}")
    print("\n--- 逐币风控详情 ---")
    for c in all_coins:
        tier = m.get_market_cap_tier(c)
        ld = m.get_listing_date(c)
        safe_flag = m.is_martin_safe(c)
        print(f"  {c:6s} tier={tier.value:5s} listing={ld} martin_safe={safe_flag}")
