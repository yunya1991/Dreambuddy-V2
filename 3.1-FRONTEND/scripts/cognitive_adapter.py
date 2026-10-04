#!/usr/bin/env python3
"""
认知系统 HTTP Adapter — 单次请求模式调用 cognitive_mcp_server 的 5 个工具。

用法:
  python3 cognitive_adapter.py recall '{"context":"test","top_k":3,"min_quality":"C"}'

stdout: 单行 JSON 响应 {"ok": true, "data": {...}} 或 {"ok": false, "error": "..."}
stderr: 错误日志和 import 噪音（不污染 stdout）

设计:
  - 复刻 dream-harness-bridge P0-5 IPC 模式 (VM-1789618914215)
  - FAIL-OPEN: 异常返回 {ok: false, error, traceback}, 不崩溃
  - stdout 行过滤: import 和 handler 执行期间重定向 stdout 到 stderr
  - 不改 4-MEMORY 后端, 仅在 3.1-FRONTEND 接入层新增 adapter
"""
import sys
import os
import json
import traceback


def _resolve_mcp_dir():
    """解析 4-MEMORY/9-工具与接口 绝对路径，支持多种 cwd。"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # 路径 1: 3.1-FRONTEND/scripts/ → ../../4-MEMORY/9-工具与接口
    candidate1 = os.path.normpath(os.path.join(script_dir, '..', '..', '4-MEMORY', '9-工具与接口'))
    if os.path.exists(candidate1):
        return candidate1
    # 路径 2: 仓库根绝对路径（fallback）
    candidate2 = '/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/4-MEMORY/9-工具与接口'
    if os.path.exists(candidate2):
        return candidate2
    return candidate1  # 返回不存在的路径，让 import 报错


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
    # 避免任何 import 噪音或 handler 内部 print 污染真 stdout
    sys.stdout = sys.stderr

    try:
        mcp_dir = _resolve_mcp_dir()
        if mcp_dir not in sys.path:
            sys.path.insert(0, mcp_dir)
        from cognitive_mcp_server import TOOL_HANDLERS  # noqa
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
