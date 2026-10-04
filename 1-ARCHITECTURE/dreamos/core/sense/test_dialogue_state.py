"""DialogueStateManager (DSM) test suite — RED phase (expects ImportError).

验证多轮对话状态管理:
    - TurnState dataclass (turn_id/intent_primary/intent_secondary/slots/timestamp)
    - DialogueStateManager 类 (max_turns=10 默认)
    - add_turn(session_id, ...) 添加对话轮次
    - resolve_reference(session_id, current_slots) 前轮继承缺槽位
    - get_context(session_id, n=3) 获取最近 n 轮上下文
    - clear_session(session_id) 清空会话

TDD RED: 本测试在 dialogue_state.py 落地前应全部失败（ImportError）。
"""
import pytest
from pathlib import Path
import sys

# 1-ARCHITECTURE/ → sys.path
BASE = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from dreamos.core.sense.dialogue_state import (
    TurnState,
    DialogueStateManager,
)


# ============================================================
# 1. 模块/类存在性
# ============================================================

def test_import_module():
    """dialogue_state 模块可被导入。"""
    from dreamos.core.sense import dialogue_state
    assert hasattr(dialogue_state, "TurnState")
    assert hasattr(dialogue_state, "DialogueStateManager")


def test_turn_state_dataclass_fields():
    """TurnState dataclass 含必需字段。"""
    ts = TurnState(
        turn_id=1,
        intent_primary="query",
        intent_secondary="market_query",
        slots={"stock": "BTC"},
    )
    assert ts.turn_id == 1
    assert ts.intent_primary == "query"
    assert ts.intent_secondary == "market_query"
    assert ts.slots == {"stock": "BTC"}
    # timestamp 自动生成
    assert hasattr(ts, "timestamp")
    assert ts.timestamp is not None or ts.timestamp == 0  # 非 None


def test_manager_init():
    """DialogueStateManager 可实例化且默认 max_turns=10。"""
    mgr = DialogueStateManager()
    assert mgr is not None
    # 默认 max_turns=10
    assert mgr.max_turns == 10


def test_manager_init_custom_max_turns():
    """支持自定义 max_turns。"""
    mgr = DialogueStateManager(max_turns=5)
    assert mgr.max_turns == 5


# ============================================================
# 2. add_turn + get_context
# ============================================================

def test_add_turn_and_get_context():
    """添加轮次并获取上下文。"""
    mgr = DialogueStateManager()
    sid = "session-1"
    mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query",
                 slots={"stock": "BTC"})
    ctx = mgr.get_context(sid)
    assert isinstance(ctx, list)
    assert len(ctx) == 1
    assert ctx[0].intent_secondary == "market_query"


def test_get_context_returns_last_n():
    """get_context(n=3) 返回最近 3 轮。"""
    mgr = DialogueStateManager()
    sid = "session-2"
    for i in range(5):
        mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query",
                     slots={"turn": i})
    ctx = mgr.get_context(sid, n=3)
    assert len(ctx) == 3
    # 最近 3 轮（turn_id 2,3,4 或 turn 字段 2,3,4）
    assert ctx[-1].slots.get("turn") == 4
    assert ctx[0].slots.get("turn") == 2


def test_get_context_unknown_session_returns_empty():
    """未知 session 返回空列表（非 None）。"""
    mgr = DialogueStateManager()
    ctx = mgr.get_context("unknown-sid")
    assert isinstance(ctx, list)
    assert ctx == []


# ============================================================
# 3. resolve_reference（前轮槽位继承）
# ============================================================

def test_resolve_reference_inherits_missing_slot():
    """前轮有 stock，当前轮缺 stock 时继承。"""
    mgr = DialogueStateManager()
    sid = "session-3"
    mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query",
                 slots={"stock": "BTC"})
    # 当前轮没有 stock
    current_slots = {"timeframe": "1h"}
    resolved = mgr.resolve_reference(sid, current_slots)
    assert "stock" in resolved
    assert resolved["stock"] == "BTC"
    assert resolved["timeframe"] == "1h"


def test_resolve_reference_does_not_overwrite_current():
    """当前轮的槽位不被前轮覆盖。"""
    mgr = DialogueStateManager()
    sid = "session-4"
    mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query",
                 slots={"stock": "BTC"})
    current_slots = {"stock": "ETH"}  # 当前轮已显式指定
    resolved = mgr.resolve_reference(sid, current_slots)
    assert resolved["stock"] == "ETH"  # 当前轮优先


def test_resolve_reference_no_history_returns_current():
    """无历史时直接返回当前 slots。"""
    mgr = DialogueStateManager()
    current_slots = {"stock": "BTC"}
    resolved = mgr.resolve_reference("no-history", current_slots)
    assert resolved == {"stock": "BTC"}


# ============================================================
# 4. clear_session + 滚动窗口
# ============================================================

def test_clear_session():
    """clear_session 清空指定会话。"""
    mgr = DialogueStateManager()
    sid = "session-5"
    mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query",
                 slots={"stock": "BTC"})
    assert len(mgr.get_context(sid)) == 1
    mgr.clear_session(sid)
    assert mgr.get_context(sid) == []


def test_max_turns_rolling_window():
    """超过 max_turns 后旧轮次被丢弃（滚动窗口）。"""
    mgr = DialogueStateManager(max_turns=3)
    sid = "session-6"
    for i in range(5):
        mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query",
                     slots={"turn": i})
    ctx = mgr.get_context(sid, n=100)  # 取全部
    assert len(ctx) == 3  # 滚动后只剩 3 轮
    # 保留最近 3 轮 (turn=2,3,4)
    turns = [ts.slots.get("turn") for ts in ctx]
    assert turns == [2, 3, 4]


def test_isolated_sessions():
    """不同 session 互相隔离。"""
    mgr = DialogueStateManager()
    mgr.add_turn("s1", intent_primary="query", intent_secondary="market_query",
                 slots={"stock": "BTC"})
    mgr.add_turn("s2", intent_primary="trade", intent_secondary="buy",
                 slots={"stock": "ETH"})
    assert len(mgr.get_context("s1")) == 1
    assert len(mgr.get_context("s2")) == 1
    assert mgr.get_context("s1")[0].intent_secondary == "market_query"
    assert mgr.get_context("s2")[0].intent_secondary == "buy"


def test_turn_id_auto_increment():
    """turn_id 在同一 session 内自增。"""
    mgr = DialogueStateManager()
    sid = "session-7"
    mgr.add_turn(sid, intent_primary="query", intent_secondary="market_query", slots={})
    mgr.add_turn(sid, intent_primary="trade", intent_secondary="buy", slots={})
    ctx = mgr.get_context(sid)
    assert ctx[0].turn_id == 1
    assert ctx[1].turn_id == 2
