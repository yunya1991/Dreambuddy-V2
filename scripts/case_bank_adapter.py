#!/usr/bin/env python3
"""
TDR IPC Adapter — 单次请求模式调用 case_bank_server 的工具。

用法:
  python3 case_bank_adapter.py store '{"intent":"...","actions":[...],...}'
  python3 case_bank_adapter.py retrieve '{"query":"...","top_k":5}'
  python3 case_bank_adapter.py stats '{}'

stdout: 单行 JSON 响应 {"ok": true, "data": {...}} 或 {"ok": false, "error": "..."}
stderr: 错误日志和 import 噪音（不污染 stdout）

设计:
  - 复刻 cognitive_adapter.py IPC 模式 (VM-1789618914215)
  - FAIL-OPEN: 异常返回 {ok: false, error, traceback}, 不崩溃
  - stdout 行过滤: import 和 handler 执行期间重定向 stdout 到 stderr
"""
import sys
import os
import json
import traceback


def _resolve_server_dir():
    """解析 case_bank_server.py 所在目录。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # case_bank_server.py 在同一 scripts/ 目录
    return script_dir


def _safe_print(payload):
    """唯一向 stdout 输出的入口，确保单行 JSON。"""
    sys.stdout = sys.__stdout__
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def main():
    if len(sys.argv) < 2:
        _safe_print({"ok": False, "error": "missing tool_name argument"})
        return

    tool_name = sys.argv[1]
    args_raw = sys.argv[2] if len(sys.argv) > 2 else '{}'
    try:
        args = json.loads(args_raw) if args_raw else {}
    except json.JSONDecodeError as e:
        _safe_print({"ok": False, "error": f"invalid args JSON: {e}"})
        return

    # === 关键: import 和 handler 执行期间把 stdout 重定向到 stderr ===
    sys.stdout = sys.stderr

    try:
        server_dir = _resolve_server_dir()
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        from case_bank_server import TOOL_HANDLERS  # noqa
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"import_failed: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })
        return

    if tool_name not in TOOL_HANDLERS:
        _safe_print({
            "ok": False,
            "error": f"unknown tool: {tool_name}. available: {sorted(TOOL_HANDLERS.keys())}",
        })
        return

    try:
        result_text = TOOL_HANDLERS[tool_name](args)
        # result_text 是 JSON 字符串, 再 parse 一次拿到结构化数据
        try:
            data = json.loads(result_text)
        except (json.JSONDecodeError, TypeError):
            data = {"raw": result_text}
        _safe_print({"ok": True, "data": data})
    except Exception as e:
        _safe_print({
            "ok": False,
            "error": f"handler_error: {type(e).__name__}: {e}",
            "traceback": traceback.format_exc(),
        })


if __name__ == "__main__":
    main()
