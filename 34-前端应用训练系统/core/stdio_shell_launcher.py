# -*- coding: utf-8 -*-
"""stdio 真 launcher（P4 收尾：消除 known_gap「stdio 真 launcher 未实现」）。

依据:
  SPEC-L0-MCP-PACKAGING v0.3 §3.1（stdio 按需拉起,1 宿主=1 壳进程）
  + §3.4（PYTHONPATH=<repo root> 由宿主注入,壳内不新增 sys.path hack）
  + §3.5（壳默认继承宿主 env,壳内不改写全局开关）
  + ADR-10/G2（壳实例进程级共享:本 launcher 每调用产出一个壳进程,交由
    ShellHandleManager 按 shell_id 复用,本模块不做复用）
  + B1 FAIL-OPEN 分型（主功能禁 FAIL-OPEN:壳崩溃/超时 ≠ 无结果,传输层
    失败一律抛异常,由宿主兜底打 degraded+error_code）

线协议 = 行分隔 JSON-RPC 2.0（与 mcp_shells/*/server.py main() 实测一致）:
  请求  一行 JSON: {"jsonrpc":"2.0","id":N,"method":"tools/call",
                    "params":{"name":tool,"arguments":{...}}}
  响应  一行 JSON: {"jsonrpc":"2.0","id":N,"result":{"content":[{"type":"text",
                    "text":"<统一信封 JSON 串>"}],"isError":bool}}
                  或 {"jsonrpc":"2.0","id":N,"error":{"code":...,"message":...}}
拉起即 initialize 握手;call() 返回解析后的统一信封 dict（isError=true 时
信封内 ok=false,语义透传不抛）;传输层失败（进程死/超时/坏响应/JSON-RPC
error）抛 StdioShellError。
"""

from __future__ import annotations

import json
import os
import select
import shlex
import subprocess
from typing import Any, Dict, Optional

# core/ → 34-前端应用训练系统/ → repo 根（registry shell_path 相对 repo 根解析）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_CALL_TIMEOUT = 30.0
DEFAULT_HANDSHAKE_TIMEOUT = 10.0
_CLOSE_WAIT_S = 3.0


class StdioShellError(RuntimeError):
    """stdio 壳传输层失败（拉起/握手/调用/关闭语义外的一切传输故障）。"""


class StdioShellTimeout(StdioShellError):
    """调用或握手超时。"""


class StdioShell:
    """一个已拉起并完成 initialize 握手的 stdio 壳子进程。"""

    def __init__(self, proc: "subprocess.Popen[str]", call_timeout: float):
        self._proc = proc
        self._call_timeout = call_timeout
        self._next_id = 0
        self._closed = False

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid

    def is_alive(self) -> bool:
        return not self._closed and self._proc.poll() is None

    # -- 传输原语 -----------------------------------------------------------

    def _send(self, req: Dict[str, Any]) -> None:
        if not self.is_alive():
            raise StdioShellError("shell process not running")
        line = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            assert self._proc.stdin is not None
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as exc:
            raise StdioShellError("stdin write failed: %s" % exc) from exc

    def _read_line(self, timeout: float) -> Dict[str, Any]:
        """读一行响应（POSIX select 超时）。严格请求-响应协议:壳不会主动
        推行,故 text buffer 不会出现「已缓冲未消费」的多余行。"""
        if not self.is_alive():
            raise StdioShellError("shell process not running")
        assert self._proc.stdout is not None
        try:
            ready, _, _ = select.select([self._proc.stdout], [], [], timeout)
        except (OSError, ValueError) as exc:
            raise StdioShellError("select failed: %s" % exc) from exc
        if not ready:
            raise StdioShellTimeout("no response within %.1fs" % timeout)
        try:
            line = self._proc.stdout.readline()
        except (OSError, ValueError) as exc:
            raise StdioShellError("stdout read failed: %s" % exc) from exc
        if not line:
            raise StdioShellError("shell closed stdout (EOF)")
        try:
            resp = json.loads(line)
        except json.JSONDecodeError as exc:
            raise StdioShellError("bad JSON response: %r" % line[:200]) from exc
        if not isinstance(resp, dict):
            raise StdioShellError("response not a JSON object")
        return resp

    # -- 对外 ---------------------------------------------------------------

    def handshake(self, timeout: float) -> None:
        """initialize 握手（launcher 内部调用;失败抛 StdioShellError）。"""
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": self._next_id, "method": "initialize"})
        resp = self._read_line(timeout)
        if "error" in resp:
            raise StdioShellError("initialize rejected: %s" % resp["error"])
        if not isinstance(resp.get("result"), dict):
            raise StdioShellError("initialize: no result in response")

    def call(self, tool: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """tools/call → 解析后的统一信封 dict。

        信封语义透传（isError=true 时信封 ok=false,不抛）;
        仅传输层失败（死进程/超时/坏响应/JSON-RPC error）抛 StdioShellError。
        """
        self._next_id += 1
        req_id = self._next_id
        self._send(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args or {}},
            }
        )
        resp = self._read_line(self._call_timeout)
        if resp.get("id") != req_id:
            raise StdioShellError("response id mismatch: want %s got %s" % (req_id, resp.get("id")))
        if "error" in resp:
            raise StdioShellError("JSON-RPC error: %s" % resp["error"])
        result = resp.get("result") or {}
        content = result.get("content") or []
        text = content[0].get("text") if content and isinstance(content[0], dict) else None
        if text is None:
            raise StdioShellError("empty content in result")
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StdioShellError("bad envelope JSON: %r" % text[:200]) from exc
        if not isinstance(envelope, dict):
            raise StdioShellError("envelope not a JSON object")
        return envelope

    def close(self) -> None:
        """关 stdin（EOF → 壳主循环退出）→ 等待 → 必要时 terminate/kill。幂等。"""
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self._proc.wait(timeout=_CLOSE_WAIT_S)
        except subprocess.TimeoutExpired:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.0)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._proc.kill()
                except OSError:
                    pass


def stdio_launcher(
    spec: Dict[str, Any],
    *,
    call_timeout: float = DEFAULT_CALL_TIMEOUT,
    handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT,
) -> StdioShell:
    """按 registry spec 拉起 stdio 壳子进程并完成 initialize 握手。

    spec 字段: shell_cmd（含 {path} 占位）/ shell_path（相对 repo 根）/
    transport（仅 stdio）。任一步失败抛 StdioShellError（宿主 ShellHandleManager
    捕获后 FAIL-OPEN 为 None）。
    """
    if not isinstance(spec, dict):
        raise StdioShellError("spec must be a dict")
    transport = spec.get("transport", "stdio")
    if transport != "stdio":
        raise StdioShellError("unsupported transport: %r" % transport)
    shell_cmd = spec.get("shell_cmd")
    if not shell_cmd or not isinstance(shell_cmd, str):
        raise StdioShellError("spec.shell_cmd missing")
    if "{path}" in shell_cmd:
        shell_path = spec.get("shell_path")
        if not shell_path or not isinstance(shell_path, str):
            raise StdioShellError("spec.shell_path missing for {path} template")
        abs_path = os.path.normpath(os.path.join(_REPO_ROOT, shell_path))
        if not os.path.isfile(abs_path):
            raise StdioShellError("shell_path not found: %s" % shell_path)
        shell_cmd = shell_cmd.replace("{path}", shlex.quote(abs_path))
    try:
        argv = shlex.split(shell_cmd)
    except ValueError as exc:
        raise StdioShellError("bad shell_cmd: %s" % exc) from exc
    if not argv:
        raise StdioShellError("empty shell_cmd")

    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # 防 stderr 管道淤积死锁;壳日志走自身通道
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=_REPO_ROOT,
            env=env,
        )
    except OSError as exc:
        raise StdioShellError("spawn failed: %s" % exc) from exc

    shell = StdioShell(proc, call_timeout=call_timeout)
    try:
        shell.handshake(handshake_timeout)
    except Exception:
        try:
            proc.kill()
        except OSError:
            pass
        raise
    return shell


__all__ = [
    "StdioShell",
    "StdioShellError",
    "StdioShellTimeout",
    "stdio_launcher",
    "DEFAULT_CALL_TIMEOUT",
    "DEFAULT_HANDSHAKE_TIMEOUT",
]
