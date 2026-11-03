# -*- coding: utf-8 -*-
"""Mandate 工具集越权拒绝(T-DSH-P1 P1-4)。

依据: DESIGN-DSH-ARCH-UPGRADE v0.2 ADR-4(能力标签→工具集唯一载体 =
47-MCP管理系统/registry/mcp_capabilities.yaml,本模块只读引用不重复定义)
+ ADR-5(Mandate=工具授权+预算同源) + ADR-9/H7(Worker 默认只读:
requires_mandate=true 写工具禁止 Worker 持有,调用侧纵深防御) +
验收 V4(越权: 调用未授权工具被明确拒绝(非静默成功),审计留痕)。

定位: Worker 工具调用前的统一门禁。判定语义默认拒绝(deny-by-default):
未知角色/未知工具一律拒;写工具即使在角色集内也拒(H7: 写操作仅编排侧
/Verifier 持 Mandate 执行)。每次判定(含放行)可经 recorder 审计留痕。

硬约束:
  HC-1 FAIL-OPEN(不抛错): 坏输入 → allowed=False + reason,绝不静默放行
  HC-2 开关 enable_mandate_gate 默认 False
  registry 为唯一事实源: 文件缺失/坏 YAML → 空集合(此时一切调用被拒)
"""

from __future__ import annotations

import os
import time
from typing import Any, Callable, Dict, List, Optional, Set

# 模块化开关(HC-2,默认 False)
GATE_SWITCH = "enable_mandate_gate"

# 47 registry 默认路径(ADR-4 唯一载体;core/ → repo 根 → 47-MCP管理系统)
_DEFAULT_REGISTRY_PATH = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "47-MCP管理系统",
        "registry",
        "mcp_capabilities.yaml",
    )
)


def is_mandate_gate_enabled(flags: Optional[Dict[str, Any]] = None) -> bool:
    """模块化开关读取(HC-2)。flags 非 dict / 缺键 → False(默认关)。"""
    try:
        if not isinstance(flags, dict):
            return False
        return bool(flags.get(GATE_SWITCH, False))
    except Exception:
        return False


def _load_registry_doc(path: Optional[str]) -> Dict[str, Any]:
    try:
        import yaml  # 延迟导入: 无 pyyaml 环境下其余函数仍可用

        with open(path or _DEFAULT_REGISTRY_PATH, encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def load_worker_roles(path: Optional[str] = None) -> Dict[str, List[str]]:
    """读 47 registry worker_roles → {role: [tool_name, ...]}。缺失/坏文件 → {}。"""
    try:
        doc = _load_registry_doc(path)
        roles_raw = doc.get("worker_roles")
        if not isinstance(roles_raw, dict):
            return {}
        roles: Dict[str, List[str]] = {}
        for role, spec in roles_raw.items():
            if not isinstance(spec, dict):
                continue
            tools = [str(t) for t in (spec.get("tools") or []) if t]
            if tools:
                roles[str(role)] = tools
        return roles
    except Exception:
        return {}


def load_mandate_write_tools(path: Optional[str] = None) -> Set[str]:
    """读 registry 中 requires_mandate=true 的工具名集合(H7 纵深防御依据)。"""
    try:
        doc = _load_registry_doc(path)
        shells = doc.get("shells")
        if not isinstance(shells, list):
            return set()
        out: Set[str] = set()
        for shell in shells:
            if not isinstance(shell, dict):
                continue
            for tool in shell.get("tools") or []:
                if (
                    isinstance(tool, dict)
                    and tool.get("requires_mandate") is True
                    and tool.get("name")
                ):
                    out.add(str(tool["name"]))
        return out
    except Exception:
        return set()


def check_tool_call(
    role: Any,
    tool_name: Any,
    roles: Optional[Dict[str, List[str]]] = None,
    write_tools: Optional[Set[str]] = None,
    recorder: Optional[Callable[[Dict[str, Any]], None]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Worker 工具调用门禁: 默认拒绝,授权内放行,写工具一律拒(H7)。

    返回判定 {allowed, reason, role, tool, trace_id, ts}:
      ok                          授权内
      invalid_input               坏输入(安全默认拒绝)
      unknown_role                未知角色
      tool_not_in_role_set        越权(工具不在角色能力集)
      write_tool_requires_mandate 写工具(H7: 仅编排侧持 Mandate)
    判定结果(含放行)经 recorder 留痕;recorder 异常吞掉不击穿判定。
    """
    decision: Dict[str, Any] = {
        "allowed": False,
        "reason": "invalid_input",
        "role": None,
        "tool": None,
        "trace_id": trace_id,
        "ts": time.time(),
    }
    try:
        if not role or not tool_name:
            return _audit(decision, recorder)
        role_s = str(role)
        tool_s = str(tool_name)
        decision["role"] = role_s
        decision["tool"] = tool_s

        roles = roles if isinstance(roles, dict) else {}
        write_tools = write_tools if isinstance(write_tools, (set, frozenset)) else set()

        if role_s not in roles:
            decision["reason"] = "unknown_role"
            return _audit(decision, recorder)
        # H7 纵深: 写工具一律拒(即使在角色集内——registry 误配也在调用侧拦)
        if tool_s in write_tools:
            decision["reason"] = "write_tool_requires_mandate"
            return _audit(decision, recorder)
        if tool_s not in (roles.get(role_s) or []):
            decision["reason"] = "tool_not_in_role_set"
            return _audit(decision, recorder)

        decision["allowed"] = True
        decision["reason"] = "ok"
        return _audit(decision, recorder)
    except Exception:
        return _audit(decision, recorder)


def _audit(
    decision: Dict[str, Any],
    recorder: Optional[Callable[[Dict[str, Any]], None]],
) -> Dict[str, Any]:
    """审计留痕(V4): recorder 异常吞掉,不击穿判定。"""
    try:
        if recorder is not None:
            recorder(decision)
    except Exception:
        pass
    return decision
