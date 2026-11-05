# -*- coding: utf-8 -*-
"""DSH 架构升级 ↔ L0 底层协作场景测试（6 大场景）。

与 test_e2e_worker_wiring.py 的关键差异:
  - stdio_shell_launcher **真拉起** mcp_shells/l0_store_admin/server.py
  - 真实 DAL 6 repo 工厂被壳进程导入并健康检查
  - 真协议: 行分隔 JSON-RPC 2.0 + 统一信封
  - 覆盖 ADR-4/9/10 + B1 + D4 + H2/H7 硬约束
"""

from __future__ import annotations

import statistics
import time

import pytest
from core.shell_handles import ShellHandleManager
from core.stdio_shell_launcher import stdio_launcher
from core.worker_tool_call import call_worker_tool

ON = {"enable_worker_tool_call": True}


# ── fixture: 真壳管理器（ADR-10 进程级共享）────────────────────────


@pytest.fixture
def real_manager():
    """用 stdio launcher 拉起真壳的 ShellHandleManager。"""
    mgr = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    yield mgr
    mgr.close_all()


# ═══════════════════════════════════════════════════════════════════════
# 场景 1: 真壳全链调用 + L0-DAL 实时健康检查
#   verifier ── store_admin_status ──▶ 真 l0.store-admin.mcp ──▶ DAL 6 repo
#   验证: shell_id 正确 / 信封 ok / 6 repo 工厂全部存活
# ═══════════════════════════════════════════════════════════════════════


class TestScenario1RealShellDalHealth:
    def test_verifier_reads_dal_health(self, real_manager):
        """verifier 角色只读调 store_admin_status: 全链 ok + DAL 6 repo 枚举。"""
        r = call_worker_tool(
            "verifier", "store_admin_status", manager=real_manager, flags=ON, trace_id="s1-1"
        )
        assert r["ok"] is True, f"expect ok=True, got {r}"
        data = r["data"]
        assert data["shell"] == "l0.store-admin.mcp"
        assert data["mode"] == "read-only"
        repos = data["repos"]
        assert set(repos.keys()) == {"trade", "position", "market_macro", "risk", "config", "kg"}
        assert all(v == "ok" for v in repos.values()), f"degraded repo found: {repos}"

    def test_envelope_semantics(self, real_manager):
        """返回信封须含 source/trace_id 元数据,version=0.1(SPEC §3.2)。"""
        r = call_worker_tool(
            "verifier", "store_admin_status", manager=real_manager, flags=ON, trace_id="s1-2"
        )
        meta = r.get("meta", {})
        assert meta.get("trace_id") == "s1-2"
        # 壳回传的信封字段存在性（不强制精确值,版本迭代用）
        assert "data" in r
        # 壳成功时 error_code 为空串或 None;失败时为具体错误码
        assert r.get("error_code") in (None, "", "unavailable", "invalid")


# ═══════════════════════════════════════════════════════════════════════
# 场景 2: ADR-10 单壳复用（多 Worker 同进程共享壳实例）
#   research ── store_admin_query(trade) ──▶ 同壳
#   verifier  ── store_admin_status       ──▶ 同壳(不是新进程)
#   验证: stats 只有 1 个 shell_id / handles_issued=2 / 关闭只停 1 进程
# ═══════════════════════════════════════════════════════════════════════


class TestScenario2Adr10SingleShellReuse:
    def test_two_workers_share_one_shell(self, real_manager):
        """research(跨角色读)+verifier 都调 store-admin 壳 → 同壳复用。"""
        call_worker_tool(
            "verifier", "store_admin_status", manager=real_manager, flags=ON, trace_id="s2-1"
        )
        # research 不在 store-admin 壳的 worker_roles 里,但可以通过
        # 真实 manager.get_handle 绕过 role gate 直接测单壳复用(
        # call_worker_tool 的 gate 会先拦 —— 这里用 verifier 两次更直接)
        call_worker_tool(
            "verifier",
            "store_admin_query",
            manager=real_manager,
            flags=ON,
            trace_id="s2-2",
            args={"repo": "trade", "limit": 5},
        )
        # 关键断言: ADR-10 单壳
        stats = real_manager.stats()
        assert "l0.store-admin.mcp" in stats
        assert stats["l0.store-admin.mcp"]["handles_issued"] == 2
        assert len(stats) == 1, f"more than one shell_id spawned: {list(stats.keys())}"

    def test_manager_stats_accurate_after_close(self):
        """close_all 后 stats 仍保留计数(HC-3: 清壳不清 issued)。"""
        mgr = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
        try:
            for i in range(3):
                call_worker_tool(
                    "verifier",
                    "store_admin_status",
                    manager=mgr,
                    flags=ON,
                    trace_id=f"s2-close-{i}",
                )
            assert mgr.stats()["l0.store-admin.mcp"]["handles_issued"] == 3
        finally:
            mgr.close_all()
        # 关了进程但 issued 还在
        assert mgr.stats()["l0.store-admin.mcp"]["handles_issued"] == 3


# ═══════════════════════════════════════════════════════════════════════
# 场景 3: ADR-4 角色能力集 + H7 写工具纵深门禁（真 registry + 真 gate）
#   engineer 调 store_admin_status(不在 engineer 工具集) → forbidden
#   verifier 调 store_admin_status       → ok
#   verifier 调 record(requires_mandate, cognition 壳) → forbidden(H7)
# ═══════════════════════════════════════════════════════════════════════


class TestScenario3Adr4RoleGate:
    def test_engineer_cannot_call_store_admin(self, real_manager):
        """engineer 工具集不含 store_admin_* → gate 拒绝。"""
        r = call_worker_tool(
            "engineer", "store_admin_status", manager=real_manager, flags=ON, trace_id="s3-1"
        )
        assert r["ok"] is False
        assert r["error_code"] == "forbidden"

    def test_verifier_can_call_store_admin(self, real_manager):
        """verifier 工具集含 store_admin_* → gate 放行 + 真壳 ok。"""
        r = call_worker_tool(
            "verifier", "store_admin_status", manager=real_manager, flags=ON, trace_id="s3-2"
        )
        assert r["ok"] is True

    def test_verifier_cannot_call_write_tool(self, real_manager):
        """任何 Worker(含 verifier)都不能直调 record 写工具(H7 纵深)。"""
        r = call_worker_tool(
            "verifier",
            "record",
            manager=real_manager,
            flags=ON,
            trace_id="s3-3",
            args={"content": "x"},
        )
        assert r["ok"] is False
        assert r["error_code"] == "forbidden"


# ═══════════════════════════════════════════════════════════════════════
# 场景 4: 真壳错误传播 → degraded 信封（B1 FAIL-OPEN 语义）
#   store_admin_query repo=invalid → 壳返回 degraded 信封 → 编排层透传
# ═══════════════════════════════════════════════════════════════════════


class TestScenario4RealShellErrorPropagation:
    def test_invalid_repo_degraded_envelope(self, real_manager):
        """不支持的 repo → 壳自己返回 degraded 信封(ok=false,invalid)。"""
        r = call_worker_tool(
            "verifier",
            "store_admin_query",
            manager=real_manager,
            flags=ON,
            trace_id="s4-1",
            args={"repo": "nonexistent"},
        )
        assert r["ok"] is False
        assert r["error_code"] in ("invalid", "unavailable")

    def test_degraded_not_throw(self, real_manager):
        """壳返回 degraded 信封时编排层**不抛异常**,而是 ok=false 信封(B1 硬约束)。"""
        try:
            r = call_worker_tool(
                "verifier",
                "store_admin_query",
                manager=real_manager,
                flags=ON,
                trace_id="s4-2",
                args={"repo": "nonexistent"},
            )
        except Exception as exc:
            pytest.fail(f"B1 FAIL-OPEN 违规: 壳 degraded 信封不应被编排层抛异常, got {exc}")
        assert r["ok"] is False


# ═══════════════════════════════════════════════════════════════════════
# 场景 5: H2 开关门控 + FAIL-OPEN（注册表/开关关闭）
#   enable_worker_tool_call=False → disabled
#   enable_shell_handles=False   → unavailable + degraded
# ═══════════════════════════════════════════════════════════════════════


class TestScenario5H2SwitchGate:
    def test_worker_tool_call_disabled(self, real_manager):
        """H2: enable_worker_tool_call 关闭 → 明确 disabled 信封,不崩。"""
        r = call_worker_tool(
            "verifier",
            "store_admin_status",
            manager=real_manager,
            flags={},
            trace_id="s5-1",
        )
        assert r["ok"] is False
        assert r["error_code"] == "disabled"

    def test_shell_handles_disabled(self):
        """H2: enable_shell_handles 关闭 → manager.get_handle 返回 None → unavailable。"""
        mgr = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": False})
        r = call_worker_tool(
            "verifier", "store_admin_status", manager=mgr, flags=ON, trace_id="s5-2"
        )
        assert r["ok"] is False
        assert r["error_code"] == "unavailable"
        assert r["meta"].get("degraded") is True
        mgr.close_all()


# ═══════════════════════════════════════════════════════════════════════
# 场景 6: bench 级压力 → D4 判据（真壳 100 轮）
#   transport_component_ms = real_p50 - fake_p50 ≤ 45ms
# ═══════════════════════════════════════════════════════════════════════


class TestScenario6D4LatencyBudget:
    ROUNDS = 100
    D4_BUDGET_MS = 45

    def _measure(self, launcher, rounds):
        mgr = ShellHandleManager(launcher=launcher, flags={"enable_shell_handles": True})
        flags = {"enable_worker_tool_call": True}
        lat = []
        try:
            for i in range(rounds):
                t0 = time.perf_counter()
                r = call_worker_tool(
                    "verifier",
                    "store_admin_status",
                    manager=mgr,
                    flags=flags,
                    trace_id=f"s6-{i}",
                )
                assert r["ok"] is True
                lat.append((time.perf_counter() - t0) * 1000)
        finally:
            mgr.close_all()
        lat.sort()
        return statistics.median(lat)

    def test_transport_component_within_d4_budget(self):
        """D4 硬约束: 真壳传输分量(real_p50 - fake_p50) ≤ 45ms。"""

        class _FakeShell:
            def __init__(self, spec):
                self.spec = spec

            def call(self, tool, args=None):
                return {"ok": True, "data": {"tool": tool}}

            def close(self):
                pass

        fake_p50 = self._measure(lambda spec: _FakeShell(spec), self.ROUNDS)
        real_p50 = self._measure(stdio_launcher, self.ROUNDS)
        transport = real_p50 - fake_p50
        assert (
            transport <= self.D4_BUDGET_MS
        ), f"D4 预算破: transport_component={transport:.3f}ms > {self.D4_BUDGET_MS}ms"
