#!/usr/bin/env python3
"""mcp_shells/l1_stats/server.py — L1 统计能力 MCP（l1.stats.mcp）。

契约：TASKS-20261116 T1-4；上游 SPEC-20261116 §4。
硬约束：
  - **只透传**：4 个工具全部转发给 `python-server` 的 `stats_capability`，壳内不计算、不缓存；
  - 只读：不写库、不落盘、不改注册表；
  - 文件/进程缺失、能力失败 → FAIL-OPEN 为 degraded（`ok=false` + `degraded=true`），不抛异常；
  - stdio JSON-RPC 2.0，按需拉起，不常驻。

工具面（与插件侧一一对应）：
  stats_list / stats_run / stats_validate / stats_explain
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402

SHELL_SOURCE = "l1.stats.mcp"

_SERVER_PATH = Path(
    os.environ.get(
        "DREAMBUDDY_PY_SERVER",
        str(
            _REPO_ROOT
            / "1-ARCHITECTURE"
            / "dream-harness-bridge"
            / "packages"
            / "python-server"
            / "server.py"
        ),
    )
)
_MODULE_NAME = "_dreambuddy_stats_python_server"


def _ipc_module() -> Any:
    """惰性加载 python-server（复用其 `_handle_stats_capability`，不复制逻辑）。"""
    if _MODULE_NAME in sys.modules:
        return sys.modules[_MODULE_NAME]
    if not _SERVER_PATH.exists():
        raise FileNotFoundError(f"python-server not found: {_SERVER_PATH}")
    server_dir = str(_SERVER_PATH.parent)
    if server_dir not in sys.path:
        sys.path.insert(0, server_dir)
    spec = importlib.util.spec_from_file_location(_MODULE_NAME, _SERVER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load python-server: {_SERVER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


def _call(op: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"op": op}
    for key, value in (arguments or {}).items():
        if value is not None:
            params[key] = value
    try:
        server = _ipc_module()
    except Exception as exc:  # noqa: BLE001 — 壳层 fail-open
        return {
            "ok": False,
            "degraded": True,
            "reason": f"l1_unavailable: {type(exc).__name__}: {exc}",
        }
    try:
        return server._handle_stats_capability(params)
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "degraded": True,
            "reason": f"l1_call_failed: {type(exc).__name__}: {exc}",
        }


_ERROR_CODE_MAP = {
    "unknown_capability": "not_found",
    "invalid_params": "invalid",
    "payload_must_be_object": "invalid",
    "unsupported_op": "invalid",
    "capability_id_required": "invalid",
    "timeout": "timeout",
    "l1_unavailable": "unavailable",
    "l1_call_failed": "unavailable",
    "manifest_unavailable": "unavailable",
    "capability_failed": "unavailable",
    "executor_unresolved": "unavailable",
}


def _render(payload: dict[str, Any], tool: str) -> str:
    """统一信封：ok=false → degraded（reason 前缀映射到 SPEC-L0 error_code）。"""
    ok = bool(payload.get("ok", True))
    reason = str(payload.get("reason") or "")
    prefix = reason.split(":", 1)[0] if reason else ""
    meta: dict[str, Any] = {"tool": tool}
    if reason:
        meta["reason"] = reason
    return json.dumps(
        wrap(
            payload,
            SHELL_SOURCE,
            degraded=not ok,
            error_code="" if ok else _ERROR_CODE_MAP.get(prefix, "degraded"),
            meta=meta,
        ),
        ensure_ascii=False,
    )


# ── 4 工具 handlers ─────────────────────────────────────────────


def stats_list(arguments: dict[str, Any]) -> str:
    payload = _call(
        "list",
        {
            "domain": arguments.get("domain"),
            "q": arguments.get("q"),
            "min_n_max": arguments.get("min_n_max"),
            "limit": arguments.get("limit"),
        },
    )
    return _render(payload, "stats_list")


def stats_run(arguments: dict[str, Any]) -> str:
    payload = _call(
        "run",
        {
            "capability_id": arguments.get("capability_id"),
            "payload": arguments.get("payload"),
        },
    )
    return _render(payload, "stats_run")


def stats_validate(arguments: dict[str, Any]) -> str:
    payload = _call(
        "validate",
        {
            "capability_id": arguments.get("capability_id"),
            "payload": arguments.get("payload"),
        },
    )
    return _render(payload, "stats_validate")


def stats_explain(arguments: dict[str, Any]) -> str:
    payload = _call("explain", {"capability_id": arguments.get("capability_id")})
    return _render(payload, "stats_explain")


_TOOLS = [
    {
        "name": "stats_list",
        "description": "列出 L1 统计能力目录（域/意图/最小样本/方法/数据域）；只读 manifest，不执行。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "A/B/E/G/J/K"},
                "q": {"type": "string", "description": "能力 ID、意图或方法号"},
                "min_n_max": {"type": "number"},
                "limit": {"type": "integer", "default": 50, "maximum": 200},
            },
        },
    },
    {
        "name": "stats_run",
        "description": "执行一个 L1 统计能力，返回标准 capability_result（status/data/visual/meta）。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "capability_id": {"type": "string", "description": "如 D-A06 / D-K01"},
                "payload": {"type": "object", "description": "能力入参"},
            },
            "required": ["capability_id"],
        },
    },
    {
        "name": "stats_validate",
        "description": "预检入参是否可执行（不取数）：missing_params / unknown_params / warnings。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {
                "capability_id": {"type": "string"},
                "payload": {"type": "object"},
            },
            "required": ["capability_id"],
        },
    },
    {
        "name": "stats_explain",
        "description": "解释能力口径：方法号、最小样本、数据域、可接受参数、完整 notes。",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "inputSchema": {
            "type": "object",
            "properties": {"capability_id": {"type": "string"}},
            "required": ["capability_id"],
        },
    },
]

_TOOL_HANDLERS = {
    "stats_list": stats_list,
    "stats_run": stats_run,
    "stats_validate": stats_validate,
    "stats_explain": stats_explain,
}


def _handle_request(req: dict[str, Any]) -> dict[str, Any] | None:
    method = req.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": SHELL_SOURCE, "version": "0.1"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": _TOOLS}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        started = time.perf_counter()
        text = handler(params.get("arguments", {}) or {})
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": False,
                "_meta": {"latency_ms": round((time.perf_counter() - started) * 1000.0, 2)},
            },
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                )
                + "\n"
            )
            sys.stdout.flush()
            continue
        resp = _handle_request(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
