"""dream-harness-bridge 算法驱动层 IPC handler

Layer 1 算法识别 — 来源: SPEC_ALGORITHM_DRIVEN_TRAINING_LOOP.md Phase 0-2b

设计原则:
    - F-06: 惰性 import 重原生库（sklearn/torch），模块级不 import
    - FAIL-OPEN: 任何异常返回中性兜底，不阻塞交易热路径
    - HC-1a: 不修改 dreamos/ 代码，只通过 import 调用
    - 功能开关: ENABLE_ALGORITHM_LAYER=0 时返回 degraded=True

IPC handler:
    handle_algorithm_recognize(params) → 算法识别（Layer 1）
    handle_shadow_review(params)       → 影子评审（Layer 2, P0-3-S2 扩展）
    handle_agent_takeover(params)      → Agent接管（Layer 3, P0-4-S1 扩展）
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path
from typing import Any

# 复用 server.py 的 _send_stderr 和 _DREAMOS_ARCH_DIR
# 同目录 import，运行时由 server.py 的 sys.path 保证可导入
try:
    from server import _send_stderr, _DREAMOS_ARCH_DIR, ENABLE_ALGORITHM_LAYER
    _ALGORITHM_TRIGGER_THRESHOLD = 0.70
    _AGENT_TAKEOVER_T3_CONFIDENCE = 0.88
    _SHADOW_REVIEW_SAMPLE_RATE = 0.30
    _ACTIVE_LEARNING_DIFFICULTY_THRESHOLD = 0.55
except ImportError:
    # 独立运行时 fallback
    import os
    _send_stderr = lambda level, msg: sys.stderr.write(f"[{level}] {msg}\n")  # noqa: E731
    _DREAMOS_ARCH_DIR = str(Path(__file__).resolve().parent.parent.parent.parent)
    ENABLE_ALGORITHM_LAYER = os.environ.get("ENABLE_ALGORITHM_LAYER", "0") == "1"
    _ALGORITHM_TRIGGER_THRESHOLD = 0.70
    _AGENT_TAKEOVER_T3_CONFIDENCE = 0.88
    _SHADOW_REVIEW_SAMPLE_RATE = 0.30
    _ACTIVE_LEARNING_DIFFICULTY_THRESHOLD = 0.55


# ============================================================
# Layer 1: 算法识别 IPC handler
# ============================================================

def handle_algorithm_recognize(params: dict) -> dict:
    """Layer 1 算法识别 IPC handler

    输入: {user_message, market, signals, memory, knowledge_hits, context, symbol}
    输出: {intent_type, confidence, tier, base_chain, agent_takeover_needed, degraded}

    短路逻辑:
        1. 检查 ENABLE_ALGORITHM_LAYER 开关
        2. 惰性 import DreamOS 识别器
        3. 调用 RuleBasedRecognizer
        4. 调用 classify_complexity 分级
        5. 判断是否需要 Agent 接管
    """
    # 1. 检查功能开关
    if not ENABLE_ALGORITHM_LAYER:
        return {"degraded": True, "reason": "algorithm_layer_disabled"}

    try:
        # 2. 惰性 import DreamOS 识别器（F-06: 不在模块级 import）
        if _DREAMOS_ARCH_DIR not in sys.path:
            sys.path.insert(0, _DREAMOS_ARCH_DIR)
        from dreamos.core.sense.complexity_classifier import (
            classify_complexity, TIER_T3,
        )
        from dreamos.core.sense.recognizers.rule_based import RuleBasedRecognizer
        from dreamos.core.sense.types import IntentInput

        # 3. 构造 IntentInput
        _input = IntentInput(
            user_message=params.get("user_message"),
            market=params.get("market"),
            signals=params.get("signals"),
            memory=params.get("memory"),
            knowledge_hits=params.get("knowledge_hits"),
            context=params.get("context") or {},
            symbol=params.get("symbol", "BTC-USDT"),
        )

        # 4. 调用 RuleBasedRecognizer
        recognizer = RuleBasedRecognizer()
        result = recognizer.recognize(_input)

        # 5. 复杂度分级
        complexity = classify_complexity(
            user_message=params.get("user_message"),
            intent_type=result.intent_type,
            context=params.get("context"),
        )

        # 6. 判断是否需要 Agent 接管
        agent_takeover_needed = (
            complexity.tier == TIER_T3
            or result.confidence >= _AGENT_TAKEOVER_T3_CONFIDENCE
        )

        return {
            "intent_type": result.intent_type,
            "confidence": result.confidence,
            "tier": complexity.tier,
            "base_chain": result.base_chain or [],
            "agent_takeover_needed": agent_takeover_needed,
            "rationale": result.rationale,
            "complexity_rationale": complexity.rationale,
            "degraded": False,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"algorithm_recognize 失败，FAIL-OPEN: {e}\n{stack}")
        # FAIL-OPEN: 返回中性兜底
        return {
            "intent_type": "UNCERTAIN",
            "confidence": 0.0,
            "tier": "T1",
            "base_chain": [],
            "agent_takeover_needed": False,
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }


# ============================================================
# Layer 2: 影子评审 IPC handler (P0-3-S2)
# ============================================================

def handle_shadow_review(params: dict) -> dict:
    """Layer 2 影子评审 IPC handler

    输入: {algorithm_result: {intent_type, confidence, tier, ...}}
    输出: {review_result, review_confidence, similar_cases_count, degraded}

    边界守护:
        - HC-5: 绝不计算/返回 reward 字段
        - HC-9: 绝不返回交易决策字段（direction/action等）
    """
    if not ENABLE_ALGORITHM_LAYER:
        return {"degraded": True, "reason": "algorithm_layer_disabled"}

    try:
        algorithm_result = params.get("algorithm_result", {})

        # 1. 调用认知系统 recall 检索相似案例
        similar_cases = _recall_similar_cases(algorithm_result)

        # 2. 对比 algorithm 决策与历史案例
        review_result = "uncertain"
        review_confidence = 0.5
        if similar_cases:
            # 简化版: 若 algorithm 决策与多数历史案例一致，则 consistent
            same_intent = sum(
                1 for c in similar_cases
                if c.get("intent_type") == algorithm_result.get("intent_type")
            )
            review_confidence = same_intent / len(similar_cases)
            review_result = "consistent" if review_confidence > 0.6 else "divergent"

        # HC-5: 绝不返回 reward 字段
        # HC-9: 绝不返回交易决策字段（direction/action等）
        return {
            "review_result": review_result,
            "review_confidence": review_confidence,
            "similar_cases_count": len(similar_cases),
            "degraded": False,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"shadow_review 失败，FAIL-OPEN: {e}\n{stack}")
        return {
            "review_result": "skipped",
            "review_confidence": 0.0,
            "similar_cases_count": 0,
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }


def _recall_similar_cases(algorithm_result: dict) -> list:
    """调用认知系统 recall 检索相似案例（FAIL-OPEN）"""
    try:
        cog_path = str(
            Path(__file__).resolve().parent.parent.parent.parent.parent
            / "4-MEMORY" / "9-工具与接口"
        )
        if cog_path not in sys.path:
            sys.path.insert(0, cog_path)
        from cognitive_loop_entry import get_cle
        cle = get_cle()

        context = (
            f"intent_type={algorithm_result.get('intent_type', '')}, "
            f"tier={algorithm_result.get('tier', '')}"
        )
        memories = cle.recall(context=context, top_k=5, min_quality="C")
        return memories if memories else []
    except Exception:
        return []  # FAIL-OPEN


# ============================================================
# Layer 3: Agent 接管 IPC handler (P0-4-S1)
# ============================================================

def handle_agent_takeover(params: dict) -> dict:
    """Layer 3 Agent 接管 IPC handler

    输入: {algorithm_result: {tier, confidence, ...}, context}
    输出: {decision: CONTINUE/INSERT_BEFORE, agent_delegated, degraded}

    边界: 只返回 ReflectionDecision，不做交易判断
    """
    if not ENABLE_ALGORITHM_LAYER:
        return {"degraded": True, "reason": "algorithm_layer_disabled"}

    try:
        from reflection_handler import VALID_DECISIONS  # 复用 F-10 决策枚举

        algorithm_result = params.get("algorithm_result", {})
        tier = algorithm_result.get("tier", "T1")
        confidence = algorithm_result.get("confidence", 0.0)

        # T3 或高置信度 → 委托 Agent
        should_delegate = (
            tier == "T3"
            or confidence >= _AGENT_TAKEOVER_T3_CONFIDENCE
        )

        if should_delegate:
            decision = "INSERT_BEFORE"
        else:
            decision = "CONTINUE"

        # 验证 decision 值在合法枚举内
        assert decision in VALID_DECISIONS, f"非法 decision: {decision}"

        return {
            "decision": decision,
            "target_step": "harness_subagent" if should_delegate else None,
            "agent_delegated": should_delegate,
            "reason": f"tier={tier}, confidence={confidence}",
            "degraded": False,
        }
    except Exception as e:
        stack = traceback.format_exc()
        _send_stderr("WARN", f"agent_takeover 失败，FAIL-OPEN: {e}\n{stack}")
        return {
            "decision": "CONTINUE",
            "agent_delegated": False,
            "degraded": True,
            "reason": f"{type(e).__name__}: {e}",
        }
