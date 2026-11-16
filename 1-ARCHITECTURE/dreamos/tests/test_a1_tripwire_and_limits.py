"""A1-4: 45 tripwire（shadow→hard）+ 迭代上限 + 循环内自动压缩

对齐 45 门禁双模语义（先 shadow 记录误拦率，再 hard 熔断）与 SPEC-56 G-L2-10/11:
  - shadow: 评估记录，不阻塞
  - hard:   BLOCK 立即熔断 → stop_reason=error
  - 迭代上限: INSERT_BEFORE 次数受 max_inserts 约束（防反射扩张失控）
  - GAP-26: 循环内按阈值自动压缩（不再只依赖检查点）
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.compute.graph_executor import GraphExecutor  # noqa: E402
from dreamos.core.compute.tripwire import (  # noqa: E402
    TripwireRegistry,
    default_registry,
)
from dreamos.core.compute.types import ReflectAction, ReflectDecision  # noqa: E402
from dreamos.shared.state import NodeResult, NodeStatus, new_state  # noqa: E402


class _Node:
    def __init__(self, node_id, status=NodeStatus.SUCCESS):
        self.node_id = node_id
        self.name = node_id
        self.chain = "C"
        self.required_tokens = 0
        self.status = status
        self.confidence = 0.8

    def execute(self, state):
        return NodeResult(node_id=self.node_id, status=self.status, confidence=self.confidence)

    def validate(self, state):
        return None


class _Graph:
    def __init__(self, nodes):
        self._map = {n.node_id: n for n in nodes}
        self._order = [n.node_id for n in nodes]

    def get_entry(self):
        return self._map[self._order[0]] if self._order else None

    def get_next(self, current_id, state):
        if current_id not in self._order:
            return None
        idx = self._order.index(current_id)
        return self._map[self._order[idx + 1]] if idx + 1 < len(self._order) else None

    def topological_order(self):
        return list(self._order)

    def all_nodes(self):
        return [self._map[n] for n in self._order]

    def get_node(self, node_id):
        return self._map.get(node_id)

    def insert_before(self, before_id, new_node):
        if new_node.node_id in self._order or before_id not in self._order:
            return False
        self._map[new_node.node_id] = new_node
        self._order.insert(self._order.index(before_id), new_node.node_id)
        return True


def _executor(**kwargs):
    kwargs.setdefault("enable_reflect", False)
    kwargs.setdefault("enable_checkpoint", False)
    return GraphExecutor(**kwargs)


def _blocking_registry() -> TripwireRegistry:
    registry = TripwireRegistry()
    registry.register("G-L2-11", lambda ctx: {"verdict": "BLOCK", "detail": {"why": "test"}})
    return registry


# ── tripwire 双模 ───────────────────────────────────


def test_shadow_records_but_does_not_block():
    graph = _Graph([_Node("G1"), _Node("N2")])

    report = _executor(tripwire_registry=_blocking_registry()).execute(
        graph, new_state("cycle-1"), tripwire_ids=["G-L2-11"], tripwire_mode="shadow"
    )

    assert report.stop_reason == "done"
    assert report.executed_nodes == 2
    verdicts = [(t["tripwire_id"], t["checkpoint"], t["verdict"]) for t in report.tripwire_history]
    assert ("G-L2-11", "post_gate", "BLOCK") in verdicts
    assert ("G-L2-11", "end", "BLOCK") in verdicts


def test_hard_blocks_at_gate():
    graph = _Graph([_Node("G1"), _Node("N2")])

    report = _executor(tripwire_registry=_blocking_registry()).execute(
        graph, new_state("cycle-1"), tripwire_ids=["G-L2-11"], tripwire_mode="hard"
    )

    assert report.stop_reason == "error"
    assert report.resumable is False
    assert report.executed_nodes == 1
    assert report.stop_detail["tripwire"] == "G-L2-11"
    assert report.stop_detail["checkpoint"] == "post_gate"


def test_end_tripwire_overrides_done_in_hard_mode():
    graph = _Graph([_Node("N1")])
    registry = TripwireRegistry()
    registry.register(
        "G-L2-10",
        lambda ctx: {"verdict": "BLOCK"} if ctx["checkpoint"] == "end" else {"verdict": "PASS"},
    )

    report = _executor(tripwire_registry=registry).execute(
        graph, new_state("cycle-1"), tripwire_ids=["G-L2-10"], tripwire_mode="hard"
    )

    assert report.executed_nodes == 1
    assert report.stop_reason == "error"
    assert report.stop_detail["checkpoint"] == "end"


# ── 内置门禁 ────────────────────────────────────────


class _FakeReport:
    def __init__(self, contract):
        self._contract = contract

    def stop_contract(self):
        return self._contract


def test_builtin_stop_contract_gate():
    registry = default_registry()

    bad = _FakeReport({"stop_reason": "done", "resumable": True, "trace_id": "run-1"})
    result = registry.evaluate("G-L2-10", {"report": bad}, checkpoint="end")
    assert result.verdict == "BLOCK"
    assert any("resumable" in r for r in result.detail["reasons"])

    good = _FakeReport({"stop_reason": "done", "resumable": False, "trace_id": "run-1"})
    assert registry.evaluate("G-L2-10", {"report": good}, checkpoint="end").verdict == "PASS"
    assert registry.evaluate("G-L2-10", {"report": good}, checkpoint="post_gate").verdict == "SKIP"


def test_builtin_tool_set_gate():
    registry = default_registry()
    state = new_state("cycle-1")

    assert registry.evaluate("G-L2-11", {"state": state}, checkpoint="end").verdict == "SKIP"

    state.extra["tool_set"] = {
        "policy": {"order": ["deny", "mode", "allow", "human"], "mode": "default"},
        "tools": [
            {
                "name": "l1.trading.forward_signal",
                "effect": "trade",
                "requires_mandate": False,
                "approval": "auto",
            }
        ],
    }
    blocked = registry.evaluate("G-L2-11", {"state": state}, checkpoint="end")
    assert blocked.verdict == "BLOCK"
    assert len(blocked.detail["reasons"]) >= 2

    state.extra["tool_set"]["tools"][0].update({"requires_mandate": True, "approval": "human"})
    assert registry.evaluate("G-L2-11", {"state": state}, checkpoint="end").verdict == "PASS"


# ── 迭代上限 / 自动压缩 ────────────────────────────


class _InsertReflector:
    """对所有节点都要求前插 X 的假反射器"""

    def decide(self, current_node_id, result, state, graph, **kwargs):
        if current_node_id == "X":
            return ReflectDecision(action=ReflectAction.CONTINUE)
        return ReflectDecision(action=ReflectAction.INSERT_BEFORE, insert_node_id="X")


def test_insert_cap_prevents_unbounded_growth():
    graph = _Graph([_Node("N1"), _Node("N2")])
    graph._map["X"] = _Node("X")  # 可插入但不在执行序列
    executor = _executor(enable_reflect=True, max_inserts=1)
    executor._reflector = _InsertReflector()

    report = executor.execute(graph, new_state("cycle-1"))

    assert graph._order.count("X") == 1  # 第二次插入被上限拦截
    assert report.total_nodes == 3
    assert report.stop_reason == "done"


class _FakeStore:
    def __init__(self, need_compress=True):
        self.calls = 0
        self.compressor = self

        class _C:
            def __init__(self, need):
                self.need = need

            def should_compress(self, state):
                return self.need

        self.compressor = _C(need_compress)

    def compress(self, state):
        self.calls += 1


def test_auto_compress_triggered_in_loop():
    store = _FakeStore()
    graph = _Graph([_Node("N1"), _Node("N2")])

    report = _executor(graph_store=store).execute(graph, new_state("cycle-1"))

    assert store.calls == 2
    assert report.compression_count == 2


def test_auto_compress_skipped_below_threshold():
    store = _FakeStore(need_compress=False)
    graph = _Graph([_Node("N1")])

    report = _executor(graph_store=store).execute(graph, new_state("cycle-1"))

    assert store.calls == 0
    assert report.compression_count == 0
