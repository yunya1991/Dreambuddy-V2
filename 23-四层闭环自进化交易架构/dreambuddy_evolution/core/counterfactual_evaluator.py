"""
CounterfactualEvaluator — 反事实评估器（Phase 2.2）

核心思想：交易不是因果实验，无法直接观测"如果不交易"的结果。
用合成控制法构造反事实基准，区分策略 alpha 和市场 beta。

核心能力：
  1. synthetic_control   — 合成控制法，用"其他资产加权"构造未交易时的反事实收益
  2. what_if_no_trade    — 计算"如果不交易"的反事实 P&L
  3. counterfactual_eval — 完整评估：actual vs counterfactual，归因 alpha/beta
  4. validate_migration  — 迁移 pattern 的反事实验证（HC-AGI-05）

硬约束：
  - HC-AGI-05: 迁移 pattern 必须经反事实评估
  - HC-AGI-09: actual_pnl 异常时用 counterfactual 兜底

FAIL-OPEN：合成控制失败 → 用市场均值作为反事实基准
"""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


class CounterfactualEvaluator:
    """反事实评估器.

    用合成控制法（Synthetic Control Method）构造反事实基准.
    """

    # HC-AGI-09 异常阈值
    PNL_OUTLIER_Z = 3.0  # actual_pnl z-score > 3 视为异常

    def __init__(self, min_control_units: int = 3) -> None:
        self.min_control_units = min_control_units

    # ------------------------------------------------------------------
    # 1. 合成控制法
    # ------------------------------------------------------------------
    def synthetic_control(
        self,
        target_returns: np.ndarray,
        control_returns: np.ndarray,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """合成控制法：用控制组加权构造目标的反事实路径.

        原理：最小化 pre-treatment 期间 目标 vs 加权控制组 的距离，
        得到权重 w，反事实 = w @ control_returns.

        Args:
            target_returns: 目标资产收益序列 (T,)
            control_returns: 控制组资产收益矩阵 (T, N)
        Returns:
            (synthetic, weights): 反事实序列, 控制组权重
        FAIL-OPEN: 优化失败 → 等权重
        """
        try:
            target = np.asarray(target_returns, dtype=np.float64).ravel()
            controls = np.asarray(control_returns, dtype=np.float64)
            if controls.ndim == 1:
                controls = controls.reshape(-1, 1)

            T, N = controls.shape
            if N < self.min_control_units:
                logger.warning("[FO-AGI-02] 控制组不足(< %d)，用等权重", self.min_control_units)
                weights = np.ones(N) / N
                synthetic = controls @ weights
                return synthetic, weights

            # 用前 70% 数据拟合权重（pre-treatment）
            pre_T = max(1, int(T * 0.7))
            target_pre = target[:pre_T]
            controls_pre = controls[:pre_T]

            # 最小二乘：target_pre ≈ controls_pre @ w，约束 w≥0, sum(w)=1
            # 用约束优化（scipy 可用时），否则用非负最小二乘 + 归一化
            try:
                from scipy.optimize import minimize

                def objective(w):
                    w = np.abs(w)
                    w = w / w.sum()
                    return np.sum((target_pre - controls_pre @ w) ** 2)

                w0 = np.ones(N) / N
                res = minimize(objective, w0, method="Nelder-Mead", options={"maxiter": 500})
                weights = np.abs(res.x)
                weights = weights / weights.sum()
            except Exception:  # noqa: BLE001
                # 降级：非负最小二乘
                from numpy.linalg import lstsq

                w, *_ = lstsq(controls_pre, target_pre, rcond=None)
                weights = np.clip(w, 0, None)
                if weights.sum() > 0:
                    weights = weights / weights.sum()
                else:
                    weights = np.ones(N) / N

            synthetic = controls @ weights
            return synthetic, weights
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] synthetic_control failed: %s", e)
            # FAIL-OPEN：等权重
            N = control_returns.shape[1] if hasattr(control_returns, "shape") and control_returns.ndim > 1 else 1
            weights = np.ones(N) / N
            synthetic = np.asarray(control_returns) @ weights if N > 1 else np.asarray(control_returns).ravel()
            return synthetic, weights

    # ------------------------------------------------------------------
    # 2. what_if_no_trade 反事实 P&L
    # ------------------------------------------------------------------
    def what_if_no_trade(
        self,
        actual_pnl: float,
        target_returns: np.ndarray,
        control_returns: np.ndarray,
        position_size: float = 1.0,
    ) -> dict:
        """计算"如果不交易"的反事实 P&L.

        Args:
            actual_pnl: 实际交易 P&L
            target_returns: 交易期间目标资产收益序列
            control_returns: 控制组资产收益矩阵
            position_size: 仓位大小
        Returns:
            dict: {
                "counterfactual_pnl": float,   # 反事实P&L（不交易时的收益）
                "alpha": float,                 # actual - counterfactual（超额收益）
                "synthetic_returns": np.ndarray,
                "weights": np.ndarray,
                "pnl_attribution": {
                    "alpha": float,    # 策略alpha
                    "beta": float,     # 市场beta（反事实收益）
                },
            }
        """
        try:
            target = np.asarray(target_returns, dtype=np.float64).ravel()
            controls = np.asarray(control_returns, dtype=np.float64)

            # 合成控制
            synthetic, weights = self.synthetic_control(target, controls)

            # 反事实 P&L = 合成控制路径的累计收益 × 仓位
            counterfactual_return = float(np.sum(synthetic))
            counterfactual_pnl = counterfactual_return * position_size

            # Alpha = 实际 P&L - 反事实 P&L
            alpha = actual_pnl - counterfactual_pnl

            return {
                "counterfactual_pnl": counterfactual_pnl,
                "alpha": alpha,
                "synthetic_returns": synthetic,
                "weights": weights,
                "pnl_attribution": {
                    "alpha": alpha,
                    "beta": counterfactual_pnl,
                },
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] what_if_no_trade failed: %s", e)
            return {
                "counterfactual_pnl": 0.0,
                "alpha": 0.0,
                "synthetic_returns": np.zeros_like(target_returns) if hasattr(target_returns, "__len__") else np.array([0.0]),
                "weights": np.array([1.0]),
                "pnl_attribution": {"alpha": 0.0, "beta": 0.0},
            }

    # ------------------------------------------------------------------
    # 3. 完整反事实评估
    # ------------------------------------------------------------------
    def counterfactual_eval(
        self,
        actual_pnl: float,
        target_returns: np.ndarray,
        control_returns: np.ndarray,
        position_size: float = 1.0,
        market_returns: Optional[np.ndarray] = None,
    ) -> dict:
        """完整反事实评估：actual vs counterfactual，归因 alpha/beta.

        还包含 HC-AGI-09：actual_pnl 异常检测与兜底.

        Returns:
            dict: {
                "actual_pnl": float,
                "counterfactual_pnl": float,
                "alpha": float,
                "beta": float,
                "actual_is_outlier": bool,   # HC-AGI-09 异常标记
                "reliable": bool,             # 评估是否可靠
                "alpha_significance": str,    # "positive"/"negative"/"neutral"
                "sharpe_alpha": float,        # alpha 单位风险收益
            }
        """
        try:
            target = np.asarray(target_returns, dtype=np.float64).ravel()
            controls = np.asarray(control_returns, dtype=np.float64)

            # 反事实评估
            cf = self.what_if_no_trade(actual_pnl, target, controls, position_size)

            # HC-AGI-09: actual_pnl 异常检测
            outlier = self._detect_pnl_outlier(actual_pnl, target)

            # Alpha 显著性
            alpha = cf["alpha"]
            if alpha > 0:
                significance = "positive"
            elif alpha < 0:
                significance = "negative"
            else:
                significance = "neutral"

            # Alpha Sharpe：alpha / 目标收益波动
            target_vol = float(np.std(target)) if len(target) > 1 else 1.0
            sharpe_alpha = alpha / (target_vol + 1e-10)

            # 可靠性：控制组足够 + 非异常
            reliable = controls.shape[1] >= self.min_control_units and not outlier

            return {
                "actual_pnl": float(actual_pnl),
                "counterfactual_pnl": cf["counterfactual_pnl"],
                "alpha": alpha,
                "beta": cf["pnl_attribution"]["beta"],
                "actual_is_outlier": outlier,
                "reliable": reliable,
                "alpha_significance": significance,
                "sharpe_alpha": float(sharpe_alpha),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] counterfactual_eval failed: %s", e)
            return {
                "actual_pnl": float(actual_pnl) if isinstance(actual_pnl, (int, float)) else 0.0,
                "counterfactual_pnl": 0.0,
                "alpha": 0.0,
                "beta": 0.0,
                "actual_is_outlier": False,
                "reliable": False,
                "alpha_significance": "neutral",
                "sharpe_alpha": 0.0,
            }

    def _detect_pnl_outlier(self, actual_pnl: float, returns: np.ndarray) -> bool:
        """HC-AGI-09: 检测 actual_pnl 是否异常（z-score > 阈值）"""
        try:
            if not isinstance(actual_pnl, (int, float)):
                return True
            r = np.asarray(returns, dtype=np.float64).ravel()
            if len(r) < 5:
                return False
            mean = float(np.mean(r))
            std = float(np.std(r))
            if std < 1e-10:
                return False
            z = abs(actual_pnl - mean) / std
            return z > self.PNL_OUTLIER_Z
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 4. 迁移 pattern 的反事实验证（HC-AGI-05）
    # ------------------------------------------------------------------
    def validate_migration(
        self,
        pattern_source_returns: np.ndarray,
        pattern_target_returns: np.ndarray,
        control_returns: np.ndarray,
        source_pnl: float,
        threshold_alpha: float = 0.0,
    ) -> dict:
        """验证迁移 pattern 是否有效（HC-AGI-05）.

        逻辑：
        1. 用源资产的 pattern 在目标资产上的收益作为 actual_pnl
        2. 用合成控制法计算目标资产的反事实收益
        3. 如果 actual > counterfactual（alpha > threshold）→ 迁移有效

        Args:
            pattern_source_returns: 源资产 pattern 期间收益
            pattern_target_returns: 目标资产 pattern 期间收益
            control_returns: 控制组收益
            source_pnl: 源资产实际 P&L
            threshold_alpha: alpha 阈值（>此值才认可迁移）
        Returns:
            dict: {
                "valid": bool,              # 迁移是否有效
                "alpha": float,             # 迁移超额收益
                "counterfactual_pnl": float,
                "reason": str,
            }
        """
        try:
            target = np.asarray(pattern_target_returns, dtype=np.float64).ravel()
            controls = np.asarray(control_returns, dtype=np.float64)

            # actual_pnl = 目标资产在 pattern 期间的收益（模拟迁移后的收益）
            actual_pnl = float(np.sum(target))

            # 反事实评估
            eval_result = self.counterfactual_eval(actual_pnl, target, controls)

            alpha = eval_result["alpha"]
            valid = alpha > threshold_alpha and eval_result["reliable"]

            if valid:
                reason = f"迁移有效: alpha={alpha:.4f} > {threshold_alpha}"
            elif not eval_result["reliable"]:
                reason = "迁移无效: 反事实评估不可靠（控制组不足或actual异常）"
            else:
                reason = f"迁移无效: alpha={alpha:.4f} <= {threshold_alpha}"

            return {
                "valid": valid,
                "alpha": alpha,
                "counterfactual_pnl": eval_result["counterfactual_pnl"],
                "reason": reason,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-02] validate_migration failed: %s", e)
            return {
                "valid": False,
                "alpha": 0.0,
                "counterfactual_pnl": 0.0,
                "reason": f"error: {e}",
            }

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------
    def backend_status(self) -> dict:
        return {
            "min_control_units": self.min_control_units,
            "pnl_outlier_z": self.PNL_OUTLIER_Z,
        }
