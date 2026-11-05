#!/usr/bin/env python3
"""
认知系统 HTTP Adapter — 单次请求模式调用认知 MCP 壳 (B 方案重构版)。

用法 (完全兼容原格式):
  python3 cognitive_adapter.py recall '{"context":"test","top_k":3,"min_quality":"C"}'
  python3 cognitive_adapter.py record '{"content":"经验","quality_level":"B","tags":"tag1"}'
  python3 cognitive_adapter.py verify '{"memory_id":"VM-xxx","success":true}'
  python3 cognitive_adapter.py stats '{}'
  python3 cognitive_adapter.py health '{}'

内部路由:
  tool_name → call_tool('research', tool_name, args) 完整链路
  → ShellHandleManager → StdioShell(fake_mode/ssh-stdio) → cognitive_mcp_server

壳复用: 进程内首次拉起后复用 (ADR-10), 后续 call 不重复 Popen
健康检查: HC-4 is_alive(), HC-6 transport fail 自动重拉 retry, HC-7 degrade

Fail-Open: dsh_frontend_bridge.call_tool 内部兜底
"""

import json
import os
import sys
import traceback


def _resolve_34_core_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core"))


# 认知 MCP 壳 shell_id + 默认角色
_SHELL_ID = "l0.cognition.mcp"
_DEFAULT_ROLE = "research"


# 47 registry 里认知壳的 6 个工具
_COGNITIVE_TOOLS = {"recall", "unified_search", "record", "verify", "stats", "health"}


def _safe_print(payload):
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def main():
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    if len(sys.argv) < 2:
        _safe_print(
            {
                "ok": False,
                "error": "missing tool_name argument",
                "available": sorted(_COGNITIVE_TOOLS),
            }
        )
        return

    tool_name = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
        return

    sys.stdout = sys.stderr

    try:
        from dsh_frontend_bridge import call_tool

        if tool_name not in _COGNITIVE_TOOLS:
            _safe_print(
                {
                    "ok": False,
                    "error": f"unknown cognitive tool: {tool_name}",
                    "available": sorted(_COGNITIVE_TOOLS),
                }
            )
            return
        result = call_tool(_DEFAULT_ROLE, tool_name, args)
    except Exception as e:
        result = {
            "ok": False,
            "error": f"bridge_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    # 适配前端现有消费格式: {ok:true, data:{...}} 或 {ok:false, error:"..."}
    if isinstance(result, dict):
        if result.get("ok") is False:
            _safe_print(result)
            return
        data = result.get("data")
        _safe_print({"ok": True, "data": data if data is not None else result.get("output")})
    else:
        _safe_print({"ok": True, "data": result})


if __name__ == "__main__":
    main()
