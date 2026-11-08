"""mcp_client.py — 最小 stdio MCP 客户端（供 Research Prepass 复用）。

只实现本模块需要的 JSON-RPC 方法：
  initialize → tools/call

设计：
- 每次 collect 拉起一个壳进程，调用完关闭；避免常驻与跨进程状态；
- 读取 stdout 一行作为响应；超时使用线程 + future，超时即杀进程；
- FAIL-OPEN 由调用方决定（本模块抛异常，research 层捕获）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any


class MCPError(RuntimeError):
    pass


class MCPTimeout(MCPError):
    pass


class MCPClient:
    def __init__(
        self,
        server_path: str | Path,
        *,
        python_bin: str | None = None,
        timeout: float = 20.0,
        env: dict[str, str] | None = None,
    ):
        self.server_path = Path(server_path)
        self.python_bin = python_bin or sys.executable
        self.timeout = timeout
        self.env = {
            **os.environ,
            "PYTHONPATH": str(self.server_path.parents[2]),
            **(env or {}),
        }
        self._proc: subprocess.Popen | None = None
        self._next_id = 1

    def __enter__(self) -> "MCPClient":
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._proc is not None:
            return
        if not self.server_path.exists():
            raise MCPError(f"shell not found: {self.server_path}")
        self._proc = subprocess.Popen(
            [self.python_bin, str(self.server_path)],
            cwd=str(self.server_path.parents[2]),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=self.env,
        )
        self._request("initialize", {"clientInfo": {"name": "debate-research"}})

    def _request(self, method: str, params: dict | None = None) -> dict:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise MCPError("client not started")
        req_id = self._next_id
        self._next_id += 1
        req = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            req["params"] = params
        try:
            self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except OSError as exc:
            raise MCPError(f"write failed: {exc}") from exc

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._proc.stdout.readline)
            try:
                line = future.result(timeout=self.timeout)
            except FutureTimeout as exc:
                self.close()
                raise MCPTimeout(f"{method} timeout after {self.timeout}s") from exc
        if not line:
            raise MCPError("empty response (shell exited?)")
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPError(f"invalid JSON-RPC response: {line[:200]}") from exc
        if resp.get("id") != req_id:
            raise MCPError(f"id mismatch: expected {req_id}, got {resp.get('id')}")
        if "error" in resp:
            raise MCPError(str(resp["error"]))
        return resp

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict:
        """调用工具，返回壳信封（content[0].text 解析为 dict）。"""
        resp = self._request(
            "tools/call",
            {"name": tool, "arguments": arguments or {}},
        )
        try:
            text = resp["result"]["content"][0]["text"]
            envelope = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise MCPError(f"invalid envelope for {tool}: {resp}") from exc
        if not isinstance(envelope, dict):
            raise MCPError(f"non-dict envelope for {tool}")
        return envelope

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
