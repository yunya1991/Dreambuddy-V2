"""
L3 自修复: Trace Replay + CircuitBreaker + AutoBugfix 单测
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.core.compute.trace_replay import (
    TraceReplayEngine, ReplayStatus, ReplayComparison, ReplayResult,
)
from dreamos.core.compute.circuit_breaker import (
    CircuitBreaker, CircuitState, CircuitBreakerOpen,
    CircuitBreakerRegistry, LLMDegradationChain,
)
from dreamos.core.compute.auto_bugfix import (
    AutoBugfixLoop, BugfixAction, BugfixReport,
    create_default_auto_bugfix,
)


# ============================================================================
# Trace Replay 测试
# ============================================================================

class TestTraceReplayEngine:
    """Trace Replay 引擎测试"""

    def test_replay_match(self):
        """原始和重放完全匹配 → MATCH"""
        events = [
            {"trace_id": "t1", "system": "frontend", "layer": "api",
             "node": "task", "event_type": "created", "status": "ok", "ts": "2026-09-29T10:00:00Z"},
            {"trace_id": "t1", "system": "dreamos", "layer": "graph",
             "node": "A1", "event_type": "execute", "status": "ok", "ts": "2026-09-29T10:00:01Z"},
        ]
        engine = TraceReplayEngine(
            events_reader=lambda tid: events if tid == "t1" else [],
            replayer=lambda e: {**e, "ts": "2026-09-29T11:00:00Z"},  # 只改 ts
        )
        result = engine.replay("t1")
        assert result.status == ReplayStatus.COMPLETED
        assert result.comparison == ReplayComparison.MATCH
        assert result.matched_count == 2
        assert result.mismatched_count == 0

    def test_replay_partial(self):
        """部分字段不同 → PARTIAL"""
        events = [
            {"trace_id": "t1", "system": "frontend", "layer": "api",
             "node": "task", "event_type": "created", "status": "ok", "ts": "2026-09-29T10:00:00Z"},
            {"trace_id": "t1", "system": "dreamos", "layer": "graph",
             "node": "A1", "event_type": "execute", "status": "ok", "ts": "2026-09-29T10:00:01Z"},
        ]
        engine = TraceReplayEngine(
            events_reader=lambda tid: events,
            replayer=lambda e: {**e, "status": "fail"} if e["node"] == "A1" else {**e},
        )
        result = engine.replay("t1")
        assert result.comparison == ReplayComparison.PARTIAL
        assert result.matched_count == 1
        assert result.mismatched_count == 1

    def test_replay_mismatch_node_count(self):
        """重放事件数与原始不同 → MISMATCH
        replayer 返回 dict，但 status 不同 → 节点数一致但内容不匹配"""
        events = [
            {"trace_id": "t1", "system": "frontend", "layer": "api",
             "node": "task", "event_type": "created", "status": "ok", "ts": "t"},
            {"trace_id": "t1", "system": "dreamos", "layer": "node",
             "node": "A1", "event_type": "exec", "status": "ok", "ts": "t2"},
        ]
        engine = TraceReplayEngine(
            events_reader=lambda tid: events,
            replayer=lambda e: {**e, "status": "fail", "system": "dsh"},
        )
        result = engine.replay("t1")
        assert result.comparison == ReplayComparison.MISMATCH

    def test_replay_no_original_events(self):
        """无原始事件 → FAILED"""
        engine = TraceReplayEngine(
            events_reader=lambda tid: [],
            replayer=lambda e: e,
        )
        result = engine.replay("t1")
        assert result.status == ReplayStatus.FAILED
        assert "未找到" in (result.error or "")

    def test_replay_ok_degraded_compatible(self):
        """ok 和 degraded 视为匹配"""
        events = [
            {"trace_id": "t1", "system": "dreamos", "layer": "node",
             "node": "A1", "event_type": "exec", "status": "ok", "ts": "t1"},
        ]
        engine = TraceReplayEngine(
            events_reader=lambda tid: events,
            replayer=lambda e: {**e, "status": "degraded"},
        )
        result = engine.replay("t1")
        assert result.comparison == ReplayComparison.MATCH

    def test_replay_different_system_mismatch(self):
        """system 不同 → MISMATCH"""
        events = [
            {"trace_id": "t1", "system": "frontend", "layer": "api",
             "node": "task", "event_type": "created", "status": "ok", "ts": "t"},
        ]
        engine = TraceReplayEngine(
            events_reader=lambda tid: events,
            replayer=lambda e: {**e, "system": "dreamos"},
        )
        result = engine.replay("t1")
        assert result.comparison == ReplayComparison.MISMATCH

    def test_replay_result_to_dict(self):
        """to_dict 可序列化"""
        engine = TraceReplayEngine(
            events_reader=lambda tid: [],
            replayer=lambda e: e,
        )
        result = engine.replay("t1")
        d = result.to_dict()
        assert "trace_id" in d
        assert "status" in d
        assert "comparison" in d

    def test_replay_duration_tracked(self):
        """重放耗时被记录"""
        events = [{"trace_id": "t1", "system": "frontend", "status": "ok", "ts": "t"}]
        engine = TraceReplayEngine(
            events_reader=lambda tid: events,
            replayer=lambda e: {**e},
        )
        result = engine.replay("t1")
        assert result.duration_ms > 0


# ============================================================================
# CircuitBreaker 测试
# ============================================================================

class TestCircuitBreaker:
    """断路器测试"""

    def test_initial_state_closed(self):
        """初始状态 CLOSED"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        assert b.state == CircuitState.CLOSED

    def test_success_stays_closed(self):
        """成功保持 CLOSED"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        with b:
            pass  # 成功
        assert b.state == CircuitState.CLOSED
        assert b.stats.success_count == 1

    def test_failure_increments_counter(self):
        """失败增加计数器"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert b.stats.consecutive_failures == 1
        assert b.state == CircuitState.CLOSED  # 还没到阈值

    def test_threshold_reaches_open(self):
        """连续失败达阈值 → OPEN"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        for _ in range(3):
            try:
                with b:
                    raise RuntimeError("fail")
            except RuntimeError:
                pass
        assert b.state == CircuitState.OPEN
        assert b.stats.open_count == 1

    def test_open_blocks_calls(self):
        """OPEN 状态阻止调用"""
        b = CircuitBreaker("test", threshold=1, timeout_s=60)
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert b.state == CircuitState.OPEN
        with pytest.raises(CircuitBreakerOpen):
            with b:
                pass

    def test_fallback_on_open(self):
        """OPEN 时使用 fallback"""
        b = CircuitBreaker("test", threshold=1, timeout_s=60)
        b.set_fallback(lambda: "fallback_value")
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        # 现在是 OPEN
        result = b.call(lambda: "normal")
        assert result == "fallback_value"

    def test_call_with_fallback_on_exception(self):
        """call 方法异常时使用 fallback"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        b.set_fallback(lambda: "safe")
        result = b.call(lambda: 1/0)
        assert result == "safe"

    def test_call_success_no_fallback(self):
        """成功时不使用 fallback"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        result = b.call(lambda: "ok")
        assert result == "ok"

    def test_reset(self):
        """手动重置"""
        b = CircuitBreaker("test", threshold=1, timeout_s=60)
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        assert b.state == CircuitState.OPEN
        b.reset()
        assert b.state == CircuitState.CLOSED
        assert b.stats.total_calls == 0

    def test_to_dict(self):
        """to_dict 输出完整状态"""
        b = CircuitBreaker("test", threshold=3, timeout_s=60)
        with b:
            pass
        d = b.to_dict()
        assert d["name"] == "test"
        assert d["state"] == "closed"
        assert d["stats"]["total_calls"] == 1


class TestCircuitBreakerHalfOpen:
    """半开状态测试"""

    def test_half_open_after_timeout(self):
        """超时后转 HALF_OPEN"""
        b = CircuitBreaker("test", threshold=1, timeout_s=0)  # timeout=0 立即过
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        # timeout=0 → 立即转 HALF_OPEN（在 state 属性中检查时自动转换）
        assert b.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        """HALF_OPEN 成功 → CLOSED"""
        b = CircuitBreaker("test", threshold=1, timeout_s=0)
        # 打开断路器
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        # 强制转 HALF_OPEN
        with b._lock:
            b._state = CircuitState.HALF_OPEN
            b._half_open_calls = 0
        # 成功
        with b:
            pass
        assert b.state == CircuitState.CLOSED

    def test_half_open_failure_reopens(self):
        """HALF_OPEN 失败 → 重新 OPEN"""
        b = CircuitBreaker("test", threshold=1, timeout_s=60)
        # 打开断路器
        try:
            with b:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        # 强制转 HALF_OPEN
        with b._lock:
            b._state = CircuitState.HALF_OPEN
            b._half_open_calls = 0
        # 失败
        try:
            with b:
                raise RuntimeError("still failing")
        except RuntimeError:
            pass
        assert b.state == CircuitState.OPEN
        assert b.stats.open_count == 2


class TestCircuitBreakerRegistry:
    """断路器注册表测试"""

    def test_register_and_get(self):
        """注册后可查询"""
        reg = CircuitBreakerRegistry()
        b = reg.register("okx", threshold=3)
        assert reg.get("okx") is b

    def test_call_through_breaker(self):
        """通过注册表调用"""
        reg = CircuitBreakerRegistry()
        reg.register("okx", threshold=3)
        result = reg.call("okx", lambda: "ok")
        assert result == "ok"

    def test_call_unknown_breaker_passthrough(self):
        """未注册的断路器直接调用"""
        reg = CircuitBreakerRegistry()
        result = reg.call("unknown", lambda: "direct")
        assert result == "direct"

    def test_status_all(self):
        """status 返回全部断路器状态"""
        reg = CircuitBreakerRegistry()
        reg.register("okx", threshold=3)
        reg.register("llm", threshold=5)
        status = reg.status()
        assert "okx" in status
        assert "llm" in status

    def test_reset_all(self):
        """reset_all 重置所有"""
        reg = CircuitBreakerRegistry()
        b1 = reg.register("okx", threshold=1)
        b2 = reg.register("llm", threshold=1)
        try:
            with b1:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        try:
            with b2:
                raise RuntimeError("fail")
        except RuntimeError:
            pass
        reg.reset_all()
        assert b1.state == CircuitState.CLOSED
        assert b2.state == CircuitState.CLOSED


class TestLLMDegradationChain:
    """LLM 降级链测试"""

    def test_first_provider_success(self):
        """第一个 provider 成功"""
        chain = LLMDegradationChain()
        chain.add_provider("deepseek", lambda **kw: {"content": "ds_result"})
        chain.add_provider("qwen", lambda **kw: {"content": "qwen_result"})
        result = chain.call(prompt="test")
        assert result["content"] == "ds_result"
        assert result["_provider"] == "deepseek"

    def test_fallback_to_second(self):
        """第一个失败，降级到第二个"""
        chain = LLMDegradationChain()
        chain.add_provider("deepseek", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
        chain.add_provider("qwen", lambda **kw: {"content": "qwen_result"})
        result = chain.call(prompt="test")
        assert result["content"] == "qwen_result"
        assert result["_provider"] == "qwen"

    def test_all_fail_returns_noop(self):
        """全部失败 → noop 空结果"""
        chain = LLMDegradationChain()
        chain.add_provider("deepseek", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
        chain.add_provider("qwen", lambda **kw: (_ for _ in ()).throw(RuntimeError("down")))
        result = chain.call(prompt="test")
        assert result["content"] == ""
        assert result["error"] == "all providers failed"


# ============================================================================
# AutoBugfix 测试
# ============================================================================

class TestAutoBugfixLoop:
    """自动 bugfix 闭环测试"""

    def test_no_anomaly_no_action(self):
        """无异常 → NO_ACTION"""
        loop = AutoBugfixLoop(
            health_check_fn=lambda: [],
            recall_fn=lambda **kw: [],
            record_fn=lambda **kw: {"memory_id": "test"},
        )
        report = loop.run_once()
        assert report.action == BugfixAction.NO_ACTION
        assert report.recorded is False

    def test_anomaly_recall_hit_auto_fix(self):
        """异常 + recall 命中 → AUTO_FIX"""
        mock_fix = MagicMock(return_value="fixed")
        loop = AutoBugfixLoop(
            health_check_fn=lambda: [{"name": "budget", "status": "unhealthy", "message": "预算耗尽"}],
            recall_fn=lambda **kw: [{"id": "VM-001", "content": "budget fix经验"}],
            record_fn=lambda **kw: {"memory_id": "VM-new"},
            auto_fix_fn=mock_fix,
        )
        report = loop.run_once()
        assert report.action == BugfixAction.AUTO_FIX
        assert report.fix_applied is True
        assert report.recorded is True
        mock_fix.assert_called_once()

    def test_anomaly_recall_miss_manual(self):
        """异常 + recall 未命中 → MANUAL_REQUIRED"""
        loop = AutoBugfixLoop(
            health_check_fn=lambda: [{"name": "budget", "status": "unhealthy", "message": "耗尽"}],
            recall_fn=lambda **kw: [],
            record_fn=lambda **kw: {"memory_id": "VM-new"},
        )
        report = loop.run_once()
        assert report.action == BugfixAction.MANUAL_REQUIRED
        assert report.recorded is True

    def test_record_quality_c_for_manual(self):
        """手动修复记录为 C 级"""
        mock_record = MagicMock(return_value={"memory_id": "VM-c"})
        loop = AutoBugfixLoop(
            health_check_fn=lambda: [{"name": "test", "status": "unhealthy", "message": "fail"}],
            recall_fn=lambda **kw: [],
            record_fn=mock_record,
        )
        report = loop.run_once()
        assert report.action == BugfixAction.MANUAL_REQUIRED
        mock_record.assert_called_once()
        args, kwargs = mock_record.call_args
        assert kwargs["quality_level"] == "C"

    def test_record_quality_b_for_auto_fix(self):
        """自动修复记录为 B 级"""
        mock_record = MagicMock(return_value={"memory_id": "VM-b"})
        loop = AutoBugfixLoop(
            health_check_fn=lambda: [{"name": "test", "status": "degraded", "message": "low"}],
            recall_fn=lambda **kw: [{"id": "VM-001", "content": "fix"}],
            record_fn=mock_record,
            auto_fix_fn=lambda a, m: "fixed",
        )
        report = loop.run_once()
        assert report.action == BugfixAction.AUTO_FIX
        mock_record.assert_called_once()
        args, kwargs = mock_record.call_args
        assert kwargs["quality_level"] == "B"

    def test_health_check_exception_returns_no_action(self):
        """健康检查异常 → NO_ACTION"""
        loop = AutoBugfixLoop(
            health_check_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        report = loop.run_once()
        assert report.action == BugfixAction.NO_ACTION

    def test_report_to_dict(self):
        """to_dict 可序列化"""
        loop = AutoBugfixLoop(
            health_check_fn=lambda: [],
        )
        report = loop.run_once()
        d = report.to_dict()
        assert "action" in d
        assert "timestamp" in d

    def test_create_default_auto_bugfix(self):
        """create_default_auto_bugfix 工厂"""
        loop = create_default_auto_bugfix(
            health_checker=None,
            cognitive_recall=lambda **kw: [],
            cognitive_record=lambda **kw: {"memory_id": "x"},
        )
        assert isinstance(loop, AutoBugfixLoop)
        report = loop.run_once()
        assert report.action == BugfixAction.NO_ACTION
