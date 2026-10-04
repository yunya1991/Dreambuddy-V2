#!/usr/bin/env python3
"""test_orchestration_optimizer_agent.py — A 层编排优化 subagent 测试

TDD RED 阶段：所有测试在实现前应 FAIL（ModuleNotFoundError）。
GREEN 阶段实现 orchestration_optimizer_agent.py 后全部通过。

覆盖：
  1. 模块导入（ModuleNotFoundError → GREEN 后通过）
  2. FAIL-OPEN：无 llm_fn → 规则降级（原 plan 透传）
  3. FAIL-OPEN：异常 → PlanOptimization(keep_static_fallback=True)
  4. 空 plan 处理
  5. LLM 优化正常路径：add_nodes + remove_nodes + reorder
  6. 认知闭环 recall + record 调用
  7. 低置信度触发优化 + 高置信度不触发
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))


def test_module_import():
    """测试 1: 模块可导入"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent, PlanOptimization
    )
    assert OrchestrationOptimizerAgent is not None
    assert PlanOptimization is not None


def test_fail_open_no_llm_fn():
    """测试 2: 无 llm_fn → 规则降级, 保持原 plan"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent, PlanOptimization
    )
    from dreamos.core.arrange.types import ExecutionPlan

    agent = OrchestrationOptimizerAgent()  # 无 llm_fn
    plan = ExecutionPlan(planned_chain="A", rationale="测试")
    optimization = agent.optimize(plan, intent={"confidence": 0.50}, runtime_signals={})
    assert isinstance(optimization, PlanOptimization)
    assert optimization.keep_static_fallback is True


def test_fail_open_exception():
    """测试 3: LLM 异常 → FAIL-OPEN 返回安全默认"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent, PlanOptimization
    )
    from dreamos.core.arrange.types import ExecutionPlan

    def bad_llm(prompt: str) -> str:
        raise RuntimeError("LLM service down")

    agent = OrchestrationOptimizerAgent(llm_fn=bad_llm)
    plan = ExecutionPlan(planned_chain="A", rationale="测试")
    optimization = agent.optimize(plan, intent={"confidence": 0.50}, runtime_signals={})
    assert isinstance(optimization, PlanOptimization)
    assert optimization.keep_static_fallback is True


def test_empty_plan():
    """测试 4: 空 plan → 返回安全默认"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent, PlanOptimization
    )
    from dreamos.core.arrange.types import ExecutionPlan

    agent = OrchestrationOptimizerAgent()
    plan = ExecutionPlan()
    optimization = agent.optimize(plan, intent={"confidence": 0.50}, runtime_signals={})
    assert isinstance(optimization, PlanOptimization)
    assert optimization.keep_static_fallback is True


def test_llm_optimization_normal_path():
    """测试 5: LLM 正常优化路径"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent, PlanOptimization
    )
    from dreamos.core.arrange.types import ExecutionPlan

    def mock_llm(prompt: str) -> str:
        import json
        return json.dumps({
            "add_nodes": ["A6", "A7"],
            "remove_nodes": ["A8"],
            "reorder": {"A1": 1, "A2": 2, "A3": 3},
            "budget_adjustment": {"A6": 500},
            "reasoning": "低置信度, 增加情报和验证节点"
        })

    agent = OrchestrationOptimizerAgent(llm_fn=mock_llm)
    plan = ExecutionPlan(planned_chain="A", rationale="默认编排")
    optimization = agent.optimize(
        plan,
        intent={"confidence": 0.55, "intent_type": "trend_following", "complexity_tier": "T2"},
        runtime_signals={"data_quality": "moderate"},
    )
    assert isinstance(optimization, PlanOptimization)
    assert "A6" in optimization.add_nodes
    assert "A7" in optimization.add_nodes
    assert "A8" in optimization.remove_nodes
    assert optimization.reorder is not None
    assert optimization.reorder.get("A1") == 1
    assert optimization.keep_static_fallback is False


def test_cognitive_recall_record():
    """测试 6: 认知闭环 recall + record 调用"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent, PlanOptimization
    )
    from dreamos.core.arrange.types import ExecutionPlan

    class MockCognitive:
        def __init__(self):
            self.recalled = []
            self.recorded = []

        def recall(self, context, top_k=5, min_quality="C"):
            self.recalled.append(context)
            return [{"content": "历史编排经验", "score": 0.8}]

        def record(self, content, tags="", quality_level="C"):
            self.recorded.append({"content": content, "tags": tags, "quality_level": quality_level})

    cog = MockCognitive()

    def mock_llm(prompt: str) -> str:
        import json
        return json.dumps({
            "add_nodes": [],
            "remove_nodes": [],
            "reorder": None,
            "budget_adjustment": None,
            "reasoning": "无需调整"
        })

    agent = OrchestrationOptimizerAgent(llm_fn=mock_llm, cognitive_adapter=cog)
    plan = ExecutionPlan(planned_chain="A", rationale="默认编排")
    agent.optimize(
        plan,
        intent={"confidence": 0.55, "intent_type": "trend_following"},
        runtime_signals={},
    )

    assert len(cog.recalled) >= 1
    assert len(cog.recorded) >= 1
    assert "A层" in cog.recorded[0]["tags"] or "编排优化" in cog.recorded[0]["tags"]


def test_low_confidence_triggers_optimization():
    """测试 7: 低置信度触发优化, 高置信度不触发"""
    from dreamos.core.arrange.optimizers.orchestration_optimizer_agent import (
        OrchestrationOptimizerAgent
    )
    from dreamos.core.arrange.types import ExecutionPlan

    call_count = {"llm": 0}

    def mock_llm(prompt: str) -> str:
        call_count["llm"] += 1
        import json
        return json.dumps({"add_nodes": [], "remove_nodes": [], "reasoning": "noop"})

    agent = OrchestrationOptimizerAgent(llm_fn=mock_llm)

    # 低置信度 → 应调用 LLM
    plan = ExecutionPlan(planned_chain="A")
    agent.optimize(plan, intent={"confidence": 0.50}, runtime_signals={})
    assert call_count["llm"] >= 1

    # 高置信度 → 不应调用 LLM
    call_count["llm"] = 0
    plan2 = ExecutionPlan(planned_chain="A")
    result = agent.optimize(plan2, intent={"confidence": 0.85}, runtime_signals={})
    assert call_count["llm"] == 0
    assert result.keep_static_fallback is True
