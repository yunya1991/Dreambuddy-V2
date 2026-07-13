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
        """注册 OKX 常见支持的资产（含加密货币 + 贵金属代币）"""

        # ── 主流加密货币 ──
        majors = [
            ("BTC", "Bitcoin"),
            ("ETH", "Ethereum"),
            ("SOL", "Solana"),
            ("BNB", "BNB"),
            ("XRP", "Ripple"),
            ("ADA", "Cardano"),
            ("DOGE", "Dogecoin"),
            ("LTC", "Litecoin"),
            ("LINK", "Chainlink"),
            ("AVAX", "Avalanche"),
            ("DOT", "Polkadot"),
            ("MATIC", "Polygon"),
            ("TRX", "TRON"),
            ("ATOM", "Cosmos"),
            ("UNI", "Uniswap"),
            ("NEAR", "NEAR Protocol"),
            ("APT", "Aptos"),
            ("FIL", "Filecoin"),
            ("ARB", "Arbitrum"),
            ("OP", "Optimism"),
            ("INJ", "Injective"),
            ("SUI", "Sui"),
            ("SEI", "Sei"),
            ("TIA", "Celestia"),
            ("RUNE", "THORChain"),
        ]
        for sym, name in majors:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.CRYPTO,
                exchanges={"okx": True},
            ))

        # ── 交易所平台币 ──
        self.register(AssetInfo(
            symbol="OKB", name="OKB",
            category=AssetCategory.CRYPTO,
            exchanges={"okx": True},
        ))

        # ── 热门山寨币 ──
        hot_alt = [
            ("AAVE", "Aave"),
            ("ALGO", "Algorand"),
            ("APE", "ApeCoin"),
            ("AXS", "Axie Infinity"),
            ("CHZ", "Chiliz"),
            ("COMP", "Compound"),
            ("CRV", "Curve DAO"),
            ("DYDX", "dYdX"),
            ("GALA", "Gala"),
            ("GRT", "The Graph"),
            ("IMX", "Immutable X"),
            ("LDO", "Lido DAO"),
            ("MKR", "Maker"),
            ("PEPE", "Pepe"),
            ("RNDR", "Render"),
            ("SAND", "The Sandbox"),
            ("SHIB", "Shiba Inu"),
            ("STX", "Stacks"),
            ("SUSHI", "SushiSwap"),
            ("WLD", "Worldcoin"),
            ("ZEC", "Zcash"),
        ]
        for sym, name in hot_alt:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.CRYPTO,
                exchanges={"okx": True},
            ))

        # ── HYPE（用户原有币种，OKX 部分时期支持，标记支持）──
        self.register(AssetInfo(
            symbol="HYPE", name="Hyperliquid",
            category=AssetCategory.CRYPTO,
            exchanges={"okx": True},
        ))

        # ── 贵金属代币（OKX SWAP 支持）──
        precious_metals = [
            ("XAUT", "Tether Gold", 0.01, 0.01, 1.0),   # XAUT-USDT-SWAP, 1张=1 XAUT
            ("PAXG", "Paxos Gold", 0.001, 0.01, 1.0),   # PAXG-USDT-SWAP
        ]
        for sym, name, lot, tick, ctval in precious_metals:
            self.register(AssetInfo(
                symbol=sym, name=name,
                category=AssetCategory.PRECIOUS_METAL,
                exchanges={"okx": True},
                lot_sz_override=lot,
                tick_sz_override=tick,
                ct_val_override=ctval,
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
