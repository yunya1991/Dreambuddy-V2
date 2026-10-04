"""AssetClassMapper — 币种精细分类映射（P1a 跨币种迁移基础设施）

将币种映射到 asset_sub_class，用于 ReflectionScanner 类先验继承。
不修改 11-易经推理系统 的 classify_asset_class()（被 BDSM 等消费），此处独立维护更细的 crypto 子类。

分类体系：
  crypto_major   — BTC, ETH（市值前二，市场风向标）
  crypto_layer1  — 公链代币（SOL, AVAX, NEAR, ADA, DOT, ATOM, APT, OP, INJ, TON, SUI, SEI, TIA, EGLD, XTZ, ALGO, HBAR, ICP, XLM, EOS, MATIC, TRX, FTM, ETC, ARB, OKB）
  crypto_defi    — DeFi 协议代币（UNI, AAVE, LINK, COMP, MKR, SNX, DYDX, GMX, RDNT, QNT, GRT, CRO）
  crypto_meme    — Meme 币（DOGE, PEPE, WIF, SHIB）
  crypto_alt     — 其他加密资产（PUMP, HYPE, ZEC, BNB, LTC, IMX, JUP, RUNE, VET, FIL, CRCL）
  us_stock       — 美股（MU, SKHYNIX, GOOGL, NVDA, AMZN, SNDK, SPX, COIN, BMNR, MSTR）
  precious_metal — 贵金属（XAU, XAG）

FAIL-OPEN: 未知币种返回 None，调用方回退到默认值。
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# 常量
# ============================================================================
CRYPTO_MAJOR = "crypto_major"
CRYPTO_LAYER1 = "crypto_layer1"
CRYPTO_DEFI = "crypto_defi"
CRYPTO_MEME = "crypto_meme"
CRYPTO_ALT = "crypto_alt"
US_STOCK = "us_stock"
PRECIOUS_METAL = "precious_metal"

# ============================================================================
# 硬编码映射表（frozenset，O(1) 查找）
# ============================================================================
_CRYPTO_MAJOR_COINS = frozenset({
    "BTC", "ETH",
})

_CRYPTO_LAYER1_COINS = frozenset({
    "SOL", "AVAX", "NEAR", "ADA", "DOT", "ATOM", "APT", "OP", "INJ",
    "TON", "SUI", "SEI", "TIA", "EGLD", "XTZ", "ALGO", "HBAR", "ICP",
    "XLM", "EOS", "MATIC", "TRX", "FTM", "ETC", "ARB", "OKB",
})

_CRYPTO_DEFI_COINS = frozenset({
    "UNI", "AAVE", "LINK", "COMP", "MKR", "SNX", "DYDX", "GMX",
    "RDNT", "QNT", "GRT", "CRO",
})

_CRYPTO_MEME_COINS = frozenset({
    "DOGE", "PEPE", "WIF", "SHIB",
})

_CRYPTO_ALT_COINS = frozenset({
    "PUMP", "HYPE", "ZEC", "BNB", "LTC", "IMX", "JUP", "RUNE",
    "VET", "FIL", "CRCL", "XRP",
})

_US_STOCK_COINS = frozenset({
    "MU", "SKHYNIX", "GOOGL", "NVDA", "AMZN", "SNDK", "SPCX",
    "COIN", "BMNR", "MSTR",
})

_PRECIOUS_METAL_COINS = frozenset({
    "XAU", "XAG",
})

# 全量映射（用于反向查找）
_ALL_MAPPINGS = [
    (_CRYPTO_MAJOR_COINS, CRYPTO_MAJOR),
    (_CRYPTO_LAYER1_COINS, CRYPTO_LAYER1),
    (_CRYPTO_DEFI_COINS, CRYPTO_DEFI),
    (_CRYPTO_MEME_COINS, CRYPTO_MEME),
    (_CRYPTO_ALT_COINS, CRYPTO_ALT),
    (_US_STOCK_COINS, US_STOCK),
    (_PRECIOUS_METAL_COINS, PRECIOUS_METAL),
]


def get_asset_class(coin: str) -> Optional[str]:
    """返回币种的精细 asset_sub_class。未知币种返回 None（FAIL-OPEN）。

    Args:
        coin: 币种符号（大写，如 "BTC"）
    Returns:
        asset_sub_class 字符串，或 None
    """
    coin_upper = coin.upper().strip()
    for coin_set, class_name in _ALL_MAPPINGS:
        if coin_upper in coin_set:
            return class_name
    return None


def get_coarse_class(coin: str) -> Optional[str]:
    """返回币种的粗分类（crypto_usdt / us_stock / precious_metal）。

    委托 11-易经推理系统 的 classify_asset_class()，跨子系统导入用 try/except 包裹。
    导入失败时，从精细分类降级推导。
    """
    # 优先尝试精细分类降级
    fine = get_asset_class(coin)
    if fine is None:
        return None
    if fine in (CRYPTO_MAJOR, CRYPTO_LAYER1, CRYPTO_DEFI, CRYPTO_MEME, CRYPTO_ALT):
        return "crypto_usdt"
    if fine == US_STOCK:
        return "us_stock"
    if fine == PRECIOUS_METAL:
        return "precious_metal"
    return None


def get_all_classified_coins() -> dict[str, list[str]]:
    """返回所有分类映射的逆映射：{class_name: [coin1, coin2, ...]}"""
    result: dict[str, list[str]] = {}
    for coin_set, class_name in _ALL_MAPPINGS:
        result.setdefault(class_name, []).extend(sorted(coin_set))
    return result
