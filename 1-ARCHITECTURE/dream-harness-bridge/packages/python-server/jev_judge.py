#!/usr/bin/env python3
"""Jev (TypeSafe System One Model) 决策判断封装层

将 TypeSafe Jev 的三种原语（noul/choice/score）封装为统一的 judge 接口，
供 dream-harness-bridge 的 IPC handler 调用。

接口契约复用社区 anasbekheit/typesafe-jev-mcp 的 evaluate 格式：
    Request:  {state, questions: {name: {type, instructions, criteria}}}
    Response: {model, answers: {name: {type, noul|choice|score, ...}}, usage}

设计原则:
    - FAIL-OPEN: 任何异常返回 degraded=True，不阻塞调用方
    - HC-9: 只做通用判断（是否完成/路由/质量），不做交易决策
    - HC-5: 绝不返回 reward 字段
    - 优先官方 SDK (typesafe-sdk)，未安装时 fallback 到 urllib 直调 HTTP API（零依赖）
    - 惰性 import: SDK 在调用时才 import，避免模块级依赖

来源: Jev 引入调研（2026-09-22）
"""

from __future__ import annotations

import json
import os
import time
import traceback
import urllib.error
import urllib.request
from typing import Any

# 复用 server.py 的 _send_stderr（结构化日志）
try:
    from server import _send_stderr
except ImportError:
    import sys

    def _send_stderr(level: str, msg: str) -> None:  # type: ignore[no-redef]
        sys.stderr.write(f"[{level}] {msg}\n")


# ============================================================
# 配置
# ============================================================

# 功能开关（默认关闭，1=开启）
ENABLE_JEV_JUDGE = os.environ.get("ENABLE_JEV_JUDGE", "0") == "1"

# API 配置
TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
TYPESAFE_BASE_URL = os.environ.get(
    "TYPESAFE_BASE_URL", "https://api.typesafe.ai"
).rstrip("/")
TYPESAFE_DEFAULT_MODEL = os.environ.get("TYPESAFE_DEFAULT_MODEL", "jev-latest")
TYPESAFE_TIMEOUT_S = float(os.environ.get("TYPESAFE_TIMEOUT_S", "10"))

# Jev 原语限制
MAX_CHOICE_OPTIONS = 255
MAX_SCORE_LEVELS = 10

# 合法的问题类型
_VALID_QUESTION_TYPES = ("noul", "choice", "score")


# ============================================================
# 输入校验
# ============================================================

def _validate_questions(questions: dict[str, Any]) -> list[str]:
    """校验 questions 格式合法性

    返回错误列表（空列表=合法）。
    校验项:
        1. questions 非空 dict
        2. 每个 question 有 type 字段且为 noul/choice/score
        3. choice 必须有 criteria (dict, 1~255 项)
        4. score 必须有 criteria (list, 2~10 项)
    """
    errors: list[str] = []

    if not isinstance(questions, dict) or not questions:
        return ["questions must be a non-empty dict"]

    for name, q in questions.items():
        if not isinstance(q, dict):
            errors.append(f"question '{name}' must be a dict")
            continue

        qtype = q.get("type")
        if qtype not in _VALID_QUESTION_TYPES:
            errors.append(
                f"question '{name}' has invalid type '{qtype}' "
                f"(must be one of {_VALID_QUESTION_TYPES})"
            )
            continue

        if not q.get("instructions"):
            errors.append(f"question '{name}' missing 'instructions'")

        if qtype == "choice":
            criteria = q.get("criteria")
            if not isinstance(criteria, dict) or not criteria:
                errors.append(f"question '{name}' (choice) requires non-empty dict criteria")
            elif len(criteria) > MAX_CHOICE_OPTIONS:
                errors.append(
                    f"question '{name}' (choice) has {len(criteria)} options, "
                    f"max is {MAX_CHOICE_OPTIONS}"
                )

        elif qtype == "score":
            criteria = q.get("criteria")
            if not isinstance(criteria, list) or not criteria:
                errors.append(f"question '{name}' (score) requires non-empty list criteria")
            elif len(criteria) > MAX_SCORE_LEVELS:
                errors.append(
                    f"question '{name}' (score) has {len(criteria)} levels, "
                    f"max is {MAX_SCORE_LEVELS}"
                )

    return errors


# ============================================================
# API 调用（SDK 优先，urllib fallback）
# ============================================================

def _call_via_sdk(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """通过官方 typesafe-sdk 调用 Jev"""
    from typesafe_sdk import TypeSafeClient  # type: ignore[import]

    client = TypeSafeClient()
    response = client.system_one(state=state, questions=questions)
    return response


def _call_via_http(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """通过 urllib 直接调用 TypeSafe HTTP API（零依赖 fallback）"""
    url = f"{TYPESAFE_BASE_URL}/v1/systemone"
    payload = json.dumps(
        {
            "state": state,
            "model": TYPESAFE_DEFAULT_MODEL,
            "questions": questions,
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {TYPESAFE_API_KEY}",
        },
    )

    with urllib.request.urlopen(req, timeout=TYPESAFE_TIMEOUT_S) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _call_jev_api(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """调用 Jev API（SDK 优先，urllib fallback）

    Raises:
        Exception: 任何网络/API 异常
    """
    # 优先尝试官方 SDK
    try:
        return _call_via_sdk(state, questions)
    except ImportError:
        # SDK 未安装，fallback 到 urllib
        _send_stderr("INFO", "typesafe-sdk 未安装，使用 urllib fallback 调用 Jev API")
        return _call_via_http(state, questions)
    except Exception as e:
        # SDK 调用失败（非 ImportError），fallback 到 urllib
        _send_stderr(
            "WARN",
            f"typesafe-sdk 调用失败 ({type(e).__name__}: {e})，尝试 urllib fallback",
        )
        return _call_via_http(state, questions)


# ============================================================
# 主入口：judge
# ============================================================

def judge(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """调用 Jev 进行决策判断

    输入:
        state: 状态上下文（文本或 JSON 序列化对象）
        questions: 问题集合，复用 anasbekheit evaluate 契约:
            {
                "name": {"type": "noul", "instructions": "..."},
                "name": {"type": "choice", "instructions": "...", "criteria": {"a": "...", "b": "..."}},
                "name": {"type": "score", "instructions": "...", "criteria": ["low", "mid", "high"]}
            }

    输出:
        成功: {
            "model": "jev-1.13.0",
            "answers": {...},
            "usage": {"input_tokens": ..., "output_tokens": ...},
            "degraded": False
        }
        失败: {
            "answers": {},
            "degraded": True,
            "reason": "..."
        }

    FAIL-OPEN: 开关关闭/校验失败/API异常 → degraded=True
    """
    # 1. 功能开关检查
    if not ENABLE_JEV_JUDGE:
        return {"answers": {}, "degraded": True, "reason": "jev_judge_disabled"}

    # 2. API Key 检查
    if not TYPESAFE_API_KEY:
        return {
            "answers": {},
            "degraded": True,
            "reason": "missing TYPESAFE_API_KEY",
        }

    # 3. 输入校验
    errors = _validate_questions(questions)
    if errors:
        return {
            "answers": {},
            "degraded": True,
            "reason": f"invalid_questions: {'; '.join(errors[:3])}",
        }

    # 4. 调用 Jev API
    try:
        result = _call_jev_api(state, questions)

        # 标准化响应（兼容 SDK 和 HTTP 两种返回格式）
        answers = result.get("answers", {})
        model = result.get("model", TYPESAFE_DEFAULT_MODEL)
        usage = result.get("usage", {})

        # HC-5: 确保不包含 reward 字段
        # HC-9: 确保不包含交易决策字段（direction/action/position/size）
        sanitized_answers: dict[str, Any] = {}
        for name, ans in answers.items():
            if isinstance(ans, dict):
                # 剔除禁止字段
                sanitized = {
                    k: v
                    for k, v in ans.items()
                    if k
                    not in (
                        "reward",
                        "direction",
                        "action",
                        "position",
                        "size",
                        "position_delta",
                        "target_weight",
                        "notional",
                    )
                }
                sanitized_answers[name] = sanitized
            else:
                sanitized_answers[name] = ans

        return {
            "model": model,
            "answers": sanitized_answers,
            "usage": usage,
            "degraded": False,
        }

    except urllib.error.HTTPError as e:
        stack = traceback.format_exc()
        _send_stderr(
            "WARN",
            f"jev_judge HTTP 错误 {e.code}: {e.reason}\n{stack}",
        )
        return {
            "answers": {},
            "degraded": True,
            "reason": f"http_error_{e.code}: {e.reason}",
        }

    except urllib.error.URLError as e:
        stack = traceback.format_exc()
        _send_stderr(
            "WARN",
            f"jev_judge 网络错误: {e.reason}\n{stack}",
        )
        return {
            "answers": {},
            "degraded": True,
            "reason": f"network_error: {e.reason}",
        }

    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr(
            "WARN",
            f"jev_judge 异常，FAIL-OPEN: {type(e).__name__}: {e}\n{stack}",
        )
        return {
            "answers": {},
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }


# ============================================================
# IPC handler（供 server.py 路由调用）
# ============================================================

def handle_jev_judge(params: dict) -> dict:
    """jev_judge IPC handler

    输入: {state, questions}
    输出: judge() 的返回值

    边界守护:
        - HC-5: 绝不返回 reward 字段
        - HC-9: 绝不返回交易决策字段（direction/action 等）
    """
    state = params.get("state")
    questions = params.get("questions", {})
    return judge(state, questions)
