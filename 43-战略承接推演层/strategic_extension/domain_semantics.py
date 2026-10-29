# -*- coding: utf-8 -*-
"""五维语义映射层（方案A，SPEC v1.2 语义重构）。

定位：保留内部计算键名（dao/tian/di/jiang/fa）与全部计算函数结构不变，
新增语义映射层，对外输出（信号/四要素/文档）统一使用交易市场语义：

| 交易市场语义 | 内部键 | 权重 | 语义内容 |
|---|---|---|---|
| 宏观政策 macro_policy | tian | 20% | 美林时钟/流动性周期/日历季节性/央行政策 |
| 技术分析 technical | di | 25% | regime/弹簧力场MA/盘整/FTD/MA200距离/洗盘判定 |
| 资金流向 capital_flow | dao | 20% | CFTC投机头寸/稳定币供应/交易所净流入/板块轮动 |
| 市场情绪 market_sentiment | jiang | 15% | 自建情绪通道（F&G恐惧贪婪指数+分量） |
| 基本面分析 fundamental | fa | 20% | 系统质量（智信仁勇严）+ 链上基本面 |

权重说明：新权重（20/25/20/15/20）为 v1.2 版本变更值，原权重
（道30/天15/地25/将15/法15）保留于 v1.0 冻结记录。

注意：内部键与语义维的对应为『内容主导』映射——内部计算函数的输入字段
按新语义归类调整由承接适配器与情绪通道承担，本模块只做命名与权重映射。
"""

from typing import Any, Dict

# 语义映射表：内部键 → 交易市场语义
DOMAIN_SEMANTIC_MAP: Dict[str, Dict[str, Any]] = {
    "tian": {
        "semantic_name": "宏观政策",
        "semantic_key": "macro_policy",
        "weight": 0.20,
        "description": "美林时钟/流动性周期/日历季节性/央行政策方向",
    },
    "di": {
        "semantic_name": "技术分析",
        "semantic_key": "technical",
        "weight": 0.25,
        "description": "市场结构regime/弹簧力场MA/盘整持续/FTD/MA200距离/洗盘判定",
    },
    "dao": {
        "semantic_name": "资金流向",
        "semantic_key": "capital_flow",
        "weight": 0.20,
        "description": "CFTC投机头寸/稳定币供应变化/交易所净流入/板块轮动",
    },
    "jiang": {
        "semantic_name": "市场情绪",
        "semantic_key": "market_sentiment",
        "weight": 0.15,
        "description": "自建情绪通道：F&G恐惧贪婪指数+分量（动量/资金费率/资金流/波动率）",
    },
    "fa": {
        "semantic_name": "基本面分析",
        "semantic_key": "fundamental",
        "weight": 0.20,
        "description": "系统质量（智信仁勇严）+ 链上基本面（NVT/MVRV/SOPR/活跃地址）",
    },
}

# 反向映射：语义键 → 内部键
SEMANTIC_TO_INTERNAL = {v["semantic_key"]: k for k, v in DOMAIN_SEMANTIC_MAP.items()}

# 新权重表（语义键 → 权重）
SEMANTIC_WEIGHTS = {v["semantic_key"]: v["weight"] for v in DOMAIN_SEMANTIC_MAP.values()}


def to_semantic_scores(internal_scores: Dict[str, int]) -> Dict[str, int]:
    """内部五维评分 → 语义五维评分（键名转换，值不变）。"""
    out: Dict[str, int] = {}
    for internal_key, score in (internal_scores or {}).items():
        sem = DOMAIN_SEMANTIC_MAP.get(internal_key)
        if sem:
            out[sem["semantic_key"]] = score
        else:
            out[internal_key] = score
    return out


def semantic_total(internal_scores: Dict[str, int]) -> int:
    """按新语义权重计算加权总分（0-100）。"""
    total = 0.0
    for internal_key, meta in DOMAIN_SEMANTIC_MAP.items():
        score = (internal_scores or {}).get(internal_key, 50)
        total += score * meta["weight"]
    return int(round(total))


def semantic_descriptions() -> Dict[str, str]:
    """语义维描述表（供文档与信号 payload 使用）。"""
    return {
        v["semantic_key"]: "{}：{}".format(v["semantic_name"], v["description"])
        for v in DOMAIN_SEMANTIC_MAP.values()
    }
