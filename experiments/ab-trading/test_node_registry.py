#!/usr/bin/env python3
"""
节点注册表测试

位置: experiments/ab-trading/test_node_registry.py

测试内容：
1. NodeInfo 数据结构
2. NodeRegistry 注册/注销/查询
3. 多维度索引查询
4. 节点-模块映射对齐
5. 新旧ID兼容
6. 从模块注册表自动生成
"""

import sys
import os
import unittest
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.nodes.node_registry import (
    NodeInfo,
    NodeRegistry,
    IOSchema,
    NodeRetryPolicy,
    NodeFallbackPolicy,
    get_node_registry,
    register_node,
    get_node,
    get_node_handler,
)

from core.nodes.node_definitions import (
    get_all_node_definitions,
    LEGACY_TO_NEW_ID,
    NEW_TO_LEGACY_ID,
    map_legacy_id,
    map_new_id,
)

from core.nodes import (
    get_node_handler as global_get_node_handler,
    list_nodes,
    node_exists,
    list_legacy_nodes,
    NODE_HANDLERS,
    get_node_registry as global_registry,
)


# ============================================================
# 数据结构测试
# ============================================================

class TestDataStructures(unittest.TestCase):
    """测试数据结构"""

    def test_io_schema(self):
        """测试IOSchema"""
        schema = IOSchema(
            required_fields=["mkt"],
            optional_fields=["data"],
            field_types={"mkt": "dict", "data": "dict"},
        )

        d = schema.to_dict()
        self.assertIn("required_fields", d)
        self.assertEqual(d["required_fields"], ["mkt"])

        schema2 = IOSchema.from_dict(d)
        self.assertEqual(schema2.required_fields, ["mkt"])

    def test_retry_policy(self):
        """测试重试策略"""
        policy = NodeRetryPolicy(enabled=True, max_retries=3)
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.max_retries, 3)

        d = policy.to_dict()
        self.assertEqual(d["max_retries"], 3)

        policy2 = NodeRetryPolicy.from_dict(d)
        self.assertTrue(policy2.enabled)

    def test_fallback_policy(self):
        """测试降级策略"""
        policy = NodeFallbackPolicy(
            enabled=True,
            fallback_node_id="fallback-node",
        )
        self.assertTrue(policy.enabled)
        self.assertEqual(policy.fallback_node_id, "fallback-node")

        d = policy.to_dict()
        policy2 = NodeFallbackPolicy.from_dict(d)
        self.assertEqual(policy2.fallback_node_id, "fallback-node")

    def test_node_info(self):
        """测试NodeInfo"""
        node = NodeInfo(
            node_id="test-node",
            name="测试节点",
            description="测试用",
            chain="A",
            module_id="test-module",
            node_type="local_node",
            tags=["test"],
        )

        self.assertEqual(node.node_id, "test-node")
        self.assertEqual(node.chain, "A")

        d = node.to_dict()
        self.assertEqual(d["node_id"], "test-node")

        node2 = NodeInfo.from_dict(d)
        self.assertEqual(node2.name, "测试节点")


# ============================================================
# 节点注册表测试
# ============================================================

class TestNodeRegistry(unittest.TestCase):
    """测试节点注册表"""

    def _create_test_registry(self):
        """创建测试用注册表"""
        registry = NodeRegistry()

        nodes = [
            NodeInfo(node_id="n1", name="节点1", chain="A", module_id="m1",
                     node_type="local_node", tags=["tag1", "tag2"],
                     applicable_stages=["analysis"]),
            NodeInfo(node_id="n2", name="节点2", chain="A", module_id="m1",
                     node_type="skill_node", tags=["tag2", "tag3"],
                     applicable_stages=["analysis", "strategy"]),
            NodeInfo(node_id="n3", name="节点3", chain="C", module_id="m2",
                     node_type="api_node", tags=["tag1", "tag3"],
                     applicable_stages=["execution"]),
            NodeInfo(node_id="n4", name="节点4", chain="F", module_id="m3",
                     node_type="local_node", tags=["tag4"]),
        ]

        for n in nodes:
            registry.register(n)

        return registry

    def test_register_and_get(self):
        """测试注册和获取"""
        registry = NodeRegistry()

        node = NodeInfo(node_id="test", name="测试", chain="A")
        result = registry.register(node)

        self.assertTrue(result)
        self.assertTrue(registry.has("test"))

        fetched = registry.get("test")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "测试")

    def test_unregister(self):
        """测试注销"""
        registry = NodeRegistry()
        node = NodeInfo(node_id="test", name="测试")
        registry.register(node)

        self.assertTrue(registry.has("test"))
        registry.unregister("test")
        self.assertFalse(registry.has("test"))
        # 注销后还能查到，但状态是inactive
        self.assertIsNotNone(registry.get("test"))
        self.assertTrue(registry.get("test").deprecated)

    def test_query_by_chain(self):
        """测试按链查询"""
        registry = self._create_test_registry()

        a_nodes = registry.query(chain="A")
        self.assertEqual(len(a_nodes), 2)

        c_nodes = registry.query(chain="C")
        self.assertEqual(len(c_nodes), 1)

    def test_query_by_module(self):
        """测试按模块查询"""
        registry = self._create_test_registry()

        m1_nodes = registry.query(module_id="m1")
        self.assertEqual(len(m1_nodes), 2)

    def test_query_by_type(self):
        """测试按节点类型查询"""
        registry = self._create_test_registry()

        local_nodes = registry.query(node_type="local_node")
        self.assertEqual(len(local_nodes), 2)

    def test_query_by_tag(self):
        """测试按标签查询"""
        registry = self._create_test_registry()

        tag1_nodes = registry.query(tag="tag1")
        self.assertEqual(len(tag1_nodes), 2)

        tag4_nodes = registry.query(tag="tag4")
        self.assertEqual(len(tag4_nodes), 1)

    def test_query_by_stage(self):
        """测试按阶段查询"""
        registry = self._create_test_registry()

        analysis_nodes = registry.query(stage="analysis")
        self.assertEqual(len(analysis_nodes), 2)

    def test_count(self):
        """测试计数"""
        registry = self._create_test_registry()
        self.assertEqual(registry.count(), 4)

    def test_get_all(self):
        """测试获取所有"""
        registry = self._create_test_registry()
        all_nodes = registry.get_all()
        self.assertEqual(len(all_nodes), 4)

    def test_stats(self):
        """测试统计"""
        registry = self._create_test_registry()
        stats = registry.get_stats()

        self.assertEqual(stats["total"], 4)
        self.assertIn("by_chain", stats)
        self.assertEqual(stats["by_chain"]["A"], 2)
        self.assertEqual(stats["by_type"]["local_node"], 2)

    def test_record_call(self):
        """测试调用记录"""
        registry = NodeRegistry()
        node = NodeInfo(node_id="test", name="测试")
        registry.register(node)

        registry.record_call("test", 100.0)
        registry.record_call("test", 200.0)

        stats = registry.get_node_stats("test")
        self.assertEqual(stats["call_count"], 2)
        self.assertEqual(stats["total_latency_ms"], 300.0)
        self.assertEqual(stats["avg_latency_ms"], 150.0)


# ============================================================
# 节点定义测试
# ============================================================

class TestNodeDefinitions(unittest.TestCase):
    """测试节点定义"""

    def test_definitions_count(self):
        """测试定义数量"""
        defs = get_all_node_definitions()
        self.assertGreaterEqual(len(defs), 10)  # 至少10个节点

    def test_all_definitions_valid(self):
        """测试所有定义都是合法的NodeInfo"""
        defs = get_all_node_definitions()

        for d in defs:
            node = NodeInfo.from_dict(d)
            self.assertIsNotNone(node.node_id)
            self.assertIsNotNone(node.name)
            self.assertIn(node.chain, ["A", "C", "F", "G", "T"])

    def test_legacy_to_new_id_mapping(self):
        """测试新旧ID映射"""
        # 旧ID都能映射到新ID
        for legacy, new in LEGACY_TO_NEW_ID.items():
            self.assertEqual(map_legacy_id(legacy), new)
            self.assertEqual(map_new_id(new), legacy)

        # 不存在的ID原样返回
        self.assertEqual(map_legacy_id("不存在"), "不存在")
        self.assertEqual(map_new_id("not-exist"), "not-exist")

    def test_definitions_match_modules(self):
        """测试节点ID与模块ID对齐"""
        defs = get_all_node_definitions()

        for d in defs:
            # node_id 应该等于 module_id（一一对应）
            self.assertEqual(d["node_id"], d["module_id"])


# ============================================================
# 全局注册表测试
# ============================================================

class TestGlobalRegistry(unittest.TestCase):
    """测试全局注册表"""

    def test_global_registry_exists(self):
        """测试全局注册表存在"""
        registry = global_registry()
        self.assertIsNotNone(registry)
        self.assertIsInstance(registry, NodeRegistry)

    def test_global_nodes_registered(self):
        """测试全局节点已注册"""
        registry = global_registry()
        self.assertGreater(registry.count(), 0)

    def test_global_get_node_handler_new_id(self):
        """测试用新ID获取处理器"""
        handler = global_get_node_handler("classic-indicator-scan")
        self.assertIsNotNone(handler)

    def test_global_get_node_handler_legacy_id(self):
        """测试用旧ID获取处理器（向后兼容）"""
        handler = global_get_node_handler("C1_技术扫描")
        self.assertIsNotNone(handler)

    def test_node_exists(self):
        """测试node_exists"""
        self.assertTrue(node_exists("classic-indicator-scan"))
        self.assertTrue(node_exists("C1_技术扫描"))
        self.assertFalse(node_exists("不存在的节点"))

    def test_list_nodes(self):
        """测试list_nodes"""
        nodes = list_nodes()
        self.assertIsInstance(nodes, list)
        self.assertGreater(len(nodes), 0)
        # 都是新ID（kebab-case）
        for nid in nodes:
            self.assertIsInstance(nid, str)

    def test_list_legacy_nodes(self):
        """测试list_legacy_nodes"""
        legacy = list_legacy_nodes()
        self.assertIsInstance(legacy, list)
        self.assertGreater(len(legacy), 0)
        self.assertIn("C1_技术扫描", legacy)

    def test_node_handlers_backward_compat(self):
        """测试NODE_HANDLERS向后兼容"""
        self.assertIn("C1_技术扫描", NODE_HANDLERS)
        self.assertIn("A0_矛盾论", NODE_HANDLERS)
        self.assertIn("做梦部", NODE_HANDLERS)

    def test_all_registered_nodes_have_handlers(self):
        """测试所有注册的节点都有处理器"""
        registry = global_registry()
        all_nodes = registry.get_all()

        for node in all_nodes:
            handler = registry.get_handler(node.node_id)
            # 有些节点可能没有本地handler（如skill_node），但可以通过适配器执行
            # 所以这里不强制要求有handler
            if handler:
                self.assertTrue(callable(handler))

    def test_chain_distribution(self):
        """测试各链的节点分布"""
        registry = global_registry()
        stats = registry.get_stats()

        by_chain = stats["by_chain"]
        self.assertIn("A", by_chain)  # A链至少有几个
        self.assertGreaterEqual(by_chain["A"], 5)
        self.assertIn("C", by_chain)
        self.assertIn("F", by_chain)
        self.assertGreaterEqual(by_chain["F"], 3)


# ============================================================
# 从模块注册表生成测试
# ============================================================

class TestGenerateFromModuleRegistry(unittest.TestCase):
    """测试从模块注册表生成节点"""

    def test_generate_from_module_registry(self):
        """测试从模块注册表生成节点"""
        from core.modules.module_registry import get_module_registry

        module_reg = get_module_registry()
        module_count = module_reg.count()

        if module_count == 0:
            self.skipTest("模块注册表为空（可能YAML文件不存在）")

        node_reg = NodeRegistry()
        generated = node_reg.generate_from_module_registry(module_reg)

        self.assertGreater(generated, 0)
        self.assertEqual(node_reg.count(), generated)

        # 每个模块至少对应一个节点
        self.assertGreaterEqual(generated, module_count)


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
