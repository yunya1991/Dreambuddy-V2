"""A1-3: graph_store 压缩器接 24 BAC 锚点语义

对齐 24-图结构上下文压缩/TECHNICAL_DESIGN §锚点节点:
  - 锚点原文保留并重注入：Blueprint 目标 / 最新用户指令 / 未完成计划节点
  - trace 首部 anchor_nodes 条强制保留（跨片连续性）+ 最近 N 条
  - Plan 必选节点（is_required）结果不降级，证据不外置
  - 工具结果只进 trace，不写入摘要
"""

from __future__ import annotations

import sys
from pathlib import Path

BASE = Path(__file__).parent.parent.parent  # 1-ARCHITECTURE/
sys.path.insert(0, str(BASE))

from dreamos.core.graph_store.compressor import ContextCompressor  # noqa: E402
from dreamos.shared.state import NodeResult, NodeStatus, new_state  # noqa: E402


def _trace_entry(i: int) -> dict:
    return {"node_id": f"t{i}", "status": "success", "confidence": 0.5, "direction": "LONG"}


# ── 锚点收集与重注入 ────────────────────────────────


def test_collect_and_reinject_anchors():
    state = new_state("cycle-1")
    state.intent = {"user_message": "分析 BTC 趋势并给出计划"}
    state.blueprint = {
        "objective": "给出可执行交易计划",
        "execution_plan": [
            {"node_id": "A1", "status": "done"},
            {"node_id": "A9", "status": "pending"},
        ],
    }
    state.plan = {
        "selected_nodes": [{"node_id": "A5", "is_required": True}],
        "deferred_nodes": ["A7"],
    }
    state.update("A1", NodeResult(node_id="A1", status=NodeStatus.SUCCESS, confidence=0.8))

    result = ContextCompressor().compress(state)

    assert result.anchors["objective"] == "给出可执行交易计划"
    assert result.anchors["latest_instruction"] == "分析 BTC 趋势并给出计划"
    assert result.anchors["unfinished_node_ids"] == ["A5", "A7", "A9"]
    assert result.anchors["required_node_ids"] == ["A5"]
    assert result.anchored_node_ids == ["A5", "A7", "A9"]

    # 重注入：下一轮上下文组装可直接读取
    assert state.extra["compression_anchors"] == result.anchors
    assert result.to_dict()["anchors"] == result.anchors


def test_required_node_evidence_not_downgraded():
    """Plan 必选节点的低置信度结果不被摘要化（证据外置只作用于非锚点）"""
    state = new_state("cycle-1")
    state.plan = {"selected_nodes": [{"node_id": "r0", "is_required": True}]}
    for i in range(25):
        state.results[f"r{i}"] = NodeResult(
            node_id=f"r{i}",
            status=NodeStatus.SUCCESS,
            confidence=0.1,
            outputs={"evidence": i},
        )

    ContextCompressor().compress(state, keep_recent_results=5)

    assert state.results["r0"].outputs == {"evidence": 0}  # 锚点：证据保留
    assert state.results["r1"].outputs == {}  # 非锚点旧结果：降级为摘要


# ── trace 首部锚点 + 最近窗口 ───────────────────────


def test_trace_head_anchor_and_recent_window():
    state = new_state("cycle-1")
    state.trace = [_trace_entry(i) for i in range(20)]

    result = ContextCompressor().compress(state, keep_recent_trace=5, anchor_nodes=2)

    assert len(state.trace) == 7
    assert [t["node_id"] for t in state.trace] == ["t0", "t1", "t15", "t16", "t17", "t18", "t19"]
    assert result.summary["compressed_from"] == 13
    assert result.removed_trace_count == 13
    assert result.retained_trace_count == 7


def test_anchor_nodes_zero_keeps_only_recent():
    state = new_state("cycle-1")
    state.trace = [_trace_entry(i) for i in range(20)]

    ContextCompressor().compress(state, keep_recent_trace=5, anchor_nodes=0)

    assert [t["node_id"] for t in state.trace] == ["t15", "t16", "t17", "t18", "t19"]


def test_small_state_is_noop():
    state = new_state("cycle-1")
    state.trace = [_trace_entry(i) for i in range(3)]

    result = ContextCompressor().compress(state, keep_recent_trace=5)

    assert len(state.trace) == 3
    assert result.summary == {}
    assert result.anchors == {}
    assert "compression_anchors" not in state.extra
