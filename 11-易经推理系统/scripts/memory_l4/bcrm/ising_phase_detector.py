"""
Ising相变检测器 — 统计力学市场集体状态识别。

基于二维Ising模型（Onsager精确解），将市场建模为自旋格子系统：
    - 资产收益符号 = 自旋 s_i ∈ {+1(涨), -1(跌)}
    - 资产间相关性 = 交互强度 J_ij（默认最近邻耦合）
    - 磁化强度 M = |Σs_i|/N → 市场共识度
    - 能量 E = -ΣJ_ij·s_i·s_j → 市场紧张度
    - 温度 T ∝ 波动率² → 有序/无序相变

相变判定：
    - T < Tc 且 |M| > 阈值 → 有序相（强趋势）
    - T > Tc 且 |M| ≈ 0 → 无序相（震荡）
    - 能量突变 E > mean + factor×std → 相变预警（牛熊转换）

与力学引擎/A0的关系（三层交叉验证）：
    - 微观层（Ising自旋）：市场集体行为
    - 宏观层（A0矛盾）：多空矛盾张力
    - 物理层（力学引擎）：趋势动力学
    三层独立信号交叉验证，提高信号可靠性
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from collections import deque
import numpy as np

from ._constants import (
    ISING_GRID_SIZE,
    ISING_INTERACTION_BASE,
    ISING_TEMP_SCALE,
    ISING_TEMP_CRITICAL,
    ISING_ORDERED_RATIO,
    ISING_DISORDERED_RATIO,
    ISING_MAGNETIZATION_THRESHOLD,
    ISING_ENERGY_SPIKE_FACTOR,
    ISING_WINDOW_SIZE,
    DIR_UP, DIR_DOWN, DIR_FLAT, DIR_UNKNOWN,
)


@dataclass
class IsingPhaseResult:
    """Ising相变检测结果"""
    magnetization: float = 0.0       # 磁化强度 M ∈ [-1, 1]，|M|高=共识强
    energy: float = 0.0              # 能量 E（负值，越负越有序）
    temperature: float = 0.0         # 温度 T ∝ 波动率²
    phase: str = "UNKNOWN"           # 相态：ORDERED(有序/趋势) / DISORDERED(无序/震荡) / CRITICAL(临界)
    direction: str = DIR_UNKNOWN     # 市场方向：M>0=UP, M<0=DOWN, M≈0=FLAT
    consensus_strength: float = 0.0  # 共识强度 = |M| ∈ [0, 1]
    phase_transition_alert: bool = False  # 相变预警（能量突变）
    transition_probability: float = 0.0   # 相变概率 ∈ [0, 1]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "magnetization": round(self.magnetization, 4),
            "energy": round(self.energy, 4),
            "temperature": round(self.temperature, 4),
            "phase": self.phase,
            "direction": self.direction,
            "consensus_strength": round(self.consensus_strength, 4),
            "phase_transition_alert": self.phase_transition_alert,
            "transition_probability": round(self.transition_probability, 4),
        }


class IsingPhaseDetector:
    """
    Ising相变检测器 — 纯代码驱动统计力学模型。

    用法：
        detector = IsingPhaseDetector()
        # 输入最近N个K线的收益符号序列
        result = detector.detect(returns, volatility=0.03)
    """

    def __init__(
        self,
        grid_size: int = ISING_GRID_SIZE,
        interaction_base: float = ISING_INTERACTION_BASE,
    ):
        """
        初始化Ising相变检测器。

        Args:
            grid_size: 自旋网格边长 N（N×N个自旋）
            interaction_base: 基础交互强度 J
        """
        self.grid_size = grid_size
        self.n_spins = grid_size * grid_size
        self.J = interaction_base

        # 构建最近邻交互矩阵（周期性边界条件，Onsager模型）
        self._interaction_matrix = self._build_neighbor_interactions()

        # 能量历史（用于突变检测）
        self._energy_history: deque = deque(maxlen=ISING_WINDOW_SIZE)
        self._magnetization_history: deque = deque(maxlen=ISING_WINDOW_SIZE)

    def _build_neighbor_interactions(self) -> np.ndarray:
        """
        构建最近邻交互矩阵（二维格子，周期性边界）。

        Ising哈密顿量：H = -J Σ_{<i,j>} s_i · s_j
        其中 <i,j> 表示最近邻对。
        """
        n = self.n_spins
        # 交互矩阵 J_ij（仅最近邻非零）
        interaction = np.zeros((n, n))
        gs = self.grid_size

        for i in range(gs):
            for j in range(gs):
                idx = i * gs + j
                # 四个最近邻（周期性边界）
                neighbors = [
                    ((i + 1) % gs) * gs + j,  # 下
                    ((i - 1) % gs) * gs + j,  # 上
                    i * gs + (j + 1) % gs,    # 右
                    i * gs + (j - 1) % gs,    # 左
                ]
                for nb in neighbors:
                    interaction[idx, nb] = self.J

        return interaction

    def detect(
        self,
        returns: np.ndarray,
        volatility: float = 0.03,
    ) -> IsingPhaseResult:
        """
        检测市场相变状态。

        Args:
            returns: 收益率序列（一维数组，长度≥n_spins）
                     会取最近 n_spins 个值，转为自旋 ±1
            volatility: 当前波动率（用于映射温度）

        Returns:
            IsingPhaseResult
        """
        # Step 1: 收益率 → 自旋 ±1
        spins = self._returns_to_spins(returns)

        # Step 2: 计算磁化强度 M = Σs_i / N
        magnetization = float(np.mean(spins))

        # Step 3: 计算能量 E = -Σ J_ij · s_i · s_j
        energy = self._compute_energy(spins)

        # Step 4: 计算温度 T = scale × volatility（线性映射）
        # vol=0.02→T=1.2(有序), vol=0.03→T=1.8(临界附近), vol=0.05→T=3.0(无序)
        temperature = ISING_TEMP_SCALE * volatility

        # Step 5: 判定相态
        phase, transition_prob = self._determine_phase(
            magnetization, energy, temperature
        )

        # Step 6: 方向判定
        if abs(magnetization) < ISING_MAGNETIZATION_THRESHOLD * 0.5:
            direction = DIR_FLAT
        elif magnetization > 0:
            direction = DIR_UP
        else:
            direction = DIR_DOWN

        # Step 7: 能量突变检测（相变预警）
        alert = self._detect_energy_spike(energy)

        # Step 7b: ORDERED相趋势衰竭检测
        # 物理意义：有序相中磁化强度持续下降 = 趋势失去动能 = 转折前兆
        if not alert and phase == "ORDERED":
            alert = self._detect_trend_exhaustion(magnetization)

        # Step 8: 共识强度
        consensus = abs(magnetization)

        result = IsingPhaseResult(
            magnetization=magnetization,
            energy=energy,
            temperature=temperature,
            phase=phase,
            direction=direction,
            consensus_strength=consensus,
            phase_transition_alert=alert,
            transition_probability=transition_prob,
        )

        # 更新历史
        self._energy_history.append(energy)
        self._magnetization_history.append(magnetization)

        return result

    def _returns_to_spins(self, returns: np.ndarray) -> np.ndarray:
        """
        收益率序列 → 自旋 ±1。

        取最近 n_spins 个收益，正值→+1，负值→-1，零→+1（默认）。
        不足 n_spins 时用0填充（自旋=+1）。
        """
        returns = np.asarray(returns, dtype=float).flatten()
        if len(returns) < self.n_spins:
            # 不足时左侧填充0
            padding = np.zeros(self.n_spins - len(returns))
            returns = np.concatenate([padding, returns])

        # 取最近 n_spins 个
        recent = returns[-self.n_spins:]
        # 转为自旋 ±1
        spins = np.where(recent >= 0, 1.0, -1.0)
        return spins

    def _compute_energy(self, spins: np.ndarray) -> float:
        """
        计算Ising能量 E = -Σ J_ij · s_i · s_j / N。

        归一化到 [-J, +J]，便于跨标的比较。
        负能量=有序（同向自旋多），正能量=无序（反向自旋多）。
        """
        # 向量化计算：E = -s^T · J · s / (2N)（除2因为每对计算两次）
        energy = -0.5 * float(spins @ self._interaction_matrix @ spins) / self.n_spins
        return energy

    def _determine_phase(
        self,
        magnetization: float,
        energy: float,
        temperature: float,
    ) -> Tuple[str, float]:
        """
        判定相态和相变概率。

        Onsager精确解：二维Ising模型临界温度 Tc ≈ 2.269·J/k
        - T < Tc × ordered_ratio：有序相（铁磁态），|M| > 0
        - T > Tc × disordered_ratio：无序相（顺磁态），M ≈ 0
        - 中间区域：临界相（涨落最大）

        相变概率：基于温度接近Tc的程度 + 磁化强度变化率
        """
        Tc = ISING_TEMP_CRITICAL
        consensus = abs(magnetization)

        # 温度比 r = T / Tc
        temp_ratio = temperature / Tc if Tc > 0 else 0

        ordered_thresh = ISING_ORDERED_RATIO      # 0.85
        disordered_thresh = ISING_DISORDERED_RATIO  # 1.15

        if temp_ratio < ordered_thresh:
            # 远低于临界温度 → 有序相（强趋势）
            phase = "ORDERED"
            transition_prob = max(0.0, (temp_ratio - 0.5) / (ordered_thresh - 0.5)) * 0.3
        elif temp_ratio > disordered_thresh:
            # 远高于临界温度 → 无序相（震荡）
            phase = "DISORDERED"
            transition_prob = max(0.0, (2.0 - temp_ratio) / (2.0 - disordered_thresh)) * 0.3
        else:
            # 临界区域 → 临界相（收紧范围，减少误报）
            phase = "CRITICAL"
            # 距离Tc越近概率越高
            center = (ordered_thresh + disordered_thresh) / 2  # 1.0
            width = (disordered_thresh - ordered_thresh) / 2   # 0.15
            distance = abs(temp_ratio - center) / width
            transition_prob = max(0.0, 1.0 - distance)

        # 磁化强度修正：有序相但共识低 且 温度接近临界 → 可能正在相变
        # 远低于临界温度时（T<<Tc），即使M低也可能是弱有序（而非相变）
        if phase == "ORDERED" and consensus < ISING_MAGNETIZATION_THRESHOLD and temp_ratio > 0.6:
            phase = "CRITICAL"
            transition_prob = max(transition_prob, 0.4)

        return phase, min(1.0, transition_prob)

    def _detect_energy_spike(self, current_energy: float) -> bool:
        """
        能量突变检测（相变早期预警）。

        当当前能量显著偏离历史均值（> mean + factor×std）时，
        判定为相变预警。

        物理意义：能量突变对应序参量的剧烈变化，预示相变发生。
        """
        if len(self._energy_history) < 5:
            # 历史不足，无法判断突变
            return False

        history = list(self._energy_history)
        mean_e = float(np.mean(history))
        std_e = float(np.std(history))

        if std_e < 1e-9:
            return False

        # 能量突变：|E - mean| > factor × std
        deviation = abs(current_energy - mean_e)
        return deviation > ISING_ENERGY_SPIKE_FACTOR * std_e

    def _detect_trend_exhaustion(self, current_magnetization: float) -> bool:
        """
        ORDERED相趋势衰竭检测。

        物理意义：有序相中磁化强度|M|持续下降 = 共识减弱 = 趋势即将结束。
        这是Ising模型中有序→无序相变的前兆信号。

        判定条件：
        1. 前5个|M|均值 >= 0.2（存在真实趋势，非低共识噪声）
        2. 最近5个|M|均值比前5个下降超过50%（显著衰竭）
        """
        if len(self._magnetization_history) < 10:
            return False

        history = list(self._magnetization_history)
        # 取最近10个磁化强度的绝对值
        abs_m = [abs(m) for m in history[-10:]]
        recent_mean = float(np.mean(abs_m[-5:]))
        earlier_mean = float(np.mean(abs_m[:5]))

        # 必须存在真实趋势（|M|够高）才检测衰竭
        if earlier_mean < 0.2:
            return False

        # 磁化强度下降比例
        decline_ratio = (earlier_mean - recent_mean) / earlier_mean

        # 下降超过50% = 趋势衰竭
        return decline_ratio > 0.5

    def get_phase_trend(self) -> Dict[str, Any]:
        """
        获取相态趋势（基于磁化强度历史）。

        用于判断市场是否正在从有序→无序（趋势衰竭）或反向。
        """
        if len(self._magnetization_history) < 3:
            return {"trend": "INSUFFICIENT_DATA", "delta_m": 0.0}

        history = list(self._magnetization_history)
        # 近5个 vs 前5个的磁化强度变化
        recent = history[-5:] if len(history) >= 5 else history[-3:]
        earlier = history[:-len(recent)] if len(history) > len(recent) else history[:1]
        delta_m = float(np.mean(np.abs(recent)) - np.mean(np.abs(earlier)))

        if delta_m > 0.05:
            trend = "INCREASING_CONSENSUS"  # 共识增强（趋势形成）
        elif delta_m < -0.05:
            trend = "DECREASING_CONSENSUS"  # 共识减弱（趋势衰竭）
        else:
            trend = "STABLE"

        return {"trend": trend, "delta_m": round(delta_m, 4)}

    def reset(self):
        """重置历史状态。"""
        self._energy_history.clear()
        self._magnetization_history.clear()
