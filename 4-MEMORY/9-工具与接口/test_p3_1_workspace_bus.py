"""P3-1 GWT Workspace Bus TDD RED 测试

借鉴 GWT (Global Workspace Theory) + HOT 双层意识架构，
在 5 子系统之上增加全局工作空间广播层：
  1. broadcast(content) — 广播工作空间内容到所有订阅者
  2. subscribe(subsystem, callback) — 子系统订阅
  3. ignite(content) — 高置信内容被点燃（confidence > 0.8）
  4. get_workspace_state() — 获取当前工作空间状态

RED 契约:
  1. workspace_bus 模块不存在 → ImportError
  2. WorkspaceBus 类不存在
  3. WorkspaceContent dataclass 不存在
  4. broadcast() 不存在
  5. subscribe() 不存在
  6. ignite() 不存在
  7. CognitiveLoopEntry 无 workspace_bus 属性

参考: SPEC-CognitiveSystem-Evolution.md §4.3 P3-1 + §2.5.1
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestWorkspaceBusCore:
    """WorkspaceBus 核心广播能力。"""

    def test_import_workspace_bus(self):
        """RED: workspace_bus 模块可导入。"""
        from workspace_bus import WorkspaceBus  # noqa: F401

    def test_workspace_content_dataclass(self):
        """RED: WorkspaceContent dataclass 存在且有必要字段。"""
        from workspace_bus import WorkspaceContent

        wc = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[{"id": "VM-001", "score": 0.9}],
            skill_match=[{"id": "skill-1", "score": 0.8}],
            knowledge_retrieval=[{"id": "chunk-1", "score": 0.7}],
            confidence=0.85,
        )
        assert wc.intent == {"type": "query"}
        assert wc.confidence == 0.85
        assert hasattr(wc, "ignited")

    def test_broadcast_stores_content(self):
        """RED: broadcast() 存储内容到工作空间。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.5,
        )
        bus.broadcast(content)

        state = bus.get_workspace_state()
        assert state["current"] is not None
        assert state["current"].confidence == 0.5

    def test_subscribe_and_receive_broadcast(self):
        """RED: 订阅者能收到广播内容。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        received = []

        def callback(content):
            received.append(content)

        bus.subscribe("memory_subsystem", callback)

        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.5,
        )
        bus.broadcast(content)

        assert len(received) == 1
        assert received[0].confidence == 0.5

    def test_ignite_on_high_confidence(self):
        """RED: confidence > 0.8 时 ignited=True。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.85,
        )
        bus.broadcast(content)

        state = bus.get_workspace_state()
        assert state["current"].ignited is True

    def test_no_ignite_on_low_confidence(self):
        """RED: confidence <= 0.8 时 ignited=False。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.7,
        )
        bus.broadcast(content)

        state = bus.get_workspace_state()
        assert state["current"].ignited is False

    def test_broadcast_history(self):
        """RED: 广播历史被记录。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        for i in range(3):
            bus.broadcast(WorkspaceContent(
                intent={"type": f"query_{i}"},
                memory_recall=[],
                skill_match=[],
                knowledge_retrieval=[],
                confidence=0.5,
            ))

        state = bus.get_workspace_state()
        assert state["history_count"] >= 3

    def test_failopen_subscriber_exception(self):
        """RED: 订阅者抛异常不阻塞其他订阅者（FAIL-OPEN）。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        received = []

        def bad_callback(content):
            raise RuntimeError("subscriber error")

        def good_callback(content):
            received.append(content)

        bus.subscribe("bad", bad_callback)
        bus.subscribe("good", good_callback)

        content = WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.5,
        )
        # 不应抛异常
        bus.broadcast(content)

        # good_callback 仍应收到
        assert len(received) == 1

    def test_unsubscribe(self):
        """RED: 取消订阅后不再收到广播。"""
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        received = []

        def callback(content):
            received.append(content)

        sub_id = bus.subscribe("test", callback)
        bus.broadcast(WorkspaceContent(
            intent={}, memory_recall=[], skill_match=[],
            knowledge_retrieval=[], confidence=0.5,
        ))
        assert len(received) == 1

        bus.unsubscribe(sub_id)
        bus.broadcast(WorkspaceContent(
            intent={}, memory_recall=[], skill_match=[],
            knowledge_retrieval=[], confidence=0.5,
        ))
        # 取消订阅后不再收到
        assert len(received) == 1

    def test_get_workspace_state_returns_dict(self):
        """RED: get_workspace_state() 返回完整状态字典。"""
        from workspace_bus import WorkspaceBus

        bus = WorkspaceBus()
        state = bus.get_workspace_state()

        assert isinstance(state, dict)
        assert "current" in state
        assert "subscribers" in state
        assert "history_count" in state

    def test_ignited_content_broadcast_to_all(self):
        """RED: 被点燃的内容广播到所有子系统。

        模拟 5 子系统订阅，高置信内容应被所有订阅者接收。
        """
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        received = {"memory": 0, "skill": 0, "knowledge": 0, "docs": 0, "index": 0}

        for name in received:
            def make_cb(n):
                def cb(content):
                    received[n] += 1
                return cb
            bus.subscribe(name, make_cb(name))

        content = WorkspaceContent(
            intent={"type": "high_confidence"},
            memory_recall=[{"id": "VM-001"}],
            skill_match=[{"id": "skill-1"}],
            knowledge_retrieval=[{"id": "chunk-1"}],
            confidence=0.9,  # > 0.8 → ignited
        )
        bus.broadcast(content)

        # 所有订阅者都应收到
        assert all(count == 1 for count in received.values())


class TestCognitiveLoopEntryWorkspaceBus:
    """CognitiveLoopEntry P3-1 集成点。"""

    def test_workspace_bus_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 workspace_bus 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        import inspect

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "workspace_bus" in src
        assert "WorkspaceBus" in src
