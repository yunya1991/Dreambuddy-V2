"""
DreamOS S层 — 识别器基类

设计:
    - BaseRecognizer 是所有识别器的抽象基类
    - 每个识别器接收 IntentInput，产出 RecognizerResult
    - 识别器可插拔，IntentEngine 可以组合多个识别器

识别器层级（从低到高）:
    1. RuleBasedRecognizer    零 Token，纯规则
    2. LLMBasedRecognizer     LLM 深度识别
    3. DynamicRecognizer      动态意图（可扩展）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from ..types import IntentInput, RecognizerResult, IntentType, get_intent_definition
from dreamos.shared.utils import Timer


class BaseRecognizer(ABC):
    """识别器基类"""

    name: str = "base"
    level: str = "local"              # local / llm / hybrid
    estimated_tokens: int = 0

    def __init__(self, **kwargs):
        self._options = kwargs

    @abstractmethod
    def recognize(self, _input: IntentInput) -> RecognizerResult:
        """执行识别

        Args:
            _input: 意图识别输入

        Returns:
            RecognizerResult: 识别结果
        """
        ...

    def can_handle(self, _input: IntentInput) -> bool:
        """是否能处理此输入（默认都可以）"""
        return True

    # ── 工具方法 ───────────────────────────────────

    def _make_result(self, intent_type: str, confidence: float,
                     rationale: str = "", **kwargs) -> RecognizerResult:
        """便捷构造结果"""
        definition = get_intent_definition(intent_type)
        return RecognizerResult(
            recognizer=self.name,
            intent_type=intent_type,
            confidence=min(max(confidence, 0.0), 1.0),
            rationale=rationale,
            base_chain=kwargs.get("base_chain", []),
            extend_nodes=kwargs.get("extend_nodes", []),
            context=kwargs.get("context", {}),
            level=self.level,
        )

    def _uncertain(self, reason: str = "无法确定意图") -> RecognizerResult:
        """返回不确定结果"""
        return self._make_result(
            IntentType.UNCERTAIN.value, 0.0, reason,
        )
