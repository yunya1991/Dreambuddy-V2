"""门禁系统：回测 + 过拟合检测 + 漂移监控。"""

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .backtest import BacktestResult, Backtester
from .drift import DriftMonitor, DriftReport
from .overfitting import OverfitReport, OverfittingDetector
from .paths import qmm_dir
from .types import CleanedEvent


@dataclass
class GateResult:
    backtest: Optional[BacktestResult]
    overfitting: Optional[OverfitReport]
    drift: Optional[DriftReport]
    passed: bool
    reason_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        backtest = None
        if self.backtest is not None:
            backtest = {
                "total_predictions": self.backtest.total_predictions,
                "overall_accuracy": self.backtest.overall_accuracy,
                "high_confidence_accuracy": self.backtest.high_confidence_accuracy,
                "fold_accuracies": self.backtest.fold_accuracies,
                "train_test_gap": self.backtest.train_test_gap,
                "by_regime": self.backtest.by_regime,
            }

        overfitting = None
        if self.overfitting is not None:
            overfitting = {
                "is_overfit": self.overfitting.is_overfit,
                "train_test_gap": self.overfitting.train_test_gap,
                "fold_variance": self.overfitting.fold_variance,
                "regime_max_gap": self.overfitting.regime_max_gap,
                "recommendation": self.overfitting.recommendation,
            }

        drift = None
        if self.drift is not None:
            drift = {
                "drift_detected": self.drift.drift_detected,
                "drift_type": self.drift.drift_type,
                "severity": self.drift.severity,
                "psi_x": self.drift.psi_x,
                "performance_drift": self.drift.performance_drift,
                "recommendation": self.drift.recommendation,
            }

        return {
            "passed": self.passed,
            "reason_codes": self.reason_codes,
            "backtest": backtest,
            "overfitting": overfitting,
            "drift": drift,
        }


class GateRunner:
    """门禁执行器。

    门禁通过条件：
    1. 方向预测准确率 > 55%
    2. 高置信度子集准确率 > 65% (uncertainty < 0.3)
    3. 跨 regime 准确率 > 50% 每个 regime
    4. train/test gap < 10%
    5. 无显著过拟合
    6. 无漂移
    """

    # 阈值常量
    ACCURACY_THRESHOLD = 0.55
    HIGH_CONF_ACCURACY_THRESHOLD = 0.65
    REGIME_ACCURACY_THRESHOLD = 0.50
    GAP_THRESHOLD = 0.10

    def __init__(
        self,
        n_folds: int = 5,
        min_train: int = 10,
        min_test: int = 5,
        xgb_mode: bool = False,
        raw_cases: Optional[List[Dict]] = None,
    ):
        self.backtester = Backtester(
            n_folds=n_folds,
            min_train=min_train,
            min_test=min_test,
            xgb_mode=xgb_mode,
            raw_cases=raw_cases,
        )
        self.overfit_detector = OverfittingDetector(
            gap_threshold=self.GAP_THRESHOLD,
        )
        self.drift_monitor = DriftMonitor()

    def run(
        self,
        events: List[CleanedEvent],
        baseline_stats: Optional[Dict[str, Any]] = None,
    ) -> GateResult:
        """执行完整门禁检查。

        如果 baseline_stats 为空，用前 60% 数据构建基线。
        """
        # 1. 回测
        bt = self.backtester.run(events)

        # 2. 过拟合检测
        of = self.overfit_detector.detect(bt)

        # 3. 漂移检测
        if baseline_stats is None and len(events) >= 10:
            split_idx = int(len(events) * 0.6)
            baseline_stats = self.drift_monitor.build_baseline_stats(
                events[:split_idx],
            )
            drift_events = events[split_idx:]
        else:
            drift_events = events

        dr = self.drift_monitor.check_drift(drift_events, baseline_stats or {})

        # 4. 综合判断
        passed, reason_codes = self._evaluate(bt, of, dr)

        return GateResult(
            backtest=bt,
            overfitting=of,
            drift=dr,
            passed=passed,
            reason_codes=reason_codes,
        )

    def _evaluate(
        self,
        bt: BacktestResult,
        of: OverfitReport,
        dr: DriftReport,
    ) -> tuple:
        """判断是否通过门禁。"""
        reason_codes: List[str] = []

        # 准确率检查
        if bt.overall_accuracy <= self.ACCURACY_THRESHOLD:
            reason_codes.append("LOW_ACCURACY")

        # 高置信度子集检查
        if (
            bt.high_confidence_accuracy > 0
            and bt.high_confidence_accuracy <= self.HIGH_CONF_ACCURACY_THRESHOLD
        ):
            reason_codes.append("LOW_HIGH_CONF_ACCURACY")

        # 跨 regime 检查
        for reg, accs in bt.by_regime.items():
            if accs and accs[0] <= self.REGIME_ACCURACY_THRESHOLD:
                reason_codes.append(f"LOW_REGIME_ACCURACY_{reg.upper()}")

        # 过拟合检查
        if of.is_overfit:
            reason_codes.append("OVERFITTING_DETECTED")

        # 漂移检查
        if dr.drift_detected:
            reason_codes.append("DRIFT_DETECTED")

        passed = len(reason_codes) == 0
        return passed, reason_codes

    def save_gate_result(self, gate_result: GateResult) -> None:
        """将门禁结果写入 signals_index.json。"""
        out_dir = qmm_dir()
        out_dir.mkdir(parents=True, exist_ok=True)

        index_path = out_dir / "signals_index.json"
        if index_path.exists():
            data = json.loads(index_path.read_text(encoding="utf-8"))
        else:
            data = {}

        data["gate_status"] = "PASSED" if gate_result.passed else "FAILED"
        data["gate_results"] = gate_result.to_dict()

        index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
