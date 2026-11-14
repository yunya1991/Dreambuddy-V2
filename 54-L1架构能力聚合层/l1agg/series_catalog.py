# -*- coding: utf-8 -*-
"""S1 指标字典：前端 11 模块主序列 + L1 自然语言指标别名。

单一事实源（SSoT）：`fundamental_snapshot.py`（前端 timeseries）与
`data_query_executor.exec_metric_series`（L1 直答）都从这里取 (sub_category, metric_name)，
禁止在各自脚本内另立映射（SPEC §六「同一指标在 L1 与前端必须来自同一 Aggregator 输出」）。

所有条目均为 mm_metrics 实际存在的序列（来源：S1.0-4 覆盖体检 + dsh_frontend_bridge 指标表）。
"""

from __future__ import annotations

import json
import os
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

# ============================================================
# 单维关键词注册表（S1 扩展）：巨鲸流向 / 经济日历事件
# 命中即走确定性检索直答（不依赖语义模型），新增关键词只需在此加一行。
# ============================================================

# 巨鲸指标：metric_name → (关键词, 展示名, 单位, 展示缩放, 默认天数, 符号修正)
# 均为 mm_metrics 实存序列（sub_category=exchanges_whales）
# 符号修正：whale_netflow_to_ex_usd 落库口径为「转出-转入」（净转出为正），
# 展示为「净流入交易所」需乘 -1；其余为直接值。
WHALE_METRICS: List[Tuple[str, Tuple[str, ...], str, str, float, int, float]] = [
    (
        "whale_netflow_to_ex_usd",
        ("净流入", "净流", "净流出", "netflow", "动向", "动态"),
        "巨鲸净流入交易所",
        "亿美元",
        1e8,
        7,
        -1.0,
    ),
    (
        "whale_24h_to_ex_usd",
        ("流入", "转入", "to exchange"),
        "巨鲸转入交易所（24h）",
        "亿美元",
        1e8,
        7,
        1.0,
    ),
    (
        "whale_24h_from_ex_usd",
        ("流出", "转出", "from exchange"),
        "巨鲸转出交易所（24h）",
        "亿美元",
        1e8,
        7,
        1.0,
    ),
    (
        "whales_transfer_count",
        ("笔数", "次数", "count"),
        "巨鲸大额转账笔数",
        "笔",
        1.0,
        7,
        1.0,
    ),
]

# 经济日历事件类型：kind → (关键词, 展示名)
# kind 与 mm_events.event_type 对齐（fed_calendar=fomc / macro_calendar=nfp,cpi,macro_other）
EVENT_KINDS: List[Tuple[str, Tuple[str, ...], str]] = [
    (
        "fomc",
        ("议息", "fomc", "美联储会议", "利率决议", "加息会议", "降息会议"),
        "议息会议（FOMC）",
    ),
    ("nfp", ("非农", "nfp", "就业形势", "就业报告"), "非农就业报告"),
    ("cpi", ("cpi", "消费者价格", "通胀数据"), "CPI 数据"),
    ("ppi", ("ppi", "生产者价格"), "PPI 数据"),
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
    """自然语言 → 指标序列定义（三级：别名 → curated → 全量目录）；未命中返回 None。"""
    return resolve_series(text)


def _norm(text: str) -> str:
    """关键词匹配归一：小写 + 去空白（「ETF 净流入」与「ETF总净流入」等价命中）。"""
    return (text or "").lower().replace(" ", "").replace("　", "")


def resolve_whale_metric(text: str) -> Dict[str, Any]:
    """巨鲸问句 → 单维序列定义；最长关键词优先，默认净流入交易所。"""
    best = WHALE_METRICS[0]
    best_len = 0
    low = _norm(text)
    for item in WHALE_METRICS:
        for alias in item[1]:
            name = _norm(alias)
            if name in low and len(name) > best_len:
                best, best_len = item, len(name)
    return {
        "sub_category": "exchanges_whales",
        "metric_name": best[0],
        "label": best[2],
        "unit": best[3],
        "scale": best[4],
        "days": best[5],
        "sign": best[6],
    }


def resolve_event_kind(text: str) -> Optional[Dict[str, Any]]:
    """经济日历问句 → 事件类型 {kind,label}；未识别返回 None（由调用方查全部）。"""
    low = _norm(text)
    best = None
    best_len = 0
    for kind, aliases, label in EVENT_KINDS:
        for alias in aliases:
            name = _norm(alias)
            if name in low and len(name) > best_len:
                best, best_len = {"kind": kind, "label": label}, len(name)
    return best


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


# ============================================================
# 全量数据关键词注册表（S1 第一层能力底座）
#
# 三段式：数据关键词注册 → 意图识别（查询类）→ 索引输出（统一模板）
#   Tier-1 METRIC_ALIASES      ：历史别名（兼容，勿删）
#   Tier-2 CURATED_SERIES      ：按模块穷举的人工词表（前端 11 模块 + 18/19 新增能力）
#   Tier-3 data_catalog.json   ：mm_metrics 全量 (sub_category, metric_name) 自动目录
# 新增数据能力只需在 CURATED_SERIES 加一行；重跑 catalog_build 覆盖长尾。
# ============================================================

_UNIT_INT = ("条", "笔", "块", "个", "次", "家", "张", "BTC", "ETH", "枚")

# 纯标的/币种词不算「一个指标维度」：避免「BTC 资金费率」被判成多维并列
_SYMBOL_WORDS = frozenset(
    {
        "btc",
        "eth",
        "sol",
        "比特币",
        "以太坊",
        "以太",
        "大饼",
        "狗狗币",
        "黄金",
        "原油",
        "xau",
        "xaut",
        "纳指",
        "标普",
        "纳斯达克",
    }
)


def _c(
    sub: str,
    metric: str,
    label: str,
    unit: str,
    keywords: Tuple[str, ...],
    days: int = 90,
    scale: float = 1.0,
    sign: float = 1.0,
) -> Dict[str, Any]:
    return {
        "sub_category": sub,
        "metric_name": metric,
        "label": label,
        "unit": unit,
        "keywords": keywords,
        "days": days,
        "scale": scale,
        "sign": sign,
        "source": "curated",
    }


CURATED_SERIES: List[Dict[str, Any]] = [
    # ---- macro（FRED / 美元流动性）----
    _c("DGS10", "value", "美债10年收益率", "%", ("美债收益率", "十年期美债", "10年美债"), 365),
    _c("CPIAUCSL", "value", "CPI 指数", "指数", ("cpi", "通胀", "消费者价格"), 365),
    _c("PPIACO", "value", "PPI 指数", "指数", ("ppi", "生产者价格"), 365),
    _c("FEDFUNDS", "value", "联邦基金利率", "%", ("联邦基金利率", "基准利率"), 365),
    _c("M2NS", "value", "M2 货币供应", "十亿美元", ("m2", "货币供应"), 365),
    _c("WALCL", "value", "美联储资产负债表", "百万美元", ("资产负债表", "缩表", "扩表"), 365),
    _c("INDPRO", "value", "美国工业产出", "指数", ("工业产出", "工业生产"), 365),
    _c("VIXCLS", "value", "VIX 恐慌指数", "", ("vix", "恐慌指数"), 365),
    _c("DX-Y.NYB", "value", "美元指数", "", ("美元指数", "dxy"), 365),
    _c("SP500", "value", "标普500", "", ("标普", "标普500", "sp500"), 365),
    _c("NASDAQCOM", "value", "纳斯达克指数", "", ("纳指", "纳斯达克"), 365),
    _c("DCOILWTICO", "value", "WTI 原油", "USD", ("原油", "油价", "wti"), 365),
    # ---- onchain（链上基础面）----
    _c("btc_basics", "active_addresses", "BTC 活跃地址", "个", ("活跃地址", "链上活跃"), 90),
    _c("btc_basics", "hashrate", "BTC 哈希率", "H/s", ("哈希率", "算力"), 90),
    _c("btc_basics", "tx_count_24h", "BTC 24h 交易数", "笔", ("交易数", "交易笔数"), 90),
    _c("btc_basics", "total_btc", "BTC 流通量", "BTC", ("流通量", "总供应"), 365),
    _c(
        "btc_basics",
        "market_cap_usd",
        "BTC 市值",
        "万亿美元",
        ("btc 市值", "比特币市值"),
        365,
        1e12,
    ),
    _c("btc_basics", "difficulty", "BTC 挖矿难度", "", ("挖矿难度", "难度"), 90),
    _c("btc_onchain", "mempool_count", "BTC mempool 交易数", "笔", ("mempool", "内存池"), 90),
    _c("btc_onchain", "tip_height", "BTC 区块高度", "块", ("区块高度", "出块高度"), 90),
    _c("btc_onchain", "difficulty_change_pct", "BTC 难度变化", "%", ("难度变化",), 90),
    _c("btc_onchain", "mempool_fee_btc", "内存池手续费", "BTC", ("内存池手续费", "链上手续费"), 90),
    # ---- sentiment / news ----
    _c(
        "crypto_fear_greed",
        "value",
        "加密恐惧贪婪指数",
        "分",
        ("恐惧贪婪", "fear greed", "fng"),
        90,
    ),
    _c("social_volume", "social_volume", "社交热度", "", ("社交热度", "社交量"), 90),
    _c("social_volume", "news_count_24h", "24h 新闻数", "条", ("新闻数", "快讯数"), 90),
    # ---- valuation（BTC 估值）----
    _c("btc_metrics", "mvrv", "MVRV", "倍", ("mvrv",), 365),
    _c("btc_metrics", "mvrv_z_score", "MVRV Z-Score", "", ("mvrv z", "mvrv_z"), 365),
    _c("btc_metrics", "nvt_ratio", "NVT Ratio", "", ("nvt",), 365),
    _c("btc_metrics", "sopr", "SOPR", "", ("sopr",), 365),
    _c("btc_metrics", "nupl", "NUPL", "", ("nupl",), 365),
    _c("btc_metrics", "puell_multiple", "Puell Multiple", "", ("puell", "普尔倍数"), 365),
    _c("btc_metrics", "realized_price", "已实现价格", "USD", ("已实现价格",), 365),
    # ---- flow（ETF / 资金流）----
    _c(
        "etf_flow",
        "total_flow",
        "ETF 总净流入",
        "百万美元",
        ("etf 流入", "etf 净流入", "etf flow", "etf 总净流入", "总净流入"),
        90,
    ),
    _c("etf_flow", "IBIT", "IBIT 净流入", "百万美元", ("ibit",), 90),
    _c("etf_flow", "FBTC", "FBTC 净流入", "百万美元", ("fbtc",), 90),
    _c("etf_flow", "GBTC", "GBTC 净流入", "百万美元", ("gbtc",), 90),
    _c(
        "etf_institutional",
        "btc_etf_daily_flow_usd",
        "BTC ETF 日净流入",
        "万美元",
        ("btc etf 流入", "比特币 etf 流入"),
        90,
        1e4,
    ),
    _c(
        "etf_institutional",
        "btc_etf_total_aum_usd",
        "BTC ETF 总规模",
        "亿美元",
        ("etf 规模", "etf aum"),
        90,
        1e8,
    ),
    _c(
        "etf_institutional",
        "eth_etf_daily_flow_usd",
        "ETH ETF 日净流入",
        "万美元",
        ("eth etf 流入", "以太 etf"),
        90,
        1e4,
    ),
    # ---- breadth（广度 / 全局）----
    _c("overview_market", "btc_dominance_pct", "BTC 市占率", "%", ("btc 市占率", "btc 主导"), 90),
    _c(
        "overview_market",
        "global_market_cap_usd",
        "加密总市值",
        "万亿美元",
        ("总市值", "全市场市值"),
        90,
        1e12,
    ),
    _c("overview_market", "global_change24_pct", "加密总市值24h变化", "%", ("总市值变化",), 30),
    _c(
        "chains_summary", "total_tvl_bln", "DeFi TVL", "十亿美元", ("defi tvl", "tvl", "锁仓量"), 90
    ),
    # ---- capital_flow（衍生品 / 资金）----
    _c(
        "open_interest",
        "open_interest_value",
        "合约持仓量价值",
        "亿美元",
        ("持仓量", "未平仓", "open interest"),
        90,
        1e8,
    ),
    _c("funding_rate", "funding_rate_pct", "资金费率", "%", ("资金费率", "funding rate"), 90),
    _c(
        "funding_rate",
        "funding_rate_annualized_pct",
        "资金费率年化",
        "%",
        ("资金费率年化", "年化费率"),
        90,
    ),
    _c("long_short_ratio", "long_short_ratio", "多空比", "", ("多空比", "long short"), 90),
    _c("okx_derivatives", "open_interest_usd", "OKX 持仓量", "亿美元", ("okx 持仓",), 90, 1e8),
    # ---- overview_market：调研新增（交易所/爆仓/衍生品/RWA/持币）----
    _c(
        "exchanges_whales",
        "ex_summary_inflowUsd24h",
        "交易所24h净流入",
        "亿美元",
        ("交易所流入", "交易所净流入", "交易所余额流入", "24h净流入", "24小时净流入", "链上净流入"),
        30,
        1e8,
    ),
    _c(
        "exchanges_whales",
        "ex_summary_balanceChangeUsd24h",
        "交易所余额24h变化",
        "亿美元",
        ("交易所余额变化", "交易所余额"),
        30,
        1e8,
    ),
    _c("exchanges_whales", "ex_bal_BTC_total", "交易所 BTC 余额", "BTC", ("交易所btc余额",), 90),
    _c("exchanges_whales", "ex_bal_ETH_total", "交易所 ETH 余额", "ETH", ("交易所eth余额",), 90),
    _c(
        "derivatives_spot",
        "fut_open_interest_usd",
        "全市场合约持仓",
        "亿美元",
        ("全市场持仓", "合约持仓"),
        90,
        1e8,
    ),
    _c(
        "derivatives_spot",
        "fut_volume_24h_usd",
        "合约24h成交量",
        "亿美元",
        ("合约成交量", "24小时成交量", "合约成交"),
        90,
        1e8,
    ),
    _c(
        "derivatives_spot",
        "fut_liq_total_24h_usd",
        "24h 爆仓总额",
        "亿美元",
        ("爆仓", "清算额"),
        90,
        1e8,
    ),
    _c(
        "derivatives_spot", "fut_liq_long_24h_usd", "24h 多头爆仓", "亿美元", ("多头爆仓",), 90, 1e8
    ),
    _c(
        "derivatives_spot",
        "fut_liq_short_24h_usd",
        "24h 空头爆仓",
        "亿美元",
        ("空头爆仓",),
        90,
        1e8,
    ),
    _c("stablecoin_rwa", "rwa_tvl_usd", "RWA 总规模", "亿美元", ("rwa", "真实世界资产"), 90, 1e8),
    _c("stablecoin_rwa", "rwa_change7d_pct", "RWA 7日变化", "%", ("rwa 变化",), 90),
    _c(
        "etf_institutional",
        "treasury_total_btc_holdings",
        "上市公司持币总量",
        "BTC",
        ("上市公司持币", "企业持币", "储备比特币"),
        90,
    ),
    _c(
        "holdings_onchain_funds",
        "holdings_treasury_btc_sum",
        "机构/国家持币合计",
        "BTC",
        ("机构持币", "国家持币"),
        90,
    ),
    _c(
        "exchanges_whales",
        "whales_transfer_count",
        "巨鲸大额转账笔数",
        "笔",
        ("转账笔数", "大额转账"),
        30,
    ),
    # ---- 稳定币 ----
    _c(
        "stablecoins_top_10",
        "total_circulating_usd_bln",
        "稳定币总供应",
        "十亿美元",
        ("稳定币", "稳定币总市值", "stablecoin"),
        90,
    ),
    _c("stablecoins_top_10", "USDT_bln", "USDT 供应量", "十亿美元", ("usdt", "tether"), 90),
    _c("stablecoins_top_10", "USDC_bln", "USDC 供应量", "十亿美元", ("usdc",), 90),
    _c("stablecoins_top_10", "usdt_pct_of_total", "USDT 市占率", "%", ("usdt 市占率",), 90),
    # ---- 期权 ----
    _c("options", "put_call_ratio", "期权 Put/Call 比", "", ("put call", "期权多空比"), 90),
    _c("options", "max_pain_oi", "期权最大痛点持仓", "张", ("最大痛点", "max pain"), 90),
    _c("options", "total_oi", "期权总持仓", "张", ("期权持仓",), 90),
    # ---- intermarket（跨市场行情）----
    _c("BTC", "close_usd", "BTC 价格", "USD", ("btc 价格", "比特币价格"), 90),
    _c("ETH", "close_usd", "ETH 价格", "USD", ("eth 价格", "以太坊价格"), 90),
    _c("SOL", "close_usd", "SOL 价格", "USD", ("sol 价格", "索拉纳价格"), 90),
    _c("XAU", "close_usd", "黄金价格", "USD", ("黄金价格", "金价"), 365),
    # ---- calendar（预期代理）----
    _c("fedwatch", "cut_prob", "降息概率", "%", ("降息概率",), 365),
    _c("fedwatch", "hold_prob", "维持利率概率", "%", ("维持利率概率", "按兵不动概率"), 365),
    _c("fedwatch", "hike_prob", "加息概率", "%", ("加息概率",), 365),
    _c("fedwatch", "effr", "有效联邦基金利率", "%", ("effr", "有效联邦基金利率"), 365),
    # ---- narrative（情绪增强因子）----
    _c("fear_greed_enhanced", "momentum", "情绪动量因子", "", ("情绪动量", "恐惧贪婪动量"), 90),
    _c("fear_greed_enhanced", "capital_flow", "情绪资金流因子", "", ("情绪资金流",), 90),
    _c("fear_greed_enhanced", "volatility", "情绪波动率因子", "", ("情绪波动率",), 90),
    _c("fear_greed_enhanced", "funding", "情绪资金费率因子", "", ("情绪资金费率",), 90),
    # ---- cycle_signals（周期底部信号，18/19 调研新增）----
    _c(
        "cycle_signals",
        "bottom_hit_ratio_pct",
        "周期底部信号命中率",
        "%",
        ("底部信号命中率", "底部信号"),
        365,
    ),
    _c(
        "cycle_signals",
        "bottom_hit_count",
        "周期底部信号命中数",
        "个",
        ("底部信号数", "底部命中数", "底部信号命中"),
        365,
    ),
]


# 全量自动目录（catalog_build 生成的 data_catalog.json），懒加载 + 进程内缓存
_CATALOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_catalog.json")
_CATALOG_CACHE: Optional[Dict[str, Any]] = None

# Tier-3 精确匹配时排除的泛化词（避免 "value"/"count" 命中随机序列）
_CATALOG_STOPWORDS = {
    "value",
    "count",
    "price",
    "total",
    "latest",
    "asset",
    "chain",
    "data",
    "time",
    "pct",
    "usd",
    "btc",
    "eth",
    "index",
    "ratio",
    "amount",
    "volume",
}


def _load_catalog() -> Optional[Dict[str, Any]]:
    """加载全量目录并建索引：sub → rows、metric → 最大 rows 的 (sub, rows)。"""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE or None
    try:
        if not os.path.isfile(_CATALOG_PATH):
            _CATALOG_CACHE = {}
            return None
        with open(_CATALOG_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        _CATALOG_CACHE = {}
        return None
    subs: Dict[str, Tuple[str, int]] = {}
    metrics: Dict[str, Tuple[str, str, int]] = {}
    for key, rows in (raw.get("series") or {}).items():
        if "::" not in key:
            continue
        sub, metric = key.split("::", 1)
        try:
            n = int(rows)
        except (TypeError, ValueError):
            n = 0
        if sub.lower() not in subs or n > subs[sub.lower()][1]:
            subs[sub.lower()] = (sub, n)
        low = metric.lower()
        if low in _CATALOG_STOPWORDS or len(low) < 5:
            continue
        cur = metrics.get(low)
        if cur is None or n > cur[2]:
            metrics[low] = (sub, metric, n)
    _CATALOG_CACHE = {"subs": subs, "metrics": metrics, "total": raw.get("total_series", 0)}
    return _CATALOG_CACHE


def _match_catalog(text: str) -> Optional[Dict[str, Any]]:
    """Tier-3：问句里出现与目录完全一致的英文序列名/sub_category 即命中。"""
    import re

    cat = _load_catalog()
    if not cat:
        return None
    tokens = {t.lower() for t in re.findall(r"[A-Za-z0-9][A-Za-z0-9_./\-]{3,}", text or "")}
    if not tokens:
        return None
    for tok in sorted(tokens, key=len, reverse=True):
        if tok in cat["metrics"]:
            sub, metric, _ = cat["metrics"][tok]
            return {
                "sub_category": sub,
                "metric_name": metric,
                "label": f"{sub} · {metric}",
                "unit": "",
                "days": 90,
                "scale": 1.0,
                "sign": 1.0,
                "source": "catalog",
            }
        if tok in cat["subs"]:
            sub, _ = cat["subs"][tok]
            return {
                "sub_category": sub,
                "metric_name": "value",
                "label": sub,
                "unit": "",
                "days": 90,
                "scale": 1.0,
                "sign": 1.0,
                "source": "catalog",
            }
    return None


def count_series_hits(text: str) -> int:
    """问句命中的不同指标序列数（不含纯币种/标的词），用于判断是否「多维并列」。"""
    low = _norm(text)
    hits = set()
    for (sub, metric), aliases, *_ in METRIC_ALIASES:
        for alias in aliases:
            name = _norm(alias)
            if len(name) < 2 or name in _SYMBOL_WORDS:
                continue
            if name in low:
                hits.add((sub, metric))
                break
    for item in CURATED_SERIES:
        for alias in item["keywords"]:
            name = _norm(alias)
            if len(name) < 2 or name in _SYMBOL_WORDS:
                continue
            if name in low:
                hits.add((item["sub_category"], item["metric_name"]))
                break
    return len(hits)


def resolve_series(text: str) -> Optional[Dict[str, Any]]:
    """自然语言 → 单维序列定义（别名 → curated → 全量目录），未命中返回 None。"""
    if not text:
        return None
    low = _norm(text)
    # Tier-1/Tier-2 一起按「最长别名优先」比较，避免短词截断长词
    best: Optional[Tuple[str, str, str, str, int]] = None
    best_len = 0
    for (sub, metric), aliases, label, unit, days in METRIC_ALIASES:
        for alias in aliases:
            name = _norm(alias)
            if len(name) < 2:
                continue
            if name in low and len(name) > best_len:
                best, best_len = (sub, metric, label, unit, days), len(name)
    for item in CURATED_SERIES:
        for alias in item["keywords"]:
            name = _norm(alias)
            if len(name) < 2:
                continue
            if name in low and len(name) > best_len:
                best = (
                    item["sub_category"],
                    item["metric_name"],
                    item["label"],
                    item["unit"],
                    item["days"],
                )
                best_len = len(name)
    if best is not None:
        for item in CURATED_SERIES:
            if (item["sub_category"], item["metric_name"]) == (best[0], best[1]):
                return dict(item)
        return {
            "sub_category": best[0],
            "metric_name": best[1],
            "label": best[2],
            "unit": best[3],
            "days": best[4],
            "scale": 1.0,
            "sign": 1.0,
            "source": "alias",
        }
    return _match_catalog(text)


def format_series_output(
    *,
    series: Dict[str, Any],
    points: List[Dict[str, Any]],
    days: int,
    quality: str = "",
    source: str = "",
) -> Dict[str, Any]:
    """统一「索引输出」模板：所有单维数据问答共用同一结构，前端可原样渲染。

    返回 {kind,id,title,unit,value,as_of,window,range,change,quality,source,text}，
    text 为一句可直接展示的中文摘要（L1 直答与前端卡片同源）。
    """
    import time as _t

    unit = series.get("unit", "") or ""
    scale = series.get("scale", 1.0) or 1.0
    sign = series.get("sign", 1.0) or 1.0
    sid = f"{series.get('sub_category')}::{series.get('metric_name')}"
    title = series.get("label") or sid
    prec = 0 if unit in _UNIT_INT else 2
    out: Dict[str, Any] = {
        "kind": "series",
        "id": sid,
        "title": title,
        "unit": unit,
        "days": days,
        "quality": quality,
        "source": source,
        "points_n": len(points or []),
    }
    if not points:
        out["value"] = None
        out["text"] = f"{title}：近 {days} 天暂无历史数据（{sid}）"
        return out

    def _fmt(v: float) -> str:
        return f"{v / scale:.{prec}f}"

    vals = [float(p["value"]) * sign for p in points]
    last = vals[-1]
    first = vals[0]
    last_ts = int(points[-1].get("ts", 0))
    g = _t.gmtime(last_ts + 8 * 3600)
    as_of = "%04d-%02d-%02d %02d:%02d" % (g.tm_year, g.tm_mon, g.tm_mday, g.tm_hour, g.tm_min)
    delta = last - first
    pct = (delta / abs(first) * 100.0) if first else 0.0
    out.update(
        {
            "value": round(last, 6),
            "as_of": as_of,
            "window": {"days": days, "points": len(vals)},
            "range": {"min": round(min(vals), 6), "max": round(max(vals), 6)},
            "change": {"abs": round(delta, 6), "pct": round(pct, 2)},
        }
    )
    text = (
        f"{title}：最新 {_fmt(last)}{unit}（{as_of} CST）；"
        f"近 {days} 天 {_fmt(min(vals))}~{_fmt(max(vals))}{unit}，"
        f"变化 {delta / scale:+.{prec}f}{unit}（{pct:+.2f}%）"
    )
    if quality:
        text += f"；数据质量 {quality}"
    out["text"] = text
    return out
