"""
DreamOS S层 — Sense 感知层

职责:
    - 意图识别（Intent Recognition）
    - 多源输入融合（市场数据/NLP/信号/记忆/知识库）
    - 零 Token 优先（规则识别），不足时调用 LLM
    - Token 预算管理
    - 可扩展的动态意图类型

子模块:
    - types:            类型定义（IntentInput/IntentResult/RecognizerResult/IntentType）
    - intent_engine:    意图引擎主入口（IntentEngine）
    - token_budget:     Token 预算管理器
    - recognizers/:     识别器实现
        - base.py           基类
        - rule_based.py     零 Token 规则识别
        - llm_based.py      LLM 深度识别
        - dynamic.py        动态可扩展识别

快速上手:
    from dreamos.core.sense import IntentEngine

    engine = IntentEngine(budget_mode="standard")
    result = engine.recognize(
        market={"price": 50000, "rsi14": 45, "change_24h": 2.5},
        user_message="分析BTC",
    )
    print(result.intent_type, result.confidence)
"""

from .types import (
    IntentType,
    IntentInput,
    IntentResult,
    RecognizerResult,
    register_intent_type,
    get_intent_definition,
)
from .intent_engine import IntentEngine
from .token_budget import TokenBudgetManager, BudgetLevel, BUDGET_MODES
from .recognizers import (
    BaseRecognizer,
    RuleBasedRecognizer,
    LLMBasedRecognizer,
    DynamicIntentRecognizer,
)

__all__ = [
    # types
    "IntentType", "IntentInput", "IntentResult", "RecognizerResult",
    "register_intent_type", "get_intent_definition",
    # engine
    "IntentEngine",
    # budget
    "TokenBudgetManager", "BudgetLevel", "BUDGET_MODES",
    # recognizers
    "BaseRecognizer", "RuleBasedRecognizer", "LLMBasedRecognizer",
    "DynamicIntentRecognizer",
]
