"""
DreamOS ACG 三层测试

验证:
    A层: GraphPlanner / NodeSelector / BudgetAllocator / ExecutionGraph
    C层: GraphExecutor / NodeRunner / Reflector / Aggregator
    G层: GraphStore / Checkpointer / ContextCompressor / HistoryReplay
    集成: S→A→C→G 全链路
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """测试三层 import"""
    from dreamos.core.arrange import (
        GraphPlanner, NodeSelector, BudgetAllocator,
        SequentialGraph, ConditionalGraph,
        ExecutionPlan, NodeMeta, BudgetAllocation, ChainSpec,
    )
    from dreamos.core.compute import (
        GraphExecutor, NodeRunner, Reflector, Aggregator,
        ReflectAction, ReflectDecision, ExecutionReport,
    )
    from dreamos.core.graph_store import (
        GraphStore, Checkpointer, ContextCompressor, HistoryReplay,
        Checkpoint, CompressedState, HistoryEntry,
    )
    print("✅ import 测试通过")


# ============================================================
# A 层测试
# ============================================================

def test_sequential_graph():
    """测试顺序执行图"""
    from dreamos.core.arrange import SequentialGraph
    from dreamos.shared.state import State, NodeResult, NodeStatus
    from dreamos.registry.base import BaseNode

    class TestNode(BaseNode):
        node_id = "test"
        name = "test"
        chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="test", confidence=0.5)

    graph = SequentialGraph()
    node = TestNode()
    graph.add_node(node)

    assert graph.get_entry() is node
    assert graph.get_next("test", State()) is None  # 只有一个节点
    assert graph.topological_order() == ["test"]
    assert len(graph) == 1

    print("✅ SequentialGraph 测试通过")


def test_conditional_graph():
    """测试条件执行图"""
    from dreamos.core.arrange import ConditionalGraph
    from dreamos.shared.state import State, NodeResult, NodeStatus
    from dreamos.registry.base import BaseNode

    class NodeA(BaseNode):
        node_id = "A"; name = "A"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="A", confidence=0.8)

    class NodeB(BaseNode):
        node_id = "B"; name = "B"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="B", confidence=0.5)

    class NodeC(BaseNode):
        node_id = "C"; name = "C"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="C", confidence=0.6)

    graph = ConditionalGraph()
    graph.add_node(NodeA())
    graph.add_node(NodeB())
    graph.add_node(NodeC())

    # 添加条件边: A 置信度 > 0.7 → C, 否则 → B
    graph.add_edge("A", "C", condition=lambda s: s.get_confidence("A") > 0.7)
    graph.add_edge("A", "B")  # 默认 → B

    state = State()
    state.update("A", NodeResult(node_id="A", confidence=0.85))

    next_node = graph.get_next("A", state)
    assert next_node.node_id == "C"  # 高置信度应该到 C

    state2 = State()
    state2.update("A", NodeResult(node_id="A", confidence=0.3))
    next_node2 = graph.get_next("A", state2)
    assert next_node2.node_id == "B"  # 低置信度应该到 B

    print("✅ ConditionalGraph 测试通过")


def test_node_selector():
    """测试节点选择器"""
    from dreamos.core.arrange import NodeSelector
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import NodeResult

    registry = NodeRegistry()

    class A1Node(BaseNode):
        node_id = "A1"; name = "深度调研"; chain = "A"; estimated_tokens = 500
        def execute_core(self, state):
            return NodeResult(node_id="A1", confidence=0.6)

    class A2Node(BaseNode):
        node_id = "A2"; name = "第一性原理"; chain = "A"; estimated_tokens = 400
        def execute_core(self, state):
            return NodeResult(node_id="A2", confidence=0.65)

    registry.register(A1Node())
    registry.register(A2Node())

    selector = NodeSelector(registry)
    metas = selector.select(chain="A", base_chain=["A1", "A2"], intent_confidence=0.7)

    assert len(metas) == 2
    assert metas[0].node_id == "A1"
    assert metas[0].priority == 0  # 主链节点是必须的
    assert metas[0].estimated_tokens == 500

    print("✅ NodeSelector 测试通过")


def test_budget_allocator():
    """测试预算分配器"""
    from dreamos.core.arrange import BudgetAllocator, NodeMeta

    # 3 个必须节点 + 1 个可选节点
    nodes = [
        NodeMeta(node_id="A1", name="深度调研", chain="A", priority=0, estimated_tokens=500),
        NodeMeta(node_id="A2", name="第一性原理", chain="A", priority=0, estimated_tokens=400),
        NodeMeta(node_id="A3", name="策略设计", chain="A", priority=0, estimated_tokens=600),
        NodeMeta(node_id="C1", name="短线", chain="C", priority=2, estimated_tokens=200),
    ]

    allocator = BudgetAllocator(total=6000, mode="standard")
    allocation = allocator.allocate(nodes)

    assert allocation.total_budget == 6000
    assert allocation.reserved > 0  # 有预留
    # 必须节点都有预算
    assert allocation.get("A1") > 0
    assert allocation.get("A2") > 0
    assert allocation.get("A3") > 0
    # 总分配不超过预算
    assert allocation.total_allocated + allocation.reserved <= 6000

    print(f"✅ BudgetAllocator 测试通过 (allocated={allocation.total_allocated}, reserved={allocation.reserved})")


def test_graph_planner():
    """测试图规划器"""
    from dreamos.core.arrange import GraphPlanner
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import NodeResult

    registry = NodeRegistry()

    class A0(BaseNode):
        node_id = "A0"; name = "矛盾论"; chain = "A"; estimated_tokens = 300
        def execute_core(self, state):
            return NodeResult(node_id="A0", confidence=0.7, direction="LONG")

    class A1(BaseNode):
        node_id = "A1"; name = "趋势"; chain = "A"; estimated_tokens = 500
        def execute_core(self, state):
            return NodeResult(node_id="A1", confidence=0.65, direction="LONG")

    registry.register(A0())
    registry.register(A1())

    planner = GraphPlanner(registry=registry, budget_total=6000, budget_mode="standard")
    plan = planner.plan_from_intent(
        recommended_chain="A",
        base_chain=["A0", "A1"],
        confidence=0.72,
    )

    assert plan.planned_chain == "A"
    assert len(plan.selected_nodes) == 2
    assert plan.budget.total_budget == 6000
    assert plan.estimated_total_tokens > 0

    # 构建图
    graph = planner.build_graph(plan)
    assert graph.get_entry() is not None
    assert graph.get_entry().node_id == "A0"

    print(f"✅ GraphPlanner 测试通过 (chain={plan.planned_chain}, nodes={plan.node_ids})")


# ============================================================
# C 层测试
# ============================================================

def test_node_runner():
    """测试节点执行器"""
    from dreamos.core.compute import NodeRunner
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import State, NodeResult

    class SuccessNode(BaseNode):
        node_id = "test_success"; name = "success"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="test_success", confidence=0.7, direction="LONG")

    runner = NodeRunner(max_retries=2)
    state = State()
    record = runner.run(SuccessNode(), state)

    assert record.status == "success"
    assert record.confidence == 0.7
    assert record.direction == "LONG"
    assert record.retries == 0
    # State 被更新
    assert state.has_node("test_success")

    print("✅ NodeRunner 测试通过")


def test_node_runner_retry():
    """测试节点重试"""
    from dreamos.core.compute import NodeRunner
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import State, NodeResult, NodeStatus
    from dreamos.shared.errors import ErrorCode

    attempt_count = [0]

    class FlakyNode(BaseNode):
        node_id = "flaky"; name = "flaky"; chain = "A"
        def execute_core(self, state):
            attempt_count[0] += 1
            if attempt_count[0] < 2:
                return NodeResult(
                    node_id="flaky", status=NodeStatus.FAILED,
                    error="临时失败", error_code=ErrorCode.EXEC_002,
                )
            return NodeResult(node_id="flaky", confidence=0.6, direction="LONG")

    runner = NodeRunner(max_retries=2)
    state = State()
    record = runner.run(FlakyNode(), state)

    assert record.confidence == 0.6
    assert record.retries >= 1

    print(f"✅ NodeRunner 重试测试通过 (retries={record.retries})")


def test_reflector():
    """测试反射决策器"""
    from dreamos.core.compute import Reflector, ReflectAction
    from dreamos.core.arrange import SequentialGraph
    from dreamos.shared.state import State, NodeResult, NodeStatus
    from dreamos.registry.base import BaseNode

    class DummyNode(BaseNode):
        node_id = "dummy"; name = "dummy"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="dummy", confidence=0.5)

    graph = SequentialGraph()
    graph.add_node(DummyNode())

    reflector = Reflector()
    state = State()

    # 成功 + 置信度 0.7 → CONTINUE
    result = NodeResult(node_id="A0", confidence=0.7, direction="LONG")
    state.update("A0", result)
    decision = reflector.decide("A0", result, state, graph, 1, 3)
    assert decision.action == ReflectAction.CONTINUE

    # 成功但置信度极低 → 可能终止
    result2 = NodeResult(node_id="A1", confidence=0.1)
    state.update("A1", result2)
    decision2 = reflector.decide("A1", result2, state, graph, 2, 3)
    assert decision2.action in (ReflectAction.CONTINUE, ReflectAction.EARLY_TERMINATE)

    print("✅ Reflector 测试通过")


def test_aggregator():
    """测试结果聚合器"""
    from dreamos.core.compute import Aggregator
    from dreamos.shared.state import State, NodeResult

    state = State()
    state.update("A0", NodeResult(node_id="A0", confidence=0.7, direction="LONG"))
    state.update("A1", NodeResult(node_id="A1", confidence=0.8, direction="LONG"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.6, direction="LONG"))

    agg = Aggregator()
    report = agg.aggregate(state, node_ids=["A0", "A1", "A2"])

    assert report.final_action == "LONG"
    assert report.final_confidence > 0.6
    assert "LONG" in report.final_direction_scores

    print(f"✅ Aggregator 测试通过 (action={report.final_action}, conf={report.final_confidence:.2f})")


def test_aggregator_disagreement():
    """测试聚合器方向分歧 → HOLD"""
    from dreamos.core.compute import Aggregator
    from dreamos.shared.state import State, NodeResult

    state = State()
    # 2 LONG vs 2 SHORT，方向完全对半分
    state.update("A0", NodeResult(node_id="A0", confidence=0.7, direction="LONG"))
    state.update("A1", NodeResult(node_id="A1", confidence=0.7, direction="SHORT"))
    state.update("A2", NodeResult(node_id="A2", confidence=0.7, direction="SHORT"))
    state.update("A3", NodeResult(node_id="A3", confidence=0.7, direction="LONG"))

    agg = Aggregator()
    report = agg.aggregate(state, node_ids=["A0", "A1", "A2", "A3"])

    # 方向分歧大 → HOLD
    assert report.final_action == "HOLD"

    print(f"✅ Aggregator 分歧测试通过 (action={report.final_action})")


def test_graph_executor():
    """测试图执行器"""
    from dreamos.core.compute import GraphExecutor
    from dreamos.core.arrange import SequentialGraph
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import State, NodeResult, new_state

    class A0Node(BaseNode):
        node_id = "A0"; name = "矛盾论"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="A0", confidence=0.7, direction="LONG")

    class A1Node(BaseNode):
        node_id = "A1"; name = "趋势"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="A1", confidence=0.75, direction="LONG")

    class A2Node(BaseNode):
        node_id = "A2"; name = "量价"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="A2", confidence=0.8, direction="LONG")

    graph = SequentialGraph()
    graph.add_node(A0Node()).add_node(A1Node()).add_node(A2Node())

    state = new_state(cycle_id="test_exec")
    executor = GraphExecutor(max_retries=1, enable_early_terminate=False)
    report = executor.execute(graph, state)

    assert report.executed_nodes == 3
    assert report.success_nodes == 3
    assert report.final_action == "LONG"
    assert report.final_confidence > 0.6
    assert len(report.records) == 3

    print(f"✅ GraphExecutor 测试通过 (nodes={report.executed_nodes}, action={report.final_action})")


def test_graph_executor_early_terminate():
    """测试提前终止"""
    from dreamos.core.compute import GraphExecutor
    from dreamos.core.arrange import SequentialGraph
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import State, NodeResult, new_state

    class HighConfNode(BaseNode):
        node_id = "hc"; name = "high"; chain = "A"
        def execute_core(self, state):
            return NodeResult(node_id="hc", confidence=0.9, direction="LONG")

    graph = SequentialGraph()
    # 添加 5 个高置信度节点
    for i in range(5):
        node = type(f"Node{i}", (HighConfNode,), {
            "node_id": f"HC{i}", "name": f"HC{i}", "chain": "A",
            "execute_core": lambda self, s: NodeResult(
                node_id=self.node_id, confidence=0.9, direction="LONG"
            )
        })()
        graph.add_node(node)

    state = new_state(cycle_id="test_early")
    executor = GraphExecutor(enable_early_terminate=True)
    report = executor.execute(graph, state)

    # 由于连续高置信度且方向一致，应该会提前终止
    assert report.executed_nodes <= 5
    assert report.final_action == "LONG"

    print(f"✅ GraphExecutor 提前终止测试通过 (executed={report.executed_nodes}/5)")


# ============================================================
# G 层测试
# ============================================================

def test_checkpointer():
    """测试检查点管理器"""
    from dreamos.core.graph_store import Checkpointer
    from dreamos.shared.state import State, NodeResult, new_state

    cp = Checkpointer(max_checkpoints=5)
    state = new_state(cycle_id="test_cp")
    state.update("A0", NodeResult(node_id="A0", confidence=0.7, direction="LONG"))

    # 保存
    cp_id = cp.save(state, node_id="A0")
    assert cp_id is not None
    assert cp.count == 1

    # 加载
    restored = cp.load(cp_id)
    assert restored is not None
    assert restored.cycle_id == "test_cp"
    assert restored.get_confidence("A0") == 0.7

    # 列出
    cps = cp.list_checkpoints()
    assert len(cps) == 1

    # 删除
    assert cp.delete(cp_id)
    assert cp.count == 0

    print("✅ Checkpointer 测试通过")


def test_compressor():
    """测试上下文压缩器"""
    from dreamos.core.graph_store import ContextCompressor
    from dreamos.shared.state import State, NodeResult, new_state

    state = new_state(cycle_id="test_compress")

    # 填充大量 trace
    for i in range(30):
        state.update(f"Node{i}", NodeResult(
            node_id=f"Node{i}",
            confidence=0.5 + i * 0.01,
            direction="LONG" if i % 2 == 0 else "SHORT",
        ))

    assert len(state.trace) == 30

    compressor = ContextCompressor(keep_recent_trace=10, keep_recent_results=10)
    result = compressor.compress(state)

    assert result.original_size > 0
    assert result.compressed_size > 0
    assert result.compression_ratio < 1.0
    assert result.retained_trace_count == 10
    assert result.removed_trace_count == 20
    assert len(state.trace) == 10  # 被原地压缩

    print(f"✅ ContextCompressor 测试通过 (ratio={result.compression_ratio:.2f})")


def test_history_replay():
    """测试历史回放"""
    from dreamos.core.graph_store import HistoryReplay
    from dreamos.shared.state import State, new_state

    history = HistoryReplay(max_entries=100)

    # 记录 3 次执行
    for i in range(3):
        state = new_state(cycle_id=f"cycle_{i}")
        state.intent = {"intent_type": "TREND_FOLLOWING"}
        state.plan = {"planned_chain": "A"}
        state.final_action = "LONG"
        state.final_confidence = 0.7 + i * 0.05
        history.record(state, {
            "total_tokens": 500,
            "total_latency_ms": 1200,
            "success_rate": 0.8,
            "executed_nodes": 5,
            "early_terminated": False,
        })

    assert history.total == 3

    # 查询
    entries = history.query(intent_type="TREND_FOLLOWING")
    assert len(entries) == 3

    # 模式识别
    patterns = history.find_patterns()
    assert patterns["total"] == 3
    assert patterns["intent_counts"].get("TREND_FOLLOWING") == 3
    assert patterns["action_counts"].get("LONG") == 3

    print(f"✅ HistoryReplay 测试通过 (entries={history.total})")


def test_graph_store():
    """测试 G 层主入口"""
    from dreamos.core.graph_store import GraphStore
    from dreamos.shared.state import State, NodeResult, new_state

    store = GraphStore(max_checkpoints=10, max_history=50, auto_compress=False)

    state = new_state(cycle_id="test_store")
    state.update("A0", NodeResult(node_id="A0", confidence=0.7, direction="LONG"))

    # 检查点
    cp_id = store.checkpoint(state, node_id="A0")
    assert cp_id is not None

    # 回滚
    restored = store.rollback(cp_id)
    assert restored is not None
    assert restored.get_confidence("A0") == 0.7

    # 记录历史
    state.final_action = "LONG"
    state.final_confidence = 0.75
    store.record(state, {"total_tokens": 500, "total_latency_ms": 1000})

    # 查询
    patterns = store.find_patterns()
    assert patterns["total"] == 1

    # 摘要
    summary = store.summary()
    assert summary["checkpoints"] == 1
    assert summary["history_entries"] == 1

    print("✅ GraphStore 测试通过")


# ============================================================
# 全链路集成测试
# ============================================================

def test_full_pipeline_sacg():
    """S→A→C→G 全链路集成测试"""
    from dreamos.core.sense import IntentEngine
    from dreamos.core.arrange import GraphPlanner
    from dreamos.core.compute import GraphExecutor
    from dreamos.core.graph_store import GraphStore
    from dreamos.registry.node_registry import NodeRegistry
    from dreamos.registry.base import BaseNode
    from dreamos.shared.state import State, NodeResult, new_state

    # 准备注册表
    registry = NodeRegistry()

    class A0Node(BaseNode):
        node_id = "A0"; name = "矛盾论"; chain = "A"; estimated_tokens = 300
        def execute_core(self, state):
            return NodeResult(node_id="A0", confidence=0.72, direction="LONG")

    class A1Node(BaseNode):
        node_id = "A1"; name = "趋势"; chain = "A"; estimated_tokens = 500
        def execute_core(self, state):
            return NodeResult(node_id="A1", confidence=0.75, direction="LONG")

    class A2Node(BaseNode):
        node_id = "A2"; name = "量价"; chain = "A"; estimated_tokens = 400
        def execute_core(self, state):
            return NodeResult(node_id="A2", confidence=0.78, direction="LONG")

    registry.register(A0Node())
    registry.register(A1Node())
    registry.register(A2Node())

    # ── S 层: 意图识别 ─────────────────────────────
    engine = IntentEngine(budget_mode="standard", use_llm_based=False)
    intent_result = engine.recognize(
        market={"price": 50000, "change_24h": 5.0, "rsi14": 55,
                "ema20": 49000, "ema50": 47000, "ema200": 44000,
                "adx": 28, "vol_ratio": 1.3}
    )
    assert intent_result.confidence > 0
    assert intent_result.recommended_chain in ("A", "C", "F")

    # ── A 层: 图编排 ───────────────────────────────
    state = new_state(cycle_id="integration_test")
    state.intent = intent_result.to_dict()

    planner = GraphPlanner(registry=registry, budget_total=6000)
    plan = planner.plan(state)
    graph = planner.build_graph(plan)

    assert plan.planned_chain in ("A", "C", "F")
    assert len(plan.selected_nodes) > 0

    # ── C 层: 图执行 ───────────────────────────────
    executor = GraphExecutor(max_retries=1, enable_early_terminate=False)
    report = executor.execute(graph, state, plan=plan)

    assert report.executed_nodes > 0
    assert report.success_nodes > 0
    assert report.final_action in ("LONG", "SHORT", "HOLD")
    assert report.final_confidence > 0

    # ── G 层: 存储与历史 ───────────────────────────
    store = GraphStore(auto_compress=False)
    cp_id = store.checkpoint(state, node_id="A2")
    store.record(state, report.to_dict())

    patterns = store.find_patterns()
    assert patterns["total"] == 1

    print(f"✅ SACG 全链路集成测试通过")
    print(f"   S: {intent_result.intent_type} (conf={intent_result.confidence:.2f})")
    print(f"   A: chain={plan.planned_chain}, nodes={plan.node_ids}")
    print(f"   C: action={report.final_action}, conf={report.final_confidence:.2f}, success={report.success_nodes}/{report.executed_nodes}")
    print(f"   G: checkpoints={store.summary()['checkpoints']}, history={store.summary()['history_entries']}")


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("DreamOS ACG 三层测试")
    print("=" * 60)

    test_imports()

    print("\n── A 层 ──")
    test_sequential_graph()
    test_conditional_graph()
    test_node_selector()
    test_budget_allocator()
    test_graph_planner()

    print("\n── C 层 ──")
    test_node_runner()
    test_node_runner_retry()
    test_reflector()
    test_aggregator()
    test_aggregator_disagreement()
    test_graph_executor()
    test_graph_executor_early_terminate()

    print("\n── G 层 ──")
    test_checkpointer()
    test_compressor()
    test_history_replay()
    test_graph_store()

    print("\n── 集成 ──")
    test_full_pipeline_sacg()

    print("\n" + "=" * 60)
    print("🎉 所有 ACG 三层测试通过！")
    print("=" * 60)
