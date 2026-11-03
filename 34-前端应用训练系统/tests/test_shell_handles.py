# -*- coding: utf-8 -*-
"""RED: 壳句柄管理器(DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-10 / G2 定稿)。

ADR-10: 宿主=DSH 运行时进程;同一进程内按域共享单壳实例,Worker 会话只持
「工具调用句柄」→ 连接数=聚合后域数,而非 Worker 数。跨进程才各自拉起。
壳内禁止自建连接池(47 SPEC §3.1);本模块是宿主侧唯一壳生命周期载体。

红线: H1 FAIL-OPEN(开关关/注册表缺失/壳拉起失败 → None,不崩)、
H2 开关 enable_shell_handles 默认关。
"""

from __future__ import annotations

from core.shell_handles import ShellHandleManager

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeShell:
    """launcher 返回的壳对象约定: call(tool,args) + close()。"""

    def __init__(self, spec):
        self.spec = spec
        self.closed = False
        self.calls = []

    def call(self, tool, args=None):
        self.calls.append((tool, args))
        return {"ok": True, "data": {"tool": tool}}

    def close(self):
        self.closed = True


class CountingLauncher:
    def __init__(self, fail_on=None):
        self.launched = []
        self.fail_on = fail_on or set()

    def __call__(self, spec):
        sid = spec.get("shell_id")
        if sid in self.fail_on:
            raise RuntimeError("spawn failed: %s" % sid)
        self.launched.append(sid)
        return FakeShell(spec)


ON = {"enable_shell_handles": True}
OFF = {}  # 默认关


# ---------------------------------------------------------------------------
# H2 开关默认关 / H1 FAIL-OPEN
# ---------------------------------------------------------------------------


class TestSwitchAndFailOpen:
    def test_switch_off_returns_none(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=OFF)
        assert mgr.get_handle("l0.data.mcp") is None

    def test_bad_flags_returns_none(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags="bad")
        assert mgr.get_handle("l0.data.mcp") is None
        mgr2 = ShellHandleManager(launcher=CountingLauncher(), flags=None)
        assert mgr2.get_handle("l0.data.mcp") is None

    def test_missing_registry_returns_none(self, tmp_path):
        mgr = ShellHandleManager(
            registry_path=str(tmp_path / "nope.yaml"),
            launcher=CountingLauncher(),
            flags=ON,
        )
        assert mgr.get_handle("l0.data.mcp") is None

    def test_unknown_shell_id_returns_none(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=ON)
        assert mgr.get_handle("no.such.shell") is None

    def test_launcher_failure_returns_none(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(fail_on={"l0.data.mcp"}), flags=ON)
        assert mgr.get_handle("l0.data.mcp") is None


# ---------------------------------------------------------------------------
# ADR-10 核心: 同进程按域共享单壳
# ---------------------------------------------------------------------------


class TestSingleShellPerDomain:
    def test_same_shell_id_launched_once(self):
        launcher = CountingLauncher()
        mgr = ShellHandleManager(launcher=launcher, flags=ON)
        h1 = mgr.get_handle("l0.data.mcp")
        h2 = mgr.get_handle("l0.data.mcp")
        assert h1 is not None and h2 is not None
        assert launcher.launched == ["l0.data.mcp"]  # 只拉起一次

    def test_handles_share_underlying_shell(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=ON)
        h1 = mgr.get_handle("l0.data.mcp")
        h2 = mgr.get_handle("l0.data.mcp")
        # 两个 Worker 句柄指向同一壳实例(连接数=域数,不是 Worker 数)
        assert h1.shell is h2.shell

    def test_distinct_shell_ids_each_launched(self):
        launcher = CountingLauncher()
        mgr = ShellHandleManager(launcher=launcher, flags=ON)
        mgr.get_handle("l0.data.mcp")
        mgr.get_handle("l0.eval.mcp")
        assert sorted(launcher.launched) == ["l0.data.mcp", "l0.eval.mcp"]

    def test_handle_exposes_shell_id_and_spec(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=ON)
        h = mgr.get_handle("l0.data.mcp")
        assert h.shell_id == "l0.data.mcp"
        assert h.spec.get("transport") == "stdio"

    def test_bad_shell_id_type_returns_none(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=ON)
        assert mgr.get_handle(None) is None
        assert mgr.get_handle(123) is None


# ---------------------------------------------------------------------------
# 关闭语义
# ---------------------------------------------------------------------------


class TestClose:
    def test_close_all_closes_each_shell_once(self):
        launcher = CountingLauncher()
        mgr = ShellHandleManager(launcher=launcher, flags=ON)
        h1 = mgr.get_handle("l0.data.mcp")
        h2 = mgr.get_handle("l0.eval.mcp")
        mgr.close_all()
        assert h1.shell.closed is True
        assert h2.shell.closed is True

    def test_close_all_isolates_single_shell_failure(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=ON)
        h1 = mgr.get_handle("l0.data.mcp")
        h2 = mgr.get_handle("l0.eval.mcp")

        def boom():
            raise RuntimeError("close failed")

        h1.shell.close = boom
        mgr.close_all()  # 不抛
        assert h2.shell.closed is True

    def test_handle_after_close_all_relaunches(self):
        launcher = CountingLauncher()
        mgr = ShellHandleManager(launcher=launcher, flags=ON)
        mgr.get_handle("l0.data.mcp")
        mgr.close_all()
        mgr.get_handle("l0.data.mcp")
        assert launcher.launched == ["l0.data.mcp", "l0.data.mcp"]

    def test_stats(self):
        mgr = ShellHandleManager(launcher=CountingLauncher(), flags=ON)
        mgr.get_handle("l0.data.mcp")
        mgr.get_handle("l0.data.mcp")
        s = mgr.stats()
        assert s["l0.data.mcp"]["handles_issued"] == 2
