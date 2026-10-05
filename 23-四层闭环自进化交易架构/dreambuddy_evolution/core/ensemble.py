"""P1.1 熵加权 SDE+GARCH Ensemble.

结合 P0.2 (regime_uncertainty) + P1.1 (ensemble):
  final_pred = w * SDE_pred + (1-w) * GARCH_pred
  w = f(entropy): 熵越高, SDE 权重越低 (过拟合风险高时降权)

设计依据:
  - NeuralSDE 在 regime 稳定 (低熵) 时表现好, 在 regime 切换频繁 (高熵) 时过拟合
  - GARCH 更稳健, 在高熵 regime 下作为兜底
  - 熵加权自动调节两个模型的权重, 无需手动调参
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


def entropy_to_weight(entropy: float, n_regimes: int = 3) -> float:
    """将 regime 不确定性 (熵) 转换为 SDE 权重.

    w = 1 - entropy / log(n_regimes)

    - entropy=0 (regime 完全稳定): w=1.0 (全信 SDE)
    - entropy=log(n_regimes) (完全随机): w=0.0 (全信 GARCH)
    - 中间值: 线性插值

    Args:
        entropy: regime 预测熵 (nats), 来自 BTCRegimeDetector.regime_uncertainty()
        n_regimes: regime 数量

    Returns:
        float: SDE 权重 w ∈ [0, 1]
    """
    if n_regimes <= 1:
        return 1.0
    max_entropy = math.log(n_regimes)
    if max_entropy <= 0:
        return 1.0
    # clamp entropy to [0, max_entropy]
    entropy = max(0.0, min(float(entropy), max_entropy))
    w = 1.0 - entropy / max_entropy
    return float(max(0.0, min(1.0, w)))


def ensemble_forecast(
    sde_pred: Optional[np.ndarray],
    garch_pred: np.ndarray,
    sde_weight: float = 0.5,
) -> np.ndarray:
    """合并 SDE 和 GARCH 预测.

    final_pred = w * SDE_pred + (1-w) * GARCH_pred

    Args:
        sde_pred: NeuralSDE 预测均值 (horizon,), None 或 NaN → 回退 GARCH
        garch_pred: GARCH 预测均值 (horizon,)
        sde_weight: SDE 权重 w ∈ [0, 1]

    Returns:
        np.ndarray: 合并后的预测 (horizon,)
    """
    garch_pred = np.asarray(garch_pred, dtype=np.float64)

    if sde_pred is None:
        return garch_pred.copy()

    sde_pred = np.asarray(sde_pred, dtype=np.float64)
    # 检查 SDE 预测是否有效 (无 NaN/Inf)
    if not np.all(np.isfinite(sde_pred)):
        return garch_pred.copy()

    w = float(max(0.0, min(1.0, sde_weight)))
    return w * sde_pred + (1.0 - w) * garch_pred


def compute_sde_weight_from_regime(
    Q: np.ndarray,
    current_regime: int,
    n_regimes: int = 3,
) -> float:
    """从转移矩阵 Q 和当前 regime 计算 SDE 权重.

    便捷函数: 先算 regime_uncertainty (熵), 再转权重.

    Args:
        Q: (n_regimes, n_regimes) 转移概率矩阵
        current_regime: 当前 regime 标签
        n_regimes: regime 数量

    Returns:
        float: SDE 权重 w ∈ [0, 1]
    """
    from .btc_regime_detector import BTCRegimeDetector

    detector = BTCRegimeDetector(n_regimes=n_regimes)
    entropy = detector.regime_uncertainty(Q, current_regime)
    return entropy_to_weight(entropy, n_regimes)
