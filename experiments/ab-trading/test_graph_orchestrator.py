#!/usr/bin/env python3
"""
A层 + C层 图编排引擎测试

位置: experiments/ab-trading/test_graph_orchestrator.py

测试内容:
1. A层 - 图编排引擎 (GraphOrchestrator)
   - 顺序执行
   - 并行执行
   - 混合执行
   - 依赖管理
   - 错误处理

2. C层 - 节点执行器 (NodeExecutor)
   - 基本执行
   - 降级容错

3. C层 - 结果聚合器 (ResultAggregator)
   - 加权聚合
   - 投票聚合
"""

import sys
import unittest
import os
from typing import Dict, Any, List

# 添加 ab-trading 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.intent_engine.types import ExecutionBlueprint

from core.a_graph_orchestrator import (
    GraphOrchestrator,
    ExecutionStrategy,
    GraphExecutionResult,
)
from core.shared.interfaces import NodeExecutionStatus

from core.c_execution_layer import (
    SimpleNodeExecutor,
    ResultAggregator,
    NodeExecutionResult as CNodeResult,
    NodeStatus,
    aggregate_results,
)


# ============================================================
# 测试工具
# ============================================================

def create_simple_blueprint(
    node_ids: List[str],
    execution_mode: str = "sequential",
    dependencies: Dict[str, List[str]] = None,
    parallel_groups: List[List[str]] = None,
) -> ExecutionBlueprint:
    """创建简单的测试蓝图"""
    blueprint = ExecutionBlueprint()
    blueprint.blueprint_id = "test_bp_001"
    blueprint.objective_id = "test_obj_001"
    blueprint.node_sequence = node_ids
    blueprint.execution_mode = execution_mode
    blueprint.dependencies = dependencies or {}
    blueprint.okr_mode = "single"
    blueprint.complexity = "simple"
    blueprint.kr_to_nodes = {f"kr_{i}": [nid] for i, nid in enumerate(node_ids)}
    blueprint.node_to_kr = {nid: f"kr_{i}" for i, nid in enumerate(node_ids)}
    blueprint.parallel_groups = parallel_groups or []
    return blueprint


# ============================================================
# A层测试
# ============================================================

class TestGraphOrchestratorSequential(unittest.TestCase):
    """测试顺序执行"""

    def setUp(self):
        """设置测试"""
        self.executor = SimpleNodeExecutor()

        # 注册测试节点
        def node_a(inputs, ctx):
            return {"result": "A完成", "value": 10}

        def node_b(inputs, ctx):
            prev = inputs.get("previous_output", {}).get("value", 0)
            return {"result": "B完成", "value": prev + 20}

        def node_c(inputs, ctx):
            prev = inputs.get("previous_output", {}).get("value", 0)
            return {"result": "C完成", "value": prev + 30}

        self.executor.register_handler("node_a", node_a)
        self.executor.register_handler("node_b", node_b)
        self.executor.register_handler("node_c", node_c)

        self.orchestrator = GraphOrchestrator(self.executor)

    def test_sequential_execution(self):
        """测试顺序执行"""
        blueprint = create_simple_blueprint(
            ["node_a", "node_b", "node_c"],
            execution_mode="sequential",
        )

        result = self.orchestrator.execute(blueprint)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.completed_nodes, 3)
        self.assertEqual(result.failed_nodes, 0)

        # 验证节点顺序执行
        completed_order = [
            status.node_id for status in result.node_statuses.values()
            if status.status == "completed"
        ]
        self.assertEqual(completed_order, ["node_a", "node_b", "node_c"])

        # 验证值传递
        node_b_status = result.get_node_status("node_b")
        self.assertIsNotNone(node_b_status.result)
        self.assertEqual(node_b_status.result.get("value"), 30)  # 10 + 20

    def test_sequential_with_failure(self):
        """测试顺序执行中的节点失败"""

        def failing_node(inputs, ctx):
            raise Exception("节点执行失败")

        self.executor.register_handler("failing_node", failing_node)

        blueprint = create_simple_blueprint(
            ["node_a", "failing_node", "node_c"],
            execution_mode="sequential",
        )

        # 默认策略：失败后继续
        result = self.orchestrator.execute(blueprint)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.completed_nodes, 2)  # node_a 和 node_c（failing_node失败了）
        self.assertEqual(result.failed_nodes, 1)  # failing_node

    def test_sequential_stop_on_failure(self):
        """测试失败停止策略"""
        strategy = ExecutionStrategy(stop_on_first_failure=True)

        def failing_node(inputs, ctx):
            raise Exception("节点执行失败")

        self.executor.register_handler("failing_node", failing_node)

        orchestrator = GraphOrchestrator(self.executor, strategy)

        blueprint = create_simple_blueprint(
            ["node_a", "failing_node", "node_c"],
            execution_mode="sequential",
        )

        result = orchestrator.execute(blueprint)

        self.assertEqual(result.status, "partial")
        self.assertEqual(result.completed_nodes, 1)
        # node_c应该被跳过
        node_c_status = result.get_node_status("node_c")
        self.assertEqual(node_c_status.status, "skipped")


class TestGraphOrchestratorParallel(unittest.TestCase):
    """测试并行执行"""

    def setUp(self):
        self.executor = SimpleNodeExecutor()

        def node_x(inputs, ctx):
            return {"result": "X完成"}

        def node_y(inputs, ctx):
            return {"result": "Y完成"}

        def node_z(inputs, ctx):
            return {"result": "Z完成"}

        self.executor.register_handler("node_x", node_x)
        self.executor.register_handler("node_y", node_y)
        self.executor.register_handler("node_z", node_z)

        self.orchestrator = GraphOrchestrator(self.executor)

    def test_parallel_execution(self):
        """测试并行执行"""
        blueprint = create_simple_blueprint(
            ["node_x", "node_y", "node_z"],
            execution_mode="parallel",
            parallel_groups=[["node_x", "node_y", "node_z"]],
        )

        result = self.orchestrator.execute(blueprint)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.completed_nodes, 3)
        self.assertEqual(result.execution_mode, "parallel")


class TestGraphOrchestratorHybrid(unittest.TestCase):
    """测试混合执行"""

    def setUp(self):
        self.executor = SimpleNodeExecutor()

        def node_a(inputs, ctx):
            return {"result": "A完成"}

        def node_b(inputs, ctx):
            return {"result": "B完成"}

        def node_c(inputs, ctx):
            return {"result": "C完成"}

        self.executor.register_handler("node_a", node_a)
        self.executor.register_handler("node_b", node_b)
        self.executor.register_handler("node_c", node_c)

        self.orchestrator = GraphOrchestrator(self.executor)

    def test_hybrid_execution(self):
        """测试混合执行"""
        # hybrid模式：先执行node_a，然后node_b和node_c并行
        blueprint = create_simple_blueprint(
            ["node_a", "node_b", "node_c"],
            execution_mode="hybrid",
            parallel_groups=[["node_a"], ["node_b", "node_c"]],
        )

        result = self.orchestrator.execute(blueprint)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.completed_nodes, 3)
        self.assertEqual(result.execution_mode, "hybrid")


# ============================================================
# C层测试
# ============================================================

class TestResultAggregator(unittest.TestCase):
    """测试结果聚合器"""

    def test_weighted_aggregation(self):
        """测试加权聚合"""
        results = [
            CNodeResult(node_id="n1", confidence=0.8, outputs={"value": 10}),
            CNodeResult(node_id="n2", confidence=0.6, outputs={"value": 20}),
            CNodeResult(node_id="n3", confidence=0.9, outputs={"value": 30}),
        ]

        for r in results:
            r.mark_completed(r.outputs)

        aggregated = aggregate_results(results, mode="weighted")

        self.assertIsNotNone(aggregated.aggregated_output)
        # 加权平均：10*0.8 + 20*0.6 + 30*0.9 / (0.8+0.6+0.9) ≈ 19.1
        self.assertGreater(aggregated.aggregated_output["value"], 15)
        self.assertLess(aggregated.aggregated_output["value"], 25)

    def test_max_aggregation(self):
        """测试最大值聚合"""
        results = [
            CNodeResult(node_id="n1", confidence=0.5, outputs={"direction": "bullish"}),
            CNodeResult(node_id="n2", confidence=0.9, outputs={"direction": "bearish"}),
            CNodeResult(node_id="n3", confidence=0.6, outputs={"direction": "bullish"}),
        ]

        for r in results:
            r.mark_completed(r.outputs)

        aggregated = aggregate_results(results, mode="voting")

        # 投票结果应该是bullish（2票）
        self.assertEqual(aggregated.final_decision, "bullish")

    def test_empty_results(self):
        """测试空结果"""
        aggregated = aggregate_results([], mode="weighted")
        self.assertIsNotNone(aggregated.rationale)


# ============================================================
# 集成测试
# ============================================================

class TestIntegration(unittest.TestCase):
    """集成测试：S层 + A层 + C层"""

    def test_s_to_a_to_c_flow(self):
        """测试完整流程"""
        # 1. 创建简化蓝图（模拟S层输出）
        blueprint = create_simple_blueprint(
            ["analysis_node", "decision_node"],
            execution_mode="sequential",
        )

        # 2. 创建C层执行器
        executor = SimpleNodeExecutor()

        def analysis_handler(inputs, ctx):
            return {
                "trend": "bullish",
                "confidence": 0.85,
                "indicators": {"rsi": 45, "macd": "金叉"},
            }

        def decision_handler(inputs, ctx):
            prev = inputs.get("previous_output", {})
            trend = prev.get("trend", "neutral")
            return {
                "action": "BUY" if trend == "bullish" else "WAIT",
                "confidence": prev.get("confidence", 0.5),
            }

        executor.register_handler("analysis_node", analysis_handler)
        executor.register_handler("decision_node", decision_handler)

        # 3. A层编排执行
        orchestrator = GraphOrchestrator(executor)
        result = orchestrator.execute(blueprint)

        # 4. 验证结果
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.completed_nodes, 2)

        # 验证决策正确
        decision_result = result.get_node_status("decision_node").result
        self.assertEqual(decision_result["action"], "BUY")


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
