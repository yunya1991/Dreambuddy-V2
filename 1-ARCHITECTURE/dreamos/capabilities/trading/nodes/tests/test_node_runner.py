"""
L2 自检测: NodeRunner 节点执行器单测
覆盖: 前置检查/超时/重试/退避/失败回退/预算检查
"""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(PROJECT_ROOT / "1-ARCHITECTURE"))

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.errors import ErrorCode
from dreamos.core.compute.node_runner import NodeRunner
from dreamos.core.compute.types import NodeExecutionRecord


def make_mock_node(node_id="A1", estimated_tokens=100):
    """构造 mock 节点"""
    node = MagicMock()
    node.node_id = node_id
    node.estimated_tokens = estimated_tokens
    node.validate.return_value = None
    return node


def make_state():
    return State(cycle_id="test")


class TestNodeRunnerPreCheck:
    """前置检查测试"""

    def test_validate_failure_skips_node(self):
        """validate 失败 → SKIPPED"""
        node = make_mock_node()
        node.validate.return_value = "依赖缺失"
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state())
        assert record.status == "skipped"
        assert record.error == "前置检查失败: 依赖缺失"

    def test_validate_exception_skips_node(self):
        """validate 抛异常 → SKIPPED"""
        node = make_mock_node()
        node.validate.side_effect = RuntimeError("boom")
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state())
        assert record.status == "skipped"
        assert "前置检查异常" in record.error

    def test_budget_insufficient_skips(self):
        """预算不足 → SKIPPED"""
        node = make_mock_node(estimated_tokens=500)
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state(), allocated_tokens=100)
        assert record.status == "skipped"
        assert "预算不足" in record.error

    def test_budget_sufficient_passes(self):
        """预算充足 → 通过前置检查"""
        node = make_mock_node(estimated_tokens=50)
        node.execute.return_value = NodeResult(node_id="A1", confidence=0.8, direction="LONG")
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state(), allocated_tokens=100)
        assert record.status == "success"

    def test_disable_pre_check(self):
        """禁用前置检查 → 直接执行"""
        node = make_mock_node()
        node.validate.return_value = "依赖缺失"  # 即使 validate 失败也不跳过
        node.execute.return_value = NodeResult(node_id="A1", confidence=0.8, direction="LONG")
        runner = NodeRunner(max_retries=0, enable_pre_check=False)
        record = runner.run(node, make_state())
        assert record.status == "success"


class TestNodeRunnerExecution:
    """执行与重试测试"""

    def test_successful_execution(self):
        """正常执行成功"""
        node = make_mock_node()
        node.execute.return_value = NodeResult(
            node_id="A1", confidence=0.8, direction="LONG", tokens_used=42
        )
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state())
        assert record.status == "success"
        assert record.confidence == 0.8
        assert record.direction == "LONG"
        assert record.tokens_used == 42
        assert record.retries == 0

    def test_execute_exception_fallback_success(self):
        """execute 抛异常但 fallback 成功 → degraded/success"""
        node = make_mock_node()
        node.execute.side_effect = RuntimeError("LLM timeout")
        node.fallback.return_value = NodeResult(
            node_id="A1", status=NodeStatus.DEGRADED, confidence=0.5, direction="HOLD"
        )
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state())
        assert record.status in ("degraded", "success")
        node.fallback.assert_called_once()

    def test_execute_exception_fallback_fails(self):
        """execute 抛异常且 fallback 也失败 → failed"""
        node = make_mock_node()
        node.execute.side_effect = RuntimeError("boom")
        node.fallback.side_effect = RuntimeError("fallback also failed")
        runner = NodeRunner(max_retries=0)
        record = runner.run(node, make_state())
        assert record.status == "failed"

    def test_state_updated_after_execution(self):
        """执行后 state 被更新"""
        node = make_mock_node()
        node.execute.return_value = NodeResult(node_id="A1", confidence=0.8, direction="LONG")
        runner = NodeRunner(max_retries=0)
        state = make_state()
        runner.run(node, state)
        assert "A1" in state.results
        assert state.results["A1"].confidence == 0.8


class TestNodeRunnerRetry:
    """重试逻辑测试"""

    def test_retry_on_retryable_error(self):
        """可重试错误 → 重试后成功"""
        node = make_mock_node()
        # 第一次失败（可重试），第二次成功
        node.execute.side_effect = [
            NodeResult(node_id="A1", status=NodeStatus.FAILED, error_code=ErrorCode.EXEC_002, error="retryable"),
            NodeResult(node_id="A1", confidence=0.8, direction="LONG"),
        ]
        runner = NodeRunner(max_retries=2)
        record = runner.run(node, make_state())
        assert record.status == "success"
        assert record.retries == 1

    def test_max_retries_exhausted(self):
        """重试次数耗尽 → 最终失败"""
        node = make_mock_node()
        node.execute.return_value = NodeResult(
            node_id="A1", status=NodeStatus.FAILED,
            error_code=ErrorCode.EXEC_002, error="always fail"
        )
        runner = NodeRunner(max_retries=2)
        record = runner.run(node, make_state())
        assert record.status == "failed"
        assert record.retries == 2

    def test_non_retryable_error_no_retry(self):
        """不可重试错误 → 不重试"""
        node = make_mock_node()
        node.execute.return_value = NodeResult(
            node_id="A1", status=NodeStatus.FAILED,
            error_code=ErrorCode.NODE_001, error="non-retryable"
        )
        runner = NodeRunner(max_retries=3)
        record = runner.run(node, make_state())
        assert record.retries == 0

    def test_retryable_errors_disabled(self):
        """禁用可重试错误 → 不重试"""
        node = make_mock_node()
        node.execute.return_value = NodeResult(
            node_id="A1", status=NodeStatus.FAILED,
            error_code=ErrorCode.EXEC_002, error="retryable"
        )
        runner = NodeRunner(max_retries=3, retryable_errors=False)
        record = runner.run(node, make_state())
        assert record.retries == 0


class TestNodeRunnerTimeout:
    """超时测试"""

    def test_timeout_returns_failed(self):
        """执行超时 → FAILED"""
        node = make_mock_node()

        def slow_execute(state):
            time.sleep(2)  # 超过 timeout
            return NodeResult(node_id="A1")

        node.execute.side_effect = slow_execute
        runner = NodeRunner(max_retries=0, timeout_ms=100)
        record = runner.run(node, make_state())
        assert record.status == "failed"
        assert "超时" in (record.error or "")

    def test_within_timeout_succeeds(self):
        """超时内完成 → 成功"""
        node = make_mock_node()
        node.execute.return_value = NodeResult(node_id="A1", confidence=0.8, direction="LONG")
        runner = NodeRunner(max_retries=0, timeout_ms=5000)
        record = runner.run(node, make_state())
        assert record.status == "success"


class TestNodeRunnerBackoff:
    """退避测试"""

    def test_backoff_delay_increases(self):
        """退避延迟指数增长"""
        runner = NodeRunner(max_retries=3)
        # 验证退避计算逻辑（不实际 sleep）
        with patch("dreamos.core.compute.node_runner.time.sleep") as mock_sleep:
            runner._backoff(1)
            runner._backoff(2)
            runner._backoff(3)
            # 100ms, 200ms, 400ms
            assert mock_sleep.call_count == 3
            delays = [call.args[0] for call in mock_sleep.call_args_list]
            assert delays[0] < delays[1] < delays[2]
