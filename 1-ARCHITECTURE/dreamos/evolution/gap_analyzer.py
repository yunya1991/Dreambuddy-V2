"""
DreamOS Evolution — 知行差距分析器

职责:
    1. 分析"计划的"和"实际发生的"之间的差距
    2. 多维度评分（意图/规划/方向/置信度）
    3. 生成改进建议

gap_score: 0-1 之间，越小越好
    0.0 = 完全知行合一
    1.0 = 完全背离
"""

from __future__ import annotations

from typing import Dict, List, Optional, Any
from collections import defaultdict

from dreamos.core.graph_store.types import HistoryEntry

from .types import GapAnalysis


class GapAnalyzer:
    """知行差距分析器

    用法:
        analyzer = GapAnalyzer()
        result = analyzer.analyze(history_entries)
        print(result.overall_gap_score)  # 0.35
    """

    def __init__(self):
        self._weights = {
            "intent": 0.2,       # 意图识别权重
            "plan": 0.2,         # 计划完成权重
            "direction": 0.35,   # 方向判断权重
            "confidence": 0.25,  # 置信度校准权重
        }

    def analyze(self, entries: List[HistoryEntry]) -> GapAnalysis:
        """分析知行差距

        Args:
            entries: 历史执行记录

        Returns:
            GapAnalysis: 分析结果
        """
        if not entries:
            return GapAnalysis()

        gaps: List[Dict[str, Any]] = []
        insights: List[str] = []

        # 1. 意图准确性（同一意图下方向一致性）
        intent_acc = self._analyze_intent_accuracy(entries, gaps, insights)

        # 2. 计划完成率
        plan_rate = self._analyze_plan_completion(entries, gaps, insights)

        # 3. 方向一致性（同一市场条件下方向是否一致）
        dir_acc = self._analyze_direction_consistency(entries, gaps, insights)

        # 4. 置信度校准（高置信度是否对应高成功率）
        conf_cal = self._analyze_confidence_calibration(entries, gaps, insights)

        # 计算总分
        w = self._weights
        overall = (
            intent_acc * w["intent"] +
            plan_rate * w["plan"] +
            dir_acc * w["direction"] +
            conf_cal * w["confidence"]
        )

        # gap_score = 1 - 准确率，越小越好
        overall_gap = 1.0 - overall

        return GapAnalysis(
            overall_gap_score=round(overall_gap, 3),
            intent_accuracy=round(intent_acc, 3),
            plan_completion_rate=round(plan_rate, 3),
            direction_accuracy=round(dir_acc, 3),
            confidence_calibration=round(conf_cal, 3),
            gaps=gaps,
            top_insights=insights[:5],
        )

    def _analyze_intent_accuracy(self, entries, gaps, insights) -> float:
        """分析意图识别准确性"""
        by_intent = defaultdict(list)
        for e in entries:
            if e.intent_type and e.final_confidence > 0:
                by_intent[e.intent_type].append(e)

        if not by_intent:
            return 0.5

        accuracies = []
        for intent, intent_entries in by_intent.items():
            # 用非 HOLD 率作为意图识别有效性的代理指标
            non_hold = [e for e in intent_entries if e.final_action != "HOLD"]
            rate = len(non_hold) / len(intent_entries) if intent_entries else 0
            accuracies.append(rate)

            if rate < 0.5:
                gaps.append({
                    "type": "intent",
                    "intent": intent,
                    "non_hold_rate": rate,
                    "description": f"{intent} 意图产生有效方向的比例低",
                })

        avg_acc = sum(accuracies) / len(accuracies) if accuracies else 0.5

        if avg_acc < 0.6:
            insights.append(f"整体意图有效率偏低 ({avg_acc:.0%})，建议优化 S 层识别器")

        return min(avg_acc, 1.0)

    def _analyze_plan_completion(self, entries, gaps, insights) -> float:
        """分析计划完成率"""
        if not entries:
            return 0.5

        # 用节点成功率和非提前终止率作为计划完成度代理
        success_rates = [e.success_rate for e in entries if e.success_rate > 0]
        avg_success = sum(success_rates) / len(success_rates) if success_rates else 0.5

        normal = sum(1 for e in entries if not e.early_terminated)
        normal_rate = normal / len(entries) if entries else 0.5

        completion = (avg_success + normal_rate) / 2

        if completion < 0.7:
            gaps.append({
                "type": "plan",
                "completion": completion,
                "description": f"计划完成率偏低 ({completion:.0%})",
            })
            insights.append("计划完成率不足 70%，建议检查节点依赖和稳定性")

        return min(completion, 1.0)

    def _analyze_direction_consistency(self, entries, gaps, insights) -> float:
        """分析方向一致性（相似场景方向是否一致）"""
        by_intent = defaultdict(list)
        for e in entries:
            if e.intent_type and e.final_action in ("LONG", "SHORT"):
                by_intent[e.intent_type].append(e.final_action)

        if not by_intent:
            return 0.5

        consistency_scores = []
        for intent, actions in by_intent.items():
            if len(actions) < 2:
                continue
            # 多数方向的比例
            counts = defaultdict(int)
            for a in actions:
                counts[a] += 1
            majority = max(counts.values())
            score = majority / len(actions)
            consistency_scores.append(score)

            if score < 0.6:
                gaps.append({
                    "type": "direction",
                    "intent": intent,
                    "consistency": score,
                    "description": f"{intent} 场景方向判断不一致",
                })

        avg_cons = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 0.5

        if avg_cons < 0.6:
            insights.append(f"方向一致性偏低 ({avg_cons:.0%})，相同场景结论不统一")

        return min(avg_cons, 1.0)

    def _analyze_confidence_calibration(self, entries, gaps, insights) -> float:
        """分析置信度校准（高置信度是否对应高确定性）"""
        # 简化：用置信度方差和中位数评估
        confidences = [e.final_confidence for e in entries if e.final_confidence > 0]
        if not confidences:
            return 0.5

        avg_conf = sum(confidences) / len(confidences)
        # 计算方差
        variance = sum((c - avg_conf) ** 2 for c in confidences) / len(confidences)
        std_dev = variance ** 0.5

        # 校准度: 方差越小 + 平均越高 = 校准越好
        calibration = max(0, avg_conf - std_dev * 0.5)

        if std_dev > 0.3:
            gaps.append({
                "type": "confidence",
                "avg_confidence": avg_conf,
                "std_dev": std_dev,
                "description": f"置信度波动大 (σ={std_dev:.2f})",
            })

        if avg_conf < 0.5:
            insights.append(f"整体置信度偏低 ({avg_conf:.1%})，系统不够自信")

        return max(0, min(calibration, 1.0))
