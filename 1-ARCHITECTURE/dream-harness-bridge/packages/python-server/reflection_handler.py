#!/usr/bin/env python3
"""F-10: Python 侧反思维决策处理器

DreamBuddy C 层反思维决策机制的 5 种决策:
- CONTINUE: 继续执行下一步
- REDO: 重新执行当前步骤
- INSERT_BEFORE: 在当前步骤前插入新步骤
- JUMP_TO: 跳转到指定步骤
- EARLY_TERMINATE: 提前终止

F-10 要求: 这些反思维决策在 TS<->Python IPC 翻译后语义等价。
本模块作为独立模块, 不修改已有 server.py。

来源: SPEC v0.3 七补.1 F-10
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Tuple

# 合法决策枚举（与 TS 侧 VALID_DECISIONS 保持一致）
VALID_DECISIONS: List[str] = [
    "CONTINUE",
    "REDO",
    "INSERT_BEFORE",
    "JUMP_TO",
    "EARLY_TERMINATE",
]

# 需要 target_step 的决策
DECISIONS_REQUIRING_TARGET_STEP: List[str] = ["INSERT_BEFORE", "JUMP_TO"]


class ReflectionDecisionError(ValueError):
    """反思维决策错误"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


def handle_reflection(decision: str, params: dict) -> dict:
    """处理反思维决策（简化版 echo, 验证语义等价性）

    Args:
        decision: 决策类型 (CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE)
        params: 决策参数 (可能含 target_step, reason 等)

    Returns:
        {"decision": str, "executed": bool, "params": dict}

    Raises:
        ReflectionDecisionError: 非法决策或缺少必要参数
    """
    if decision not in VALID_DECISIONS:
        raise ReflectionDecisionError(
            "INVALID_DECISION",
            f"非法反思维决策: {decision} (合法值: {'/'.join(VALID_DECISIONS)})",
        )

    if decision in DECISIONS_REQUIRING_TARGET_STEP:
        if "target_step" not in params or params.get("target_step") is None:
            raise ReflectionDecisionError(
                "MISSING_TARGET_STEP",
                f"{decision} 需要 target_step 参数",
            )

    # 简化版 echo: 验证语义等价性
    # 真实场景下这里会调用 DreamBuddy C 层的反思维决策执行器
    return {
        "decision": decision,
        "executed": True,
        "params": params,
    }


def handle_reflection_safe(
    decision: str, params: dict
) -> Tuple[bool, dict]:
    """安全版反思维决策处理（不抛异常）

    Returns:
        (ok, result_or_error)
        ok=True  -> result = {"decision", "executed", "params"}
        ok=False -> result = {"code", "message"}
    """
    try:
        result = handle_reflection(decision, params)
        return True, result
    except ReflectionDecisionError as e:
        return False, {"code": e.code, "message": e.message}


def _cli_main() -> int:
    """CLI 入口: 接收 JSON 参数, 输出 JSON 结果

    用法:
        python3 reflection_handler.py '{"decision": "CONTINUE", "params": {}}'
        python3 reflection_handler.py '{"decision": "INSERT_BEFORE", "params": {"target_step": 3}}'
        python3 reflection_handler.py '{"decision": "INVALID", "params": {}}'
    """
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": {"code": "MISSING_ARG", "message": "用法: python3 reflection_handler.py '<json>'"}}))
        return 1

    try:
        arg = json.loads(sys.argv[1])
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": {"code": "INVALID_JSON", "message": str(e)}}))
        return 1

    decision = arg.get("decision", "")
    params = arg.get("params", {})

    ok, result = handle_reflection_safe(decision, params)
    if ok:
        print(json.dumps({"ok": True, "result": result}, ensure_ascii=False))
    else:
        print(json.dumps({"ok": False, "error": result}, ensure_ascii=False))
    # 始终返回 0 — JSON 的 ok 字段表示域级成功/失败，退出码仅表示进程是否正常
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
