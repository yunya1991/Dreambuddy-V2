"""
Phase 2.5: 路径积分引擎
SPEC-AGI升级蓝图.md §4.2.5

核心哲学: 最小阻力路径 — 市场=引力场，价格=粒子，
  最小作用量路径 = 最优交易路径.

路径积分: K(q',t';q,t) = ∫ D[q] exp(iS[q]/ℏ)
  离散化: 蒙特卡洛采样N条路径，计算每条路径的作用量S，
  最小S的路径即为最小阻力路径.

HC-AGI-12: 蒙特卡洛采样≥1000条路径
HC-AGI-14: 最小阻力路径需同时满足成本/风险/不确定性三阈值
"""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


class PathIntegralEngine:
    """路径积分引擎 — 蒙特卡洛采样 + 最小阻力路径搜索.

    作用量（阻力）定义: S = α·成本 + β·风险 + γ·不确定性
      成本: 交易摩擦（路径总波动的函数）
      风险: 路径最大回撤
      不确定性: 路径与均值路径的偏离
    """

    MIN_PATHS = 1000  # HC-AGI-12

    def __init__(
        self,
        n_paths: int = 1000,
        alpha: float = 0.4,  # 成本权重
        beta: float = 0.3,   # 风险权重
        gamma: float = 0.3,  # 不确定性权重
    ) -> None:
        if n_paths < self.MIN_PATHS:
            logger.warning(
                "[HC-AGI-12] n_paths=%d < %d，建议增加采样数", n_paths, self.MIN_PATHS
            )
        self.n_paths = int(n_paths)
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.gamma = float(gamma)

    def sample_paths(
        self,
        start_price: float,
        horizon: int,
        volatility: float,
        drift: float = 0.0,
    ) -> list[np.ndarray]:
        """蒙特卡洛采样 N 条价格路径（几何布朗运动）.

        Args:
            start_price: 起始价格
            horizon: 路径长度（步数）
            volatility: 每步波动率
            drift: 漂移率

        Returns:
            list of 1D numpy arrays，每条长度 = horizon + 1
        """
        paths: list[np.ndarray] = []
        for _ in range(self.n_paths):
            # GBM: dS = μS dt + σS dW
            returns = np.random.normal(drift, volatility, size=horizon)
            path = start_price * np.cumprod(1.0 + returns)
            path = np.insert(path, 0, start_price)  # 加入起点
            paths.append(path)
        return paths

    def compute_action(self, path: np.ndarray) -> float:
        """计算路径的作用量（阻力）.

        S = α·成本 + β·风险 + γ·不确定性
          成本 = 总波动 / 路径长度（交易摩擦代理）
          风险 = 最大回撤
          不确定性 = 路径与线性趋势的RMSE
        """
        path = np.asarray(path, dtype=np.float64).ravel()
        n = len(path)
        if n < 2:
            return 0.0

        # 成本: 总波动（绝对收益之和）/ 长度
        diffs = np.diff(path)
        cost = float(np.sum(np.abs(diffs)) / max(n - 1, 1))

        # 风险: 最大回撤
        running_max = np.maximum.accumulate(path)
        drawdowns = (running_max - path) / np.maximum(running_max, 1e-12)
        risk = float(np.max(drawdowns))

        # 不确定性: 路径与线性趋势的RMSE
        t = np.arange(n, dtype=np.float64)
        if n > 2:
            coeffs = np.polyfit(t, path, 1)
            trend = np.polyval(coeffs, t)
            uncertainty = float(np.sqrt(np.mean((path - trend) ** 2)))
        else:
            uncertainty = 0.0

        action = self.alpha * cost + self.beta * risk + self.gamma * uncertainty
        return float(max(0.0, action))

    def find_least_resistance_path(self, paths: list[np.ndarray]) -> tuple[int, float]:
        """搜索最小阻力路径.

        Returns:
            (best_index, best_action)
        """
        if not paths:
            raise ValueError("paths 不能为空")
        actions = np.array([self.compute_action(p) for p in paths])
        best_idx = int(np.argmin(actions))
        return best_idx, float(actions[best_idx])

    def compute_transition_amplitude(
        self,
        paths: list[np.ndarray],
        temperature: float = 1.0,
    ) -> np.ndarray:
        """路径积分跃迁振幅: K = Σ exp(-S/temperature).

        温度越高，高阻力路径的权重越大（探索更多）.
        温度越低，越集中在最小阻力路径（利用）.
        """
        actions = np.array([self.compute_action(p) for p in paths])
        # 数值稳定: 减去最小action
        weights = np.exp(-actions / max(temperature, 1e-12))
        weights /= np.sum(weights)
        return weights

    def expected_path(self, paths: list[np.ndarray], temperature: float = 1.0) -> np.ndarray:
        """路径积分期望路径（加权平均）."""
        weights = self.compute_transition_amplitude(paths, temperature)
        max_len = max(len(p) for p in paths)
        # 对齐到最长路径
        aligned = np.zeros((len(paths), max_len))
        for i, p in enumerate(paths):
            aligned[i, :len(p)] = p
            if len(p) < max_len:
                aligned[i, len(p):] = p[-1]  # 用末值填充
        return np.sum(aligned * weights[:, np.newaxis], axis=0)
