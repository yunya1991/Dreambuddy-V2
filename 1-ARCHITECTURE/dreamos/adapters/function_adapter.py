"""
Dreambuddy OS — 函数适配器

将本地 Python 函数包装为 Node。

适用场景:
    - 快速接入已有工具函数
    - 单元测试 mock
    - 原型开发

用法:
    adapter = FunctionAdapter()

    def my_analysis(state: State) -> dict:
        return {"confidence": 0.8, "direction": "LONG"}

    node = adapter.to_node({
        "type": "function",
        "node_id": "F_custom",
        "name": "自定义分析",
        "chain": "F",
        "handler": my_analysis,
    })
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from .base import BaseAdapter
from ..registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus


class FunctionNode(BaseNode):
    """将函数包装为节点"""

    def __init__(self, handler: Callable[[State], Any],
                 node_id: str, name: str = "", chain: str = "",
                 tags: Optional[list] = None, **kwargs):
        super().__init__(config=kwargs)
        self._handler = handler
        self.node_id = node_id
        self.name = name or node_id
        self.chain = chain
        self.tags = tags or []

    def execute_core(self, state: State) -> NodeResult:
        result = self._handler(state)

        # 支持多种返回格式
        if isinstance(result, NodeResult):
            return result
        if isinstance(result, dict):
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.SUCCESS,
                confidence=float(result.get("confidence", 0.0)),
                direction=result.get("direction"),
                outputs=result.get("outputs", result),
            )
        # 原始值：放进 outputs
        return NodeResult(
            node_id=self.node_id,
            status=NodeStatus.SUCCESS,
            outputs={"value": result},
        )


class FunctionAdapter(BaseAdapter):
    """函数适配器 — 将本地函数转为 Node"""

    adapter_type = "function"

    def can_handle(self, config: Dict[str, Any]) -> bool:
        return config.get("type") == "function" and "handler" in config

    def wrap(self, handler: Callable[[State], Any], **kwargs) -> FunctionNode:
        """便捷包装方法 — 直接传入函数和关键字参数"""
        return FunctionNode(
            handler=handler,
            node_id=kwargs.get("node_id", ""),
            name=kwargs.get("name", ""),
            chain=kwargs.get("chain", ""),
            tags=kwargs.get("tags"),
            **{k: v for k, v in kwargs.items()
               if k not in ("node_id", "name", "chain", "tags")}
        )

    def to_node(self, config: Dict[str, Any]) -> FunctionNode:
        if not self.can_handle(config):
            raise ValueError(f"FunctionAdapter 无法处理配置: {config}")

        return FunctionNode(
            handler=config["handler"],
            node_id=config["node_id"],
            name=config.get("name", ""),
            chain=config.get("chain", ""),
            tags=config.get("tags"),
            **{k: v for k, v in config.items()
               if k not in ("type", "handler", "node_id", "name", "chain", "tags")}
        )
