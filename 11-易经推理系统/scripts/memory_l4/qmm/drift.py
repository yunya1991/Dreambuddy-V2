"""漂移监控：PSI（分布漂移） + 性能漂移检测。"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .types import CleanedEvent


@dataclass
class DriftReport:
    drift_detected: bool
    drift_type: str  # "DISTRIBUTION" / "PERFORMANCE" / "NONE"
    severity: float  # 0-1
    psi_x: float
    performance_drift: float
    recommendation: str  # "RECALIBRATE" / "NO_ACTION"
    details: Dict[str, Any] = field(default_factory=dict)


class DriftMonitor:
    """漂移监控器。

    检测项：
    1. 象限分布漂移（PSI）
    2. 性能漂移（Z-score of recent pnl vs baseline）
    """

    def __init__(
        self,
        psi_threshold: float = 0.2,
        perf_z_threshold: float = 2.0,
        recent_window: int = 10,
    ):
        self.psi_threshold = psi_threshold
        self.perf_z_threshold = perf_z_threshold
        self.recent_window = recent_window

    def check_drift(
        self,
        events: List[CleanedEvent],
        baseline_stats: Dict[str, Any],
    ) -> DriftReport:
        """综合漂移检查。"""
        if len(events) < 3:
            return DriftReport(
                drift_detected=False,
                drift_type="NONE",
                severity=0.0,
                psi_x=0.0,
                performance_drift=0.0,
                recommendation="NO_ACTION",
                details={"status": "INSUFFICIENT_DATA"},
            )

        # 分布漂移（象限 x 分布 PSI）
        current_x_dist = self._bin_quadrant_x(events)
        baseline_x_dist = baseline_stats.get("x_distribution", {})
        psi_x = self._compute_psi(baseline_x_dist, current_x_dist)

        # 性能漂移
        recent = events[-self.recent_window:]
        recent_pnls = [e.pnl_pct for e in recent if e.pnl_pct is not None]
        perf_drift = self._detect_performance_drift(
            recent_pnls,
            baseline_stats.get("pnl_mean", 0),
            baseline_stats.get("pnl_std", 1),
        )

        # 综合判断
        drift_detected = (
            psi_x >= self.psi_threshold
            or perf_drift >= self.perf_z_threshold
        )

        if psi_x >= self.psi_threshold:
            drift_type = "DISTRIBUTION"
        elif perf_drift >= self.perf_z_threshold:
            drift_type = "PERFORMANCE"
        else:
            drift_type = "NONE"

        severity = round(
            max(psi_x / self.psi_threshold, perf_drift / self.perf_z_threshold),
            4,
        )

        recommendation = "RECALIBRATE" if drift_detected else "NO_ACTION"

        return DriftReport(
            drift_detected=drift_detected,
            drift_type=drift_type,
            severity=min(1.0, severity),
            psi_x=psi_x,
            performance_drift=perf_drift,
            recommendation=recommendation,
        )

    def _bin_quadrant_x(self, events: List[CleanedEvent]) -> Dict[str, float]:
        """将象限 x 值分箱为分布。"""
        bins = {"negative": 0, "neutral": 0, "positive": 0}
        for ev in events:
            if ev.quadrant_x < -0.1:
                bins["negative"] += 1
            elif ev.quadrant_x > 0.1:
                bins["positive"] += 1
            else:
                bins["neutral"] += 1
        total = sum(bins.values())
        if total == 0:
            return {"negative": 0.333, "neutral": 0.333, "positive": 0.334}
        return {k: v / total for k, v in bins.items()}

    def _compute_psi(
        self,
        expected_dist: Dict[str, float],
        actual_dist: Dict[str, float],
    ) -> float:
        """PSI = Σ (actual_i - expected_i) * ln(actual_i / expected_i)

        解释:
        - PSI < 0.1: 无显著变化
        - 0.1 <= PSI < 0.2: 中度变化
        - PSI >= 0.2: 显著变化 → 漂移检测
        """
        psi = 0.0
        all_keys = set(expected_dist.keys()) | set(actual_dist.keys())
        for key in all_keys:
            expected = expected_dist.get(key, 0.0) or 0.001
            actual = actual_dist.get(key, 0.0) or 0.001
            psi += (actual - expected) * math.log(actual / expected)
        return round(max(0, psi), 4)

    def _detect_performance_drift(
        self,
        recent_pnls: List[float],
        baseline_mean: float,
        baseline_std: float,
    ) -> float:
        """Z-score of recent mean vs baseline。"""
        if not recent_pnls or baseline_std == 0:
            return 0.0

        import statistics as _stats
        recent_mean = _stats.mean(recent_pnls)
        z_score = abs(recent_mean - baseline_mean) / baseline_std
        return round(z_score, 4)

    def build_baseline_stats(
        self, events: List[CleanedEvent]
    ) -> Dict[str, Any]:
        """从历史数据构建基线统计。"""
        if not events:
            return {}

        pnls = [e.pnl_pct for e in events if e.pnl_pct is not None]
        pnl_mean = sum(pnls) / max(len(pnls), 1)
        pnl_std = 0.0
        if len(pnls) >= 2:
            pnl_std = math.sqrt(
                sum((p - pnl_mean) ** 2 for p in pnls) / (len(pnls) - 1)
            )

        return {
            "x_distribution": self._bin_quadrant_x(events),
            "pnl_mean": round(pnl_mean, 4),
            "pnl_std": round(max(pnl_std, 0.001), 4),
            "total_events": len(events),
        }
