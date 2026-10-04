"""
对话意图分类器

属于 DreamOS 操作系统内核 S 层。
输入用户消息，输出对话意图（6×30）+ 槽位 + 风险等级 + 能力路由。

分类策略:
    1. 规则快速匹配（零 Token，处理明确意图）
    2. LLM 分类（处理模糊/复杂意图）
    3. 结果融合

输出结构（DialogueIntentResult）:
    - intent_primary: 一级意图
    - intent_secondary: 二级意图
    - slots: 类型化槽位
    - risk_level: low/medium/high
    - in_scope: 是否在 DreamOS 能力范围内
    - capability_route: 能力路由决策
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .taxonomy import (
    INTENT_TAXONOMY,
    get_primary_intent,
    get_risk_level,
    get_default_capability_route,
    is_valid_secondary,
)
from .slots import extract_slots_from_text, normalize_stock
from .multi_intent import MultiIntentDetector


# ============================================================
# 规则匹配关键词库
# ============================================================

# 二级意图 → 关键词列表
SECONDARY_KEYWORDS: Dict[str, List[str]] = {
    # query
    "market_query": ["多少钱", "价格", "行情", "现价", "最新价", "涨了", "跌了", "涨幅", "跌幅"],
    "holding_query": ["持仓", "我买了", "我的仓位", "持有", "仓位"],
    "order_query": ["订单", "委托", "挂单", "成交了吗", "撤单"],
    "account_query": ["账户", "余额", "总资产", "可用资金", "盈亏"],
    "market_overview": ["大盘", "市场", "今天怎么样", "整体", "概览"],
    # analysis
    "technical_analysis": ["走势", "技术面", "k线", "支撑", "压力", "均线", "macd", "rsi"],
    "holding_analysis": ["分析持仓", "持仓分析", "我的票怎么样"],
    "deep_analysis": ["深度分析", "调研报告", "全面分析", "详细分析"],
    "three_screen_analysis": ["三屏", "周线", "多周期"],
    "sector_analysis": ["板块", "行业", "概念", "轮动"],
    # trade
    "buy": ["买入", "买进", "建仓", "开多", "做多"],
    "add_position": ["加仓", "补仓", "追加"],
    "sell": ["卖出", "卖掉", "止盈", "平仓", "清仓"],
    "close_position": ["砍了", "止损", "全部卖掉", "清仓"],
    "conditional_order": ["条件单", "止损单", "止盈单", "挂单买", "挂单卖"],
    "order_manage": ["改单", "修改订单", "撤单", "订单管理"],
    # strategy
    "stock_recommendation": ["推荐", "荐股", "买什么", "选什么", "看好"],
    "factor_screen": ["筛选", "选股", "因子", "条件选股"],
    "strategy_design": ["策略", "设计策略", "策略开发", "怎么交易"],
    "strategy_optimization": ["优化", "参数", "调参", "改进策略"],
    # risk
    "risk_assessment": ["风险", "评估风险", "风险大吗"],
    "risk_advice": ["风控建议", "怎么控制风险", "止损位"],
    "alert_setup": ["预警", "提醒", "设置提醒", "到价提醒"],
    "portfolio_risk": ["组合风险", "仓位风险", "集中度"],
    # dialog
    "confirm": ["确认", "是的", "对", "好的", "可以"],
    "cancel": ["取消", "不要了", "算了", "撤销"],
    "modify": ["不是", "改成", "修改", "换"],
    "repeat": ["再说一遍", "重复", "刚才说什么"],
    "clarify": ["什么意思", "没懂", "解释一下", "哪个"],
    "chitchat": ["你好", "谢谢", "再见", "在吗"],
}


# 二级意图的权重 — 解决同分冲突（分析/交易类优先于查询类）
# 数值越大，在关键词匹配数相同时越优先
SECONDARY_WEIGHTS: Dict[str, float] = {
    # trade 类最高权重（高风险意图优先识别）
    "buy": 3.0, "add_position": 3.0, "sell": 3.0,
    "close_position": 3.0, "conditional_order": 3.0, "order_manage": 3.0,
    # analysis 类次高（分析优先于简单查询）
    "technical_analysis": 2.5, "holding_analysis": 2.5,
    "deep_analysis": 2.5, "three_screen_analysis": 2.5, "sector_analysis": 2.5,
    # strategy/risk 类中等
    "stock_recommendation": 2.0, "factor_screen": 2.0,
    "strategy_design": 2.0, "strategy_optimization": 2.0,
    "risk_assessment": 2.0, "risk_advice": 2.0,
    "alert_setup": 2.0, "portfolio_risk": 2.0,
    # query 类较低
    "market_query": 1.0, "holding_query": 1.0,
    "order_query": 1.0, "account_query": 1.0, "market_overview": 1.0,
    # dialog 类最低
    "confirm": 0.5, "cancel": 0.5, "modify": 0.5,
    "repeat": 0.5, "clarify": 0.5, "chitchat": 0.5,
}


def _rule_classify(text: str) -> Optional[str]:
    """规则快速匹配二级意图（带权重）

    优化（2026-09-17）：
      - 引入意图权重，解决同分冲突
      - 同分时优先选择权重更高的意图（分析/交易 > 查询）
      - 例如："分析比特币价格走势" → technical_analysis(2.5) 而非 market_query(1.0)
    """
    scores: Dict[str, float] = {}
    for secondary, keywords in SECONDARY_KEYWORDS.items():
        match_count = sum(1 for kw in keywords if kw in text)
        if match_count > 0:
            weight = SECONDARY_WEIGHTS.get(secondary, 1.0)
            scores[secondary] = match_count * weight

    if not scores:
        return None

    # 返回加权分最高的意图
    return max(scores, key=scores.get)


def _is_in_scope(secondary: str) -> bool:
    """判断意图是否在 DreamOS 能力范围内"""
    # 当前所有意图都在范围内（Harness 作为降级处理复杂场景）
    # 未来可根据具体意图和槽位判断
    return True


# ============================================================
# 分类结果
# ============================================================

@dataclass
class DialogueIntentResult:
    """对话意图识别结果"""
    intent_primary: str = "query"
    intent_secondary: str = "market_query"
    slots: Dict[str, Any] = field(default_factory=dict)
    risk_level: str = "low"
    in_scope: bool = True
    capability_route: str = "database"
    confidence: float = 0.0
    multi_intent: List[str] = field(default_factory=list)
    is_multi: bool = False
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_primary": self.intent_primary,
            "intent_secondary": self.intent_secondary,
            "slots": self.slots,
            "risk_level": self.risk_level,
            "in_scope": self.in_scope,
            "capability_route": self.capability_route,
            "confidence": self.confidence,
            "multi_intent": self.multi_intent,
            "is_multi": self.is_multi,
            "rationale": self.rationale,
        }


# ============================================================
# 主分类器
# ============================================================

class DialogueIntentClassifier:
    """对话意图分类器

    规则 + LLM 融合分类。
    """

    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM 客户端（可选，用于复杂意图分类）
        """
        self._llm_client = llm_client
        self._multi_intent_detector = MultiIntentDetector()

    def classify(self, text: str, context: Optional[Dict[str, Any]] = None) -> DialogueIntentResult:
        """分类用户输入

        Args:
            text: 用户输入文本
            context: 对话上下文

        Returns:
            DialogueIntentResult
        """
        if not text or not text.strip():
            return DialogueIntentResult(
                intent_primary="dialog",
                intent_secondary="chitchat",
                rationale="空输入",
            )

        # 1. 检测多意图（委托给 MultiIntentDetector 三层检测）
        multi = self._multi_intent_detector.detect(text)
        is_multi = len(multi) > 1

        # 2. 规则匹配主意图
        secondary = _rule_classify(text)

        if secondary:
            # 规则匹配成功
            primary = get_primary_intent(secondary)
            slots = extract_slots_from_text(text)
            risk_level = get_risk_level(primary)
            in_scope = _is_in_scope(secondary)
            capability_route = get_default_capability_route(primary)

            # 如果是多意图，取第一个作为主意图
            if is_multi:
                secondary = multi[0]
                primary = get_primary_intent(secondary)

            return DialogueIntentResult(
                intent_primary=primary,
                intent_secondary=secondary,
                slots=slots,
                risk_level=risk_level,
                in_scope=in_scope,
                capability_route=capability_route,
                confidence=0.8,
                multi_intent=multi if is_multi else [],
                is_multi=is_multi,
                rationale=f"规则匹配: {secondary}",
            )

        # 3. 规则未匹配，尝试 LLM 分类
        if self._llm_client:
            return self._llm_classify(text, context)

        # 4. 兜底：默认查询
        return DialogueIntentResult(
            intent_primary="query",
            intent_secondary="market_query",
            slots=extract_slots_from_text(text),
            risk_level="low",
            in_scope=True,
            capability_route="database",
            confidence=0.3,
            rationale="规则未匹配，默认查询",
        )

    def _llm_classify(self, text: str, context: Optional[Dict[str, Any]] = None) -> DialogueIntentResult:
        """LLM 分类（需要外部实现具体的 prompt 调用）"""
        # 这里提供框架，具体 LLM 调用由上层注入
        # 参考 intent-recognition-spec/system_prompt.md 的 prompt
        return DialogueIntentResult(
            intent_primary="query",
            intent_secondary="market_query",
            confidence=0.5,
            rationale="LLM 分类待实现",
        )
