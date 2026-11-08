"""debate_mcp_client.py — C-Drive 侧 `agent.debate.mcp` 最小 stdio 客户端。

用途：
  - C-Drive 在 `DEBATE_MCP_ENABLED=true` 时经 MCP 壳做 Bull/Bear 辩论；
  - 壳以子进程 stdio JSON-RPC 拉起，异步 job 模式（start_debate → 轮询）；
  - 失败由调用方回退到本地 v1/v2 引擎（FAIL-OPEN）。

边界：
  - 只读/计算；不产生交易、不写外部状态；
  - 不常驻；一次辩论一个子进程，结束即关闭。
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


class DebateMCPError(RuntimeError):
    """MCP 壳调用失败。"""


_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_SERVER = _REPO_ROOT / "mcp_shells" / "debate_adversarial" / "server.py"


class DebateMCPClient:
    """最小 MCP stdio 客户端：initialize → start_debate → 轮询 get_debate_result。"""

    def __init__(
        self,
        server_path: str | Path | None = None,
        *,
        python_bin: str | None = None,
        timeout: float | None = None,
    ):
        self.server_path = Path(
            server_path
            or os.environ.get("DEBATE_MCP_SERVER_PATH")
            or _DEFAULT_SERVER
        )
        self.python_bin = python_bin or sys.executable
        self.timeout = float(
            timeout
            if timeout is not None
            else os.environ.get("DEBATE_MCP_TIMEOUT_SEC", "60")
        )
        self._proc: subprocess.Popen | None = None
        self._next_id = 1

    def __enter__(self) -> "DebateMCPClient":
        self.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def start(self) -> None:
        if self._proc is not None:
            return
        if not self.server_path.exists():
            raise DebateMCPError(f"debate shell not found: {self.server_path}")
        env = {
            **os.environ,
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(_REPO_ROOT),
        }
        self._proc = subprocess.Popen(
            [self.python_bin, str(self.server_path)],
            cwd=str(_REPO_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        self._request("initialize", {"clientInfo": {"name": "cdrive"}})

    def _request(self, method: str, params: dict | None = None) -> dict:
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            raise DebateMCPError("client not started")
        req_id = self._next_id
        self._next_id += 1
        req: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            req["params"] = params
        try:
            self._proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except OSError as exc:
            raise DebateMCPError(f"write failed: {exc}") from exc

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._proc.stdout.readline)
            try:
                line = future.result(timeout=self.timeout)
            except FutureTimeout as exc:
                self.close()
                raise DebateMCPError(
                    f"{method} timeout after {self.timeout}s"
                ) from exc
        if not line:
            raise DebateMCPError("empty response (shell exited?)")
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DebateMCPError(f"invalid JSON-RPC response: {line[:200]}") from exc
        if resp.get("id") != req_id:
            raise DebateMCPError(
                f"id mismatch: expected {req_id}, got {resp.get('id')}"
            )
        if "error" in resp:
            raise DebateMCPError(str(resp["error"]))
        return resp

    def call(self, tool: str, arguments: dict[str, Any] | None = None) -> dict:
        resp = self._request(
            "tools/call",
            {"name": tool, "arguments": arguments or {}},
        )
        try:
            text = resp["result"]["content"][0]["text"]
            envelope = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise DebateMCPError(f"invalid envelope for {tool}: {resp}") from exc
        if not isinstance(envelope, dict):
            raise DebateMCPError(f"non-dict envelope for {tool}")
        return envelope

    def run(
        self,
        topic: str,
        mode: str = "fast",
        background: str = "",
        *,
        rounds: int | None = None,
        research: bool = False,
        research_sources: list[str] | None = None,
        adjudication: bool = True,
        profile: str = "signal",
    ) -> dict:
        """启动并等待一场辩论，返回 DebateResult v1。"""
        self.start()
        args: dict[str, Any] = {
            "topic": topic,
            "mode": mode,
            "background": background,
            "research": research,
            "adjudication": adjudication,
            "profile": profile,
        }
        if rounds is not None:
            args["rounds"] = rounds
        if research_sources is not None:
            args["research_sources"] = research_sources

        started = self.call("start_debate", args)
        if not started.get("ok", False):
            raise DebateMCPError(
                f"start_debate failed: {started.get('error_code')} "
                f"{started.get('meta', {}).get('reason', '')}"
            )
        debate_id = (started.get("data") or {}).get("debate_id")
        if not debate_id:
            raise DebateMCPError("start_debate returned no debate_id")

        deadline = time.monotonic() + self.timeout
        last_status = "queued"
        while time.monotonic() < deadline:
            job_env = self.call("get_debate_result", {"debate_id": debate_id})
            if not job_env.get("ok", False):
                raise DebateMCPError(
                    f"get_debate_result failed: {job_env.get('error_code')}"
                )
            job = job_env.get("data") or {}
            status = str(job.get("status", ""))
            last_status = status
            if status == "completed":
                result = job.get("result")
                if not isinstance(result, dict):
                    raise DebateMCPError("completed job has no result")
                return result
            if status == "error":
                raise DebateMCPError(f"debate job error: {job.get('error')}")
            time.sleep(0.2)

        raise DebateMCPError(
            f"debate timeout after {self.timeout}s (last_status={last_status})"
        )

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