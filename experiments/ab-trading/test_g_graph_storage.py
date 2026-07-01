#!/usr/bin/env python3
"""
G层 - 图存储/压缩层测试

位置: experiments/ab-trading/test_g_graph_storage.py

测试内容：
1. 类型定义 - G.B / G.A / G.C
2. 压缩器 - 价值评估 + 回溯压缩
3. 展开器 - 正向展开
4. 管理器 - 统一入口 + 持久化
"""

import sys
import os
import unittest
import tempfile
from typing import Dict, Any, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.g_graph_storage import (
    # 类型
    BlueprintGraph,
    ArchitectureGraph,
    ChronicleGraph,
    BNode,
    ANode,
    CNode,
    BEdge,
    AEdge,
    CEdge,
    NodeStatus,
    NodeType,
    ComponentType,
    NodeMetadata,
    CompressionStrategy,
    CompressionResult,
    # 组件
    ValueScorer,
    GraphCompressor,
    GraphExpander,
    GraphStorageManager,
)


# ============================================================
# 测试工具
# ============================================================

def create_test_chronicle(node_count: int = 6) -> ChronicleGraph:
    """创建测试用时间线"""
    chron = ChronicleGraph()
    chron.execution_id = "test_exec_001"
    chron.architecture_id = "test_arch_001"

    prev_id = None
    for i in range(node_count):
        node = CNode(
            id=f"node_{i}",
            architecture_node_id=f"anode_{i}",
            execution_id=chron.execution_id,
            start_time=1000.0 + i * 100,
            end_time=1000.0 + i * 100 + 80 + i * 10,
        )
        node.metadata.token_cost = 100 * (i + 1)
        node.outputs = {
            "result": f"output_{i}",
            "confidence": 0.5 + i * 0.08,
            f"field_{i}": f"value_{i}",
        }
        chron.add_node(node)

        if prev_id:
            edge = CEdge(
                source=prev_id,
                target=node.id,
                data_keys=["previous_output"],
            )
            chron.add_edge(edge)

        prev_id = node.id

    return chron


def create_test_blueprint() -> BlueprintGraph:
    """创建测试用蓝图"""
    bp = BlueprintGraph(name="测试系统", root_id="root")

    root = BNode(id="root", name="系统入口", type=ComponentType.COMPONENT)
    bp.add_node(root)
    bp.root_id = "root"

    # 子模块
    modules = [
        ("intent", "意图识别", ComponentType.MODULE),
        ("analysis", "分析引擎", ComponentType.MODULE),
        ("strategy", "策略引擎", ComponentType.MODULE),
        ("execution", "执行模块", ComponentType.SERVICE),
    ]

    prev_id = "root"
    for mid, name, mtype in modules:
        node = BNode(id=mid, name=name, type=mtype, parent_id=prev_id)
        bp.add_node(node)
        root.children.append(mid)

        edge = BEdge(source=prev_id, target=mid, data_flow_type="control")
        bp.add_edge(edge)

        prev_id = mid

    return bp


# ============================================================
# 类型定义测试
# ============================================================

class TestGraphTypes(unittest.TestCase):
    """测试图模型类型定义"""

    def test_blueprint_graph(self):
        """测试蓝图"""
        bp = BlueprintGraph(name="测试蓝图")
        self.assertEqual(bp.name, "测试蓝图")
        self.assertEqual(len(bp.nodes), 0)

        node = BNode(id="mod1", name="模块1", type=ComponentType.MODULE)
        bp.add_node(node)
        self.assertEqual(len(bp.nodes), 1)
        self.assertIsNotNone(bp.get_node("mod1"))

    def test_architecture_graph(self):
        """测试架构图"""
        arch = ArchitectureGraph(name="测试架构")
        node = ANode(id="step1", name="步骤1", type=NodeType.STEP)
        arch.add_node(node)

        self.assertEqual(len(arch.nodes), 1)
        self.assertEqual(arch.compression_level, 0)

    def test_chronicle_graph(self):
        """测试时间线"""
        chron = create_test_chronicle(3)
        self.assertEqual(len(chron.nodes), 3)
        self.assertEqual(len(chron.sequence), 3)
        self.assertGreater(chron.total_tokens, 0)
        self.assertGreater(chron.total_duration_ms, 0)

    def test_node_metadata(self):
        """测试节点元数据"""
        meta = NodeMetadata(token_cost=100, status=NodeStatus.COMPLETED)
        self.assertEqual(meta.token_cost, 100)
        self.assertEqual(meta.status, NodeStatus.COMPLETED)

        d = meta.to_dict()
        self.assertEqual(d["status"], "completed")

    def test_compression_strategy(self):
        """测试压缩策略枚举"""
        self.assertEqual(CompressionStrategy.VALUE_PRIORITY.value, "value_priority")
        self.assertEqual(CompressionStrategy.CRITICAL_ONLY.value, "critical_only")


# ============================================================
# 压缩器测试
# ============================================================

class TestValueScorer(unittest.TestCase):
    """测试价值评估器"""

    def test_score_nodes(self):
        """测试节点评分"""
        chron = create_test_chronicle(5)
        scorer = ValueScorer()

        scores = {}
        for nid, node in chron.nodes.items():
            score = scorer.score_chronicle_node(node, chron)
            scores[nid] = score
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)

        # Token消耗高的节点评分应该更高
        self.assertGreater(scores["node_4"], scores["node_0"])


class TestGraphCompressor(unittest.TestCase):
    """测试图压缩器"""

    def test_value_priority_compression(self):
        """测试价值优先压缩"""
        chron = create_test_chronicle(6)
        compressor = GraphCompressor(
            strategy=CompressionStrategy.VALUE_PRIORITY,
            target_ratio=0.5,
        )

        result = compressor.compress_chronicle(chron)

        self.assertTrue(result.success)
        self.assertIsNotNone(result.compressed_chronicle)
        self.assertGreater(len(result.preserved_nodes), 0)
        self.assertGreater(len(result.compressed_nodes), 0)
        self.assertLess(result.compression_ratio, 1.0)

    def test_critical_only_compression(self):
        """测试关键节点压缩（只保留首尾）"""
        chron = create_test_chronicle(6)
        compressor = GraphCompressor(strategy=CompressionStrategy.CRITICAL_ONLY)

        result = compressor.compress_chronicle(chron)

        self.assertTrue(result.success)
        # 关键节点模式应该只保留2个（首尾）
        self.assertEqual(len(result.preserved_nodes), 2)

    def test_compressed_nodes_marked(self):
        """测试压缩节点标记"""
        chron = create_test_chronicle(4)
        compressor = GraphCompressor(target_ratio=0.5)

        result = compressor.compress_chronicle(chron)
        compressed_chron = result.compressed_chronicle

        # 检查压缩节点是否被标记
        compressed_count = sum(
            1 for n in compressed_chron.nodes.values()
            if n.is_compressed
        )
        self.assertEqual(compressed_count, len(result.compressed_nodes))

    def test_compression_stats(self):
        """测试压缩统计"""
        chron = create_test_chronicle(6)
        compressor = GraphCompressor(target_ratio=0.5)

        result = compressor.compress_chronicle(chron)

        self.assertGreater(result.original_size, 0)
        self.assertGreater(result.compressed_size, 0)
        self.assertGreater(result.compression_time_ms, 0)
        self.assertLessEqual(result.compression_ratio, 1.0)


# ============================================================
# 展开器测试
# ============================================================

class TestGraphExpander(unittest.TestCase):
    """测试图展开器"""

    def test_blueprint_to_architecture(self):
        """测试B→A展开"""
        bp = create_test_blueprint()
        expander = GraphExpander()

        arch = expander.expand_blueprint_to_architecture(bp)

        self.assertIsNotNone(arch)
        self.assertGreater(len(arch.nodes), 0)
        self.assertEqual(arch.blueprint_id, bp.id)
        self.assertTrue(arch.entry_node_id)

    def test_architecture_to_chronicle(self):
        """测试A→C展开"""
        bp = create_test_blueprint()
        expander = GraphExpander()
        arch = expander.expand_blueprint_to_architecture(bp)

        chron = expander.expand_architecture_to_chronicle(arch, "exec_001")

        self.assertIsNotNone(chron)
        self.assertEqual(chron.architecture_id, arch.id)
        self.assertEqual(chron.execution_id, "exec_001")
        self.assertEqual(len(chron.nodes), len(arch.nodes))

    def test_full_expand(self):
        """测试完整展开 B→A→C"""
        bp = create_test_blueprint()
        expander = GraphExpander()

        arch, chron = expander.expand_full(bp, "test_exec")

        self.assertIsNotNone(arch)
        self.assertIsNotNone(chron)
        self.assertEqual(chron.execution_id, "test_exec")


# ============================================================
# 管理器测试
# ============================================================

class TestGraphStorageManager(unittest.TestCase):
    """测试图存储管理器"""

    def test_create_and_get_blueprint(self):
        """测试创建和获取蓝图"""
        mgr = GraphStorageManager()
        bp = mgr.create_blueprint("测试蓝图", "测试描述")

        self.assertIsNotNone(bp)
        self.assertEqual(bp.name, "测试蓝图")

        fetched = mgr.get_blueprint(bp.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, bp.id)

    def test_expand_from_blueprint(self):
        """测试从蓝图展开"""
        mgr = GraphStorageManager()
        bp = mgr.create_blueprint("测试系统")

        # 添加一些节点
        from core.g_graph_storage import BNode, ComponentType, BEdge
        root = BNode(id="root", name="入口", type=ComponentType.COMPONENT)
        bp.add_node(root)
        bp.root_id = "root"
        mgr.save_blueprint(bp)

        arch = mgr.create_architecture_from_blueprint(bp.id)
        self.assertIsNotNone(arch)
        self.assertEqual(arch.blueprint_id, bp.id)

        chron = mgr.create_chronicle_from_architecture(arch.id)
        self.assertIsNotNone(chron)
        self.assertEqual(chron.architecture_id, arch.id)

    def test_compress_chronicle(self):
        """测试压缩时间线"""
        mgr = GraphStorageManager(default_compression_ratio=0.5)
        bp = mgr.create_blueprint("测试")
        root = BNode(id="root", name="入口", type=ComponentType.COMPONENT)
        bp.add_node(root)
        bp.root_id = "root"

        # 添加更多节点以支持压缩
        for i in range(5):
            n = BNode(id=f"mod_{i}", name=f"模块{i}", type=ComponentType.MODULE)
            bp.add_node(n)
            root.children.append(f"mod_{i}")
        mgr.save_blueprint(bp)

        arch = mgr.create_architecture_from_blueprint(bp.id)
        chron = mgr.create_chronicle_from_architecture(arch.id)

        result = mgr.compress_chronicle(chron.id)
        self.assertIsNotNone(result)
        self.assertTrue(result.success)

    def test_memory_mode(self):
        """测试内存模式"""
        mgr = GraphStorageManager()
        stats = mgr.get_stats()

        self.assertEqual(stats["storage_path"], "memory_only")
        self.assertEqual(stats["blueprints_count"], 0)

    def test_stats(self):
        """测试统计信息"""
        mgr = GraphStorageManager()
        mgr.create_blueprint("蓝图1")
        mgr.create_blueprint("蓝图2")

        stats = mgr.get_stats()
        self.assertEqual(stats["blueprints_count"], 2)
        self.assertEqual(stats["default_strategy"], "value_priority")

    def test_persistence(self):
        """测试持久化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = GraphStorageManager(storage_path=tmpdir)
            bp = mgr.create_blueprint("持久化测试")
            mgr.save_to_disk()

            # 创建新的管理器并加载
            mgr2 = GraphStorageManager(storage_path=tmpdir)
            loaded = mgr2.load_from_disk()
            self.assertTrue(loaded)


# ============================================================
# 集成测试（压缩+展开往返）
# ============================================================

class TestCompressExpandRoundTrip(unittest.TestCase):
    """测试压缩和展开的往返"""

    def test_compress_preserves_structure(self):
        """测试压缩后保留基本结构"""
        chron = create_test_chronicle(6)
        compressor = GraphCompressor(target_ratio=0.5)

        result = compressor.compress_chronicle(chron)
        compressed = result.compressed_chronicle

        # 节点数量应该不变（压缩不是删除，而是标记）
        self.assertEqual(len(compressed.nodes), len(chron.nodes))
        # 但部分节点被标记为压缩
        self.assertTrue(any(n.is_compressed for n in compressed.nodes.values()))

    def test_full_lifecycle(self):
        """测试完整生命周期：创建 → 展开 → 执行 → 压缩"""
        mgr = GraphStorageManager(default_compression_ratio=0.4)

        # 1. 创建蓝图
        bp = mgr.create_blueprint("交易分析系统")
        root = BNode(id="root", name="系统入口", type=ComponentType.COMPONENT)
        bp.add_node(root)
        bp.root_id = "root"

        modules = ["data", "analysis", "strategy", "risk", "execution", "report"]
        for mid in modules:
            n = BNode(id=mid, name=mid, type=ComponentType.MODULE)
            bp.add_node(n)
            root.children.append(mid)
        mgr.save_blueprint(bp)

        # 2. 展开
        arch, chron = mgr.expand_blueprint(bp.id, "exec_001")
        self.assertIsNotNone(arch)
        self.assertIsNotNone(chron)

        # 3. 模拟执行更新
        for nid in chron.nodes:
            mgr.update_chronicle_node(chron.id, nid, {
                "status": NodeStatus.COMPLETED,
                "token_cost": 100,
                "outputs": {"result": "ok"},
            })

        # 4. 压缩
        result = mgr.compress_chronicle(chron.id)
        self.assertIsNotNone(result)
        self.assertTrue(result.success)

        # 5. 验证统计
        stats = mgr.get_stats()
        self.assertGreater(stats["compressed_chronicles"], 0)


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
