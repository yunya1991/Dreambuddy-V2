#!/usr/bin/env python3
"""
SKILL 增强触发层 (Skill Enhancement Trigger Layer)

定位: synthesizer 产出报告之后, 检测是否需要调用 6-TRADING SKILL 做增强分析.
设计原则:
  - FAIL-OPEN: 任何异常不影响原报告输出
  - 按需触发: 仅在检测到特定信号时产出 enhancement_hints
  - IDE 执行: 实际 SKILL 由 WorkBuddy/Trae 执行, 本模块只产出触发信号
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ── SKILL 映射表 (与 6-TRADING/bridge/api/skill_router_api.py SKILL_MAP 一致) ──
SKILL_MAP = {
    "A0": "dream-contradiction-theory",
    "A1": "dream-strategy-research",
    "A2": "dream-first-principles",
    "regime": "dream-regime-detector",
    "signal": "dream-signal-scoring-spec",
    "risk": "dream-risk-position-sizing",
}

SKILL_DESCRIPTIONS = {
    "A0": "矛盾论分析 - 识别多空信号冲突",
    "A1": "深度调研 - 补充缺失数据维度",
    "A2": "第一性原理 - 市场本质再解析",
    "regime": "Regime检测 - 市场状态识别",
    "signal": "信号评分 - 多源信号标准化",
    "risk": "仓位风控 - 风险预算与仓位计算",
}


@dataclass
class EnhancementHint:
    """增强提示: 告诉前端/IDE 应该调用哪个 SKILL 及原因"""
    skill_key: str          # SKILL 映射键 (如 "A0", "regime")
    skill_name: str         # 实际 SKILL 名称
    reason: str             # 触发原因 (人类可读)
    target_modules: List[str] = field(default_factory=list)  # 涉及的模块
    priority: str = "medium"  # high / medium / low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "skill_key": self.skill_key,
            "skill_name": self.skill_name,
            "description": SKILL_DESCRIPTIONS.get(self.skill_key, ""),
            "reason": self.reason,
            "target_modules": self.target_modules,
            "priority": self.priority,
        }


# ── 触发检测规则 ──

# 看多/看空关键词 (用于检测模块间信号冲突)
_BULLISH_PATTERNS = re.compile(
    r"(上涨|看多|牛市|多头|突破|反弹|支撑|强势|向上|做多|买入|看涨|上升趋势)",
    re.IGNORECASE,
)
_BEARISH_PATTERNS = re.compile(
    r"(下跌|看空|熊市|空头|跌破|回调|阻力|弱势|向下|做空|卖出|看跌|下降趋势)",
    re.IGNORECASE,
)

# 数据不足关键词
_DATA_GAP_PATTERNS = re.compile(
    r"(数据不足|暂无|缺失|无法获取|N/A|未提供|缺少)",
    re.IGNORECASE,
)

# 盘整/不确定关键词
_RANGING_PATTERNS = re.compile(
    r"(横盘|震荡|盘整|区间|方向不明|不确定|观望|等待)",
    re.IGNORECASE,
)


def _detect_direction(text: str) -> Optional[str]:
    """检测文本的多空方向: 'bull' / 'bear' / 'neutral' / None"""
    bull = bool(_BULLISH_PATTERNS.search(text))
    bear = bool(_BEARISH_PATTERNS.search(text))
    if bull and not bear:
        return "bull"
    if bear and not bull:
        return "bear"
    if bull and bear:
        return "mixed"
    return "neutral"


def detect_enhancement_triggers(
    cards: List[Dict[str, Any]],
    overall_confidence: Optional[float] = None,
) -> List[EnhancementHint]:
    """
    检测是否需要 SKILL 增强.

    Args:
        cards: synthesizer 产出的卡片列表 (to_dict 后的 dict)
        overall_confidence: 整体置信度 (0-1), 可选

    Returns:
        EnhancementHint 列表, 空列表表示无需增强
    """
    hints: List[EnhancementHint] = []

    if not cards:
        return hints

    # ── 规则1: 数据不足 → A1 深度调研 ──
    data_gap_modules: List[str] = []
    for card in cards:
        content = str(card.get("content", ""))
        if _DATA_GAP_PATTERNS.search(content):
            for mod in card.get("source_modules", []):
                if mod not in data_gap_modules:
                    data_gap_modules.append(mod)
    if data_gap_modules:
        hints.append(EnhancementHint(
            skill_key="A1",
            skill_name=SKILL_MAP["A1"],
            reason=f"以下维度数据不足: {', '.join(data_gap_modules)}",
            target_modules=data_gap_modules,
            priority="high",
        ))

    # ── 规则2: 模块间信号冲突 → A0 矛盾论 ──
    module_directions: Dict[str, List[str]] = {}
    for card in cards:
        content = str(card.get("content", ""))
        direction = _detect_direction(content)
        if direction in ("bull", "bear", "mixed"):
            for mod in card.get("source_modules", []):
                module_directions.setdefault(mod, []).append(direction)

    has_bull = any("bull" in dirs for dirs in module_directions.values())
    has_bear = any("bear" in dirs for dirs in module_directions.values())
    if has_bull and has_bear:
        conflict_modules = [
            mod for mod, dirs in module_directions.items()
            if "bull" in dirs or "bear" in dirs
        ]
        hints.append(EnhancementHint(
            skill_key="A0",
            skill_name=SKILL_MAP["A0"],
            reason="多模块信号存在多空冲突, 需矛盾论分析识别主要矛盾",
            target_modules=conflict_modules,
            priority="high",
        ))

    # ── 规则3: 盘整/方向不明 → regime 检测 ──
    ranging_modules: List[str] = []
    for card in cards:
        content = str(card.get("content", ""))
        if _RANGING_PATTERNS.search(content):
            for mod in card.get("source_modules", []):
                if mod not in ranging_modules:
                    ranging_modules.append(mod)
    if ranging_modules and not has_bull and not has_bear:
        hints.append(EnhancementHint(
            skill_key="regime",
            skill_name=SKILL_MAP["regime"],
            reason="市场处于盘整/方向不明状态, 需识别当前 Regime",
            target_modules=ranging_modules,
            priority="medium",
        ))

    # ── 规则4: 整体低置信度 → A2 第一性原理 ──
    if overall_confidence is not None and overall_confidence < 0.4:
        hints.append(EnhancementHint(
            skill_key="A2",
            skill_name=SKILL_MAP["A2"],
            reason=f"整体置信度偏低 ({overall_confidence:.2f}), 需从第一性原理重新解析",
            target_modules=[],
            priority="medium",
        ))

    # 去重 (同 skill_key 只保留优先级最高的)
    seen: Dict[str, EnhancementHint] = {}
    for hint in hints:
        if hint.skill_key not in seen:
            seen[hint.skill_key] = hint
        else:
            # 合并 target_modules
            existing = seen[hint.skill_key]
            for m in hint.target_modules:
                if m not in existing.target_modules:
                    existing.target_modules.append(m)

    # 按优先级排序: high > medium > low
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(seen.values(), key=lambda h: priority_order.get(h.priority, 3))


def enhancement_hints_to_dicts(hints: List[EnhancementHint]) -> List[Dict[str, Any]]:
    """将 EnhancementHint 列表转为可序列化的 dict 列表"""
    return [h.to_dict() for h in hints]
