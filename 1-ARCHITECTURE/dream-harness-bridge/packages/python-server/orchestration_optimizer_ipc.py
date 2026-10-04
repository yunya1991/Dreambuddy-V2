#!/usr/bin/env python3
"""orchestration_optimizer_ipc — A 层编排优化 subagent IPC handler

供 server.py 路由调用, 将 params 转发到 OrchestrationOptimizerAgent。
"""
import traceback
import sys
import os

# 确保 dreamos 路径可达
_dreamos_root = os.path.join(
    os.path.dirname(__file__), "..", "..", "1-ARCHITECTURE"
)
if _dreamos_root not in sys.path:
    sys.path.insert(0, _dreamos_root)

from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
    OrchestrationOptimizerAgent, PlanOptimization,
)


def handle_orchestration_optimizer(params: dict) -> dict:
    """IPC handler: A 层编排优化 subagent

    参数:
        plan: ExecutionPlan dict (planned_chain, selected_nodes, rationale 等)
        intent: 意图信息 (confidence, intent_type, complexity_tier)
        runtime_signals: 运行时信号

    返回:
        {ok: True, optimization: {...}} 或 {ok: False, error: ...}
    """
    try:
        plan_dict = params.get("plan", {})
        intent = params.get("intent", {})
        runtime_signals = params.get("runtime_signals", {})

        # 从 dict 构造轻量 proxy
        class _PlanProxy:
            def __init__(self, d):
                self.planned_chain = d.get("planned_chain", "")
                self.rationale = d.get("rationale", "")
                self.selected_nodes = d.get("selected_nodes", [])

        plan_proxy = _PlanProxy(plan_dict)
        agent = OrchestrationOptimizerAgent()  # 生产环境注入 llm_fn / cognitive_adapter
        result: PlanOptimization = agent.optimize(plan_proxy, intent, runtime_signals)
        return {
            "ok": True,
            "optimization": result.to_dict(),
        }
    except Exception as e:
        stack = traceback.format_exc()
        return {"ok": False, "error": str(e), "stack": stack}
