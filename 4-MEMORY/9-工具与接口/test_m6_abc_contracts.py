"""M6 ABC 接口契约 TDD RED 测试

SPEC: SPEC-CognitiveSystem-Evolution.md §3.5 M6

定义认知系统三层边界 ABC 契约：
  - CognitiveRouter  (L3 路由层接口 — Intent-Engine → 三库加权召回)
  - EvidenceSink     (L2 Evidence Ledger 接口 — 集中化决策审计 trail)
  - MetacogMonitor   (L4 元认知层接口 — 自我监控+错误检测，研究探索项)

RED 契约：
  - 三个 ABC 均不能直接实例化
  - 子类未实现 abstractmethod 时实例化失败
  - 完整子类可实例化且方法可调用
  - 方法签名正确（参数名+返回类型）

注意：本任务只定义接口契约，不强制已有实现类继承 ABC（渐进式）。
"""
from __future__ import annotations

import inspect
from typing import Any

import pytest


# ============================================================
# RED: CognitiveRouter (L3 路由层)
# ============================================================

def test_cognitive_router_is_abstract():
    """RED: CognitiveRouter 是 ABC，不能直接实例化。"""
    from cognitive_interfaces import CognitiveRouter
    with pytest.raises(TypeError):
        CognitiveRouter()


def test_cognitive_router_requires_route():
    """RED: 子类未实现 route() 时实例化失败。"""
    from cognitive_interfaces import CognitiveRouter

    class IncompleteRouter(CognitiveRouter):
        pass

    with pytest.raises(TypeError):
        IncompleteRouter()


def test_cognitive_router_subclass_works():
    """RED: 完整子类可实例化且 route() 可调用，返回 RecallResult。"""
    from cognitive_interfaces import CognitiveRouter, RecallResult

    class CompleteRouter(CognitiveRouter):
        def route(self, intent_vector: Any, databases: dict) -> RecallResult:
            return RecallResult(
                memories=[{"id": "m1"}],
                skills=[{"id": "s1"}],
                knowledge=[{"id": "k1"}],
                confidence=0.8,
            )

    router = CompleteRouter()
    result = router.route(intent_vector=[0.1, 0.9], databases={"mem": None})
    assert isinstance(result, RecallResult)
    assert result.memories == [{"id": "m1"}]
    assert result.skills == [{"id": "s1"}]
    assert result.knowledge == [{"id": "k1"}]
    assert result.confidence == 0.8


def test_cognitive_router_route_signature():
    """RED: route(self, intent_vector, databases) -> RecallResult 签名正确。"""
    from cognitive_interfaces import CognitiveRouter, RecallResult
    import typing
    sig = inspect.signature(CognitiveRouter.route)
    params = list(sig.parameters.keys())
    # self + intent_vector + databases
    assert params == ["self", "intent_vector", "databases"]
    # 返回注解为 RecallResult（用 get_type_hints 解析，因 from __future__ import annotations）
    hints = typing.get_type_hints(CognitiveRouter.route)
    assert hints.get("return") is RecallResult


# ============================================================
# RED: EvidenceSink (L2 Evidence Ledger)
# ============================================================

def test_evidence_sink_is_abstract():
    """RED: EvidenceSink 是 ABC，不能直接实例化。"""
    from cognitive_interfaces import EvidenceSink
    with pytest.raises(TypeError):
        EvidenceSink()


def test_evidence_sink_requires_append():
    """RED: 子类未实现 append() 时实例化失败。"""
    from cognitive_interfaces import EvidenceSink

    class IncompleteSink(EvidenceSink):
        pass

    with pytest.raises(TypeError):
        IncompleteSink()


def test_evidence_sink_subclass_works():
    """RED: 完整子类可实例化且 append() 可调用，返回 str。"""
    from cognitive_interfaces import EvidenceSink

    class CompleteSink(EvidenceSink):
        def append(self, entry: Any) -> str:
            return "receipt_fixed"

    sink = CompleteSink()
    receipt = sink.append(entry={"subject": "test"})
    assert isinstance(receipt, str)
    assert receipt == "receipt_fixed"


def test_evidence_sink_append_signature():
    """RED: append(self, entry) -> str 签名正确。"""
    from cognitive_interfaces import EvidenceSink
    import typing
    sig = inspect.signature(EvidenceSink.append)
    params = list(sig.parameters.keys())
    assert params == ["self", "entry"]
    hints = typing.get_type_hints(EvidenceSink.append)
    assert hints.get("return") is str


# ============================================================
# RED: MetacogMonitor (L4 元认知层 — 研究探索项)
# ============================================================

def test_metacog_monitor_is_abstract():
    """RED: MetacogMonitor 是 ABC，不能直接实例化。"""
    from cognitive_interfaces import MetacogMonitor
    with pytest.raises(TypeError):
        MetacogMonitor()


def test_metacog_monitor_requires_monitor():
    """RED: 子类未实现 monitor() 时实例化失败。"""
    from cognitive_interfaces import MetacogMonitor

    class IncompleteMonitor(MetacogMonitor):
        pass

    with pytest.raises(TypeError):
        IncompleteMonitor()


def test_metacog_monitor_subclass_works():
    """RED: 完整子类可实例化且 monitor() 可调用，返回 MonitorResult。"""
    from cognitive_interfaces import MetacogMonitor, MonitorResult

    class CompleteMonitor(MetacogMonitor):
        def monitor(self, workspace_state: dict) -> MonitorResult:
            return MonitorResult(
                action="proceed",
                targets=["target_1"],
                calibration=0.95,
            )

    monitor = CompleteMonitor()
    result = monitor.monitor(workspace_state={"active": True})
    assert isinstance(result, MonitorResult)
    assert result.action == "proceed"
    assert result.targets == ["target_1"]
    assert result.calibration == 0.95


def test_metacog_monitor_monitor_signature():
    """RED: monitor(self, workspace_state) -> MonitorResult 签名正确。"""
    from cognitive_interfaces import MetacogMonitor, MonitorResult
    import typing
    sig = inspect.signature(MetacogMonitor.monitor)
    params = list(sig.parameters.keys())
    assert params == ["self", "workspace_state"]
    hints = typing.get_type_hints(MetacogMonitor.monitor)
    assert hints.get("return") is MonitorResult


# ============================================================
# RED: 结果类型 dataclass
# ============================================================

def test_recall_result_dataclass():
    """RED: RecallResult 是 dataclass，含 memories/skills/knowledge/confidence。"""
    from cognitive_interfaces import RecallResult
    result = RecallResult(memories=[], skills=[], knowledge=[])
    assert result.memories == []
    assert result.skills == []
    assert result.knowledge == []
    assert result.confidence == 0.0  # 默认值


def test_monitor_result_dataclass():
    """RED: MonitorResult 是 dataclass，含 action/targets/calibration。"""
    from cognitive_interfaces import MonitorResult
    result = MonitorResult(action="verify")
    assert result.action == "verify"
    assert result.targets == []
    assert result.calibration == 1.0  # 默认值
