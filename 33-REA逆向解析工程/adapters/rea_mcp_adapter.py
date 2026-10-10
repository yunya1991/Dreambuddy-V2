"""morluto/rea MCP 适配器 — 通过 MCP 协议调用 REA 的逆向能力。

集成方式：
1. 安装 rea-agents: npm install -g rea-agents
2. 启动 MCP server: rea mcp
3. 通过 MCP client 调用其 133 个工具
"""

from __future__ import annotations


class ReaMcpAdapter:
    """REA MCP server 客户端适配器。"""

    def __init__(self, mcp_server_cmd: str = "rea mcp") -> None:
        self._mcp_server_cmd = mcp_server_cmd
        self._client = None  # MCP client（懒加载）

    def is_available(self) -> bool:
        """检查 REA MCP server 是否可用。"""
        # TODO: 检查 rea 命令是否存在
        return False

    def analyze_native_binary(self, path: str, provider: str = "auto") -> dict:
        """调用 REA 分析原生二进制。"""
        # TODO: 通过 MCP 调用 open_binary + binary_overview
        raise NotImplementedError
