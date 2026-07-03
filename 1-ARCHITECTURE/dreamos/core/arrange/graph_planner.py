"""
DreamOS A层 — 图规划器 (GraphPlanner)

A 层主入口，职责:
    1. 接收 S 层的 IntentResult
    2. 选择执行链路 (A/C/F)
    3. 节点选择 (NodeSelector)
    4. 预算分配 (BudgetAllocator)
    5. 构建执行图 (ExecutionGraph)
    6. 输出 ExecutionPlan

执行流程:
    IntentResult (from S层)
        ↓
    确定链路 (A/C/F)
        ↓
    NodeSelector 选节点
        ↓
    BudgetAllocator 分配预算
        ↓
    构建 ExecutionGraph
        ↓
    输出 ExecutionPlan → 写入 state.plan
        ↓
    返回 Graph (给 C 层执行)
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any

from dreamos.shared.state import State
from dreamos.shared.interfaces import Graph, Node
from dreamos.registry.node_registry import NodeRegistry, get_default_registry
from dreamos.shared.utils import Timer, safe_get

from .types import ExecutionPlan, NodeMeta, ChainSpec, BudgetAllocation, STANDARD_CHAINS, INTENT_CHAIN_MAP
from .node_selector import NodeSelector
from .budget_allocator import BudgetAllocator
from .execution_graph import SequentialGraph, ConditionalGraph


class GraphPlanner:
    """图规划器 — A 层主入口

    用法:
        planner = GraphPlanner()
        plan = planner.plan(state)
        # state.plan 已更新
        # plan.selected_nodes → 选中节点列表

    也可直接传入意图结果:
        plan = planner.plan_from_intent(
            intent_type="TREND_FOLLOWING",
            recommended_chain="A",
            base_chain=["A0", "A1", "A2"],
            confidence=0.72,
            budget_total=6000,
        )
    """

    def __init__(self,
                 registry: Optional[NodeRegistry] = None,
                 budget_total: int = 6000,
                 budget_mode: str = "standard"):
        self._registry = registry or get_default_registry()
        self._selector = NodeSelector(self._registry)
        self._budget_total = budget_total
        self._budget_mode = budget_mode

    def plan(self, state: State) -> ExecutionPlan:
        """根据 State 中的意图信息规划执行图

        Args:
            state: 全局状态（需包含 state.intent）

        Returns:
            ExecutionPlan: 执行计划
        """
        timer = Timer("graph_planner")

        # 从 state 中提取意图信息
        intent = state.intent or {}
        intent_type = intent.get("intent_type", "UNCERTAIN")
        recommended_chain = intent.get("recommended_chain", "A")
        base_chain = intent.get("base_chain", [])
        extend_nodes = intent.get("extend_nodes", [])
        confidence = intent.get("confidence", 0.0)

        # 如果没有推荐链，根据意图类型推断
        if not recommended_chain or recommended_chain == "":
            recommended_chain = self._infer_chain(intent_type)

        plan = self._build_plan(
            chain=recommended_chain,
            base_chain=base_chain,
            extend_nodes=extend_nodes,
            confidence=confidence,
        )

        # 写入 state
        state.plan = plan.to_dict()
        with timer:
            pass

        return plan

    def plan_from_intent(self,
                         intent_type: str = "UNCERTAIN",
                         recommended_chain: str = "A",
                         base_chain: Optional[List[str]] = None,
                         extend_nodes: Optional[List[str]] = None,
                         confidence: float = 0.5,
                         budget_total: Optional[int] = None,
                         budget_mode: Optional[str] = None) -> ExecutionPlan:
        """直接从意图参数构建执行计划（不依赖 State）"""
        if not recommended_chain:
            recommended_chain = self._infer_chain(intent_type)

        return self._build_plan(
            chain=recommended_chain,
            base_chain=base_chain,
            extend_nodes=extend_nodes,
            confidence=confidence,
            budget_total=budget_total,
            budget_mode=budget_mode,
        )

    def build_graph(self, plan: ExecutionPlan,
                    use_conditional: bool = False) -> Graph:
        """根据执行计划构建执行图

        Args:
            plan: 执行计划
            use_conditional: 是否使用条件图（支持跳转）

        Returns:
            Graph: 可执行的图
        """
        if use_conditional:
            graph = ConditionalGraph()
        else:
            graph = SequentialGraph()

        for meta in plan.selected_nodes:
            node = self._registry.get(meta.node_id)
            if node:
                graph.add_node(node)

        return graph

    # ── 内部方法 ───────────────────────────────────────

    def _build_plan(self,
                    chain: str,
                    base_chain: Optional[List[str]],
                    extend_nodes: Optional[List[str]],
                    confidence: float,
                    budget_total: Optional[int] = None,
                    budget_mode: Optional[str] = None) -> ExecutionPlan:
        """构建执行计划"""
        total = budget_total or self._budget_total
        mode = budget_mode or self._budget_mode

        # 选节点
        metas = self._selector.select(
            chain=chain,
            base_chain=base_chain,
            extend_nodes=extend_nodes,
            intent_confidence=confidence,
        )

        # 分配预算
        allocator = BudgetAllocator(total=total, mode=mode)
        allocation = allocator.allocate(metas)

        # 更新节点的分配预算
        for meta in metas:
            meta.allocated_tokens = allocation.get(meta.node_id)

        chain_spec = self._selector.get_chain_spec(chain)

        # 估算总消耗
        est_tokens = sum(m.allocated_tokens for m in metas)
        est_latency = sum(m.estimated_latency_ms for m in metas)

        return ExecutionPlan(
            planned_chain=chain,
            selected_nodes=metas,
            budget=allocation,
            chain_spec=chain_spec,
            rationale=self._build_rationale(chain, metas, confidence),
            estimated_total_tokens=est_tokens,
            estimated_total_latency_ms=est_latency,
        )

    def _infer_chain(self, intent_type: str) -> str:
        """根据意图类型推断链路

        使用 INTENT_CHAIN_MAP 映射:
            TREND_FOLLOWING / MEAN_REVERSION / UNCERTAIN → A 链 (执行环)
            FUNDAMENTAL_PLAY → F 链 (基本面)
            BREAKOUT / KNOWLEDGE_MATCH → C 链 (短线/突破)
        """
        return INTENT_CHAIN_MAP.get(intent_type, "A")

    def _build_rationale(self, chain: str, metas: List[NodeMeta],
                         confidence: float) -> str:
        chain_name = STANDARD_CHAINS.get(chain, STANDARD_CHAINS["A"]).name
        node_count = len(metas)
        required = sum(1 for m in metas if m.is_required)
        optional = node_count - required
        return (f"链路={chain}({chain_name})，"
                f"节点={node_count}(必须{required}+可选{optional})，"
                f"置信度={confidence:.0%}")
