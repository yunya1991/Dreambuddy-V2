"""
Dreambuddy OS — API 适配器

将外部 HTTP API 包装为 Node。

设计:
    - 通过 requests/httpx 调用 API
    - 支持同步和异步
    - 支持超时和重试
    - 将响应转为 NodeResult

P0 阶段: 接口 + 占位实现
P1 阶段: 真正接入 HTTP 客户端
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .base import BaseAdapter
from ..registry.base import BaseNode
from dreamos.shared.state import State, NodeResult, NodeStatus
from dreamos.shared.utils import Timer


class APINode(BaseNode):
    """API 节点 — 包装一个 HTTP API 调用"""

    def __init__(self, node_id: str, url: str, method: str = "GET",
                 headers: Optional[Dict[str, str]] = None,
                 body: Optional[Dict[str, Any]] = None,
                 name: str = "", chain: str = "",
                 timeout_ms: int = 30000,
                 response_path: str = "",
                 **kwargs):
        super().__init__(config=kwargs)
        self.node_id = node_id
        self.name = name or node_id
        self.chain = chain
        self.url = url
        self.method = method.upper()
        self.headers = headers or {}
        self.body = body
        self.timeout_ms = timeout_ms
        self.response_path = response_path  # 从响应 JSON 中取值的路径

    def execute_core(self, state: State) -> NodeResult:
        # P0: 占位实现，P1 接入 httpx
        try:
            # 占位: 用 urllib 做最简实现
            from urllib.request import Request, urlopen
            from urllib.error import URLError

            timer = Timer(self.node_id)
            data = None
            if self.body:
                data = json.dumps(self.body).encode("utf-8")
                self.headers.setdefault("Content-Type", "application/json")

            req = Request(self.url, data=data, headers=self.headers, method=self.method)
            with timer:
                resp = urlopen(req, timeout=self.timeout_ms / 1000)
                body = resp.read().decode("utf-8")
                status_code = resp.getcode()

            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {"raw": body}

            if status_code >= 400:
                return NodeResult(
                    node_id=self.node_id,
                    status=NodeStatus.FAILED,
                    error=f"API 返回错误状态: {status_code}",
                    error_code="EXEC_002",
                    latency_ms=timer.elapsed_ms,
                    outputs={"status": status_code, "body": payload},
                )

            # 从响应中提取置信度/方向（如果有约定）
            confidence = 0.0
            direction = None
            if isinstance(payload, dict):
                confidence = float(payload.get("confidence", 0.0))
                direction = payload.get("direction")

            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.SUCCESS,
                confidence=confidence,
                direction=direction,
                latency_ms=timer.elapsed_ms,
                outputs={"status": status_code, "body": payload},
            )

        except Exception as e:
            return NodeResult(
                node_id=self.node_id,
                status=NodeStatus.FAILED,
                error=f"API 调用异常: {e}",
                error_code="EXEC_002",
                confidence=0.0,
            )


class APIAdapter(BaseAdapter):
    """API 适配器 — 将 HTTP API 包装为 Node

    用法:
        adapter = APIAdapter()
        node = adapter.to_node({
            "type": "api",
            "node_id": "C1_tech_scan",
            "url": "http://127.0.0.1:8092/scan",
            "method": "GET",
            "chain": "C",
        })
    """

    adapter_type = "api"

    def can_handle(self, config: Dict[str, Any]) -> bool:
        return config.get("type") == "api" and "url" in config

    def to_node(self, config: Dict[str, Any]) -> APINode:
        return APINode(
            node_id=config["node_id"],
            url=config["url"],
            method=config.get("method", "GET"),
            headers=config.get("headers"),
            body=config.get("body"),
            name=config.get("name", ""),
            chain=config.get("chain", ""),
            timeout_ms=config.get("timeout_ms", 30000),
            response_path=config.get("response_path", ""),
        )
