"""
体量引擎 — 小大之辩，参数自适应核心。

小大之异，时间长短，空间振幅，表里强度，互为因果。
体量决定参数，参数决定力场，力场决定方向。

体量系数 scale ∈ [0, 1]：
    0.0 = 微盘（高波动、短时间、小空间、表强里弱）
    0.5 = 中盘
    1.0 = 超大盘（低波动、长时间、大空间、里强表弱）

体量×四象 = 参数空间 → 八八六十四卦
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Tuple
import math

from ._constants import (
    FORCE_WEIGHT_CORE, FORCE_WEIGHT_SURFACE,
    FORCE_WEIGHT_TIME, FORCE_WEIGHT_SPACE,
    SCALE_VOLATILITY_BASE, SCALE_VOLATILITY_RANGE,
    SCALE_TIME_SHORT, SCALE_TIME_MID, SCALE_TIME_LONG,
    SCALE_SPACE_SENSITIVITY_SMALL, SCALE_SPACE_SENSITIVITY_LARGE,
    SCALE_SURFACE_WEIGHT_SMALL, SCALE_SURFACE_WEIGHT_LARGE,
    SCALE_CORE_WEIGHT_SMALL, SCALE_CORE_WEIGHT_LARGE,
    SCALE_MASS_SMALL, SCALE_MASS_LARGE,
    SCALE_DECAY_SMALL, SCALE_DECAY_LARGE,
    SCALE_CONFIDENCE_THRESHOLD_SMALL, SCALE_CONFIDENCE_THRESHOLD_LARGE,
    SCALE_REVERSAL_THRESHOLD_SMALL, SCALE_REVERSAL_THRESHOLD_LARGE,
    MARKET_MASS_BASE,
    VELOCITY_DECAY,
    REVERSAL_WARNING_THRESHOLD,
    GUA_QIAN, GUA_KUN, GUA_ZHEN, GUA_XUN,
    GUA_KAN, GUA_LI, GUA_GEN, GUA_DUI,
    GUA_NAMES_CN,
)


@dataclass
class ScaleParams:
    """
    体量自适应参数集。

    每个参数随体量系数连续变化，通过线性插值或非线性映射。
    """
    scale: float = 0.5  # 体量系数 [0, 1]

    # 四象权重（随体量变化）
    weight_time: float = FORCE_WEIGHT_TIME
    weight_space: float = FORCE_WEIGHT_SPACE
    weight_surface: float = FORCE_WEIGHT_SURFACE
    weight_core: float = FORCE_WEIGHT_CORE

    # 力学参数
    market_mass_base: float = MARKET_MASS_BASE
    velocity_decay: float = VELOCITY_DECAY
    confidence_threshold: float = 0.36
    reversal_threshold: float = REVERSAL_WARNING_THRESHOLD

    # 时空参数
    time_horizon_base: float = SCALE_TIME_MID
    space_sensitivity: float = 2.0  # 空间力弹簧系数
    volatility_adjustment: float = 0.0  # 波动率调整量

    # 体量对应的八卦
    scale_gua: str = GUA_KAN  # 中盘=坎水

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scale": round(self.scale, 4),
            "weight_time": round(self.weight_time, 4),
            "weight_space": round(self.weight_space, 4),
            "weight_surface": round(self.weight_surface, 4),
            "weight_core": round(self.weight_core, 4),
            "market_mass_base": round(self.market_mass_base, 4),
            "velocity_decay": round(self.velocity_decay, 4),
            "confidence_threshold": round(self.confidence_threshold, 4),
            "reversal_threshold": round(self.reversal_threshold, 4),
            "time_horizon_base": round(self.time_horizon_base, 4),
            "space_sensitivity": round(self.space_sensitivity, 4),
            "volatility_adjustment": round(self.volatility_adjustment, 4),
            "scale_gua": self.scale_gua,
        }


def compute_scale(market_cap: float = None,
                  volume: float = None,
                  float_shares: float = None,
                  explicit: float = None) -> float:
    """
    计算连续体量系数 scale ∈ [0, 1]。

    优先级：explicit > market_cap > volume > 默认0.5

    市值映射（对数缩放）：
        <50亿     → 0.0-0.2（微盘）
        50-200亿  → 0.2-0.4（小盘）
        200-1000亿 → 0.4-0.6（中盘）
        1000-5000亿 → 0.6-0.8（大盘）
        >5000亿   → 0.8-1.0（超大盘）
    """
    if explicit is not None:
        return max(0.0, min(1.0, explicit))

    if market_cap is not None and market_cap > 0:
        # 对数缩放：10亿→0.1, 100亿→0.3, 1000亿→0.5, 10000亿→0.7, 100000亿→0.9
        log_cap = math.log10(market_cap / 1e8)  # 以亿为单位
        # 映射到 [0, 1]
        scale = (log_cap + 1) / 10  # 10亿→0.0, 1000亿→0.4, 100000亿→0.8
        return max(0.0, min(1.0, scale))

    if volume is not None and volume > 0:
        # 成交量映射
        log_vol = math.log10(volume)
        scale = (log_vol - 6) / 8  # 100万→0.0, 1亿→0.25, 100亿→0.5
        return max(0.0, min(1.0, scale))

    return 0.5  # 默认中盘


def scale_to_params(scale: float) -> ScaleParams:
    """
    体量系数 → 全套参数映射。

    核心映射逻辑：
    1. 四象权重：小体量表强里弱 → 大体量里强表弱
    2. 市场质量：小体量质量小 → 大体量质量大
    3. 速度衰减：小体量衰减快 → 大体量衰减慢
    4. 置信度阈值：小体量门槛低 → 大体量门槛高
    5. 转折预警：小体量敏感 → 大体量迟钝
    6. 时间尺度：小体量短期 → 大体量长期
    7. 空间敏感度：小体量高敏感 → 大体量低敏感
    8. 波动率调整：小体量+波动 → 大体量-波动
    """
    s = max(0.0, min(1.0, scale))

    # --- 四象权重插值 ---
    # 小体量：表>时>空>里 → 大体量：里>时>表>空
    w_surface = _lerp(SCALE_SURFACE_WEIGHT_SMALL, SCALE_SURFACE_WEIGHT_LARGE, s)
    w_core = _lerp(SCALE_CORE_WEIGHT_SMALL, SCALE_CORE_WEIGHT_LARGE, s)
    # 时和空保持相对稳定，但微调
    w_time = FORCE_WEIGHT_TIME + (s - 0.5) * 0.05  # 大体量时间略增
    w_space = FORCE_WEIGHT_SPACE - (s - 0.5) * 0.03  # 大体量空间略减

    # 归一化（确保权重和为1）
    total = w_time + w_space + w_surface + w_core
    w_time /= total
    w_space /= total
    w_surface /= total
    w_core /= total

    # --- 力学参数插值 ---
    mass_base = _lerp(SCALE_MASS_SMALL, SCALE_MASS_LARGE, s)
    decay = _lerp(SCALE_DECAY_SMALL, SCALE_DECAY_LARGE, s)
    conf_threshold = _lerp(SCALE_CONFIDENCE_THRESHOLD_SMALL,
                            SCALE_CONFIDENCE_THRESHOLD_LARGE, s)
    reversal_thresh = _lerp(SCALE_REVERSAL_THRESHOLD_SMALL,
                             SCALE_REVERSAL_THRESHOLD_LARGE, s)

    # --- 时空参数 ---
    time_horizon = _lerp(SCALE_TIME_SHORT, SCALE_TIME_LONG, s)
    space_sensitivity = _lerp(SCALE_SPACE_SENSITIVITY_SMALL,
                               SCALE_SPACE_SENSITIVITY_LARGE, s)
    # 波动率调整：小体量+0.2，大体量-0.2
    vol_adj = (0.5 - s) * SCALE_VOLATILITY_RANGE

    # --- 体量→八卦映射 ---
    scale_gua = scale_to_gua(s)

    return ScaleParams(
        scale=s,
        weight_time=w_time,
        weight_space=w_space,
        weight_surface=w_surface,
        weight_core=w_core,
        market_mass_base=mass_base,
        velocity_decay=decay,
        confidence_threshold=conf_threshold,
        reversal_threshold=reversal_thresh,
        time_horizon_base=time_horizon,
        space_sensitivity=space_sensitivity,
        volatility_adjustment=vol_adj,
        scale_gua=scale_gua,
    )


def scale_to_gua(scale: float) -> str:
    """
    体量系数 → 八卦映射。

    八卦代表不同体量特征：
        乾☰（天/大）  → 超大盘：大而强
        兑☱（泽/悦）  → 大盘：大而活跃
        离☲（火/明）  → 中大盘：明亮活跃
        震☳（雷/动）  → 中盘：震动频繁
        巽☴（风/入）  → 中小盘：渗透快
        坎☵（水/险）  → 小盘：风险高
        艮☶（山/止）  → 微盘偏大：静止少动
        坤☷（地/厚）  → 微盘：厚而小
    """
    s = max(0.0, min(1.0, scale))

    if s >= 0.875:
        return GUA_QIAN   # 超大盘
    elif s >= 0.75:
        return GUA_DUI    # 大盘偏大
    elif s >= 0.625:
        return GUA_LI     # 中大盘
    elif s >= 0.5:
        return GUA_ZHEN   # 中盘
    elif s >= 0.375:
        return GUA_XUN    # 中小盘
    elif s >= 0.25:
        return GUA_KAN    # 小盘
    elif s >= 0.125:
        return GUA_GEN    # 微盘偏大
    else:
        return GUA_KUN    # 微盘


def gua_to_scale_params(gua: str) -> ScaleParams:
    """
    八卦 → 体量参数（反向映射）。

    用于从卦象反推参数，实现"卦象即参数"。
    """
    gua_scale_map = {
        GUA_QIAN: 0.95,  # 超大盘
        GUA_DUI: 0.80,   # 大盘
        GUA_LI: 0.70,    # 中大盘
        GUA_ZHEN: 0.55,  # 中盘
        GUA_XUN: 0.40,   # 中小盘
        GUA_KAN: 0.30,   # 小盘
        GUA_GEN: 0.15,   # 微盘偏大
        GUA_KUN: 0.05,   # 微盘
    }
    s = gua_scale_map.get(gua, 0.5)
    return scale_to_params(s)


def _lerp(a: float, b: float, t: float) -> float:
    """线性插值。"""
    return a + (b - a) * t


def _smoothstep(t: float) -> float:
    """平滑插值（S曲线），避免线性插值的突变。"""
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def smooth_scale_to_params(scale: float) -> ScaleParams:
    """
    平滑版参数映射（使用S曲线而非线性插值）。

    在体量切换边界处更平滑，避免参数突变。
    """
    s = _smoothstep(scale)
    return scale_to_params(s)


# ============================================================
# 体量×四象 = 六十四卦参数空间
# ============================================================

def compute_hexagram_params(scale: float,
                              force_directions: Dict[str, float]) -> Dict[str, Any]:
    """
    体量×四象方向 → 六十四卦参数组合。

    这是算法的核心：通过四象八卦计算合理参数，
    推导力的方向、变化阈值、变化时机。

    Args:
        scale: 体量系数 [0, 1]
        force_directions: 四象力方向 {
            "time": float, "space": float,
            "surface": float, "core": float
        }

    Returns:
        参数组合，包含力的方向、变化阈值、时机等
    """
    params = scale_to_params(scale)

    # 体量卦（外因）
    scale_gua = params.scale_gua

    # 四象方向 → 内卦（里+表）和外卦（时+空）
    # 内卦：里（core）+ 表（surface）
    inner_yao1 = 1 if force_directions.get("core", 0) > 0 else 0
    inner_yao2 = 1 if force_directions.get("surface", 0) > 0 else 0
    inner_yao3 = 1 if (force_directions.get("core", 0) *
                       force_directions.get("surface", 0)) > 0 else 0

    # 外卦：时（time）+ 空（space）
    outer_yao1 = 1 if force_directions.get("time", 0) > 0 else 0
    outer_yao2 = 1 if force_directions.get("space", 0) > 0 else 0
    outer_yao3 = 1 if (force_directions.get("time", 0) *
                       force_directions.get("space", 0)) > 0 else 0

    # 计算变化阈值（体量调整后）
    change_threshold = params.confidence_threshold
    time_window = _lerp(3, 15, scale)  # 小体量3bar，大体量15bar
    space_range = _lerp(0.02, 0.08, scale)  # 小体量2%，大体量8%

    # 变化时机（加速度触发条件）
    acceleration_trigger = params.reversal_threshold

    return {
        "scale": scale,
        "scale_gua": scale_gua,
        "scale_gua_name": GUA_NAMES_CN.get(scale_gua, ""),
        "inner_yao": [inner_yao1, inner_yao2, inner_yao3],
        "outer_yao": [outer_yao1, outer_yao2, outer_yao3],
        "params": params.to_dict(),
        "change_threshold": round(change_threshold, 4),
        "time_window": round(time_window, 1),
        "space_range": round(space_range, 4),
        "acceleration_trigger": round(acceleration_trigger, 4),
    }


class ScaleEngine:
    """
    体量引擎 — 参数自适应核心。

    类似大模型的超参数自适应：
    1. 从市场特征计算体量系数
    2. 体量系数映射到全套参数
    3. 参数传递给力学引擎和易经引擎
    """

    def __init__(self):
        self._scale_cache: Dict[float, ScaleParams] = {}

    def get_params(self, scale: float) -> ScaleParams:
        """获取体量参数（带缓存）。"""
        key = round(scale, 4)
        if key not in self._scale_cache:
            self._scale_cache[key] = smooth_scale_to_params(scale)
        return self._scale_cache[key]

    def compute_scale(self, market_snapshot: Dict[str, Any]) -> float:
        """从市场快照计算体量系数。"""
        return compute_scale(
            market_cap=market_snapshot.get("market_cap"),
            volume=market_snapshot.get("volume"),
            float_shares=market_snapshot.get("float_shares"),
            explicit=market_snapshot.get("market_scale"),
        )

    def adapt_snapshot(self, market_snapshot: Dict[str, Any],
                       scale: float = None) -> Tuple[Dict[str, Any], ScaleParams]:
        """
        根据体量调整市场快照。

        返回调整后的快照和参数集。
        """
        if scale is None:
            scale = self.compute_scale(market_snapshot)

        params = self.get_params(scale)

        # 调整波动率
        adjusted = dict(market_snapshot)
        vol = adjusted.get("volatility", 0.5)
        adjusted["volatility"] = max(0.05, min(0.95,
            vol + params.volatility_adjustment))

        # 调整价格位置敏感度
        pp = adjusted.get("price_position", 0.5)
        adjusted["price_position"] = pp  # 保持原值，空间力在引擎内调整

        return adjusted, params
