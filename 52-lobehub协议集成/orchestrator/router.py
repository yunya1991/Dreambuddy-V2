#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4.6 — 意图路由（纯确定性，零 token / 零第三方依赖）。

SPEC §7.6 / 铁律⑥：只有「方案择优类」才进 Debate 双链；交易执行永不进辩论；
高风险强制人工审批；事实查询直答；其余走 orchestrator-workers 单边兜底。

路由五分流（严格按优先级，命中即返回）：
  ① trade_deny        下单动作 + 标的/数量特征，或 DreamOS 交易意图类型
  ② high_risk_human   risk_flags 命中 13 风控域关键词，或文本含 全仓/杠杆/借款
  ③ debate            择优信号 + 可判定标准（回测/指标/成本/延迟/准确率/收益/风险）
  ④ direct_answer     短事实查询（<60 字，且不含方案/对比/优化等判断类标记）
  ⑤ workers           其余兜底（单边规划，不升级 Debate）

规则版本化写入 trace，变更需评审（`ROUTE_RULES_VERSION`）。
"""

from __future__ import annotations

import re
from typing import Any

ROUTE_RULES_VERSION = "r9-v1"

ROUTES = ("trade_deny", "high_risk_human", "debate", "workers", "direct_answer")

# DreamOS 六类意图（1-ARCHITECTURE/dreamos/core/arrange/types.py::INTENT_CHAIN_MAP）
DREAMOS_TRADE_INTENTS = {
    "TREND_FOLLOWING",
    "MEAN_REVERSION",
    "FUNDAMENTAL_PLAY",
    "BREAKOUT",
}
DREAMOS_QUERY_INTENTS = {"KNOWLEDGE_MATCH"}

# ① 交易执行类
TRADE_ACTION_WORDS = (
    "买入",
    "卖出",
    "加仓",
    "减仓",
    "平仓",
    "开仓",
    "下单",
    "挂单",
    "实盘",
    "paper trading",
    "仓位调整",
    "止损单",
)
TRADE_TARGET_WORDS = (
    "股",
    "手",
    "张",
    "份",
    "合约",
    "期货",
    "期权",
    "etf",
    "基金",
    "股票",
    "标的",
    "仓位",
    "币",
    "btc",
    "eth",
    "茅台",
)
# 数量特征：数字 + 交易单位，或 A 股 6 位代码
QUANTITY_RE = re.compile(r"\d+(?:\.\d+)?\s*(?:股|手|张|份|个|万|千|元|刀|usdt|btc|eth)")
STOCK_CODE_RE = re.compile(r"(?<![0-9])(?:sh|sz|bj)?\d{6}(?![0-9])", re.IGNORECASE)

# ② 高风险（13 风控域关键词子集）
RISK_DOMAIN_WORDS = ("杠杆", "全仓", "借款", "融资", "大额", "超额")
RISK_TEXT_WORDS = ("全仓", "杠杆", "借款")

# ③ 方案择优
DEBATE_SIGNAL_WORDS = (
    "对比",
    "比较",
    "哪个更好",
    "哪种更好",
    "哪个更",
    "哪种更",
    "哪个方案",
    "哪种方案",
    "选哪个",
    "用哪个",
    "还是用",
    "二选一",
    "选型",
    "方案选择",
    "权衡",
    "取舍",
    "优劣",
    "最优",
    "参数怎么定",
)
DEBATE_CRITERIA_WORDS = (
    "回测",
    "指标",
    "成本",
    "延迟",
    "准确率",
    "收益",
    "风险",
    "阈值",
    "夏普",
    "稳定性",
    "一致率",
    "可解释",
)

# ④ 短事实查询
SHORT_QUERY_MAX_LEN = 60
QUERY_WORDS = ("查询", "是多少", "什么是", "是否", "哪一年", "几点", "价格", "多少")
# 判断/决策类标记：出现即不视为「短事实查询」（含方案/对比/优化，SPEC 显式要求）
QUERY_EXCLUDE_WORDS = ("方案", "对比", "优化", "评估", "怎么", "如何", "要不要", "哪个")


def _contains_any(text: str, words: tuple[str, ...]) -> list[str]:
    """返回命中的关键词列表（拉丁词大小写不敏感）。"""
    lowered = text.lower()
    return [word for word in words if word.lower() in lowered]


def _has_trade_target(text: str) -> list[str]:
    """判定交易标的/数量特征，返回命中特征。"""
    lowered = text.lower()
    matched: list[str] = []
    quantity = QUANTITY_RE.search(lowered)
    if quantity:
        matched.append(quantity.group(0).strip())
    code = STOCK_CODE_RE.search(lowered)
    if code:
        matched.append(code.group(0))
    for word in TRADE_TARGET_WORDS:
        if word in lowered:
            matched.append(word)
            break
    return matched


def _intent_type_route(intent_type: str | None) -> str | None:
    """DreamOS 意图类型 → 路由；未知/未映射返回 None（回退关键词判定）。"""
    if not intent_type:
        return None
    normalized = str(intent_type).strip().upper()
    if normalized in DREAMOS_TRADE_INTENTS:
        return "trade_deny"
    if normalized in DREAMOS_QUERY_INTENTS:
        return "direct_answer"
    return None


def route(
    intent: str,
    *,
    risk_flags: list[str] | None = None,
    intent_type: str | None = None,
) -> dict[str, Any]:
    """确定性意图路由 → {route, reason, matched, version}。

    优先级：trade_deny → high_risk_human → debate → direct_answer → workers。
    intent_type 可映射时以其为主（reason 标注来源 dreamos_intent），
    关键词为辅（来源 keyword）；交易/高风险安全分支始终优先。
    """
    text = (intent or "").strip()
    flags = [str(flag).strip() for flag in (risk_flags or []) if str(flag).strip()]
    mapped = _intent_type_route(intent_type)

    # ① 交易执行类：下单动作 + 标的/数量，或 DreamOS 交易意图
    action_hits = _contains_any(text, TRADE_ACTION_WORDS)
    target_hits = _has_trade_target(text)
    if action_hits and target_hits:
        return {
            "route": "trade_deny",
            "reason": f"命中下单动作 {action_hits} + 交易标的/数量特征 {target_hits}；"
            "交易执行永不进辩论（铁律④）（来源: keyword）",
            "matched": action_hits + target_hits,
            "version": ROUTE_RULES_VERSION,
        }
    if mapped == "trade_deny":
        return {
            "route": "trade_deny",
            "reason": f"DreamOS 意图类型 {intent_type} 属交易意图类；"
            "交易执行永不进辩论（铁律④）（来源: dreamos_intent）",
            "matched": [f"intent_type={intent_type}"],
            "version": ROUTE_RULES_VERSION,
        }

    # ② 高风险：risk_flags 命中风控域，或文本含全仓/杠杆/借款
    flag_hits = _contains_any(" ".join(flags), RISK_DOMAIN_WORDS)
    text_risk_hits = _contains_any(text, RISK_TEXT_WORDS)
    if flag_hits or text_risk_hits:
        matched = flag_hits + text_risk_hits
        source = "risk_flags" if flag_hits else "keyword"
        return {
            "route": "high_risk_human",
            "reason": f"命中 13 风控域关键词 {matched}；强制人工审批节点（无论任务类型）"
            f"（来源: {source}）",
            "matched": matched,
            "version": ROUTE_RULES_VERSION,
        }

    # ③ 方案择优：择优信号 + 可判定标准
    signal_hits = _contains_any(text, DEBATE_SIGNAL_WORDS)
    if "评估" in text and re.search(r"(?:与|和|vs|相比)", text, re.IGNORECASE):
        signal_hits.append("评估A与B")
    criteria_hits = _contains_any(text, DEBATE_CRITERIA_WORDS)
    if signal_hits and criteria_hits:
        return {
            "route": "debate",
            "reason": f"命中择优信号 {signal_hits} + 可判定标准 {criteria_hits}；"
            "进入 Debate 双链（来源: keyword）",
            "matched": signal_hits + criteria_hits,
            "version": ROUTE_RULES_VERSION,
        }

    # ④ 直答：intent_type 映射优先，否则短事实查询
    if mapped == "direct_answer":
        return {
            "route": "direct_answer",
            "reason": f"DreamOS 意图类型 {intent_type} 属知识查询类；"
            "直答省 token（不进辩论/双规划）（来源: dreamos_intent）",
            "matched": [f"intent_type={intent_type}"],
            "version": ROUTE_RULES_VERSION,
        }
    query_hits = _contains_any(text, QUERY_WORDS)
    exclude_hits = _contains_any(text, QUERY_EXCLUDE_WORDS)
    if len(text) < SHORT_QUERY_MAX_LEN and query_hits and not exclude_hits:
        return {
            "route": "direct_answer",
            "reason": f"短事实查询（{len(text)} 字，命中 {query_hits}）；直答省 token（来源: keyword）",
            "matched": query_hits,
            "version": ROUTE_RULES_VERSION,
        }

    # ⑤ 兜底：单边规划 + orchestrator-workers
    return {
        "route": "workers",
        "reason": "未命中交易/高风险/择优/直答分支；走单边规划（不升级 Debate）（来源: keyword）",
        "matched": [],
        "version": ROUTE_RULES_VERSION,
    }


__all__ = [
    "ROUTES",
    "ROUTE_RULES_VERSION",
    "DREAMOS_QUERY_INTENTS",
    "DREAMOS_TRADE_INTENTS",
    "route",
]
