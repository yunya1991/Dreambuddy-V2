"""
DreamOS C层 — 节点执行器

职责:
    1. 执行单个节点
    2. 处理失败重试（可配置次数）
    3. 记录执行结果
    4. 消耗 Token 预算

执行流程:
    validate → execute → (失败时) retry → (仍失败时) fallback
"""

from __future__ import annotations

from typing import Optional, Dict, Any

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.interfaces import Node
from dreamos.shared.utils import Timer
from dreamos.shared.errors import ErrorCode

from .types import NodeExecutionRecord


class NodeRunner:
    """节点执行器 — 执行单个节点并记录结果

    用法:
        runner = NodeRunner(max_retries=2)
        record = runner.run(node, state, allocated_tokens=500)
    """

    def __init__(self, max_retries: int = 2, retryable_errors: bool = True):
        self._max_retries = max_retries
        self._retryable_errors = retryable_errors

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

        # 重试循环
        while retries <= self._max_retries:
            try:
                with timer:
                    result = node.execute(state)
                last_result = result

                # 成功或不可重试的失败
                if result.success or not self._is_retryable(result):
                    break

                # 可重试的失败
                if retries < self._max_retries:
                    retries += 1
                    continue
                break

            except Exception as e:
                # 尝试降级
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

        # 构建执行记录
        status_str = "success"
        if last_result:
            if last_result.status == NodeStatus.DEGRADED:
                status_str = "degraded"
            elif last_result.status == NodeStatus.FAILED:
                status_str = "failed"
            elif last_result.status == NodeStatus.SKIPPED:
                status_str = "skipped"

        # 更新 State
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

    def _is_retryable(self, result: NodeResult) -> bool:
        """判断结果是否可重试"""
        if not self._retryable_errors:
            return False
        if result.status == NodeStatus.SUCCESS:
            return False
        # 可重试的错误码
        retryable_codes = {
            ErrorCode.EXEC_001,  # 超时
            ErrorCode.EXEC_002,  # 执行失败
            ErrorCode.SYS_002,   # 资源耗尽
            ErrorCode.SYS_003,   # 服务不可用
        }
        return result.error_code in retryable_codes
