#!/usr/bin/env python3
"""
C层 - 动态链融合测试

位置: experiments/ab-trading/test_dynamic_chain_fusion.py

测试内容：
1. LLM结果分析器 - 规则分析
2. 动态决策器 - 规则决策
3. 动态重规划器 - 规则重规划
4. 执行反思进化器 - 规则反思
5. 融合编排器 - 端到端流程
"""

import sys
import os
import unittest
from typing import Dict, Any, List

# 添加路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.c_execution_layer import (
    NodeExecutionResult,
    NodeStatus,
    LLMResultAnalyzer,
    ResultAnalysis,
    DynamicDecisionMaker,
    DynamicReplanner,
    ReplanningResult,
    ExecutionReflector,
    ExecutionReflection,
    FusionOrchestrator,
)

from core.intent_engine.types import ExecutionBlueprint


# ============================================================
# 测试工具
# ============================================================

def make_node_result(
    node_id: str,
    success: bool = True,
    confidence: float = 0.8,
    outputs: Dict = None,
    error: str = None,
) -> NodeExecutionResult:
    """创建测试用节点结果"""
    result = NodeExecutionResult(node_id=node_id, confidence=confidence)
    if success:
        result.mark_completed(outputs or {"result": "success"})
    else:
        result.mark_failed(error or "测试错误")
    return result


def make_test_blueprint(node_ids: List[str]) -> ExecutionBlueprint:
    """创建测试蓝图"""
    bp = ExecutionBlueprint()
    bp.blueprint_id = "test_bp"
    bp.objective_id = "test_obj"
    bp.node_sequence = node_ids
    bp.execution_mode = "sequential"
    bp.dependencies = {}
    bp.okr_mode = "single"
    bp.complexity = "standard"
    return bp


# ============================================================
# LLM结果分析器测试
# ============================================================

class TestLLMResultAnalyzer(unittest.TestCase):
    """测试LLM结果分析器（规则模式）"""

    def setUp(self):
        self.analyzer = LLMResultAnalyzer(use_llm=False)

    def test_successful_node_analysis(self):
        """测试成功节点的分析"""
        result = make_node_result(
            "tech_analysis",
            confidence=0.85,
            outputs={
                "trend": "bullish",
                "rsi": 55,
                "macd": "golden_cross",
                "confidence": 0.82,
            },
        )

        analysis = self.analyzer.analyze(result)

        self.assertEqual(analysis.node_id, "tech_analysis")
        self.assertGreater(analysis.quality_score, 0)
        self.assertTrue(analysis.is_acceptable)

    def test_empty_output_analysis(self):
        """测试空输出的分析"""
        result = make_node_result("empty_node", confidence=0.5)
        result.outputs = {}  # 直接设置为空dict

        analysis = self.analyzer.analyze(result)

        self.assertFalse(analysis.is_acceptable)
        self.assertTrue(len(analysis.issues) > 0)

    def test_failed_node_analysis(self):
        """测试失败节点的分析"""
        result = make_node_result(
            "failed_node",
            success=False,
            error="网络超时",
        )

        analysis = self.analyzer.analyze(result)

        self.assertEqual(analysis.quality_score, 0.0)
        self.assertFalse(analysis.is_acceptable)
        self.assertIn("失败", analysis.summary)

    def test_low_confidence_analysis(self):
        """测试低置信度的分析"""
        result = make_node_result(
            "low_conf_node",
            confidence=0.2,
            outputs={"result": "uncertain"},
        )

        analysis = self.analyzer.analyze(result)

        self.assertFalse(analysis.is_acceptable)
        self.assertTrue(any("置信度" in issue for issue in analysis.issues))


# ============================================================
# 动态决策器测试
# ============================================================

class TestDynamicDecisionMaker(unittest.TestCase):
    """测试动态决策器（规则模式）"""

    def setUp(self):
        self.decision_maker = DynamicDecisionMaker(
            use_llm=False,
            quality_threshold=0.6,
            replan_threshold=0.3,
        )

    def _make_analysis(self, quality: float, is_acceptable: bool = True) -> ResultAnalysis:
        analysis = ResultAnalysis(node_id="test_node")
        analysis.quality_score = quality
        analysis.is_acceptable = is_acceptable
        analysis.completeness = quality
        analysis.consistency = quality
        analysis.relevance = quality
        return analysis

    def test_continue_decision(self):
        """测试继续决策（高质量结果）"""
        node_result = make_node_result("node_a", confidence=0.9)
        analysis = self._make_analysis(0.85)
        available = ["node_a", "node_b", "node_c"]

        decision = self.decision_maker.decide(node_result, analysis, available)

        self.assertEqual(decision.action, "continue")
        self.assertEqual(decision.next_node_id, "node_b")
        self.assertGreater(decision.confidence, 0)

    def test_retry_decision(self):
        """测试重试决策（中等质量结果）"""
        node_result = make_node_result("node_a", confidence=0.7)
        analysis = self._make_analysis(0.45, is_acceptable=False)
        analysis.issues = ["信息不完整"]
        available = ["node_a", "node_b"]

        decision = self.decision_maker.decide(node_result, analysis, available)

        self.assertEqual(decision.action, "retry")
        self.assertIsNotNone(decision.retry_params)

    def test_replan_decision_low_quality(self):
        """测试重规划决策（低质量结果）"""
        node_result = make_node_result("node_a", confidence=0.5)
        analysis = self._make_analysis(0.2, is_acceptable=False)
        analysis.issues = ["严重质量问题"]
        available = ["node_a", "node_b"]

        decision = self.decision_maker.decide(node_result, analysis, available)

        self.assertEqual(decision.action, "replan")
        self.assertTrue(decision.replan_required)

    def test_replan_decision_failed_node(self):
        """测试失败节点的重规划决策"""
        node_result = make_node_result("failed_node", success=False, error="超时")
        analysis = self._make_analysis(0.0, is_acceptable=False)
        available = ["failed_node", "next_node"]

        decision = self.decision_maker.decide(node_result, analysis, available)

        self.assertTrue(decision.replan_required)

    def test_contradiction_triggers_retry(self):
        """测试矛盾触发重试"""
        node_result = make_node_result("node_a", confidence=0.7)
        analysis = self._make_analysis(0.65)
        analysis.contradictions = ["技术面和基本面矛盾"]
        available = ["node_a", "node_b"]

        decision = self.decision_maker.decide(node_result, analysis, available)

        self.assertEqual(decision.action, "retry")


# ============================================================
# 动态重规划器测试
# ============================================================

class TestDynamicReplanner(unittest.TestCase):
    """测试动态重规划器"""

    def setUp(self):
        self.replanner = DynamicReplanner(max_replans=3, use_llm=False)

    def test_replan_skip_failed_node(self):
        """测试重规划跳过失败节点"""
        blueprint = make_test_blueprint(["node_a", "node_b", "node_c"])
        history = [make_node_result("node_a")]

        result = self.replanner.replan(
            blueprint,
            failed_node_id="node_b",
            reason="节点执行失败",
            execution_history=history,
        )

        self.assertTrue(result.success)
        self.assertIn("node_b", result.removed_nodes)
        self.assertIsNotNone(result.new_blueprint)
        self.assertNotIn("node_b", result.new_blueprint.node_sequence)

    def test_max_replans_limit(self):
        """测试重规划次数限制"""
        blueprint = make_test_blueprint(["n1", "n2", "n3"])
        history = []

        for i in range(3):
            result = self.replanner.replan(
                blueprint, f"node_{i}", "测试", history
            )
            if result.new_blueprint:
                blueprint = result.new_blueprint

        # 第4次应该失败
        result = self.replanner.replan(
            blueprint, "node_x", "测试", history
        )

        self.assertFalse(result.success)
        self.assertTrue(result.max_replans_reached)

    def test_can_replan_property(self):
        """测试can_replan属性"""
        self.assertTrue(self.replanner.can_replan)
        self.assertEqual(self.replanner.replan_count, 0)

        blueprint = make_test_blueprint(["n1", "n2"])
        self.replanner.replan(blueprint, "n1", "test", [])

        self.assertEqual(self.replanner.replan_count, 1)
        self.assertTrue(self.replanner.can_replan)

    def test_reset(self):
        """测试重置"""
        blueprint = make_test_blueprint(["n1", "n2"])
        self.replanner.replan(blueprint, "n1", "test", [])
        self.assertEqual(self.replanner.replan_count, 1)

        self.replanner.reset()
        self.assertEqual(self.replanner.replan_count, 0)
        self.assertTrue(self.replanner.can_replan)


# ============================================================
# 执行反思进化器测试
# ============================================================

class TestExecutionReflector(unittest.TestCase):
    """测试执行反思进化器"""

    def setUp(self):
        self.reflector = ExecutionReflector(use_llm=False)

    def test_reflect_all_success(self):
        """测试全部成功的反思"""
        history = [
            make_node_result("n1", confidence=0.9),
            make_node_result("n2", confidence=0.85),
            make_node_result("n3", confidence=0.95),
        ]

        reflection = self.reflector.reflect(history)

        self.assertGreater(reflection.overall_score, 0)
        self.assertGreater(reflection.quality_score, 0)
        self.assertEqual(len(reflection.node_scores), 3)
        self.assertTrue(any("成功" in lesson for lesson in reflection.lessons_learned))

    def test_reflect_with_failures(self):
        """测试有失败的反思"""
        history = [
            make_node_result("n1", confidence=0.8),
            make_node_result("n2", success=False, error="失败"),
            make_node_result("n3", confidence=0.7),
        ]

        reflection = self.reflector.reflect(history)

        self.assertLess(reflection.quality_score, 1.0)
        self.assertTrue(
            any(ins.level == "error" for ins in reflection.insights)
        )

    def test_reflect_empty_history(self):
        """测试空历史的反思"""
        reflection = self.reflector.reflect([])

        self.assertEqual(reflection.overall_score, 0.0)
        self.assertTrue(len(reflection.lessons_learned) > 0)

    def test_reflect_with_blueprint(self):
        """测试带蓝图的反思"""
        blueprint = make_test_blueprint(["n1", "n2"])
        history = [
            make_node_result("n1", confidence=0.8),
            make_node_result("n2", confidence=0.9),
        ]

        reflection = self.reflector.reflect(history, blueprint=blueprint)

        self.assertEqual(reflection.blueprint_id, "test_bp")
        self.assertEqual(reflection.objective_id, "test_obj")

    def test_node_scores(self):
        """测试节点评分"""
        history = [
            make_node_result("good_node", confidence=0.95),
            make_node_result("bad_node", success=False),
        ]

        reflection = self.reflector.reflect(history)

        self.assertIn("good_node", reflection.node_scores)
        self.assertIn("bad_node", reflection.node_scores)
        self.assertGreater(
            reflection.node_scores["good_node"],
            reflection.node_scores["bad_node"],
        )


# ============================================================
# 融合编排器测试（端到端）
# ============================================================

class TestFusionOrchestrator(unittest.TestCase):
    """测试融合编排器（端到端流程）"""

    def setUp(self):
        self.fusion = FusionOrchestrator(
            use_llm=False,
            enable_replanning=True,
            enable_reflection=True,
            max_replans=2,
        )

    def test_end_to_end_happy_path(self):
        """测试正常路径（全部成功）"""
        blueprint = make_test_blueprint(["n1", "n2", "n3"])
        available = ["n1", "n2", "n3"]

        # 节点1
        r1 = make_node_result("n1", confidence=0.9)
        d1 = self.fusion.process_node_result(r1, available)
        self.assertEqual(d1.action, "continue")

        # 节点2
        r2 = make_node_result("n2", confidence=0.85)
        d2 = self.fusion.process_node_result(r2, available)
        self.assertEqual(d2.action, "continue")

        # 节点3
        r3 = make_node_result("n3", confidence=0.95)
        d3 = self.fusion.process_node_result(r3, available)
        # 最后一个节点
        self.assertIn(d3.action, ["continue", "complete"])

        # 反思
        reflection = self.fusion.reflect(blueprint)
        self.assertGreater(reflection.overall_score, 0)

        # 摘要
        summary = self.fusion.get_execution_summary()
        self.assertEqual(summary["total_nodes"], 3)
        self.assertEqual(summary["successful"], 3)

    def test_end_to_end_with_replan(self):
        """测试含重规划的路径"""
        blueprint = make_test_blueprint(["n1", "bad_node", "n3"])
        available = ["n1", "bad_node", "n3"]

        # 节点1成功
        r1 = make_node_result("n1", confidence=0.9)
        d1 = self.fusion.process_node_result(r1, available)
        self.assertEqual(d1.action, "continue")

        # 坏节点失败
        r2 = make_node_result("bad_node", success=False, error="超时")
        d2 = self.fusion.process_node_result(r2, available)

        # 应该触发重规划
        if d2.replan_required:
            replan_result = self.fusion.handle_replan(
                blueprint, "bad_node", d2.replan_reason or "失败"
            )
            self.assertTrue(replan_result.success)
            self.assertIn("bad_node", replan_result.removed_nodes)

        # 摘要
        summary = self.fusion.get_execution_summary()
        self.assertEqual(summary["failed"], 1)
        self.assertGreaterEqual(summary["replans_triggered"], 0)

    def test_reset(self):
        """测试重置"""
        r1 = make_node_result("n1", confidence=0.8)
        self.fusion.process_node_result(r1, ["n1"])

        self.assertEqual(len(self.fusion.execution_history), 1)

        self.fusion.reset()

        self.assertEqual(len(self.fusion.execution_history), 0)
        self.assertEqual(len(self.fusion.decision_history), 0)
        self.assertEqual(self.fusion.replanner.replan_count, 0)

    def test_disabled_features(self):
        """测试禁用功能"""
        fusion = FusionOrchestrator(
            use_llm=False,
            enable_replanning=False,
            enable_reflection=False,
        )

        # 重规划应该被禁用
        blueprint = make_test_blueprint(["n1"])
        replan_result = fusion.handle_replan(blueprint, "n1", "test", [])
        self.assertFalse(replan_result.success)

        # 反思应该返回空
        reflection = fusion.reflect()
        self.assertEqual(reflection.overall_score, 0.0)


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
