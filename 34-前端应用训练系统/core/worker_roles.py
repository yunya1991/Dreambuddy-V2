# -*- coding: utf-8 -*-
"""W3：Worker 角色白名单与 G2 连接聚合校验。

依据 PROPOSAL-P0-D3 §4.7（ADR-9/G1/G2）：
  - Worker 只读：按 `worker_roles[role].tools` 白名单装载工具，越权在拉起器侧拒绝
  - G2：壳实例按域共享，连接数不随 Worker 数增长（角色网关共用一个入口）

本模块只做**校验**，不做工具调用；拉起器用它判定 assignment 的工具请求是否越权。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional, Set

import yaml

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_ROLES_PATH = os.path.join(_REPO_ROOT, "47-MCP管理系统", "registry", "mcp_capabilities.yaml")
DEFAULT_PROFILES_PATH = os.path.join(_REPO_ROOT, "47-MCP管理系统", "registry", "mcp_profiles.json")

MAX_TOOLS_PER_ROLE = 10

# 写工具：任何 Worker 角色都不得纳入（ADR-9/H7）
WRITE_TOOLS = frozenset(
    {"place_order", "cancel_order", "ingest_signal", "forward_signal", "record", "verify"}
)


def load_worker_roles(path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """从 47 registry 读取 worker_roles；失败返回空字典（FAIL-OPEN 由调用方决定）。"""
    try:
        with open(path or DEFAULT_ROLES_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {}
    roles = data.get("worker_roles") if isinstance(data, dict) else None
    return roles if isinstance(roles, dict) else {}


class RolePolicy:
    """角色 → 工具白名单。"""

    def __init__(self, roles: Optional[Dict[str, Any]] = None) -> None:
        self.roles = roles or {}

    def allowed(self, role: str) -> Optional[Set[str]]:
        cfg = self.roles.get(str(role))
        if not isinstance(cfg, dict):
            return None
        tools = cfg.get("tools")
        if not isinstance(tools, (list, tuple)):
            return set()
        return {str(t) for t in tools}

    def check(self, role: str, requested: Optional[Iterable[Any]] = None) -> Optional[str]:
        """返回违规原因；None 表示通过。"""
        cfg = self.roles.get(str(role))
        if not isinstance(cfg, dict):
            return "role %r not in worker_roles whitelist" % role
        tools = cfg.get("tools")
        if not isinstance(tools, (list, tuple)) or not tools:
            return "role %r has empty tool set" % role
        if requested is None:
            return None
        allowed = {str(t) for t in tools}
        extra = sorted({str(t) for t in requested} - allowed)
        if extra:
            return "tool(s) %s not allowed for role %r" % (",".join(extra), role)
        return None

    def validate(self) -> List[str]:
        """花名册自检：工具上限、写工具、壳声明、重复项。"""
        problems: List[str] = []
        for role, cfg in self.roles.items():
            if not isinstance(cfg, dict):
                problems.append("%s: role config is not a mapping" % role)
                continue
            tools = cfg.get("tools")
            if not isinstance(tools, (list, tuple)) or not tools:
                problems.append("%s: empty tool set" % role)
                continue
            if len(tools) > MAX_TOOLS_PER_ROLE:
                problems.append("%s: %d tools > max %d" % (role, len(tools), MAX_TOOLS_PER_ROLE))
            if len(set(tools)) != len(tools):
                problems.append("%s: duplicate tools" % role)
            written = sorted(set(tools) & WRITE_TOOLS)
            if written:
                problems.append("%s: write tools forbidden: %s" % (role, ",".join(written)))
            shells = cfg.get("shells")
            if not isinstance(shells, (list, tuple)) or not shells:
                problems.append("%s: empty shells" % role)
        return problems


def g2_summary(profiles_path: Optional[str] = None) -> Dict[str, Any]:
    """G2 连接聚合：角色网关是否共用同一入口（连接数不随 Worker 数增长）。"""
    with open(profiles_path or DEFAULT_PROFILES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    profiles = data.get("profiles") if isinstance(data, dict) else {}
    profiles = profiles if isinstance(profiles, dict) else {}

    def entrypoint(cfg: Dict[str, Any]) -> str:
        command = str(cfg.get("command") or "")
        args = cfg.get("args") if isinstance(cfg.get("args"), list) else []
        if command == "ssh":
            return "ssh"
        return str(args[0]) if args else command

    role_scoped = {
        name: entrypoint(cfg)
        for name, cfg in profiles.items()
        if isinstance(cfg, dict) and any(str(a) == "--role" for a in (cfg.get("args") or []))
    }
    entrypoints = sorted({entrypoint(cfg) for cfg in profiles.values() if isinstance(cfg, dict)})
    role_entrypoints = sorted(set(role_scoped.values()))
    return {
        "profiles": len(profiles),
        "entrypoints": entrypoints,
        "role_scoped_profiles": sorted(role_scoped),
        "role_scoped_entrypoints": role_entrypoints,
        "connections_independent_of_roles": len(role_entrypoints) <= 1,
    }
