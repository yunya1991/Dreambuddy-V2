# -*- coding: utf-8 -*-
"""T-DSH-P1 P1-4: Mandate 工具集越权拒绝测试（RED）。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-4(能力标签→工具集唯一载体 =
47-MCP管理系统/registry/mcp_capabilities.yaml,本模块只读引用) + ADR-5
(Mandate=工具授权+预算同源,越权与超预算同处判定) + ADR-9/H7(Worker 默认
只读: requires_mandate=true 写工具禁止出现在 Worker 角色集,纵深防御——
即使 registry 误配也在调用侧拒) + 验收 V4(越权: 调用未授权工具被明确拒绝
(非静默成功),审计留痕)。

验收:
  - load_worker_roles 读 47 registry worker_roles(research/engineer/verifier)
  - load_mandate_write_tools 读 registry 中 requires_mandate=true 工具集合
  - 授权内调用 → allowed=True
  - 越权(工具不在角色集) → allowed=False,reason=tool_not_in_role_set
  - 未知角色 → allowed=False,reason=unknown_role(默认拒绝,不静默放行)
  - H7 纵深: 写工具即使在角色集内 → allowed=False,reason=write_tool_requires_mandate
  - 审计: 每次判定(尤其拒绝)经 recorder 留痕,recorder 异常不击穿
  - FAIL-OPEN: 坏输入不抛错(但安全默认拒绝);registry 缺失 → {} / set()
  - 开关 enable_mandate_gate 默认 False
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.mandate_gate import (  # noqa: E402
    check_tool_call,
    is_mandate_gate_enabled,
    load_mandate_write_tools,
    load_worker_roles,
)


class TestSwitch:
    def test_default_off(self):
        assert is_mandate_gate_enabled() is False
        assert is_mandate_gate_enabled({}) is False
        assert is_mandate_gate_enabled(None) is False

    def test_on(self):
        assert is_mandate_gate_enabled({"enable_mandate_gate": True}) is True


class TestLoadRegistry:
    def test_load_worker_roles_real_registry(self):
        roles = load_worker_roles()  # 默认 47 registry 路径
        assert set(roles.keys()) == {"research", "engineer", "verifier"}
        assert "recall" in roles["research"]
        assert "data_fetch" in roles["engineer"]
        assert "eval_analyze" in roles["verifier"]
        for tools in roles.values():
            assert len(tools) <= 10  # ADR-4 每角色 ≤10 工具

    def test_load_write_tools_real_registry(self):
        write_tools = load_mandate_write_tools()
        # registry 中 requires_mandate=true 的写工具
        assert {
            "record",
            "verify",
            "distill_aliases",
            "training_feed",
            "data_store_write",
        } <= write_tools
        # 写工具不得出现在任何 Worker 角色集(registry 自身合规,ADR-9)
        roles = load_worker_roles()
        for tools in roles.values():
            assert not (set(tools) & write_tools)

    def test_load_missing_file_fail_open(self, tmp_path):
        assert load_worker_roles(str(tmp_path / "nope.yaml")) == {}
        assert load_mandate_write_tools(str(tmp_path / "nope.yaml")) == set()


class TestAllowed:
    def test_in_role_set_allowed(self):
        roles = {"research": ["recall", "unified_search"]}
        d = check_tool_call("research", "recall", roles=roles)
        assert d["allowed"] is True
        assert d["reason"] == "ok"
        assert d["role"] == "research"
        assert d["tool"] == "recall"

    def test_real_registry_verifier_eval(self):
        roles = load_worker_roles()
        write_tools = load_mandate_write_tools()
        d = check_tool_call("verifier", "eval_analyze", roles=roles, write_tools=write_tools)
        assert d["allowed"] is True


class TestDenied:
    def test_tool_not_in_role_set(self):
        roles = {"engineer": ["data_fetch"]}
        d = check_tool_call("engineer", "eval_report", roles=roles)
        assert d["allowed"] is False
        assert d["reason"] == "tool_not_in_role_set"

    def test_unknown_role_denied(self):
        """默认拒绝: 未知角色不得静默放行(V4 越权必须明确拒绝)。"""
        d = check_tool_call("ghost_role", "recall", roles={"research": ["recall"]})
        assert d["allowed"] is False
        assert d["reason"] == "unknown_role"

    def test_cross_role_denied_real_registry(self):
        """verifier 调 engineer 的数据工具 → 越权拒绝。"""
        roles = load_worker_roles()
        d = check_tool_call("verifier", "data_fetch", roles=roles)
        assert d["allowed"] is False
        assert d["reason"] == "tool_not_in_role_set"

    def test_write_tool_denied_even_if_in_role_set(self):
        """H7 纵深防御: 即使 registry 误配把写工具放进角色集,调用侧仍拒。"""
        roles = {"broken_role": ["record", "recall"]}  # 误配
        write_tools = {"record", "verify"}
        d = check_tool_call("broken_role", "record", roles=roles, write_tools=write_tools)
        assert d["allowed"] is False
        assert d["reason"] == "write_tool_requires_mandate"

    def test_invalid_input_denied_not_crash(self):
        assert check_tool_call(None, "recall", roles={})["allowed"] is False
        assert check_tool_call("research", None, roles={})["allowed"] is False
        assert check_tool_call("research", "recall", roles=None)["allowed"] is False


class TestAudit:
    def test_denial_recorded(self):
        verdicts = []
        check_tool_call(
            "engineer",
            "eval_report",
            roles={"engineer": ["data_fetch"]},
            recorder=verdicts.append,
            trace_id="tr-audit-1",
        )
        assert len(verdicts) == 1
        v = verdicts[0]
        assert v["allowed"] is False
        assert v["reason"] == "tool_not_in_role_set"
        assert v["trace_id"] == "tr-audit-1"  # 审计留痕带 trace

    def test_allow_also_recorded(self):
        verdicts = []
        check_tool_call(
            "research", "recall", roles={"research": ["recall"]}, recorder=verdicts.append
        )
        assert verdicts[0]["allowed"] is True

    def test_recorder_exception_swallowed(self):
        def bad_recorder(_):
            raise RuntimeError("boom")

        d = check_tool_call(
            "research", "recall", roles={"research": ["recall"]}, recorder=bad_recorder
        )
        assert d["allowed"] is True  # 审计异常不击穿判定
