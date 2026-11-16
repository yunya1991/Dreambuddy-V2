"""A1-1: GraphExecutor 统一循环出口 stop_reason（RED → GREEN）

对齐 56-L2架构能力聚合层/contracts/stop_reason.schema.json (v1.1):
  - 任何 loop 结束都必须给出唯一 stop_reason（7 值枚举）
  - parked 三态 + resumable=true + resume_from
  - done/error/no_next_context → resumable=false
  - 软预算收尾 done / 硬预算 cost_limit / 步数上限 max_steps
  - 独立恢复入口 resume_from

硬约束:
  - parked_reason 仅在 stop_reason=parked 时出现在契约中（schema 基类 enum 不允许 null）
  - resumable 由 stop_reason 唯一推导，禁止调用方各自推导
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.compute.graph_executor import GraphExecutor  # noqa: E402
from dreamos.shared.state import NodeResult, NodeStatus, new_state  # noqa: E402

ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{3,64}$")


# ── 测试桩 ──────────────────────────────────────────


class _FakeNode:
    """最小 Node 桩 — 可配置 tokens / status / parked_reason"""

    def __init__(
        self,
        node_id: str,
        tokens: int = 0,
        confidence: float = 0.8,
        status: NodeStatus = NodeStatus.SUCCESS,
        parked_reason=None,
        direction=None,
    ):
        self.node_id = node_id
        self.name = node_id
        self.chain = "C"
        self.required_tokens = tokens
        self.status = status
        self.parked_reason = parked_reason
        self.confidence = confidence
        self.direction = direction
        self.calls = 0

    def execute(self, state) -> NodeResult:
        self.calls += 1
        return NodeResult(
            node_id=self.node_id,
            status=self.status,
            confidence=self.confidence,
            direction=self.direction,
            tokens_used=self.required_tokens,
            parked_reason=self.parked_reason,
        )

    def validate(self, state):
        return None


class _FakeGraph:
    """最小 Graph 桩 — 顺序执行"""

    def __init__(self, nodes):
        self._nodes = list(nodes)
        self._order = [n.node_id for n in self._nodes]

    def get_entry(self):
        return self._nodes[0] if self._nodes else None

    def get_next(self, current_id, state):
        if current_id not in self._order:
            return None
        idx = self._order.index(current_id)
        return self._nodes[idx + 1] if idx + 1 < len(self._nodes) else None

    def topological_order(self):
        return list(self._order)

    def all_nodes(self):
        return list(self._nodes)

    def get_node(self, node_id):
        for n in self._nodes:
            if n.node_id == node_id:
                return n
        return None

    def insert_before(self, before_id, new_node):
        return False


def _executor(**kwargs) -> GraphExecutor:
    kwargs.setdefault("enable_reflect", False)
    kwargs.setdefault("enable_checkpoint", False)
    return GraphExecutor(**kwargs)


# ── 用例 ────────────────────────────────────────────


def test_done_contract_shape():
    """正常走完 → done / 不可续跑 / 契约字段齐全"""
    graph = _FakeGraph([_FakeNode("A1", tokens=100), _FakeNode("A2", tokens=50)])

    report = _executor().execute(
        graph, new_state("cycle-1"), trace_id="trace-a1-1", run_id="run-a1-1"
    )

    contract = report.stop_contract()

    assert report.stop_reason == "done"
    assert contract["schema_version"] == "1.1"
    assert contract["trace_id"] == "trace-a1-1"
    assert contract["run_id"] == "run-a1-1"
    assert contract["stop_reason"] == "done"
    assert contract["resumable"] is False
    assert "parked_reason" not in contract
    assert contract["steps"] == 2
    assert contract["tokens_used"] == 150
    assert contract["cost_cu"] == 0.0
    assert report.to_dict()["stop_reason"] == "done"


def test_trace_and_run_id_generated_when_missing():
    """未显式传 id 时自动生成合法 id（满足 schema pattern）"""
    graph = _FakeGraph([_FakeNode("A1")])

    report = _executor().execute(graph, new_state())
    contract = report.stop_contract()

    assert ID_PATTERN.match(contract["trace_id"])
    assert ID_PATTERN.match(contract["run_id"])


def test_max_steps_and_resume_from():
    """步数上限 → max_steps / 可续跑 / 从下一个未执行节点续跑"""
    graph = _FakeGraph([_FakeNode(f"N{i}") for i in range(1, 6)])

    report = _executor(max_steps=2).execute(graph, new_state("cycle-1"))

    assert report.stop_reason == "max_steps"
    assert report.resumable is True
    assert report.resume_from == "N3"
    assert report.stop_contract()["resumable"] is True


def test_hard_budget_cost_limit():
    """硬预算耗尽 → cost_limit / 可续跑"""
    graph = _FakeGraph([_FakeNode("N1", tokens=100), _FakeNode("N2"), _FakeNode("N3")])

    report = _executor().execute(graph, new_state("cycle-1"), total_budget=100)

    assert report.stop_reason == "cost_limit"
    assert report.resumable is True
    assert report.resume_from == "N2"
    assert report.stop_detail["hard_budget"] == 100
    assert report.stop_detail["tokens_used"] == 100


def test_soft_budget_soft_wrap_is_done():
    """软预算触顶 → 软收尾 done（detail 标记，非硬停）"""
    graph = _FakeGraph([_FakeNode("N1", tokens=100), _FakeNode("N2")])

    report = _executor().execute(graph, new_state("cycle-1"), total_budget=1000, soft_budget=100)

    assert report.stop_reason == "done"
    assert report.resumable is False
    assert report.stop_detail["soft_budget_reached"] is True
    assert report.stop_detail["next_node_id"] == "N2"
    assert report.executed_nodes == 1


def test_parked_three_state_and_independent_resume():
    """节点 parked → parked + 子因 + resume_from；独立入口可续跑"""
    first = _FakeNode("A1")
    parked = _FakeNode(
        "A2",
        status=NodeStatus.PARKED,
        parked_reason="waiting_for_human",
    )
    graph = _FakeGraph([first, parked])

    report = _executor().execute(graph, new_state("cycle-1"))
    contract = report.stop_contract()

    assert report.stop_reason == "parked"
    assert contract["parked_reason"] == "waiting_for_human"
    assert contract["resumable"] is True
    assert report.resume_from == "A2"

    # 恢复：独立入口从 A2 重新开始，不重跑 A1
    parked.status = NodeStatus.SUCCESS
    parked.parked_reason = None
    resumed = _executor().execute(graph, new_state("cycle-1"), resume_from="A2")

    assert resumed.records[0].node_id == "A2"
    assert resumed.stop_reason == "done"
    assert first.calls == 1


def test_no_entry_is_error_not_resumable():
    """无入口 → error（配置错误不可续跑）"""
    report = _executor().execute(_FakeGraph([]), new_state("cycle-1"))

    assert report.stop_reason == "error"
    assert report.resumable is False
    assert "parked_reason" not in report.stop_contract()


def test_interrupted_and_resume_from_current():
    """外部中断 → interrupted / 可续跑 / 从当前未执行节点续跑"""
    checks = {"n": 0}

    def _should_interrupt() -> bool:
        checks["n"] += 1
        return checks["n"] > 1  # 第 1 次（N1 前）False，第 2 次（N2 前）True

    graph = _FakeGraph([_FakeNode("N1"), _FakeNode("N2"), _FakeNode("N3")])

    report = _executor().execute(graph, new_state("cycle-1"), should_interrupt=_should_interrupt)

    assert report.stop_reason == "interrupted"
    assert report.resumable is True
    assert report.resume_from == "N2"
    assert report.executed_nodes == 1
