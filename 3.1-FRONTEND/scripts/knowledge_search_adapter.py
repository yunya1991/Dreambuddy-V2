#!/usr/bin/env python3
"""知识库检索 HTTP Adapter — 薄 wrapper, 全部逻辑下放到 dsh_frontend_bridge 统一壳层。

用法 (兼容原格式):
  python3 knowledge_search_adapter.py search '{"query":"BTC", "top_k":5, "method":"hybrid"}'

后端链路:
  call_handler('knowledge_search', {query, top_k, method})
  → ShellHandleManager → knowledge.search (InProcessShell)
  → _handle_knowledge_search → rag_engine (fts/vector/hybrid)
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

    # 合并 command 到 args (handler 期望 {"query","top_k","method"})
    bridge_args = dict(args)
    if command == "search":
        # search 命令不需要额外包装, args 里已有 query/top_k/method
        pass
    else:
        bridge_args["command"] = command

    try:
        from dsh_frontend_bridge import call_handler

        result = call_handler("knowledge_search", bridge_args)
    except Exception as e:
        result = {
            "ok": False,
            "error": f"bridge_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        }

    # 适配前端消费格式 {ok:true, data:{results, method, degraded}}
    if result.get("ok") is False:
        sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        return
    data = result.get("data") or result.get("output") or result.get("result")
    if isinstance(data, dict) and "results" in data:
        sys.stdout.write(
            json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str) + "\n"
        )
    elif isinstance(result, dict) and "output" in result:
        sys.stdout.write(
            json.dumps({"ok": True, "data": result["output"]}, ensure_ascii=False, default=str)
            + "\n"
        )
    else:
        sys.stdout.write(
            json.dumps({"ok": True, "data": data}, ensure_ascii=False, default=str) + "\n"
        )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
