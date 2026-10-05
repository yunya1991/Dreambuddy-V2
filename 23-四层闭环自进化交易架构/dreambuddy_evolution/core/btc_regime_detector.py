"""BTCRegimeDetector — BTC 市场制度检测器 (k=3 HMM + drawdown 观测).

解决 NeuralSDE V3c MAE 退化根因 (V2 MAE=269 → V3c MAE=569):
  BTC 2017-2025 多 regime (牛/熊/DeFi夏/2022 崩溃), 单一 SDE 难同时拟合.
  本检测器将 BTC 历史切分为 3 种 regime (bull/chop/bear), 供 NeuralSDE:
    - drift_net 加 regime one-hot 输入 (T2)
    - prepare_data 按 regime 分组切窗 (T3)
    - forecast 接受 regime 参数 (T4)

学术依据 (调研 spec VM-1791190210830):
  - HMM K=3 (bull/chop/bear) 是 BTC regime 最佳配置 (Koki 2020, Bielejec 2026)
  - observation = drawdown from rolling max (非 log-return; Bielejec 2026 证明优)
    drawdown 在牛市 ≈ 0, 熊市大幅负, 震荡市中等 — 天然区分 regime

设计原则:
  1. 复用 StructuralBreakDetector 的 MarkovRegression 模式 (k=2 → k=3)
  2. FAIL-OPEN: 数据不足 / HMM 不收敛 → 简单 drawdown 阈值兜底, 不抛异常
  3. regime 标签排序: bull=0 (drawdown 接近 0), bear=2 (drawdown 最负), chop=1
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

try:
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    _HAS_HMM = True
except ImportError:
    _HAS_HMM = False
    logger.warning("MarkovRegression not available, BTCRegimeDetector 退化到阈值法")


class BTCRegimeDetector:
    """BTC 市场制度检测器 (k=3 HMM + drawdown 观测).

    接口:
      detect(closes) -> np.ndarray[int]  # regime label per timestep, 0=bull/1=chop/2=bear
      save_labels(path, labels) / load_labels(path) -> 持久化 regime labels

    Args:
        n_regimes: regime 数 (默认 3 = bull/chop/bear, SOTA per Bielejec 2026)
        window: rolling max 窗口 (默认 720, 1h 数据 = 30 天, Bielejec 2026 推荐)
                短窗口 (24h) 只能捕获日内回撤, 会错过 2018 这种多月熊市.
        min_samples: 最小样本数, 不足则 FAIL-OPEN 返回 zeros
    """

    observation_kind = "drawdown"  # 暴露给测试 T1.4 验证

    def __init__(self, n_regimes: int = 3, window: int = 720, min_samples: int = 200):
        self.n_regimes = n_regimes
        self.window = window
        self.min_samples = min_samples
        self._fitted = False
        self._regime_order: list[int] | None = None  # 排序映射 (old → new)

    # ------------------------------------------------------------------
    # drawdown 计算 (T1.4 验证)
    # ------------------------------------------------------------------
    def _compute_drawdown(self, closes: np.ndarray) -> np.ndarray:
        """计算 drawdown from rolling max: (P_t - max(P_0..P_t)) / max(P_0..P_t).

        性质:
          - 所有值 ≤ 0 (P_t ≤ max to date)
          - 创新高时 = 0
          - 回撤越大, 值越接近 -1

        使用 rolling max 而非全局 max (window=24) 以更快响应 regime 转换.
        窗口外早期值用 expanding max 兜底.
        """
        closes = np.asarray(closes, dtype=float)
        n = closes.size
        if n == 0:
            return np.array([], dtype=float)

        # rolling max with min_periods=1 (expanding until window 满)
        from numpy.lib.stride_tricks import sliding_window_view
        # 用 pandas 风格 rolling max, 简化实现:
        rolling_max = np.maximum.accumulate(closes) if self.window >= n else self._rolling_max(closes, self.window)
        drawdown = (closes - rolling_max) / rolling_max
        # 处理 rolling_max 为 0 的情况 (理论上 BTC 不可能)
        drawdown = np.where(rolling_max > 0, drawdown, 0.0)
        return drawdown

    @staticmethod
    def _rolling_max(arr: np.ndarray, window: int) -> np.ndarray:
        """rolling max with min_periods=1 (前 window-1 个用 expanding)."""
        n = arr.size
        out = np.empty(n, dtype=float)
        for i in range(n):
            lo = max(0, i - window + 1)
            out[i] = np.max(arr[lo:i + 1])
        return out

    # ------------------------------------------------------------------
    # 主检测接口
    # ------------------------------------------------------------------
    def detect(self, closes: np.ndarray) -> np.ndarray:
        """对 close 序列检测 regime, 返回与 closes 等长的 int ndarray.

        Args:
            closes: BTC close 价格序列 (1d array)

        Returns:
            np.ndarray[int]: regime label per timestep (0=bull, 1=chop, 2=bear)
                             短数据/异常时返回全 0 (FAIL-OPEN)
        """
        closes = np.asarray(closes, dtype=float)
        n = closes.size

        # FAIL-OPEN: 短数据
        if n < self.min_samples:
            logger.debug("BTCRegimeDetector: n=%d < min_samples=%d, 返回 zeros 兜底", n, self.min_samples)
            return np.zeros(n, dtype=int)

        # FAIL-OPEN: NaN 处理 (前向+后向填充均值)
        if np.isnan(closes).any():
            valid_mask = ~np.isnan(closes)
            if not valid_mask.any():
                return np.zeros(n, dtype=int)
            fill_value = float(np.nanmean(closes))
            closes = np.where(np.isnan(closes), fill_value, closes)

        # 计算 drawdown observation
        obs = self._compute_drawdown(closes)

        # 主路径: HMM k=3
        try:
            labels = self._fit_hmm(obs)
            if labels is not None:
                self._fitted = True
                return labels
        except Exception as e:
            logger.debug("BTCRegimeDetector HMM k=%d 失败: %s, 退化到阈值法", self.n_regimes, e)

        # 兜底: 简单 drawdown 阈值法
        return self._fallback_threshold(obs)

    def _fit_hmm(self, obs: np.ndarray) -> np.ndarray | None:
        """Markov-Regression k=3 拟合 + 标签排序."""
        if not _HAS_HMM:
            return None

        obs_2d = np.asarray(obs, dtype=float).reshape(-1, 1)
        # MarkovRegression 要求无 NaN, 有限值
        if not np.all(np.isfinite(obs_2d)):
            obs_2d = np.nan_to_num(obs_2d, nan=0.0, posinf=0.0, neginf=-1.0)

        model = MarkovRegression(obs_2d, k_regimes=self.n_regimes, trend="c")
        result = model.fit(maxiter=200, disp=False)

        probs = result.smoothed_marginal_probabilities  # (n, k)
        if probs is None:
            return None
        raw_labels = probs.argmax(axis=1)

        # 标签重排: 使 0=bull (drawdown 接近 0), 2=bear (drawdown 最负)
        # 即: 按 regime 内 drawdown 均值降序排, 最大值→0(bull), 最小值→2(bear)
        n_regimes = self.n_regimes
        mean_obs = np.array([
            float(np.mean(obs[raw_labels == k])) if (raw_labels == k).any() else 0.0
            for k in range(n_regimes)
        ])
        # 降序: argsort(-mean_obs) 给出 [最大值的 idx, ..., 最小值的 idx]
        order = np.argsort(-mean_obs)  # order[0]=bull 原始 idx, order[2]=bear 原始 idx
        remap = np.zeros(n_regimes, dtype=int)
        for new_label, old_label in enumerate(order):
            remap[old_label] = new_label
        self._regime_order = order.tolist()
        return remap[raw_labels]

    def _fallback_threshold(self, obs: np.ndarray) -> np.ndarray:
        """drawdown 阈值法兜底 (HMM 不可用 / 不收敛时).

        - drawdown > -0.10: bull (0)  — 接近历史高点
        - drawdown < -0.30: bear (2)  — 深度回撤
        - 其它: chop (1)  — 中等震荡
        """
        labels = np.ones(obs.size, dtype=int)  # 默认 chop
        labels[obs > -0.10] = 0  # bull
        labels[obs < -0.30] = 2  # bear
        return labels

    # ------------------------------------------------------------------
    # 持久化 (T1.8 验证)
    # ------------------------------------------------------------------
    def save_labels(self, path: str, labels: np.ndarray) -> None:
        """保存 regime labels 到 .npy 文件供训练数据准备复用."""
        labels = np.asarray(labels, dtype=int)
        np.save(path, labels)
        logger.info("BTCRegimeDetector: regime labels 保存到 %s (shape=%s)", path, labels.shape)

    @staticmethod
    def load_labels(path: str) -> np.ndarray:
        """从 .npy 文件加载 regime labels."""
        labels = np.load(path)
        return labels.astype(int)

    # ------------------------------------------------------------------
    # P0.2: regime-transition 建模 (Markov transition matrix)
    # 解决 T7 OOS 根因 3: regime 标签同质化 (2024 伪 bull 与训练集 bull 动态不同)
    # ------------------------------------------------------------------
    def estimate_transition_matrix(self, regime_labels: np.ndarray) -> np.ndarray:
        """估计 n_regimes × n_regimes 转移概率矩阵 Q.

        Q[i,j] = P(regime j at t+1 | regime i at t) = count(i→j) / count(i)

        Args:
            regime_labels: 1d int array, regime label per timestep

        Returns:
            np.ndarray (n_regimes, n_regimes): 转移概率矩阵, 每行和为 1.
            短序列 (<2) 或某 regime 无数据 → 对应行退化为单位阵 (FAIL-OPEN).
        """
        labels = np.asarray(regime_labels, dtype=int).ravel()
        n = labels.size
        k = self.n_regimes
        Q = np.eye(k, dtype=float)  # 默认单位阵 (FAIL-OPEN 兜底)

        if n < 2:
            return Q

        # 统计转移计数
        counts = np.zeros((k, k), dtype=float)
        for i in range(n - 1):
            src = labels[i]
            dst = labels[i + 1]
            if 0 <= src < k and 0 <= dst < k:
                counts[src, dst] += 1.0

        # 归一化: 每行除以行和
        row_sums = counts.sum(axis=1, keepdims=True)
        for i in range(k):
            if row_sums[i, 0] > 0:
                Q[i] = counts[i] / row_sums[i, 0]
            # 无数据的行保持单位阵 (Q[i] = eye row)

        return Q

    def stationary_distribution(self, Q: np.ndarray) -> np.ndarray:
        """计算 Markov chain 的平稳分布 π (解 πQ = π).

        方法: 解 (Q^T - I)π = 0, s.t. sum(π)=1
        用特征值分解: Q^T 的特征值 1 对应的特征向量, 归一化到和为 1.

        Args:
            Q: (n_regimes, n_regimes) 转移概率矩阵

        Returns:
            np.ndarray (n_regimes,): 平稳分布, 元素非负, 和为 1.
            若 Q 不可约/计算失败 → 均匀分布兜底 (FAIL-OPEN).
        """
        Q = np.asarray(Q, dtype=float)
        k = Q.shape[0]

        try:
            # Q^T 的左特征向量 = π
            eigenvalues, eigenvectors = np.linalg.eig(Q.T)
            # 找最接近 1 的特征值
            idx = np.argmin(np.abs(eigenvalues - 1.0))
            pi = np.real(eigenvectors[:, idx])
            # 归一化: 确保非负且和为 1
            pi = np.abs(pi)
            pi_sum = pi.sum()
            if pi_sum > 0:
                pi = pi / pi_sum
            else:
                pi = np.ones(k) / k
            return pi
        except Exception:
            return np.ones(k) / k  # FAIL-OPEN: 均匀分布

    def regime_uncertainty(self, Q: np.ndarray, current_regime: int) -> float:
        """计算当前 regime 的预测熵 (不确定性).

        H = -sum_j Q[i,j] * log(Q[i,j])

        熵高 = 当前 regime 不稳定, 切换频繁 → 降权 NeuralSDE
        熵低 = 当前 regime 稳定, 自转移概率高 → 信任 NeuralSDE

        Args:
            Q: (n_regimes, n_regimes) 转移概率矩阵
            current_regime: 当前 regime 标签 (0..n_regimes-1)

        Returns:
            float: 熵值 (nats). 范围 [0, log(n_regimes)].
            current_regime 越界 → 返回最大熵 (FAIL-OPEN, 最保守).
        """
        Q = np.asarray(Q, dtype=float)
        k = Q.shape[0]

        if not (0 <= current_regime < k):
            return float(np.log(k))  # FAIL-OPEN: 最大熵

        row = Q[current_regime]
        # 熵: -sum(p * log(p)), 跳过 p=0
        entropy = 0.0
        for p in row:
            if p > 0:
                entropy -= p * np.log(p)
        return float(entropy)
