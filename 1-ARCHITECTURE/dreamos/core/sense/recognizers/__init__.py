"""
DreamOS S层 — Recognizers 识别器包

提供多种意图识别器，可插拔组合:
    - BaseRecognizer:       识别器基类
    - RuleBasedRecognizer:  零 Token 规则识别
    - LLMBasedRecognizer:   LLM 深度识别
    - DynamicIntentRecognizer: 动态可扩展识别
"""

from .base import BaseRecognizer
from .rule_based import RuleBasedRecognizer
from .llm_based import LLMBasedRecognizer
from .dynamic import DynamicIntentRecognizer

__all__ = [
    "BaseRecognizer",
    "RuleBasedRecognizer",
    "LLMBasedRecognizer",
    "DynamicIntentRecognizer",
]
