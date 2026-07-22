"""
Dream OS — 能力域路由器 (CapabilityRouter)

S层意图识别 → 能力域选择 → A层编排 的关键桥梁。

根据 IntentResult 中的意图类型和关键词，从 CapabilityRegistry 中选择最优能力域，
并生成路由决策（RoutingResult），供 A 层的 GraphPlanner 使用。

设计原则:
    - 路由决策可追踪: 记录选择理由、匹配置信度、候选列表
    - 支持多级降级: 精确匹配 → 模糊匹配 → 默认能力域
    - 与内核解耦: 只依赖 CapabilityRegistry，不依赖具体能力域
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

from dreamos.core.sense.types import IntentResult
from .registry import CapabilityRegistry, CapabilityDomain


@dataclass
class RoutingResult:
    """能力域路由结果

    由 CapabilityRouter 生成，传递给 A 层 GraphPlanner 作为编排依据。
    """
    # 选中的能力域
    selected_capability: Optional[CapabilityDomain] = None
    capability_id: Optional[str] = None

    # 匹配信息
    match_score: float = 0.0           # 匹配置信度 (0.0 ~ 1.0)
    match_type: str = "none"           # 匹配类型: exact / fuzzy / fallback / none

    # 候选列表（用于调试和追踪）
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    # 路由决策理由
    rationale: str = ""

    # 能力域配置（合并到 ExecutionPlan 中）
    capability_config: Dict[str, Any] = field(default_factory=dict)

    # 是否成功路由
    success: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "match_score": self.match_score,
            "match_type": self.match_type,
            "candidates": self.candidates,
            "rationale": self.rationale,
            "success": self.success,
        }


class CapabilityRouter:
    """能力域路由器 — 意图到能力域的映射器

    用法:
        router = CapabilityRouter(capability_registry)

        intent = IntentResult(intent_type="TREND_FOLLOWING", confidence=0.72)
        routing = router.route(intent)

        if routing.success:
            print(f"选择能力域: {routing.capability_id} (置信度: {routing.match_score})")
        else:
            print(f"未匹配到能力域，候选: {routing.candidates}")
    """

    def __init__(self, registry: CapabilityRegistry,
                 default_capability_id: Optional[str] = None):
        self.registry = registry
        self.default_capability_id = default_capability_id

    # ── 核心路由方法 ──────────────────────────────

    def route(self, intent_result: IntentResult) -> RoutingResult:
        """根据意图结果选择最优能力域

        路由策略（按优先级）:
            1. 精确匹配: intent_type 在能力域的 supported_intents 中
            2. 关键词匹配: intent 关键词与能力域 tags 匹配
            3. 默认回退: 使用默认能力域（如交易能力域）
            4. 失败: 无匹配能力域

        Args:
            intent_result: S层意图识别结果

        Returns:
            RoutingResult 路由决策
        """
        intent_type = getattr(intent_result, "intent_type", "")
        keywords = self._extract_keywords(intent_result)

        # 1. 精确匹配
        candidates = self.registry.find_by_intent(intent_type, keywords=keywords)

        if candidates:
            best_cap, best_score = candidates[0]

            # 判断匹配类型
            if intent_type in getattr(best_cap, "supported_intents", []):
                match_type = "exact"
            else:
                match_type = "fuzzy"

            return RoutingResult(
                selected_capability=best_cap,
                capability_id=best_cap.capability_id,
                match_score=best_score,
                match_type=match_type,
                candidates=[
                    {"id": c.capability_id, "name": c.name, "score": s}
                    for c, s in candidates[:3]
                ],
                rationale=f"意图 '{intent_type}' 匹配到能力域 '{best_cap.name}' (score={best_score:.2f})",
                capability_config=getattr(best_cap, "get_config", lambda: {})(),
                success=True,
            )

        # 2. 默认回退
        if self.default_capability_id:
            default_cap = self.registry.get(self.default_capability_id)
            if default_cap:
                return RoutingResult(
                    selected_capability=default_cap,
                    capability_id=default_cap.capability_id,
                    match_score=0.3,
                    match_type="fallback",
                    candidates=[],
                    rationale=f"意图 '{intent_type}' 无精确匹配，回退到默认能力域 '{default_cap.name}'",
                    capability_config=getattr(default_cap, "get_config", lambda: {})(),
                    success=True,
                )

        # 3. 完全失败
        return RoutingResult(
            match_score=0.0,
            match_type="none",
            rationale=f"意图 '{intent_type}' 未匹配到任何能力域，且无默认能力域",
            success=False,
        )

    # ── 便捷方法 ──────────────────────────────────

    def route_trading(self, intent_result: IntentResult) -> RoutingResult:
        """强制路由到交易能力域（用于交易系统场景）

        Dream OS 交易系统的入口: 意图明确为交易时，直接选择交易能力域。
        """
        trading_cap = self.registry.get("trading")
        if trading_cap:
            return RoutingResult(
                selected_capability=trading_cap,
                capability_id="trading",
                match_score=1.0,
                match_type="exact",
                rationale="交易系统强制路由到交易能力域",
                capability_config=getattr(trading_cap, "get_config", lambda: {})(),
                success=True,
            )
        return self.route(intent_result)

    # ── 内部工具 ──────────────────────────────────

    def _extract_keywords(self, intent_result: IntentResult) -> List[str]:
        """从意图结果中提取关键词"""
        keywords: List[str] = []

        # 从 user_message 提取（如果有）
        user_msg = getattr(intent_result, "user_message", "")
        if user_msg:
            keywords.extend(user_msg.lower().split())

        # 从 rationale 提取
        rationale = getattr(intent_result, "rationale", "")
        if rationale:
            keywords.extend(rationale.lower().split())

        return keywords

    def __repr__(self) -> str:
        return (f"<CapabilityRouter "
                f"registry={len(self.registry)} "
                f"default={self.default_capability_id}>")
