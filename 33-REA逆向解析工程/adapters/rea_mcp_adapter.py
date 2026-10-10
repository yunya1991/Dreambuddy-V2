"""morluto/rea MCP 适配器 — 通过 MCP 协议调用 REA 的逆向能力。

集成方式：
1. 安装 rea-agents: npm install -g rea-agents
2. 启动 MCP server: rea mcp
3. 通过 MCP client 调用其 133 个工具

设计原则（Evidence-First）：
- 每条结论带 Evidence（provenance + confidence + known_gaps）
- rea 未安装时降级返回 + Evidence(level=unknown)
- 二进制分析结果标注已知局限（stripped/obfuscated/anti-debug）
"""

from __future__ import annotations

import shutil
import subprocess
import json
from typing import Any

from core.evidence import Evidence


class ReaMcpAdapter:
    """REA MCP server 客户端适配器。

    Args:
        mcp_server_cmd: MCP server 启动命令（默认 "rea mcp"）
    """

    def __init__(self, mcp_server_cmd: str = "rea mcp") -> None:
        self._mcp_server_cmd = mcp_server_cmd
        self._client = None  # MCP client（懒加载）
        self._available: bool | None = None  # 缓存 is_available 结果

    def is_available(self) -> bool:
        """检查 REA MCP server 是否可用。

        检查 rea 命令是否存在于 PATH 中。
        结果缓存，首次检查后不再重复。
        """
        if self._available is not None:
            return self._available

        # 检查 rea 命令是否存在
        rea_cmd = self._mcp_server_cmd.split()[0]
        found = shutil.which(rea_cmd) is not None
        self._available = found
        return found

    def analyze_native_binary(
        self, path: str, provider: str = "auto",
    ) -> dict[str, Any]:
        """调用 REA 分析原生二进制。

        Args:
            path: 二进制文件路径
            provider: 分析引擎（auto/ghidra/hopper/radare2）

        Returns:
            {
                "functions": [{name, address, ...}],
                "sections": [".text", ".data", ...],
                "summary": str,
                "evidence": [Evidence],
            }
        """
        evidence: list[Evidence] = []

        # 检查 rea 是否可用
        if not self.is_available():
            evidence.append(Evidence(
                result=(
                    f"REA MCP server 不可用 "
                    f"(command '{self._mcp_server_cmd}' not found)"
                ),
                provenance={
                    "engine": "rea_mcp",
                    "binary": path,
                    "provider": provider,
                },
                confidence=1.0,
                known_gaps=[
                    "REA 未安装，无法进行二进制反编译分析",
                    "建议安装: npm install -g rea-agents",
                    "二进制分析能力缺失，仅能依赖 Python/TS AST 分析",
                ],
                level="unknown",
            ))
            return {
                "functions": [],
                "sections": [],
                "summary": "REA MCP server 不可用，二进制分析跳过",
                "evidence": evidence,
                "available": False,
            }

        # 调用 MCP 工具
        try:
            overview = self._call_mcp("binary_overview", {"path": path, "provider": provider})
            functions = overview.get("functions", [])
            sections = overview.get("sections", [])

            n_funcs = len(functions)
            n_sections = len(sections)

            evidence.append(Evidence(
                result=f"二进制 {path} 包含 {n_funcs} 个函数, {n_sections} 个段",
                provenance={
                    "engine": "rea_mcp",
                    "provider": provider,
                    "binary": path,
                    "tool": "binary_overview",
                },
                confidence=0.9,
                known_gaps=[
                    "stripped 二进制的函数名为地址（如 sub_1000），非源码函数名",
                    "混淆/加密代码的反编译结果可能不准确",
                    "动态计算的跳转目标可能被遗漏",
                    "anti-debug 技术可能干扰分析器输出",
                    "反编译伪代码与源码语义可能不完全等价",
                ],
                level="observation",
            ))

            summary = (
                f"REA 二进制分析: {path} | "
                f"provider={provider} | "
                f"{n_funcs} functions, {n_sections} sections"
            )

            return {
                "functions": functions,
                "sections": sections,
                "summary": summary,
                "evidence": evidence,
                "available": True,
            }

        except Exception as e:
            error_msg = str(e)
            evidence.append(Evidence(
                result=f"REA MCP 调用失败: {error_msg}",
                provenance={
                    "engine": "rea_mcp",
                    "provider": provider,
                    "binary": path,
                    "tool": "binary_overview",
                },
                confidence=1.0,
                known_gaps=[
                    "MCP 通信可能中断（server 进程崩溃）",
                    "provider 可能不支持该二进制架构",
                    "建议检查 rea mcp 是否正常运行",
                ],
                level="unknown",
            ))
            return {
                "functions": [],
                "sections": [],
                "summary": f"REA MCP 调用失败: {error_msg}",
                "evidence": evidence,
                "available": False,
                "error": error_msg,
            }

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _call_mcp(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """调用 REA MCP server 的指定工具。

        生产环境中通过 MCP 协议（JSON-RPC over stdio）与 rea mcp server 通信。
        本方法可被子类覆盖或 mock 以便测试。

        Args:
            tool_name: REA 工具名（如 "binary_overview", "open_binary"）
            params: 工具参数

        Returns:
            工具返回的结构化结果
        """
        # 初始化 MCP client（懒加载）
        if self._client is None:
            self._client = self._init_mcp_client()

        # 通过 MCP 协议调用工具
        # 实际实现需要遵循 MCP JSON-RPC 规范
        # 这里提供基本框架，具体实现依赖 mcp Python SDK
        raise RuntimeError(
            f"MCP client not initialized. "
            f"Tool '{tool_name}' call requires a running MCP server "
            f"('{self._mcp_server_cmd}')."
        )

    def _init_mcp_client(self) -> Any:
        """初始化 MCP client。

        生产环境中使用 mcp Python SDK 连接到 rea mcp server。
        本方法可被子类覆盖或 mock 以便测试。
        """
        # 检查 mcp 包是否安装
        try:
            import mcp  # noqa: F401
        except ImportError:
            raise RuntimeError(
                "mcp Python SDK not installed. "
                "Install with: pip install mcp"
            )

        # TODO: 实际 MCP client 初始化
        # from mcp import ClientSession, StdioServerParameters
        # server_params = StdioServerParameters(
        #     command=self._mcp_server_cmd.split()[0],
        #     args=self._mcp_server_cmd.split()[1:],
        # )
        # return ClientSession(server_params)
        raise RuntimeError("MCP client initialization not yet implemented")
