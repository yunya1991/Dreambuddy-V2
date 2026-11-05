#!/usr/bin/env python3
"""Shell stats adapter — 桥 ShellHandleManager 运行时监控 (P3 新增)。

用法:
  python3 shell_stats_adapter.py health '{}'     # 壳健康度+明细
  python3 shell_stats_adapter.py stats '{}'      # 壳注册清单+调用计数

输出: {"ok":true,"data":{total_shells,alive,dead,handles_issued,...}}
"""

import json
import os
import sys
import traceback


def _resolve_34_core_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(script_dir, "..", "..", "34-前端应用训练系统", "core"))


def main():
    core_dir = _resolve_34_core_dir()
    if os.path.isdir(core_dir) and core_dir not in sys.path:
        sys.path.insert(0, core_dir)

    command = sys.argv[1] if len(sys.argv) > 1 else "stats"
    args_raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        sys.stdout.write(json.dumps({"ok": False, "error": f"invalid args JSON: {e}"}) + "\n")
        return
    args["command"] = command

    try:
        from dsh_frontend_bridge import call_handler

        result = call_handler("shell_stats", args)
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
