#!/usr/bin/env python3
"""Laya (开源 System 1 决策模型) 决策判断封装层

将 Laya 的三种原语（noul/choice/score）封装为统一的 judge 接口，
供 dream-harness-bridge 的 IPC handler 调用。

接口契约与 jev_judge.py 完全兼容（复用 anasbekheit evaluate 格式）：
    Request:  {state, questions: {name: {type, instructions, criteria}}}
    Response: {model, answers: {name: {type, noul|choice|score, ...}}, usage}

设计原则:
    - FAIL-OPEN: 任何异常返回 degraded=True，不阻塞调用方
    - HC-9: 只做通用判断（是否完成/路由/质量），不做交易决策
    - HC-5: 绝不返回 reward 字段
    - 本地推理：不依赖外部 API，数据不出域
    - 惰性加载：模型在首次调用时加载，避免启动阻塞
    - MPS 优先：Apple Silicon 上自动使用 MPS 加速，fallback 到 CPU

与 jev_judge 的关系:
    - 接口完全兼容，可作为 Jev 的本地替代/并行验证
    - 复用 jev_judge 的 _validate_questions 和字段过滤逻辑
    - 适用于 A/B 测试：同一 questions 同时跑 Jev 和 Laya，对比校准

来源: Laya 引入调研（2026-09-24）
"""

from __future__ import annotations

import os
import time
import traceback
from typing import Any

# 复用 jev_judge 的输入校验和字段过滤逻辑（优雅改动：不重造轮子）
try:
    from jev_judge import _validate_questions
except ImportError:
    _validate_questions = None  # type: ignore[assignment]

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
ENABLE_LAYA_JUDGE = os.environ.get("ENABLE_LAYA_JUDGE", "0") == "1"

# 模型配置
LAYA_MODEL_ID = os.environ.get("LAYA_MODEL_ID", "convaiinnovations/laya")
LAYA_SUBFOLDER = os.environ.get("LAYA_SUBFOLDER", "multilingual")  # 多语言（含中文）
LAYA_DEVICE = os.environ.get("LAYA_DEVICE", "mps")  # mps / cpu / cuda

# 合法的问题类型
_VALID_QUESTION_TYPES = ("noul", "choice", "score")

# 禁止字段（HC-5/HC-9）
_FORBIDDEN_FIELDS = (
    "reward",
    "direction",
    "action",
    "position",
    "size",
    "position_delta",
    "target_weight",
    "notional",
)

# 全局模型实例（惰性加载）
_laya_agent: Any = None
_laya_load_error: str | None = None


# ============================================================
# 模型加载（惰性）
# ============================================================

def _get_agent() -> Any:
    """惰性加载 Laya 模型（线程不安全，单进程使用足够）

    Returns:
        Laya Agent 实例；加载失败返回 None（错误已记录到 _laya_load_error）
    """
    global _laya_agent, _laya_load_error

    if _laya_agent is not None:
        return _laya_agent

    if _laya_load_error is not None:
        return None  # 之前加载失败，不再重试

    try:
        import laya

        _send_stderr(
            "INFO",
            f"Laya 加载模型: {LAYA_MODEL_ID} (subfolder={LAYA_SUBFOLDER}, device={LAYA_DEVICE})",
        )
        t0 = time.time()
        _laya_agent = laya.load(
            LAYA_MODEL_ID,
            subfolder=LAYA_SUBFOLDER,
            device=LAYA_DEVICE,
        )
        _send_stderr("INFO", f"Laya 模型加载完成，耗时 {time.time() - t0:.1f}s")
        return _laya_agent

    except Exception as e:
        _laya_load_error = f"{type(e).__name__}: {e}"
        stack = traceback.format_exc()
        _send_stderr(
            "ERROR",
            f"Laya 模型加载失败: {_laya_load_error}\n{stack}",
        )
        return None


# ============================================================
# 字段过滤（复用 jev_judge 的 HC-5/HC-9 策略）
# ============================================================

def _sanitize_answers(answers: dict[str, Any]) -> dict[str, Any]:
    """剔除禁止字段（HC-5/HC-9）

    与 jev_judge 的过滤逻辑保持一致。
    """
    sanitized: dict[str, Any] = {}
    for name, ans in answers.items():
        if isinstance(ans, dict):
            sanitized[name] = {
                k: v for k, v in ans.items() if k not in _FORBIDDEN_FIELDS
            }
        else:
            sanitized[name] = ans
    return sanitized


# ============================================================
# 主入口：judge
# ============================================================

def judge(state: Any, questions: dict[str, Any]) -> dict[str, Any]:
    """调用 Laya 进行决策判断

    接口与 jev_judge.judge 完全兼容。

    输入:
        state: 状态上下文（文本或 JSON 序列化对象）
        questions: 问题集合，复用 anasbekheit evaluate 契约

    输出:
        成功: {
            "model": "laya-rl-agent",
            "answers": {...},
            "usage": {"input_tokens": ..., "output_tokens": 0},
            "degraded": False
        }
        失败: {
            "answers": {},
            "degraded": True,
            "reason": "..."
        }

    FAIL-OPEN: 开关关闭/校验失败/模型加载失败/推理异常 → degraded=True
    """
    # 1. 功能开关检查
    if not ENABLE_LAYA_JUDGE:
        return {"answers": {}, "degraded": True, "reason": "laya_judge_disabled"}

    # 2. 输入校验（复用 jev_judge 的校验逻辑）
    if _validate_questions is not None:
        errors = _validate_questions(questions)
        if errors:
            return {
                "answers": {},
                "degraded": True,
                "reason": f"invalid_questions: {'; '.join(errors[:3])}",
            }
    else:
        # fallback: 基本校验
        if not isinstance(questions, dict) or not questions:
            return {
                "answers": {},
                "degraded": True,
                "reason": "invalid_questions: questions must be a non-empty dict",
            }

    # 3. 加载模型（惰性）
    agent = _get_agent()
    if agent is None:
        return {
            "answers": {},
            "degraded": True,
            "reason": f"model_load_failed: {_laya_load_error}",
        }

    # 4. 调用 Laya 推理
    try:
        result = agent.predict(state, questions)

        # 标准化响应
        answers = result.get("answers", {})
        model = result.get("model", "laya-rl-agent")
        usage = result.get("usage", {})

        # HC-5/HC-9: 剔除禁止字段
        sanitized_answers = _sanitize_answers(answers)

        return {
            "model": model,
            "answers": sanitized_answers,
            "usage": usage,
            "degraded": False,
        }

    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr(
            "WARN",
            f"laya_judge 推理异常，FAIL-OPEN: {type(e).__name__}: {e}\n{stack}",
        )
        return {
            "answers": {},
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }


# ============================================================
# IPC handler（供 server.py 路由调用）
# ============================================================

def handle_laya_judge(params: dict) -> dict:
    """laya_judge IPC handler

    输入: {state, questions}
    输出: judge() 的返回值

    边界守护:
        - HC-5: 绝不返回 reward 字段
        - HC-9: 绝不返回交易决策字段（direction/action 等）
    """
    state = params.get("state")
    questions = params.get("questions", {})
    return judge(state, questions)
