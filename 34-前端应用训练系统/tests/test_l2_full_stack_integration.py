# -*- coding: utf-8 -*-
"""L2 完整架构集成测试：DreamOs(SACG) ↔ DSH ↔ L0。

接线点: SACGOrchestrator.c_executor = DSH call_worker_tool + stdio_launcher。
验证 S→A→C→G 每一层都经过并触发真 stdio 壳进程 + L0-DAL 健康枚举。

与既有测试的差异:
  - test_e2e_worker_wiring.py: FakeShell + 无 SACG
  - test_dsh_l0_scenario.py: stdio 真壳 + 无 SACG
  - 本测试: stdio 真壳 + SACG 编排层接线完整链路
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from core.sacg_orchestrator import SACGOrchestrator
from core.shell_handles import ShellHandleManager
from core.stdio_shell_launcher import stdio_launcher
from core.worker_tool_call import call_worker_tool

ON = {"enable_worker_tool_call": True}


@pytest.fixture
def real_manager():
    mgr = ShellHandleManager(launcher=stdio_launcher, flags={"enable_shell_handles": True})
    yield mgr
    mgr.close_all()


def _dsh_c_executor(manager, flags, trace_prefix="l2"):
    """把 DSH call_worker_tool 包装成 SACG C 层执行器。"""

    def _exec(router, node):
        role = node.get("role")
        tool = node.get("tool")
        if not role or not tool:
            return {"action": "CONTINUE", "tier": "Tier1", "dsh": {"skipped": True}}
        r = call_worker_tool(
            role,
            tool,
            args=node.get("args"),
            manager=manager,
            flags=flags,
            trace_id=f"{trace_prefix}-{node.get('node_id')}",
        )
        return {
            "action": "CONTINUE" if r.get("ok") else "FAILED",
            "tier": "Tier1",
            "effort_level": "light",
            "dsh_result": r,
        }

    return _exec


def _single_storeadmin_node(plan):
    """定制 A 层节点: verifier→store_admin_status (单节点)。"""
    return [
        {
            "node_id": "N-store-admin",
            "criteria": "库管健康状态验证",
            "role": "verifier",
            "tool": "store_admin_status",
        }
    ]


def _high_score_mems(n=5, score=0.95):
    """L1_DIRECT 触发条件: memories 有高分条目。"""
    return [SimpleNamespace(score=score, content=f"mem{i}") for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════
# Test 1: SACG → DSH → stdio 真壳 → L0-DAL 全链 1 次走通
# ═══════════════════════════════════════════════════════════════════════


class TestL2FullChainOneShot:
    def test_sacg_handoff_executes_via_dsh(self, real_manager):
        """L2_HANDOFF → S 规划 → A 分解 → C(真壳执行) → G 收尾, 全部 ok。"""
        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(real_manager, ON),
            a_decomposer=_single_storeadmin_node,
        )
        out = orch.handle("帮我验证库管健康状态", l1_intent_hint=None, memories=[])
        # 关键断言 1: 进入编排, stages = ["S", "A", "C", "G"]
        assert out["route"] == "L2_HANDOFF"
        assert out["orchestrated"] is True
        assert out["stages"] == ["S", "A", "C", "G"]
        # 关键断言 2: C 层节点 result.action=CONTINUE (DSH 真壳调用 ok)
        node_results = out["node_results"]
        assert len(node_results) == 1
        assert node_results[0]["action"] == "CONTINUE"
        # 关键断言 3: DSH 真壳结果内嵌 detail.dsh_result, 含 l0.store-admin.mcp + DAL 6 repo
        dsh_res = node_results[0]["detail"]["dsh_result"]
        assert dsh_res["ok"] is True
        assert dsh_res["data"]["shell"] == "l0.store-admin.mcp"
        repos = dsh_res["data"]["repos"]
        assert set(repos.keys()) == {"trade", "position", "market_macro", "risk", "config", "kg"}

    def test_manager_stats_after_full_chain(self, real_manager):
        """完整 L2 链路跑完后, manager 应只拉起 1 个真壳(ADR-10)。"""
        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(real_manager, ON),
            a_decomposer=_single_storeadmin_node,
        )
        orch.handle("验证", l1_intent_hint=None, memories=[])
        stats = real_manager.stats()
        assert len(stats) == 1
        assert stats["l0.store-admin.mcp"]["handles_issued"] == 1


# ═══════════════════════════════════════════════════════════════════════
# Test 2: SACG 多节点 → DSH 多 Worker 工具 → 同壳复用 (ADR-10)
# ═══════════════════════════════════════════════════════════════════════


class TestL2MultiNodeAdr10Reuse:
    def test_two_nodes_share_one_shell(self, real_manager):
        """2 个 SACG 节点都调 store-admin → 真壳只拉起 1 次, handles_issued=2。"""

        def _two_nodes(plan):
            return [
                {
                    "node_id": "N1",
                    "criteria": "状态",
                    "role": "verifier",
                    "tool": "store_admin_status",
                },
                {
                    "node_id": "N2",
                    "criteria": "查询",
                    "role": "verifier",
                    "tool": "store_admin_query",
                    "args": {"repo": "trade", "limit": 3},
                },
            ]

        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(real_manager, ON),
            a_decomposer=_two_nodes,
        )
        out = orch.handle("2 节点测试", l1_intent_hint=None, memories=[])
        # 两个节点都 CONTINUE
        nr = out["node_results"]
        assert len(nr) == 2
        assert all(r["action"] == "CONTINUE" for r in nr)
        # 关键: ADR-10 单壳复用
        stats = real_manager.stats()
        assert len(stats) == 1, f"不应多拉起壳, 实际: {list(stats.keys())}"
        assert stats["l0.store-admin.mcp"]["handles_issued"] == 2

    def test_manager_close_all_kills_shell(self, real_manager):
        """完整链路跑完, manager.close_all() 后底层壳进程 is_alive=False。"""
        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(real_manager, ON),
            a_decomposer=_single_storeadmin_node,
        )
        orch.handle("close 测试", l1_intent_hint=None, memories=[])
        shell = real_manager._shells.get("l0.store-admin.mcp")
        assert shell is not None
        real_manager.close_all()
        assert shell.is_alive() is False


# ═══════════════════════════════════════════════════════════════════════
# Test 3: SACG C 层 DSH 调用失败 → FAILED, SACG 不崩继续走 G
# ═══════════════════════════════════════════════════════════════════════


class TestL2FailurePropagation:
    def test_bad_role_forbidden_action_failed(self, real_manager):
        """DSH gate 拒绝 engineer→store_admin_status → node action=FAILED, SACG 仍走完 G。"""

        def _bad_node(plan):
            return [
                {
                    "node_id": "N-bad",
                    "criteria": "角色能力集外",
                    "role": "engineer",
                    "tool": "store_admin_status",
                },
            ]

        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(real_manager, ON),
            a_decomposer=_bad_node,
        )
        out = orch.handle("坏角色节点", l1_intent_hint=None, memories=[])
        nr = out["node_results"][0]
        assert nr["action"] == "FAILED"
        assert nr["detail"]["dsh_result"]["error_code"] == "forbidden"
        # FAIL-OPEN: SACG 不崩, stages 完整
        assert out["stages"] == ["S", "A", "C", "G"]

    def test_invalid_repo_action_failed(self, real_manager):
        """store_admin_query repo=invalid → DSH degraded → node action=FAILED, G 仍到达。"""

        def _invalid_repo(plan):
            return [
                {
                    "node_id": "N-inv",
                    "criteria": "无效 repo",
                    "role": "verifier",
                    "tool": "store_admin_query",
                    "args": {"repo": "nonexistent"},
                },
            ]

        orch = SACGOrchestrator(
            c_executor=_dsh_c_executor(real_manager, ON),
            a_decomposer=_invalid_repo,
        )
        out = orch.handle("无效查询", l1_intent_hint=None, memories=[])
        assert out["node_results"][0]["action"] == "FAILED"
        assert out["stages"] == ["S", "A", "C", "G"]


# ═══════════════════════════════════════════════════════════════════════
# Test 4: L1_DIRECT 直答短路编排层, c_executor 根本不触发
# ═══════════════════════════════════════════════════════════════════════


class TestL1DirectShortCircuit:
    def test_no_c_executor_called_for_l1_direct(self):
        """L1_DIRECT 条件满足(memories 有高分) → c_executor 不被调。"""
        called = []

        def _spy_exec(router, node):
            called.append(True)
            return {"action": "CONTINUE", "tier": "Tier1"}

        orch = SACGOrchestrator(c_executor=_spy_exec)
        out = orch.handle(
            "BTC什么价",
            l1_intent_hint="price_query",
            memories=_high_score_mems(n=5, score=0.95),
        )
        assert out["route"] == "L1_DIRECT"
        assert out["orchestrated"] is False
        assert out["stages"] == []
        assert called == []  # 确认没调 c_executor


# ═══════════════════════════════════════════════════════════════════════
# Test 5: DSH 开关关闭 → disabled 信封, SACG 不崩
# ═══════════════════════════════════════════════════════════════════════


class TestL2SwitchDisabled:
    def test_dsh_switch_off_yields_disabled(self, real_manager):
        """enable_worker_tool_call=False → DSH 返回 disabled, SACG 节点 FAILED 但不崩。"""

        def _dsh_off(router, node):
            role = node.get("role")
            tool = node.get("tool")
            r = call_worker_tool(
                role,
                tool,
                manager=real_manager,
                flags={},  # 开关关!
                trace_id="off-1",
            )
            return {
                "action": "FAILED" if not r.get("ok") else "CONTINUE",
                "tier": "Tier1",
                "dsh_result": r,
            }

        orch = SACGOrchestrator(
            c_executor=_dsh_off,
            a_decomposer=_single_storeadmin_node,
        )
        out = orch.handle("开关关闭测试", l1_intent_hint=None, memories=[])
        nr = out["node_results"][0]
        assert nr["detail"]["dsh_result"]["error_code"] == "disabled"
        # FAIL-OPEN: SACG 不崩, stages 完整
        assert out["stages"] == ["S", "A", "C", "G"]
