"""
能力路由决策

根据对话意图决定路由到哪个系统能力。
属于 DreamOS 操作系统内核 S 层。

能力路由选项:
    - knowledge_base    知识库查询（2-KNOWLEDGE/）
    - cognitive_memory  认知系统/记忆（4-MEMORY/）
    - index_system      索引检索（2-KNOWLEDGE/0-SCHEMA/）
    - database          直接数据查询
    - trading_nodes     交易节点编排（经典指标系统 + 四大子交易系统）
    - harness           超出范围，交 Harness 驱动外部 agent 调研
    - direct_response   直接响应（对话类意图）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .dialogue_intent.taxonomy import (
    get_default_capability_route,
    get_risk_level,
)


# ============================================================
# 能力路由描述
# ============================================================

CAPABILITY_DESCRIPTIONS: Dict[str, Dict[str, str]] = {
    "knowledge_base": {
        "name": "知识库",
        "path": "2-KNOWLEDGE/",
        "description": "交易策略、方法论、理论知识库",
    },
    "cognitive_memory": {
        "name": "认知系统",
        "path": "4-MEMORY/",
        "description": "认知记忆、贝叶斯记忆、经验沉淀",
    },
    "index_system": {
        "name": "索引系统",
        "path": "2-KNOWLEDGE/0-SCHEMA/",
        "description": "三级索引快速检索",
    },
    "database": {
        "name": "数据库",
        "path": "JSON/SQLite",
        "description": "行情、持仓、订单等结构化数据",
    },
    "trading_nodes": {
        "name": "交易节点编排",
        "path": "capabilities/trading/nodes/",
        "description": "经典指标系统 + 四大子交易系统（核心护城河）",
    },
    "harness": {
        "name": "Harness 外部调研",
        "path": "dream-harness-bridge/",
        "description": "超出 DreamOS 能力范围，交 Harness 驱动外部 agent 调研",
    },
    "direct_response": {
        "name": "直接响应",
        "path": "对话状态管理",
        "description": "对话类意图直接响应，无需调用能力",
    },
}


# ============================================================
# Harness 工具选择策略
# ============================================================

# 意图二级 → Harness 工具选择
HARNESS_TOOL_STRATEGY: Dict[str, str] = {
    # 交易调研 → 6-TRADING SKILL
    "technical_analysis": "trading_skills",
    "deep_analysis": "trading_skills",
    "three_screen_analysis": "trading_skills",
    # 策略开发 → Superpowers
    "strategy_design": "superpowers",
    "strategy_optimization": "superpowers",
    "factor_screen": "superpowers",
    # 通用 → 大模型 + 认知系统
    "market_query": "llm_memory",
    "chitchat": "llm_memory",
}

HARNESS_TOOL_DESCRIPTIONS: Dict[str, str] = {
    "trading_skills": "6-TRADING SKILL 合集（矛盾论/三屏/策略研究/风控/回测/离场/情报/治理）",
    "superpowers": "Superpowers 策略开发框架（specs/plans/research/contracts/元技能）",
    "llm_memory": "大模型能力 + 认知系统直接决策",
}


# ============================================================
# 能力路由器
# ============================================================

class CapabilityRouter:
    """能力路由器

    根据对话意图和槽位，决定路由到哪个系统能力。
    """

    def route(self, intent_primary: str, intent_secondary: str,
              slots: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """路由决策

        Args:
            intent_primary: 一级意图
            intent_secondary: 二级意图
            slots: 槽位

        Returns:
            路由决策结果
        """
        slots = slots or {}

        # 1. 获取默认路由
        route = get_default_capability_route(intent_primary)
        risk_level = get_risk_level(intent_primary)

        # 2. 根据二级意图和槽位细化路由
        route = self._refine_route(intent_primary, intent_secondary, slots, route)

        # 3. 判断是否在能力范围内
        in_scope = self._check_scope(intent_primary, intent_secondary, slots)
        if not in_scope:
            route = "harness"

        # 4. 如果路由到 harness，决定使用哪个工具
        harness_tool = None
        if route == "harness":
            harness_tool = self._select_harness_tool(intent_secondary)

        return {
            "capability_route": route,
            "in_scope": in_scope,
            "risk_level": risk_level,
            "harness_tool": harness_tool,
            "description": CAPABILITY_DESCRIPTIONS.get(route, {}).get("description", ""),
        }

    def _refine_route(self, primary: str, secondary: str,
                      slots: Dict[str, Any], default_route: str) -> str:
        """根据具体意图和槽位细化路由"""
        # 对话类直接响应
        if primary == "dialog":
            return "direct_response"

        # 查询类：根据查询内容选择
        if primary == "query":
            if secondary in ("holding_query", "order_query", "account_query"):
                return "database"
            if secondary == "market_overview":
                return "index_system"
            return default_route

        # 分析类：有知识库关键词走知识库，否则走交易节点
        if primary == "analysis":
            if "知识" in str(slots) or "历史" in str(slots):
                return "knowledge_base"
            return "trading_nodes"

        # 策略类：策略设计走 Superpowers（通过 harness），其他走交易节点
        if primary == "strategy":
            if secondary in ("strategy_design", "strategy_optimization"):
                # 复杂策略开发可以交给 harness + superpowers
                return "harness"
            return "trading_nodes"

        # 风险类：组合风险走认知系统，其他走交易节点
        if primary == "risk":
            if secondary == "portfolio_risk":
                return "cognitive_memory"
            return "trading_nodes"

        return default_route

    def _check_scope(self, primary: str, secondary: str,
                     slots: Dict[str, Any]) -> bool:
        """判断是否在 DreamOS 能力范围内"""
        # 当前所有意图都在范围内
        # 未来可根据具体意图和槽位判断
        return True

    def _select_harness_tool(self, secondary: str) -> str:
        """选择 Harness 工具"""
        return HARNESS_TOOL_STRATEGY.get(secondary, "llm_memory")


# 全局路由器实例
router = CapabilityRouter()


def route_capability(intent_primary: str, intent_secondary: str,
                     slots: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """便捷函数：能力路由决策"""
    return router.route(intent_primary, intent_secondary, slots)
