"""回测框架：Walk-Forward 验证，支持 XGBoost 小模型预测。"""

import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .types import CleanedEvent


@dataclass
class Prediction:
    event_id: str
    predicted_direction: str  # "UP" / "DOWN" / "FLAT"
    actual_direction: str
    correct: bool
    regime: str
    uncertainty: float = 0.5


@dataclass
class FoldResult:
    fold_id: int
    train_size: int
    test_size: int
    predictions: List[Prediction] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        if not self.predictions:
            return 0.0
        return sum(1 for p in self.predictions if p.correct) / len(self.predictions)


@dataclass
class BacktestResult:
    total_predictions: int
    overall_accuracy: float
    fold_accuracies: List[float] = field(default_factory=list)
    fold_results: List[FoldResult] = field(default_factory=list)
    train_test_gap: float = 0.0
    by_regime: Dict[str, List[float]] = field(default_factory=dict)
    high_confidence_accuracy: float = 0.0


class Backtester:
    """Walk-Forward 回测执行器。

    支持两种预测模式：
    1. xgb_mode：用 XGBoost 在 train fold 上训练，在 test fold 上预测
    2. rule_mode（默认）：用基于基线的规则预测（向后兼容）
    """

    def __init__(
        self,
        n_folds: int = 5,
        min_train: int = 10,
        min_test: int = 5,
        xgb_mode: bool = False,
        raw_cases: Optional[List[Dict]] = None,
    ):
        self.n_folds = n_folds
        self.min_train = min_train
        self.min_test = min_test
        self.xgb_mode = xgb_mode
        self.raw_cases = raw_cases  # XGBoost 模式需要原始 case dict

    def run(self, events: List[CleanedEvent]) -> BacktestResult:
        """执行 walk-forward 回测。"""
        folds = self._split_folds(events)
        fold_results: List[FoldResult] = []

        # XGBoost 模式：需要 raw_cases 且数量匹配
        if self.xgb_mode and self.raw_cases and len(self.raw_cases) >= len(events):
            return self._run_xgb_backtest(events, folds)

        # 规则模式（向后兼容）
        for fold_id, (train, test) in enumerate(folds, 1):
            baseline = self._compute_baseline(train)
            predictions = []
            for ev in test:
                pred_dir, unc = self._predict_direction(ev, baseline)
                actual_dir = "UP" if ev.pnl_pct and ev.pnl_pct > 0.01 else (
                    "DOWN" if ev.pnl_pct is not None and ev.pnl_pct < -0.01 else "FLAT"
                )
                predictions.append(Prediction(
                    event_id=ev.event_id,
                    predicted_direction=pred_dir,
                    actual_direction=actual_dir,
                    correct=pred_dir == actual_dir,
                    regime=ev.regime,
                    uncertainty=unc,
                ))

            fr = FoldResult(
                fold_id=fold_id,
                train_size=len(train),
                test_size=len(test),
                predictions=predictions,
            )
            fold_results.append(fr)

        return self._aggregate(fold_results)

    def _run_xgb_backtest(
        self,
        events: List[CleanedEvent],
        folds: List[Tuple[List[CleanedEvent], List[CleanedEvent]]],
    ) -> BacktestResult:
        """XGBoost walk-forward 回测。"""
        from .xgb_predictor import QMMPredictor, extract_features_from_case, extract_label_from_case
        import numpy as np

        # 构建 event_id → case 映射
        case_by_id = {}
        for c in self.raw_cases:
            cid = c.get("case_id", "")
            if cid:
                case_by_id[cid] = c

        # event_id 有序列表
        event_ids = [e.event_id for e in events]
        id_to_idx = {eid: i for i, eid in enumerate(event_ids)}

        fold_results: List[FoldResult] = []

        last_predictor = None
        last_train_events = None

        for fold_id, (train_events, test_events) in enumerate(folds, 1):
            # 收集训练数据
            train_cases = []
            for ev in train_events:
                c = case_by_id.get(ev.event_id)
                if c:
                    train_cases.append(c)

            # 训练 XGBoost
            predictor = QMMPredictor()
            train_stats = predictor.train(train_cases, n_folds=2)
            if not train_stats.get("ok"):
                # 退化为规则预测
                baseline = self._compute_baseline(train_events)
                predictions = []
                for ev in test_events:
                    pred_dir, unc = self._predict_direction(ev, baseline)
                    actual_dir = "UP" if ev.pnl_pct and ev.pnl_pct > 0 else (
                        "DOWN" if ev.pnl_pct is not None and ev.pnl_pct < 0 else "FLAT"
                    )
                    predictions.append(Prediction(
                        event_id=ev.event_id,
                        predicted_direction=pred_dir,
                        actual_direction=actual_dir,
                        correct=pred_dir == actual_dir,
                        regime=ev.regime,
                        uncertainty=unc,
                    ))
                fold_results.append(FoldResult(
                    fold_id=fold_id,
                    train_size=len(train_events),
                    test_size=len(test_events),
                    predictions=predictions,
                ))
                continue

            # 在 test 上预测
            predictions = []
            for ev in test_events:
                c = case_by_id.get(ev.event_id)
                if c:
                    pred_dir, unc = predictor.predict(c)
                else:
                    # 无 case 数据，退化为象限预测
                    if ev.quadrant_x > 0.1:
                        pred_dir = "UP"
                    elif ev.quadrant_x < -0.1:
                        pred_dir = "DOWN"
                    else:
                        pred_dir = "FLAT"
                    unc = 0.7

                actual_dir = "UP" if ev.pnl_pct and ev.pnl_pct > 0.01 else (
                    "DOWN" if ev.pnl_pct is not None and ev.pnl_pct < -0.01 else "FLAT"
                )
                predictions.append(Prediction(
                    event_id=ev.event_id,
                    predicted_direction=pred_dir,
                    actual_direction=actual_dir,
                    correct=pred_dir == actual_dir,
                    regime=ev.regime,
                    uncertainty=unc,
                ))

            fold_results.append(FoldResult(
                fold_id=fold_id,
                train_size=len(train_events),
                test_size=len(test_events),
                predictions=predictions,
            ))

            last_predictor = predictor
            last_train_events = train_events

        # 计算最后一个 fold 的 train 准确率（用于 gap 估算）
        if last_predictor and last_predictor.model is not None and last_train_events:
            train_preds = []
            for ev in last_train_events:
                c = case_by_id.get(ev.event_id)
                if c:
                    pred_dir, _ = last_predictor.predict(c)
                    actual_dir = "UP" if ev.pnl_pct and ev.pnl_pct > 0.01 else (
                        "DOWN" if ev.pnl_pct is not None and ev.pnl_pct < -0.01 else "FLAT"
                    )
                    train_preds.append(Prediction(
                        event_id=ev.event_id,
                        predicted_direction=pred_dir,
                        actual_direction=actual_dir,
                        correct=pred_dir == actual_dir,
                        regime=ev.regime,
                        uncertainty=0.0,
                    ))
            self._last_train_predictions = train_preds

        return self._aggregate(fold_results)

    def _aggregate(self, fold_results: List[FoldResult]) -> BacktestResult:
        """聚合 fold 结果。"""
        all_preds = [p for fr in fold_results for p in fr.predictions]
        all_correct = sum(1 for p in all_preds if p.correct)
        all_total = len(all_preds)

        overall_accuracy = all_correct / max(all_total, 1)

        # Train/Test gap
        train_acc = self._compute_train_accuracy(fold_results)
        train_test_gap = max(0, train_acc - overall_accuracy)

        # 按 regime 分组
        by_regime: Dict[str, List[float]] = {}
        for p in all_preds:
            by_regime.setdefault(p.regime, []).append(1 if p.correct else 0)
        by_regime_acc = {
            r: [round(sum(v) / len(v), 4)] if v else [0.0]
            for r, v in by_regime.items()
        }

        # 高置信度子集准确率 (uncertainty < 0.3)
        hc_preds = [p for p in all_preds if p.uncertainty < 0.3]
        hc_accuracy = (
            sum(1 for p in hc_preds if p.correct) / len(hc_preds)
            if hc_preds
            else 0.0
        )

        return BacktestResult(
            total_predictions=all_total,
            overall_accuracy=round(overall_accuracy, 4),
            fold_accuracies=[fr.accuracy for fr in fold_results],
            fold_results=fold_results,
            train_test_gap=round(train_test_gap, 4),
            by_regime=by_regime_acc,
            high_confidence_accuracy=round(hc_accuracy, 4),
        )

    def _split_folds(
        self, events: List[CleanedEvent]
    ) -> List[Tuple[List[CleanedEvent], List[CleanedEvent]]]:
        """扩展窗口分割。"""
        n = len(events)
        min_total = self.min_train + self.min_test
        if n < min_total:
            return []

        fold_size = max((n - self.min_train) // self.n_folds, self.min_test)
        folds = []
        for i in range(self.n_folds):
            train_end = self.min_train + i * fold_size
            test_end = min(train_end + fold_size, n)
            if test_end - train_end < self.min_test:
                break
            folds.append((events[:train_end], events[train_end:test_end]))
        return folds

    def _compute_baseline(
        self, train: List[CleanedEvent]
    ) -> Dict[str, Any]:
        """从 train 计算基线统计。"""
        if not train:
            return {}

        regime_counts: Dict[str, int] = {}
        for ev in train:
            regime_counts[ev.regime] = regime_counts.get(ev.regime, 0) + 1
        dominant_regime = max(regime_counts, key=regime_counts.get)

        up_count = sum(1 for e in train if e.pnl_pct and e.pnl_pct > 0)
        down_count = sum(1 for e in train if e.pnl_pct is not None and e.pnl_pct < 0)
        dominant_direction = "UP" if up_count >= down_count else "DOWN"

        x_mean = statistics.mean(e.quadrant_x for e in train)
        y_mean = statistics.mean(e.quadrant_y for e in train)

        return {
            "dominant_regime": dominant_regime,
            "dominant_direction": dominant_direction,
            "x_mean": x_mean,
            "y_mean": y_mean,
            "regime_direction": self._regime_direction(train),
        }

    def _regime_direction(
        self, train: List[CleanedEvent]
    ) -> Dict[str, str]:
        """按 regime 计算方向。"""
        regime_pnl: Dict[str, List[float]] = {}
        for ev in train:
            if ev.pnl_pct is not None:
                regime_pnl.setdefault(ev.regime, []).append(ev.pnl_pct)
        return {
            r: "UP" if statistics.mean(pnls) > 0 else "DOWN"
            for r, pnls in regime_pnl.items()
        }

    def _predict_direction(
        self, event: CleanedEvent, baseline: Dict[str, Any]
    ) -> Tuple[str, float]:
        """基于基线的确定性方向预测 + 不确定性估算（规则模式）。"""
        if event.regime in baseline.get("regime_direction", {}):
            direction = baseline["regime_direction"][event.regime]
            uncertainty = 0.4
        elif event.regime == baseline.get("dominant_regime"):
            direction = baseline.get("dominant_direction", "FLAT")
            uncertainty = 0.3
        else:
            if event.quadrant_x > 0.1:
                direction = "UP"
            elif event.quadrant_x < -0.1:
                direction = "DOWN"
            else:
                direction = "FLAT"
            uncertainty = 0.7

        y_factor = 1.0 - event.quadrant_y
        uncertainty = round(min(1.0, uncertainty * (0.5 + 0.5 * y_factor)), 4)

        return direction, uncertainty

    def _compute_train_accuracy(self, fold_results: List[FoldResult]) -> float:
        """从最后一个 fold 的 train 预测计算准确率。

        如果有 xgb_mode 和 raw_cases，直接用模型在 train 上预测。
        否则用 test accuracy 近似。
        """
        if not fold_results:
            return 0.0

        # XGBoost 模式下，从 fold 的 train 预测中获取
        if self.xgb_mode and self.raw_cases and hasattr(self, '_last_train_predictions'):
            if self._last_train_predictions:
                correct = sum(1 for p in self._last_train_predictions if p.correct)
                return correct / len(self._last_train_predictions)

        # 回退：test accuracy + 上界估计
        last_fold = fold_results[-1]
        return min(1.0, last_fold.accuracy + 0.05)
