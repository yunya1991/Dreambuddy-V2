# -*- coding: utf-8 -*-
"""Super-agent P0 handlers — 由 python-server/server.py 在进程内直接调用。

P1-2/D3: 原 `superagent_bridge.py` 是独立常驻子进程；现合并进 server.py 的单进程
IPC 服务，减少一个常驻 Python 子进程。本模块只提供方法实现，不负责 stdin/stdout。

包装 34-前端应用训练系统/core/ 下的 P0 组件:
  - event_gateway       → event_gateway_route (L1 shadow, 零 token 三分流)
  - ticket_router       → ticket_router_dispatch (无状态单轮分派)
  - okr_ticket_bridge   → ticket_bridge_translate  (OKR→Ticket 翻译)
  - ticket_state        → ticket_state_transition  (四态状态机)

硬约束 (DESIGN-DSH-ARCH-UPGRADE v0.2):
  HC-1 FAIL-OPEN: 任何组件异常 → 返回 degraded 结果,不抛错
  HC-2 总闸门 DSH_ENABLE_UPGRADE(默认 false)关闭时全部降级
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import traceback
from typing import Any, Dict, Optional

# ── sys.path 注入: 让 P0 组件可 import ──────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGES_DIR = os.path.dirname(_THIS_DIR)
_BRIDGE_DIR = os.path.dirname(_PACKAGES_DIR)
_REPO_ROOT = os.path.dirname(os.path.dirname(_BRIDGE_DIR))
_CORE_34 = os.path.join(_REPO_ROOT, "34-前端应用训练系统", "core")
_PARENT_34 = os.path.join(_REPO_ROOT, "34-前端应用训练系统")

# core 目录需要作为 package 加载(okr_ticket_bridge 有 relative import)
_init_path = os.path.join(_CORE_34, "__init__.py")
if not os.path.exists(_init_path):
    try:
        with open(_init_path, "w") as f:
            f.write("")
    except Exception:
        pass

for _p in [_PARENT_34, _CORE_34]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

# ── 总闸门开关 (HC-2) ────────────────────────────────────────────────
ENABLE_UPGRADE = os.environ.get("DSH_ENABLE_UPGRADE", "false").lower() in (
    "true",
    "1",
    "yes",
)

_p0_modules: Dict[str, Any] = {}


def _load_p0(name: str) -> Optional[Any]:
    """延迟加载 P0 组件,失败返回 None(FAIL-OPEN)。"""
    if name in _p0_modules:
        return _p0_modules[name]
    try:
        if name in {"event_gateway", "ticket_router", "ticket_state"}:
            spec = importlib.util.spec_from_file_location(
                name, os.path.join(_CORE_34, f"{name}.py")
            )
            if spec and spec.loader:
                m = importlib.util.module_from_spec(spec)
                sys.modules[name] = m
                spec.loader.exec_module(m)
                _p0_modules[name] = m
                return m
        elif name in {"okr_ticket_bridge", "router_loop", "ticket_store", "thread_affinity"}:
            mod = importlib.import_module("core.%s" % name)
            _p0_modules[name] = mod
            return mod
        return None
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[SuperAgentP0] 加载 {name} 失败: {e}\n")
        sys.stderr.write(traceback.format_exc() + "\n")
        return None


def _degraded(reason: str) -> Dict[str, Any]:
    return {"ok": False, "degraded": True, "reason": reason}


# ── 方法实现 ────────────────────────────────────────────────────────


def _health(params: Dict[str, Any]) -> Dict[str, Any]:
    status = {}
    for name in (
        "event_gateway",
        "ticket_router",
        "okr_ticket_bridge",
        "ticket_state",
        "router_loop",
    ):
        status[name] = _load_p0(name) is not None
    return {
        "ok": True,
        "result": {
            "upgrade_enabled": ENABLE_UPGRADE,
            "p0_components": status,
            "profile": os.environ.get("DSH_PROFILE", "unknown"),
        },
    }


def _event_gateway_route(params: Dict[str, Any]) -> Dict[str, Any]:
    if not ENABLE_UPGRADE:
        return _degraded("upgrade_disabled")
    mod = _load_p0("event_gateway")
    if mod is None:
        return _degraded("event_gateway_unavailable")
    try:
        trigger = params.get("trigger") or {}
        intents = params.get("intents") or None
        # P0 默认 shadow=True — 只记录不拦截 (DESIGN §五 P0 退出判据)
        result = mod.route_trigger(trigger, intents=intents, shadow=True)
        return {"ok": True, "result": result}
    except Exception as e:  # noqa: BLE001
        return _degraded(f"event_gateway_error: {type(e).__name__}: {e}")


def _ticket_router_dispatch(params: Dict[str, Any]) -> Dict[str, Any]:
    if not ENABLE_UPGRADE:
        return _degraded("upgrade_disabled")
    mod = _load_p0("ticket_router")
    if mod is None:
        return _degraded("ticket_router_unavailable")
    try:
        plan = params.get("plan")
        workers = params.get("workers")
        completed_refs = set(params.get("completed_refs") or [])
        assignments = mod.route_single_round(plan, workers, completed_refs)
        return {"ok": True, "result": assignments}
    except Exception as e:  # noqa: BLE001
        return _degraded(f"ticket_router_error: {type(e).__name__}: {e}")


def _ticket_bridge_translate(params: Dict[str, Any]) -> Dict[str, Any]:
    if not ENABLE_UPGRADE:
        return _degraded("upgrade_disabled")
    mod = _load_p0("okr_ticket_bridge")
    if mod is None:
        return _degraded("okr_ticket_bridge_unavailable")
    try:
        okr_nodes = params.get("okr_nodes") or {}
        flags = params.get("flags") or {"enable_superagent_bridge": True}
        plan = mod.translate_plan_to_tickets(okr_nodes, flags=flags)
        return {"ok": True, "result": plan}
    except Exception as e:  # noqa: BLE001
        return _degraded(f"ticket_bridge_error: {type(e).__name__}: {e}")


def _ticket_state_transition(params: Dict[str, Any]) -> Dict[str, Any]:
    mod = _load_p0("ticket_state")
    if mod is None:
        return _degraded("ticket_state_unavailable")
    try:
        ticket = params.get("ticket")
        new_state = params.get("new_state") or params.get("action")
        if ticket and new_state:
            return {"ok": True, "result": mod.transition_ticket(ticket, new_state)}
        # 简写: {current, action} — 只校验迁移合法性,不持有记录
        if params.get("current") and params.get("action"):
            legal = mod._TRANSITIONS.get(params["current"], set())
            return {
                "ok": True,
                "result": {
                    "current": params["current"],
                    "action": params["action"],
                    "new_state": params["action"],
                    "legal_transition": params["action"] in legal,
                },
            }
        return _degraded("invalid_params")
    except Exception as e:  # noqa: BLE001
        return _degraded(f"ticket_state_error: {type(e).__name__}: {e}")


# ── D2: 常驻 Router 循环(单轮 pass 编排,无状态) ──────────────────────
# 进程级单例: store(L0) / affinity(可丢) / stats(可丢) / inbox sink
_LOOP_STATE: Dict[str, Any] = {
    "store": None,
    "affinity": None,
    "stats": None,
    "sink": None,
}

# 循环语义下默认开启槽位/亲和(否则 route_single_round 不剔除占槽会重复分派);
# 调用方可通过 params.flags 覆盖
_DEFAULT_LOOP_FLAGS: Dict[str, Any] = {
    "enable_router_loop": True,
    "enable_superagent_router": True,
    "enable_ticket_store": True,
    "enable_worker_pool": True,
    "enable_thread_affinity": True,
}


def _loop_state() -> Dict[str, Any]:
    """惰性构建循环依赖(FAIL-OPEN: 任一组件缺失即抛,由调用方降级)。"""
    if _LOOP_STATE["store"] is None:
        store_mod = _load_p0("ticket_store")
        loop_mod = _load_p0("router_loop")
        if store_mod is None or loop_mod is None:
            raise RuntimeError("router_loop_unavailable")
        affinity_mod = _load_p0("thread_affinity")
        _LOOP_STATE["store"] = store_mod.JsonlTicketStore(root=_REPO_ROOT)
        _LOOP_STATE["affinity"] = affinity_mod.AffinityTable() if affinity_mod is not None else None
        _LOOP_STATE["stats"] = loop_mod.PassStats()
        _LOOP_STATE["sink"] = loop_mod.JsonlInboxSink(root=_REPO_ROOT)
    return _LOOP_STATE


def _router_pass(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行一次 pass(八步)。params: roster/plan/triggers/completed_refs/shadow/flags。"""
    if not ENABLE_UPGRADE:
        return _degraded("upgrade_disabled")
    loop_mod = _load_p0("router_loop")
    if loop_mod is None:
        return _degraded("router_loop_unavailable")
    try:
        state = _loop_state()
        flags = dict(_DEFAULT_LOOP_FLAGS)
        flags.update(params.get("flags") or {})
        summary = loop_mod.run_pass(
            state["store"],
            roster=params.get("roster") or {},
            affinity=state["affinity"],
            triggers=params.get("triggers"),
            plan=params.get("plan"),
            completed_refs=set(params.get("completed_refs") or []),
            sink=state["sink"],
            flags=flags,
            shadow=bool(params.get("shadow", True)),
            gate=None,  # 生产双门由调用方注入;未注入视为单门放行(MVP)
            stats=state["stats"],
        )
        return {"ok": True, "result": summary}
    except Exception as e:  # noqa: BLE001
        return _degraded(f"router_pass_error: {type(e).__name__}: {e}")


def _router_loop_stats(params: Dict[str, Any]) -> Dict[str, Any]:
    """循环诊断面: 最近 N 轮摘要 + 计数(只读,不触发 pass)。"""
    loop_mod = _load_p0("router_loop")
    if loop_mod is None:
        return _degraded("router_loop_unavailable")
    try:
        state = _loop_state()
        return {
            "ok": True,
            "result": {
                "upgrade_enabled": ENABLE_UPGRADE,
                "store_root": _REPO_ROOT,
                "stats": state["stats"].snapshot(),
            },
        }
    except Exception as e:  # noqa: BLE001
        return _degraded(f"router_loop_stats_error: {type(e).__name__}: {e}")


_METHODS = {
    "superagent_p0_health": _health,
    "event_gateway_route": _event_gateway_route,
    "ticket_router_dispatch": _ticket_router_dispatch,
    "ticket_bridge_translate": _ticket_bridge_translate,
    "ticket_state_transition": _ticket_state_transition,
    "router_pass": _router_pass,
    "router_loop_stats": _router_loop_stats,
}

METHOD_NAMES = frozenset(_METHODS)


def handle(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """server.py 分派入口。异常一律降级,不击穿 IPC 主循环。"""
    handler = _METHODS.get(method)
    if handler is None:
        return _degraded(f"unknown_method: {method}")
    try:
        return handler(params or {})
    except Exception as e:  # noqa: BLE001
        traceback.print_exc(file=sys.stderr)
        return _degraded(f"handler_exception: {type(e).__name__}: {e}")
