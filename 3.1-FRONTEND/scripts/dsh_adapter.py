#!/usr/bin/env python3
"""
DSH IPC Adapter — 前端 → DSH 壳层统一入口 (B 方案重构版)。

用法 (完全兼容原格式, 前端 dsh-execution-engine.ts 零改动):
  python3 dsh_adapter.py technical '{"node_output": {...}}'
  python3 dsh_adapter.py c_drive '{"node_id":"C1","confidence":0.8,...}'
  python3 dsh_adapter.py orchestrator '{"node_output": {"symbol": "BTC"}}'

内部路由:
  handler_name → HANDLER_TO_SHELL_ID → call_worker_tool 完整链路
  (mandate_gate → 47 registry → ShellHandleManager → InProcessShell/StdioShell/SshStdioShell)

设计变化 (原 VS 新):
  原: 每个 handler 独立 import python-server 的 handle_* 函数 → 冷启动 → 直接执行
  新: 全部进 ShellHandleManager 单例 → 进程内复用 → 健康检查/自动重拉/retry-degrade

Fail-Open: dsh_frontend_bridge.call_handler 内部异常 → {ok:false, error, meta}
"""

import json
import os
import sys
import traceback


def _resolve_34_core_dir() -> str:
    """解析 34-前端应用训练系统/core 绝对路径 (相对本脚本位置)。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 3.1-FRONTEND/scripts/ → ../../34-前端应用训练系统/core
    candidate = os.path.normpath(
        os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core")
    )
    return candidate


def main():
    # 把 34-core 加进 sys.path (在任何 import 之前)
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    if len(sys.argv) < 2:
        sys.stdout.write(json.dumps({"ok": False, "error": "missing handler_name argument"}) + "\n")
        return

    handler_name = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        sys.stdout.write(json.dumps({"ok": False, "error": f"invalid args JSON: {e}"}) + "\n")
        return

    try:
        from dsh_frontend_bridge import call_handler

        result = call_handler(handler_name, args)
    except Exception as e:
        result = {
            "ok": False,
            "error": f"bridge_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
