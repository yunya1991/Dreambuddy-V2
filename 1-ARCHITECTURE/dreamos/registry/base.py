"""
Dreambuddy OS — Node 基类实现

提供 Node 接口的具体实现，子类只需实现 execute() 方法。

设计:
    - Node (ABC)        在 shared/interfaces.py — 纯接口
    - BaseNode          在本文件 — 带常用默认行为的基类
    - FunctionNode      在 adapters/function_adapter.py — 包装函数
    - 具体节点          在 os-nodes/ — A0/A1/... 业务节点

BaseNode 额外提供:
    - 自动计时（latency_ms 自动填充）
    - 自动错误处理（捕获异常转为 FAILED NodeResult）
    - 可选 LLM 客户端注入
    - 配置注入
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime

from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.interfaces import Node
from dreamos.shared.llm_client import LLMClient, get_default_client
from dreamos.shared.utils import Timer
from dreamos.shared.errors import ErrorCode


class BaseNode(Node):
    """节点基类 — 带常用默认行为

    子类只需实现 execute_core()，BaseNode 会:
        1. 自动计时
        2. 自动捕获异常转为 NodeResult
        3. 调用 validate() 做输入校验
        4. 失败时调用 fallback()

    用法:
        class A0Node(BaseNode):
            node_id = "A0"
            name = "矛盾论"
            chain = "A"

            def execute_core(self, state: State) -> NodeResult:
                # 业务逻辑
                return NodeResult(node_id="A0", confidence=0.7, direction="LONG")
    """

    # 元信息（子类重写）
    node_id: str = ""
    name: str = ""
    description: str = ""
    chain: str = ""
    tags: list = []

    def __init__(self, llm: Optional[LLMClient] = None, config: Optional[Dict[str, Any]] = None):
        self._llm = llm
        self._config = config or {}

    @property
    def llm(self) -> LLMClient:
        """LLM 客户端（延迟初始化）"""
        if self._llm is None:
            self._llm = get_default_client()
        return self._llm

    @property
    def config(self) -> Dict[str, Any]:
        return self._config

    # ── 子类实现这个方法 ────────────────────────────────

    def execute_core(self, state: State) -> NodeResult:
        """子类实现的核心执行逻辑（不包含错误处理和计时）

        默认返回一个 SUCCESS 结果。
        """
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            confidence=0.0,
            error=f"{self.node_id} 未实现 execute_core()",
        )

    # ── 模板方法（不要重写） ────────────────────────────

    def execute(self, state: State) -> NodeResult:
        """执行入口（模板方法，不要重写）

        流程:
            1. validate(state) → 校验失败返回 FAILED
            2. execute_core(state) → 自动计时
            3. 异常 → 标记 FAILED，调用 fallback
        """
        # 输入校验
        err = self.validate(state)
        if err:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                error_code=ErrorCode.DATA_001,
                error=f"输入校验失败: {err}",
                confidence=0.0,
            )

        # 执行 + 计时
        timer = Timer(self.node_id)
        try:
            with timer:
                result = self.execute_core(state)
        except Exception as e:
            # 异常 → 尝试降级
            try:
                result = self.fallback(state)
            except Exception as fallback_err:
                result = NodeResult(
                    node_id=self.node_id,
                    status=NodeStatus.FAILED,
                    error_code=ErrorCode.EXEC_002,
                    error=f"执行异常: {e}; 降级也失败: {fallback_err}",
                    confidence=0.0,
                )

        # 填充计时
        if result.latency_ms == 0:
            result.latency_ms = timer.elapsed_ms
        result.node_id = result.node_id or self.node_id

        return result

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.node_id} [{self.chain}]>"
