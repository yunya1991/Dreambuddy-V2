#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4 — 辩论壳（agent.debate.mcp）stdio JSON-RPC 客户端。

复用 `bridge/distill_bridge.py` 的 stdio 客户端写法（精简复制，避免跨目录 import 耦合），
工具白名单仅 start_debate / get_debate_result（本编排器不调 debate_health）。

边界：只发起/读取辩论 job，不执行 DreamOS 执行链；shadow 模式下仅记录 debate_id。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
REPO_ROOT = ORCHESTRATOR_DIR.parents[1]
DEFAULT_SHELL_PATH = REPO_ROOT / "mcp_shells" / "debate_adversarial" / "server.py"

PROTOCOL_VERSION = "2024-11-05"
REQUEST_TIMEOUT_SEC = 60
ALLOWED_TOOLS = frozenset({"start_debate", "get_debate_result"})


class DebateTransportError(Exception):
    """stdio 链路错误（调用方降级为 debate.error）。"""


class StdioShellClient:
    """通用 stdio MCP 壳客户端（懒启动，initialize → notifications/initialized → tools/call）。

    默认按辩论壳配置（见 `DebateClient` 别名）；传入 `allowed_tools` 可复用为
    cognition 壳的只读 recall 客户端。
    """

    def __init__(
        self,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        allowed_tools: frozenset[str] | set[str] | None = None,
        client_name: str = "brainstorm-orchestrator",
    ) -> None:
        self._command = command or os.environ.get("DEBATE_SHELL_CMD") or sys.executable
        self._args = (
            list(args)
            if args is not None
            else [str(Path(os.environ.get("DEBATE_SHELL_PATH", DEFAULT_SHELL_PATH)))]
        )
        merged = {
            "PYTHONPATH": str(REPO_ROOT),
            "PYTHONIOENCODING": "utf-8",
        }
        if env:
            merged.update(env)
        self._env = merged
        self._allowed_tools = frozenset(allowed_tools or ALLOWED_TOOLS)
        self._client_name = client_name
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 1

    def _ensure_started(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        full_env = dict(os.environ)
        full_env.update(self._env)
        self._proc = subprocess.Popen(
            [self._command, *self._args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            env=full_env,
        )
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": "0.1.0"},
            },
        )
        if not isinstance(result, dict) or not result.get("serverInfo", {}).get("name"):
            raise DebateTransportError("mcp_initialize_invalid_response")
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def _read_response(self, rid: int) -> dict[str, Any]:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            line = self._proc.stdout.readline()
            if not line:
                raise DebateTransportError("mcp_process_eof")
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != rid:
                continue
            if message.get("error"):
                raise DebateTransportError(f"mcp_rpc_error:{message['error'].get('message')}")
            return message.get("result") or {}

    def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        rid = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "method": method}
        if params is not None:
            payload["params"] = params
        self._send(payload)
        return self._read_response(rid)

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name in self._allowed_tools, f"tool_not_allowed:{name!r}"
        self._ensure_started()
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            text = "".join(
                c.get("text", "") for c in result.get("content", []) if isinstance(c, dict)
            )
            raise DebateTransportError(f"mcp_tool_error:{text[:200]}")
        return _unwrap_envelope(result)

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:  # noqa: BLE001 — 关闭失败不影响主流程
                proc.kill()

    def __enter__(self) -> "DebateClient":
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()


def _unwrap_envelope(result: dict[str, Any]) -> dict[str, Any]:
    """MCP tools/call result → L0 信封 dict（content[0].text 为 JSON 字符串）。"""
    for item in result.get("content", []):
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                parsed = json.loads(item.get("text") or "{}")
            except json.JSONDecodeError as exc:
                raise DebateTransportError(f"envelope_not_json:{exc}") from exc
            if isinstance(parsed, dict):
                return parsed
    raise DebateTransportError("envelope_missing")


def start_debate(
    client: StdioShellClient,
    topic: str,
    background: str,
    model_pair: list[str],
    plancards: list[dict[str, Any]],
    rounds: int = 1,
) -> str:
    """发起辩论 → debate_id。envelope.ok=false 时抛 DebateTransportError。"""
    arguments: dict[str, Any] = {
        "topic": topic,
        "background": background,
        "rounds": rounds,
        "mode": "review",
        "model_pair": list(model_pair),
        "plancards": list(plancards),
    }
    envelope = client.call_tool("start_debate", arguments)
    if not envelope.get("ok"):
        raise DebateTransportError(
            f"start_debate_rejected:{envelope.get('error_code')}:"
            f"{(envelope.get('meta') or {}).get('reason')}"
        )
    debate_id = (envelope.get("data") or {}).get("debate_id")
    if not debate_id:
        raise DebateTransportError("start_debate_no_debate_id")
    return str(debate_id)


def get_debate_result(client: StdioShellClient, debate_id: str) -> dict[str, Any]:
    """读取辩论 job 状态（只读）。"""
    return client.call_tool("get_debate_result", {"debate_id": debate_id})


# 语义别名：辩论壳专用客户端
DebateClient = StdioShellClient
