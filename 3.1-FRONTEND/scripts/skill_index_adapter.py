#!/usr/bin/env python3
"""Skill 索引 HTTP Adapter — 薄 wrapper, 全部逻辑下放到 dsh_frontend_bridge 统一壳层。

用法 (兼容原格式):
  python3 skill_index_adapter.py list '{}'
  python3 skill_index_adapter.py query '{"trigger":"recall","category":"memory"}'
  python3 skill_index_adapter.py drift '{}'
  python3 skill_index_adapter.py conflicts '{}'
  python3 skill_index_adapter.py stats '{}'

后端链路:
  call_handler('skill_index', {command, trigger?, category?, status?})
  → ShellHandleManager → skill.index (InProcessShell)
  → _handle_skill_index → skill_indexer (scan_skills/build_registry)
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

    if len(sys.argv) < 2:
        sys.stdout.write(json.dumps({"ok": False, "error": "missing command"}) + "\n")
        return

    command = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else "{}"
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        sys.stdout.write(json.dumps({"ok": False, "error": f"invalid args JSON: {e}"}) + "\n")
        return

    # bridge 期望 {"command":"list", "trigger":..., "category":..., "status":...}
    bridge_args = dict(args)
    bridge_args["command"] = command

    try:
        from dsh_frontend_bridge import call_handler

        result = call_handler("skill_index", bridge_args)
    except Exception as e:
        result = {
            "ok": False,
            "error": f"bridge_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    if result.get("ok") is False:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        return
    data = result.get("data") or result.get("output")
    sys.stdout.write(json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
