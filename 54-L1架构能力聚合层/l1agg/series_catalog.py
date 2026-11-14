# -*- coding: utf-8 -*-
"""S1 指标字典：前端 11 模块主序列 + L1 自然语言指标别名。

单一事实源（SSoT）：`fundamental_snapshot.py`（前端 timeseries）与
`data_query_executor.exec_metric_series`（L1 直答）都从这里取 (sub_category, metric_name)，
禁止在各自脚本内另立映射（SPEC §六「同一指标在 L1 与前端必须来自同一 Aggregator 输出」）。

所有条目均为 mm_metrics 实际存在的序列（来源：S1.0-4 覆盖体检 + dsh_frontend_bridge 指标表）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# module → {series: [(sub_category, metric_name), ...], label, unit, days, agg}
# series 为回退链：第一个有历史数据的生效
MODULE_SERIES: Dict[str, Dict[str, Any]] = {
    "macro": {
        "series": [("DGS10", "value"), ("CPIAUCSL", "value")],
        "label": "美债10年收益率",
        "unit": "%",
        "days": 365,
    },
    "onchain": {
        "series": [("btc_basics", "active_addresses"), ("btc_onchain", "mempool_count")],
        "label": "BTC 活跃地址",
        "unit": "个",
        "days": 90,
    },
    "sentiment": {
        "series": [("crypto_fear_greed", "value")],
        "label": "加密恐惧贪婪指数",
        "unit": "分",
        "days": 90,
    },
    "valuation": {
        "series": [("btc_metrics", "mvrv"), ("btc_metrics", "nvt_ratio")],
        "label": "MVRV",
        "unit": "倍",
        "days": 365,
    },
    "flow": {
        "series": [
            ("etf_flow", "total_flow"),
            ("okx_derivatives", "funding_rate_pct"),
            ("funding_rate", "funding_rate_pct"),
        ],
        "label": "ETF 总净流入",
        "unit": "百万美元",
        "days": 90,
    },
    "breadth": {
        "series": [("overview_market", "btc_dominance_pct"), ("chains_summary", "total_tvl_bln")],
        "label": "BTC 市占率",
        "unit": "%",
        "days": 90,
    },
    "capital_flow": {
        "series": [("open_interest", "open_interest_value"), ("funding_rate", "funding_rate_pct")],
        "label": "合约持仓量价值",
        "unit": "USD",
        "days": 90,
    },
    "intermarket": {
        "series": [("BTC", "close_usd"), ("BTC/USDT", "last")],
        "label": "BTC 价格",
        "unit": "USD",
        "days": 90,
    },
    "news": {
        "series": [("social_volume", "news_count_24h"), ("social_volume", "social_volume")],
        "label": "24h 新闻数",
        "unit": "条",
        "days": 90,
    },
    "narrative": {
        "series": [("crypto_fear_greed", "value"), ("fear_greed_enhanced", "momentum")],
        "label": "恐惧贪婪指数",
        "unit": "分",
        "days": 90,
    },
    "calendar": {
        # 经济日历无独立数值序列，用 CME FedWatch 降息概率作为日历事件的预期代理
        "series": [("fedwatch", "cut_prob"), ("fedwatch", "effr")],
        "label": "降息概率",
        "unit": "%",
        "days": 365,
    },
}

# 自然语言别名 → (sub_category, metric_name, label, unit, 默认天数)
# 匹配规则：最长别名优先；单字别名不参与匹配
METRIC_ALIASES: List[Tuple[Tuple[str, str], Tuple[str, ...], str, str, int]] = [
    (
        ("crypto_fear_greed", "value"),
        ("恐惧贪婪", "恐惧贪婪指数", "fear greed", "fear_greed", "fng"),
        "恐惧贪婪指数",
        "分",
        30,
    ),
    (("BTC", "close_usd"), ("btc", "比特币"), "BTC 价格", "USD", 30),
    (("ETH", "close_usd"), ("eth", "以太坊", "以太"), "ETH 价格", "USD", 30),
    (("SOL", "close_usd"), ("sol", "索拉纳"), "SOL 价格", "USD", 30),
    (("XAU", "close_usd"), ("黄金", "xau", "xaut"), "黄金价格", "USD", 90),
    (("CPIAUCSL", "value"), ("cpi", "通胀", "消费者价格", "物价指数"), "CPI 指数", "指数", 365),
    (("PPIACO", "value"), ("ppi", "生产者价格"), "PPI 指数", "指数", 365),
    (("M2NS", "value"), ("m2", "货币供应"), "M2 货币供应", "十亿美元", 365),
    (("FEDFUNDS", "value"), ("联邦基金利率", "fed funds", "基准利率"), "联邦基金利率", "%", 365),
    (("DGS10", "value"), ("美债", "10年美债", "十年期美债", "dgs10"), "美债10年收益率", "%", 365),
    (("DX-Y.NYB", "value"), ("美元指数", "dxy"), "美元指数", "", 365),
    (("VIXCLS", "value"), ("vix", "恐慌指数"), "VIX", "", 365),
    (("NASDAQCOM", "value"), ("纳指", "纳斯达克"), "纳斯达克指数", "", 365),
    (("SP500", "value"), ("标普", "标普500"), "标普500", "", 365),
    (("DCOILWTICO", "value"), ("原油", "wti", "油价"), "WTI 原油", "USD", 365),
    (("btc_metrics", "mvrv"), ("mvrv",), "MVRV", "倍", 365),
    (("btc_metrics", "sopr"), ("sopr",), "SOPR", "", 365),
    (("btc_metrics", "nupl"), ("nupl",), "NUPL", "", 365),
    (
        ("btc_basics", "active_addresses"),
        ("活跃地址", "active addresses"),
        "BTC 活跃地址",
        "个",
        90,
    ),
    (
        ("btc_basics", "hashrate"),
        ("哈希率", "算力", "hashrate", "hash rate"),
        "BTC 哈希率",
        "H/s",
        90,
    ),
    (("funding_rate", "funding_rate_pct"), ("资金费率", "funding rate"), "资金费率", "%", 90),
    (("long_short_ratio", "long_short_ratio"), ("多空比", "long short"), "多空比", "", 90),
    (
        ("open_interest", "open_interest_value"),
        ("持仓量", "未平仓", "open interest"),
        "合约持仓量",
        "USD",
        90,
    ),
    (
        ("chains_summary", "total_tvl_bln"),
        ("defi tvl", "tvl", "锁仓量"),
        "DeFi TVL",
        "十亿美元",
        90,
    ),
    (
        ("overview_market", "btc_dominance_pct"),
        ("btc 市占率", "btc市占率", "btc主导", "btc dominance"),
        "BTC 市占率",
        "%",
        90,
    ),
    (
        ("etf_flow", "total_flow"),
        ("etf 流入", "etf 净流入", "etf流入", "etf净流入", "etf flow"),
        "ETF 总净流入",
        "百万美元",
        90,
    ),
    (("social_volume", "news_count_24h"), ("新闻数", "快讯数"), "24h 新闻数", "条", 90),
    (("fedwatch", "cut_prob"), ("降息概率", "cut probability"), "降息概率", "%", 365),
]

# 天数口语解析（按最长匹配优先）
_PERIOD_ALIASES = (
    ("三年", 1095),
    ("3年", 1095),
    ("两年", 730),
    ("2年", 730),
    ("一年", 365),
    ("1年", 365),
    ("半年", 180),
    ("三个月", 90),
    ("3个月", 90),
    ("一个月", 30),
    ("1个月", 30),
    ("一周", 7),
)


def module_series(module_key: str) -> Dict[str, Any]:
    """取模块主序列定义；未知模块返回空回退链（由调用方降级）。"""
    return MODULE_SERIES.get(
        module_key,
        {"series": [], "label": module_key, "unit": "", "days": 90},
    )


def resolve_metric(text: str) -> Optional[Dict[str, Any]]:
    """自然语言 → 指标序列定义；未命中返回 None。"""
    if not text:
        return None
    low = text.lower()
    best: Optional[Tuple[Tuple[str, str], Tuple[str, ...], str, str, int]] = None
    best_len = 0
    for item in METRIC_ALIASES:
        for alias in item[1]:
            if len(alias) < 2:
                continue
            if alias in low and len(alias) > best_len:
                best, best_len = item, len(alias)
    if best is None:
        return None
    sub, metric = best[0]
    return {
        "sub_category": sub,
        "metric_name": metric,
        "label": best[2],
        "unit": best[3],
        "days": best[4],
    }


def resolve_days(text: str, default: int) -> int:
    """从问句解析时间窗口（天）；命中「近 90 天 / 365 日」等显式写法优先。"""
    import re

    if not text:
        return default
    for word, days in _PERIOD_ALIASES:
        if word in text:
            return days
    m = re.search(r"(\d{1,4})\s*(天|日|周|个月|月|年)", text)
    if not m:
        return default
    n = int(m.group(1))
    unit = m.group(2)
    if unit in ("天", "日"):
        days = n
    elif unit == "周":
        days = n * 7
    elif unit in ("个月", "月"):
        days = n * 30
    else:
        days = n * 365
    return max(1, min(days, 1825))
