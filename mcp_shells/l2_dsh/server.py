#!/usr/bin/env python3
"""mcp_shells/l2_dsh/server.py — L2-E DSH 编排面只读 MCP（GAP-03 / SPEC-56 P2）

定位：把 L2-E（DSH Router / Ticket / Worker 角色）的状态面暴露给外部宿主。
此前 Worker 编排只有 IPC，外部零可观测（GAP-03）。

三工具（全只读，exposure=readonly-observe）：
  get_router_summary — Router 摘要：Ticket 状态计数 / 漂移 / 最近 Ticket
  get_ticket_status  — Ticket 状态：单票详情（含 history 尾部）或按 state 列表
  get_worker_roster  — Worker 角色：registry worker_roles 白名单 + 越权自检

硬约束：
  - 壳零业务逻辑：Ticket 读取委托 34 core/ticket_store.py（L0 SSoT，
    append-only latest-wins），角色白名单委托 34 core/worker_roles.py
  - 只读：不写 dsh_tickets.jsonl、不投递 inbox、不迁移状态
  - 零 DB 直连、零 LLM 依赖
  - FAIL-OPEN：委托模块不可用 → 统一信封 degraded + error_code=unavailable
  - Router 常驻循环的 pass 统计只在守护进程内存中，壳层不虚构
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l2.dsh.mcp"

# 统一信封必带字段（L2 H6）：ok / data / source / meta / version / trace_id
_ENVELOPE_FIELDS = ("ok", "data", "source", "meta", "version", "trace_id")

_CORE_DIR = _REPO_ROOT / "34-前端应用训练系统" / "core"
_STORE_REL_PATH = Path("34-前端应用训练系统") / "dsh_tickets.jsonl"
_TICKET_STATES = ("live", "paused", "waitsForPerson", "ended")

_MODULE_CACHE: Dict[str, Any] = {}


# ── 委托模块加载（按文件路径，避免 34 目录名 CJK 造成的包名冲突） ──


def _load_core_module(name: str) -> Any:
    cached = _MODULE_CACHE.get(name)
    if cached is not None:
        return cached
    path = _CORE_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"dsh_core_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _MODULE_CACHE[name] = module
    return module


def _l0_root() -> Path:
    """L0 根目录：DREAMBUDDY_L0_ROOT 覆盖，默认仓库根（与 L0Foundation 一致）。"""
    return Path(os.environ.get("DREAMBUDDY_L0_ROOT") or _REPO_ROOT)


def _store_path() -> Path:
    return _l0_root() / _STORE_REL_PATH


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: Any, default: int, upper: int) -> int:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(num, upper))


def _degraded(reason: str, upstream: str) -> Dict[str, Any]:
    return wrap(
        None,
        SHELL_SOURCE,
        degraded=True,
        error_code="unavailable",
        meta={"reason": reason, "upstream": upstream, "observed_at": _now_iso()},
    )


def _read_tickets() -> Dict[str, Dict[str, Any]]:
    """从 L0 快照恢复 Ticket（latest-wins）。委托 ticket_store.recover_tickets。"""
    module = _load_core_module("ticket_store")
    store = module.JsonlTicketStore(str(_l0_root()))
    return module.recover_tickets(store) or {}


def _state_counts(tickets: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"total": 0, "live": 0, "paused": 0, "waitsForPerson": 0, "ended": 0}
    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue
        counts["total"] += 1
        state = ticket.get("state")
        if state in counts:
            counts[state] += 1
    return counts


def _ticket_brief(ticket: Dict[str, Any], history_tail: int = 0) -> Dict[str, Any]:
    brief: Dict[str, Any] = {
        "ticket_id": ticket.get("ticket_id"),
        "state": ticket.get("state"),
        "worker_id": ticket.get("worker_id"),
        "thread_id": ticket.get("thread_id"),
        "trace_id": ticket.get("trace_id"),
        "external_ref": ticket.get("external_ref"),
        "paused_reason": ticket.get("paused_reason"),
        "stored_at": ticket.get("stored_at"),
    }
    history = ticket.get("history")
    if isinstance(history, list):
        brief["history_count"] = len(history)
        if history_tail > 0:
            brief["history_tail"] = history[-history_tail:]
    return brief


# ── 工具实现 ──


def _handle_get_router_summary(args: Dict[str, Any]) -> Dict[str, Any]:
    """Router 摘要：Ticket 状态计数 + 漂移（live 无 worker）+ 最近 Ticket。"""
    limit = _clamp(args.get("limit"), default=20, upper=200)
    upstream = "34-前端应用训练系统/core/ticket_store.py"
    try:
        tickets = _read_tickets()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return _degraded(f"{type(exc).__name__}: {exc}", upstream)

    ordered = sorted(
        tickets.values(),
        key=lambda t: float(t.get("stored_at") or 0) if isinstance(t, dict) else 0.0,
        reverse=True,
    )
    drift = [
        str(t.get("ticket_id"))
        for t in ordered
        if t.get("state") == "live" and not t.get("worker_id")
    ]
    store = _store_path()
    return wrap(
        {
            "counts": _state_counts(ordered),
            "drift": drift[:limit],
            "drift_total": len(drift),
            "recent_tickets": [_ticket_brief(t) for t in ordered[:limit]],
            "store_file": str(store),
            "store_exists": store.exists(),
            "observed_at": _now_iso(),
        },
        SHELL_SOURCE,
        meta={
            "upstream": upstream,
            "loop_pass_stats": "in_process_only_unavailable",
            "note": "Router 常驻循环的 pass 统计仅存于守护进程内存，壳层不虚构",
        },
    )


def _handle_get_ticket_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Ticket 状态：单票详情（含 history 尾部）或按 state 过滤列表。"""
    upstream = "34-前端应用训练系统/core/ticket_store.py"
    ticket_id = args.get("ticket_id")
    state = args.get("state")
    limit = _clamp(args.get("limit"), default=20, upper=200)

    if ticket_id is not None and not isinstance(ticket_id, str):
        bad = wrap(
            None,
            SHELL_SOURCE,
            degraded=True,
            error_code="invalid",
            meta={"reason": "ticket_id 必须是字符串", "upstream": upstream},
        )
        return bad
    if state is not None and state not in _TICKET_STATES:
        return wrap(
            None,
            SHELL_SOURCE,
            degraded=True,
            error_code="invalid",
            meta={
                "reason": f"state 必须是 {list(_TICKET_STATES)} 之一",
                "upstream": upstream,
            },
        )

    try:
        tickets = _read_tickets()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return _degraded(f"{type(exc).__name__}: {exc}", upstream)

    if ticket_id:
        ticket = tickets.get(ticket_id.strip())
        if ticket is None:
            return wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="not_found",
                meta={"reason": f"ticket_id={ticket_id!r} 不存在", "upstream": upstream},
            )
        return wrap(
            {"ticket": _ticket_brief(ticket, history_tail=5)},
            SHELL_SOURCE,
            meta={"upstream": upstream, "observed_at": _now_iso()},
        )

    ordered = sorted(
        tickets.values(),
        key=lambda t: float(t.get("stored_at") or 0) if isinstance(t, dict) else 0.0,
        reverse=True,
    )
    matched = [t for t in ordered if state is None or t.get("state") == state]
    return wrap(
        {
            "state_filter": state,
            "matched_total": len(matched),
            "tickets": [_ticket_brief(t) for t in matched[:limit]],
            "observed_at": _now_iso(),
        },
        SHELL_SOURCE,
        meta={"upstream": upstream},
    )


def _handle_get_worker_roster(args: Dict[str, Any]) -> Dict[str, Any]:
    """Worker 角色：registry worker_roles 白名单 + RolePolicy 越权自检。"""
    upstream = "47-MCP管理系统/registry/mcp_capabilities.yaml#worker_roles"
    try:
        module = _load_core_module("worker_roles")
        roles = module.load_worker_roles() or {}
        problems = module.RolePolicy(roles).validate()
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        return _degraded(f"{type(exc).__name__}: {exc}", upstream)

    items: List[Dict[str, Any]] = []
    for role, config in sorted(roles.items()):
        if not isinstance(config, dict):
            items.append({"role": role, "invalid": True})
            continue
        shells = list(config.get("shells") or [])
        tools = list(config.get("tools") or [])
        items.append(
            {
                "role": role,
                "shells": shells,
                "tools": tools,
                "tool_count": len(tools),
            }
        )
    return wrap(
        {
            "role_count": len(roles),
            "roles": items,
            "problems": problems,
            "observed_at": _now_iso(),
        },
        SHELL_SOURCE,
        meta={"upstream": upstream, "readonly": True},
    )


# ── 工具注册表 ──


_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "get_router_summary": {
        "description": "Router 摘要：Ticket 状态计数 / 漂移（live 无 worker）/ 最近 Ticket。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "default 20, max 200"},
            },
        },
    },
    "get_ticket_status": {
        "description": "Ticket 状态：单票详情（含 history 尾部）或按 state 过滤列表。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "ticket_id": {"type": "string", "description": "Ticket 主键（可选）"},
                "state": {
                    "type": "string",
                    "description": "live / paused / waitsForPerson / ended（可选）",
                },
                "limit": {"type": "integer", "description": "default 20, max 200"},
            },
        },
    },
    "get_worker_roster": {
        "description": "Worker 角色：registry worker_roles 白名单 + 越权/写工具自检。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
}

_TOOL_HANDLERS: Dict[str, Any] = {
    "get_router_summary": _handle_get_router_summary,
    "get_ticket_status": _handle_get_ticket_status,
    "get_worker_roster": _handle_get_worker_roster,
}

_TOOL_LIST: List[Dict[str, Any]] = [
    {
        "name": name,
        "description": defs["description"],
        "inputSchema": defs["inputSchema"],
        "annotations": defs.get("annotations", {}),
    }
    for name, defs in _TOOL_DEFS.items()
]


def _handle_request(req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """测试入口：单参数 JSON-RPC 分发。"""
    method = req.get("method", "")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": SHELL_SOURCE, "version": "0.1"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _TOOL_LIST}}

    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name", "")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        envelope = handler(params.get("arguments") or {})
        text = envelope if isinstance(envelope, str) else json.dumps(envelope, ensure_ascii=False)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": text}], "isError": False},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, _TOOL_DEFS, _TOOL_HANDLERS)
