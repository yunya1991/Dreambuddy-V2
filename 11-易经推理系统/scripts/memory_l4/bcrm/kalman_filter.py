"""
卡尔曼滤波器 — 力学引擎后处理滤波层。

基于 pykalman 库（成熟稳定的开源实现），对力学引擎输出的
速度和加速度进行贝叶斯状态估计，过滤市场高频噪声。

物理模型（匀加速运动）：
    状态向量 x = [velocity, acceleration]^T
    状态转移 F = [[1, dt], [0, 1]]
    观测 H = [[1, 0]]（观测=速度=价格变化率）

噪声自适应：
    过程噪声 Q ∝ 波动率（市场突发风险，VIX正相关）
    观测噪声 R ∝ 买卖价差（微观结构噪声）

与力学引擎的关系：
    力学引擎（Verlet+Langevin）输出 → 卡尔曼滤波平滑 → 最终信号
    力学引擎负责物理推理，卡尔曼负责噪声过滤，职责分离
"""

from typing import Dict, Any, Optional, Tuple
import numpy as np
from pykalman import KalmanFilter

from ._constants import (
    KALMAN_PROCESS_NOISE_VEL, KALMAN_PROCESS_NOISE_ACC,
    KALMAN_OBS_NOISE_BASE, KALMAN_VOLATILITY_FACTOR,
    KALMAN_SPREAD_FACTOR, KALMA_INITIAL_COV,
)


class VelocityKalmanFilter:
    """
    速度-加速度卡尔曼滤波器。

    使用 pykalman 的 EM 自适应 + 在线 filter 接口，
    对力学引擎输出的速度序列进行平滑估计。

    用法：
        kf = VelocityKalmanFilter()
        # 逐帧滤波
        smoothed_v, smoothed_a = kf.update(raw_velocity, volatility, spread)
    """

    def __init__(
        self,
        dt: float = 1.0,
        process_noise_vel: float = KALMAN_PROCESS_NOISE_VEL,
        process_noise_acc: float = KALMAN_PROCESS_NOISE_ACC,
        obs_noise_base: float = KALMAN_OBS_NOISE_BASE,
    ):
        """
        初始化卡尔曼滤波器。

        Args:
            dt: 时间步长（与力学引擎 ACCELERATION_DT 一致）
            process_noise_vel: 速度过程噪声基础值
            process_noise_acc: 加速度过程噪声基础值
            obs_noise_base: 观测噪声基础值
        """
        self.dt = dt
        self.process_noise_vel = process_noise_vel
        self.process_noise_acc = process_noise_acc
        self.obs_noise_base = obs_noise_base

        # 初始状态：[velocity=0, acceleration=0]
        self._initial_state_mean = np.array([0.0, 0.0])
        self._initial_state_covariance = np.eye(2) * KALMA_INITIAL_COV

        # 内部 pykalman 实例（延迟初始化，首次 update 时构建）
        self._kf: Optional[KalmanFilter] = None
        self._filtered_state: Optional[np.ndarray] = None
        self._filtered_cov: Optional[np.ndarray] = None
        self._step_count: int = 0

    def _build_kf(self, volatility: float, spread: float) -> KalmanFilter:
        """
        根据当前市场状态构建/更新卡尔曼滤波器参数。

        自适应噪声：
            Q = diag(q_v × (1 + factor × vol), q_a × (1 + factor × vol))
            R = r × (1 + spread_factor × spread)

        Args:
            volatility: 当前波动率
            spread: 当前买卖价差比率
        """
        # 过程噪声随波动率放大（高波动=大过程不确定性）
        vol_factor = 1.0 + KALMAN_VOLATILITY_FACTOR * volatility
        q_v = self.process_noise_vel * vol_factor
        q_a = self.process_noise_acc * vol_factor

        # 观测噪声随买卖价差放大（大价差=大观测不确定性）
        spread_factor = 1.0 + KALMAN_SPREAD_FACTOR * spread
        r = self.obs_noise_base * spread_factor

        # 状态转移矩阵：匀加速运动
        transition_matrices = np.array([
            [1.0, self.dt],
            [0.0, 1.0],
        ])
        # 观测矩阵：只观测速度
        observation_matrices = np.array([[1.0, 0.0]])
        # 过程噪声协方差
        transition_covariance = np.diag([q_v, q_a])
        # 观测噪声协方差（标量）
        observation_covariance = np.array([[r]])

        return KalmanFilter(
            transition_matrices=transition_matrices,
            observation_matrices=observation_matrices,
            transition_covariance=transition_covariance,
            observation_covariance=observation_covariance,
            initial_state_mean=self._initial_state_mean,
            initial_state_covariance=self._initial_state_covariance,
        )

    def update(
        self,
        raw_velocity: float,
        volatility: float = 0.03,
        spread: float = 0.0,
    ) -> Tuple[float, float]:
        """
        在线滤波一步更新（预测-更新循环）。

        Args:
            raw_velocity: 力学引擎输出的原始速度（含噪声）
            volatility: 当前波动率（用于自适应过程噪声）
            spread: 当前买卖价差比率（用于自适应观测噪声）

        Returns:
            (smoothed_velocity, smoothed_acceleration): 滤波后的速度和加速度
        """
        # 构建当前帧的滤波器（参数自适应市场状态）
        kf = self._build_kf(volatility, spread)

        if self._filtered_state is None:
            # 首帧：直接用观测初始化
            self._filtered_state = np.array([raw_velocity, 0.0])
            self._filtered_cov = self._initial_state_covariance.copy()
            self._kf = kf
            self._step_count = 1
            return float(self._filtered_state[0]), float(self._filtered_state[1])

        # 使用 pykalman 的 filter_update 进行单步在线滤波
        self._filtered_state, self._filtered_cov = kf.filter_update(
            filtered_state_mean=self._filtered_state,
            filtered_state_covariance=self._filtered_cov,
            observation=np.array([raw_velocity]),
        )
        self._kf = kf
        self._step_count += 1

        return float(self._filtered_state[0]), float(self._filtered_state[1])

    def filter_batch(
        self,
        raw_velocities: np.ndarray,
        volatilities: Optional[np.ndarray] = None,
        spreads: Optional[np.ndarray] = None,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        批量滤波（离线平滑模式，使用 EM + smooth）。

        适用于回测场景：一次性输入完整速度序列，输出平滑结果。
        比在线模式更精确（利用了未来信息）。

        Args:
            raw_velocities: 原始速度序列 shape=(N,)
            volatilities: 波动率序列 shape=(N,)，None 则用均值
            spreads: 价差序列 shape=(N,)，None 则用0

        Returns:
            (smoothed_velocities, smoothed_accelerations): shape=(N,)
        """
        raw_velocities = np.asarray(raw_velocities, dtype=float).reshape(-1, 1)
        n = len(raw_velocities)

        if volatilities is None:
            volatilities = np.full(n, 0.03)
        if spreads is None:
            spreads = np.zeros(n)

        # 用平均市场状态构建固定参数滤波器（批量模式不支持逐帧自适应）
        avg_vol = float(np.mean(volatilities))
        avg_spread = float(np.mean(spreads))
        kf = self._build_kf(avg_vol, avg_spread)

        # 使用 smooth 接口（前向-后向平滑，比 filter 更精确）
        smoothed_state_means, _ = kf.smooth(raw_velocities)

        return smoothed_state_means[:, 0], smoothed_state_means[:, 1]

    def reset(self):
        """重置滤波器状态（新标的或新会话时调用）。"""
        self._filtered_state = None
        self._filtered_cov = None
        self._kf = None
        self._step_count = 0

    def get_state(self) -> Dict[str, Any]:
        """获取当前滤波器内部状态（调试用）。"""
        return {
            "step_count": self._step_count,
            "filtered_velocity": float(self._filtered_state[0]) if self._filtered_state is not None else 0.0,
            "filtered_acceleration": float(self._filtered_state[1]) if self._filtered_state is not None else 0.0,
            "filtered_cov": self._filtered_cov.tolist() if self._filtered_cov is not None else None,
        }
