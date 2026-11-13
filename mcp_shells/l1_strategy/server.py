#!/usr/bin/env python3
"""mcp_shells/l1_strategy/server.py — L1 策略层 MCP（P1-A，DEC-01）

只读 / 无大模型依赖 / 封装 25-28 端口 Flask 服务的 HTTP 端点。
壳三段：协议解析 → HTTP 调用 → 信封映射。

前置依赖（4 个本地 Flask 服务）：
  - 26-策略管理模块  port 8093
  - 27-策略治理审批系统 port 8094
  - 28-策略信号触发模块 port 8096

壳零业务逻辑：HTTP 返回什么就透传什么，不做二次加工。
服务不可达 → FAIL-OPEN：ok=false, error_code="unavailable"。

硬约束：
  - 全只读（read_write=read / requires_mandate=false）
  - 无大模型调用、不直连 DB、不联网（仅 localhost HTTP）
  - 所有 handler 异常 FAIL-OPEN（不抛到外层）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.shell_runtime import run_stdio  # noqa: E402

SHELL_SOURCE = "l1.strategy.mcp"

# ── 服务地址（可 env 覆盖） ──
_STRATEGY_LIB_BASE = os.environ.get("STRATEGY_LIB_BASE", "http://127.0.0.1:8093")
_GOVERNANCE_BASE = os.environ.get("GOVERNANCE_BASE", "http://127.0.0.1:8094")
_SIGNAL_TRIGGER_BASE = os.environ.get("SIGNAL_TRIGGER_BASE", "http://127.0.0.1:8096")

_HTTP_TIMEOUT_SEC = float(os.environ.get("L1_STRATEGY_HTTP_TIMEOUT", "3.0"))


# ── 辅助：HTTP GET（FAIL-OPEN） ──


def _http_get(url: str) -> Dict[str, Any]:
    """HTTP GET → 返回 parsed JSON dict。FAIL-OPEN：网络/解析失败返回 ok=false。"""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict):
                return data
            return {"ok": True, "data": data}
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return {
            "ok": False,
            "error_code": "http_error",
            "reason": f"HTTP {exc.code}: {body[:200]}",
            "meta": {"url": url},
        }
    except urllib.error.URLError as exc:
        return {
            "ok": False,
            "error_code": "unavailable",
            "reason": f"服务不可达: {exc.reason}",
            "meta": {"url": url},
        }
    except (json.JSONDecodeError, Exception) as exc:
        return {
            "ok": False,
            "error_code": "parse_error",
            "reason": str(exc),
            "meta": {"url": url},
        }


# ── 工具实现 ──


def _handle_list_strategies(args: Dict[str, Any]) -> Dict[str, Any]:
    """列出所有中台策略（26-策略管理模块 GET /api/v1/lib/strategies）。

    optional scope: "all" | "active" | "archived"（若后端支持）。
    """
    scope = (args.get("scope") or "all").lower()
    url = f"{_STRATEGY_LIB_BASE}/api/v1/lib/strategies"
    if scope != "all":
        url += f"?scope={scope}"
    result = _http_get(url)
    if result.get("ok") is False:
        return result
    # 后端可能返回 {"ok": True, "entries": [...]} 或直接 list
    entries = result.get("entries", result if isinstance(result, list) else [])
    return {
        "ok": True,
        "total": len(entries) if isinstance(entries, list) else 0,
        "strategies": entries if isinstance(entries, list) else [],
        "meta": {
            "source": "l1.strategy.mcp",
            "upstream": "26-策略管理模块",
            "endpoint": "/api/v1/lib/strategies",
        },
    }


def _handle_get_strategy_version(args: Dict[str, Any]) -> Dict[str, Any]:
    """按 strategy_id 查策略详情（26-策略管理模块 GET /api/v1/lib/strategies/<id>）。"""
    sid = args.get("strategy_id") or args.get("id") or ""
    if not isinstance(sid, str) or not sid.strip():
        return {
            "ok": False,
            "error_code": "invalid",
            "reason": "strategy_id 必须是非空字符串",
        }
    url = f"{_STRATEGY_LIB_BASE}/api/v1/lib/strategies/{sid.strip()}"
    result = _http_get(url)
    if result.get("ok") is False:
        return result
    return {
        "ok": True,
        "strategy_id": sid.strip(),
        "strategy": result,
        "meta": {
            "source": "l1.strategy.mcp",
            "upstream": "26-策略管理模块",
            "endpoint": f"/api/v1/lib/strategies/{sid.strip()}",
        },
    }


def _handle_get_approval_state(args: Dict[str, Any]) -> Dict[str, Any]:
    """查策略治理流水线状态（27-策略治理审批系统 GET /api/v1/pipeline/state/<trace_id>）。"""
    trace_id = args.get("trace_id") or args.get("strategy_id") or ""
    if not isinstance(trace_id, str) or not trace_id.strip():
        return {
            "ok": False,
            "error_code": "invalid",
            "reason": "trace_id 必须是非空字符串",
        }
    url = f"{_GOVERNANCE_BASE}/api/v1/pipeline/state/{trace_id.strip()}"
    result = _http_get(url)
    if result.get("ok") is False:
        return result
    return {
        "ok": True,
        "trace_id": trace_id.strip(),
        "pipeline_state": result,
        "meta": {
            "source": "l1.strategy.mcp",
            "upstream": "27-策略治理审批系统",
            "endpoint": f"/api/v1/pipeline/state/{trace_id.strip()}",
        },
    }


def _handle_list_signal_triggers(args: Dict[str, Any]) -> Dict[str, Any]:
    """列最近 webhook signal 事件（28-策略信号触发模块 GET /api/v1/webhook/events）。

    optional limit: 正整数，默认 50。
    """
    limit = args.get("limit")
    try:
        limit_int = int(limit) if limit is not None else 50
    except (TypeError, ValueError):
        limit_int = 50
    limit_int = max(1, min(limit_int, 500))

    url = f"{_SIGNAL_TRIGGER_BASE}/api/v1/webhook/events?limit={limit_int}"
    result = _http_get(url)
    if result.get("ok") is False:
        return result
    events = result.get("events", result if isinstance(result, list) else [])
    return {
        "ok": True,
        "total": len(events) if isinstance(events, list) else 0,
        "events": events if isinstance(events, list) else [],
        "meta": {
            "source": "l1.strategy.mcp",
            "upstream": "28-策略信号触发模块",
            "endpoint": "/api/v1/webhook/events",
            "limit": limit_int,
        },
    }


# ── 工具注册表 ──


_TOOL_DEFS: Dict[str, Dict[str, Any]] = {
    "list_strategies": {
        "description": "列出所有中台策略（26-策略管理模块 GET /api/v1/lib/strategies）；纯只读，FAIL-OPEN。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "description": "可选过滤：all | active | archived（默认 all）",
                },
            },
        },
    },
    "get_strategy_version": {
        "description": "按 strategy_id 查策略详情（版本、参数、事件），零写入。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "strategy_id": {"type": "string", "description": "策略唯一 ID"},
            },
            "required": ["strategy_id"],
        },
    },
    "get_approval_state": {
        "description": "查策略治理流水线 C0-C8 状态（27-治理审批系统），只读。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "治理流水线 trace_id"},
            },
            "required": ["trace_id"],
        },
    },
    "list_signal_triggers": {
        "description": "列最近 Freqtrade webhook signal 事件（28-信号触发模块），只读。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限（默认 50，最大 500）",
                },
            },
        },
    },
}

_TOOL_HANDLERS: Dict[str, Any] = {
    "list_strategies": _handle_list_strategies,
    "get_strategy_version": _handle_get_strategy_version,
    "get_approval_state": _handle_get_approval_state,
    "list_signal_triggers": _handle_list_signal_triggers,
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
    """测试入口：单参数 JSON-RPC 分发（同 l1_intent / l1_trading 模式）。"""
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
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": _TOOL_LIST},
        }

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
        result = handler(params.get("arguments") or {})
        text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
            },
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


if __name__ == "__main__":
    run_stdio(SHELL_SOURCE, _TOOL_DEFS, _TOOL_HANDLERS)
