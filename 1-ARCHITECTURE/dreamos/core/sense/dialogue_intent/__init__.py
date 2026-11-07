"""
DreamOS 对话意图识别模块（操作系统内核 S 层）

提供 6×30 对话意图分类、槽位归一化、能力路由决策、多意图检测。

核心组件:
    - taxonomy:       意图分类体系定义（6 大类 × 30 二级意图）
    - slots:          槽位归一化（股票/时间/数量/板块/指标）
    - classifier:     意图分类器（规则 + LLM 融合）
    - multi_intent:   多意图检测器（三层：连接词/标的级/复合意图）
"""

from .classifier import (
    DialogueIntentClassifier,
    DialogueIntentResult,
)
from .multi_intent import (
    COMPOUND_PATTERNS,
    CONJUNCTIONS,
    MultiIntentDetector,
)
from .slots import (
    extract_slots_from_text,
    normalize_indicator,
    normalize_quantity,
    normalize_sector,
    normalize_stock,
    normalize_timeframe,
)
from .taxonomy import (
    INTENT_TAXONOMY,
    AnalysisIntent,
    DialogIntent,
    PrimaryIntent,
    QueryIntent,
    RiskIntent,
    StrategyIntent,
    TradeIntent,
    get_all_secondaries,
    get_default_capability_route,
    get_primary_intent,
    get_risk_level,
    is_valid_secondary,
)

__all__ = [
    # taxonomy
    "PrimaryIntent",
    "QueryIntent",
    "AnalysisIntent",
    "TradeIntent",
    "StrategyIntent",
    "RiskIntent",
    "DialogIntent",
    "INTENT_TAXONOMY",
    "get_primary_intent",
    "get_risk_level",
    "get_default_capability_route",
    "is_valid_secondary",
    "get_all_secondaries",
    # slots
    "normalize_stock",
    "normalize_timeframe",
    "normalize_quantity",
    "normalize_sector",
    "normalize_indicator",
    "extract_slots_from_text",
    # multi_intent
    "MultiIntentDetector",
    "CONJUNCTIONS",
    "COMPOUND_PATTERNS",
    # classifier
    "DialogueIntentClassifier",
    "DialogueIntentResult",
]
