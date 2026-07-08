"""
力学引擎 — BCRM 第一性原理层。

核心公式：
    F合 = Σ (Fi × wi)           # 四象力场加权合成
    a   = F合 / m                # 加速度 = 合力 / 市场质量
    v(t+Δt) = v(t)×decay + a×Δt  # 速度更新（含摩擦衰减）
    direction = sign(v)          # 趋势方向 = 速度方向
    strength  = |v|              # 趋势强度 = 速度大小
    reversal  = sign(a) ≠ sign(v)  # 转折预警 = 减速

四象力场（时空表里）：
    时（周期力）：康波/中周期/短周期的方向合成
    空（空间力）：价格位置的反重力（弹簧/皮球模型）
    表（技术力）：均线/MACD/RSI 等数字化表观
    里（内驱力）：供需/资金/情绪的内在驱动
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Tuple

from ._constants import (
    DIR_UP, DIR_DOWN, DIR_FLAT, DIR_TRANSITIONING, DIR_UNKNOWN,
    SIXIANG_TIME, SIXIANG_SPACE, SIXIANG_SURFACE, SIXIANG_CORE,
    FORCE_WEIGHT_CORE, FORCE_WEIGHT_SURFACE,
    FORCE_WEIGHT_TIME, FORCE_WEIGHT_SPACE,
    TIME_HORIZON_SHORT, TIME_HORIZON_MID, TIME_HORIZON_LONG,
    SPACE_EQUILIBRIUM, SPACE_SPRING_K,
    MARKET_MASS_BASE, MARKET_MASS_VOLATILITY_FACTOR,
    VELOCITY_DECAY, ACCELERATION_DT,
    REVERSAL_WARNING_THRESHOLD,
    FORCE_MAGNITUDE_NORM_FACTOR, VELOCITY_NORM_FACTOR,
    CONFIDENCE_WEIGHT_FORCE, CONFIDENCE_WEIGHT_AGREEMENT,
    CONFIDENCE_WEIGHT_VELOCITY,
    VELOCITY_ZERO_THRESHOLD, REVERSAL_STRENGTH_THRESHOLD,
)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class Force3D:
    """
    三维力向量。

    direction:    方向轴  +1=做多力, -1=做空力, 0=震荡
    time_horizon: 时间轴  0.3=短期, 0.6=中期, 1.0=长期
    certainty:    确定性轴 0-1
    """
    direction: float = 0.0
    time_horizon: float = 0.6
    certainty: float = 0.5

    def magnitude(self) -> float:
        """力的大小（标量）。"""
        return abs(self.direction) * self.certainty

    def signed_magnitude(self) -> float:
        """带符号的力大小（保留方向）。"""
        return self.direction * self.certainty

    def to_dict(self) -> Dict[str, Any]:
        return {
            "direction": round(self.direction, 4),
            "time_horizon": round(self.time_horizon, 4),
            "certainty": round(self.certainty, 4),
            "magnitude": round(self.magnitude(), 4),
            "signed_magnitude": round(self.signed_magnitude(), 4),
        }


@dataclass
class MarketForces:
    """四象力场集合。"""
    time_force: Force3D = field(default_factory=Force3D)      # 时：周期力
    space_force: Force3D = field(default_factory=Force3D)     # 空：空间力
    surface_force: Force3D = field(default_factory=Force3D)   # 表：技术力
    core_force: Force3D = field(default_factory=Force3D)      # 里：内驱力

    def all_forces(self) -> List[Tuple[str, Force3D, float]]:
        """返回 (名称, 力, 权重) 列表。"""
        return [
            (SIXIANG_TIME, self.time_force, FORCE_WEIGHT_TIME),
            (SIXIANG_SPACE, self.space_force, FORCE_WEIGHT_SPACE),
            (SIXIANG_SURFACE, self.surface_force, FORCE_WEIGHT_SURFACE),
            (SIXIANG_CORE, self.core_force, FORCE_WEIGHT_CORE),
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            SIXIANG_TIME: self.time_force.to_dict(),
            SIXIANG_SPACE: self.space_force.to_dict(),
            SIXIANG_SURFACE: self.surface_force.to_dict(),
            SIXIANG_CORE: self.core_force.to_dict(),
        }


@dataclass
class ForceResult:
    """
    力学引擎输出 — 核心推理结果。

    这是 BCRM 的第一性原理输出，决定趋势方向和强度。
    易经引擎接收此结果进行符号翻译。
    """
    # 合力
    net_force: Force3D = field(default_factory=Force3D)

    # 运动学
    acceleration: float = 0.0     # 加速度 a = F/m
    velocity: float = 0.0         # 当前速度（含历史惯性）
    prev_velocity: float = 0.0    # 前一步速度

    # 趋势判定
    direction: str = DIR_UNKNOWN  # 趋势方向 = sign(v)
    trend_strength: float = 0.0   # 趋势强度 = |v|
    confidence: float = 0.0       # 置信度

    # 转折预警
    reversal_warning: bool = False  # a 与 v 反向 = 减速
    reversal_strength: float = 0.0  # 减速强度

    # 四象力场详情
    forces: MarketForces = field(default_factory=MarketForces)

    # 市场质量
    market_mass: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "net_force": self.net_force.to_dict(),
            "acceleration": round(self.acceleration, 4),
            "velocity": round(self.velocity, 4),
            "prev_velocity": round(self.prev_velocity, 4),
            "direction": self.direction,
            "trend_strength": round(self.trend_strength, 4),
            "confidence": round(self.confidence, 4),
            "reversal_warning": self.reversal_warning,
            "reversal_strength": round(self.reversal_strength, 4),
            "forces": self.forces.to_dict(),
            "market_mass": round(self.market_mass, 4),
        }


# ============================================================
# 力学引擎
# ============================================================

class ForceEngine:
    """
    力学引擎 — 基于第一性原理的趋势推理。

    核心流程：
    1. 从市场快照提取四象力场
    2. 加权合成为合力
    3. 计算加速度 a = F/m
    4. 更新速度 v = v*decay + a*Δt
    5. 判定趋势方向和强度
    """

    def __init__(self):
        self.prev_velocity = 0.0  # 维护速度的历史状态

    def infer(self,
              market_snapshot: Dict[str, Any],
              prev_velocity: float = None,
              scale_params=None) -> ForceResult:
        """
        运行力学推理。

        Args:
            market_snapshot: 市场快照，包含四维评分、技术指标等
            prev_velocity: 前一步速度（None 则使用内部状态）
            scale_params: 体量自适应参数（None 则使用默认参数）

        Returns:
            ForceResult
        """
        if prev_velocity is None:
            prev_velocity = self.prev_velocity

        # 体量参数（如果未提供，使用默认）
        if scale_params is None:
            from .scale_engine import scale_to_params
            scale_params = scale_to_params(0.5)

        # Step 1: 提取四象力场
        forces = self._extract_forces(market_snapshot, scale_params)

        # Step 2: 合力计算（使用体量调整后的权重）
        net_force = self._compute_net_force(forces, scale_params)

        # Step 3: 市场质量（体量调整）
        volatility = market_snapshot.get("volatility", 0.5)
        market_mass = self._compute_market_mass(volatility, scale_params)

        # Step 4: 加速度 a = F/m
        acceleration = net_force.signed_magnitude() / market_mass

        # Step 5: 速度更新 v = v*decay + a*Δt（体量调整衰减率）
        velocity = (prev_velocity * scale_params.velocity_decay
                    + acceleration * ACCELERATION_DT)

        # Step 6: 趋势判定
        direction = self._direction_from_velocity(velocity)
        trend_strength = min(1.0, abs(velocity))

        # Step 7: 转折预警（体量调整阈值）
        reversal_warning, reversal_strength = self._check_reversal(
            velocity, acceleration, prev_velocity, scale_params)

        # Step 8: 置信度
        confidence = self._compute_confidence(
            net_force, forces, trend_strength, reversal_warning)

        # 更新内部速度状态
        self.prev_velocity = velocity

        return ForceResult(
            net_force=net_force,
            acceleration=acceleration,
            velocity=velocity,
            prev_velocity=prev_velocity,
            direction=direction,
            trend_strength=trend_strength,
            confidence=confidence,
            reversal_warning=reversal_warning,
            reversal_strength=reversal_strength,
            forces=forces,
            market_mass=market_mass,
        )

    # ============================================================
    # Step 1: 四象力场提取
    # ============================================================
    def _extract_forces(self, snapshot: Dict[str, Any],
                        scale_params=None) -> MarketForces:
        """从市场快照提取四象力场。"""

        # --- 时（周期力）---
        time_force = self._extract_time_force(snapshot)

        # --- 空（空间力）---
        space_force = self._extract_space_force(snapshot)

        # --- 表（技术力）---
        surface_force = self._extract_surface_force(snapshot)

        # --- 里（内驱力）---
        core_force = self._extract_core_force(snapshot)

        return MarketForces(
            time_force=time_force,
            space_force=space_force,
            surface_force=surface_force,
            core_force=core_force,
        )

    def _extract_time_force(self, snapshot: Dict) -> Force3D:
        """
        时（周期力）：长周期/中周期/短周期的方向合成。

        类似易经看时间 — 不同周期各有方向，合力为总时间力。
        """
        # 长周期（康波）：1.0 时间轴
        long_cycle = snapshot.get("long_cycle_position", 0.5)
        long_dir = (long_cycle - 0.5) * 2  # -1 ~ +1

        # 中周期：0.6 时间轴
        mid_cycle = snapshot.get("mid_cycle_position",
                                  snapshot.get("price_position", 0.5))
        mid_dir = (mid_cycle - 0.5) * 2

        # 短周期：0.3 时间轴
        short_cycle = snapshot.get("short_cycle_position",
                                    snapshot.get("trend_strength", 0.5))
        short_dir = (short_cycle - 0.5) * 2 if short_cycle > 0 else 0

        # 加权合成（长期权重最大）
        combined_dir = (long_dir * 0.5 + mid_dir * 0.3 + short_dir * 0.2)

        # 时间轴：取主导周期
        if abs(long_dir) > abs(mid_dir) and abs(long_dir) > abs(short_dir):
            time_horizon = TIME_HORIZON_LONG
        elif abs(mid_dir) > abs(short_dir):
            time_horizon = TIME_HORIZON_MID
        else:
            time_horizon = TIME_HORIZON_SHORT

        # 确定性：周期越一致，确定性越高
        directions = [long_dir, mid_dir, short_dir]
        signs = [1 if d > 0 else -1 if d < 0 else 0 for d in directions]
        agreement = sum(1 for i in range(len(signs) - 1)
                        if signs[i] == signs[i + 1]) / (len(signs) - 1)

        return Force3D(
            direction=max(-1.0, min(1.0, combined_dir)),
            time_horizon=time_horizon,
            certainty=0.3 + 0.7 * agreement,
        )

    def _extract_space_force(self, snapshot: Dict,
                              scale_params=None) -> Force3D:
        """
        空（空间力）：价格位置的反重力。

        皮球置于空中 — 偏离均衡越远，反向力越大。
        F = -k(x - x0)，x0=0.5 均衡位置
        k 随体量变化：小体量高敏感，大体量低敏感
        """
        price_position = snapshot.get("price_position", 0.5)

        # 弹簧系数：体量调整
        spring_k = SPACE_SPRING_K
        if scale_params:
            spring_k = scale_params.space_sensitivity

        # 弹簧模型：偏离均衡位置产生反向力
        deviation = price_position - SPACE_EQUILIBRIUM
        space_dir = -spring_k * deviation  # 反向

        # 确定性：偏离越远越确定（极端位置反弹概率高）
        certainty = min(1.0, abs(deviation) * 4)

        # 空间力通常是短期的
        return Force3D(
            direction=max(-1.0, min(1.0, space_dir)),
            time_horizon=TIME_HORIZON_SHORT,
            certainty=certainty,
        )

    def _extract_surface_force(self, snapshot: Dict) -> Force3D:
        """
        表（技术力）：技术分析数字化综合体现。

        均线排列、MACD、RSI、KDJ 等技术指标合成。
        """
        # 综合技术评分（0-1），>0.5 偏多，<0.5 偏空
        tech_score = snapshot.get("technical_score", 0.5)

        # 均线方向（如果有）
        ma_direction = snapshot.get("ma_direction", 0)
        # MACD 信号（如果有）
        macd_signal = snapshot.get("macd_signal", 0)
        # RSI（如果有）
        rsi = snapshot.get("rsi", 50)
        rsi_dir = (rsi - 50) / 50  # -1 ~ +1

        # 合成方向
        tech_dir = (tech_score - 0.5) * 2  # -1 ~ +1
        combined = (tech_dir * 0.4 + ma_direction * 0.25 +
                    macd_signal * 0.2 + rsi_dir * 0.15)

        # 确定性：技术指标一致性
        signals = [tech_dir, ma_direction, macd_signal, rsi_dir]
        signs = [1 if s > 0.05 else -1 if s < -0.05 else 0
                 for s in signals]
        non_zero = [s for s in signs if s != 0]
        if len(non_zero) > 1:
            agreement = sum(1 for i in range(len(non_zero) - 1)
                            if non_zero[i] == non_zero[i + 1]) / (len(non_zero) - 1)
        else:
            agreement = 0.5

        return Force3D(
            direction=max(-1.0, min(1.0, combined)),
            time_horizon=TIME_HORIZON_MID,
            certainty=0.3 + 0.7 * agreement,
        )

    def _extract_core_force(self, snapshot: Dict) -> Force3D:
        """
        里（内驱力）：供需/资金/情绪的内在驱动。

        最根本的力 — 决定市场的长期方向。
        """
        sd = snapshot.get("supply_demand_score", 0.5)
        cf = snapshot.get("capital_flow_score", 0.5)
        sent = snapshot.get("sentiment_score", 0.5)

        # 供需是核心中的核心
        sd_dir = (sd - 0.5) * 2
        cf_dir = (cf - 0.5) * 2
        sent_dir = (sent - 0.5) * 2

        # 加权合成（供需>资金>情绪）
        combined = sd_dir * 0.5 + cf_dir * 0.3 + sent_dir * 0.2

        # 确定性：三维一致性
        dirs = [sd_dir, cf_dir, sent_dir]
        signs = [1 if d > 0.05 else -1 if d < -0.05 else 0 for d in dirs]
        non_zero = [s for s in signs if s != 0]
        if len(non_zero) > 1:
            agreement = sum(1 for i in range(len(non_zero) - 1)
                            if non_zero[i] == non_zero[i + 1]) / (len(non_zero) - 1)
        else:
            agreement = 0.5

        # 内驱力是长期的
        return Force3D(
            direction=max(-1.0, min(1.0, combined)),
            time_horizon=TIME_HORIZON_LONG,
            certainty=0.4 + 0.6 * agreement,
        )

    # ============================================================
    # Step 2: 合力计算
    # ============================================================
    def _compute_net_force(self, forces: MarketForces,
                            scale_params=None) -> Force3D:
        """
        四象力场加权合成。

        F合 = Σ (Fi.direction × Fi.certainty × wi)
        wi 随体量动态调整。

        时间轴取加权主导周期。
        """
        # 体量调整后的权重
        if scale_params:
            weighted_list = [
                (SIXIANG_TIME, forces.time_force, scale_params.weight_time),
                (SIXIANG_SPACE, forces.space_force, scale_params.weight_space),
                (SIXIANG_SURFACE, forces.surface_force, scale_params.weight_surface),
                (SIXIANG_CORE, forces.core_force, scale_params.weight_core),
            ]
        else:
            weighted_list = forces.all_forces()

        total_dir = 0.0
        total_weight = 0.0
        weighted_time = 0.0
        weighted_certainty = 0.0
        sum_weights = sum(w for _, _, w in weighted_list)

        for name, force, weight in weighted_list:
            signed = force.signed_magnitude()  # direction × certainty
            total_dir += signed * weight
            total_weight += weight * force.certainty
            weighted_time += force.time_horizon * weight
            weighted_certainty += force.certainty * weight

        # 归一化方向
        if total_weight > 0:
            net_dir = total_dir / total_weight
        else:
            net_dir = 0.0

        net_dir = max(-1.0, min(1.0, net_dir))
        avg_time = weighted_time / sum_weights if sum_weights > 0 else 0.5
        avg_certainty = weighted_certainty / sum_weights if sum_weights > 0 else 0.5

        return Force3D(
            direction=net_dir,
            time_horizon=avg_time,
            certainty=avg_certainty,
        )

    # ============================================================
    # Step 3: 市场质量
    # ============================================================
    def _compute_market_mass(self, volatility: float,
                              scale_params=None) -> float:
        """
        市场质量（惯性）。

        波动率越高 → 质量越小 → 同样合力下加速度越大
        体量越大 → 基础质量越大 → 惯性越大
        """
        mass_base = MARKET_MASS_BASE
        if scale_params:
            mass_base = scale_params.market_mass_base
        return mass_base / (1 + MARKET_MASS_VOLATILITY_FACTOR * volatility)

    # ============================================================
    # Step 6: 趋势方向判定
    # ============================================================
    def _direction_from_velocity(self, velocity: float) -> str:
        """从速度判定趋势方向。
        P1 修复: 降低阈值 0.05→0.02，减少过度 FLAT 输出
        参考 Backtrader 的信号阈值动态调整原则。
        """
        threshold = 0.02  # P1修复: 原0.05过于宽松导致全部FLAT
        if velocity > threshold:
            return DIR_UP
        elif velocity < -threshold:
            return DIR_DOWN
        elif abs(velocity) < threshold * 0.3:
            return DIR_FLAT
        else:
            return DIR_TRANSITIONING

    # ============================================================
    # Step 7: 转折预警
    # ============================================================
    def _check_reversal(self, velocity: float, acceleration: float,
                         prev_velocity: float,
                         scale_params=None) -> Tuple[bool, float]:
        """
        转折预警：加速度与速度反向 = 减速。

        当市场正在一个方向运动，但合力开始反向时，
        速度开始减小，预示趋势可能转折。
        阈值随体量调整：小体量敏感，大体量迟钝。
        """
        if abs(velocity) < VELOCITY_ZERO_THRESHOLD:
            return False, 0.0

        # 减速 = 速度方向与加速度方向相反
        if velocity > 0 and acceleration < 0:
            reversal = abs(acceleration)
        elif velocity < 0 and acceleration > 0:
            reversal = abs(acceleration)
        else:
            reversal = 0.0

        # 体量调整阈值
        threshold = REVERSAL_WARNING_THRESHOLD
        if scale_params:
            threshold = scale_params.reversal_threshold

        warning = reversal > threshold
        return warning, reversal

    # ============================================================
    # Step 8: 置信度
    # ============================================================
    def _compute_confidence(self, net_force: Force3D,
                              forces: MarketForces,
                              trend_strength: float,
                              reversal_warning: bool) -> float:
        """
        置信度计算。

        基于以下因素：
        1. 合力大小 — 合力越大约确定
        2. 四象一致性 — 力场方向越一致越高
        3. 趋势强度 — 速度越大约确定
        4. 转折预警 — 减速时降低置信度
        """
        # 1. 合力大小
        force_mag = abs(net_force.signed_magnitude())

        # 2. 四象一致性
        force_dirs = [f.direction for _, f, _ in forces.all_forces()]
        signs = [1 if d > 0.05 else -1 if d < -0.05 else 0
                 for d in force_dirs]
        non_zero = [s for s in signs if s != 0]
        if len(non_zero) > 1:
            agreement = sum(1 for i in range(len(non_zero) - 1)
                            if non_zero[i] == non_zero[i + 1]) / (len(non_zero) - 1)
        else:
            agreement = 0.5

        # 3. 综合置信度
        # 力的归一化：合力最大约 1.0（四象全同向），放大到合理范围
        force_mag_norm = min(1.0, force_mag * FORCE_MAGNITUDE_NORM_FACTOR)
        # 速度归一化：速度可以累积，趋势一旦形成就有惯性
        velocity_norm = min(1.0, trend_strength * VELOCITY_NORM_FACTOR)
        confidence = (force_mag_norm * CONFIDENCE_WEIGHT_FORCE +
                      agreement * CONFIDENCE_WEIGHT_AGREEMENT +
                      velocity_norm * CONFIDENCE_WEIGHT_VELOCITY)

        # 4. 转折预警惩罚
        if reversal_warning:
            confidence *= 0.75

        return max(0.0, min(1.0, confidence))

    # ============================================================
    # 辅助：重置速度状态
    # ============================================================
    def reset_velocity(self):
        """重置速度历史状态。"""
        self.prev_velocity = 0.0
