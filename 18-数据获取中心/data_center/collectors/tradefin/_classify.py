"""中文财经快讯 → §3.1 事件类型 / 受影响标的 的轻量规则分类器（P1-A）。

为什么不用 LLM：中文门户快讯量大、价值密度低，规则分类可离线复现且有单测；
LLM 抽取留给后续 P2 的深度文章 F1/F2/F3（`processing/factor_extractor.py`）。

标的口径：只使用 40 域龙头宇宙已存在的代码（XAU/XAG/CL/NG/XCU/BTC/ETH/NVDA/
TLT/JP225/US500）；无法归因到单一龙头的宏观快讯统一为 "MACRO"（39 的既有兜底值），
禁止把 A 股快讯强行映射到美股指数。
"""

from __future__ import annotations

# 类型优先级：同分时按元组顺序取第一个。
# rate_decision 优先于 fomc —— "美联储降息"实质是利率决议，不是会议日程。
_TYPE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "rate_decision",
        (
            "降息",
            "加息",
            "利率决议",
            "维持利率",
            "政策利率",
            "LPR",
            "降准",
            "存款准备金率",
            "逆回购",
        ),
    ),
    ("fomc", ("FOMC", "美联储", "鲍威尔", "点阵图", "议息会议", "会议纪要")),
    ("cpi", ("CPI", "消费者物价", "核心通胀", "通胀数据", "PCE")),
    ("nfp", ("非农", "就业数据", "失业率", "ADP", "就业报告")),
    ("earnings", ("财报", "业绩", "营收", "净利润", "季报", "年报", "EPS")),
    ("guidance", ("业绩指引", "上调预期", "下调预期", "盈利预警", "业绩展望")),
    ("mna", ("收购", "并购", "合并", "要约收购", "私有化")),
    ("buyback", ("回购", "增持计划")),
    ("dividend", ("分红", "派息", "股息", "特别股息")),
    (
        "regulatory",
        ("监管", "证监会", "SEC", "罚款", "处罚", "立案", "调查", "牌照", "合规", "禁令"),
    ),
    ("product", ("发布", "新品", "量产", "订单", "芯片", "交付")),
    ("legal", ("诉讼", "起诉", "仲裁", "判决", "违法")),
    (
        "macro_other",
        ("GDP", "PMI", "社融", "M2", "社零", "进出口", "贸易数据", "工业增加值", "零售销售"),
    ),
)

_SYMBOL_RULES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("黄金", "金价", "COMEX黄金"), ("XAU",)),
    (("白银", "银价"), ("XAG",)),
    (("原油", "油价", "WTI", "布伦特", "OPEC"), ("CL",)),
    (("天然气",), ("NG",)),
    (("铜价", "LME铜", "精铜", "铜矿"), ("XCU",)),
    (("比特币", "BTC", "加密货币", "以太坊", "ETH", "稳定币"), ("BTC", "ETH")),
    (("英伟达", "NVIDIA", "NVDA", "AI芯片", "算力"), ("NVDA",)),
    (("美债", "国债收益率", "TLT", "长期国债"), ("TLT",)),
    (("日经", "日本央行", "日元"), ("JP225",)),
    (("标普", "纳斯达克", "美股"), ("US500",)),
)

DEFAULT_SYMBOLS: tuple[str, ...] = ("MACRO",)
DEFAULT_TYPE = "macro_other"


def classify(headline: str, body: str = "") -> tuple[str, list[str]]:
    """返回 (event_type ∈ §3.1 枚举, symbols)。"""
    hay = f"{headline or ''} {body or ''}"
    best_type = DEFAULT_TYPE
    best_key: tuple[int, int] | None = None
    for idx, (type_, keywords) in enumerate(_TYPE_RULES):
        hits = sum(1 for kw in keywords if kw in hay)
        if not hits:
            continue
        key = (hits, -idx)
        if best_key is None or key > best_key:
            best_key, best_type = key, type_

    symbols: list[str] = []
    for keywords, codes in _SYMBOL_RULES:
        if not any(kw in hay for kw in keywords):
            continue
        for code in codes:
            if code not in symbols:
                symbols.append(code)

    return best_type, symbols or list(DEFAULT_SYMBOLS)
