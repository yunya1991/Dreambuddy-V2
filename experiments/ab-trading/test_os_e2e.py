#!/usr/bin/env python3
"""
端到端集成测试 + 图压缩贡献评测

位置: experiments/ab-trading/test_os_e2e.py

测试内容：
1. 操作系统端到端流程（S → A → C → G）
2. G层桥接器功能验证
3. 自动归档压缩
4. 历史检索与经验复用
5. 图压缩对操作系统的贡献评测
   - 存储空间节省
   - 上下文效率提升
   - 记忆复用价值
"""

import sys
import os
import unittest
import time
from typing import Dict, Any, List
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.g_graph_storage import (
    # 类型
    BlueprintGraph,
    ArchitectureGraph,
    ChronicleGraph,
    BNode,
    ANode,
    CNode,
    NodeStatus,
    ComponentType,
    CompressionStrategy,
    # 组件
    GraphStorageManager,
    GraphStorageBridge,
    HistoryRetriever,
    HistoryRecord,
    SimilarTaskMatch,
    ExecutionPattern,
)


# ============================================================
# 模拟数据
# ============================================================

@dataclass
class MockObjective:
    title: str = ""
    description: str = ""


@dataclass
class MockExecutionBlueprint:
    node_sequence: List[str] = None
    kr_to_nodes: Dict[str, List[str]] = None

    def __post_init__(self):
        if self.node_sequence is None:
            self.node_sequence = []
        if self.kr_to_nodes is None:
            self.kr_to_nodes = {}


@dataclass
class MockIntentResult:
    objective: MockObjective = None
    blueprint: MockExecutionBlueprint = None

    def __post_init__(self):
        if self.objective is None:
            self.objective = MockObjective()
        if self.blueprint is None:
            self.blueprint = MockExecutionBlueprint()


def create_mock_intent(
    title: str = "股票分析任务",
    description: str = "分析股票市场趋势，制定交易策略",
    nodes: List[str] = None,
) -> MockIntentResult:
    """创建模拟意图"""
    if nodes is None:
        nodes = ["data_collection", "market_analysis", "strategy_build", "risk_check", "execution_plan"]

    return MockIntentResult(
        objective=MockObjective(title=title, description=description),
        blueprint=MockExecutionBlueprint(
            node_sequence=nodes,
            kr_to_nodes={
                "kr_data": ["data_collection"],
                "kr_analysis": ["market_analysis"],
                "kr_strategy": ["strategy_build", "risk_check"],
                "kr_exec": ["execution_plan"],
            }
        ),
    )


# ============================================================
# G层桥接器测试
# ============================================================

class TestGraphStorageBridge(unittest.TestCase):
    """测试G层桥接器"""

    def test_start_execution(self):
        """测试开始执行（完整流程）"""
        bridge = GraphStorageBridge()
        intent = create_mock_intent()

        bp, arch, chron = bridge.start_execution(intent)

        self.assertIsNotNone(bp)
        self.assertIsNotNone(arch)
        self.assertIsNotNone(chron)
        self.assertEqual(bp.name, "股票分析任务")
        self.assertGreater(len(chron.nodes), 0)

        # 检查活跃执行
        self.assertEqual(len(bridge._active_executions), 1)

    def test_update_chronicle_node(self):
        """测试更新时间线节点"""
        bridge = GraphStorageBridge()
        intent = create_mock_intent(nodes=["step1", "step2", "step3"])
        bp, arch, chron = bridge.start_execution(intent)
        exec_id = chron.execution_id

        # 更新节点
        success = bridge.update_chronicle_node(
            exec_id,
            "step1",
            status=NodeStatus.COMPLETED,
            start_time=1000.0,
            end_time=1500.0,
            token_cost=200,
            outputs={"result": "step1_output"},
        )

        self.assertTrue(success)

    def test_archive_execution(self):
        """测试归档执行"""
        bridge = GraphStorageBridge(auto_compress=True)
        intent = create_mock_intent(nodes=["n1", "n2", "n3", "n4", "n5"])
        bp, arch, chron = bridge.start_execution(intent)
        exec_id = chron.execution_id

        # 归档
        result = bridge.archive_execution(exec_id, compress=True)

        self.assertIsNotNone(result)
        self.assertTrue(result["archived"])
        self.assertTrue(result["compressed"])
        self.assertEqual(len(bridge._active_executions), 0)

    def test_stats(self):
        """测试统计信息"""
        bridge = GraphStorageBridge()
        stats = bridge.get_stats()

        self.assertIn("active_executions", stats)
        self.assertIn("auto_compress", stats)
        self.assertIn("blueprints_count", stats)


# ============================================================
# 历史检索器测试
# ============================================================

class TestHistoryRetriever(unittest.TestCase):
    """测试历史检索器"""

    def _setup_with_history(self, count: int = 5):
        """创建带历史记录的检索器"""
        storage = GraphStorageManager()
        retriever = HistoryRetriever(storage)

        for i in range(count):
            bp = storage.create_blueprint(f"任务_{i}", f"这是第{i}个交易分析任务")
            root = BNode(id="root", name="入口", type=ComponentType.COMPONENT)
            bp.add_node(root)
            bp.root_id = "root"

            for j in range(3 + i):
                n = BNode(id=f"mod_{j}", name=f"模块{j}", type=ComponentType.MODULE)
                bp.add_node(n)
                root.children.append(f"mod_{j}")
            storage.save_blueprint(bp)

            arch = storage.create_architecture_from_blueprint(bp.id)
            chron = storage.create_chronicle_from_architecture(arch.id, f"exec_{i}")

            tags = ["trading", "analysis"] if i % 2 == 0 else ["research", "data"]
            retriever.add_history(
                bp, arch, chron,
                success=True,
                summary=f"任务{i}执行完成",
                tags=tags,
            )

        return storage, retriever

    def test_add_and_list_history(self):
        """测试添加和列出历史"""
        _, retriever = self._setup_with_history(5)

        records = retriever.list_history(limit=10)
        self.assertEqual(len(records), 5)
        self.assertIsInstance(records[0], HistoryRecord)

    def test_get_history(self):
        """测试获取单条历史"""
        _, retriever = self._setup_with_history(3)

        all_records = retriever.list_history()
        first_id = all_records[0].execution_id

        record = retriever.get_history(first_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.execution_id, first_id)

    def test_find_similar_tasks(self):
        """测试相似任务检索"""
        _, retriever = self._setup_with_history(5)

        # 搜索"交易分析"
        matches = retriever.find_similar_tasks("交易 分析", top_k=3)

        self.assertIsInstance(matches, list)
        self.assertLessEqual(len(matches), 3)
        for m in matches:
            self.assertIsInstance(m, SimilarTaskMatch)
            self.assertGreater(m.similarity, 0.0)

    def test_filter_by_tags(self):
        """测试按标签过滤"""
        _, retriever = self._setup_with_history(5)

        trading_records = retriever.list_history(tags=["trading"])
        self.assertGreater(len(trading_records), 0)
        for r in trading_records:
            self.assertIn("trading", r.tags)

    def test_extract_reusable_knowledge(self):
        """测试提取可复用知识"""
        storage, retriever = self._setup_with_history(3)

        all_records = retriever.list_history()
        first_id = all_records[0].execution_id

        knowledge = retriever.extract_reusable_knowledge(first_id)
        self.assertIn("execution_id", knowledge)
        self.assertIn("node_outputs", knowledge)
        self.assertIn("key_insights", knowledge)

    def test_discover_patterns(self):
        """测试模式发现"""
        _, retriever = self._setup_with_history(5)

        patterns = retriever.discover_patterns(min_frequency=2)
        self.assertIsInstance(patterns, list)
        for p in patterns:
            self.assertIsInstance(p, ExecutionPattern)
            self.assertGreaterEqual(p.frequency, 2)

    def test_stats(self):
        """测试统计"""
        _, retriever = self._setup_with_history(10)

        stats = retriever.get_stats()
        self.assertEqual(stats["total_records"], 10)
        self.assertIn("success_rate", stats)
        self.assertIn("avg_tokens", stats)
        self.assertIn("avg_duration_ms", stats)


# ============================================================
# 端到端操作系统测试
# ============================================================

class TestOSEndToEnd(unittest.TestCase):
    """操作系统端到端测试"""

    def test_full_os_lifecycle(self):
        """测试完整操作系统生命周期

        流程：
        1. 意图识别（S层模拟）→ 创建 G.B
        2. 图编排（A层模拟）→ 创建 G.A
        3. 执行（C层模拟）→ 写入 G.C
        4. 完成后自动归档压缩
        5. 历史检索与经验复用
        """
        # 初始化
        storage = GraphStorageManager()
        bridge = GraphStorageBridge(
            storage_manager=storage,
            auto_archive=True,
            auto_compress=True,
            compression_ratio=0.5,
        )
        history = HistoryRetriever(storage)

        # === Step 1: 意图识别 → G.B ===
        intent = create_mock_intent(
            title="BTC趋势分析",
            description="分析比特币市场趋势，制定短期交易策略",
        )
        bp, arch, chron = bridge.start_execution(intent)
        exec_id = chron.execution_id

        self.assertIsNotNone(bp)
        self.assertIsNotNone(arch)
        self.assertIsNotNone(chron)

        # === Step 2: 执行中更新（模拟C层） ===
        node_count = len(chron.nodes)
        for i, nid in enumerate(chron.sequence):
            bridge.update_chronicle_node(
                exec_id,
                nid.replace("a_", "").replace("c_", ""),
                status=NodeStatus.RUNNING,
                start_time=time.time(),
            )
            # 模拟执行
            time.sleep(0.001)
            bridge.update_chronicle_node(
                exec_id,
                nid.replace("a_", "").replace("c_", ""),
                status=NodeStatus.COMPLETED,
                end_time=time.time(),
                token_cost=100 * (i + 1),
                outputs={
                    "step": i + 1,
                    "result": f"step_{i}_output",
                    "confidence": 0.7 + i * 0.05,
                    "insight": f"第{i+1}步的关键发现",
                },
            )

        # === Step 3: 归档压缩 ===
        archive_result = bridge.finish_execution(exec_id)

        self.assertIsNotNone(archive_result)
        self.assertTrue(archive_result["archived"])
        self.assertTrue(archive_result["compressed"])

        # === Step 4: 历史记录 ===
        chron_after = storage.get_chronicle(chron.id)
        history.add_history(
            bp, arch, chron_after,
            success=True,
            summary="BTC趋势分析完成，发现上涨趋势",
            tags=["crypto", "trading", "btc"],
        )

        # === Step 5: 历史检索 ===
        matches = history.find_similar_tasks("比特币 趋势 交易", top_k=3)
        self.assertGreater(len(matches), 0)

        # === Step 6: 经验复用 ===
        knowledge = history.extract_reusable_knowledge(exec_id)
        self.assertIn("key_insights", knowledge)
        self.assertGreater(len(knowledge["key_insights"]), 0)

        # === 验证 ===
        stats = storage.get_stats()
        self.assertGreater(stats["blueprints_count"], 0)
        self.assertGreater(stats["compressed_chronicles"], 0)

    def test_multiple_executions(self):
        """测试多次执行积累历史"""
        storage = GraphStorageManager()
        bridge = GraphStorageBridge(storage_manager=storage, auto_compress=True)
        history = HistoryRetriever(storage)

        tasks = [
            ("BTC行情分析", "分析比特币行情", ["crypto", "btc"]),
            ("ETH趋势判断", "分析以太坊趋势", ["crypto", "eth"]),
            ("A股市场扫描", "扫描A股市场机会", ["stock", "china"]),
            ("美股财报分析", "分析美股财报", ["stock", "us"]),
            ("黄金走势预测", "预测黄金价格走势", ["commodity", "gold"]),
        ]

        for title, desc, tags in tasks:
            intent = create_mock_intent(title=title, description=desc)
            bp, arch, chron = bridge.start_execution(intent)
            exec_id = chron.execution_id

            # 模拟执行
            for nid in chron.sequence:
                bridge.update_chronicle_node(
                    exec_id,
                    nid.replace("a_", "").replace("c_", ""),
                    status=NodeStatus.COMPLETED,
                    token_cost=150,
                    outputs={"result": "done"},
                )

            bridge.finish_execution(exec_id)
            chron_after = storage.get_chronicle(chron.id)
            history.add_history(bp, arch, chron_after, success=True, tags=tags, summary=f"{title}完成")

        # 验证
        all_records = history.list_history(limit=20)
        self.assertEqual(len(all_records), 5)

        # 搜索相似
        matches = history.find_similar_tasks("加密货币 行情", top_k=3)
        self.assertGreater(len(matches), 0)

        # 按标签过滤
        crypto_records = history.list_history(tags=["crypto"])
        self.assertEqual(len(crypto_records), 2)

        # 模式发现
        patterns = history.discover_patterns(min_frequency=2)
        self.assertGreater(len(patterns), 0)


# ============================================================
# 图压缩贡献评测
# ============================================================

class TestCompressionContribution(unittest.TestCase):
    """图压缩对操作系统的贡献评测"""

    def test_storage_savings(self):
        """评测：存储空间节省"""
        storage = GraphStorageManager()
        bridge = GraphStorageBridge(storage_manager=storage)

        # 创建多个执行
        total_tokens_original = 0
        num_executions = 20

        for i in range(num_executions):
            intent = create_mock_intent(
                title=f"任务_{i}",
                nodes=[f"step_{j}" for j in range(6 + i % 4)],
            )
            bp, arch, chron = bridge.start_execution(intent)
            exec_id = chron.execution_id

            # 模拟执行，产生数据
            for j, nid in enumerate(chron.sequence):
                bridge.update_chronicle_node(
                    exec_id,
                    nid.replace("a_", "").replace("c_", ""),
                    status=NodeStatus.COMPLETED,
                    token_cost=100 + j * 50,
                    outputs={
                        "result": f"output_{j}" * 10,
                        "data": {"field1": "x" * 50, "field2": "y" * 30},
                    },
                )

            chron_before = storage.get_chronicle(chron.id)
            total_tokens_original += chron_before.total_tokens

            # 压缩
            bridge.archive_execution(exec_id, compress=True)

        # 计算节省
        stats = storage.get_stats()
        compressed_count = stats["compressed_chronicles"]

        # 压缩率评测
        self.assertEqual(compressed_count, num_executions)

        # 打印评测结果
        print(f"\n{'='*60}")
        print("  图压缩贡献评测 - 存储空间节省")
        print(f"{'='*60}")
        print(f"  执行数量: {num_executions}")
        print(f"  原始总Token: {total_tokens_original}")
        print(f"  压缩策略: 价值优先 (目标50%)")
        print(f"  压缩后数量: {compressed_count}")
        print(f"{'='*60}")

    def test_context_efficiency(self):
        """评测：上下文效率提升

        模拟长期运行场景，评估压缩对上下文窗口的利用效率。
        """
        storage = GraphStorageManager()
        bridge = GraphStorageBridge(storage_manager=storage)
        history = HistoryRetriever(storage)

        # 模拟100次执行
        num_executions = 50
        nodes_per_exec = 8

        print(f"\n{'='*60}")
        print("  图压缩贡献评测 - 上下文效率")
        print(f"{'='*60}")
        print(f"  模拟执行次数: {num_executions}")
        print(f"  每次节点数: {nodes_per_exec}")

        # 无压缩的理论总大小（线性增长）
        theoretical_linear = 0
        # 有压缩的实际大小（对数级增长）
        actual_with_compression = 0

        for i in range(num_executions):
            intent = create_mock_intent(
                title=f"任务_{i}",
                nodes=[f"step_{j}" for j in range(nodes_per_exec)],
            )
            bp, arch, chron = bridge.start_execution(intent)
            exec_id = chron.execution_id

            for j, nid in enumerate(chron.sequence):
                bridge.update_chronicle_node(
                    exec_id,
                    nid.replace("a_", "").replace("c_", ""),
                    status=NodeStatus.COMPLETED,
                    token_cost=200,
                    outputs={"result": f"output_{j}"},
                )

            chron_before = storage.get_chronicle(chron.id)
            theoretical_linear += chron_before.total_tokens

            # 压缩归档
            result = bridge.archive_execution(exec_id, compress=True)
            if result and result.get("compression_result"):
                cr = result["compression_result"]
                actual_with_compression += cr.get("compressed_size", 0)

            history.add_history(
                bp, arch, chron_before,
                success=True,
                tags=["test"],
                summary=f"任务{i}",
            )

        # 计算节省
        if theoretical_linear > 0:
            savings_ratio = 1 - (actual_with_compression / theoretical_linear)
        else:
            savings_ratio = 0

        print(f"  理论线性总大小: {theoretical_linear} tokens")
        print(f"  压缩后总大小: {actual_with_compression} tokens (估算)")
        print(f"  节省比例: {savings_ratio:.1%}")
        print(f"{'='*60}")

        # 长期来看是对数级 vs 线性级
        self.assertGreater(theoretical_linear, 0)

    def test_memory_reuse_value(self):
        """评测：记忆复用价值

        评估历史经验复用时的效率提升。
        """
        storage = GraphStorageManager()
        bridge = GraphStorageBridge(storage_manager=storage)
        history = HistoryRetriever(storage)

        print(f"\n{'='*60}")
        print("  图压缩贡献评测 - 记忆复用价值")
        print(f"{'='*60}")

        # Phase 1: 积累10个相似任务
        for i in range(10):
            intent = create_mock_intent(
                title=f"股票分析_{i}",
                description="分析股票市场，制定交易策略",
                nodes=["data", "analysis", "strategy", "risk", "exec"],
            )
            bp, arch, chron = bridge.start_execution(intent)
            exec_id = chron.execution_id

            for j, nid in enumerate(chron.sequence):
                bridge.update_chronicle_node(
                    exec_id,
                    nid.replace("a_", "").replace("c_", ""),
                    status=NodeStatus.COMPLETED,
                    token_cost=300,
                    outputs={
                        "result": f"step_{j}_result",
                        "insight": f"第{j}步的洞察",
                    },
                )

            bridge.finish_execution(exec_id)
            chron_after = storage.get_chronicle(chron.id)
            history.add_history(
                bp, arch, chron_after,
                success=True,
                tags=["trading", "stock", "analysis"],
                summary=f"股票分析任务{i}完成",
            )

        # Phase 2: 新任务检索相似
        new_task_desc = "分析A股市场，制定交易策略"
        matches = history.find_similar_tasks(new_task_desc, top_k=3)

        print(f"  历史任务数: 10")
        print(f"  新任务: {new_task_desc}")
        print(f"  找到相似任务: {len(matches)}")

        if matches:
            print(f"  最高相似度: {matches[0].similarity:.2f}")
            print(f"  匹配原因: {matches[0].match_reason}")

            # 提取可复用知识
            top_match = matches[0]
            knowledge = history.extract_reusable_knowledge(top_match.record.execution_id)
            print(f"  可复用节点数: {len(knowledge.get('node_outputs', {}))}")
            print(f"  关键洞察数: {len(knowledge.get('key_insights', []))}")

        # 模式发现
        patterns = history.discover_patterns(min_frequency=3)
        print(f"  发现模式数: {len(patterns)}")
        if patterns:
            print(f"  Top模式频率: {patterns[0].frequency}")
            print(f"  Top模式平均耗时: {patterns[0].avg_duration_ms:.0f}ms")

        print(f"{'='*60}")

        # 验证
        self.assertGreater(len(matches), 0)
        self.assertGreater(len(patterns), 0)

    def test_compression_strategy_comparison(self):
        """评测：不同压缩策略对比"""
        storage = GraphStorageManager()

        print(f"\n{'='*60}")
        print("  图压缩贡献评测 - 压缩策略对比")
        print(f"{'='*60}")

        # 创建测试数据
        bp = storage.create_blueprint("对比测试")
        root = BNode(id="root", name="入口", type=ComponentType.COMPONENT)
        bp.add_node(root)
        bp.root_id = "root"
        for i in range(10):
            n = BNode(id=f"mod_{i}", name=f"模块{i}", type=ComponentType.MODULE)
            bp.add_node(n)
            root.children.append(f"mod_{i}")
        storage.save_blueprint(bp)

        arch = storage.create_architecture_from_blueprint(bp.id)

        strategies = [
            (CompressionStrategy.VALUE_PRIORITY, "价值优先"),
            (CompressionStrategy.PATH_PRESERVE, "路径保留"),
            (CompressionStrategy.CRITICAL_ONLY, "关键节点"),
            (CompressionStrategy.SEMANTIC_AWARE, "语义感知"),
        ]

        ratios = [0.3, 0.5, 0.7]

        print(f"{'策略':<12} {'压缩率':<8} {'保留节点':<10} {'压缩节点':<10}")
        print("-" * 50)

        for strategy, name in strategies:
            for ratio in ratios:
                chron = storage.create_chronicle_from_architecture(arch.id, f"test_{strategy.value}_{ratio}")
                compressor = storage.compressor
                compressor.strategy = strategy
                compressor.target_ratio = ratio

                result = compressor.compress_chronicle(chron)
                if result.success:
                    preserved = len(result.preserved_nodes)
                    compressed = len(result.compressed_nodes)
                    print(f"{name:<12} {ratio:<8.0%} {preserved:<10} {compressed:<10}")

        print(f"{'='*60}")

        self.assertTrue(True)  # 只要不报错就通过


# ============================================================
# 运行测试
# ============================================================

if __name__ == '__main__':
    unittest.main(verbosity=2)
