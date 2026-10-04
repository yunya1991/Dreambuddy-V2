"""N-P2 质量预测器蒸馏。

设计来源：千问 N-P2 质量预测器方案
核心思路：从 VerificationRecord 历史学习记忆特征 → 验证通过率 p 的映射，
用于预筛选低质量记忆，减少全量验证成本。

模型：基于实例的最近邻加权平均（无需 numpy，可解释，可增量训练）。
特征：age_days, verify_count, quality_level(C/B/A/S→0/1/2/3), content_length
预测：k 近邻的 p 加权平均（权重 = 1/(1+距离)）。

增强功能（N-P2 文档要求）：
- 影子模式：打分不影响排序
- 达标门：gold set 上 AUC/ECE
- 灰度放量：gray_traffic_pct% 流量使用预测器
- 5% 探索流量：始终包含抑制记忆
- PSI 漂移监控
- 审计日志

硬约束：
- 无训练数据时返回默认 p=0.5
- 输出始终 clamp 到 [0,1]
- 可导出/导入参数
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_QUALITY_ENCODE = {"C": 0.0, "B": 1.0, "A": 2.0, "S": 3.0}
_DEFAULT_P = 0.5
_K_NEIGHBORS = 5


@dataclass
class MemoryFeatures:
    """记忆特征向量。"""
    age_days: float = 0.0
    verify_count: int = 0
    quality_level: str = "C"
    content_length: int = 0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "MemoryFeatures":
        return cls(
            age_days=float(d.get("age_days", 0.0)),
            verify_count=int(d.get("verify_count", 0)),
            quality_level=str(d.get("quality_level", "C")),
            content_length=int(d.get("content_length", 0)),
        )

    def to_vector(self) -> List[float]:
        return [
            float(self.age_days),
            float(self.verify_count),
            _QUALITY_ENCODE.get(self.quality_level, 0.0),
            float(self.content_length),
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "age_days": self.age_days,
            "verify_count": self.verify_count,
            "quality_level": self.quality_level,
            "content_length": self.content_length,
        }


def _euclidean(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@dataclass
class QualityPredictor:
    """基于实例的质量预测器。"""
    _samples: List[Tuple[List[float], float]] = field(default_factory=list)
    _default_p: float = _DEFAULT_P
    _audit_log: List[Dict[str, Any]] = field(default_factory=list)

    def train(self, samples: List[Tuple[MemoryFeatures, float]]) -> None:
        """增量训练：追加 (features, p) 样本。"""
        for feat, p in samples:
            vec = feat.to_vector()
            self._samples.append((vec, max(0.0, min(1.0, p))))

    def predict(self, features: MemoryFeatures) -> float:
        """预测验证通过率 p ∈ [0,1]。"""
        if not self._samples:
            return self._default_p

        vec = features.to_vector()
        # 计算所有样本的距离
        distances = [(_euclidean(vec, s[0]), s[1]) for s in self._samples]
        distances.sort(key=lambda x: x[0])

        # k 近邻加权平均
        neighbors = distances[:_K_NEIGHBORS]
        weights = [1.0 / (1.0 + d) for d, _ in neighbors]
        total_w = sum(weights)
        if total_w <= 0:
            return self._default_p

        weighted_p = sum(w * p for w, (_, p) in zip(weights, neighbors))
        return max(0.0, min(1.0, weighted_p / total_w))

    def export_params(self) -> Dict[str, Any]:
        return {
            "samples": [
                {"vector": vec, "p": p} for vec, p in self._samples
            ],
            "default_p": self._default_p,
        }

    def import_params(self, params: Dict[str, Any]) -> None:
        self._samples = [
            (s["vector"], s["p"]) for s in params.get("samples", [])
        ]
        self._default_p = float(params.get("default_p", _DEFAULT_P))

    def sample_count(self) -> int:
        return len(self._samples)

    # ------------------------------------------------------------------
    # N-P2 增强：影子模式 + 灰度 + 探索流量 + 审计
    # ------------------------------------------------------------------

    def is_suppressed(
        self,
        features: Optional[MemoryFeatures],
        config: "ShadowModeConfig",
        memory_id: str = "",
    ) -> bool:
        """判断记忆是否应被抑制（不进默认 recall）。

        影子模式下始终返回 False（只打分不影响排序）。
        """
        if config.shadow_mode:
            suppressed = False
        else:
            p = self.predict(features) if features is not None else self._default_p
            suppressed = p < config.suppress_threshold

        # 审计日志
        self._audit_log.append({
            "memory_id": memory_id,
            "predicted_p": float(self.predict(features)) if features else self._default_p,
            "suppressed": suppressed,
            "shadow_mode": config.shadow_mode,
            "threshold": config.suppress_threshold,
            "ts": time.time(),
        })
        return suppressed

    def should_route_to_predictor(self, config: "ShadowModeConfig") -> bool:
        """灰度放量：判断本次请求是否路由到预测器。"""
        if config.gray_traffic_pct <= 0:
            return False
        if config.gray_traffic_pct >= 100:
            return True
        return random.random() * 100 < config.gray_traffic_pct

    def is_exploration_traffic(self, config: "ShadowModeConfig") -> bool:
        """5% 探索流量：被探索的请求会包含抑制记忆。"""
        if config.exploration_pct <= 0:
            return False
        return random.random() * 100 < config.exploration_pct

    def evaluate_on_gold_set(
        self, gold_set: List[Tuple[MemoryFeatures, float]]
    ) -> Dict[str, float]:
        """达标门：在 gold set 上计算 AUC 和 ECE。

        gold_set: [(features, actual_p), ...]，actual_p ∈ {0.0, 1.0}
        """
        if not gold_set:
            return {"auc": 0.0, "ece": 0.0}

        predictions = []
        actuals = []
        for feat, actual in gold_set:
            pred = self.predict(feat)
            predictions.append(pred)
            actuals.append(actual)

        return {
            "auc": self._compute_auc(predictions, actuals),
            "ece": self._compute_ece(predictions, actuals),
        }

    def passes_gate(
        self,
        gold_set: List[Tuple[MemoryFeatures, float]],
        min_auc: float = 0.6,
        max_ece: float = 0.15,
    ) -> bool:
        """达标门：AUC ≥ min_auc 且 ECE ≤ max_ece 时通过。"""
        metrics = self.evaluate_on_gold_set(gold_set)
        return metrics["auc"] >= min_auc and metrics["ece"] <= max_ece

    def get_audit_log(self) -> List[Dict[str, Any]]:
        return list(self._audit_log)

    @staticmethod
    def _compute_auc(predictions: List[float], actuals: List[float]) -> float:
        """计算 AUC（Area Under ROC Curve）。"""
        if len(set(actuals)) < 2:
            return 0.5  # 只有一类，AUC 无意义，返回 0.5
        # 按预测值降序排列
        pairs = sorted(zip(predictions, actuals), key=lambda x: x[0], reverse=True)
        n_pos = sum(1 for _, a in pairs if a >= 0.5)
        n_neg = len(pairs) - n_pos
        if n_pos == 0 or n_neg == 0:
            return 0.5
        tp = 0
        fp = 0
        auc = 0.0
        for _, actual in pairs:
            if actual >= 0.5:
                tp += 1
            else:
                fp += 1
                auc += tp  # 每个负样本贡献当前的 tp 数
        return auc / (n_pos * n_neg)

    @staticmethod
    def _compute_ece(predictions: List[float], actuals: List[float], n_bins: int = 10) -> float:
        """计算 ECE（Expected Calibration Error）。"""
        if not predictions:
            return 0.0
        bin_boundaries = [i / n_bins for i in range(n_bins + 1)]
        ece = 0.0
        n = len(predictions)
        for i in range(n_bins):
            lo, hi = bin_boundaries[i], bin_boundaries[i + 1]
            bin_preds = [p for p in predictions if lo <= p < hi or (i == n_bins - 1 and p == hi)]
            bin_actuals = [a for p, a in zip(predictions, actuals) if lo <= p < hi or (i == n_bins - 1 and p == hi)]
            if not bin_preds:
                continue
            avg_pred = sum(bin_preds) / len(bin_preds)
            avg_actual = sum(bin_actuals) / len(bin_actuals)
            ece += (len(bin_preds) / n) * abs(avg_pred - avg_actual)
        return ece


@dataclass
class ShadowModeConfig:
    """N-P2 影子模式 + 灰度配置。"""
    shadow_mode: bool = True  # 默认影子模式（只打分不影响排序）
    suppress_threshold: float = 0.3  # p < 阈值则抑制
    gray_traffic_pct: float = 0.0  # 灰度放量百分比（0-100）
    exploration_pct: float = 5.0  # 探索流量百分比（默认 5%）


class DriftMonitor:
    """PSI（Population Stability Index）漂移监控。"""

    def __init__(self, alert_threshold: float = 0.25):
        self.alert_threshold = alert_threshold

    def compute_psi(self, baseline: List[float], current: List[float]) -> float:
        """计算 PSI。

        PSI = Σ (current% - baseline%) * ln(current% / baseline%)
        """
        if len(baseline) != len(current):
            raise ValueError("baseline and current must have same length")
        # 归一化
        b_sum = sum(baseline)
        c_sum = sum(current)
        if b_sum == 0 or c_sum == 0:
            return 0.0
        b_norm = [x / b_sum for x in baseline]
        c_norm = [x / c_sum for x in current]

        psi = 0.0
        for b, c in zip(b_norm, c_norm):
            # 避免除零和 log(0)
            b_safe = max(b, 1e-6)
            c_safe = max(c, 1e-6)
            psi += (c_safe - b_safe) * math.log(c_safe / b_safe)
        return max(0.0, psi)

    def is_drifted(self, baseline: List[float], current: List[float]) -> bool:
        """PSI > alert_threshold 时判定为漂移。"""
        return self.compute_psi(baseline, current) > self.alert_threshold
