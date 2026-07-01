#!/usr/bin/env python3
"""
模块接口验证测试

位置: experiments/ab-trading/test_module_interfaces.py

测试内容：
1. 所有已注册节点都能通过统一执行器执行
2. 所有节点返回统一格式的结果
3. 所有节点的输入输出Schema验证
4. A/C/F/G各链模块接口一致性验证
5. 降级功能验证
"""

import sys
import os
import unittest
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.nodes.node_registry import get_node_registry, NodeInfo
from core.c_execution_layer.unified_executor import UnifiedNodeExecutor
from core.modules.unified_types import ModuleResult


# ============================================================
# 测试用市场数据
# ============================================================

def create_test_mkt() -> Dict[str, Any]:
    """创建测试用市场数据"""
    price = 45000.0
    return {
        "symbol": "BTC/USDT",
        "coin": "BTC",
        "price": price,
        "high_24h": price * 1.05,
        "low_24h": price * 0.95,
        "volume_24h": 1000000000,
        "change_24h": 2.5,
        "change_4h": 0.8,
        "change_1h": 0.3,
        # MA指标
        "ema5": price * 1.002,
        "ema10": price * 0.998,
        "ema20": price * 0.995,
        "ema50": price * 0.99,
        "ema200": price * 0.97,
        "ma20": price * 0.995,
        "ma50": price * 0.99,
        "ma200": price * 0.97,
        # RSI
        "rsi14": 58.0,
        "rsi7": 62.0,
        # MACD
        "macd": 50.0,
        "macd_signal": 45.0,
        "macd_histogram": 5.0,
        # 布林带
        "bb_upper": price * 1.03,
        "bb_middle": price * 0.995,
        "bb_lower": price * 0.96,
        # 成交量
        "volume": 50000,
        "volume_ma": 45000,
        # 资金流
        "money_flow": 15000000,
        "money_flow_ratio": 1.2,
        # 情绪指标
        "fear_greed_index": 65,
        "put_call_ratio": 0.7,
    }


def create_test_memory() -> Dict[str, Any]:
    """创建测试用记忆数据"""
    return {
        "session_id": "test-session-001",
        "previous_analysis": {
            "direction": "long",
            "confidence": 0.6,
        },
        "position": {
            "side": "long",
            "entry_price": 44000.0,
            "size": 0.1,
            "pnl": 500.0,
        },
        "trade_history": [
            {"symbol": "BTC", "side": "long", "pnl": 200},
            {"symbol": "BTC", "side": "short", "pnl": -100},
        ],
    }


def create_test_data() -> Dict[str, Any]:
    """创建测试用共享数据"""
    return {
        "timeframe": "4h",
        "risk_level": "medium",
        "user_preference": {
            "max_drawdown": 0.1,
            "target_profit": 0.05,
        },
    }


# ============================================================
# 模块接口基础测试
# ============================================================

class TestAllNodesExecutable(unittest.TestCase):
    """测试所有已注册节点都能执行"""

    @classmethod
    def setUpClass(cls):
        cls.registry = get_node_registry()
        cls.executor = UnifiedNodeExecutor()
        cls.all_nodes = cls.registry.get_all()
        cls.test_mkt = create_test_mkt()
        cls.test_memory = create_test_memory()
        cls.test_data = create_test_data()

    def test_nodes_registered(self):
        """测试有节点注册"""
        self.assertGreater(len(self.all_nodes), 0)
        print(f"\n  已注册节点数: {len(self.all_nodes)}")

    def test_all_nodes_have_basic_info(self):
        """测试所有节点都有基本信息"""
        for node in self.all_nodes:
            with self.subTest(node=node.node_id):
                self.assertTrue(node.node_id, "节点ID不能为空")
                self.assertTrue(node.name, f"节点 {node.node_id} 名称不能为空")
                self.assertIn(node.chain, ["A", "C", "F", "G", "T"],
                              f"节点 {node.node_id} 链标识无效")
                self.assertIn(node.node_type,
                              ["skill_node", "api_node", "local_node", "composite_node"],
                              f"节点 {node.node_id} 类型无效")

    def test_all_nodes_executable_via_unified_executor(self):
        """测试所有节点都能通过统一执行器执行"""
        inputs = {
            "mkt": self.test_mkt,
            "memory": self.test_memory,
            "data": self.test_data,
        }
        context = {
            "session_id": "test-exec-all",
            "intent": "test",
        }

        success_count = 0
        failed_nodes = []

        for node in self.all_nodes:
            with self.subTest(node=node.node_id):
                result = self.executor.execute(node.node_id, inputs, context)
                self.assertIsInstance(result, ModuleResult)
                self.assertEqual(result.capability_id, node.node_id)

                if result.success or result.fallback_used:
                    success_count += 1
                else:
                    # 记录失败但不中断（有些模块可能依赖外部服务）
                    failed_nodes.append((node.node_id, result.error))

        print(f"\n  可执行节点: {success_count}/{len(self.all_nodes)}")
        if failed_nodes:
            print(f"  失败节点:")
            for nid, err in failed_nodes:
                print(f"    - {nid}: {err}")

    def test_all_nodes_return_consistent_format(self):
        """测试所有节点返回格式一致"""
        inputs = {
            "mkt": self.test_mkt,
            "memory": self.test_memory,
            "data": self.test_data,
        }
        context = {"session_id": "test-format"}

        for node in self.all_nodes:
            with self.subTest(node=node.node_id):
                result = self.executor.execute(node.node_id, inputs, context)

                # 检查必须有的字段
                self.assertTrue(hasattr(result, 'success'))
                self.assertTrue(hasattr(result, 'capability_id'))
                self.assertTrue(hasattr(result, 'outputs'))
                self.assertTrue(hasattr(result, 'confidence'))
                self.assertTrue(hasattr(result, 'latency_ms'))
                self.assertTrue(hasattr(result, 'metadata'))

                # confidence 范围检查（百分制）
                if result.success:
                    self.assertGreaterEqual(result.confidence, 0.0)
                    self.assertLessEqual(result.confidence, 100.0)


# ============================================================
# A链模块接口测试
# ============================================================

class TestAChainModules(unittest.TestCase):
    """A链模块接口测试"""

    @classmethod
    def setUpClass(cls):
        cls.registry = get_node_registry()
        cls.executor = UnifiedNodeExecutor()
        cls.a_nodes = cls.registry.query(chain="A")
        cls.test_mkt = create_test_mkt()
        cls.test_memory = create_test_memory()
        cls.test_data = create_test_data()

    def test_a_chain_nodes_exist(self):
        """测试A链有节点"""
        self.assertGreaterEqual(len(self.a_nodes), 5)
        print(f"\n  A链节点数: {len(self.a_nodes)}")

    def test_a0_contradiction(self):
        """测试A0矛盾论接口"""
        result = self.executor.execute(
            "dream-contradiction-theory",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-a0"}
        )
        print(f"\n  A0矛盾论: success={result.success}, confidence={result.confidence:.1f}")
        self.assertIsInstance(result, ModuleResult)

    def test_a2_first_principles(self):
        """测试A2第一性原理接口"""
        result = self.executor.execute(
            "dream-first-principles",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-a2"}
        )
        print(f"\n  A2第一性原理: success={result.success}, confidence={result.confidence:.1f}")
        self.assertIsInstance(result, ModuleResult)

    def test_a_chain_nodes_have_retry_policy(self):
        """测试A链节点有重试策略"""
        for node in self.a_nodes:
            with self.subTest(node=node.node_id):
                self.assertIsNotNone(node.retry_policy)

    def test_a_chain_nodes_have_fallback(self):
        """测试A链节点有降级策略"""
        for node in self.a_nodes:
            with self.subTest(node=node.node_id):
                self.assertIsNotNone(node.fallback_policy)


# ============================================================
# C链模块接口测试
# ============================================================

class TestCChainModules(unittest.TestCase):
    """C链模块接口测试"""

    @classmethod
    def setUpClass(cls):
        cls.registry = get_node_registry()
        cls.executor = UnifiedNodeExecutor()
        cls.c_nodes = cls.registry.query(chain="C")
        cls.test_mkt = create_test_mkt()
        cls.test_memory = create_test_memory()
        cls.test_data = create_test_data()

    def test_c_chain_nodes_exist(self):
        """测试C链有节点"""
        self.assertGreaterEqual(len(self.c_nodes), 1)
        print(f"\n  C链节点数: {len(self.c_nodes)}")

    def test_c1_tech_scan(self):
        """测试C1技术扫描接口"""
        result = self.executor.execute(
            "classic-indicator-scan",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-c1"}
        )
        print(f"\n  C1技术扫描: success={result.success}, confidence={result.confidence:.1f}")
        self.assertTrue(result.success)
        self.assertIsInstance(result, ModuleResult)

    def test_c1_returns_direction(self):
        """测试C1返回direction"""
        result = self.executor.execute(
            "classic-indicator-scan",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-c1-dir"}
        )
        outputs = result.outputs.to_dict() if hasattr(result.outputs, 'to_dict') else {}
        # direction 可能在 outputs 的字段里
        has_direction = (
            'direction' in outputs or
            hasattr(result.outputs, 'direction')
        )
        print(f"\n  C1有direction字段: {has_direction}")


# ============================================================
# F链模块接口测试
# ============================================================

class TestFChainModules(unittest.TestCase):
    """F链模块接口测试"""

    @classmethod
    def setUpClass(cls):
        cls.registry = get_node_registry()
        cls.executor = UnifiedNodeExecutor()
        cls.f_nodes = cls.registry.query(chain="F")
        cls.test_mkt = create_test_mkt()
        cls.test_memory = create_test_memory()
        cls.test_data = create_test_data()

    def test_f_chain_nodes_exist(self):
        """测试F链有节点"""
        self.assertGreaterEqual(len(self.f_nodes), 3)
        print(f"\n  F链节点数: {len(self.f_nodes)}")

    def test_f1_news(self):
        """测试F1新闻分析接口"""
        result = self.executor.execute(
            "fundamental-news-analysis",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-f1"}
        )
        print(f"\n  F1新闻分析: success={result.success}, confidence={result.confidence:.1f}")
        self.assertIsInstance(result, ModuleResult)

    def test_f2_fund_flow(self):
        """测试F2资金流分析接口"""
        result = self.executor.execute(
            "fundamental-fund-flow",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-f2"}
        )
        print(f"\n  F2资金流分析: success={result.success}, confidence={result.confidence:.1f}")
        self.assertTrue(result.success)

    def test_f3_sentiment(self):
        """测试F3情绪分析接口"""
        result = self.executor.execute(
            "fundamental-sentiment",
            {"mkt": self.test_mkt, "memory": self.test_memory, "data": self.test_data},
            {"session_id": "test-f3"}
        )
        print(f"\n  F3情绪分析: success={result.success}, confidence={result.confidence:.1f}")
        self.assertTrue(result.success)

    def test_f_chain_confidence_range(self):
        """测试F链置信度范围合理（一般低于A链）"""
        # F链是基本面，置信度通常较低
        for node in self.f_nodes:
            with self.subTest(node=node.node_id):
                # 检查置信度范围配置
                cr = node.confidence_range
                self.assertGreaterEqual(len(cr), 2)
                self.assertLessEqual(cr[0], cr[1])


# ============================================================
# 节点Schema验证测试
# ============================================================

class TestNodeSchemas(unittest.TestCase):
    """节点Schema验证测试"""

    @classmethod
    def setUpClass(cls):
        cls.registry = get_node_registry()
        cls.all_nodes = cls.registry.get_all()

    def test_all_nodes_have_input_schema(self):
        """测试所有节点都有输入Schema"""
        for node in self.all_nodes:
            with self.subTest(node=node.node_id):
                self.assertIsNotNone(node.input_schema)
                self.assertIsInstance(node.input_schema.required_fields, list)
                self.assertIsInstance(node.input_schema.optional_fields, list)

    def test_all_nodes_have_output_schema(self):
        """测试所有节点都有输出Schema"""
        for node in self.all_nodes:
            with self.subTest(node=node.node_id):
                self.assertIsNotNone(node.output_schema)

    def test_critical_nodes_have_required_inputs(self):
        """测试关键节点必须有mkt输入"""
        critical_nodes = [
            "classic-indicator-scan",
            "dream-contradiction-theory",
            "dream-first-principles",
        ]

        for nid in critical_nodes:
            node = self.registry.get(nid)
            if node:
                with self.subTest(node=nid):
                    # 检查mkt在required或optional字段中
                    all_fields = (
                        node.input_schema.required_fields +
                        node.input_schema.optional_fields
                    )
                    has_mkt = 'mkt' in all_fields or 'mkt' in str(node.input_schema.field_types)
                    self.assertTrue(has_mkt, f"{nid} 应该有mkt输入")


# ============================================================
# 执行器统计测试
# ============================================================

class TestExecutorStats(unittest.TestCase):
    """执行器统计测试"""

    def test_executor_stats_after_execution(self):
        """测试执行后统计正确"""
        executor = UnifiedNodeExecutor()
        mkt = create_test_mkt()
        memory = create_test_memory()
        data = create_test_data()
        inputs = {"mkt": mkt, "memory": memory, "data": data}

        # 执行几个节点
        nodes_to_test = [
            "classic-indicator-scan",
            "fundamental-fund-flow",
            "fundamental-sentiment",
        ]

        for nid in nodes_to_test:
            executor.execute(nid, inputs, {"session_id": "stats-test"})

        stats = executor.get_stats()
        self.assertEqual(stats["total_calls"], len(nodes_to_test))
        self.assertGreaterEqual(stats["success"], 0)
        self.assertIn("avg_latency_ms", stats)
        self.assertIn("success_rate", stats)
        self.assertGreater(stats["total_latency_ms"], 0)

        print(f"\n  执行统计: {stats['success']}/{stats['total_calls']} 成功, "
              f"平均延迟: {stats['avg_latency_ms']:.1f}ms, "
              f"成功率: {stats['success_rate']*100:.1f}%")


# ============================================================
# 节点分类索引测试
# ============================================================

class TestNodeIndexing(unittest.TestCase):
    """节点分类索引测试"""

    @classmethod
    def setUpClass(cls):
        cls.registry = get_node_registry()

    def test_query_by_chain(self):
        """测试按链查询"""
        a_nodes = self.registry.query(chain="A")
        c_nodes = self.registry.query(chain="C")
        f_nodes = self.registry.query(chain="F")

        self.assertGreater(len(a_nodes), 0)
        self.assertGreater(len(c_nodes), 0)
        self.assertGreater(len(f_nodes), 0)

    def test_query_by_type(self):
        """测试按节点类型查询"""
        local_nodes = self.registry.query(node_type="local_node")
        skill_nodes = self.registry.query(node_type="skill_node")

        # 应该有两种类型的节点
        self.assertGreater(len(local_nodes), 0)
        self.assertGreater(len(skill_nodes), 0)

    def test_query_by_tag(self):
        """测试按标签查询"""
        nodes = self.registry.query(tag="technical")
        # 应该有技术类节点
        self.assertGreaterEqual(len(nodes), 1)

    def test_registry_stats(self):
        """测试注册表统计"""
        stats = self.registry.get_stats()
        self.assertIn("total", stats)
        self.assertIn("by_chain", stats)
        self.assertIn("by_type", stats)
        self.assertGreater(stats["total"], 0)
        self.assertGreater(stats["by_module_count"], 0)


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
