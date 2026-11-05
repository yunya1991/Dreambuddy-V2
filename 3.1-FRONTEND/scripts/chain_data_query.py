#!/usr/bin/env python3
"""Chain data adapter — 薄 wrapper, 全部逻辑下放到 dsh_frontend_bridge data.dal_query 壳。

用法 (兼容原格式, 零前端 route 改动):
  python3 chain_data_query.py
  python3 chain_data_query.py '{}'

后端链路: call_tool('research', 'data.dal_query', {command:'chain'}) → SQLite mm_metrics
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

    # bridge call 期间把 stdout 重定向到 stderr, 避免 import 噪音污染
    sys.stdout = sys.stderr
    try:
        from dsh_frontend_bridge import call_tool

        result = call_tool("research", "data.dal_query", {"command": "chain"})
    except Exception as e:
        result = {
            "ok": False,
            "error": f"bridge_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    # 恢复 stdout
    sys.stdout = sys.__stdout__
    if result.get("ok") is False:
        output = {"degraded": True, "error": result.get("error_code", "unknown")}
    else:
        output = result.get("data", {}) or {}
        output.setdefault("degraded", False)
    sys.stdout.write(json.dumps(output, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
