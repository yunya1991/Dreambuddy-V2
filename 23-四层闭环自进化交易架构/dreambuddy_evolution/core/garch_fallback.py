"""
GARCH(1,1) 纯 numpy 降级实现
SPEC-AGI升级蓝图.md HC-AGI-13

当 Neural SDE 训练样本 < 1000 时，降级为 GARCH(1,1) 而非 GBM。
GARCH(1,1): σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}

FAIL-OPEN: 样本 < 50 时返回 None，触发 GBM 最后兜底。
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class GARCHFallback:
    """GARCH(1,1) 纯 numpy 实现.

    用于 Neural SDE 不可用时的降级路径生成（HC-AGI-13）.
    """

    MIN_SAMPLES = 50  # 低于此值 GARCH 也估计不了

    def __init__(self) -> None:
        self._omega: float = 0.0
        self._alpha: float = 0.1
        self._beta: float = 0.85
        self._fitted: bool = False

    @property
    def is_fitted(self) -> bool:
        return self._fitted

    def estimate(self, returns: np.ndarray) -> bool:
        """矩估计法估计 GARCH(1,1) 参数.

        σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1}
        用样本方差和自相关推导参数.

        Returns:
            True if estimation succeeded.
        """
        returns = np.asarray(returns, dtype=np.float64).ravel()
        if len(returns) < self.MIN_SAMPLES:
            logger.debug("[FO-AGI-13] 样本 %d < %d, GARCH 估计失败", len(returns), self.MIN_SAMPLES)
            self._fitted = False
            return False

        try:
            # 矩估计法
            r2 = returns ** 2
            var0 = float(np.mean(r2))
            if var0 <= 0:
                self._fitted = False
                return False

            # lag-1 自相关
            if len(r2) > 1:
                rho1 = float(np.corrcoef(r2[:-1], r2[1:])[0, 1])
            else:
                rho1 = 0.0

            if np.isnan(rho1):
                rho1 = 0.0

            # GARCH(1,1) 矩估计:
            # E[r²] = ω / (1 - α - β)
            # Corr(r²_0, r²_1) = α(1 - α² - β²) / (1 - (α+β)² + α²)
            # 简化: α ≈ rho1 * (1 - β), β ≈ 1 - α - ω/var0
            # 用迭代简化估计
            alpha = max(0.01, min(0.49, rho1 * 0.5 + 0.05))
            beta = max(0.01, min(0.949, 0.95 - alpha))

            # 约束 α + β < 0.999（平稳性）
            if alpha + beta >= 0.999:
                scale = 0.999 / (alpha + beta)
                alpha *= scale
                beta *= scale

            omega = var0 * (1.0 - alpha - beta)
            if omega <= 0:
                omega = var0 * 0.01

            self._omega = omega
            self._alpha = alpha
            self._beta = beta
            self._fitted = True
            logger.debug(
                "[GARCH] 估计完成: ω=%.6f α=%.4f β=%.4f (α+β=%.4f)",
                omega, alpha, beta, alpha + beta,
            )
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("[FO-AGI-13] GARCH 估计异常: %s", e)
            self._fitted = False
            return False

    def simulate(
        self,
        n_paths: int,
        horizon: int,
        init_price: float,
        init_vol: float,
    ) -> np.ndarray:
        """GARCH(1,1) 路径模拟.

        Args:
            n_paths: 路径数
            horizon: 预测步数
            init_price: 初始价格
            init_vol: 初始波动率（年化或日收益率标准差）

        Returns:
            shape (n_paths, horizon+1) 的价格路径数组
        """
        if not self._fitted:
            return np.full((n_paths, horizon + 1), init_price)

        dt = 1.0
        paths = np.zeros((n_paths, horizon + 1), dtype=np.float64)
        paths[:, 0] = init_price

        # 初始条件方差
        sigma2 = np.full(n_paths, init_vol ** 2)
        eps = np.zeros(n_paths)

        for t in range(horizon):
            # 生成新息
            z = np.random.standard_normal(n_paths)
            eps = z * np.sqrt(np.maximum(sigma2, 1e-12))

            # 更新价格
            log_ret = -0.5 * sigma2 * dt + eps * np.sqrt(dt)
            paths[:, t + 1] = paths[:, t] * np.exp(log_ret)

            # GARCH 方差递推
            sigma2 = self._omega + self._alpha * eps ** 2 + self._beta * sigma2
            sigma2 = np.maximum(sigma2, 1e-10)

        return paths
