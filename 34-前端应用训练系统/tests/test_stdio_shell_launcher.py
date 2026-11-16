# -*- coding: utf-8 -*-
"""stdio 真 launcher（core/stdio_shell_launcher.py）测试。

覆盖:
  拉起+initialize 握手 / call 返回解析后统一信封 / 多 call 复用同一进程(ADR-10)
  close 终止进程 / 坏命令拉起即抛 / 超时抛 / 死进程抛 / JSON-RPC error 抛
  处理器级失败(isError)返回 ok=false 信封而不抛(信封语义透传)
  与 ShellHandleManager 集成(真实 launcher 注入,开关开)
"""

import os
import shlex
import sys

import pytest
from core import stdio_shell_launcher as launcher_mod
from core.shell_handles import ShellHandleManager
from core.stdio_shell_launcher import (
    StdioShell,
    StdioShellError,
    StdioShellTimeout,
    stdio_launcher,
)

_FLAGS_ON = {"enable_shell_handles": True}

_FAKE_SERVER = os.path.join("34-前端应用训练系统", "tests", "fixtures", "fake_mcp_server.py")
_PY = shlex.quote(sys.executable)


def _spec(**overrides):
    spec = {
        "shell_id": "fake.mcp",
        "shell_path": _FAKE_SERVER,
        "shell_cmd": "%s {path}" % _PY,
        "transport": "stdio",
        "status": "available",
        "tools": [{"name": "echo_tool"}],
    }
    spec.update(overrides)
    return spec


class TestLaunch:
    def test_launch_and_handshake(self):
        shell = stdio_launcher(_spec())
        try:
            assert isinstance(shell, StdioShell)
            assert shell.pid is not None
            assert shell.is_alive()
        finally:
            shell.close()

    def test_bad_shell_path_raises(self):
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(shell_path="no/such/server.py"))

    def test_missing_cmd_raises(self):
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(shell_cmd=""))

    def test_handshake_failure_raises(self):
        # 进程立刻退出 → 握手读不到响应 → 抛
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(shell_cmd="%s -c pass" % _PY), handshake_timeout=3.0)

    def test_non_stdio_transport_rejected(self):
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(transport="http"))


class TestCall:
    def test_call_returns_parsed_envelope(self):
        shell = stdio_launcher(_spec())
        try:
            env = shell.call("echo_tool", {"k": 1, "s": "中文"})
            assert env["ok"] is True
            assert env["data"]["tool"] == "echo_tool"
            assert env["data"]["args"] == {"k": 1, "s": "中文"}
            assert env["source"] == "fake.mcp"
            assert "error_code" in env  # 信封字段完整透传
        finally:
            shell.close()

    def test_call_with_none_args(self):
        shell = stdio_launcher(_spec())
        try:
            env = shell.call("echo_tool")
            assert env["ok"] is True
            assert env["data"]["args"] == {}
        finally:
            shell.close()

    def test_multiple_calls_reuse_same_process(self):
        shell = stdio_launcher(_spec())
        try:
            pid_before = shell.pid
            shell.call("echo_tool")
            shell.call("echo_tool", {"n": 2})
            assert shell.pid == pid_before  # ADR-10: 单壳复用,不重复拉起
            assert shell.is_alive()
        finally:
            shell.close()

    def test_iserror_envelope_returned_not_raised(self):
        shell = stdio_launcher(_spec())
        try:
            env = shell.call("failing_tool")
            assert env["ok"] is False
            assert env["error_code"] == "unavailable"
            assert env["degraded"] is True
        finally:
            shell.close()

    def test_jsonrpc_error_raises(self):
        shell = stdio_launcher(_spec())
        try:
            with pytest.raises(StdioShellError):
                shell.call("nonexistent_tool")
        finally:
            shell.close()

    def test_call_timeout_raises(self):
        shell = stdio_launcher(_spec(), call_timeout=0.3)
        try:
            with pytest.raises(StdioShellTimeout):
                shell.call("echo_tool", {"__sleep_ms": 2000})
        finally:
            shell.close()

    def test_call_on_dead_process_raises(self):
        shell = stdio_launcher(_spec())
        shell.close()
        with pytest.raises(StdioShellError):
            shell.call("echo_tool")


class TestClose:
    def test_close_terminates_process(self):
        shell = stdio_launcher(_spec())
        pid = shell.pid
        shell.close()
        assert not shell.is_alive()
        # 进程确已退出(非僵尸悬挂)
        with pytest.raises(OSError):
            os.kill(pid, 0)

    def test_close_idempotent(self):
        shell = stdio_launcher(_spec())
        shell.close()
        shell.close()  # 不抛


class TestInterpreterResolution:
    """`python3 {path}` 必须解析到宿主解释器链：COGNITIVE_PYTHON || PYTHON || sys.executable。

    云端 registry 的 shell_cmd 统一写 `python3 {path}`；若按 PATH 命中系统
    /usr/bin/python3，会缺 venv 依赖（fastembed/statsmodels），导致认知壳降级。
    """

    @staticmethod
    def _capture_argv(monkeypatch):
        captured = {}

        def fake_popen(argv, **_kwargs):
            captured["argv"] = list(argv)
            raise OSError("stop-after-capture")

        monkeypatch.setattr(launcher_mod.subprocess, "Popen", fake_popen)
        return captured

    def test_prefers_cognitive_python_over_python(self, monkeypatch):
        captured = self._capture_argv(monkeypatch)
        monkeypatch.setenv("COGNITIVE_PYTHON", "/opt/cognitive/bin/python")
        monkeypatch.setenv("PYTHON", "/opt/other/bin/python")
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(shell_cmd="python3 {path}"))
        assert captured["argv"][0] == "/opt/cognitive/bin/python"

    def test_falls_back_to_python_env(self, monkeypatch):
        captured = self._capture_argv(monkeypatch)
        monkeypatch.delenv("COGNITIVE_PYTHON", raising=False)
        monkeypatch.setenv("PYTHON", "/opt/other/bin/python")
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(shell_cmd="python {path}"))
        assert captured["argv"][0] == "/opt/other/bin/python"

    def test_absolute_interpreter_untouched(self, monkeypatch):
        captured = self._capture_argv(monkeypatch)
        monkeypatch.setenv("COGNITIVE_PYTHON", "/opt/cognitive/bin/python")
        with pytest.raises(StdioShellError):
            stdio_launcher(_spec(shell_cmd="/usr/local/bin/python3.12 {path}"))
        assert captured["argv"][0] == "/usr/local/bin/python3.12"


class TestManagerIntegration:
    def test_manager_with_real_launcher(self, tmp_path):
        reg = tmp_path / "reg.yaml"
        reg.write_text(
            "shells:\n"
            "  - shell_id: fake.mcp\n"
            "    shell_path: %s\n"
            "    shell_cmd: '%s {path}'\n"
            "    transport: stdio\n"
            "    status: available\n"
            "    tools:\n"
            "      - name: echo_tool\n"
            "        requires_mandate: false\n" % (_FAKE_SERVER, _PY),
            encoding="utf-8",
        )
        mgr = ShellHandleManager(registry_path=str(reg), launcher=stdio_launcher, flags=_FLAGS_ON)
        handle = mgr.get_handle("fake.mcp")
        assert handle is not None
        assert handle.call("echo_tool", {"x": 1})["ok"] is True
        # 同 id 复用底层单壳(不重复拉起进程)
        assert mgr.get_handle("fake.mcp").shell is handle.shell
        assert mgr.stats()["fake.mcp"]["handles_issued"] == 2
        mgr.close_all()
        assert not handle.shell.is_alive()

    def test_manager_launcher_failure_still_none(self, tmp_path):
        reg = tmp_path / "reg.yaml"
        reg.write_text(
            "shells:\n"
            "  - shell_id: bad.mcp\n"
            "    shell_path: no/such/server.py\n"
            "    shell_cmd: '%s {path}'\n"
            "    transport: stdio\n"
            "    status: available\n"
            "    tools: []\n" % _PY,
            encoding="utf-8",
        )
        mgr = ShellHandleManager(registry_path=str(reg), launcher=stdio_launcher, flags=_FLAGS_ON)
        assert mgr.get_handle("bad.mcp") is None  # 拉起失败 FAIL-OPEN 隔离
