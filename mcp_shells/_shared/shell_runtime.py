#!/usr/bin/env python3
"""mcp_shells/_shared/shell_runtime.py — 通用壳运行时（P1）

目标：把每个壳里重复的 initialize / tools/list / tools/call / stdio 主循环
收敛到一处，并让 `tools/list` **从 47 registry 派生**（单一事实源），从结构上
消除"注册表一套、代码里手写一套"的漂移。

用法（壳入口）：
    TOOL_DEFS = {
        "data_fetch": {
            "description": "Fetch data context by scope (read-only)",
            "inputSchema": {"type": "object", "properties": {"scope": {"type": "string"}}},
        },
    }
    TOOL_HANDLERS = {"data_fetch": _handle_data_fetch}
    if __name__ == "__main__":
        run_stdio(SHELL_SOURCE, TOOL_DEFS, TOOL_HANDLERS)

契约：
  - registry 中登记但代码无 handler → 启动即报错（结构性缺陷）
  - 代码有 handler 但 registry 未登记 → 不暴露 + stderr WARN（注册表为 SSoT）
  - handler 返回 str（信封 JSON）或 dict；dict 无 `ok` 时自动包信封
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import yaml
except ImportError:  # pragma: no cover - 环境缺依赖时由壳启动失败暴露
    yaml = None  # type: ignore[assignment]

from mcp_shells._shared.envelope_wrap import wrap
from mcp_shells._shared.shadow_hook import observe_envelope

REPO_ROOT = Path(__file__).resolve().parents[2]
REGISTRY_DEFAULT = Path(
    os.environ.get(
        "DREAMBUDDY_MCP_REGISTRY",
        str(REPO_ROOT / "47-MCP管理系统" / "registry" / "mcp_capabilities.yaml"),
    )
)

# MCP 协议版本协商：2024-11-05 的 tools 面在后续版本保持兼容，按客户端
# 请求回显；未知/缺失版本回退到保守默认值。
SUPPORTED_PROTOCOL_VERSIONS = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
    "2025-11-25",
)
DEFAULT_PROTOCOL_VERSION = "2024-11-05"
PROTOCOL_VERSION = DEFAULT_PROTOCOL_VERSION
SERVER_VERSION = "0.3"


def negotiate_protocol_version(requested: Any) -> str:
    """客户端请求版本受支持则回显，否则回退默认版本。"""
    if isinstance(requested, str) and requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return DEFAULT_PROTOCOL_VERSION


class ShellRuntimeError(RuntimeError):
    """壳定义与注册表不一致等结构性错误。"""


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def load_registry_doc(registry_path: Path = REGISTRY_DEFAULT) -> Dict[str, Any]:
    if yaml is None:
        raise ShellRuntimeError("pyyaml 未安装，无法读取 47 registry")
    with open(registry_path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_shell_spec(
    shell_id: str, registry_path: Path = REGISTRY_DEFAULT
) -> Dict[str, Any]:
    doc = load_registry_doc(registry_path)
    for spec in doc.get("shells") or []:
        if isinstance(spec, dict) and spec.get("shell_id") == shell_id:
            return spec
    raise ShellRuntimeError(f"registry 未登记 shell_id: {shell_id}")


def build_tool_list(
    shell_id: str,
    tool_defs: Dict[str, Dict[str, Any]],
    registry_path: Path = REGISTRY_DEFAULT,
) -> List[Dict[str, Any]]:
    """registry 决定工具集合与注解；tool_defs 提供描述与入参 schema。"""
    spec = load_shell_spec(shell_id, registry_path)
    reg_tools = {
        t["name"]: t
        for t in (spec.get("tools") or [])
        if isinstance(t, dict) and t.get("name")
    }

    missing_defs = sorted(set(reg_tools) - set(tool_defs))
    if missing_defs:
        raise ShellRuntimeError(f"{shell_id}: 注册表工具缺少 code 定义: {missing_defs}")

    extra_defs = sorted(set(tool_defs) - set(reg_tools))
    for name in extra_defs:
        print(
            f"[shell_runtime] WARN {shell_id}: 未登记工具不暴露: {name}",
            file=sys.stderr,
        )

    tools: List[Dict[str, Any]] = []
    for name, reg in reg_tools.items():
        definition = tool_defs.get(name) or {}
        tools.append(
            {
                "name": name,
                "description": definition.get("description", ""),
                "inputSchema": definition.get("inputSchema")
                or {"type": "object", "properties": {}},
                "annotations": reg.get("annotations") or {},
            }
        )
    return tools


def _normalize_result(result: Any, shell_id: str) -> Dict[str, Any]:
    """handler 返回值 → 统一信封 dict。"""
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return wrap(result, shell_id)
        if isinstance(parsed, dict):
            return parsed
        return wrap(parsed, shell_id)
    if isinstance(result, dict):
        if "ok" in result:
            return result
        return wrap(result, shell_id)
    return wrap(result, shell_id)


def _envelope_text(envelope: Dict[str, Any]) -> str:
    return json.dumps(envelope, ensure_ascii=False)


def handle_request(
    req: Dict[str, Any],
    *,
    shell_id: str,
    tools: List[Dict[str, Any]],
    handlers: Dict[str, Callable[[Dict[str, Any]], Any]],
    server_name: Optional[str] = None,
    protocol_version: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """处理一条 JSON-RPC 请求；通知类返回 None（不写响应）。"""
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        params = req.get("params") or {}
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        version = protocol_version or negotiate_protocol_version(requested)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": server_name or shell_id,
                    "version": SERVER_VERSION,
                },
            },
        }

    if method == "notifications/initialized":
        return None

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name", "")
        handler = handlers.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        started = time.perf_counter()
        try:
            envelope = _normalize_result(handler(params.get("arguments") or {}), shell_id)
        except Exception as exc:  # 壳内兜底：主功能不可 FAIL-OPEN 伪装无结果
            envelope = wrap(
                None,
                shell_id,
                degraded=True,
                error_code="unavailable",
                meta={"reason": str(exc)},
            )
        result_text = _envelope_text(envelope)
        observe_envelope(
            result_text,
            latency_ms=round((time.perf_counter() - started) * 1000.0, 3),
            action=name,
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result_text}],
                "isError": not bool(envelope.get("ok", False)),
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def run_stdio(
    shell_id: str,
    tool_defs: Dict[str, Dict[str, Any]],
    handlers: Dict[str, Callable[[Dict[str, Any]], Any]],
    *,
    registry_path: Path = REGISTRY_DEFAULT,
    server_name: Optional[str] = None,
    protocol_version: Optional[str] = None,
) -> None:
    """启动 stdio JSON-RPC 主循环（阻塞至 stdin EOF）。"""
    _configure_stdio()
    tools = build_tool_list(shell_id, tool_defs, registry_path)

    missing_handlers = [t["name"] for t in tools if t["name"] not in handlers]
    if missing_handlers:
        raise ShellRuntimeError(f"{shell_id}: 注册表工具缺少 handler: {missing_handlers}")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            )
            continue
        if not isinstance(req, dict):
            _write(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32600, "message": "Invalid Request"},
                }
            )
            continue
        resp = handle_request(
            req,
            shell_id=shell_id,
            tools=tools,
            handlers=handlers,
            server_name=server_name,
            protocol_version=protocol_version,
        )
        if resp is not None:
            _write(resp)


def _write(resp: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
    sys.stdout.flush()


__all__ = [
    "ShellRuntimeError",
    "build_tool_list",
    "handle_request",
    "load_shell_spec",
    "run_stdio",
]