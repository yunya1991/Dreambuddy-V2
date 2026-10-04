"""P0-1: Reflector 认知扩展 — recall 注入测试 (RED 阶段)

验证 Spec §3.4 C-Drive-Agent Step 1: Reflector 在 decide() 前调
cognitive_adapter.recall() 检索历史经验，结果提炼为 suggestions。

硬约束:
  - HC-3: 认知系统调用 FAIL-OPEN（MCP 不可用/异常 → 不阻塞）
  - recall 结果作为 suggestions 注入决策，不改变 action 本身
"""
from __future__ import annotations

from pathlib import Path
import sys

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.shared.state import State, NodeResult, NodeStatus, new_state
from dreamos.shared.interfaces import Node
from dreamos.core.compute.reflector import Reflector
from dreamos.core.compute.types import ReflectAction


# ── 测试桩 ──────────────────────────────────────────

class _FakeGraph:
    """最小 Graph 桩：满足 Reflector.decide 调用需求"""
    def all_nodes(self):
        return []
    def get_node(self, node_id):
        return None
    def get_next(self, current_id, state):
        return None
    def topological_order(self):
        return []
    def get_entry(self):
        return None
    def insert_before(self, before_id, new_node):
        return False


class MockCognitiveAdapter:
    """模拟 CognitiveLoopAdapter，记录 recall 调用"""
    def __init__(self, memories=None, raise_exc=False):
        self._memories = memories or []
        self._raise = raise_exc
        self.recall_called = False
        self.recall_context = None
        self.recall_top_k = None
        self.recall_min_quality = None

    def recall(self, context="", top_k=5, min_quality="C"):
        self.recall_called = True
        self.recall_context = context
        self.recall_top_k = top_k
        self.recall_min_quality = min_quality
        if self._raise:
            raise RuntimeError("模拟 MCP 不可用")
        return self._memories


def _make_result(node_id="C1", confidence=0.8, direction="LONG",
                 status=NodeStatus.SUCCESS):
    return NodeResult(
        node_id=node_id,
        status=status,
        confidence=confidence,
        direction=direction,
    )


# ── 测试用例 ────────────────────────────────────────

def test_reflector_accepts_cognitive_adapter():
    """Reflector 可通过 cognitive_adapter 参数注入认知适配器"""
    adapter = MockCognitiveAdapter()
    r = Reflector(cognitive_adapter=adapter)
    assert r is not None


def test_reflector_calls_recall_on_decide():
    """decide() 时应调用 cognitive_adapter.recall() (HC: Step1)"""
    adapter = MockCognitiveAdapter(memories=[])
    r = Reflector(cognitive_adapter=adapter)
    state = new_state(cycle_id="t1")
    state.update("C1", _make_result("C1", confidence=0.8, direction="LONG"))
    r.decide(
        current_node_id="C1",
        result=state.get_result("C1"),
        state=state,
        graph=_FakeGraph(),
        executed_count=1,
        max_nodes=5,
    )
    assert adapter.recall_called, "decide() 应调用 adapter.recall()"


def test_reflector_recall_context_contains_node_id():
    """recall context 应包含当前节点 ID（便于检索节点相关经验）"""
    adapter = MockCognitiveAdapter(memories=[])
    r = Reflector(cognitive_adapter=adapter)
    state = new_state(cycle_id="t2")
    state.update("F1", _make_result("F1", confidence=0.7, direction="LONG"))
    r.decide(
        current_node_id="F1",
        result=state.get_result("F1"),
        state=state,
        graph=_FakeGraph(),
        executed_count=1,
        max_nodes=5,
    )
    assert "F1" in (adapter.recall_context or ""), \
        f"recall context 应含节点ID, got: {adapter.recall_context!r}"


def test_reflector_recall_results_in_suggestions():
    """recall 返回的记忆应提炼为 suggestions 注入决策"""
    memories = [
        {"content": "历史相似场景: 低置信度时 REDO 重试可提升结果", "score": 0.6},
        {"content": "C1 节点 RSI 超卖时反弹概率高，建议沿用 LONG", "score": 0.5},
    ]
    adapter = MockCognitiveAdapter(memories=memories)
    r = Reflector(cognitive_adapter=adapter)
    state = new_state(cycle_id="t3")
    state.update("C1", _make_result("C1", confidence=0.35, direction="LONG"))
    decision = r.decide(
        current_node_id="C1",
        result=state.get_result("C1"),
        state=state,
        graph=_FakeGraph(),
        executed_count=1,
        max_nodes=5,
        record=None,
    )
    # recall 结果应出现在 suggestions 中（提炼为可读提示）
    joined = " ".join(decision.suggestions)
    assert "REDO" in joined or "RSI" in joined or "反弹" in joined or "重试" in joined, \
        f"suggestions 应含 recall 提炼, got: {decision.suggestions}"


def test_reflector_no_adapter_fails_open():
    """HC-3: 无 cognitive_adapter 时 decide() 正常返回（FAIL-OPEN）"""
    r = Reflector()  # 不注入 adapter
    state = new_state(cycle_id="t4")
    state.update("C1", _make_result("C1", confidence=0.8, direction="LONG"))
    decision = r.decide(
        current_node_id="C1",
        result=state.get_result("C1"),
        state=state,
        graph=_FakeGraph(),
        executed_count=1,
        max_nodes=5,
    )
    assert decision.action == ReflectAction.CONTINUE
    assert decision.confidence == 0.8


def test_reflector_adapter_exception_fails_open():
    """HC-3: adapter.recall() 异常时 decide() 正常返回（FAIL-OPEN）"""
    adapter = MockCognitiveAdapter(raise_exc=True)
    r = Reflector(cognitive_adapter=adapter)
    state = new_state(cycle_id="t5")
    state.update("C1", _make_result("C1", confidence=0.8, direction="LONG"))
    decision = r.decide(
        current_node_id="C1",
        result=state.get_result("C1"),
        state=state,
        graph=_FakeGraph(),
        executed_count=1,
        max_nodes=5,
    )
    # 异常不应阻塞决策
    assert decision.action == ReflectAction.CONTINUE


def test_reflector_recall_preserves_continue_action():
    """recall 注入 suggestions 不改变原有 CONTINUE 决策逻辑"""
    adapter = MockCognitiveAdapter(memories=[
        {"content": "经验A", "score": 0.5}
    ])
    r = Reflector(cognitive_adapter=adapter)
    state = new_state(cycle_id="t6")
    state.update("C1", _make_result("C1", confidence=0.85, direction="LONG"))
    decision = r.decide(
        current_node_id="C1",
        result=state.get_result("C1"),
        state=state,
        graph=_FakeGraph(),
        executed_count=1,
        max_nodes=5,
        budget_remaining_ratio=0.8,
    )
    assert decision.action == ReflectAction.CONTINUE
    assert decision.confidence == 0.85
    assert len(decision.suggestions) >= 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
