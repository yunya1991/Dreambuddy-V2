#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fake MCP server：复刻 mcp_shells/*/server.py 的真实线协议供测试使用。

协议 = 行分隔 JSON-RPC 2.0：
  initialize → {"protocolVersion": ..., "serverInfo": ...}
  tools/call → result.content[0].text = 统一信封 JSON 串
    - echo_tool:    回显 tool/args（ok=true）
    - failing_tool: 处理器级失败（isError=true + 信封 ok=false/error_code=unavailable）
    - 其他工具名:    JSON-RPC error -32601
    - args.__sleep_ms: 响应前 sleep（供超时测试）
  未知 method → JSON-RPC error -32601
stdin EOF 即退出（宿主 close() 关 stdin 后进程自然终止）。
"""

import json
import sys
import time


def _envelope(ok, data=None, error_code=None, degraded=False):
    return {
        "ok": ok,
        "data": data,
        "source": "fake.mcp",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "degraded": degraded,
        "meta": {},
        "version": "v1",
        "trace_id": None,
        "idempotency_key": None,
        "error_code": error_code,
    }


def _tool_result(envelope, is_error=False):
    return {
        "content": [{"type": "text", "text": json.dumps(envelope, ensure_ascii=False)}],
        "isError": is_error,
    }


def _handle(req):
    method = req.get("method")
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "fake-mcp", "version": "0.0.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "tools/call":
        params = req.get("params") or {}
        name = params.get("name") or ""
        args = params.get("arguments") or {}
        sleep_ms = args.pop("__sleep_ms", 0) if isinstance(args, dict) else 0
        if sleep_ms:
            time.sleep(float(sleep_ms) / 1000.0)
        if name == "echo_tool":
            env = _envelope(True, {"tool": name, "args": args})
            return {"jsonrpc": "2.0", "id": req.get("id"), "result": _tool_result(env)}
        if name == "failing_tool":
            env = _envelope(False, None, error_code="unavailable", degraded=True)
            return {
                "jsonrpc": "2.0",
                "id": req.get("id"),
                "result": _tool_result(env, is_error=True),
            }
        return {
            "jsonrpc": "2.0",
            "id": req.get("id"),
            "error": {"code": -32601, "message": f"unknown tool: {name}"},
        }
    return {
        "jsonrpc": "2.0",
        "id": req.get("id"),
        "error": {"code": -32601, "message": f"unknown method: {method}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            resp = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            }
        else:
            resp = _handle(req)
        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
