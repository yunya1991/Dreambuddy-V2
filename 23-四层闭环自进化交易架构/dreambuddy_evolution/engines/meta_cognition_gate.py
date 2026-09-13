"""
MetaCognitionGate — 元认知门禁（Phase 5.2）

核心思想：系统知道自己"不知道什么"。
当预测不确定性高时，主动降仓或拒开仓，而非盲目交易。

核心能力：
  1. evaluate        — 评估一笔交易是否应该执行及仓位调整
  2. should_trade    — 是否允许开仓
  3. position_mult   — 仓位乘数
  4. confidence_calibration — 校准系统自身 confidence 可靠性

硬约束：
  - HC-AGI-06: uncertainty > 0.4 → 强制降仓至 0.5×
  - uncertainty > 0.7 → 拒开仓

FAIL-OPEN：任何异常 → 保守决策（降仓或拒开仓）
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class MetaCognitionGate:
    """元认知门禁.

    根据不确定性量化结果，决定交易执行策略.
    """

    # HC-AGI-06 阈值
    UNCERTAINTY_HIGH = 0.4      # 降仓阈值
    UNCERTAINTY_CRITICAL = 0.7  # 拒开仓阈值

    # 仓位乘数
    POS_MULT_LOW = 1.0       # 低不确定性：正常仓位
    POS_MULT_MEDIUM = 0.7    # 中不确定性：7折
    POS_MULT_HIGH = 0.5      # 高不确定性：5折（HC-AGI-06）
    POS_MULT_CRITICAL = 0.0  # 极高不确定性：拒开仓

    def __init__(
        self,
        uncertainty_high: Optional[float] = None,
        uncertainty_critical: Optional[float] = None,
    ) -> None:
        self.uncertainty_high = uncertainty_high or self.UNCERTAINTY_HIGH
        self.uncertainty_critical = uncertainty_critical or self.UNCERTAINTY_CRITICAL
        # 校准状态
        self._confidence_calibration: dict = {}

    # ------------------------------------------------------------------
    # 1. 评估交易决策
    # ------------------------------------------------------------------
    def evaluate(
        self,
        uncertainty_score: float,
        base_confidence: float = 0.5,
        strategy_sharpe: Optional[float] = None,
        position_size: float = 1.0,
    ) -> dict:
        """评估一笔交易的执行决策.

        Args:
            uncertainty_score: 不确定性评分 [0, 1]
            base_confidence: 策略原始 confidence [0, 1]
            strategy_sharpe: 策略历史 Sharpe（可选，高 Sharpe 可放宽）
            position_size: 基础仓位大小
        Returns:
            dict: {
                "allow_trade": bool,           # 是否允许开仓
                "position_multiplier": float,  # 仓位乘数
                "adjusted_position": float,    # 调整后仓位
                "adjusted_confidence": float,  # 校准后 confidence
                "uncertainty_level": str,      # low/medium/high/critical
                "reason": str,                 # 决策原因
            }
        FAIL-OPEN: uncertainty 异常 → 拒开仓
        """
        try:
            # 防御：uncertainty 必须在 [0, 1]
            if not isinstance(uncertainty_score, (int, float)) or np.isnan(uncertainty_score):
                return self._reject("invalid_uncertainty")
            uncertainty = float(max(0.0, min(1.0, uncertainty_score)))

            # 分级
            if uncertainty >= self.uncertainty_critical:
                level = "critical"
                allow = False
                mult = self.POS_MULT_CRITICAL
                reason = f"uncertainty={uncertainty:.3f} >= {self.uncertainty_critical} (critical) → 拒开仓"
            elif uncertainty >= self.uncertainty_high:
                level = "high"
                allow = True
                mult = self.POS_MULT_HIGH  # HC-AGI-06: 降仓至 0.5×
                reason = f"uncertainty={uncertainty:.3f} >= {self.uncertainty_high} (high) → 降仓 0.5×"
            elif uncertainty >= 0.2:
                level = "medium"
                allow = True
                mult = self.POS_MULT_MEDIUM
                reason = f"uncertainty={uncertainty:.3f} (medium) → 降仓 0.7×"
            else:
                level = "low"
                allow = True
                mult = self.POS_MULT_LOW
                reason = f"uncertainty={uncertainty:.3f} (low) → 正常仓位"

            # Sharpe 豁免：高 Sharpe 策略可适当放宽（但不突破 HC-AGI-06 下限）
            if strategy_sharpe is not None and strategy_sharpe > 1.5:
                if level == "medium":
                    mult = self.POS_MULT_LOW  # 恢复正常仓位
                    reason += f" [Sharpe={strategy_sharpe:.2f}>1.5 豁免 medium→low]"
                # high/critical 不豁免（HC-AGI-06 硬约束）

            # confidence 校准：不确定性越高，confidence 越低
            adj_confidence = float(base_confidence * (1.0 - uncertainty * 0.5))
            adj_confidence = max(0.0, min(1.0, adj_confidence))

            return {
                "allow_trade": allow,
                "position_multiplier": float(mult),
                "adjusted_position": float(position_size * mult),
                "adjusted_confidence": adj_confidence,
                "uncertainty_level": level,
                "reason": reason,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] evaluate failed: %s", e)
            return self._reject(f"error: {e}")

    def _reject(self, reason: str) -> dict:
        """保守拒绝开仓"""
        return {
            "allow_trade": False,
            "position_multiplier": 0.0,
            "adjusted_position": 0.0,
            "adjusted_confidence": 0.0,
            "uncertainty_level": "critical",
            "reason": reason,
        }

    # ------------------------------------------------------------------
    # 2. 快捷方法
    # ------------------------------------------------------------------
    def should_trade(self, uncertainty_score: float) -> bool:
        """是否允许开仓"""
        result = self.evaluate(uncertainty_score)
        return result["allow_trade"]

    def position_multiplier(self, uncertainty_score: float) -> float:
        """仓位乘数"""
        result = self.evaluate(uncertainty_score)
        return result["position_multiplier"]

    # ------------------------------------------------------------------
    # 3. Confidence 校准（系统知道自己的 confidence 是否可靠）
    # ------------------------------------------------------------------
    def calibrate_confidence(
        self,
        historical_predictions: np.ndarray,
        historical_outcomes: np.ndarray,
        historical_confidences: np.ndarray,
    ) -> dict:
        """校准系统 confidence 的可靠性.

        计算不同 confidence 分位下的实际胜率/准确率，
        如果高 confidence 但实际胜率低 → 系统过度自信.

        Args:
            historical_predictions: 历史预测方向 (+1/-1)
            historical_outcomes: 实际结果方向 (+1/-1)
            historical_confidences: 历史 confidence [0, 1]
        Returns:
            dict: {
                "calibration_curve": list[{"confidence_bin": float, "actual_accuracy": float, "n": int}],
                "overconfidence_score": float,  # >0 表示过度自信
                "reliable": bool,               # confidence 是否可靠
            }
        """
        try:
            preds = np.asarray(historical_predictions)
            outcomes = np.asarray(historical_outcomes)
            confs = np.asarray(historical_confidences)

            if len(preds) < 10:
                return {
                    "calibration_curve": [],
                    "overconfidence_score": 0.0,
                    "reliable": True,  # 样本不足，默认可靠
                }

            # 预测是否正确
            correct = (preds == outcomes).astype(float)

            # 按 confidence 分箱
            bins = np.linspace(0, 1, 6)  # 5 个 bin
            curve = []
            weighted_conf = 0.0
            weighted_acc = 0.0

            for i in range(len(bins) - 1):
                lo, hi = bins[i], bins[i + 1]
                mask = (confs >= lo) & (confs < hi) if i < len(bins) - 2 else (confs >= lo) & (confs <= hi)
                n = int(mask.sum())
                if n > 0:
                    acc = float(correct[mask].mean())
                    mid_conf = float((lo + hi) / 2)
                    curve.append({
                        "confidence_bin": round(mid_conf, 2),
                        "actual_accuracy": round(acc, 4),
                        "n": n,
                    })
                    weighted_conf += mid_conf * n
                    weighted_acc += acc * n

            total_n = len(preds)
            avg_conf = weighted_conf / total_n if total_n > 0 else 0
            avg_acc = weighted_acc / total_n if total_n > 0 else 0

            # 过度自信 = 平均 confidence - 实际准确率
            overconfidence = float(avg_conf - avg_acc)

            # 可靠标准：过度自信 < 0.15
            reliable = overconfidence < 0.15

            self._confidence_calibration = {
                "overconfidence_score": overconfidence,
                "reliable": reliable,
                "n_samples": total_n,
            }

            return {
                "calibration_curve": curve,
                "overconfidence_score": overconfidence,
                "reliable": reliable,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] calibrate_confidence failed: %s", e)
            return {
                "calibration_curve": [],
                "overconfidence_score": 0.0,
                "reliable": True,
            }

    def apply_calibration(self, confidence: float) -> float:
        """应用校准：如果系统过度自信，下调 confidence"""
        try:
            if not self._confidence_calibration:
                return confidence
            overconf = self._confidence_calibration.get("overconfidence_score", 0.0)
            if overconf > 0.15:
                # 过度自信 → 下调 confidence
                adjusted = float(confidence * (1.0 - overconf * 0.5))
                return max(0.0, min(1.0, adjusted))
            return confidence
        except Exception:
            return confidence

    # ------------------------------------------------------------------
    # 4. 端到端：不确定性量化 + 门禁决策
    # ------------------------------------------------------------------
    def gate_decision(
        self,
        uncertainty_score: float,
        base_confidence: float = 0.5,
        strategy_sharpe: Optional[float] = None,
        position_size: float = 1.0,
    ) -> dict:
        """端到端门禁决策.

        综合 uncertainty + confidence 校准，输出最终交易决策.
        """
        try:
            # 1. 应用 confidence 校准
            calibrated_conf = self.apply_calibration(base_confidence)

            # 2. 评估决策
            decision = self.evaluate(
                uncertainty_score=uncertainty_score,
                base_confidence=calibrated_conf,
                strategy_sharpe=strategy_sharpe,
                position_size=position_size,
            )

            return decision
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] gate_decision failed: %s", e)
            return self._reject(f"error: {e}")

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        return {
            "uncertainty_high": self.uncertainty_high,
            "uncertainty_critical": self.uncertainty_critical,
            "position_multipliers": {
                "low": self.POS_MULT_LOW,
                "medium": self.POS_MULT_MEDIUM,
                "high": self.POS_MULT_HIGH,
                "critical": self.POS_MULT_CRITICAL,
            },
            "confidence_calibrated": bool(self._confidence_calibration),
        }
