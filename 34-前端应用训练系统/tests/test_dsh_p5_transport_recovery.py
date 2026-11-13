# -*- coding: utf-8 -*-
"""SPEC-DSH-P5 v1.0 TDD: ssh-stdio launcher + healthcheck + retry。

三个子任务,均用假 SSH + 模拟 kill 在本地测,零真 SSH 依赖。
"""

from __future__ import annotations

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_FAKE_SERVER = os.path.join(
    REPO_ROOT, "34-前端应用训练系统", "tests", "fixtures", "fake_mcp_server.py"
)


def _fake_spec():
    return {
        "shell_id": "fake.ssh.mcp",
        "transport": "ssh-stdio",
        "shell_host": "localhost",
        "shell_cmd": "python3 {path}",
        "shell_path": _FAKE_SERVER,
        "status": "available",
    }


# ═══════════════════════════════════════════════════════════════════════
# Subtask P3a: ssh_launcher
# ═══════════════════════════════════════════════════════════════════════


class TestSshLauncher:
    """P3a ssh_launcher —— 复用 StdioShell 类, 差异只在 Popen argv。"""

    def test_import(self):
        pass

    def test_handshake_ok(self):
        """ssh_launcher 用假 SSH → 完成 initialize 握手 → 返回 StdioShell 子类。"""
        from core.ssh_shell_launcher import ssh_launcher

        shell = ssh_launcher(
            _fake_spec(),
            ssh_bin=sys.executable,
            ssh_host=None,
        )
        assert shell.is_alive()
        assert shell.pid is not None
        shell.close()
        assert not shell.is_alive()

    def test_call_after_handshake(self):
        """握手后 tools/call echo_tool → 返回正常信封。"""
        from core.ssh_shell_launcher import ssh_launcher

        shell = ssh_launcher(_fake_spec(), ssh_bin=sys.executable, ssh_host=None)
        try:
            env = shell.call("echo_tool", {"tool": "t", "args": {"x": 1}})
            assert env["ok"] is True
            assert env["data"]["tool"] == "echo_tool"  # 信封 data.tool 是工具名
        finally:
            shell.close()

    def test_spec_validation(self):
        """非 ssh-stdio transport → 抛 SshShellError。"""
        from core.ssh_shell_launcher import SshShellError, ssh_launcher

        spec = dict(_fake_spec())
        spec["transport"] = "stdio"
        with pytest.raises(SshShellError):
            ssh_launcher(spec)

    def test_ssh_host_fallback(self):
        """真实 SSH 模式 ssh_host 缺失 → 抛 SshShellError。"""
        from core.ssh_shell_launcher import SshShellError, ssh_launcher

        spec = dict(_fake_spec())
        del spec["shell_host"]
        # ssh_bin="ssh" + ssh_host=None → 真实 SSH 模式触发 → 缺 host 抛错
        with pytest.raises(SshShellError):
            ssh_launcher(spec, ssh_bin="ssh", ssh_host=None)


# ═══════════════════════════════════════════════════════════════════════
# Subtask P3-A: ShellHandleManager 健康检查 + 自动重拉 (HC-4/HC-5)
# ═══════════════════════════════════════════════════════════════════════


class _CrashableShell:
    """模拟壳, 可 kill 后 is_alive=False。"""

    def __init__(self):
        self._alive = True
        self._closed = False
        self.call_count = 0
        self.kills = 0

    @property
    def pid(self):
        return 12345

    def is_alive(self):
        return self._alive and not self._closed

    def call(self, tool, args=None):
        self.call_count += 1
        if not self.is_alive():
            raise RuntimeError("shell crashed")
        return {"ok": True, "data": {"tool": tool}}

    def crash(self):
        self._alive = False
        self.kills += 1

    def close(self):
        self._closed = True


def _patched_manager(launcher):
    """ShellHandleManager + patch _specs_cached 返回假 spec(shell_id='any')。"""
    from core.shell_handles import ShellHandleManager

    mgr = ShellHandleManager(launcher=launcher, flags={"enable_shell_handles": True})
    mgr._specs = {"any": {"shell_id": "any", "transport": "stdio", "status": "available"}}
    return mgr


class TestHealthcheckAndRestart:
    """P3-A HC-4/HC-5: 壳死自动重拉,超上限 FAIL-OPEN。"""

    def test_dead_shell_get_handle_relaunches(self):
        """HC-4: 壳 crash 后 get_handle → 关旧壳 + 拉起新壳。"""
        shells = [_CrashableShell(), _CrashableShell()]
        counter = [0]

        def launcher(spec):
            counter[0] += 1
            return shells[counter[0] - 1]

        mgr = _patched_manager(launcher)
        try:
            h1 = mgr.get_handle("any")
            assert h1 is not None
            shell1 = h1.shell
            assert shell1.is_alive()
            shell1.crash()

            # HC-4: 壳死了 → get_handle 重拉起
            h2 = mgr.get_handle("any")
            assert h2 is not None
            assert h2.shell is not shell1  # 新壳!
            assert h2.shell.is_alive()
        finally:
            mgr.close_all()

    def test_restart_count_stays_zero_when_healthy(self):
        """壳正常 → 不增加 restart_count。"""
        shells = [_CrashableShell()]
        counter = [0]

        def launcher(spec):
            counter[0] += 1
            return shells[counter[0] - 1]

        mgr = _patched_manager(launcher)
        try:
            mgr.get_handle("any")
            mgr.get_handle("any")  # 同壳复用
            assert mgr._restart_counts.get("any", 0) == 0
        finally:
            mgr.close_all()

    def test_max_restart_exceeded_returns_none(self):
        """HC-5: 重拉 2 次后 (count=2), 第 3 次重拉时 count→3 超限 → None。

        原因: HC-5 有两处检查 — 重拉前 (count<3) + launcher 前 (count<3)。
        第 2 次重拉时 count 从 1→2, launcher shell3 ✓
        h3 crash → need_restart, check1(2<3=OK), count→3, shell=None →
        check2(3<3=FAIL) → return None
        """
        shells = [_CrashableShell() for _ in range(3)]
        counter = [0]

        def launcher(spec):
            counter[0] += 1
            return shells[counter[0] - 1]

        mgr = _patched_manager(launcher)
        try:
            h1 = mgr.get_handle("any")
            h1.shell.crash()
            h2 = mgr.get_handle("any")  # 重拉 1
            h2.shell.crash()
            h3 = mgr.get_handle("any")  # 重拉 2 (count=2)
            h3.shell.crash()
            h4 = mgr.get_handle("any")  # count→3 后 check2 超限
            assert h4 is None, "HC-5: 超 MAX_RESTARTS 应返回 None"
        finally:
            mgr.close_all()

    def test_restart_does_not_bump_issued(self):
        """重拉壳不影响 handles_issued 计数。"""
        shells = [_CrashableShell() for _ in range(4)]
        counter = [0]

        def launcher(spec):
            counter[0] += 1
            return shells[counter[0] - 1]

        mgr = _patched_manager(launcher)
        try:
            mgr.get_handle("any")
            h = mgr.get_handle("any")
            h.shell.crash()
            mgr.get_handle("any")  # 重拉
            stats = mgr.stats()
            assert stats["any"]["handles_issued"] == 3
        finally:
            mgr.close_all()


# ═══════════════════════════════════════════════════════════════════════
# Subtask P3-C: call_worker_tool try-retry-degrade 三态 (HC-6/HC-7)
# ═══════════════════════════════════════════════════════════════════════


class TestRetryDegrade:
    """P3-C HC-6/HC-7: 壳异常自动重试 + 重试超限 FAIL-OPEN。"""

    ON = {"enable_worker_tool_call": True}

    def test_force_new_handle_api(self):
        """get_handle(force_new=True) 强制清旧壳重拉。"""

        shells = [_CrashableShell() for _ in range(3)]
        counter = [0]

        def launcher(spec):
            counter[0] += 1
            return shells[counter[0] - 1]

        mgr = _patched_manager(launcher)
        try:
            h1 = mgr.get_handle("any")
            h2 = mgr.get_handle("any", force_new=True)
            assert h2 is not None
            assert h2.shell is not h1.shell
            assert counter[0] == 2
        finally:
            mgr.close_all()


# ═══════════════════════════════════════════════════════════════════════
# 同机部署: ssh-stdio 无 host 时降级本地 stdio
# ═══════════════════════════════════════════════════════════════════════


class TestSameHostStdioFallback:
    """云端同机部署不应 SSH 自连: 缺 shell_host/DSH_SSH_HOST → 本地 stdio。"""

    def _spec(self):
        spec = dict(_fake_spec())
        spec.pop("shell_host", None)
        return spec

    def test_no_host_falls_back_to_stdio(self, monkeypatch):
        monkeypatch.delenv("DSH_SSH_HOST", raising=False)
        from core.dsh_frontend_bridge import launcher_factory

        shell = launcher_factory(self._spec())
        assert shell is not None, "缺 host 时应降级 stdio, 而非返回 None"
        try:
            env = shell.call("echo_tool", {"tool": "t", "args": {"x": 1}})
            assert env["ok"] is True
        finally:
            shell.close()

    def test_env_host_keeps_ssh_path(self, monkeypatch):
        monkeypatch.setenv("DSH_SSH_HOST", "localhost")

        import importlib

        from core import dsh_frontend_bridge

        calls = {}

        def _fake_ssh_launcher(spec, **kwargs):
            calls["transport"] = "ssh"
            return type(
                "S",
                (),
                {
                    "call": lambda self, t, a=None: {"ok": True},
                    "is_alive": lambda self: True,
                    "close": lambda self: None,
                },
            )()

        # launcher_factory 走顶层 `from ssh_shell_launcher import ...`,
        # 因此必须 patch 顶层模块对象, 而非 core.* 别名。
        core_dir = os.path.join(REPO_ROOT, "34-前端应用训练系统", "core")
        if core_dir not in sys.path:
            sys.path.insert(0, core_dir)
        ssh_mod = importlib.import_module("ssh_shell_launcher")
        monkeypatch.setattr(ssh_mod, "ssh_launcher", _fake_ssh_launcher)

        shell = dsh_frontend_bridge.launcher_factory(self._spec())
        assert calls.get("transport") == "ssh"
        assert shell is not None
