"""
DreamOS Evolution — 经验教训提炼器

职责:
    1. 从历史执行记录中自动提炼经验教训
    2. 识别常见错误模式
    3. 生成可复用的优化建议
    4. 按类别分组整理教训

教训类型:
    - strategy:    策略错误（方向判断错误）
    - risk:        风险控制问题（仓位/止损）
    - execution:   执行问题（节点失败/超时）
    - data:        数据问题（数据源缺失/异常）
    - budget:      预算问题（Token 不足）
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import Counter, defaultdict

from dreamos.shared.utils import gen_cycle_id
from dreamos.core.graph_store.types import HistoryEntry

from .types import Lesson


class LessonDistiller:
    """经验教训提炼器

    用法:
        distiller = LessonDistiller()
        lessons = distiller.distill(history_entries)
    """

    # 至少出现 N 次才认为是教训
    MIN_OCCURRENCES = 2
    # 最低置信度
    MIN_CONFIDENCE = 0.3

    def __init__(self, min_occurrences: int = 2):
        self._min_occ = min_occurrences
        self._lessons: List[Lesson] = []

    def distill(self, entries: List[HistoryEntry]) -> List[Lesson]:
        """从历史记录中提炼教训

        Args:
            entries: 历史执行记录列表

        Returns:
            提炼出的教训列表（按严重程度排序）
        """
        if not entries:
            return []

        lessons: List[Lesson] = []

        # ── 策略类教训 ──────────────────────────────
        strategy_lessons = self._distill_strategy_lessons(entries)
        lessons.extend(strategy_lessons)

        # ── 执行类教训 ──────────────────────────────
        execution_lessons = self._distill_execution_lessons(entries)
        lessons.extend(execution_lessons)

        # ── 预算类教训 ──────────────────────────────
        budget_lessons = self._distill_budget_lessons(entries)
        lessons.extend(budget_lessons)

        # 按严重程度 + 置信度排序
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        lessons.sort(
            key=lambda l: (-severity_order.get(l.severity, 0), -l.confidence)
        )

        self._lessons = lessons
        return lessons

    def _distill_strategy_lessons(self, entries: List[HistoryEntry]) -> List[Lesson]:
        """提炼策略类教训"""
        lessons = []

        # 分析方向判断的准确性
        actions = [e.final_action for e in entries if e.final_action and e.final_action != "HOLD"]
        if not actions:
            return lessons

        # 按意图类型分组
        by_intent = defaultdict(list)
        for e in entries:
            if e.intent_type and e.final_action:
                by_intent[e.intent_type].append(e)

        for intent, intent_entries in by_intent.items():
            if len(intent_entries) < self._min_occ:
                continue

            # 该意图下的成功率估算（用非 HOLD 比例近似）
            non_hold = [e for e in intent_entries if e.final_action != "HOLD"]
            if not non_hold:
                continue

            avg_conf = sum(e.final_confidence for e in intent_entries) / len(intent_entries)

            # 低置信度 + 频繁 HOLD → 该意图识别有问题
            hold_rate = len([e for e in intent_entries if e.final_action == "HOLD"]) / len(intent_entries)
            if hold_rate > 0.5 and len(intent_entries) >= self._min_occ:
                lessons.append(Lesson(
                    lesson_id=gen_cycle_id("lesson_strategy_hold"),
                    title=f"{intent} 意图方向不确定性高",
                    description=f"在 {len(intent_entries)} 次 {intent} 场景中，HOLD 比例达 {hold_rate:.0%}，平均置信度 {avg_conf:.1%}",
                    category="strategy",
                    severity="medium",
                    context={"intent": intent, "hold_rate": hold_rate, "count": len(intent_entries)},
                    action_suggestion=f"考虑为 {intent} 场景增加更多数据源或优化节点链路",
                    confidence=min(hold_rate, 0.9),
                ))

            # 低置信度警告
            if avg_conf < 0.4 and len(intent_entries) >= self._min_occ:
                lessons.append(Lesson(
                    lesson_id=gen_cycle_id("lesson_strategy_conf"),
                    title=f"{intent} 意图置信度偏低",
                    description=f"{intent} 场景平均置信度仅 {avg_conf:.1%}",
                    category="strategy",
                    severity="low",
                    context={"intent": intent, "avg_confidence": avg_conf},
                    action_suggestion="建议补充相关训练数据或调整节点权重",
                    confidence=0.5,
                ))

        return lessons

    def _distill_execution_lessons(self, entries: List[HistoryEntry]) -> List[Lesson]:
        """提炼执行类教训"""
        lessons = []

        # 成功率分析
        success_rates = [e.success_rate for e in entries if e.success_rate > 0]
        if success_rates:
            avg_success = sum(success_rates) / len(success_rates)

            if avg_success < 0.7 and len(entries) >= self._min_occ:
                lessons.append(Lesson(
                    lesson_id=gen_cycle_id("lesson_exec_success"),
                    title="节点执行成功率偏低",
                    description=f"平均成功率 {avg_success:.1%}",
                    category="execution",
                    severity="high",
                    context={"avg_success_rate": avg_success, "total": len(entries)},
                    action_suggestion="检查节点依赖和数据源稳定性，增加降级策略",
                    confidence=0.7,
                ))

        # 提前终止分析
        early_count = sum(1 for e in entries if e.early_terminated)
        if early_count > 0 and len(entries) >= self._min_occ:
            early_rate = early_count / len(entries)
            if early_rate > 0.3:
                lessons.append(Lesson(
                    lesson_id=gen_cycle_id("lesson_exec_early"),
                    title="提前终止比例较高",
                    description=f"{early_rate:.0%} 的执行被提前终止",
                    category="execution",
                    severity="low",
                    context={"early_count": early_count, "early_rate": early_rate},
                    action_suggestion="检查是否反射决策过于激进，或节点数量过多",
                    confidence=0.5,
                ))

        return lessons

    def _distill_budget_lessons(self, entries: List[HistoryEntry]) -> List[Lesson]:
        """提炼预算类教训"""
        lessons = []

        token_usages = [e.total_tokens for e in entries if e.total_tokens > 0]
        if not token_usages:
            return lessons

        avg_tokens = sum(token_usages) / len(token_usages)
        max_tokens = max(token_usages)

        # 高 Token 消耗警告
        if avg_tokens > 5000 and len(entries) >= self._min_occ:
            lessons.append(Lesson(
                lesson_id=gen_cycle_id("lesson_budget_high"),
                title="Token 消耗偏高",
                description=f"平均 Token 消耗 {avg_tokens:.0f}，最高 {max_tokens}",
                category="budget",
                severity="medium",
                context={"avg_tokens": avg_tokens, "max_tokens": max_tokens},
                action_suggestion="考虑切换到 lean 模式，或优化 LLM prompt 长度",
                confidence=0.6,
            ))

        return lessons

    @property
    def lessons(self) -> List[Lesson]:
        """已提炼的教训"""
        return list(self._lessons)
