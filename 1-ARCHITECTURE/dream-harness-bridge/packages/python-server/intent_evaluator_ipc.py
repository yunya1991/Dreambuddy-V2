#!/usr/bin/env python3
"""intent_evaluator_ipc — S 层意图评估 subagent IPC handler

供 server.py 路由调用, 将 params 转发到 IntentEvaluatorAgent。

集成 jev (备用 laya):
    - jev_fn 通过 handle_jev_judge 调用 TypeSafe System One
    - laya_fn 通过 handle_laya_judge 调用本地 Laya 模型
    - jev degraded 时自动 fallback 到 laya
"""
import traceback
import sys
import os

# 确保 dreamos 路径可达 (1-ARCHITECTURE/dreamos 的父目录)
# __file__ = .../dream-harness-bridge/packages/python-server/intent_evaluator_ipc.py
# ../../.. = .../1-ARCHITECTURE
_dreamos_root = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
))
if _dreamos_root not in sys.path:
    sys.path.insert(0, _dreamos_root)

# 确保 python-server 目录在 sys.path (用于导入 jev_judge / laya_judge)
_server_dir = os.path.dirname(os.path.abspath(__file__))
if _server_dir not in sys.path:
    sys.path.insert(0, _server_dir)

from dreamos.core.sense.evaluators.intent_evaluator_agent import (
    IntentEvaluatorAgent, EvalResult,
)
import jev_judge
import laya_judge


def _make_jev_fn():
    """构造 jev_fn 闭包, 内部调用 handle_jev_judge"""
    def jev_fn(state, questions):
        return jev_judge.handle_jev_judge({"state": state, "questions": questions})
    return jev_fn


def _make_laya_fn():
    """构造 laya_fn 闭包, 内部调用 handle_laya_judge"""
    def laya_fn(state, questions):
        return laya_judge.handle_laya_judge({"state": state, "questions": questions})
    return laya_fn


def handle_intent_evaluator(params: dict) -> dict:
    """IPC handler: S 层意图评估 subagent

    参数:
        intent: IntentResult dict (intent_type, confidence, rationale 等)
        context: 评估上下文 (user_message, market 等)

    返回:
        {ok: True, evaluation: {...}} 或 {ok: False, error: ...}
    """
    try:
        intent_dict = params.get("intent", {})
        context = params.get("context", {})

        # 从 dict 构造一个轻量对象 (避免 IntentResult 完整依赖)
        class _IntentProxy:
            def __init__(self, d):
                self.intent_type = d.get("intent_type", "uncertain")
                self.confidence = d.get("confidence", 0.0)
                self.rationale = d.get("rationale", "")

        intent_proxy = _IntentProxy(intent_dict)
        # 注入 jev_fn (备用 laya_fn), 生产环境可按需注入 llm_fn / cognitive_adapter
        agent = IntentEvaluatorAgent(
            jev_fn=_make_jev_fn(),
            laya_fn=_make_laya_fn(),
        )
        result: EvalResult = agent.evaluate(intent_proxy, context)
        return {
            "ok": True,
            "evaluation": result.to_dict(),
        }
    except Exception as e:
        stack = traceback.format_exc()
        return {"ok": False, "error": str(e), "stack": stack}
