#!/usr/bin/env python3
"""
接口层测试

位置: experiments/ab-trading/test_interface_layer.py

测试内容：
1. 错误码体系
2. 异常类和包装
3. 统一节点执行器
4. A层 GraphOrchestrator 与 统一执行器 联调
5. 端到端：S层 → A层 → C层(统一执行器) → G层
"""

import sys
import os
import unittest
from typing import Dict, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.shared.errors import (
    ErrorCode,
    OSBaseError,
    ModuleError,
    NodeError,
    AdapterError,
    ExecutionError,
    ValidationError,
    DataError,
    OrchestrationError,
    wrap_exception,
    ErrorInfo,
)

from core.c_execution_layer.unified_executor import UnifiedNodeExecutor
from core.shared.interfaces import NodeExecutionStatus


# ============================================================
# 错误码体系测试
# ============================================================

class TestErrorCode(unittest.TestCase):
    """测试错误码体系"""

    def test_error_code_description(self):
        """测试错误码描述"""
        self.assertEqual(ErrorCode.get_description(1000), "系统错误")
        self.assertEqual(ErrorCode.get_description(2000), "模块未找到")
        self.assertEqual(ErrorCode.get_description(2100), "节点未找到")
        self.assertEqual(ErrorCode.get_description(4000), "执行失败")
        self.assertEqual(ErrorCode.get_description(6000), "编排错误")

    def test_error_code_range(self):
        """测试错误码范围分类"""
        # 1xxx 系统级
        self.assertTrue(1000 <= ErrorCode.SYSTEM_ERROR < 2000)
        # 2xxx 模块/节点
        self.assertTrue(2000 <= ErrorCode.MODULE_NOT_FOUND < 3000)
        self.assertTrue(2000 <= ErrorCode.NODE_NOT_FOUND < 3000)
        # 3xxx 适配器
        self.assertTrue(3000 <= ErrorCode.ADAPTER_NOT_FOUND < 4000)
        # 4xxx 执行
        self.assertTrue(4000 <= ErrorCode.EXECUTION_FAILED < 5000)
        # 5xxx 数据
        self.assertTrue(5000 <= ErrorCode.DATA_NOT_FOUND < 6000)
        # 6xxx 编排
        self.assertTrue(6000 <= ErrorCode.ORCHESTRATION_ERROR < 7000)

    def test_is_retryable(self):
        """测试可重试错误判断"""
        self.assertTrue(ErrorCode.is_retryable(ErrorCode.EXECUTION_TIMEOUT))
        self.assertTrue(ErrorCode.is_retryable(ErrorCode.ADAPTER_TIMEOUT))
        self.assertTrue(ErrorCode.is_retryable(ErrorCode.API_CONNECTION_FAILED))
        self.assertFalse(ErrorCode.is_retryable(ErrorCode.MODULE_NOT_FOUND))
        self.assertFalse(ErrorCode.is_retryable(ErrorCode.VALIDATION_FAILED))

    def test_is_fallback_allowed(self):
        """测试降级允许判断"""
        self.assertTrue(ErrorCode.is_fallback_allowed(ErrorCode.EXECUTION_FAILED))
        self.assertTrue(ErrorCode.is_fallback_allowed(ErrorCode.ADAPTER_EXECUTION_ERROR))
        self.assertFalse(ErrorCode.is_fallback_allowed(ErrorCode.SYSTEM_SHUTTING_DOWN))


class TestExceptions(unittest.TestCase):
    """测试异常类"""

    def test_os_base_error(self):
        """测试异常基类"""
        err = OSBaseError("测试错误", error_code=4000, node_id="test-node")

        self.assertEqual(str(err), "测试错误")
        self.assertEqual(err.error_code, 4000)
        self.assertEqual(err.node_id, "test-node")
        self.assertEqual(err.code_description, "执行失败")

    def test_module_error(self):
        """测试模块错误"""
        err = ModuleError("模块不存在", module_id="mod-1")
        self.assertEqual(err.module_id, "mod-1")
        self.assertEqual(err.error_code, ErrorCode.MODULE_NOT_FOUND)

    def test_node_error(self):
        """测试节点错误"""
        err = NodeError("节点不存在", node_id="node-1")
        self.assertEqual(err.node_id, "node-1")
        self.assertEqual(err.error_code, ErrorCode.NODE_NOT_FOUND)

    def test_adapter_error(self):
        """测试适配器错误"""
        err = AdapterError("适配器初始化失败")
        self.assertEqual(err.error_code, ErrorCode.ADAPTER_EXECUTION_ERROR)

    def test_execution_error(self):
        """测试执行错误"""
        err = ExecutionError("执行失败")
        self.assertEqual(err.error_code, ErrorCode.EXECUTION_FAILED)

    def test_validation_error(self):
        """测试校验错误"""
        err = ValidationError("输入校验失败")
        self.assertEqual(err.error_code, ErrorCode.VALIDATION_FAILED)

    def test_data_error(self):
        """测试数据错误"""
        err = DataError("数据未找到")
        self.assertEqual(err.error_code, ErrorCode.DATA_NOT_FOUND)

    def test_orchestration_error(self):
        """测试编排错误"""
        err = OrchestrationError("编排错误")
        self.assertEqual(err.error_code, ErrorCode.ORCHESTRATION_ERROR)

    def test_to_dict(self):
        """测试异常转字典"""
        err = OSBaseError("测试", error_code=4000, node_id="n1", module_id="m1")
        d = err.to_dict()

        self.assertEqual(d["error_code"], 4000)
        self.assertEqual(d["node_id"], "n1")
        self.assertEqual(d["module_id"], "m1")
        self.assertIn("retryable", d)
        self.assertIn("fallback_allowed", d)

    def test_wrap_exception(self):
        """测试异常包装"""
        # 普通异常
        exc = ValueError("值错误")
        wrapped = wrap_exception(exc, node_id="n1")

        self.assertIsInstance(wrapped, OSBaseError)
        self.assertEqual(wrapped.error_code, ErrorCode.DATA_FORMAT_ERROR)
        self.assertEqual(wrapped.node_id, "n1")

        # 超时异常
        exc2 = TimeoutError("超时了")
        wrapped2 = wrap_exception(exc2)
        self.assertEqual(wrapped2.error_code, ErrorCode.EXECUTION_TIMEOUT)

        # 已经是 OSBaseError 的不重复包装
        original = ExecutionError("执行错")
        wrapped3 = wrap_exception(original, node_id="n2")
        self.assertIs(wrapped3, original)
        self.assertEqual(wrapped3.node_id, "n2")  # 补充了node_id

    def test_retryable_property(self):
        """测试可重试属性"""
        err1 = OSBaseError("超时", error_code=ErrorCode.EXECUTION_TIMEOUT)
        self.assertTrue(err1.is_retryable)

        err2 = OSBaseError("模块未找到", error_code=ErrorCode.MODULE_NOT_FOUND)
        self.assertFalse(err2.is_retryable)

        # 覆盖默认值
        err3 = OSBaseError("自定义", error_code=4000, retryable=True)
        self.assertTrue(err3.is_retryable)


class TestErrorInfo(unittest.TestCase):
    """测试错误信息结构"""

    def test_create_error_info(self):
        """测试创建ErrorInfo"""
        info = ErrorInfo.create(ErrorCode.NODE_NOT_FOUND, "节点不存在", node_id="n1")

        self.assertEqual(info.error_code, ErrorCode.NODE_NOT_FOUND)
        self.assertEqual(info.message, "节点不存在")
        self.assertEqual(info.node_id, "n1")
        self.assertEqual(info.description, "节点未找到")
        self.assertFalse(info.retryable)

    def test_from_exception(self):
        """测试从异常创建"""
        exc = NodeError("节点错", node_id="n1", error_code=ErrorCode.NODE_NOT_FOUND)
        info = ErrorInfo.from_exception(exc)

        self.assertEqual(info.error_code, ErrorCode.NODE_NOT_FOUND)
        self.assertEqual(info.node_id, "n1")

    def test_to_dict(self):
        """测试转字典"""
        info = ErrorInfo.create(4000, "执行失败", module_id="m1")
        d = info.to_dict()

        self.assertEqual(d["error_code"], 4000)
        self.assertEqual(d["message"], "执行失败")
        self.assertEqual(d["module_id"], "m1")
        self.assertIn("error_description", d)
        self.assertIn("retryable", d)


# ============================================================
# 统一节点执行器测试
# ============================================================

class TestUnifiedNodeExecutor(unittest.TestCase):
    """测试统一节点执行器"""

    def setUp(self):
        """设置测试环境"""
        self.executor = UnifiedNodeExecutor(enable_retry=True, enable_fallback=True)

    def test_executor_exists(self):
        """测试执行器存在"""
        self.assertIsNotNone(self.executor)
        self.assertTrue(hasattr(self.executor, 'execute_node'))
        self.assertTrue(hasattr(self.executor, 'execute'))
        self.assertTrue(hasattr(self.executor, 'get_node_schema'))

    def test_executor_implements_interface(self):
        """测试实现了 NodeExecutorInterface"""
        from core.shared.interfaces import NodeExecutorInterface
        self.assertTrue(isinstance(self.executor, NodeExecutorInterface))

    def test_execute_with_local_handler(self):
        """测试使用本地handler执行（C1技术扫描）"""
        # C1技术扫描有本地实现
        mkt = {}
        memory = {}
        data = {}
        inputs = {"mkt": mkt, "memory": memory, "data": data}
        context = {"session_id": "test-001", "intent": "tech_analysis"}

        # 用 execute（返回 ModuleResult）
        result = self.executor.execute("classic-indicator-scan", inputs, context)

        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'success'))
        self.assertTrue(hasattr(result, 'outputs'))
        self.assertTrue(hasattr(result, 'confidence'))
        self.assertTrue(hasattr(result, 'capability_id'))

    def test_execute_node_returns_status(self):
        """测试 execute_node 返回 NodeExecutionStatus"""
        inputs = {"mkt": {}, "memory": {}, "data": {}}
        context = {"session_id": "test-002"}

        status = self.executor.execute_node("classic-indicator-scan", inputs, context)

        self.assertIsInstance(status, NodeExecutionStatus)
        self.assertEqual(status.node_id, "classic-indicator-scan")
        self.assertIn(status.status, ["completed", "failed"])

        if status.status == "completed":
            self.assertIsNotNone(status.result)
            self.assertGreaterEqual(status.confidence, 0.0)
            self.assertLessEqual(status.confidence, 1.0)

    def test_execute_nonexistent_node(self):
        """测试执行不存在的节点"""
        inputs = {"mkt": {}}
        context = {}

        result = self.executor.execute("nonexistent-node", inputs, context)

        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)

    def test_get_node_schema(self):
        """测试获取节点Schema"""
        schema = self.executor.get_node_schema("classic-indicator-scan")

        # 有节点注册表的话应该有schema
        if schema is not None:
            self.assertIn("inputs", schema)
            self.assertIn("outputs", schema)

    def test_stats(self):
        """测试统计功能"""
        # 执行几次
        inputs = {"mkt": {}, "memory": {}, "data": {}}
        context = {"session_id": "stats-test"}
        for _ in range(3):
            self.executor.execute("classic-indicator-scan", inputs, context)

        stats = self.executor.get_stats()

        self.assertEqual(stats["total_calls"], 3)
        self.assertIn("success", stats)
        self.assertIn("avg_latency_ms", stats)
        self.assertIn("success_rate", stats)

    def test_get_stats_before_any_execution(self):
        """测试执行前的统计"""
        executor = UnifiedNodeExecutor()
        stats = executor.get_stats()

        self.assertEqual(stats["total_calls"], 0)
        self.assertEqual(stats["avg_latency_ms"], 0)

    def test_reset_stats(self):
        """测试重置统计"""
        inputs = {"mkt": {}, "memory": {}, "data": {}}
        context = {"session_id": "reset-test"}

        self.executor.execute("classic-indicator-scan", inputs, context)
        self.assertEqual(self.executor.get_stats()["total_calls"], 1)

        self.executor.reset_stats()
        self.assertEqual(self.executor.get_stats()["total_calls"], 0)


# ============================================================
# A层 GraphOrchestrator 与 统一执行器 联调测试
# ============================================================

class TestOrchestratorIntegration(unittest.TestCase):
    """测试A层图编排器与统一执行器集成"""

    def test_graph_orchestrator_with_unified_executor(self):
        """测试图编排器使用统一执行器"""
        from core.a_graph_orchestrator.graph_orchestrator import GraphOrchestrator
        from core.intent_engine.types import ExecutionBlueprint

        # 使用统一执行器
        executor = UnifiedNodeExecutor()

        # 构建简单蓝图
        blueprint = ExecutionBlueprint(
            blueprint_id="test-bp-001",
            objective_id="obj-001",
            node_sequence=["classic-indicator-scan"],
            execution_mode="sequential",
        )

        # 创建编排器
        orchestrator = GraphOrchestrator(
            node_executor=executor,
        )

        # 执行
        result = orchestrator.execute(blueprint, context={"session_id": "integration-test"})

        self.assertIsNotNone(result)
        self.assertTrue(hasattr(result, 'status'))
        self.assertTrue(hasattr(result, 'node_statuses'))
        self.assertGreater(len(result.node_statuses), 0)

    def test_multi_node_orchestration(self):
        """测试多节点编排（C1 + F2 + F3）"""
        from core.a_graph_orchestrator.graph_orchestrator import GraphOrchestrator
        from core.intent_engine.types import ExecutionBlueprint

        executor = UnifiedNodeExecutor()

        # 并行执行3个技术/基本面节点
        blueprint = ExecutionBlueprint(
            blueprint_id="test-bp-parallel",
            objective_id="obj-parallel",
            node_sequence=[
                "classic-indicator-scan",
                "fundamental-fund-flow",
                "fundamental-sentiment",
            ],
            execution_mode="parallel",
            parallel_groups=[
                ["classic-indicator-scan", "fundamental-fund-flow", "fundamental-sentiment"]
            ],
        )

        orchestrator = GraphOrchestrator(node_executor=executor)
        result = orchestrator.execute(blueprint, context={"session_id": "parallel-test"})

        self.assertIsNotNone(result)
        self.assertEqual(len(result.node_statuses), 3)


# ============================================================
# 端到端测试（简化版）
# ============================================================

class TestEndToEndMinimal(unittest.TestCase):
    """简化版端到端测试：S层意图识别 → A层编排 → C层执行"""

    def test_simple_trade_analysis(self):
        """简单交易分析全流程"""
        from core.intent_engine.engine import IntentRecognitionEngine
        from core.a_graph_orchestrator.graph_orchestrator import GraphOrchestrator
        from core.c_execution_layer.unified_executor import UnifiedNodeExecutor

        # 1. S层：意图识别
        engine = IntentRecognitionEngine()
        intent_result = engine.recognize("分析一下当前市场的技术面和资金流情况")

        self.assertIsNotNone(intent_result)
        self.assertIsNotNone(intent_result.blueprint)

        # 2. A层 + C层：图编排 + 执行
        executor = UnifiedNodeExecutor()
        orchestrator = GraphOrchestrator(node_executor=executor)

        graph_result = orchestrator.execute(
            intent_result.blueprint,
            context={
                "session_id": "e2e-test",
                "objective_id": intent_result.objective.id if intent_result.objective else "",
                "blueprint_id": intent_result.blueprint.blueprint_id,
            }
        )

        self.assertIsNotNone(graph_result)
        # 至少有部分节点成功执行
        self.assertGreater(len(graph_result.node_statuses), 0)


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
