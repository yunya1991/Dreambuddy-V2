#!/usr/bin/env python3
"""mcp_shells/l0_eval/server.py — L0 评测壳（M2⑥）

SPEC-L0-MCP-PACKAGING §4 P1 + registry mcp_capabilities.yaml（l0.eval.mcp）
工具面（2 个，注册表登记，均只读）：
  - eval_analyze (read) 查询单次评测状态/结果（GET /api/v1/eval/{eval_id}）
  - eval_report (read) 查询评测指标汇总（GET /api/v1/eval/metrics）

硬约束：
  - 适配层复用 45 评测系统既有 HTTP :8790 服务（PLAN M2⑥/K4），不替代、不绕过
  - 壳内零业务逻辑：协议解析 → HTTP 适配 → 信封映射 三段
  - stdio JSON-RPC 2.0，按需拉起，不常驻
  - 评测提交（submit）不在本壳工具面（写面走 45 HTTP 直连 + Mandate，注册表未登记）
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict

# 壳进程 import 规约（SPEC §3.4）
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mcp_shells._shared.envelope_wrap import wrap  # noqa: E402
from mcp_shells._shared.shadow_hook import observe_envelope  # noqa: E402

SHELL_SOURCE = "l0.eval.mcp"
EVAL_BASE_URL = os.environ.get("EVAL_API_BASE", "http://127.0.0.1:8790").rstrip("/")
API_PREFIX = "/api/v1/eval"


def _http_get(path: str) -> Dict[str, Any]:
    """GET 45 评测系统 HTTP API，返回解析后的 JSON。"""
    url = f"{EVAL_BASE_URL}{path}"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _handle_eval_analyze(args: Dict[str, Any]) -> str:
    """查询单次评测状态/结果。"""
    eval_id = str(args.get("eval_id", "")).strip()
    if not eval_id:
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="invalid",
                meta={"reason": "eval_id is required"},
            ),
            ensure_ascii=False,
        )
    try:
        result = _http_get(f"{API_PREFIX}/{eval_id}")
        return json.dumps(wrap(result, SHELL_SOURCE), ensure_ascii=False)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return json.dumps(
                wrap(
                    None,
                    SHELL_SOURCE,
                    degraded=True,
                    error_code="not_found",
                    meta={"reason": f"eval not found: {eval_id}"},
                ),
                ensure_ascii=False,
            )
        return json.dumps(
            wrap(
                None,
                SHELL_SOURCE,
                degraded=True,
                error_code="unavailable",
                meta={"reason": f"eval api http {e.code}"},
            ),
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


def _handle_eval_report(args: Dict[str, Any]) -> str:
    """查询评测指标汇总。"""
    try:
        result = _http_get(f"{API_PREFIX}/metrics")
        return json.dumps(wrap(result, SHELL_SOURCE), ensure_ascii=False)
    except Exception as e:
        return json.dumps(
            wrap(
                None, SHELL_SOURCE, degraded=True, error_code="unavailable", meta={"reason": str(e)}
            ),
            ensure_ascii=False,
        )


TOOL_HANDLERS = {
    "eval_analyze": _handle_eval_analyze,
    "eval_report": _handle_eval_report,
}


def _handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method", "")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}},
        }
    if method == "tools/list":
        tools = [
            {
                "name": "eval_analyze",
                "description": "Query eval status/result by eval_id (read-only, via 45 HTTP API)",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
            {
                "name": "eval_report",
                "description": "Query eval metrics summary (read-only, via 45 HTTP API)",
                "annotations": {"readOnlyHint": True, "destructiveHint": False},
            },
        ]
        return {"jsonrpc": "2.0", "id": req.get("id"), "result": {"tools": tools}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "error": {"code": -32601, "message": f"Method not found: {name}"},
            }
        result_text = handler(params.get("arguments", {}))
        observe_envelope(result_text)  # COMM-SHADOW 旁路观察（默认关闭，FAIL-OPEN）
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {"content": [{"type": "text", "text": result_text}], "isError": False},
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    }


def main() -> None:
    """stdio 主循环。"""
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
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
