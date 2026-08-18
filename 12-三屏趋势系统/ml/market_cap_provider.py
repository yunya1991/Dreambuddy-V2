"""市值数据提供者 — 从 CoinGecko 获取实时市值并计算动态阈值

设计理念：
    随着加密货币市值增长，大市值币种（如 BTC）的波动性降低、波浪结构置信度
    自然下降。本模块基于实时市值动态调整波浪确认阈值：
    - 市值 >= 基准市值（BTC当前市值）× large_cap_ratio（默认80%）→ 阈值 0.4
    - 市值 < 基准市值 × large_cap_ratio → 阈值 0.6

优点：
    - 不硬编码币种名称，完全基于市值自动判断
    - ETH 未来如果市值成长到 BTC 的 80%，自动采用 0.4 阈值
    - 基准市值每周自动刷新，适应市场变化

调用方式：
    from ml.market_cap_provider import get_confirm_threshold_by_symbol

    threshold = get_confirm_threshold_by_symbol("BTC")  # 返回 0.4
    threshold = get_confirm_threshold_by_symbol("ETH")  # 返回 0.6（当前市值 < BTC的80%）

数据来源：CoinGecko 公开 API（免费，无需 API Key）
速率限制：~30次/分钟，本模块每天刷新一次基准，足够使用
"""

import os
import json
import time
import threading
import requests
from pathlib import Path

# 缓存文件路径
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE_FILE = CACHE_DIR / "market_cap_cache.json"

# CoinGecko 币种ID映射
COINGECKO_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "LINK": "chainlink",
    "UNI": "uniswap",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "MATIC": "matic-network",
}

# 默认参数
LARGE_CAP_RATIO = 0.80         # 市值达到BTC的80%即视为"超大盘"，采用0.4阈值
LARGE_CAP_THRESHOLD = 0.4      # 超大盘币种的波浪确认阈值
NORMAL_THRESHOLD = 0.6         # 普通币种的波浪确认阈值
CACHE_TTL_SECONDS = 86400      # 缓存有效期：24小时
BENCHMARK_SYMBOL = "BTC"       # 基准币种
REQUEST_TIMEOUT = 15

_cache_lock = threading.Lock()


def _fetch_market_caps(symbols: list) -> dict:
    """从 CoinGecko 获取指定币种的实时市值

    Args:
        symbols: 币种符号列表，如 ["BTC", "ETH", "SOL"]

    Returns:
        dict: {"BTC": 1294100000000, "ETH": 225600000000, ...}
    """
    ids = [COINGECKO_IDS.get(s.upper()) for s in symbols if s.upper() in COINGECKO_IDS]
    ids = [i for i in ids if i]
    if not ids:
        return {}

    session = requests.Session()
    session.trust_env = False  # 禁用系统代理

    try:
        url = "https://api.coingecko.com/api/v3/coins/markets"
        params = {
            "vs_currency": "usd",
            "ids": ",".join(ids),
            "order": "market_cap_desc",
        }
        r = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"[market_cap] CoinGecko API失败: {e}")
        return {}

    result = {}
    symbol_by_id = {v: k for k, v in COINGECKO_IDS.items()}
    for coin in data:
        symbol = symbol_by_id.get(coin.get("id", ""))
        if symbol and coin.get("market_cap"):
            result[symbol] = float(coin["market_cap"])
    return result


def _load_cache() -> dict:
    """加载本地缓存"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("timestamp", 0) > CACHE_TTL_SECONDS:
            return {}
        return data
    except Exception:
        return {}


def _save_cache(data: dict):
    """保存到本地缓存"""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[market_cap] 缓存保存失败: {e}")


def get_market_caps(symbols: list = None, force_refresh: bool = False) -> dict:
    """获取多个币种的实时市值

    Args:
        symbols: 币种列表，None则返回缓存
        force_refresh: 强制刷新缓存

    Returns:
        dict: {symbol: market_cap}
    """
    with _cache_lock:
        cache = _load_cache()
        cache_data = cache.get("data", {})

        need_fetch = force_refresh or not cache_data
        if not need_fetch and symbols:
            need_fetch = any(s not in cache_data for s in symbols)

        if need_fetch:
            fetch_symbols = symbols or list(COINGECKO_IDS.keys())
            fresh = _fetch_market_caps(fetch_symbols)
            if fresh:
                cache_data.update(fresh)
                _save_cache({"data": cache_data, "timestamp": time.time()})

        if symbols:
            return {s: cache_data.get(s) for s in symbols if s in cache_data}
        return cache_data


def get_market_cap(symbol: str) -> float:
    """获取单个币种的市值"""
    caps = get_market_caps([symbol])
    return caps.get(symbol, 0.0)


def get_benchmark_market_cap() -> float:
    """获取基准币种（BTC）的市值"""
    return get_market_cap(BENCHMARK_SYMBOL)


def get_confirm_threshold_by_symbol(
    symbol: str,
    large_cap_ratio: float = LARGE_CAP_RATIO,
    large_cap_threshold: float = LARGE_CAP_THRESHOLD,
    normal_threshold: float = NORMAL_THRESHOLD,
) -> float:
    """根据币种市值动态确定波浪确认阈值

    逻辑：
        - 如果币种是 BTC（基准本身），直接使用 large_cap_threshold（0.4）
        - 其他币种市值 >= BTC市值 × large_cap_ratio → large_cap_threshold（0.4）
        - 否则 → normal_threshold（0.6）

    Args:
        symbol: 币种符号
        large_cap_ratio: 超大盘判定比例（默认80%）
        large_cap_threshold: 超大盘阈值（默认0.4）
        normal_threshold: 普通阈值（默认0.6）

    Returns:
        float: 确认阈值
    """
    if symbol.upper() == BENCHMARK_SYMBOL:
        return large_cap_threshold

    benchmark_cap = get_benchmark_market_cap()
    if benchmark_cap <= 0:
        return normal_threshold

    symbol_cap = get_market_cap(symbol)
    if symbol_cap <= 0:
        return normal_threshold

    ratio = symbol_cap / benchmark_cap
    if ratio >= large_cap_ratio:
        return large_cap_threshold
    return normal_threshold


def refresh_cache():
    """强制刷新缓存"""
    get_market_caps(list(COINGECKO_IDS.keys()), force_refresh=True)


if __name__ == "__main__":
    caps = get_market_caps(["BTC", "ETH", "SOL", "BNB", "LINK", "UNI"])
    bench = caps.get("BTC", 0)
    print(f"{'币种':<6} {'市值(亿USDT)':<15} {'相对BTC%':<10} {'confirm_threshold':<15}")
    print("-" * 50)
    for sym, cap in sorted(caps.items(), key=lambda x: -x[1]):
        ratio = cap / bench * 100 if bench > 0 else 0
        threshold = get_confirm_threshold_by_symbol(sym)
        print(f"{sym:<6} {cap/1e8:<15,.0f} {ratio:<10.1f} {threshold:<15.2f}")
