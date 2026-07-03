"""
DreamOS S层 — 动态意图识别器

支持注册自定义意图类型，不局限于预定义的 6 种。

设计:
    - 动态注册意图类型
    - 动态注册识别策略
    - LLM 辅助识别未注册的新意图类型
    - 置信度不足时回退到标准类型

与 dynamic_intent_recognizer.py 的关系:
    - 保留其核心设计（可扩展注册机制）
    - 重写为符合 DreamOS 架构的清晰实现
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import BaseRecognizer
from ..types import (
    IntentInput, RecognizerResult, IntentType,
    register_intent_type, get_intent_definition,
)
from dreamos.shared.utils import Timer


# 自定义识别函数类型
RecognizerFn = Callable[[IntentInput], Optional[RecognizerResult]]


class DynamicIntentRecognizer(BaseRecognizer):
    """动态意图识别器 — 支持扩展新的意图类型

    用法:
        rec = DynamicIntentRecognizer()

        # 注册自定义意图类型
        rec.register_intent_type("ARBITRAGE", {
            "name": "套利",
            "description": "跨平台/跨品种套利",
            "chain": "F",
            "keywords": ["套利", "arb", "spread"],
        })

        # 注册自定义识别策略
        rec.register_strategy("arbitrage_detector", my_detector_fn)

        # 执行识别
        result = rec.recognize(input)
    """

    name = "dynamic"
    level = "hybrid"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._strategies: Dict[str, RecognizerFn] = {}
        self._custom_types: Dict[str, Dict[str, Any]] = {}

    # ── 自定义意图类型 ─────────────────────────────────

    def register_intent_type(self, type_id: str, definition: Dict[str, Any]) -> bool:
        """注册自定义意图类型

        Args:
            type_id: 意图类型 ID（全大写）
            definition: 定义

        Returns:
            是否成功
        """
        if not type_id or not definition:
            return False
        type_id = type_id.upper()
        self._custom_types[type_id] = definition
        # 同时注册到全局类型库
        register_intent_type(type_id, definition)
        return True

    def list_custom_types(self) -> List[str]:
        """列出所有自定义意图类型"""
        return list(self._custom_types.keys())

    # ── 自定义识别策略 ─────────────────────────────────

    def register_strategy(self, name: str, fn: RecognizerFn) -> bool:
        """注册自定义识别策略

        Args:
            name: 策略名称
            fn: 识别函数，接收 IntentInput，返回 RecognizerResult 或 None

        Returns:
            是否成功
        """
        if not name or not callable(fn):
            return False
        self._strategies[name] = fn
        return True

    def unregister_strategy(self, name: str) -> bool:
        """注销策略"""
        if name in self._strategies:
            del self._strategies[name]
            return True
        return False

    # ── 核心识别逻辑 ───────────────────────────────────

    def recognize(self, _input: IntentInput) -> RecognizerResult:
        timer = Timer(self.name)

        results: List[RecognizerResult] = []

        # 依次运行所有策略
        for name, strategy_fn in self._strategies.items():
            try:
                result = strategy_fn(_input)
                if result is not None:
                    result.recognizer = f"{self.name}/{name}"
                    results.append(result)
            except Exception as e:
                # 单个策略失败不影响整体
                results.append(RecognizerResult(
                    recognizer=f"{self.name}/{name}",
                    intent_type=IntentType.UNCERTAIN.value,
                    confidence=0.0,
                    rationale=f"策略执行异常: {e}",
                ))

        with timer:
            pass

        if not results:
            return self._uncertain("无可用动态策略")

        # 取置信度最高的结果
        best = max(results, key=lambda r: r.confidence)
        best.latency_ms = timer.elapsed_ms
        best.level = self.level

        # 附加其他候选结果到 context
        best.context["all_results"] = [
            {"recognizer": r.recognizer, "intent_type": r.intent_type,
             "confidence": r.confidence}
            for r in results
        ]

        return best
