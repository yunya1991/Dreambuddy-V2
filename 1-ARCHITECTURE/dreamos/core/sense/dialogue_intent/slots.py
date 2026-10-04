"""
槽位归一化

将用户输入中的非标准表达归一化为标准槽位值。
属于 DreamOS 操作系统内核 S 层。
"""

from __future__ import annotations

import re
from typing import Dict, Optional, Tuple


# ============================================================
# 股票/标的别名归一化
# ============================================================

STOCK_ALIASES: Dict[str, str] = {
    # A股常见别名
    "茅台": "贵州茅台",
    "五粮液": "五粮液",
    "宁王": "宁德时代",
    "比亚迪": "比亚迪",
    "中芯": "中芯国际",
    # 加密货币直接符号（用户常直接输入英文缩写）
    "BTC": "BTC", "btc": "BTC",
    "比特币": "BTC", "大饼": "BTC",
    "ETH": "ETH", "eth": "ETH",
    "以太坊": "ETH", "姨太": "ETH",
    "SOL": "SOL", "sol": "SOL",
    "BNB": "BNB", "bnb": "BNB", "币安币": "BNB",
    "XRP": "XRP", "xrp": "XRP", "瑞波": "XRP",
    "DOGE": "DOGE", "doge": "DOGE", "狗狗币": "DOGE",
    "ADA": "ADA", "ada": "ADA",
    "AVAX": "AVAX", "avax": "AVAX",
    "DOT": "DOT", "dot": "DOT", "波卡": "DOT",
    "LINK": "LINK", "link": "LINK",
    "LTC": "LTC", "ltc": "LTC", "莱特币": "LTC",
    "TON": "TON", "ton": "TON",
    "TRX": "TRX", "trx": "TRX", "波场": "TRX",
    "SUI": "SUI", "sui": "SUI",
    "ORDI": "ORDI", "ordi": "ORDI",
    "PEPE": "PEPE", "pepe": "PEPE",
    "ARB": "ARB", "arb": "ARB",
    "OP": "OP", "op": "OP",
    "NEAR": "NEAR", "near": "NEAR",
    "APT": "APT", "apt": "APT", "aptos": "APT",
    "FIL": "FIL", "fil": "FIL",
    "AAVE": "AAVE", "aave": "AAVE",
    "UNI": "UNI", "uni": "UNI",
    "ATOM": "ATOM", "atom": "ATOM",
    # 美股
    "NVDA": "NVDA", "nvda": "NVDA", "英伟达": "NVDA",
    "TSLA": "TSLA", "tsla": "TSLA", "特斯拉": "TSLA",
    "GOOGL": "GOOGL", "googl": "GOOGL", "谷歌": "GOOGL",
    # 黄金/白银
    "XAU": "XAU", "黄金": "XAU", "金价": "XAU",
    "XAG": "XAG", "白银": "XAG",
}


def normalize_stock(raw: str) -> str:
    """归一化股票/标的名称"""
    if not raw:
        return raw
    return STOCK_ALIASES.get(raw.strip(), raw.strip())


# ============================================================
# 时间周期别名归一化
# ============================================================

TIMEFRAME_ALIASES: Dict[str, str] = {
    "1分钟": "1m", "1分": "1m", "1m": "1m",
    "5分钟": "5m", "5分": "5m", "5m": "5m",
    "15分钟": "15m", "15分": "15m", "15m": "15m",
    "30分钟": "30m", "30分": "30m", "30m": "30m",
    "1小时": "1h", "1h": "1h", "60分钟": "1h",
    "4小时": "4h", "4h": "4h",
    "日线": "1d", "日": "1d", "1d": "1d",
    "周线": "1w", "周": "1w", "1w": "1w",
    "月线": "1M", "月": "1M", "1M": "1M",
}


def normalize_timeframe(raw: str) -> str:
    """归一化时间周期"""
    if not raw:
        return raw
    return TIMEFRAME_ALIASES.get(raw.strip(), raw.strip())


# ============================================================
# 数量单位归一化
# ============================================================

# "梭哈" → all_in, "半仓" → 0.5, "满仓" → 1.0
QUANTITY_ALIASES: Dict[str, str] = {
    "梭哈": "all_in",
    "全仓": "all_in",
    "满仓": "all_in",
    "半仓": "0.5",
    "三分之一仓": "0.33",
    "三分之二仓": "0.67",
    "四分之一仓": "0.25",
    "轻仓": "0.1",
    "重仓": "0.8",
}


def normalize_quantity(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """归一化数量表达

    Returns:
        (数量值, 单位) — 数量值可能为 None（all_in 等）
    """
    if not raw:
        return None, None

    raw = raw.strip()

    # 别名匹配
    if raw in QUANTITY_ALIASES:
        val = QUANTITY_ALIASES[raw]
        if val == "all_in":
            return None, "all_in"
        return float(val), "ratio"

    # 数字 + 单位（100股, 100手, 0.5个BTC）
    match = re.match(r"^([\d.]+)\s*(股|手|个|枚|张)?$", raw)
    if match:
        num = float(match.group(1))
        unit = match.group(2) or "unit"
        return num, unit

    return None, None


# ============================================================
# 板块别名归一化
# ============================================================

SECTOR_SUFFIXES = ["板块", "概念", "行业", "指数"]

SECTOR_ALIASES: Dict[str, str] = {
    "新能源": "新能源",
    "半导体": "半导体",
    "芯片": "半导体",
    "医药": "医药生物",
    "医疗": "医药生物",
    "白酒": "白酒",
    "消费": "消费",
    "军工": "军工",
    "金融": "金融",
    "银行": "银行",
    "地产": "房地产",
    "房地产": "房地产",
}


def normalize_sector(raw: str) -> str:
    """归一化板块名称"""
    if not raw:
        return raw
    raw = raw.strip()
    # 去除后缀
    for suffix in SECTOR_SUFFIXES:
        raw = raw.replace(suffix, "")
    return SECTOR_ALIASES.get(raw, raw)


# ============================================================
# 指标别名归一化
# ============================================================

INDICATOR_ALIASES: Dict[str, str] = {
    "macd": "MACD",
    "rsi": "RSI",
    "布林": "BOLL",
    "boll": "BOLL",
    "均线": "MA",
    "ma": "MA",
    "kdj": "KDJ",
    "成交量": "VOLUME",
    "量": "VOLUME",
}


def normalize_indicator(raw: str) -> str:
    """归一化技术指标名称"""
    if not raw:
        return raw
    return INDICATOR_ALIASES.get(raw.strip().lower(), raw.strip())


# ============================================================
# 槽位提取辅助
# ============================================================

def extract_slots_from_text(text: str) -> Dict[str, str]:
    """从文本中提取常见槽位（简易规则版，完整提取由 LLM 完成）"""
    slots: Dict[str, str] = {}

    # 标的
    for alias, standard in STOCK_ALIASES.items():
        if alias in text:
            slots["stock"] = standard
            break

    # 时间周期
    for alias, standard in TIMEFRAME_ALIASES.items():
        if alias in text and len(alias) > 1:
            slots["timeframe"] = standard
            break

    # 板块
    for alias, standard in SECTOR_ALIASES.items():
        if alias in text:
            slots["sector"] = standard
            break

    # 指标
    for alias, standard in INDICATOR_ALIASES.items():
        if alias.lower() in text.lower():
            slots["indicator"] = standard
            break

    # 数量（100股、10张、0.5个、全仓/半仓/梭哈）
    for pattern, unit in [
        (r"(\d+(?:\.\d+)?)\s*股", "share"),
        (r"(\d+(?:\.\d+)?)\s*张", "contract"),
        (r"(\d+(?:\.\d+)?)\s*个", "unit"),
        (r"(\d+(?:\.\d+)?)\s*%", "percent"),
    ]:
        m = re.search(pattern, text)
        if m:
            slots["quantity"] = m.group(1)
            slots["quantity_unit"] = unit
            break
    if "quantity" not in slots:
        for kw, val in [("全仓", "all_in"), ("满仓", "all_in"), ("梭哈", "all_in"), ("半仓", "0.5")]:
            if kw in text:
                slots["quantity"] = val
                slots["quantity_unit"] = "position_ratio"
                break

    # 交易方向
    if any(w in text for w in ["买入", "买进", "建仓", "开多", "做多", "买多"]):
        slots["action"] = "buy"
    elif any(w in text for w in ["卖出", "卖掉", "止盈", "平仓", "清仓", "开空", "做空", "卖空"]):
        slots["action"] = "sell"

    return slots
