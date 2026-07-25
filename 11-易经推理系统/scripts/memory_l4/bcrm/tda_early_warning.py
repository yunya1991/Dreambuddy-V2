"""
TDA持久同调早期预警 — 代数拓扑转折点检测。

基于Takens延迟嵌入定理和Vietoris-Rips持久同调，检测时间序列
拓扑结构变化，在动力学转折（reversal_warning）之前发出预警。

数学原理：
    1. Takens嵌入：一维时间序列 → 高维相空间点云
       x(t) → [x(t), x(t+τ), x(t+2τ), ..., x(t+(m-1)τ)]
       m=嵌入维度, τ=延迟参数
    2. Vietoris-Rips复形：点云按距离阈值ε连接为单纯复形
    3. 持久同调：计算拓扑特征（H0=连通分量, H1=环）的生命周期
       (birth, death) → 持久性 = death - birth
    4. Betti曲线 β(t)：每个阈值ε下的拓扑特征数
       β突增 = 拓扑结构变化 = 转折早期信号
    5. 瓶颈距离：当前持久图 vs 历史均值持久图的距离
       距离突增 = 拓扑突变 = 转折确认

优势（相比力学引擎reversal_warning）：
    - 拓扑先于动力学：结构变化领先于速度减速
    - 多尺度：H0捕捉全局连通性，H1捕捉局部环结构
    - 噪声鲁棒：持久同调对噪声天然鲁棒（短寿命特征=噪声）

实现库：ripser（最快持久同调计算）+ persim（持久图距离度量）
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from collections import deque
import numpy as np

from ._constants import (
    TDA_EMBEDDING_DIM,
    TDA_EMBEDDING_DELAY,
    TDA_WINDOW_SIZE,
    TDA_MAX_PERSISTENCE_DIM,
    TDA_BETTI_SPIKE_FACTOR,
    TDA_PERSISTENCE_RATIO_THRESHOLD,
    TDA_BOTTLENECK_DISTANCE_THRESHOLD,
    TDA_MIN_POINTS,
    DIR_UP, DIR_DOWN, DIR_FLAT, DIR_UNKNOWN,
)


@dataclass
class TDAResult:
    """TDA持久同调检测结果"""
    betti_0: int = 0                    # H0连通分量数（拓扑碎片化程度）
    betti_1: int = 0                    # H1环数（周期性/振荡结构）
    betti_curve_max: float = 0.0        # Betti曲线峰值
    persistence_ratio: float = 0.0      # 长寿命特征占比（稳定性指标）
    bottleneck_distance: float = 0.0    # 与历史拓扑的瓶颈距离
    topological_stability: float = 0.0  # 拓扑稳定性 [0,1]
    early_warning: bool = False         # 早期转折预警
    warning_strength: float = 0.0       # 预警强度 [0,1]
    direction: str = DIR_UNKNOWN        # 拓扑推断方向
    has_sufficient_data: bool = False   # 数据是否充足

    def to_dict(self) -> Dict[str, Any]:
        return {
            "betti_0": self.betti_0,
            "betti_1": self.betti_1,
            "betti_curve_max": round(self.betti_curve_max, 4),
            "persistence_ratio": round(self.persistence_ratio, 4),
            "bottleneck_distance": round(self.bottleneck_distance, 4),
            "topological_stability": round(self.topological_stability, 4),
            "early_warning": self.early_warning,
            "warning_strength": round(self.warning_strength, 4),
            "direction": self.direction,
            "has_sufficient_data": self.has_sufficient_data,
        }


class TDAEarlyWarning:
    """
    TDA持久同调早期预警器。

    用法：
        detector = TDAEarlyWarning()
        result = detector.detect(price_series)
    """

    def __init__(
        self,
        embedding_dim: int = TDA_EMBEDDING_DIM,
        embedding_delay: int = TDA_EMBEDDING_DELAY,
        window_size: int = TDA_WINDOW_SIZE,
        max_dim: int = TDA_MAX_PERSISTENCE_DIM,
    ):
        """
        初始化TDA早期预警器。

        Args:
            embedding_dim: Takens嵌入维度 m
            embedding_delay: 嵌入延迟 τ
            window_size: 滑动窗口大小
            max_dim: 最高同调维度（0=H0, 1=H0+H1）
        """
        self.embedding_dim = embedding_dim
        self.embedding_delay = embedding_delay
        self.window_size = window_size
        self.max_dim = max_dim

        # Betti曲线历史（用于突变检测）
        self._betti_history: deque = deque(maxlen=window_size)
        # 历史持久图（用于瓶颈距离计算）
        self._prev_diagrams: Optional[List[np.ndarray]] = None

    def detect(self, price_series: np.ndarray) -> TDAResult:
        """
        检测时间序列的拓扑结构变化。

        Args:
            price_series: 价格序列（一维数组）

        Returns:
            TDAResult
        """
        result = TDAResult()

        price_series = np.asarray(price_series, dtype=float).flatten()

        # 数据充足性检查
        min_required = TDA_MIN_POINTS + self.embedding_dim * self.embedding_delay
        if len(price_series) < min_required:
            result.has_sufficient_data = False
            return result

        result.has_sufficient_data = True

        # Step 1: Takens延迟嵌入 → 相空间点云
        point_cloud = self._takens_embedding(price_series)
        if len(point_cloud) < TDA_MIN_POINTS:
            result.has_sufficient_data = False
            return result

        # Step 2: 计算持久同调
        diagrams = self._compute_persistence(point_cloud)
        if diagrams is None or len(diagrams) == 0:
            return result

        # Step 3: 提取Betti数和持久性统计
        betti_0, betti_1, persistence_ratio, betti_max = \
            self._extract_topological_features(diagrams)
        result.betti_0 = betti_0
        result.betti_1 = betti_1
        result.betti_curve_max = betti_max
        result.persistence_ratio = persistence_ratio

        # Step 4: 计算拓扑稳定性（长寿命特征占比）
        result.topological_stability = persistence_ratio

        # Step 5: 瓶颈距离（与历史拓扑对比）
        result.bottleneck_distance = self._compute_bottleneck_distance(diagrams)

        # Step 6: 早期转折预警
        result.early_warning, result.warning_strength = \
            self._detect_early_warning(betti_max, result.bottleneck_distance)

        # Step 7: 方向推断（基于点云趋势）
        result.direction = self._infer_direction(point_cloud)

        # 更新历史
        self._betti_history.append(betti_max)
        self._prev_diagrams = diagrams

        return result

    def _takens_embedding(self, series: np.ndarray) -> np.ndarray:
        """
        Takens延迟嵌入：一维时间序列 → m维相空间点云。

        x(t) → [x(t), x(t+τ), x(t+2τ), ..., x(t+(m-1)τ)]

        Takens定理：当m足够大时，重构的相空间与原系统拓扑等价。
        """
        m = self.embedding_dim
        tau = self.embedding_delay
        n = len(series)

        # 嵌入后的点数
        n_points = n - (m - 1) * tau
        if n_points < TDA_MIN_POINTS:
            return np.array([])

        # 构建点云 shape=(n_points, m)
        point_cloud = np.zeros((n_points, m))
        for i in range(m):
            point_cloud[:, i] = series[i * tau: i * tau + n_points]

        # 标准化（消除量纲影响，聚焦拓扑结构）
        std = np.std(point_cloud)
        if std > 1e-9:
            point_cloud = (point_cloud - np.mean(point_cloud)) / std

        return point_cloud

    def _compute_persistence(self, point_cloud: np.ndarray):
        """
        使用ripser计算Vietoris-Rips持久同调。

        返回持久图列表：diagrams[k] = shape=(n_features, 2) 的(birth, death)数组
        k=0: H0连通分量, k=1: H1环
        """
        try:
            from ripser import ripser
            result = ripser(point_cloud, maxdim=self.max_dim)
            return result['dgms']
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"[TDA] ripser计算失败: {e}")
            return None

    def _extract_topological_features(
        self, diagrams: List[np.ndarray]
    ) -> Tuple[int, int, float, float]:
        """
        从持久图提取拓扑特征。

        Returns:
            (betti_0, betti_1, persistence_ratio, betti_curve_max)
        """
        # H0: 连通分量
        dgm0 = diagrams[0] if len(diagrams) > 0 else np.array([])
        betti_0 = len(dgm0)

        # H1: 环
        dgm1 = diagrams[1] if len(diagrams) > 1 else np.array([])
        betti_1 = len(dgm1)

        # 持久性 = death - birth
        # 长寿命特征（持久性大）= 真实拓扑特征
        # 短寿命特征（持久性小）= 噪声
        all_persistences = []
        for dgm in diagrams:
            if len(dgm) > 0:
                persistences = dgm[:, 1] - dgm[:, 0]
                # 过滤inf（无限持久=永久特征）
                persistences = persistences[np.isfinite(persistences)]
                all_persistences.extend(persistences.tolist())

        if len(all_persistences) == 0:
            return betti_0, betti_1, 0.0, float(betti_0)

        # 长寿命特征占比（持久性 > 中位数 = 长寿命）
        persistences_arr = np.array(all_persistences)
        median_pers = np.median(persistences_arr)
        long_lived_ratio = float(np.mean(persistences_arr > median_pers))

        # Betti曲线峰值（最大特征数）
        betti_max = float(max(betti_0, betti_1)) if max(betti_0, betti_1) > 0 else 1.0

        return betti_0, betti_1, long_lived_ratio, betti_max

    def _compute_bottleneck_distance(self, diagrams: List[np.ndarray]) -> float:
        """
        计算与上一帧持久图的瓶颈距离。

        瓶颈距离大 = 拓扑结构发生显著变化 = 转折信号
        """
        if self._prev_diagrams is None:
            return 0.0

        try:
            from persim import bottleneck
            # 比较H0持久图
            dgm_current = diagrams[0] if len(diagrams) > 0 else np.array([])
            dgm_prev = self._prev_diagrams[0] if len(self._prev_diagrams) > 0 else np.array([])

            if len(dgm_current) == 0 or len(dgm_prev) == 0:
                return 0.0

            # 过滤inf点
            dgm_c = dgm_current[np.isfinite(dgm_current[:, 1])]
            dgm_p = dgm_prev[np.isfinite(dgm_prev[:, 1])]

            if len(dgm_c) == 0 or len(dgm_p) == 0:
                return 0.0

            distance = bottleneck(dgm_c, dgm_p)
            return float(distance) if distance is not None else 0.0
        except Exception:
            # persim失败时用简化距离（特征数差异）
            curr_features = sum(len(d) for d in diagrams)
            prev_features = sum(len(d) for d in self._prev_diagrams) if self._prev_diagrams else 0
            return float(abs(curr_features - prev_features))

    def _detect_early_warning(
        self, betti_max: float, bottleneck_dist: float
    ) -> Tuple[bool, float]:
        """
        早期转折预警检测。

        两个信号：
        1. Betti曲线突增：当前β > mean + factor×std（拓扑复杂度突变）
        2. 瓶颈距离突增：与历史拓扑差异 > 阈值（结构突变）

        Returns:
            (是否预警, 预警强度[0,1])
        """
        warning_signals = []

        # 信号1: Betti曲线突增（收紧阈值）
        if len(self._betti_history) >= 10:
            history = list(self._betti_history)
            mean_b = np.mean(history)
            std_b = np.std(history)
            if std_b > 1e-9:
                if betti_max > mean_b + TDA_BETTI_SPIKE_FACTOR * std_b * 2:
                    strength = min(1.0, (betti_max - mean_b) / (std_b * TDA_BETTI_SPIKE_FACTOR))
                    warning_signals.append(strength)

        # 信号2: 瓶颈距离突增（高阈值）
        if bottleneck_dist > TDA_BOTTLENECK_DISTANCE_THRESHOLD * 2:
            strength = min(1.0, bottleneck_dist / (TDA_BOTTLENECK_DISTANCE_THRESHOLD * 3))
            warning_signals.append(strength)

        if not warning_signals:
            return False, 0.0

        # 取最大预警强度
        return True, max(warning_signals)

    def _infer_direction(self, point_cloud: np.ndarray) -> str:
        """
        从点云推断趋势方向。

        用嵌入向量的首末分量差异判断方向：
        - 第一维（原始序列）首末差 > 0 = UP
        - < 0 = DOWN
        - ≈ 0 = FLAT
        """
        if len(point_cloud) < 2:
            return DIR_UNKNOWN

        first_dim = point_cloud[:, 0]
        # 用线性回归斜率判断方向（比首末差更鲁棒）
        n = len(first_dim)
        x = np.arange(n)
        slope = np.polyfit(x, first_dim, 1)[0]

        # 斜率阈值（标准化后的）
        threshold = 0.01
        if slope > threshold:
            return DIR_UP
        elif slope < -threshold:
            return DIR_DOWN
        else:
            return DIR_FLAT

    def reset(self):
        """重置历史状态。"""
        self._betti_history.clear()
        self._prev_diagrams = None
