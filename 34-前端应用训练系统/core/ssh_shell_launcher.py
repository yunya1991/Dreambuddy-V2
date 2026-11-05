# -*- coding: utf-8 -*-
"""ssh-stdio launcher（SPEC-DSH-P5 v1.0 §2）。

复用 StdioShell 类（_send/_read_line/_CLOSE_WAIT_S/initialize 握手/call/close
全部与 stdio launcher 完全相同）, 仅差异在 Popen argv:
  stdio: ["python3", "server.py"]
  ssh:   [<ssh_bin>, "-tt", <host>, <remote_cmd>]

假 SSH 本地测: ssh_bin=sys.executable + ssh_host=None → 跳过 SSH,
直接执行 shell_cmd（等价于 stdio launcher, 但走 ssh_launcher 路径）。

真实 SSH: ssh_bin="ssh" + ssh_host="dreambuddy-remote" + remote_cmd=
"cd /home/luke/dreambuddy && /home/luke/venv-trading/bin/python {shell_path}"
"""

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Any, Dict, Optional

from core.stdio_shell_launcher import (
    _REPO_ROOT,
    DEFAULT_CALL_TIMEOUT,
    DEFAULT_HANDSHAKE_TIMEOUT,
    StdioShell,
    StdioShellError,
    StdioShellTimeout,
)


class SshShellError(StdioShellError):
    """ssh-stdio 壳传输层失败（拉起/握手/调用）。"""


class SshShellTimeout(SshShellError, StdioShellTimeout):
    """ssh-stdio 壳超时（握手/调用）。"""


def _build_remote_cmd(spec: Dict[str, Any], remote_python: str = "python3") -> str:
    """构造远程命令: python3 shell_path [shell_cmd args]。"""
    shell_path = spec.get("shell_path") or ""
    shell_cmd = spec.get("shell_cmd") or ""
    # 替换 {path} 占位
    if "{path}" in shell_cmd:
        remote_path = shell_path  # 远程路径相对 repo 根
        shell_cmd = shell_cmd.replace("{path}", remote_path)
    # 移除 "python3 " 前缀（我们已经显式指定远程 python）
    if shell_cmd.startswith("python3 "):
        shell_cmd = shell_cmd[8:]
    elif shell_cmd.startswith("python "):
        shell_cmd = shell_cmd[7:]
    if shell_cmd:
        return f"{remote_python} {shell_cmd}"
    return f"{remote_python} {shell_path}"


def ssh_launcher(
    spec: Dict[str, Any],
    *,
    call_timeout: float = DEFAULT_CALL_TIMEOUT,
    handshake_timeout: float = DEFAULT_HANDSHAKE_TIMEOUT,
    ssh_bin: Optional[str] = None,
    ssh_host: Optional[str] = None,
    remote_python: str = "python3",
) -> StdioShell:
    """按 registry spec 拉起 ssh-stdio 远程壳并完成 initialize 握手。

    假 SSH 模式（本地测）: ssh_bin=sys.executable + ssh_host=None →
      跳过 SSH,直接执行 shell_cmd 等价 stdio launcher。
    真实 SSH: ssh_bin="ssh" + ssh_host="dreambuddy-remote"。

    spec 字段: transport(必须 ssh-stdio)/shell_cmd/shell_path/shell_host。
    ssh_host 优先级: 参数 > spec.shell_host > env DSH_SSH_HOST。
    """
    if not isinstance(spec, dict):
        raise SshShellError("spec must be a dict")
    transport = spec.get("transport", "stdio")
    if transport != "ssh-stdio":
        raise SshShellError("unsupported transport: %r" % transport)

    shell_cmd = spec.get("shell_cmd")
    if not shell_cmd:
        raise SshShellError("spec.shell_cmd missing")

    spec_ssh_host = spec.get("shell_host")
    explicit_ssh_host = ssh_host

    if ssh_bin is None:
        ssh_bin = os.environ.get("DSH_SSH_BIN", "ssh")

    # fake_mode 判定必须在 fallback 之前: 显式传 ssh_host=None 且 ssh_bin != "ssh"
    # → fake_mode=True (跳过 SSH, 直接执行远程命令)
    fake_mode = explicit_ssh_host is None and ssh_bin != "ssh"

    # 只有真实 SSH 模式才需要 ssh_host fallback
    if not fake_mode and ssh_host is None:
        ssh_host = spec_ssh_host or os.environ.get("DSH_SSH_HOST")

    try:
        if fake_mode:
            remote_cmd = _build_remote_cmd(spec, remote_python=remote_python)
            argv = shlex.split(remote_cmd)
        else:
            if not ssh_host:
                raise SshShellError("ssh_host required (param / spec / env DSH_SSH_HOST)")
            remote_cmd = _build_remote_cmd(spec, remote_python=remote_python)
            argv = [ssh_bin, "-tt", "-o", "BatchMode=yes", ssh_host, remote_cmd]
    except ValueError as exc:
        raise SshShellError("bad shell_cmd: %s" % exc) from exc

    env = dict(os.environ)
    env["PYTHONPATH"] = _REPO_ROOT + os.pathsep + env.get("PYTHONPATH", "")

    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=_REPO_ROOT,
            env=env,
        )
    except OSError as exc:
        raise SshShellError("ssh spawn failed: %s" % exc) from exc

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
    "SshShell",
    "SshShellError",
    "SshShellTimeout",
    "ssh_launcher",
]

# SshShell 类 — StdioShell 的别名, 保持类型层级
SshShell = StdioShell
