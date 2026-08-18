"""过拟合检测：train/test gap + fold 方差 + regime 过拟合。"""

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .backtest import BacktestResult


@dataclass
class OverfitReport:
    is_overfit: bool
    train_test_gap: float
    fold_variance: float
    regime_max_gap: float
    recommendation: str  # "SIMPLIFY" / "ACCEPT"
    details: Dict[str, Any] = field(default_factory=dict)


class OverfittingDetector:
    """过拟合检测器。

    检查项：
    1. train/test gap > 10% → 过拟合
    2. fold 间方差大 → 不稳定
    3. 单一 regime 准确率远高于其他 → regime 过拟合
    """

    def __init__(
        self,
        gap_threshold: float = 0.10,
        fold_var_threshold: float = 0.01,
        regime_gap_threshold: float = 0.50,
        min_regime_samples: int = 5,
    ):
        self.gap_threshold = gap_threshold
        self.fold_var_threshold = fold_var_threshold
        self.regime_gap_threshold = regime_gap_threshold
        self.min_regime_samples = min_regime_samples

    def detect(self, result: BacktestResult) -> OverfitReport:
        """执行过拟合检测。"""
        gap = result.train_test_gap

        fold_var = 0.0
        if len(result.fold_accuracies) >= 2:
            fold_var = statistics.variance(result.fold_accuracies)

        # Regime 过拟合检测
        regime_max_gap = self._compute_regime_gap(result.by_regime)

        is_overfit = (
            gap > self.gap_threshold
            or fold_var > self.fold_var_threshold
            or regime_max_gap > self.regime_gap_threshold
        )

        recommendation = "SIMPLIFY" if is_overfit else "ACCEPT"

        details = {
            "gap_check": "FAIL" if gap > self.gap_threshold else "PASS",
            "fold_var_check": (
                "FAIL" if fold_var > self.fold_var_threshold else "PASS"
            ),
            "regime_check": (
                "FAIL" if regime_max_gap > self.regime_gap_threshold else "PASS"
            ),
        }

        return OverfitReport(
            is_overfit=is_overfit,
            train_test_gap=round(gap, 4),
            fold_variance=round(fold_var, 6),
            regime_max_gap=round(regime_max_gap, 4),
            recommendation=recommendation,
            details=details,
        )

    def _compute_regime_gap(self, by_regime: Dict[str, List[float]]) -> float:
        """计算各 regime 准确率的最大差距（忽略小样本）。"""
        if not by_regime:
            return 0.0

        accuracies = []
        for reg, accs in by_regime.items():
            if accs:
                accuracies.append(accs[0])

        if len(accuracies) < 2:
            return 0.0

        return max(accuracies) - min(accuracies)
