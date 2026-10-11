"""训练效果评估与反馈闭环。

SPEC §2.3 辅导评估:
  - 辅导质量分(0-100): 训练结果与33-REA解析的一致度
  - 纠正次数: Trae介入纠正的次数
  - 训练成果提升: 前端系统输出质量的前后对比

P4 功能:
  - TrainingMetrics: 辅导质量分+纠正次数+提升幅度
  - PatternMiner: 跨案例模式挖掘
  - FeedbackLoop: 质量反馈到CaseIngestGate阈值调整
"""
from collections import Counter
from typing import Dict, List, Tuple, Optional


class TrainingMetrics:
    """训练效果度量。"""

    def __init__(self):
        self._before_score: float = 0.0
        self._after_score: float = 0.0
        self._corrections: List[dict] = []

    def calculate_quality_score(
        self,
        rea_patterns: List[str],
        trained_patterns: List[str],
        rea_call_chain: List[str],
        trained_call_chain: List[str],
    ) -> float:
        """计算辅导质量分 (0-100)。

        一致度 = (pattern一致度 + call_chain一致度) / 2
        """
        # Pattern 一致度: Jaccard 系数
        rea_set = set(rea_patterns)
        trained_set = set(trained_patterns)
        if rea_set or trained_set:
            intersection = rea_set & trained_set
            union = rea_set | trained_set
            pattern_score = len(intersection) / len(union) * 100
        else:
            pattern_score = 100.0

        # Call chain 一致度: 序列匹配率
        if rea_call_chain or trained_call_chain:
            rea_chain_set = set(rea_call_chain)
            trained_chain_set = set(trained_call_chain)
            intersection = rea_chain_set & trained_chain_set
            union = rea_chain_set | trained_chain_set
            chain_score = len(intersection) / len(union) * 100
        else:
            chain_score = 100.0

        return round((pattern_score + chain_score) / 2, 2)

    def record_correction(self, correction_type: str, description: str) -> None:
        """记录一次纠正。"""
        self._corrections.append({
            "type": correction_type,
            "description": description,
        })

    def get_correction_count(self) -> int:
        """获取纠正次数。"""
        return len(self._corrections)

    def get_corrections(self) -> List[dict]:
        """获取所有纠正记录。"""
        return self._corrections

    def set_before_score(self, score: float) -> None:
        """设置训练前质量分。"""
        self._before_score = score

    def set_after_score(self, score: float) -> None:
        """设置训练后质量分。"""
        self._after_score = score

    def get_improvement_delta(self) -> float:
        """获取训练成果提升幅度。"""
        return round(self._after_score - self._before_score, 2)

    def is_improved(self) -> bool:
        """是否提升。"""
        return self._after_score > self._before_score


class PatternMiner:
    """跨案例模式挖掘。"""

    def mine_common_patterns(self, cases: List[dict]) -> Dict[str, int]:
        """从多案例中挖掘共同模式，返回模式→出现次数。"""
        counter: Counter = Counter()
        for case in cases:
            patterns = case.get("patterns", [])
            for p in patterns:
                counter[p] += 1
        return dict(counter)

    def mine_top_patterns(
        self, cases: List[dict], top_n: int = 5
    ) -> List[Tuple[str, int]]:
        """获取 Top-N 频繁模式。"""
        common = self.mine_common_patterns(cases)
        sorted_patterns = sorted(common.items(), key=lambda x: x[1], reverse=True)
        return sorted_patterns[:top_n]


class FeedbackLoop:
    """训练质量反馈到 CaseIngestGate 阈值调整。

    高质量训练连续出现 → 放宽阈值（更多案例入库）
    低质量训练连续出现 → 收紧阈值（更严格筛选）
    """

    def __init__(
        self,
        initial_novelty_threshold: float = 0.6,
        initial_significance_threshold: float = 0.05,
        adjustment_step: float = 0.02,
        min_novelty: float = 0.3,
        max_novelty: float = 0.9,
    ):
        self._novelty_threshold = initial_novelty_threshold
        self._significance_threshold = initial_significance_threshold
        self._adjustment_step = adjustment_step
        self._min_novelty = min_novelty
        self._max_novelty = max_novelty
        self._quality_history: List[float] = []

    def record_training_quality(self, quality_score: float) -> None:
        """记录一次训练质量分。"""
        self._quality_history.append(quality_score)

    def get_adjusted_thresholds(self) -> Dict[str, float]:
        """根据历史训练质量获取调整后的阈值。"""
        if len(self._quality_history) < 2:
            return {
                "novelty_threshold": self._novelty_threshold,
                "significance_threshold": self._significance_threshold,
            }

        # 计算最近几次的平均质量
        recent = self._quality_history[-5:]
        avg_quality = sum(recent) / len(recent)

        if avg_quality >= 70:
            # 高质量 → 放宽阈值（降低，更多案例入库）
            new_novelty = max(
                self._min_novelty,
                self._novelty_threshold - self._adjustment_step,
            )
        elif avg_quality < 40:
            # 低质量 → 收紧阈值（提高，更严格筛选）
            new_novelty = min(
                self._max_novelty,
                self._novelty_threshold + self._adjustment_step,
            )
        else:
            new_novelty = self._novelty_threshold

        return {
            "novelty_threshold": round(new_novelty, 3),
            "significance_threshold": self._significance_threshold,
        }

    def get_quality_history(self) -> List[float]:
        """获取训练质量历史。"""
        return self._quality_history

    # ========================================================
    # v0.5 P2.4: 调优 microBatch + capacity + λ
    # ========================================================

    def get_tuning_recommendations(
        self,
        layer: str,
        current_micro_batch: int,
        current_capacity: int,
        current_lambda: float,
    ) -> Dict[str, float]:
        """根据训练质量历史返回调优建议。

        高质量 (avg≥70) → 放宽：更大微批 + 更大容量 + 更高λ（保留更多历史）
        低质量 (avg<40) → 收紧：更小微批 + 更小容量 + 更低λ（快速遗忘旧模式）
        中等质量 → 保持当前值不变
        """
        if len(self._quality_history) < 2:
            return {
                "micro_batch": current_micro_batch,
                "capacity": current_capacity,
                "lambda": current_lambda,
            }

        recent = self._quality_history[-5:]
        avg_quality = sum(recent) / len(recent)

        if avg_quality >= 70:
            return {
                "micro_batch": min(current_micro_batch + 1, 20),
                "capacity": min(int(current_capacity * 1.1), 1000),
                "lambda": round(min(current_lambda + 0.01, 0.99), 4),
            }
        elif avg_quality < 40:
            return {
                "micro_batch": max(current_micro_batch - 1, 2),
                "capacity": max(int(current_capacity * 0.9), 50),
                "lambda": round(max(current_lambda - 0.01, 0.80), 4),
            }
        else:
            return {
                "micro_batch": current_micro_batch,
                "capacity": current_capacity,
                "lambda": current_lambda,
            }
