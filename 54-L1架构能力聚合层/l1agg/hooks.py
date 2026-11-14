# -*- coding: utf-8 -*-
"""四类追问钩子：把 L1 的四项基础能力做成「用户可点的下一步」。

能力映射（与 SPEC S1/S2 + 延续性画像一一对应）：
  1. past_now_echo       过去—现在对比（价格回显，默认基准硬约束）
  2. leader_compare      同赛道龙头对照（涨跌幅度差，供信号传导）
  3. top_correlation     与目标资产相关性最高的指标（L1 统计学价值）
  4. persistence_strength 历史周期下趋势延续性强度（Hurst / VR / AR1）

纪律：本模块只生成「文本 + 可执行 query」，不计算、不取数；
所有钩子的 query 必须能被 `data_query_executor` 的确定性执行器直接消费。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .price_echo import _CLASS_TO_GROUP, ANCHORS

# 龙头/对手盘：加密→BTC，美股→US500，宏观→XAU，大宗→CL，避险→XAU，其他→BTC
_GROUP_LEADER = {
    "crypto": "BTC",
    "us_equity": "US500",
    "macro": "XAU",
    "commodity": "CL",
    "safe_haven": "XAU",
    "default": "BTC",
}

# 若目标资产本身就是该赛道龙头，对手盘换成同赛道第二标的
_PEER = {
    "BTC": "ETH",
    "ETH": "BTC",
    "SOL": "ETH",
    "US500": "US100",
    "US100": "US500",
    "DJIA": "US500",
    "XAU": "US500",
    "CL": "BZ",
    "BZ": "CL",
    "NG": "CL",
}

_LABELS = {
    "BTC": "比特币（BTC）",
    "ETH": "以太坊（ETH）",
    "SOL": "索拉纳（SOL）",
    "US500": "标普500",
    "US100": "纳斯达克100",
    "DJIA": "道琼斯",
    "XAU": "黄金（XAU）",
    "CL": "WTI 原油",
    "BZ": "布伦特原油",
    "NG": "天然气",
}

# query 里用的短名（供 date/price 解析）
_SHORT = {
    "BTC": "比特币",
    "ETH": "以太坊",
    "SOL": "索拉纳",
    "US500": "标普500",
    "US100": "纳斯达克100",
    "DJIA": "道琼斯",
    "XAU": "黄金",
    "CL": "WTI原油",
    "BZ": "布伦特原油",
    "NG": "天然气",
}


def label_of(symbol: str) -> str:
    """符号 → 中文展示名（未知符号原样返回）。"""
    sym = (symbol or "").upper()
    return _LABELS.get(sym, symbol)


def short_of(symbol: str) -> str:
    sym = (symbol or "").upper()
    return _SHORT.get(sym, symbol)


def group_of(symbol: str) -> str:
    """符号 → 锚组（crypto/us_equity/macro/commodity/safe_haven/default）。"""
    try:
        from .leader_registry import resolve

        binding = resolve(symbol)
        if binding is not None:
            return _CLASS_TO_GROUP.get(binding.asset_class, "default")
    except Exception:
        pass
    return "default"


def leader_of(symbol: str) -> str:
    """该资产所属赛道的默认基准资产（硬约束口径）。"""
    return _GROUP_LEADER.get(group_of(symbol), ANCHORS["default"].primary)


def peer_of(symbol: str) -> str:
    """对照标的：非龙头→赛道龙头；本身是龙头→赛道第二标的。"""
    sym = (symbol or "").upper()
    leader = leader_of(sym)
    if leader != sym:
        return leader
    return _PEER.get(sym, "BTC")


def build_hooks(
    symbol: str,
    *,
    at_day: Optional[str] = None,
    subject: Optional[str] = None,
) -> List[Dict[str, str]]:
    """生成四类追问钩子（顺序固定：回显 → 龙头对照 → 相关性 → 延续性）。"""
    sym = (symbol or "").upper() or "BTC"
    subj = subject or short_of(sym)
    anchor = leader_of(sym)
    peer = peer_of(sym)
    day = at_day or ""

    echo_text = (
        f"您想知道{label_of(anchor)}{day + ' ' if day else ''}的价格与现在的变化吗？"
        if anchor != sym
        else f"您想知道{label_of(peer)}同期价格与现在的变化吗？"
    )
    echo_query = f"查询{day + ' ' if day else ''}{short_of(anchor if anchor != sym else peer)}价格"

    return [
        {
            "id": "past_now_echo",
            "capability": "过去—现在对比（价格回显）",
            "text": echo_text,
            "query": echo_query,
        },
        {
            "id": "leader_compare",
            "capability": "同赛道龙头对照",
            "text": f"您想对比{subj}与{short_of(peer)}的涨跌幅度吗？",
            "query": f"对比{subj}和{short_of(peer)}的涨跌幅",
        },
        {
            "id": "top_correlation",
            "capability": "相关性最高指标",
            "text": f"您想了解与{subj}相关性最高的指标吗？",
            "query": f"与{subj}相关性最高的指标",
        },
        {
            "id": "persistence_strength",
            "capability": "趋势延续性强度",
            "text": f"您想知道{subj}历史周期下的趋势延续性强度吗？",
            "query": f"{subj}趋势延续性强度",
        },
    ]


def format_hooks(hooks: List[Dict[str, str]]) -> str:
    """钩子 → 追加在答案末尾的可选项文本。"""
    if not hooks:
        return ""
    lines = [f"{i}) {h['text']}" for i, h in enumerate(hooks, 1)]
    return "\n\n您还可以继续问：\n" + "\n".join(lines)
