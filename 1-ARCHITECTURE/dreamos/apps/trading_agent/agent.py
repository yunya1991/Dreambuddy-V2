"""
Dreambuddy OS — Trading Agent 应用

将 S-A-C-G 四层内核串联为完整的交易 Agent：
    S (Sense)    → 意图识别：用户输入/市场数据 → 交易意图
    A (Arrange)  → 图编排：根据意图从注册表选节点、分配预算、构建执行图
    C (Compute)  → 执行：运行节点、反射决策、结果聚合
    G (GraphStore) → 存储：状态快照、历史记录、上下文压缩

用法:
    from dreamos.apps.trading_agent import TradingAgent

    agent = TradingAgent()
    result = agent.run(
        user_input="BTC 现在怎么看？",
        market_data={"price": 65000, "rsi14": 45, ...},
    )
    print(result["action"], result["confidence"])
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from dreamos.shared.state import State, new_state
from dreamos.shared.utils import gen_cycle_id

from dreamos.core.sense import IntentEngine, IntentResult
from dreamos.core.arrange import GraphPlanner, ExecutionPlan
from dreamos.core.compute import GraphExecutor, ExecutionReport
from dreamos.core.graph_store import GraphStore
from dreamos.budget import GlobalBudgetManager, CostTracker

from dreamos.registry import NodeRegistry, get_default_registry

from dreamos.nodes import register_all as register_trading_nodes


class TradingAgent:
    """交易 Agent — S-A-C-G 全链路编排

    核心职责:
        1. 接收用户输入 + 市场数据
        2. S 层识别意图
        3. A 层编排执行图
        4. C 层执行
        5. G 层持久化
        6. 返回最终结果

    设计:
        - 节点可插拔：通过 Registry 管理，新增节点不影响 Agent
        - 预算全局管控：GlobalBudgetManager 统一分配
        - 状态可追溯：GraphStore 保存每个周期的完整快照
        - 自我进化：历史数据驱动 Evolution 持续优化
    """

    def __init__(self,
                 registry: Optional[NodeRegistry] = None,
                 budget_mode: str = "standard",
                 auto_register: bool = True):
        self.registry = registry or get_default_registry()
        if auto_register:
            register_trading_nodes(self.registry)

        # 内核四层
        self.intent_engine = IntentEngine()
        self.graph_planner = GraphPlanner(registry=self.registry)
        self.graph_executor = GraphExecutor()
        self.graph_store = GraphStore()

        # 横切关注点
        self.budget = GlobalBudgetManager(mode=budget_mode)
        self.cost_tracker = CostTracker()

        # 统计
        self._cycle_count = 0

    def run(self,
            user_input: str = "",
            market_data: Optional[Dict[str, Any]] = None,
            context: Optional[Dict[str, Any]] = None,
            budget_mode: Optional[str] = None) -> Dict[str, Any]:
        """执行一次完整的交易分析周期

        Args:
            user_input: 用户自然语言输入
            market_data: 市场数据（价格/指标等）
            context: 额外上下文
            budget_mode: 临时覆盖预算模式

        Returns:
            交易决策结果字典:
            {
                "cycle_id": str,
                "intent": {...},
                "plan": {...},
                "execution": {...},
                "action": "LONG" | "SHORT" | "HOLD",
                "confidence": float,
                "rationale": [str],
                "tokens_used": int,
                "latency_ms": float,
            }
        """
        cycle_id = gen_cycle_id("trade")
        start_time = time.time()
        market_data = market_data or {}
        context = context or {}

        # ── 0. 预算开始 ────────────────────────
        self.budget.begin_cycle(cycle_id)

        # ── 1. S 层：意图识别 ─────────────────
        intent_result = self._sense(user_input, market_data, context)

        # ── 2. 构建 State ───────────────────
        state = new_state(cycle_id=cycle_id)
        state.inputs = {
            "user_input": user_input,
            "mkt": market_data,
            "context": context,
        }
        state.market_data = market_data  # type: ignore[attr-defined]
        state.intent = {
            "intent_type": intent_result.intent_type,
            "confidence": intent_result.confidence,
            "recommended_chain": intent_result.recommended_chain,
            "base_chain": getattr(intent_result, "base_chain", []),
            "extend_nodes": getattr(intent_result, "extend_nodes", []),
            "rationale": getattr(intent_result, "rationale", ""),
            "recognizer": getattr(intent_result, "recognizer", ""),
        }

        # ── 3. A 层：图编排 ──────────────────
        plan = self._arrange(intent_result, state)

        # ── 4. C 层：执行 ────────────────────
        report = self._compute(state, plan)

        # ── 5. G 层：存储 ────────────────────
        self._store(state, report)

        # ── 6. 预算结算 ──────────────────────
        total_tokens = getattr(report, "total_tokens", 0)
        self.budget.end_cycle(tokens_total=total_tokens,
                              status="success" if state.final_action else "degraded")

        # ── 7. 组装结果 ──────────────────────
        latency_ms = (time.time() - start_time) * 1000

        result = {
            "cycle_id": cycle_id,
            "intent": {
                "type": intent_result.intent_type,
                "confidence": intent_result.confidence,
                "recognizer": getattr(intent_result, "recognizer", ""),
            },
            "plan": {
                "chain": getattr(plan, "planned_chain", ""),
                "nodes": plan.node_ids if hasattr(plan, "node_ids") else [],
                "budget_allocated": getattr(plan.budget, "total", 0) if hasattr(plan, "budget") else 0,
            },
            "execution": {
                "nodes_executed": getattr(report, "executed_nodes", 0),
                "success_count": getattr(report, "success_nodes", 0),
                "total_tokens": total_tokens,
            },
            "action": getattr(report, "final_action", state.final_action or "HOLD"),
            "confidence": getattr(report, "final_confidence", state.final_confidence),
            "rationale": self._collect_rationale(state),
            "tokens_used": total_tokens,
            "latency_ms": round(latency_ms, 1),
            "budget_status": self.budget.status(),
        }

        self._cycle_count += 1
        return result

    # ── S 层 ────────────────────────────────

    def _sense(self, user_input: str, market_data: Dict,
               context: Dict) -> IntentResult:
        """S 层：意图识别"""
        return self.intent_engine.recognize(
            user_message=user_input,
            market=market_data,
            context=context,
        )

    # ── A 层 ────────────────────────────────

    def _arrange(self, intent: IntentResult, state: State) -> ExecutionPlan:
        """A 层：图编排"""
        return self.graph_planner.plan(state)

    # ── C 层 ────────────────────────────────

    def _compute(self, state: State, plan: ExecutionPlan) -> ExecutionReport:
        """C 层：执行图"""
        from dreamos.core.arrange.execution_graph import SequentialGraph

        graph = SequentialGraph()
        for meta in plan.selected_nodes:
            node = self.registry.get(meta.node_id)
            if node:
                graph.add_node(node)

        return self.graph_executor.execute(
            graph=graph,
            state=state,
            plan=plan,
        )

    # ── G 层 ────────────────────────────────

    def _store(self, state: State, report: ExecutionReport) -> None:
        """G 层：保存状态与历史"""
        # 保存检查点
        self.graph_store.checkpoint(state, node_id="__end__", metadata={"tag": "end_of_cycle"})

        # 记录历史
        self.graph_store.record(
            state=state,
            report={
                "total_tokens": getattr(report, "total_tokens", 0),
                "total_latency_ms": getattr(report, "total_latency_ms", 0),
                "success_rate": getattr(report, "success_rate", 0),
                "nodes_executed": getattr(report, "nodes_executed", 0),
            },
        )

    # ── 便捷方法 ────────────────────────────

    def _collect_rationale(self, state: State) -> List[str]:
        """从各节点结果中收集 rationale"""
        rationale = []
        results = state.results if state.results else {}
        for node_id, result in results.items():
            if hasattr(result, "outputs") and result.outputs:
                node_rationale = result.outputs.get("rationale", [])
                if isinstance(node_rationale, list):
                    rationale.extend(node_rationale)
                elif isinstance(node_rationale, str):
                    rationale.append(node_rationale)
        return rationale

    def analyze(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """纯市场数据分析（无用户输入）"""
        return self.run(
            user_input="",
            market_data=market_data,
        )

    def chat(self, message: str, market_data: Optional[Dict] = None) -> Dict[str, Any]:
        """对话式交易分析"""
        return self.run(
            user_input=message,
            market_data=market_data or {},
        )

    @property
    def cycle_count(self) -> int:
        """已执行的周期数"""
        return self._cycle_count

    def history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取历史记录"""
        entries = self.graph_store.query_history()[:limit]
        return [e.to_dict() for e in entries]

    def status(self) -> Dict[str, Any]:
        """Agent 状态"""
        summary = self.graph_store.summary()
        return {
            "cycles_executed": self._cycle_count,
            "registered_nodes": len(self.registry),
            "budget": self.budget.status(),
            "history_count": summary.get("history_count", 0),
            "checkpoint_count": summary.get("checkpoint_count", 0),
        }

    def __repr__(self) -> str:
        return (f"<TradingAgent cycles={self._cycle_count} "
                f"nodes={len(self.registry)} "
                f"budget={self.budget.level()}>")
