"""多意图检测器（Multi-Intent Detector）

属于 DreamOS 操作系统内核 S 层 (core/sense/dialogue_intent/)。

三层检测策略:
    Layer 1: 连接词拆分 — 迁移自 classifier.py:127 `_detect_multi_intent`
             支持连接词: 还有/顺便/另外/以及/并且/同时/再帮我
    Layer 2: 标的级拆分 — 当单段文本提及多个标的时，按标的边界进一步切分
             使用软分隔符 (和/与/以及) 在多标的上下文中切分
    Layer 3: 复合意图检测 — 单段文本内同时出现 分析+交易 等组合
             如 "深度分析BTC并买入" → [deep_analysis, buy]

设计原则:
    - detect() 返回 List[str] 去重保序（首次出现位置）
    - slots 参数可选，用于辅助标的级拆分（当外部已提取多 stock 列表时）
    - 使用 late import 规避与 classifier.py 的循环依赖
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ============================================================
# 常量
# ============================================================

# Layer 1 连接词（与原 classifier.py:130 完全一致，确保迁移等价）
CONJUNCTIONS: List[str] = [
    "还有", "顺便", "另外", "以及", "并且", "同时", "再帮我",
]

# Layer 2 软分隔符（仅在多标的上下文中作为切分点）
TARGET_SEPARATORS: List[str] = ["和", "与", "以及", ","]

# Layer 3 复合意图 patterns
# 顺序敏感：更具体的模式在前，避免 "深度分析.*买" 与 "分析.*买" 同时命中
# 引入歧义（dedup 会处理重复 buy，但意图顺序按首次命中保留）
COMPOUND_PATTERNS: List[tuple] = [
    # (regex, [intents]) — intent 列表顺序即为首次出现顺序
    (r"深度分析.*?(?:并|而且).*(?:买入|买进|建仓|开多|做多)", ["deep_analysis", "buy"]),
    (r"推荐.*?(?:并|而且).*(?:买入|买进|建仓)",            ["stock_recommendation", "buy"]),
    (r"筛选.*?(?:并|而且).*(?:买入|买进|建仓)",            ["factor_screen", "buy"]),
    (r"分析.*?(?:并|而且).*(?:买入|买进|建仓|开多|做多)", ["technical_analysis", "buy"]),
]

# 用于识别文本中标的的别名表（late import 后填充）
_STOCK_ALIASES: Optional[Dict[str, str]] = None


# ============================================================
# MultiIntentDetector
# ============================================================

class MultiIntentDetector:
    """多意图检测器 — 三层检测策略"""

    def __init__(self) -> None:
        # late import 规避循环依赖（classifier.py 反向引用本模块）
        # 在 __init__ 中一次性加载，避免每次 detect 都触发 import
        from .slots import STOCK_ALIASES  # type: ignore
        global _STOCK_ALIASES
        _STOCK_ALIASES = STOCK_ALIASES

    # ------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------

    def detect(self, text: str, slots: Optional[Dict[str, Any]] = None) -> List[str]:
        """检测文本中的多意图

        Args:
            text: 用户输入文本
            slots: 可选槽位字典，含 'stocks' 列表时辅助标的级拆分

        Returns:
            去重保序的二级意图列表（空输入返回 []）
        """
        if not text or not text.strip():
            return []

        intents: List[str] = []

        # Layer 1: 连接词拆分
        segments = self._split_by_conjunctions(text)

        # Layer 2 + 规则匹配: 每个段做标的级拆分，再 _rule_classify
        for segment in segments:
            sub_segments = self._split_by_targets(segment, slots)
            for sub in sub_segments:
                sub = sub.strip()
                if len(sub) <= 1:
                    continue
                intent = self._rule_classify(sub)
                if intent:
                    intents.append(intent)

        # Layer 3: 复合意图（作用于原始文本，捕获单段内的组合意图）
        compound_intents = self._detect_compound(text)
        intents.extend(compound_intents)

        # 去重保序
        return self._dedup_preserve_order(intents)

    # ------------------------------------------------------------
    # Layer 1: 连接词拆分
    # ------------------------------------------------------------

    @staticmethod
    def _split_by_conjunctions(text: str) -> List[str]:
        """按连接词拆分文本（等价于 classifier.py:127 逻辑）"""
        parts: List[str] = [text]
        for conj in CONJUNCTIONS:
            new_parts: List[str] = []
            for part in parts:
                new_parts.extend(part.split(conj))
            parts = new_parts
        return parts

    # ------------------------------------------------------------
    # Layer 2: 标的级拆分
    # ------------------------------------------------------------

    def _split_by_targets(
        self, text: str, slots: Optional[Dict[str, Any]] = None
    ) -> List[str]:
        """当段内含多个标的时，按软分隔符切分"""
        # 获取文本中的标的数（来自 STOCK_ALIASES 命中）
        stocks_found = self._find_stocks_in_text(text)

        # 外部 slots 提示多 stock
        if slots and isinstance(slots.get("stocks"), list) and len(slots["stocks"]) >= 2:
            stocks_found = list(set(stocks_found + slots["stocks"]))

        if len(stocks_found) < 2:
            return [text]

        # 在多标的上下文中，按软分隔符切分
        for sep in TARGET_SEPARATORS:
            if sep in text:
                parts = text.split(sep)
                if len(parts) >= 2:
                    return parts

        return [text]

    @staticmethod
    def _find_stocks_in_text(text: str) -> List[str]:
        """扫描文本中出现的所有标准标的名称"""
        if _STOCK_ALIASES is None:
            return []
        found: List[str] = []
        seen = set()
        for alias, standard in _STOCK_ALIASES.items():
            if alias in text and standard not in seen:
                found.append(standard)
                seen.add(standard)
        return found

    # ------------------------------------------------------------
    # Layer 3: 复合意图检测
    # ------------------------------------------------------------

    @staticmethod
    def _detect_compound(text: str) -> List[str]:
        """检测单段文本中的复合意图模式"""
        result: List[str] = []
        for pattern, intents in COMPOUND_PATTERNS:
            if re.search(pattern, text):
                result.extend(intents)
        return result

    # ------------------------------------------------------------
    # 去重保序
    # ------------------------------------------------------------

    @staticmethod
    def _dedup_preserve_order(items: List[str]) -> List[str]:
        """去重并保留首次出现顺序"""
        seen = set()
        unique: List[str] = []
        for item in items:
            if item not in seen:
                seen.add(item)
                unique.append(item)
        return unique

    # ------------------------------------------------------------
    # 规则分类（late import）
    # ------------------------------------------------------------

    @staticmethod
    def _rule_classify(text: str) -> Optional[str]:
        """复用 classifier._rule_classify（late import 规避循环依赖）"""
        from .classifier import _rule_classify  # type: ignore
        return _rule_classify(text)
