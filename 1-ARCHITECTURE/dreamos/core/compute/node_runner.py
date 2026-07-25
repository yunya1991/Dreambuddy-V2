"""
DreamOS C层 — 节点执行器

职责:
    1. 前置检查（依赖满足、预算充足）
    2. 执行单个节点（含超时控制）
    3. 失败重试（指数退避）
    4. 记录执行结果
    5. 消耗 Token 预算

执行流程:
    pre_check → execute → (失败时) retry with backoff → (仍失败时) fallback
"""

from __future__ import annotations

import time
import threading
from typing import Optional, Dict, Any

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.interfaces import Node
from dreamos.shared.utils import Timer
from dreamos.shared.errors import ErrorCode

from .types import NodeExecutionRecord


class NodeRunner:
    """节点执行器 — 执行单个节点并记录结果

    用法:
        runner = NodeRunner(max_retries=2, timeout_ms=30000)
        record = runner.run(node, state, allocated_tokens=500)
    """

    BASE_BACKOFF_MS = 100
    BACKOFF_MULTIPLIER = 2.0

    def __init__(self,
                 max_retries: int = 2,
                 retryable_errors: bool = True,
                 timeout_ms: int = 30000,
                 enable_pre_check: bool = True):
        self._max_retries = max_retries
        self._retryable_errors = retryable_errors
        self._timeout_ms = timeout_ms
        self._enable_pre_check = enable_pre_check

    def run(self, node: Node, state: State,
            allocated_tokens: int = 0) -> NodeExecutionRecord:
        """执行节点

        Args:
            node: 要执行的节点
            state: 全局状态
            allocated_tokens: 分配的 Token 预算

        Returns:
            NodeExecutionRecord: 执行记录
        """
        timer = Timer(f"node_{node.node_id}")
        retries = 0
        last_result: Optional[NodeResult] = None

        # ── 前置检查 ──────────────────────────
        if self._enable_pre_check:
            check_error = self._pre_check(node, state, allocated_tokens)
            if check_error:
                last_result = NodeResult(
                    node_id=node.node_id,
                    status=NodeStatus.SKIPPED,
                    confidence=0.0,
                    error=check_error,
                    error_code=ErrorCode.EXEC_003,
                )
                state.update(node.node_id, last_result)
                return NodeExecutionRecord(
                    node_id=node.node_id,
                    status="skipped",
                    confidence=0.0,
                    direction=None,
                    latency_ms=0,
                    tokens_used=0,
                    retries=0,
                    error=check_error,
                )

        # ── 执行 + 重试循环（指数退避）────────
        while retries <= self._max_retries:
            try:
                with timer:
                    result = self._execute_with_timeout(node, state)
                last_result = result

                if result.success or not self._is_retryable(result):
                    break

                if retries < self._max_retries:
                    retries += 1
                    self._backoff(retries)
                    continue
                break

            except Exception as e:
                try:
                    result = node.fallback(state)
                    last_result = result
                    if result.success:
                        break
                except Exception:
                    last_result = NodeResult(
                        node_id=node.node_id,
                        status=NodeStatus.FAILED,
                        error=f"执行异常: {e}",
                        error_code=ErrorCode.EXEC_002,
                    )
                break

        status_str = "success"
        if last_result:
            if last_result.status == NodeStatus.DEGRADED:
                status_str = "degraded"
            elif last_result.status == NodeStatus.FAILED:
                status_str = "failed"
            elif last_result.status == NodeStatus.SKIPPED:
                status_str = "skipped"

        if last_result and last_result.node_id:
            state.update(node.node_id, last_result)

        record = NodeExecutionRecord(
            node_id=node.node_id,
            status=status_str,
            confidence=last_result.confidence if last_result else 0.0,
            direction=last_result.direction if last_result else None,
            latency_ms=timer.elapsed_ms,
            tokens_used=last_result.tokens_used if last_result else 0,
            retries=retries,
            error=last_result.error if last_result else None,
        )

        return record

    # ── 内部方法 ──────────────────────────

    def _pre_check(self, node: Node, state: State,
                   allocated_tokens: int) -> Optional[str]:
        """前置检查：依赖满足 + 预算充足

        Returns:
            None 表示通过，否则返回错误原因
        """
        # 1. 依赖检查：调用节点 validate 方法
        try:
            validate_err = node.validate(state)
            if validate_err:
                return f"前置检查失败: {validate_err}"
        except Exception as e:
            return f"前置检查异常: {e}"

        # 2. 预算检查
        if allocated_tokens > 0:
            estimated = getattr(node, "estimated_tokens", 0)
            if estimated and estimated > allocated_tokens:
                return (
                    f"预算不足: 节点预估{estimated}tokens > "
                    f"分配{allocated_tokens}tokens"
                )

        return None

    def _execute_with_timeout(self, node: Node, state: State) -> NodeResult:
        """带超时控制的节点执行"""
        result_holder: Dict[str, Any] = {"result": None, "error": None}

        def _target():
            try:
                result_holder["result"] = node.execute(state)
            except Exception as e:
                result_holder["error"] = e

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=self._timeout_ms / 1000.0)

        if thread.is_alive():
            return NodeResult(
                node_id=node.node_id,
                status=NodeStatus.FAILED,
                confidence=0.0,
                error=f"执行超时（>{self._timeout_ms}ms）",
                error_code=ErrorCode.EXEC_001,
            )

        if result_holder["error"]:
            raise result_holder["error"]

        return result_holder["result"]

    def _backoff(self, retry_num: int) -> None:
        """指数退避等待

        第1次重试: 100ms * 2^0 = 100ms
        第2次重试: 100ms * 2^1 = 200ms
        第3次重试: 100ms * 2^2 = 400ms
        """
        delay_ms = self.BASE_BACKOFF_MS * (self.BACKOFF_MULTIPLIER ** (retry_num - 1))
        time.sleep(delay_ms / 1000.0)

    def _is_retryable(self, result: NodeResult) -> bool:
        """判断结果是否可重试"""
        if not self._retryable_errors:
            return False
        if result.status == NodeStatus.SUCCESS:
            return False
        retryable_codes = {
            ErrorCode.EXEC_001,
            ErrorCode.EXEC_002,
            ErrorCode.SYS_002,
            ErrorCode.SYS_003,
        }
        return result.error_code in retryable_codes
