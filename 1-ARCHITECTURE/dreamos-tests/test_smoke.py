"""
Dreambuddy OS — P0 内核骨架冒烟测试

验证:
    1. os 包能正常 import
    2. 核心抽象可用（State / Node / NodeResult / Registry / Adapter）
    3. 基本的节点注册和执行流程
    4. 序列化/反序列化
    5. 适配器框架

运行:
    cd 1-ARCHITECTURE && python -m pytest os-tests/test_smoke.py -v
    或: python -m os_tests.test_smoke
"""

import sys
import os

# 将 1-ARCHITECTURE 加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_imports():
    """测试所有核心抽象能 import"""
    from dreamos import (
        State, NodeResult, NodeStatus, Node, Graph, Edge,
        Registry, Adapter, ErrorCode, OSError,
        BaseNode, NodeRegistry, register_node,
        BaseAdapter, AdapterRegistry,
        FunctionAdapter, FunctionNode,
        SkillAdapter, SkillNode,
        APIAdapter, APINode,
        sense, arrange, compute, graph_store,
        evolution, budget,
        new_state, gen_cycle_id,
    )
    print("✅ import 测试通过")


def test_state():
    """测试 State 基本操作"""
    from dreamos import State, NodeResult, NodeStatus, new_state

    # 创建
    s = new_state(cycle_id="test_001")
    assert s.cycle_id == "test_001"
    assert s.results == {}

    # 更新
    r = NodeResult(node_id="A0", status=NodeStatus.SUCCESS,
                   confidence=0.7, direction="LONG")
    s.update("A0", r)
    assert s.has_node("A0")
    assert s.get_confidence("A0") == 0.7
    assert s.get_direction("A0") == "LONG"
    assert len(s.trace) == 1

    # 序列化 / 反序列化
    d = s.to_dict()
    s2 = State.from_dict(d)
    assert s2.cycle_id == "test_001"
    assert s2.get_confidence("A0") == 0.7

    # 快照
    snap = s.snapshot()
    snap.update("A1", NodeResult(node_id="A1", confidence=0.5))
    assert not s.has_node("A1")  # 快照不影响原 state

    print("✅ State 测试通过")


def test_node_and_registry():
    """测试 Node + Registry"""
    from dreamos import BaseNode, NodeResult, NodeStatus, NodeRegistry, State

    class A0Node(BaseNode):
        node_id = "A0"
        name = "矛盾论"
        chain = "A"

        def execute_core(self, state: State) -> NodeResult:
            return NodeResult(
                node_id="A0",
                status=NodeStatus.SUCCESS,
                confidence=0.72,
                direction="LONG",
                outputs={"conflicts": 3},
            )

    # 注册
    reg = NodeRegistry()
    reg.register(A0Node())
    assert reg.exists("A0")
    assert len(reg) == 1

    # 查询
    nodes = reg.list_nodes(chain="A")
    assert len(nodes) == 1
    assert nodes[0].node_id == "A0"

    # 执行
    state = State()
    node = reg.get("A0")
    result = node.execute(state)
    assert result.success
    assert result.confidence == 0.72
    assert result.direction == "LONG"
    state.update("A0", result)
    assert state.has_node("A0")

    # 注销
    assert reg.unregister("A0")
    assert not reg.exists("A0")

    print("✅ Node + Registry 测试通过")


def test_error_handling():
    """测试节点错误处理"""
    from dreamos import BaseNode, NodeStatus, State

    class BadNode(BaseNode):
        node_id = "BAD"
        chain = "T"

        def execute_core(self, state):
            raise ValueError("故意出错")

    state = State()
    result = BadNode().execute(state)
    # 异常 → fallback → DEGRADED
    assert result.status == NodeStatus.DEGRADED
    assert result.confidence == 0.0

    print("✅ 错误处理测试通过")


def test_function_adapter():
    """测试函数适配器"""
    from dreamos import FunctionAdapter, State

    adapter = FunctionAdapter()
    assert adapter.can_handle({"type": "function", "handler": lambda s: 1})
    assert not adapter.can_handle({"type": "api"})

    def my_analysis(state):
        return {"confidence": 0.8, "direction": "SHORT"}

    node = adapter.to_node({
        "type": "function",
        "node_id": "F_test",
        "name": "测试函数",
        "chain": "F",
        "handler": my_analysis,
    })

    result = node.execute(State())
    assert result.success
    assert result.confidence == 0.8
    assert result.direction == "SHORT"

    print("✅ FunctionAdapter 测试通过")


def test_adapter_registry():
    """测试适配器注册表"""
    from dreamos import AdapterRegistry, FunctionAdapter, SkillAdapter, APIAdapter

    reg = AdapterRegistry()
    reg.register(FunctionAdapter())
    reg.register(SkillAdapter())
    reg.register(APIAdapter())

    assert len(reg) == 3

    # 能处理函数配置
    node = reg.to_node({
        "type": "function",
        "node_id": "F1",
        "handler": lambda s: {"confidence": 0.5},
    })
    assert node is not None
    assert node.node_id == "F1"

    print("✅ AdapterRegistry 测试通过")


def test_errors():
    """测试错误码"""
    from dreamos import ErrorCode, OSError
    from dreamos.shared.errors import node_not_found, exec_timeout

    # 错误码
    codes = ErrorCode.all_codes()
    assert "SYS_001" in codes
    assert len(codes) >= 18

    # 异常
    exc = node_not_found("A0")
    assert exc.code == ErrorCode.NODE_001
    assert exc.node_id == "A0"
    assert not exc.retryable

    exc2 = exec_timeout("A1", 5000)
    assert exc2.retryable

    print("✅ 错误码测试通过")


def test_utils():
    """测试工具函数"""
    from dreamos import gen_cycle_id, safe_get, chunk, dedupe

    cid = gen_cycle_id()
    assert cid.startswith("cycle_")

    assert safe_get({"a": {"b": {"c": 1}}}, "a.b.c") == 1
    assert safe_get({}, "x.y", "default") == "default"

    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    assert dedupe([1, 2, 2, 3, 3, 3]) == [1, 2, 3]

    print("✅ 工具函数测试通过")


def test_layers_import():
    """测试四层 + 横切占位能 import"""
    from dreamos import sense, arrange, compute, graph_store, evolution, budget

    # S 层 + A 层 + C 层 + G 层已实现
    assert hasattr(sense, "IntentEngine")
    assert hasattr(sense, "RuleBasedRecognizer")
    assert hasattr(arrange, "GraphPlanner")
    assert hasattr(compute, "GraphExecutor")
    assert hasattr(graph_store, "GraphStore")
    # 横切关注点已实现
    assert hasattr(evolution, "EvolutionEngine")
    assert hasattr(budget, "GlobalBudgetManager")

    print("✅ 四层 + 横切关注点 import 测试通过")


if __name__ == "__main__":
    print("=" * 60)
    print("Dreambuddy OS — P0 内核骨架冒烟测试")
    print("=" * 60)
    test_imports()
    test_state()
    test_node_and_registry()
    test_error_handling()
    test_function_adapter()
    test_adapter_registry()
    test_errors()
    test_utils()
    test_layers_import()
    print("=" * 60)
    print("🎉 所有测试通过！P0 内核骨架就绪。")
    print("=" * 60)
