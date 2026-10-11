"""P3-6 Reflection Node TDD RED 测试

借鉴 JPMorgan Ask David 多 Agent 架构（supervisor + reflection node）+
Bridgewater "Pain + Reflection = Progress"。现状：调度链末尾无 LLM-judge 回环。

核心机制:
  1. reflect(execution_result) — 调度链末尾反思裁决（LLM-judge 规则版）:
     - verdict: "pass" | "needs-improvement" | "fail"
     - lessons: 提取的教训列表
     - should_record: 非 pass 或高价值学习 → True（触发 record 认知闭环）
  2. attach_to_workspace_bus(bus) — 订阅 P3-1 广播（调度链末尾回环接入）
  3. get_pending_reflections() — 获取待处理反思队列

RED 契约:
  1. reflection_node 模块不存在 → ImportError
  2. ReflectionNode 类不存在
  3. CognitiveLoopEntry 无 reflection_node 属性

参考: SPEC-CognitiveSystem-Evolution.md §1.1 + §4.3 P3-6
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))


class TestReflectVerdict:
    """反思裁决能力（LLM-judge 规则版）。"""

    def test_import_reflection_node(self):
        """RED: reflection_node 模块可导入。"""
        from reflection_node import ReflectionNode  # noqa: F401

    def test_reflect_success_pass(self):
        """RED: 执行成功且无错误 → verdict=pass。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect({
            "success": True,
            "error": None,
            "steps": 3,
            "output": "done",
        })
        assert result["verdict"] == "pass"
        assert result["should_record"] is False

    def test_reflect_failure_fail(self):
        """RED: 执行失败 → verdict=fail + should_record=True。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect({
            "success": False,
            "error": "timeout",
            "steps": 2,
            "output": None,
        })
        assert result["verdict"] == "fail"
        assert result["should_record"] is True
        assert len(result["lessons"]) > 0

    def test_reflect_error_message_in_lessons(self):
        """RED: 错误信息被提取进 lessons。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect({
            "success": False,
            "error": "connection refused",
        })
        assert any("connection refused" in str(lesson) for lesson in result["lessons"])

    def test_reflect_slow_execution_needs_improvement(self):
        """RED: 执行过慢（duration > 阈值）→ verdict=needs-improvement。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect({
            "success": True,
            "error": None,
            "duration_seconds": 300,  # 超过默认慢阈值
        })
        assert result["verdict"] == "needs-improvement"
        assert result["should_record"] is True

    def test_reflect_returns_required_keys(self):
        """RED: 返回包含 verdict/lessons/should_record 的字典。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect({"success": True})
        for key in ("verdict", "lessons", "should_record"):
            assert key in result

    def test_reflect_failopen_none(self):
        """RED: None 输入 → FAIL-OPEN 保守 pass 不阻塞。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect(None)
        assert result["verdict"] == "pass"

    def test_reflect_failopen_invalid_type(self):
        """RED: 非 dict 输入 → FAIL-OPEN 不抛异常。"""
        from reflection_node import ReflectionNode

        node = ReflectionNode()
        result = node.reflect("not-a-dict")
        assert isinstance(result, dict)


class TestWorkspaceBusIntegration:
    """P3-1 WorkspaceBus 集成（调度链末尾回环）。"""

    def test_attach_to_workspace_bus(self):
        """RED: attach_to_workspace_bus() 订阅广播并返回 sub_id。"""
        from reflection_node import ReflectionNode
        from workspace_bus import WorkspaceBus

        bus = WorkspaceBus()
        node = ReflectionNode()
        sub_id = node.attach_to_workspace_bus(bus)
        assert sub_id

        state = bus.get_workspace_state()
        assert state["subscribers"] == 1

    def test_broadcast_enqueues_pending_reflection(self):
        """RED: 广播后 execution_result 进入待反思队列。"""
        from reflection_node import ReflectionNode
        from workspace_bus import WorkspaceBus, WorkspaceContent

        bus = WorkspaceBus()
        node = ReflectionNode()
        node.attach_to_workspace_bus(bus)

        # 广播带 execution_result 的内容（模拟调度链末尾）
        bus.broadcast(WorkspaceContent(
            intent={"type": "query"},
            memory_recall=[],
            skill_match=[],
            knowledge_retrieval=[],
            confidence=0.5,
            execution_result={"success": False, "error": "boom"},
        ))

        pending = node.get_pending_reflections()
        assert len(pending) == 1
        assert pending[0]["execution_result"]["error"] == "boom"


class TestCognitiveLoopEntryIntegration:
    """CognitiveLoopEntry P3-6 集成点。"""

    def test_reflection_node_attribute_exists(self):
        """RED: CognitiveLoopEntry 应有 reflection_node 属性。"""
        from cognitive_loop_entry import CognitiveLoopEntry

        src = inspect.getsource(CognitiveLoopEntry.__init__)
        assert "reflection_node" in src
        assert "ReflectionNode" in src
