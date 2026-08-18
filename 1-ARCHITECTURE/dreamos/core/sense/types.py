"""
DreamOS S层 — 类型定义

设计原则:
    - 类型是 S 层的公共语言，所有 recognizer/engine 共享
    - 类型简单、序列化友好，便于跨层传递
    - 与 6 种标准意图类型对齐

核心类型:
    - IntentType     意图类型枚举（6 种 + 可扩展）
    - IntentResult   意图识别结果（S 层最终输出）
    - IntentInput    意图识别输入（多源输入）
    - RecognizerResult  单个识别器的结果
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime


# ============================================================
# 意图类型
# ============================================================

class IntentType(str, Enum):
    """标准意图类型（与 SKILL 文档对齐）

    6 种预定义意图，可通过 register_intent_type() 扩展
    """
    TREND_FOLLOWING = "TREND_FOLLOWING"        # 趋势跟随
    MEAN_REVERSION = "MEAN_REVERSION"          # 均值回归
    FUNDAMENTAL_PLAY = "FUNDAMENTAL_PLAY"      # 基本面驱动
    BREAKOUT = "BREAKOUT"                       # 突破
    KNOWLEDGE_MATCH = "KNOWLEDGE_MATCH"         # 知识库匹配
    UNCERTAIN = "UNCERTAIN"                     # 不确定/需要澄清

    @classmethod
    def all_types(cls) -> List[str]:
        return [t.value for t in cls if t != cls.UNCERTAIN]


# 可扩展的自定义意图类型注册表
_custom_intent_types: Dict[str, Dict[str, Any]] = {}


def register_intent_type(type_id: str, definition: Dict[str, Any]) -> bool:
    """注册自定义意图类型

    Args:
        type_id: 意图类型 ID（全大写）
        definition: 定义（name / description / chain / priority / keywords）

    Returns:
        是否注册成功
    """
    if not type_id or not definition:
        return False
    _custom_intent_types[type_id] = definition
    return True


def get_intent_definition(intent_type: str) -> Dict[str, Any]:
    """获取意图类型定义"""
    # 标准意图
    standard = {
        "TREND_FOLLOWING": {
            "name": "趋势跟随",
            "description": "识别趋势行情，顺势操作",
            "chain": "A",
            "priority": 1,
            "keywords": ["趋势", "trend", "均线", "ma", "ema", "突破趋势", "顺势", "做多", "趋势跟随", "多头", "空头"],
        },
        "MEAN_REVERSION": {
            "name": "均值回归",
            "description": "识别超买超卖，逆向操作",
            "chain": "A",
            "priority": 2,
            "keywords": ["均值回归", "超买超卖", "超买", "超卖", "回调", "反弹", "rsi", "布林", "boll", "逆向", "做空", "抄底"],
        },
        "FUNDAMENTAL_PLAY": {
            "name": "基本面驱动",
            "description": "基于新闻/资金流/链上数据驱动",
            "chain": "F",
            "priority": 3,
            "keywords": ["新闻", "news", "资金", "funding", "链上", "onchain", "宏观"],
        },
        "BREAKOUT": {
            "name": "突破",
            "description": "识别关键位突破",
            "chain": "C",
            "priority": 2,
            "keywords": ["突破", "breakout", "阻力", "支撑", "新高", "新低"],
        },
        "KNOWLEDGE_MATCH": {
            "name": "知识库匹配",
            "description": "从历史模式/知识库中匹配",
            "chain": "A",
            "priority": 4,
            "keywords": ["模式", "历史", "教训", "lesson", "记忆"],
        },
        "UNCERTAIN": {
            "name": "不确定",
            "description": "需要更多信息或澄清",
            "chain": "",
            "priority": 99,
            "keywords": [],
        },
    }

    if intent_type in standard:
        return standard[intent_type]
    if intent_type in _custom_intent_types:
        return _custom_intent_types[intent_type]
    return standard["UNCERTAIN"]


# ============================================================
# 意图识别输入
# ============================================================

@dataclass
class IntentInput:
    """意图识别输入 — 多源数据的统一封装

    所有识别器都接收 IntentInput，按需读取自己关心的字段。
    """
    # 自然语言输入（可选）
    user_message: Optional[str] = None

    # 市场数据
    market: Optional[Dict[str, Any]] = None

    # 外部信号
    signals: Optional[List[Dict[str, Any]]] = None

    # 记忆/历史
    memory: Optional[Dict[str, Any]] = None
    recent_decisions: Optional[List[Dict[str, Any]]] = None

    # 知识库命中
    knowledge_hits: Optional[List[Dict[str, Any]]] = None

    # 上下文
    context: Dict[str, Any] = field(default_factory=dict)

    # 标的信息
    symbol: str = "BTC-USDT"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_message": self.user_message,
            "market": self.market,
            "signals": self.signals,
            "memory": self.memory,
            "recent_decisions": self.recent_decisions,
            "knowledge_hits": self.knowledge_hits,
            "context": self.context,
            "symbol": self.symbol,
        }


# ============================================================
# 单个识别器的结果
# ============================================================

@dataclass
class RecognizerResult:
    """单个识别器的识别结果

    多个识别器的结果会被融合为最终 IntentResult。
    """
    recognizer: str                          # 识别器名称
    intent_type: str                         # 识别出的意图类型
    confidence: float = 0.0                  # 0-1
    rationale: str = ""                      # 理由
    base_chain: List[str] = field(default_factory=list)     # 推荐主链
    extend_nodes: List[str] = field(default_factory=list)   # 扩展节点
    context: Dict[str, Any] = field(default_factory=dict)    # 额外上下文
    latency_ms: float = 0.0
    tokens_used: int = 0
    level: str = "local"                     # local / llm / hybrid


# ============================================================
# 最终意图结果（S 层输出）
# ============================================================

@dataclass
class IntentResult:
    """S 层最终输出 — 意图识别结果

    这是 S 层传给 A 层的核心数据结构。
    """
    intent_type: str = IntentType.UNCERTAIN.value
    confidence: float = 0.0

    # 链路建议
    recommended_chain: str = ""              # 推荐主链 (A/C/F)
    base_chain: List[str] = field(default_factory=list)
    extend_nodes: List[str] = field(default_factory=list)

    # 解释
    rationale: str = ""
    recognizers_used: List[str] = field(default_factory=list)

    # 上下文（传给下游层）
    context: Dict[str, Any] = field(default_factory=dict)

    # 统计
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    level: str = "local"                     # local / llm / hybrid / fallback

    # 澄清相关
    clarify_needed: bool = False
    clarify_question: Optional[str] = None
    clarify_options: Optional[List[Dict[str, Any]]] = None

    # 元信息
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "confidence": self.confidence,
            "recommended_chain": self.recommended_chain,
            "base_chain": self.base_chain,
            "extend_nodes": self.extend_nodes,
            "rationale": self.rationale,
            "recognizers_used": self.recognizers_used,
            "context": self.context,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "level": self.level,
            "clarify_needed": self.clarify_needed,
            "clarify_question": self.clarify_question,
            "clarify_options": self.clarify_options,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntentResult":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
