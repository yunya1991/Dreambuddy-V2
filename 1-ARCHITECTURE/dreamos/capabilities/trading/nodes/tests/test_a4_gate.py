"""
L2 自检测: A4 门禁节点单测
覆盖: 置信度门槛、多空方向、A8 知行合一、加权投票、趋势确认
"""

import sys
from pathlib import Path

import pytest

# 将 dreamos 加入 path
PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.capabilities.trading.nodes.a4_gate import A4GateNode


def make_state(results=None, market_data=None, intent=None):
    """构造测试用 State"""
    state = State(cycle_id="test")
    if results:
        for nid, r in results.items():
            state.results[nid] = r
    if market_data:
        state.market = market_data
        # A4 代码检查 state.market_data
        state.market_data = market_data
    if intent:
        state.intent = intent
    return state


class TestA4Gate:
    """A4 门禁节点核心逻辑测试"""

    def test_long_pass_when_confidence_above_threshold(self):
        """LONG 方向且置信度 >= 门槛 → 通过"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.8, direction="LONG"),
        })
        result = node.execute(state)
        assert result.direction == "LONG"
        assert result.outputs["gate_passed"] is True

    def test_long_blocked_when_confidence_below_threshold(self):
        """LONG 方向但置信度 < 门槛 → 拦截为 HOLD
        用 mock 控制 _collect_direction 返回低置信度"""
        node = A4GateNode()
        node._collect_direction = lambda s: ("LONG", 0.5)
        state = make_state()
        result = node.execute(state)
        assert result.direction == "HOLD"
        assert result.outputs["gate_passed"] is False

    def test_short_blocked_when_confidence_below_threshold(self):
        """SHORT 方向但置信度 < 门槛 → 拦截为 HOLD"""
        node = A4GateNode()
        node._collect_direction = lambda s: ("SHORT", 0.5)
        state = make_state()
        result = node.execute(state)
        assert result.direction == "HOLD"
        assert result.outputs["gate_passed"] is False

    def test_hold_direction_always_blocked(self):
        """HOLD 方向始终被拦截"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.9, direction="HOLD"),
        })
        result = node.execute(state)
        assert result.direction == "HOLD"
        assert result.outputs["gate_passed"] is False

    def test_no_results_returns_hold(self):
        """无前序节点结果 → HOLD"""
        node = A4GateNode()
        state = make_state()
        result = node.execute(state)
        assert result.direction == "HOLD"
        assert result.confidence == 0.0

    def test_short_pass_when_confidence_above_threshold(self):
        """SHORT 方向且置信度 >= 门槛 → 通过"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.8, direction="SHORT"),
        })
        result = node.execute(state)
        assert result.direction == "SHORT"
        assert result.outputs["gate_passed"] is True

    def test_get_threshold_short(self):
        """_get_threshold 返回 SHORT 门槛"""
        node = A4GateNode()
        assert node._get_threshold("SHORT") == A4GateNode.SHORT_THRESHOLD

    def test_get_threshold_long(self):
        """_get_threshold 返回 LONG 门槛"""
        node = A4GateNode()
        assert node._get_threshold("LONG") == A4GateNode.LONG_THRESHOLD

    def test_get_threshold_default(self):
        """非 SHORT 方向返回 LONG 门槛"""
        node = A4GateNode()
        assert node._get_threshold("HOLD") == A4GateNode.LONG_THRESHOLD


class TestA4CollectDirection:
    """_collect_direction 加权投票逻辑测试"""

    def test_single_long_node(self):
        """单一 LONG 节点 → LONG"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.8, direction="LONG"),
        })
        direction, confidence = node._collect_direction(state)
        assert direction == "LONG"
        assert confidence > 0

    def test_split_direction_returns_hold(self):
        """多空分歧接近 → HOLD
        A2(0.55 LONG, w=1.5) → 0.825; F1(0.55 SHORT, w=1.5) → 0.825
        long_ratio=0.5, short_ratio=0.5, diff=0 < 0.2 → HOLD
        """
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.55, direction="LONG"),
            "A3": NodeResult(node_id="A3", confidence=0.55, direction="SHORT"),
        })
        direction, confidence = node._collect_direction(state)
        assert direction == "HOLD"

    def test_zero_confidence_nodes_skipped(self):
        """置信度 <= 0 的节点被跳过"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.0, direction="LONG"),
            "A3": NodeResult(node_id="A3", confidence=0.8, direction="LONG"),
        })
        direction, confidence = node._collect_direction(state)
        assert direction == "LONG"

    def test_only_hold_directions_returns_hold(self):
        """所有节点都是 HOLD → HOLD"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.8, direction="HOLD"),
            "A3": NodeResult(node_id="A3", confidence=0.8, direction="HOLD"),
        })
        direction, confidence = node._collect_direction(state)
        assert direction == "HOLD"
        assert confidence == 0.0

    def test_confidence_capped_at_0_95(self):
        """置信度上限 0.95"""
        node = A4GateNode()
        state = make_state(results={
            "A2": NodeResult(node_id="A2", confidence=0.99, direction="LONG"),
            "A3": NodeResult(node_id="A3", confidence=0.99, direction="LONG"),
        })
        _, confidence = node._collect_direction(state)
        assert confidence <= 0.95

    def test_trend_confirm_lone_price_below_ema50(self):
        """LONG 但价格在 EMA50 之下 → 置信度降权"""
        node = A4GateNode()
        state = make_state(
            results={
                "A2": NodeResult(node_id="A2", confidence=0.8, direction="LONG"),
            },
            market_data={"price": 100, "ema50": 110, "ema200": 120},
        )
        _, confidence = node._collect_direction(state)
        # 无趋势确认时置信度 ~0.8，有降权后应 < 0.8
        assert confidence < 0.8

    def test_short_price_above_ema50(self):
        """SHORT 但价格在 EMA50 之上 → 置信度降权"""
        node = A4GateNode()
        state = make_state(
            results={
                "A2": NodeResult(node_id="A2", confidence=0.8, direction="SHORT"),
            },
            market_data={"price": 110, "ema50": 100, "ema200": 90},
        )
        _, confidence = node._collect_direction(state)
        assert confidence < 0.8


class TestA8Unity:
    """A8 知行合一检查测试"""

    def test_intent_confidence_close_to_execution(self):
        """意图置信度与执行置信度接近 → 知行一致"""
        node = A4GateNode()
        state = make_state(
            results={
                "A2": NodeResult(node_id="A2", confidence=0.75, direction="LONG"),
            },
            intent={"confidence": 0.78},
        )
        result = node.execute(state)
        rationale = " ".join(result.outputs["rationale"])
        assert "知行基本一致" in rationale or "Gap" in rationale

    def test_intent_confidence_gap_large(self):
        """意图与执行差距大 → 建议反思"""
        node = A4GateNode()
        state = make_state(
            results={
                "A2": NodeResult(node_id="A2", confidence=0.9, direction="LONG"),
            },
            intent={"confidence": 0.5},
        )
        result = node.execute(state)
        rationale = " ".join(result.outputs["rationale"])
        assert "知行偏差大" in rationale or "建议反思" in rationale

    def test_no_intent_confidence(self):
        """无意图置信度 → 不触发 A8 检查"""
        node = A4GateNode()
        state = make_state(
            results={
                "A2": NodeResult(node_id="A2", confidence=0.8, direction="LONG"),
            },
            intent={"confidence": 0.0},
        )
        result = node.execute(state)
        rationale = " ".join(result.outputs["rationale"])
        assert "知行" not in rationale
