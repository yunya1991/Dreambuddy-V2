"""H1：CapabilityBundle 声明层（登记 + hash）。

边界（SPEC-56-H v0.3 §4.1）：
    - 本模块只做「声明与登记」，不做执行、不调度 Worker；
      实际执行仍交给 DSH（route_hint → Worker/Model）。
    - bundle.tools 必须是 H2 tool_set 快照的子集，不能绕过审批。
    - hash 只覆盖声明字段，不含 generated_at，保证同一声明可复现。
    - 证据来源是 manifest declaration，不是 runtime observation；
      G-L2-12 在 P1 enforce 前保持 off。

与现有代码的关系：
    - 复用 A1-2 `tool_set.NAME_PATTERN` 的工具名口径；
    - 不修改 34 `route_hint`，只提供 `bundle_route_hint()` 供调用方按需合并。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, Iterable, Optional

from .tool_set import NAME_PATTERN

AGENT_PROFILES = ("developer", "reviewer", "researcher", "operator")
PERMISSION_MODES = ("read", "write", "trade")
BUNDLE_SOURCES = ("registry", "manifest", "override")

# 声明登记表：agent_profile_id → 默认声明（可在 build 时按调用方 override）
DEFAULT_DECLARATIONS: Dict[str, Dict[str, Any]] = {
    "developer": {
        "worker_role_id": "engineer",
        "model_profile": {
            "model_id": "qwen-max",
            "context_window": 131072,
            "capabilities": ["tool_use"],
        },
        "skills": ["dream-tdd-dev-workflow"],
        "tools": ["l0.rea.get_rea_snapshot"],
        "permission_mode": "read",
        "requires_mandate": False,
    },
    "reviewer": {
        "worker_role_id": "verifier",
        "model_profile": {
            "model_id": "qwen-max",
            "context_window": 131072,
            "capabilities": ["tool_use"],
        },
        "skills": ["dream-acceptance-verify"],
        "tools": ["l0.eval.eval_analyze"],
        "permission_mode": "read",
        "requires_mandate": False,
    },
    "researcher": {
        "worker_role_id": "research",
        "model_profile": {
            "model_id": "qwen-max",
            "context_window": 131072,
            "capabilities": ["tool_use"],
        },
        "skills": ["dream-research-workflow"],
        "tools": ["l0.cognition.recall", "l0.cognition.unified_search"],
        "permission_mode": "read",
        "requires_mandate": False,
    },
    "operator": {
        "worker_role_id": "l2_planner",
        "model_profile": {
            "model_id": "qwen-max",
            "context_window": 131072,
            "capabilities": ["tool_use"],
        },
        "skills": [],
        "tools": ["l2.dreamos.poll_run", "l2.dreamos.get_result"],
        "permission_mode": "read",
        "requires_mandate": False,
    },
}

# 运行时登记表（进程内；持久化可由 47 registry 后续接管）
BUNDLE_REGISTRY: Dict[str, Dict[str, Any]] = {}


class CapabilityBundleError(ValueError):
    """声明不合法（漂移需立即暴露，不静默降级）"""


def _canonical(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def compute_bundle_hash(
    *,
    agent_profile_id: str,
    worker_role_id: str,
    model_profile: Dict[str, Any],
    skills: Iterable[str],
    tools: Iterable[str],
    permission_mode: str,
) -> str:
    """对声明字段做 canonical JSON 哈希（不含 bundle_id / source / generated_at）"""
    payload = {
        "agent_profile_id": agent_profile_id,
        "worker_role_id": worker_role_id,
        "model_profile": model_profile,
        "skills": sorted(str(s) for s in skills or []),
        "tools": sorted(str(t) for t in tools or []),
        "permission_mode": permission_mode,
    }
    digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def build_bundle(
    agent_profile_id: str,
    *,
    worker_role_id: Optional[str] = None,
    model_profile: Optional[Dict[str, Any]] = None,
    skills: Optional[Iterable[str]] = None,
    tools: Optional[Iterable[str]] = None,
    permission_mode: Optional[str] = None,
    requires_mandate: Optional[bool] = None,
    source: str = "registry",
    bundle_id: Optional[str] = None,
    allowed_tools: Optional[Iterable[str]] = None,
    worker_roles: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """生成声明对象（不执行、不落盘）。

    allowed_tools: H2 快照工具名集合；提供时 bundle.tools 必须是其子集。
    worker_roles: 47 registry 的角色集合；提供时 worker_role_id 必须存在。
    """
    if agent_profile_id not in AGENT_PROFILES:
        raise CapabilityBundleError(
            f"agent_profile_id 非法: {agent_profile_id!r}，允许 {AGENT_PROFILES}"
        )
    if source not in BUNDLE_SOURCES:
        raise CapabilityBundleError(f"source 非法: {source!r}，允许 {BUNDLE_SOURCES}")

    declaration = DEFAULT_DECLARATIONS[agent_profile_id]
    role = worker_role_id or declaration["worker_role_id"]
    profile = model_profile or declaration["model_profile"]
    declared_skills = list(skills if skills is not None else declaration["skills"])
    declared_tools = list(tools if tools is not None else declaration["tools"])
    mode = permission_mode or declaration["permission_mode"]
    mandate = (
        bool(requires_mandate)
        if requires_mandate is not None
        else bool(declaration["requires_mandate"])
    )

    if mode not in PERMISSION_MODES:
        raise CapabilityBundleError(f"permission_mode 非法: {mode!r}，允许 {PERMISSION_MODES}")
    if not isinstance(role, str) or not role.strip():
        raise CapabilityBundleError("worker_role_id 不能为空")
    if worker_roles is not None and role not in set(worker_roles):
        raise CapabilityBundleError(f"worker_role_id 未在 47 registry 登记: {role!r}")
    if not isinstance(profile, dict) or not profile.get("model_id"):
        raise CapabilityBundleError("model_profile 必须包含 model_id")

    for tool in declared_tools:
        if not NAME_PATTERN.match(str(tool)):
            raise CapabilityBundleError(f"tools 含非法工具名: {tool!r}")
    if allowed_tools is not None:
        allowed = set(allowed_tools)
        outside = sorted(set(declared_tools) - allowed)
        if outside:
            raise CapabilityBundleError(f"bundle.tools 必须是 tool_set 子集，越界: {outside}")

    if mode == "read" and mandate:
        raise CapabilityBundleError("permission_mode=read 时不得 requires_mandate=true")
    if mode in ("write", "trade") and not mandate:
        raise CapabilityBundleError(f"permission_mode={mode} 时 requires_mandate 必须为 true")

    payload = {
        "bundle_id": bundle_id or f"cb-{uuid.uuid4().hex[:12]}",
        "agent_profile_id": agent_profile_id,
        "worker_role_id": role,
        "model_profile": profile,
        "skills": declared_skills,
        "tools": declared_tools,
        "permission_mode": mode,
        "requires_mandate": mandate,
        "source": source,
    }
    payload["hash"] = compute_bundle_hash(
        agent_profile_id=agent_profile_id,
        worker_role_id=role,
        model_profile=profile,
        skills=declared_skills,
        tools=declared_tools,
        permission_mode=mode,
    )
    return payload


def register_bundle(bundle: Dict[str, Any], *, replace: bool = False) -> Dict[str, Any]:
    """登记 bundle（按 bundle_id 去重；同 id 不同内容默认拒绝）"""
    if not isinstance(bundle, dict) or not bundle.get("bundle_id"):
        raise CapabilityBundleError("登记对象必须含 bundle_id")
    expected = compute_bundle_hash(
        agent_profile_id=bundle.get("agent_profile_id", ""),
        worker_role_id=bundle.get("worker_role_id", ""),
        model_profile=bundle.get("model_profile") or {},
        skills=bundle.get("skills") or [],
        tools=bundle.get("tools") or [],
        permission_mode=bundle.get("permission_mode", ""),
    )
    if bundle.get("hash") != expected:
        raise CapabilityBundleError("bundle.hash 与声明内容不一致，拒绝登记")

    bundle_id = bundle["bundle_id"]
    existing = BUNDLE_REGISTRY.get(bundle_id)
    if existing is not None and existing != bundle and not replace:
        raise CapabilityBundleError(f"bundle_id 已登记且内容不同: {bundle_id}")
    BUNDLE_REGISTRY[bundle_id] = dict(bundle)
    return BUNDLE_REGISTRY[bundle_id]


def get_bundle(bundle_id: str) -> Optional[Dict[str, Any]]:
    found = BUNDLE_REGISTRY.get(bundle_id)
    return dict(found) if found else None


def bundle_route_hint(bundle: Dict[str, Any]) -> Dict[str, str]:
    """供 34 route_hint 增量合并：只给 ID，不携带执行指令"""
    if not isinstance(bundle, dict) or not bundle.get("bundle_id"):
        raise CapabilityBundleError("bundle_route_hint 需要已登记的 bundle")
    return {
        "capability_bundle_id": str(bundle["bundle_id"]),
        "model_profile_id": str((bundle.get("model_profile") or {}).get("model_id") or ""),
    }


__all__ = [
    "AGENT_PROFILES",
    "BUNDLE_REGISTRY",
    "BUNDLE_SOURCES",
    "CapabilityBundleError",
    "DEFAULT_DECLARATIONS",
    "PERMISSION_MODES",
    "build_bundle",
    "bundle_route_hint",
    "compute_bundle_hash",
    "get_bundle",
    "register_bundle",
]
