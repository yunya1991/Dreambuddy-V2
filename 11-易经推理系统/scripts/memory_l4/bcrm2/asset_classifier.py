"""统一资产分类接口 — 资产类别 × 市值等级

整合自进化系统的 asset_class_mapper（细分类）和 BCRM2.0 的 market_cap（市值等级），
为 SL/TP 三维分类提供 (asset_class, market_cap_tier) 二元组。

分类体系：
  asset_class:
    - us_stock        美股代币
    - crypto_major    BTC/ETH
    - crypto_large    大市值加密（SOL/BNB/XRP等）
    - crypto_mid      中市值加密
    - crypto_small    小市值加密
    - crypto_meme     Meme币
    - precious_metal  贵金属

  market_cap_tier:
    - large   大市值
    - mid     中市值
    - small   小市值
    - tradfi  传统金融（美股/贵金属）

FAIL-OPEN: 未知币种返回 ("crypto_major", "large")，不抛异常。
"""
from __future__ import annotations

import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# ============================================================================
# 默认分类常量
# ============================================================================
DEFAULT_ASSET_CLASS = "crypto_major"
DEFAULT_MARKET_CAP = "large"

# 资产类别常量
ASSET_US_STOCK = "us_stock"
ASSET_CRYPTO_MAJOR = "crypto_major"
ASSET_CRYPTO_LARGE = "crypto_large"
ASSET_CRYPTO_MID = "crypto_mid"
ASSET_CRYPTO_SMALL = "crypto_small"
ASSET_CRYPTO_MEME = "crypto_meme"
ASSET_PRECIOUS_METAL = "precious_metal"

# 市值等级常量
MCAP_LARGE = "large"
MCAP_MID = "mid"
MCAP_SMALL = "small"
MCAP_TRADFI = "tradfi"


# ============================================================================
# 币种映射表（基于现有 asset_class_mapper + market_cap 整合）
# ============================================================================

# 美股代币（OKX USDT-SWAP 上的美股代币化合约）
_US_STOCK_COINS = frozenset({
    "AAPL", "AMZN", "GOOGL", "NVDA", "MSFT", "TSLA", "META", "NFLX",
    "BABA", "MU", "SKHYNIX", "SNDK", "SPCX", "PLTR", "BMNR",
})

# 加密属性美股代币（本质跟随加密市场，不跟随美股大盘）
_CRYPTO_US_STOCK_COINS = frozenset({
    "COIN", "MSTR", "CRCL",
})

# BTC/ETH（市场风向标）
_CRYPTO_MAJOR_COINS = frozenset({
    "BTC", "ETH",
})

# 大市值加密（市值排名前列）
_CRYPTO_LARGE_COINS = frozenset({
    "BNB", "SOL", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK",
    "LTC", "NEAR", "APT",
})

# 中市值加密
_CRYPTO_MID_COINS = frozenset({
    "MATIC", "UNI", "ATOM", "ETC", "FIL", "ARB", "OP", "PEPE",
    "COMP", "TIA", "SUI", "SEI", "INJ", "STRK", "JUP", "WIF",
    "JTO", "BLUR", "AAVE",
})

# 小市值加密（其他）
_CRYPTO_SMALL_COINS = frozenset({
    "OKB", "HYPE", "PUMP",
})

# Meme 币
_CRYPTO_MEME_COINS = frozenset({
    "DOGE", "PEPE", "WIF", "SHIB",
})

# 贵金属
_PRECIOUS_METAL_COINS = frozenset({
    "XAU", "XAG",
})

# 全量映射（优先级从高到低）
_ALL_MAPPINGS = [
    (_PRECIOUS_METAL_COINS, ASSET_PRECIOUS_METAL, MCAP_TRADFI),
    (_US_STOCK_COINS, ASSET_US_STOCK, MCAP_TRADFI),
    (_CRYPTO_MAJOR_COINS, ASSET_CRYPTO_MAJOR, MCAP_LARGE),
    (_CRYPTO_LARGE_COINS, ASSET_CRYPTO_LARGE, MCAP_LARGE),
    (_CRYPTO_MID_COINS, ASSET_CRYPTO_MID, MCAP_MID),
    (_CRYPTO_SMALL_COINS, ASSET_CRYPTO_SMALL, MCAP_SMALL),
]

# 快速查找表
_COIN_LOOKUP: dict[str, Tuple[str, str]] = {}
for coin_set, asset_cls, mcap in _ALL_MAPPINGS:
    for coin in coin_set:
        # DOGE/PEPE/WIF 等既是 meme 又是 mid/small，优先归为 meme
        if coin in _CRYPTO_MEME_COINS:
            _COIN_LOOKUP[coin] = (ASSET_CRYPTO_MEME, MCAP_SMALL)
        elif coin not in _COIN_LOOKUP:
            _COIN_LOOKUP[coin] = (asset_cls, mcap)


def classify_asset(coin: str) -> Tuple[str, str]:
    """统一资产分类接口。

    Args:
        coin: 币种符号（大写，如 "BTC"、"NVDA"）

    Returns:
        (asset_class, market_cap_tier) 二元组
        - asset_class: us_stock / crypto_major / crypto_large / crypto_mid /
                       crypto_small / crypto_meme / precious_metal
        - market_cap_tier: large / mid / small / tradfi

    FAIL-OPEN: 未知币种返回 ("crypto_major", "large")。
    """
    if not coin:
        return (DEFAULT_ASSET_CLASS, DEFAULT_MARKET_CAP)

    cu = coin.upper().strip()
    result = _COIN_LOOKUP.get(cu)
    if result is not None:
        return result

    # 兜底：尝试从 asset_class_mapper 和 market_cap 动态查询
    try:
        from dreambuddy_evolution.engines.asset_class_mapper import get_asset_class
        fine = get_asset_class(cu)
        if fine == "us_stock":
            return (ASSET_US_STOCK, MCAP_TRADFI)
        if fine == "precious_metal":
            return (ASSET_PRECIOUS_METAL, MCAP_TRADFI)
        if fine == "crypto_major":
            return (ASSET_CRYPTO_MAJOR, MCAP_LARGE)
    except Exception:
        pass

    try:
        from bcrm2.market_cap import KNOWN_MCAP, MARKET_CAP_LARGE, MARKET_CAP_MID, MARKET_CAP_SMALL
        mcap = KNOWN_MCAP.get(cu)
        if mcap == MARKET_CAP_LARGE:
            return (ASSET_CRYPTO_LARGE, MCAP_LARGE)
        if mcap == MARKET_CAP_MID:
            return (ASSET_CRYPTO_MID, MCAP_MID)
        if mcap == MARKET_CAP_SMALL:
            return (ASSET_CRYPTO_SMALL, MCAP_SMALL)
    except Exception:
        pass

    # 最终兜底
    return (DEFAULT_ASSET_CLASS, DEFAULT_MARKET_CAP)


def get_all_classified_coins() -> dict[str, list[str]]:
    """返回所有分类映射的逆映射：{asset_class: [coin1, coin2, ...]}"""
    result: dict[str, list[str]] = {}
    for coin, (asset_cls, _) in _COIN_LOOKUP.items():
        result.setdefault(asset_cls, []).append(coin)
    return result
