# -*- coding: utf-8 -*-
"""六维上下文信封组装器(T-DSH-P0 C3)。

依据: SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2 §三.1 任务4 + VM-1792148857896
(L0 统一信封铁律: 源不可用=degraded(reason),源可达无数据=ok+data=None)。
定位: 事件网关分流 escalate_l2 时,调 L0 fetchContext 组装六维供给
(实时数据指标/SKILL/知识库/认知经验/CBR 真实案例/REA 逆向解析)上下文信封。

硬约束:
  信封铁律: 逐维原样保留 L0 子信封,degraded(reason) 不得改写为 ok(None),
            ok(None) 不得改写为 degraded
  通道:    in-process 优先(同进程调 L0Foundation.fetch_context,P0 默认);
            MCP 仅作跨端/非热路径兜底(经统一信封映射层,P0 不在范围)
  FAIL-OPEN: L0 异常/缺 scope/坏输入 → 逐维 degraded,整体仍返回信封,不抛错
  HC-4 零 token: 纯组装,无生成式 LLM
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .event_gateway import normalize_trigger

# 六维供给(SPEC §二)
SIX_DIMS: List[str] = ["market", "skill", "knowledge", "experience", "cases", "rea"]


def _dim_degraded(dim: str, reason: str, error: str = "") -> Dict[str, Any]:
    meta: Dict[str, Any] = {"reason": reason}
    if error:
        meta["error"] = error
    return {
        "ok": False,
        "data": None,
        "source": "l0_context_assembler",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "degraded": True,
        "meta": meta,
    }


def _dim_scopes(trigger: Dict[str, Any]) -> Dict[str, Optional[Dict[str, Any]]]:
    """维 → (scope, params) 映射。

    P0: market/knowledge/experience 三维接已注册 scope;skill/cases/rea
    尚无 L0 scope(占位 None → degraded(scope_unconfigured)),待后续 SPEC 注册。
    """
    topic = "%s %s" % (trigger.get("source", ""), trigger.get("kind", ""))
    return {
        "market": {"scope": "market.ticker", "params": {}},
        "skill": None,
        "knowledge": {"scope": "docs.search", "params": {"query": topic.strip()}},
        "experience": {
            "scope": "cognitive.recall",
            "params": {"context": topic.strip(), "top_k": 5},
        },
        "cases": None,
        "rea": None,
    }


def build_six_dim_context(
    raw_trigger: Any,
    l0: Optional[Any] = None,
    dim_scopes: Optional[Dict[str, Optional[Dict[str, Any]]]] = None,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Trigger → 六维上下文信封(升级 L2 的供给包)。

    返回: {ok, data:{trigger, trace_id, six_dims:{dim: 子信封}}, degraded, meta, ...}
      - 逐维子信封语义原样保留(信封铁律)
      - 顶层 degraded=True 仅当六维全 degraded;任一维可用即 ok
      - 任何异常 → 信封仍返回(逐维 degraded 或顶层 invalid_trigger),不抛错
    """
    try:
        trigger = normalize_trigger(raw_trigger)
        if trigger is None:
            env = _dim_degraded("all", "invalid_trigger")
            env["data"] = None
            return env

        scope_map = dim_scopes if dim_scopes is not None else _dim_scopes(trigger)
        six: Dict[str, Any] = {}
        for dim in SIX_DIMS:
            if l0 is None:
                six[dim] = _dim_degraded(dim, "l0_unavailable")
                continue
            conf = scope_map.get(dim)
            if not conf or not conf.get("scope"):
                six[dim] = _dim_degraded(dim, "scope_unconfigured")
                continue
            try:
                sub = l0.fetch_context(conf["scope"], conf.get("params") or {})
                if not isinstance(sub, dict) or "degraded" not in sub:
                    six[dim] = _dim_degraded(dim, "bad_envelope")
                else:
                    six[dim] = sub  # 铁律: 原样保留,不改写
            except Exception as exc:
                six[dim] = _dim_degraded(dim, "fetch_error", "%s: %s" % (type(exc).__name__, exc))

        any_ok = any(not d.get("degraded") for d in six.values())
        return {
            "ok": any_ok,
            "data": {
                "trigger": trigger,
                "trace_id": trace_id,
                "six_dims": six,
            },
            "source": "l0_context_assembler",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "degraded": not any_ok,
            "meta": {"channel": "in-process"},
        }
    except Exception as exc:
        env = _dim_degraded("all", "fail_open", "%s: %s" % (type(exc).__name__, exc))
        env["data"] = None
        return env
