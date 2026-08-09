#!/usr/bin/env python3
"""
多空方向控制器 (DirectionGate)
==============================

基于风险-价值二元评估理论：
- 暴涨暴跌占市场20%，震荡占80%，整体做多占多数
- BTC有效跌破日线MA128（连续3日收盘价低于MA128）→ 全系统做空闸门打开
- 价格跌至周线MA200 → 继续做空风险较高，转为做多

三种市场状态：
  LONG_PREFERRED   — 价格在日线MA128上方，只做多（震荡+多头行情）
  SHORT_ALLOWED    — BTC有效跌破MA128后，允许做空（暴跌阶段）
  LONG_ONLY_FORCE  — 跌至周线MA200，强制做多，禁止做空（下跌末端）

状态转移：
  LONG_PREFERRED ──BTC有效跌破MA128──→ SHORT_ALLOWED
  SHORT_ALLOWED  ──BTC涨回MA128上──→ LONG_PREFERRED
  SHORT_ALLOWED  ──跌至周MA200──→ LONG_ONLY_FORCE
  LONG_ONLY_FORCE ──涨回日MA128上──→ LONG_PREFERRED

BTC风向标机制：
  - 当BTC有效跌破日线MA128（连续3日收盘价低于MA128），全系统做空闸门打开
  - 其他币种根据自身位置判断：跌破周MA200则强制做多
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, List, Tuple, Any
import math


class MarketRegime(str, Enum):
    """市场状态"""
    LONG_PREFERRED = "long_preferred"      # 做多优先（价格在日MA128上方）
    SHORT_ALLOWED = "short_allowed"        # 允许做空（BTC有效跌破MA128，在周MA200上方）
    LONG_ONLY_FORCE = "long_only_force"    # 强制做多（跌至周MA200）


class TradeDirection(str, Enum):
    """交易方向许可"""
    LONG_ONLY = "long_only"     # 只允许做多
    SHORT_ONLY = "short_only"   # 只允许做空
    BOTH = "both"               # 多空都允许
    NONE = "none"               # 都不允许（异常状态）


@dataclass
class GateResult:
    """方向控制判断结果"""
    regime: MarketRegime
    allowed_direction: TradeDirection
    price_vs_daily_ma128: str    # "above" / "below" / "unknown"
    price_vs_weekly_ma200: str   # "above" / "below" / "unknown"
    daily_ma128: Optional[float]
    weekly_ma200: Optional[float]
    current_price: float
    reason: str
    # Phase 1 新增：力学诊断（允许为None，表示用的是传统逻辑）
    mechanistic_diag: Optional[Dict[str, Any]] = None

    @property
    def short_enabled(self) -> bool:
        """是否允许做空"""
        return self.allowed_direction in (TradeDirection.SHORT_ONLY, TradeDirection.BOTH)

    @property
    def long_enabled(self) -> bool:
        """是否允许做多"""
        return self.allowed_direction in (TradeDirection.LONG_ONLY, TradeDirection.BOTH)

    def to_dict(self) -> Dict:
        d = {
            "regime": self.regime.value,
            "allowed_direction": self.allowed_direction.value,
            "short_enabled": self.short_enabled,
            "long_enabled": self.long_enabled,
            "price_vs_daily_ma128": self.price_vs_daily_ma128,
            "price_vs_weekly_ma200": self.price_vs_weekly_ma200,
            "daily_ma128": self.daily_ma128,
            "weekly_ma200": self.weekly_ma200,
            "current_price": self.current_price,
            "reason": self.reason,
        }
        if self.mechanistic_diag is not None:
            d["mechanistic_diag"] = self.mechanistic_diag
        return d


class DirectionGate:
    """
    多空方向控制器
    ==============

    核心逻辑：
    1. BTC有效跌破日线MA128（连续3日收盘价低于MA128）→ 全系统做空闸门打开
    2. 价格跌至周线MA200 → 强制做多，禁止做空

    用法:
        gate = DirectionGate(allow_short=True)
        result = gate.evaluate(
            current_price=65000,
            daily_ma128=60000,
            weekly_ma200=55000,
            recent_daily_closes=[59000, 58500, 58000],  # 最近3日收盘价
            btc_short_enabled=True,                      # BTC风向标
        )
        if result.short_enabled:
            # 可以做空
    """

    def __init__(self, allow_short: bool = True, buffer_pct: float = 0.01,
                 use_mechanistic: bool = False):
        """
        Args:
            allow_short: 全局做空开关。False 时永远只做多
            buffer_pct: MA附近的缓冲带（1%），避免临界点频繁切换（传统逻辑）
            use_mechanistic: Phase 1 开关：True 使用力学化力场模型，False 用传统above/below逻辑
        """
        self.allow_short = allow_short
        self.buffer_pct = buffer_pct
        self.use_mechanistic = use_mechanistic

    def evaluate(
        self,
        current_price: float,
        daily_ma128: Optional[float] = None,
        weekly_ma200: Optional[float] = None,
        recent_daily_closes: Optional[List[float]] = None,
        btc_short_enabled: bool = False,
        velocity_integrator: Optional["VelocityIntegrator"] = None,
    ) -> GateResult:
        """
        评估当前市场状态和允许的交易方向

        传统模式(use_mechanistic=False): 收盘价确认+above/below二值判定
        力学化模式(use_mechanistic=True): Phase 1 — 双均线弹簧力场 + 速度积分

        核心判断使用收盘价确认，避免实时价格波动导致频繁切换。
        有效跌破定义：连续3日收盘价低于日线MA128

        Args:
            current_price: 当前实时价格
            daily_ma128: 日线MA128（替代原MA200，更灵敏）
            weekly_ma200: 周线MA200
            recent_daily_closes: 最近N日收盘价列表（用于判断有效跌破）
            btc_short_enabled: BTC风向标，True表示BTC已有效跌破MA128，全系统做空闸门打开
            velocity_integrator: Phase 1 速度积分器（跨轮询持久化速度）；None时用F_net作为速度代理
        """
        # Phase 1 力学化模式
        if self.use_mechanistic and daily_ma128 is not None and weekly_ma200 is not None:
            return self._evaluate_mechanistic(
                current_price=current_price,
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                recent_daily_closes=recent_daily_closes or [],
                btc_short_enabled=btc_short_enabled,
                velocity_integrator=velocity_integrator,
            )

        if not self.allow_short:
            return GateResult(
                regime=MarketRegime.LONG_PREFERRED,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128=self._pos(current_price, daily_ma128),
                price_vs_weekly_ma200=self._pos(current_price, weekly_ma200),
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason="全局做空开关关闭(V15_ALLOW_SHORT=false), 只做多",
            )

        if daily_ma128 is None or weekly_ma200 is None:
            return GateResult(
                regime=MarketRegime.LONG_PREFERRED,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128="unknown",
                price_vs_weekly_ma200="unknown",
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason="MA数据不足, 保守只做多",
            )

        if recent_daily_closes is None:
            recent_daily_closes = []

        daily_buffer = daily_ma128 * self.buffer_pct
        weekly_buffer = weekly_ma200 * self.buffer_pct

        price_vs_daily = self._pos(current_price, daily_ma128)
        price_vs_weekly = self._pos(current_price, weekly_ma200)

        # ── 有效跌破判断：连续3日收盘价低于MA128 ──
        has_valid_breakdown = self._check_valid_breakdown(recent_daily_closes, daily_ma128)

        # ── 核心状态判断 ──

        # 情况1: 跌至周线MA200附近 → 强制做多，禁止做空
        # 理论：跌到周线MA200说明下跌较多，继续做空风险高，转为做多
        weekly_ref = recent_daily_closes[-1] if recent_daily_closes else current_price
        if weekly_ref <= weekly_ma200 + weekly_buffer:
            return GateResult(
                regime=MarketRegime.LONG_ONLY_FORCE,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128=price_vs_daily,
                price_vs_weekly_ma200=price_vs_weekly,
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason=f"价格({weekly_ref:.2f})跌至周线MA200({weekly_ma200:.2f})附近, 做空风险高, 强制做多",
            )

        # 情况2: 全系统做空闸门未打开 → 只做多
        # BTC风向标关闭（未有效跌破MA128），整个系统不允许做空
        if not btc_short_enabled:
            return GateResult(
                regime=MarketRegime.LONG_PREFERRED,
                allowed_direction=TradeDirection.LONG_ONLY,
                price_vs_daily_ma128=price_vs_daily,
                price_vs_weekly_ma200=price_vs_weekly,
                daily_ma128=daily_ma128,
                weekly_ma200=weekly_ma200,
                current_price=current_price,
                reason=f"BTC做空闸门未打开(btc_short_enabled=false), 只做多",
            )

        # 情况3: BTC做空闸门打开 + 在周MA200上方 → 允许做空
        # 理论：BTC有效跌破MA128，全系统做空闸门打开；当前币种在周MA200上方，做空价值较高
        return GateResult(
            regime=MarketRegime.SHORT_ALLOWED,
            allowed_direction=TradeDirection.BOTH,
            price_vs_daily_ma128=price_vs_daily,
            price_vs_weekly_ma200=price_vs_weekly,
            daily_ma128=daily_ma128,
            weekly_ma200=weekly_ma200,
            current_price=current_price,
            reason=f"BTC做空闸门打开(btc_short_enabled=true), 价格在周线MA200({weekly_ma200:.2f})上方, 允许做空",
        )

    def _check_valid_breakdown(self, recent_daily_closes: List[float], daily_ma128: float) -> bool:
        """
        检查是否有效跌破MA128

        有效跌破定义：连续3日收盘价低于MA128

        Args:
            recent_daily_closes: 最近N日收盘价列表
            daily_ma128: 日线MA128

        Returns:
            True: 有效跌破；False: 未有效跌破
        """
        if len(recent_daily_closes) < 3:
            return False
        last_3_closes = recent_daily_closes[-3:]
        return all(close <= daily_ma128 for close in last_3_closes)

    @staticmethod
    def _pos(price: float, ma: Optional[float]) -> str:
        if ma is None:
            return "unknown"
        return "above" if price > ma else "below"


# ── 模块级便捷函数 ──────────────────────────────────────────────

_gate_instance: Optional[DirectionGate] = None


def get_gate(allow_short: bool = True) -> DirectionGate:
    """获取全局 DirectionGate 单例"""
    global _gate_instance
    if _gate_instance is None:
        _gate_instance = DirectionGate(allow_short=allow_short)
    return _gate_instance


def reset_gate():
    """重置单例（测试用）"""
    global _gate_instance
    _gate_instance = None


def evaluate_direction(
    current_price: float,
    daily_ma128: Optional[float] = None,
    weekly_ma200: Optional[float] = None,
    recent_daily_closes: Optional[List[float]] = None,
    btc_short_enabled: bool = False,
    allow_short: bool = True,
) -> GateResult:
    """便捷函数：评估多空方向"""
    gate = DirectionGate(allow_short=allow_short)
    return gate.evaluate(
        current_price=current_price,
        daily_ma128=daily_ma128,
        weekly_ma200=weekly_ma200,
        recent_daily_closes=recent_daily_closes,
        btc_short_enabled=btc_short_enabled,
    )


# ── 向后兼容函数 ──────────────────────────────────────────────

def evaluate_direction_v1(
    current_price: float,
    daily_ma200: Optional[float] = None,
    weekly_ma200: Optional[float] = None,
    last_daily_close: Optional[float] = None,
    last_weekly_close: Optional[float] = None,
    allow_short: bool = True,
) -> GateResult:
    """
    向后兼容版本：使用原MA200参数
    注意：此函数会被新逻辑替代，保留仅用于兼容旧代码
    """
    gate = DirectionGate(allow_short=allow_short)
    recent_closes = []
    if last_daily_close is not None:
        recent_closes.append(last_daily_close)
    return gate.evaluate(
        current_price=current_price,
        daily_ma128=daily_ma200,
        weekly_ma200=weekly_ma200,
        recent_daily_closes=recent_closes,
        btc_short_enabled=True if allow_short else False,
    )


# ===================================================================
# Phase 1: 力学化 DirectionGate —— 双均线弹簧力场 + 速度积分
#
# 理论借鉴：BCRM1.0 ForceEngine 弹簧模型 (force_engine.py::_extract_space_force)
#           BCRM1.0 BaguaEngine 势场模型 + 距离权重
#           三屏 least_resistance 支撑阻力距离能量
# ===================================================================

@dataclass
class MAForceFieldResult:
    """双均线力场计算结果"""
    F_daily: float          # MA128 弹簧力（正=向上/支撑，负=向下/阻力）
    F_weekly: float         # MA200 弹簧力
    w_daily: float          # MA128 距离权重
    w_weekly: float         # MA200 距离权重
    F_net: float            # 加权合力 F_net = F_d*w_d + F_w*w_w
    dist_to_daily_pct: float  # 价格距MA128的百分比(正=上方，负=下方)
    dist_to_weekly_pct: float # 价格距MA200的百分比(正=上方，负=下方)
    dominant_ma: str        # 主导均线（距离更近、权重更大的一方）"daily_ma128" | "weekly_ma200"
    dominant_role: str      # 主导角色："resistance"(上方阻力) | "support"(下方支撑) | "aligned"(两线同向)


def _ma_spring_force(price: float, ma: float, spring_k: float = 2.0) -> float:
    """
    均线弹簧力（BCRM1.0 空间力 F = -k × (x - x0) 迁移）

    将 MA 视为均衡位置 x0，价格偏离 MA 产生回复力。

    Args:
        price: 当前价格
        ma: 均线值
        spring_k: 弹簧系数 k。默认2.0（与BCRM1.0 SPACE_SPRING_K一致）

    Returns:
        F: 弹簧力
           F < 0 表示价格在MA上方，被MA"向下拉回"
           F > 0 表示价格在MA下方，被MA"向上拉回"
    """
    if ma == 0:
        return 0.0
    deviation = (price - ma) / ma       # 归一化偏离 = (price - x0) / x0
    return -spring_k * deviation         # F = -k × deviation


def _distance_weight(dist_pct: float) -> float:
    """
    均线距离权重（反比距离，借鉴 BCRM1.0 势场高斯模型简化版）

    距离越近 → 权重越大（均线吸引力越强）
    距离越远 → 权重越小（均线吸引力越弱）

    公式: w = 1 / (1 + |dist_pct|)
    - dist_pct=0%  → w=1.0 (完全重合)
    - dist_pct=1%  → w≈0.99
    - dist_pct=10% → w≈0.91
    - dist_pct=50% → w≈0.67
    - dist_pct→∞   → w→0

    Args:
        dist_pct: 价格与均线的距离百分比（绝对值，正数）

    Returns:
        w: (0, 1]
    """
    return 1.0 / (1.0 + max(0.0, abs(dist_pct)))


def _compute_ma_force_field(
    price: float,
    daily_ma128: float,
    weekly_ma200: float,
    spring_k: float = 2.0,
) -> MAForceFieldResult:
    """
    双均线力场合力计算（DirectionGate Phase 1 核心）

    处理：
    1. 对每条均线计算弹簧力 F = -k × (price - MA) / MA
    2. 计算价格到每条均线的百分比距离
    3. 距离权重 w = 1/(1+|dist%|)，近的权重大
    4. 加权合力 F_net = F_128 × w_128 + F_200 × w_200
    5. 确定主导均线（权重更大的一方）及其角色（支撑/阻力）

    Args:
        price: 当前价格
        daily_ma128: 日线MA128
        weekly_ma200: 周线MA200
        spring_k: 弹簧系数，默认2.0

    Returns:
        MAForceFieldResult
    """
    # 距离百分比（正=价格在MA上方，负=价格在MA下方）
    dist_daily = (price - daily_ma128) / daily_ma128 * 100 if daily_ma128 else 0
    dist_weekly = (price - weekly_ma200) / weekly_ma200 * 100 if weekly_ma200 else 0

    # 弹簧力
    F_d = _ma_spring_force(price, daily_ma128, spring_k)
    F_w = _ma_spring_force(price, weekly_ma200, spring_k)

    # 距离权重（用绝对值，距离近则权重大）
    w_d = _distance_weight(abs(dist_daily))
    w_w = _distance_weight(abs(dist_weekly))

    # 加权合力
    F_net = F_d * w_d + F_w * w_w

    # 主导均线（比较权重大小）
    if w_d >= w_w:
        dominant = "daily_ma128"
        # 价格在MA下方 → MA在上方 → 阻力；价格在MA上方 → MA在下方 → 支撑
        role = "resistance" if dist_daily < 0 else "support"
    else:
        dominant = "weekly_ma200"
        role = "resistance" if dist_weekly < 0 else "support"

    # 两线同向判定
    if F_d * F_w > 0:  # 同号
        dominant = "aligned"
        role = "support" if F_d > 0 else "resistance"

    return MAForceFieldResult(
        F_daily=F_d,
        F_weekly=F_w,
        w_daily=w_d,
        w_weekly=w_w,
        F_net=F_net,
        dist_to_daily_pct=dist_daily,
        dist_to_weekly_pct=dist_weekly,
        dominant_ma=dominant,
        dominant_role=role,
    )


@dataclass
class VelocityIntegrator:
    """
    速度积分器（简化 Verlet + 摩擦衰减，借鉴 BCRM1.0::VelocityVerletLangevin）

    a = F_net / m
    v_new = v_old × decay + a × Δt

    Phase 1 简化：
      - 暂不引入 Langevin 热噪声（Phase 2 加）
      - Δt = 1（每步代表一次轮询）
      - threshold = 0.02（默认，BCRM1.0 velocity 阈值）

    用法:
        vi = VelocityIntegrator.load_state(saved)   # 从state恢复
        v = vi.step(acceleration=F_net / mass)      # 每轮调一次
        save_state_dict = vi.save_state()           # 持久化
    """
    decay: float = 0.85              # 摩擦衰减系数(每步)，0.85≈保留85%
    market_mass: float = 1.0         # 市场质量 m，越大越难转向
    threshold: float = 0.02          # 速度阈值，映射3状态
    velocity: float = 0.0            # 当前速度 v
    step_count: int = 0              # 累计步数

    def step(self, acceleration: float) -> float:
        """
        执行一步速度积分。

        Args:
            acceleration: 加速度 a = F_net / m。外部计算好传入。

        Returns:
            积分后的新速度
        """
        # v_new = v_old × decay + a × Δt
        self.velocity = self.velocity * self.decay + acceleration * 1.0
        self.step_count += 1
        return self.velocity

    def save_state(self) -> Dict[str, Any]:
        return {
            "decay": self.decay,
            "market_mass": self.market_mass,
            "threshold": self.threshold,
            "velocity": self.velocity,
            "step_count": self.step_count,
        }

    @classmethod
    def load_state(cls, state: Dict[str, Any]) -> "VelocityIntegrator":
        return cls(
            decay=float(state.get("decay", 0.85)),
            market_mass=float(state.get("market_mass", 1.0)),
            threshold=float(state.get("threshold", 0.02)),
            velocity=float(state.get("velocity", 0.0)),
            step_count=int(state.get("step_count", 0)),
        )


def _velocity_to_regime(velocity: float, threshold: float = 0.02) -> MarketRegime:
    """
    连续速度场 → 离散 MarketRegime 映射（Phase 1 向后兼容）

    规则:
      v > +threshold  → LONG_PREFERRED  (速度显著向上 → 做多)
      v < -threshold  → SHORT_ALLOWED   (速度显著向下 → 允许做空)
      |v| ≤ threshold → LONG_ONLY_FORCE (均线附近支撑区 → 保守做多)
                        * NEAR_SUPPORT 是新增概念，但为了向后兼容映射到 LONG_ONLY_FORCE *
                        * 语义: 均线附近筑底，保守只做多，与原有 LONG_ONLY_FORCE 一致 *
    """
    if velocity > threshold:
        return MarketRegime.LONG_PREFERRED
    elif velocity < -threshold:
        return MarketRegime.SHORT_ALLOWED
    else:
        return MarketRegime.LONG_ONLY_FORCE


# ===================================================================
# DirectionGate 力学化 evaluate
# ===================================================================
def _evaluate_mechanistic_impl(
    current_price: float,
    daily_ma128: float,
    weekly_ma200: float,
    recent_daily_closes: List[float],
    btc_short_enabled: bool,
    allow_short: bool,
    velocity_integrator: Optional[VelocityIntegrator],
) -> GateResult:
    """
    力学化 DirectionGate 评估（Phase 1 实现）

    判定流程:
    1. 力场计算: F_daily, F_weekly, F_net
    2. 加速度: a = F_net / market_mass (mass 默认1.0，Phase 2 体量自适应)
    3. 速度积分: v = vi.step(a)，若无vi则使用 proxy_v = F_net（瞬时近似）
    4. 映射: v → regime
    5. 叠加 BTC 闸门 + 全局开关
    """
    price_vs_daily = "above" if current_price > daily_ma128 else "below"
    price_vs_weekly = "above" if current_price > weekly_ma200 else "below"

    # 全局开关
    if not allow_short:
        return GateResult(
            regime=MarketRegime.LONG_PREFERRED,
            allowed_direction=TradeDirection.LONG_ONLY,
            price_vs_daily_ma128=price_vs_daily,
            price_vs_weekly_ma200=price_vs_weekly,
            daily_ma128=daily_ma128,
            weekly_ma200=weekly_ma200,
            current_price=current_price,
            reason="全局做空开关关闭(mechanistic模式), 只做多",
            mechanistic_diag=None,
        )

    ff = _compute_ma_force_field(current_price, daily_ma128, weekly_ma200)

    # 加速度 & 速度
    market_mass = 1.0
    a = ff.F_net / market_mass if velocity_integrator else 0
    if velocity_integrator is not None:
        v = velocity_integrator.step(a)
        v_source = "integrated"
    else:
        # 无积分器时，用 F_net 作为速度代理（瞬时估计）
        v = ff.F_net
        v_source = "F_net_proxy"

    # 阈值：默认 0.02，如果使用 proxy 适度放宽
    threshold = velocity_integrator.threshold if velocity_integrator else 0.02

    # 额外保护：若价格已经跌破 weekly_ma200（距离非常近 + F_weekly 反向拉上），
    # 直接强制 LONG_ONLY_FORCE（对应原来的跌至周线支撑逻辑）
    weekly_buffer = weekly_ma200 * 0.01
    weekly_ref = recent_daily_closes[-1] if recent_daily_closes else current_price
    if weekly_ref <= weekly_ma200 + weekly_buffer:
        regime = MarketRegime.LONG_ONLY_FORCE
        direction = TradeDirection.LONG_ONLY
        reason = f"mechanistic: 价格({weekly_ref:.2f})跌至周MA200({weekly_ma200:.2f})附近, 强制做多"
    else:
        # BTC 闸门：如果BTC风向标关闭（btc_short_enabled=False），
        # 即使力学化判定 v<0 也不允许做空（映射为 LONG_PREFERRED）
        regime_from_v = _velocity_to_regime(v, threshold)
        if regime_from_v == MarketRegime.SHORT_ALLOWED and not btc_short_enabled:
            regime = MarketRegime.LONG_PREFERRED
            direction = TradeDirection.LONG_ONLY
            reason = (
                f"mechanistic: v={v:+.4f} 指示SHORT但BTC做空闸门未打开(btc_short_enabled=false), "
                f"保守只做多 (dominant={ff.dominant_ma}/{ff.dominant_role}, "
                f"F_net={ff.F_net:+.4f})"
            )
        else:
            regime = regime_from_v
            if regime == MarketRegime.SHORT_ALLOWED:
                direction = TradeDirection.BOTH
                reason = (
                    f"mechanistic: v={v:+.4f}<-(向下), BTC做空闸门打开, 允许做空; "
                    f"dominant={ff.dominant_ma}/{ff.dominant_role}, F_net={ff.F_net:+.4f}"
                )
            elif regime == MarketRegime.LONG_PREFERRED:
                direction = TradeDirection.LONG_ONLY if not allow_short else TradeDirection.LONG_ONLY
                # 若允许做空但 v>0（向上）则依然只做多（趋势向上时做空无优势）
                reason = (
                    f"mechanistic: v={v:+.4f}>+(向上), 只做多; "
                    f"dominant={ff.dominant_ma}/{ff.dominant_role}, F_net={ff.F_net:+.4f}"
                )
            else:  # LONG_ONLY_FORCE (|v|小 → 支撑区)
                direction = TradeDirection.LONG_ONLY
                reason = (
                    f"mechanistic: |v|={abs(v):.4f}≤阈值{threshold} → 支撑区筑底, 保守只做多; "
                    f"dominant={ff.dominant_ma}/{ff.dominant_role}, F_net={ff.F_net:+.4f}"
                )

    # 力学诊断字段
    diag = {
        "F_daily": round(ff.F_daily, 6),
        "F_weekly": round(ff.F_weekly, 6),
        "w_daily": round(ff.w_daily, 4),
        "w_weekly": round(ff.w_weekly, 4),
        "F_net": round(ff.F_net, 6),
        "dist_to_daily_pct": round(ff.dist_to_daily_pct, 3),
        "dist_to_weekly_pct": round(ff.dist_to_weekly_pct, 3),
        "dominant_ma": ff.dominant_ma,
        "dominant_role": ff.dominant_role,
        "acceleration": round(a, 6),
        "velocity": round(v, 6),
        "velocity_source": v_source,
        "threshold": threshold,
    }

    return GateResult(
        regime=regime,
        allowed_direction=direction,
        price_vs_daily_ma128=price_vs_daily,
        price_vs_weekly_ma200=price_vs_weekly,
        daily_ma128=daily_ma128,
        weekly_ma200=weekly_ma200,
        current_price=current_price,
        reason=reason,
        mechanistic_diag=diag,
    )


# 挂载到 DirectionGate（作为实例方法）
def _evaluate_mechanistic(
    self: DirectionGate,
    current_price: float,
    daily_ma128: float,
    weekly_ma200: float,
    recent_daily_closes: List[float],
    btc_short_enabled: bool,
    velocity_integrator: Optional[VelocityIntegrator],
) -> GateResult:
    return _evaluate_mechanistic_impl(
        current_price=current_price,
        daily_ma128=daily_ma128,
        weekly_ma200=weekly_ma200,
        recent_daily_closes=recent_daily_closes,
        btc_short_enabled=btc_short_enabled,
        allow_short=self.allow_short,
        velocity_integrator=velocity_integrator,
    )


# 绑定为 DirectionGate 的方法
DirectionGate._evaluate_mechanistic = _evaluate_mechanistic


if __name__ == "__main__":
    print("=== DirectionGate 自检 (MA128 + BTC风向标) ===")

    gate = DirectionGate(allow_short=True)

    # 场景1: BTC未有效跌破MA128 → 做空闸门关闭，只做多
    r = gate.evaluate(
        current_price=65000,
        daily_ma128=60000,
        weekly_ma200=55000,
        recent_daily_closes=[62000, 61500, 61000],
        btc_short_enabled=False,
    )
    print(f"\n场景1 (BTC做空闸门关闭): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景2: BTC有效跌破MA128（连续3日收盘价低于MA128）→ 做空闸门打开
    r = gate.evaluate(
        current_price=58000,
        daily_ma128=60000,
        weekly_ma200=55000,
        recent_daily_closes=[59000, 58500, 58000],
        btc_short_enabled=True,
    )
    print(f"\n场景2 (BTC有效跌破MA128, 做空闸门打开): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景3: BTC做空闸门打开但跌至周MA200 → 强制做多
    r = gate.evaluate(
        current_price=54000,
        daily_ma128=60000,
        weekly_ma200=55000,
        recent_daily_closes=[54500, 54000, 53500],
        btc_short_enabled=True,
    )
    print(f"\n场景3 (跌至周MA200, 强制做多): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景4: 全局开关关闭
    gate_off = DirectionGate(allow_short=False)
    r = gate_off.evaluate(
        current_price=58000,
        daily_ma128=60000,
        weekly_ma200=55000,
        btc_short_enabled=True,
    )
    print(f"\n场景4 (全局做空关闭): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景5: 非BTC币种，BTC做空闸门打开
    r = gate.evaluate(
        current_price=4200,
        daily_ma128=4500,
        weekly_ma200=3800,
        btc_short_enabled=True,
    )
    print(f"\n场景5 (ETH,BTC做空闸门打开): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")

    # 场景6: 非BTC币种，BTC做空闸门打开但跌至周MA200
    r = gate.evaluate(
        current_price=3700,
        daily_ma128=4500,
        weekly_ma200=3800,
        btc_short_enabled=True,
    )
    print(f"\n场景6 (ETH跌至周MA200, 强制做多): {r.regime.value}, 做多={r.long_enabled}, 做空={r.short_enabled}")
    print(f"  {r.reason}")
