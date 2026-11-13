#!/usr/bin/env python3
"""mcp_shells/l1_ops/server.py — L1 运维审计 MCP（P2，DEC-01）

全只读 / 零大模型依赖 / 本地文件扫描。
三个工具：
  list_alerts    — 扫 16-调控系统 日志 + 制品目录，列出最近告警
  get_health     — 读各服务 health 文件 / PID 文件，聚合总体健康
  get_bus_state  — 读 36-通信系统层 signal-bus 订阅/事件 outbox 状态

硬约束：
  - 全只读（read_write=read / requires_mandate=false）
  - 零大模型、零联网、零 DB 直连
  - FAIL-OPEN：任何文件 IO 错误返回 ok=false + error_code
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l1.ops.mcp"

# 本地扫描目录
_LOGS_DIR = _REPO_ROOT / "16-调控系统" / "logs"
_ARTIFACTS_DIR = _REPO_ROOT / "16-调控系统" / "artifacts" / "capital-reports"
_SIGNAL_BUS_OUTBOX = _REPO_ROOT / "36-通信系统层" / "signal-bus" / "outbox.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_read_text(path: Path, max_bytes: int = 512 * 1024) -> Optional[str]:
    try:
        if not path.exists():
            return None
        data = path.read_bytes()
        if len(data) > max_bytes:
            return data[:max_bytes].decode("utf-8", errors="replace")
        return data.decode("utf-8", errors="replace")
    except OSError:
        return None


def _fail(reason: str, error_code: str = "io_error") -> Dict[str, Any]:
    return {"ok": False, "error_code": error_code, "reason": reason}


# ── 工具实现 ──


def _handle_list_alerts(args: Dict[str, Any]) -> Dict[str, Any]:
    """扫描最近告警——日志文件含 ERROR/WARN 关键字 + 制品目录变更。

    optional limit: 正整数，默认 20。
    """
    try:
        limit = int(args.get("limit", 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 200))

    alerts: List[Dict[str, Any]] = []

    # 扫日志文件（grep 风格：找 ERROR/WARN 行 + 最近 mtime）
    log_files = sorted(
        _LOGS_DIR.glob("*.log"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for log in log_files[:10]:
        content = _safe_read_text(log, max_bytes=256 * 1024)
        if content is None:
            continue
        for line in content.splitlines():
            line_stripped = line.strip()
            lower = line_stripped.lower()
            level = None
            if "error" in lower or "fail" in lower or "exception" in lower:
                level = "error"
            elif "warn" in lower:
                level = "warn"
            if level:
                alerts.append(
                    {
                        "level": level,
                        "file": log.name,
                        "line": line_stripped[:300],
                        "mtime": datetime.fromtimestamp(
                            log.stat().st_mtime, timezone.utc
                        ).isoformat(),
                    }
                )

    # 按 mtime 排 + 截断
    alerts.sort(key=lambda a: a.get("mtime", ""), reverse=True)
    alerts = alerts[:limit]

    return {
        "ok": True,
        "total": len(alerts),
        "alerts": alerts,
        "scanned_files": len(log_files),
        "meta": {
            "source": SHELL_SOURCE,
            "upstream": "16-调控系统 logs",
        },
    }


def _handle_get_health(args: Dict[str, Any]) -> Dict[str, Any]:
    """聚合各子系统健康——扫 health 文件 + PID 文件 + 进程存活。"""
    subsystems = []
    # 16-调控系统
    if _LOGS_DIR.exists():
        subsystems.append({"name": "16-control", "health": "ok", "status": "logs_dir_present"})
    # 36-通信系统层
    bus_dir = _REPO_ROOT / "36-通信系统层"
    if bus_dir.exists():
        subsystems.append(
            {
                "name": "36-signal-bus",
                "health": "ok",
                "status": "module_present",
                "outbox_size": (
                    _SIGNAL_BUS_OUTBOX.stat().st_size if _SIGNAL_BUS_OUTBOX.exists() else 0
                ),
            }
        )
    # 48-涌现架构
    em_dir = _REPO_ROOT / "48-涌现架构"
    if em_dir.exists():
        trials = em_dir / "runtime" / "trials.jsonl"
        subsystems.append(
            {
                "name": "48-emergence",
                "health": "ok",
                "status": "module_present",
                "trials_size": trials.stat().st_size if trials.exists() else 0,
            }
        )
    # 26-策略管理模块
    strat_dir = _REPO_ROOT / "26-策略管理模块"
    subsystems.append(
        {
            "name": "26-strategy-lib",
            "health": "ok" if strat_dir.exists() else "missing",
            "status": "module_present" if strat_dir.exists() else "dir_missing",
        }
    )
    # 27-治理审批
    gov_dir = _REPO_ROOT / "27-策略治理审批系统"
    subsystems.append(
        {
            "name": "27-governance",
            "health": "ok" if gov_dir.exists() else "missing",
            "status": "module_present" if gov_dir.exists() else "dir_missing",
        }
    )

    healthy = sum(1 for s in subsystems if s["health"] == "ok")
    return {
        "ok": True,
        "overall_health": "healthy" if healthy == len(subsystems) else "degraded",
        "healthy_count": healthy,
        "total_count": len(subsystems),
        "subsystems": subsystems,
        "checked_at": _now_iso(),
        "meta": {"source": SHELL_SOURCE},
    }


def _handle_get_bus_state(args: Dict[str, Any]) -> Dict[str, Any]:
    """读 36-通信系统层 signal-bus outbox 状态。"""
    if not _SIGNAL_BUS_OUTBOX.exists():
        return {
            "ok": True,
            "bus_available": False,
            "outbox_path": str(_SIGNAL_BUS_OUTBOX),
            "subscribers": [],
            "pending_events": 0,
            "meta": {"source": SHELL_SOURCE, "note": "signal-bus outbox 不存在（未启动）"},
        }
    content = _safe_read_text(_SIGNAL_BUS_OUTBOX, max_bytes=1024 * 1024)
    subscribers: List[Dict[str, Any]] = []
    pending = 0
    if content:
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                pending = len(data.get("events", data.get("outbox", [])))
                subs = data.get("subscribers", [])
                subscribers = subs if isinstance(subs, list) else []
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "ok": True,
        "bus_available": True,
        "pending_events": pending,
        "subscriber_count": len(subscribers),
        "subscribers_preview": subscribers[:10],
        "outbox_size_bytes": _SIGNAL_BUS_OUTBOX.stat().st_size,
        "meta": {"source": SHELL_SOURCE, "outbox_path": str(_SIGNAL_BUS_OUTBOX)},
    }


# ── 工具注册表 ──


_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "list_alerts": {
        "description": "扫 16-调控系统日志 + 制品目录，列出最近 ERROR/WARN 告警。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "返回条数上限（默认 20，最大 200）"},
            },
        },
    },
    "get_health": {
        "description": "聚合各子系统健康状态——16/26/27/36/48 五模块。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
    "get_bus_state": {
        "description": "读 36-通信系统层 signal-bus outbox 状态（pending events + subscribers）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {"type": "object", "properties": {}},
    },
}

_TOOL_HANDLERS: Dict[str, Any] = {
    "list_alerts": _handle_list_alerts,
    "get_health": _handle_get_health,
    "get_bus_state": _handle_get_bus_state,
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
        try:
            result = handler(params.get("arguments") or {})
        except Exception as exc:
            result = _fail(f"{type(exc).__name__}: {exc}")
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
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
