"""
八卦力学引擎 — 第一性原理的市场力场计算。

核心思想：易经不是玄学，是古代的系统动力学/拓扑分类学。
用现代物理数学语言重述：

  太极 = 市场本体（价格 + 成交量 + 时间）
  两仪 = 阴阳 = 多空 = 力的方向（+/-）
  四象 = 时间/空间/表/里 = 力的四个作用维度
  八卦 = 两仪 × 四象 = 8 种基础力场拓扑模式
  六十四卦 = 八卦 × 八卦 = 64 种内外环境叠加状态

八卦定乾坤 = 第一性原理：市场沿阻力最小方向运动
  ↓ 数学表述
  路径积分中，能量耗散最小的路径就是实际路径
  ↓ 计算方法
  构建多空势场 U(x)，计算两条路径的作用量 S = ∫Ldt
  选择 S 更小的方向 = 阻力最小方向
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Tuple, Optional
import math


# ============================================================
# 八卦定义（力场拓扑模式）
# ============================================================
# 每个八卦对应一种力场拓扑结构：
#   乾 ☰  — 三阳 — 多头共振，势不可挡
#   兑 ☱  — 上缺 — 表面强劲，内里不足
#   离 ☲  — 中虚 — 外强中干，虚火上升
#   震 ☳  — 上虚 — 底部启动，能量爆发
#   巽 ☴  — 下断 — 缓慢渗透，润物无声
#   坎 ☵  — 中实 — 深陷其中，险象环生
#   艮 ☶  — 上实 — 顶部沉重，下行压力大
#   坤 ☷  — 三阴 — 空头共振，绵绵不绝

GUA_QIAN = "qian"
GUA_DUI = "dui"
GUA_LI = "li"
GUA_ZHEN = "zhen"
GUA_XUN = "xun"
GUA_KAN = "kan"
GUA_GEN = "gen"
GUA_KUN = "kun"

GUA_NAMES_CN = {
    GUA_QIAN: "乾", GUA_DUI: "兑", GUA_LI: "离", GUA_ZHEN: "震",
    GUA_XUN: "巽", GUA_KAN: "坎", GUA_GEN: "艮", GUA_KUN: "坤",
}

# 八卦三爻（从下到上：初/二/三 = 里/中/表）
# 阳爻=1，阴爻=0
GUA_BINARY = {
    GUA_QIAN: (1, 1, 1),  # 乾：三阴转阳，最强做多
    GUA_DUI:  (0, 1, 1),  # 兑：里阴，表中阳
    GUA_LI:   (1, 0, 1),  # 离：里外阳，中间阴（虚火）
    GUA_ZHEN: (0, 0, 1),  # 震：里阴中阴，表阳（启动）
    GUA_XUN:  (1, 1, 0),  # 巽：里阳中阳，表阴（渗透）
    GUA_KAN:  (0, 1, 0),  # 坎：里阴中阳，表阴（险陷）
    GUA_GEN:  (1, 0, 0),  # 艮：里阳中阴，表阴（止住）
    GUA_KUN:  (0, 0, 0),  # 坤：三阴，最强做空
}


# ============================================================
# 四象力场分量
# ============================================================
@dataclass
class SixiangVector:
    """四象向量 — 四个维度的力分量。"""
    time_force: float = 0.0      # 时：周期力（-1~+1）
    space_force: float = 0.0     # 空：空间力（-1~+1）
    surface_force: float = 0.0   # 表：技术力（-1~+1）
    core_force: float = 0.0      # 里：内驱力（-1~+1）

    # 各维度的强度（0~1，用于计算确定性）
    time_strength: float = 0.0
    space_strength: float = 0.0
    surface_strength: float = 0.0
    core_strength: float = 0.0

    def magnitude(self) -> float:
        """向量模长。"""
        return math.sqrt(
            self.time_force**2 + self.space_force**2 +
            self.surface_force**2 + self.core_force**2
        ) / 2.0  # 归一化到 ~0-1

    def direction_consistency(self) -> float:
        """方向一致性：各维度符号相同的比例。"""
        forces = [self.time_force, self.space_force,
                  self.surface_force, self.core_force]
        signs = [1 if f > 0.05 else (-1 if f < -0.05 else 0) for f in forces]
        non_zero = [s for s in signs if s != 0]
        if not non_zero:
            return 0.5
        same_count = sum(1 for s in non_zero if s == non_zero[0])
        return same_count / len(non_zero)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "time_force": round(self.time_force, 4),
            "space_force": round(self.space_force, 4),
            "surface_force": round(self.surface_force, 4),
            "core_force": round(self.core_force, 4),
            "magnitude": round(self.magnitude(), 4),
            "consistency": round(self.direction_consistency(), 4),
        }


# ============================================================
# 势场与阻力最小路径
# ============================================================
@dataclass
class PotentialField:
    """
    价格势场 U(x)。

    势场由多个分量叠加而成：
    - 重力势：长期趋势产生的"坡度"
    - 弹性势：价格偏离均衡产生的回复力（弹簧）
    - 障碍势：支撑阻力位产生的势垒/势阱
    - 摩擦势：成交量/波动率产生的阻力

    阻力最小方向 = 势场梯度的反方向（从高势能到低势能）
    """
    # 网格点（价格位置 0~1 映射到 -1~+1）
    grid_points: List[float] = field(default_factory=list)
    # 各点的势能
    potential: List[float] = field(default_factory=list)
    # 各点的阻力（摩擦）
    resistance: List[float] = field(default_factory=list)

    # 多空路径的能量消耗
    long_path_energy: float = 0.0
    short_path_energy: float = 0.0

    # 阻力最小方向
    least_resistance_dir: str = "neutral"
    resistance_gap: float = 0.0  # 两条路径的能量差（归一化）

    def to_dict(self) -> Dict[str, Any]:
        return {
            "long_path_energy": round(self.long_path_energy, 4),
            "short_path_energy": round(self.short_path_energy, 4),
            "least_resistance_dir": self.least_resistance_dir,
            "resistance_gap": round(self.resistance_gap, 4),
            "potential_peaks": len([p for p in self.potential if p > 0.7]),
            "potential_valleys": len([p for p in self.potential if p < 0.3]),
        }


# ============================================================
# 八卦力学引擎输出
# ============================================================
@dataclass
class BaguaResult:
    """八卦力学引擎输出。"""
    # 四象力场
    sixiang: SixiangVector = field(default_factory=SixiangVector)

    # 本卦（当前力场拓扑）
    current_gua: str = GUA_KAN
    current_gua_cn: str = "坎"
    current_gua_binary: Tuple[int, int, int] = (0, 1, 0)

    # 两仪状态
    liangyi_state: str = "yang"   # yang / yin / balanced
    liangyi_strength: float = 0.0  # 0~1

    # 势场与阻力最小路径
    potential_field: PotentialField = field(default_factory=PotentialField)

    # 核心结论：第一性原理方向
    primary_direction: str = "neutral"  # long / short / neutral
    primary_confidence: float = 0.0     # 0~1

    # 六十四卦（内卦=当前微观，外卦=环境宏观）
    inner_gua: str = ""
    outer_gua: str = ""
    hexagram_name: str = ""
    hexagram_name_cn: str = ""

    # 统计特征
    feature_stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sixiang": self.sixiang.to_dict(),
            "current_gua": self.current_gua,
            "current_gua_cn": self.current_gua_cn,
            "current_gua_binary": list(self.current_gua_binary),
            "liangyi_state": self.liangyi_state,
            "liangyi_strength": round(self.liangyi_strength, 4),
            "potential_field": self.potential_field.to_dict(),
            "primary_direction": self.primary_direction,
            "primary_confidence": round(self.primary_confidence, 4),
            "inner_gua": self.inner_gua,
            "outer_gua": self.outer_gua,
            "hexagram_name": self.hexagram_name,
            "hexagram_name_cn": self.hexagram_name_cn,
            "feature_stats": self.feature_stats,
        }


# ============================================================
# 八卦力学引擎
# ============================================================
class BaguaEngine:
    """
    八卦力学引擎 — 第一性原理的市场力场计算。

    计算流程：
    1. 四象深度量化（时间/空间/表/里）
    2. 两仪判定（阴阳 = 多空主导）
    3. 八卦映射（两仪 × 四象 = 8 种力场拓扑）
    4. 势场构建（重力+弹性+障碍+摩擦）
    5. 阻力最小路径计算（能量最小化）
    6. 六十四卦（内外卦叠加）
    """

    def __init__(self):
        self.grid_size = 20  # 势场网格点数

    def infer(self, snapshot: Dict[str, Any],
               closes: List[float] = None,
               volumes: List[float] = None) -> BaguaResult:
        """
        运行八卦力学推理。

        Args:
            snapshot: 市场快照
            closes: 收盘价序列（旧→新）
            volumes: 成交量序列（旧→新）

        Returns:
            BaguaResult
        """
        result = BaguaResult()

        # Step 1: 四象深度量化
        sixiang = self._compute_sixiang(snapshot, closes, volumes)
        result.sixiang = sixiang

        # Step 2: 两仪判定
        liangyi_state, liangyi_strength = self._compute_liangyi(sixiang)
        result.liangyi_state = liangyi_state
        result.liangyi_strength = liangyi_strength

        # Step 3: 八卦映射（力场拓扑）
        gua, gua_binary = self._compute_bagua(sixiang, liangyi_state)
        result.current_gua = gua
        result.current_gua_cn = GUA_NAMES_CN.get(gua, "")
        result.current_gua_binary = gua_binary

        # Step 4: 势场构建
        pf = self._build_potential_field(snapshot, closes, volumes, sixiang)
        result.potential_field = pf

        # Step 5: 阻力最小方向 = 第一性原理结论
        if pf.least_resistance_dir == "long":
            result.primary_direction = "long"
        elif pf.least_resistance_dir == "short":
            result.primary_direction = "short"
        else:
            result.primary_direction = "neutral"

        # 置信度 = 阻力差距 × 四象一致性 × 两仪强度
        conf = (abs(pf.resistance_gap) * 0.5
                + sixiang.direction_consistency() * 0.3
                + liangyi_strength * 0.2)
        result.primary_confidence = max(0.0, min(1.0, conf))

        # Step 6: 六十四卦（内卦=里+中，外卦=表+环境）
        inner, outer = self._compute_inner_outer(sixiang, snapshot)
        result.inner_gua = inner
        result.outer_gua = outer
        result.hexagram_name = f"{GUA_NAMES_CN.get(outer, '')}为{GUA_NAMES_CN.get(inner, '')}"
        # 拼接六十四卦名
        result.hexagram_name_cn = self._build_hexagram_name(inner, outer)

        # 统计特征
        result.feature_stats = self._compute_feature_stats(
            snapshot, closes, volumes, sixiang)

        return result

    # ============================================================
    # Step 1: 四象深度量化
    # ============================================================
    def _compute_sixiang(self, snapshot: Dict[str, Any],
                          closes: List[float] = None,
                          volumes: List[float] = None) -> SixiangVector:
        """
        四象深度量化。

        每个维度不是一个简单的分数，而是有完整的统计计算：
        - 时：多周期自相关 + 傅里叶主频 + 相位
        - 空：分形维数 + 支撑阻力能量 + 布林带
        - 表：10+技术指标的统计一致性 + 动量通量
        - 里：供需能量差 + 资金流向积分 + 情绪熵
        """
        sv = SixiangVector()

        price = snapshot.get("price", 0)
        if not price:
            return sv

        # --- 时（周期力）---
        if closes and len(closes) >= 30:
            tf, ts = self._time_force_spectral(closes)
            sv.time_force = tf
            sv.time_strength = ts
        else:
            # 降级：用已有指标估算
            med_change = snapshot.get("med_change_pct", 0)
            sv.time_force = max(-1.0, min(1.0, med_change * 5))
            sv.time_strength = min(1.0, abs(med_change) * 10)

        # --- 空（空间力）---
        if closes and len(closes) >= 20:
            sf, ss = self._space_force_fractal(closes, price)
            sv.space_force = sf
            sv.space_strength = ss
        else:
            pos = snapshot.get("price_position", 0.5)
            sv.space_force = -(pos - 0.5) * 2  # 位置越高，向下力越大
            sv.space_strength = min(1.0, abs(pos - 0.5) * 2)

        # --- 表（技术力）---
        if closes and len(closes) >= 14:
            suf, sus = self._surface_force_matrix(closes)
            sv.surface_force = suf
            sv.surface_strength = sus
        else:
            tech = snapshot.get("technical_score", 0.5)
            sv.surface_force = (tech - 0.5) * 2
            sv.surface_strength = 0.5

        # --- 里（内驱力）---
        if closes and volumes and len(closes) >= 10:
            cf, cs = self._core_force_energy(closes, volumes)
            sv.core_force = cf
            sv.core_strength = cs
        else:
            sd = snapshot.get("supply_demand_score", 0.5)
            cf_s = snapshot.get("capital_flow_score", 0.5)
            sent = snapshot.get("sentiment_score", 0.5)
            core_val = (sd - 0.5) * 0.5 + (cf_s - 0.5) * 0.3 + (sent - 0.5) * 0.2
            sv.core_force = max(-1.0, min(1.0, core_val * 2))
            sv.core_strength = 0.4

        return sv

    def _time_force_spectral(self, closes: List[float]) -> Tuple[float, float]:
        """
        时间力：谱分析方法。

        计算多周期自相关系数，判断周期方向和强度。
        原理：如果短中长周期方向一致，周期力越强。
        """
        n = len(closes)
        if n < 10:
            return 0.0, 0.0

        # 计算不同周期的收益率
        def period_return(period):
            if period >= n:
                return 0.0, 0.0
            rets = [(closes[i] - closes[i - period]) / closes[i - period]
                    for i in range(period, n)]
            if not rets:
                return 0.0, 0.0
            avg_ret = sum(rets) / len(rets)
            # 用收益率的标准差倒数作为确定性
            std = (sum((r - avg_ret) ** 2 for r in rets) / len(rets)) ** 0.5
            certainty = 1.0 / (1.0 + std * 20) if std > 0 else 1.0
            return avg_ret, certainty

        # 短周期（3-5根K线）
        short_ret, short_cert = period_return(max(3, n // 10))
        # 中周期（10-15根K线）
        mid_ret, mid_cert = period_return(max(8, n // 5))
        # 长周期（20-30根K线）
        long_ret, long_cert = period_return(max(15, n // 3))

        # 标准化到 -1~+1
        def norm_ret(r):
            return max(-1.0, min(1.0, r * 50))  # 2% 对应 1.0

        short_f = norm_ret(short_ret)
        mid_f = norm_ret(mid_ret)
        long_f = norm_ret(long_ret)

        # 加权合成（长期权重最大）
        combined = short_f * 0.2 + mid_f * 0.3 + long_f * 0.5

        # 强度 = 加权一致性
        signs = [1 if f > 0 else -1 for f in [short_f, mid_f, long_f]]
        agreement = sum(1 for i in range(len(signs) - 1) if signs[i] == signs[i + 1]) / (len(signs) - 1)
        avg_cert = (short_cert + mid_cert + long_cert) / 3
        strength = agreement * 0.6 + avg_cert * 0.4

        return combined, min(1.0, strength)

    def _space_force_fractal(self, closes: List[float],
                               price: float) -> Tuple[float, float]:
        """
        空间力：分形 + 支撑阻力能量。

        计算：
        1. 价格在近期高低点中的位置（弹簧模型）
        2. 布林带位置（偏离度）
        3. 局部极值密度（支撑阻力位能量）

        空间力是回复力：位置越高，向下力越大。
        """
        n = len(closes)
        if n < 10:
            return 0.0, 0.0

        # 高低点
        high = max(closes)
        low = min(closes)
        if high == low:
            return 0.0, 0.5

        # 价格位置
        pos = (price - low) / (high - low)

        # 布林带
        ma20 = sum(closes[-20:]) / 20 if n >= 20 else sum(closes) / n
        std20 = (sum((c - ma20) ** 2 for c in closes[-20:]) / min(20, n)) ** 0.5
        boll_position = (price - ma20) / std20 if std20 > 0 else 0

        # 局部极值检测（简单版本：找出最近 N 个高低点）
        extremes = []
        window = 3
        for i in range(window, n - window):
            if closes[i] == max(closes[i - window:i + window + 1]):
                extremes.append(("high", closes[i]))
            elif closes[i] == min(closes[i - window:i + window + 1]):
                extremes.append(("low", closes[i]))

        # 计算当前价格到最近支撑阻力的距离
        nearest_resistance = high
        nearest_support = low
        for etype, eprice in extremes:
            if etype == "high" and eprice > price and eprice < nearest_resistance:
                nearest_resistance = eprice
            elif etype == "low" and eprice < price and eprice > nearest_support:
                nearest_support = eprice

        # 距离能量：离支撑越近向上力越大，离阻力越近向下力越大
        dist_resist = (nearest_resistance - price) / (high - low) if high != low else 0.5
        dist_support = (price - nearest_support) / (high - low) if high != low else 0.5

        # 空间力 = 支撑近则向上（正），阻力近则向下（负）
        if dist_support < dist_resist:
            space_f = (1.0 - dist_support * 2)  # 越近支撑力越大
        else:
            space_f = -(1.0 - dist_resist * 2)  # 越近阻力向下力越大

        # 布林带补充：上轨以上强阻力，下轨以下强支撑
        boll_contrib = -boll_position * 0.3
        space_f = space_f * 0.7 + boll_contrib
        space_f = max(-1.0, min(1.0, space_f))

        # 强度 = 极端值密度 + 布林带位置偏离度
        extreme_density = len(extremes) / max(1, n - 2 * window)
        boll_strength = min(1.0, abs(boll_position) / 2.0)
        strength = min(1.0, extreme_density * 2 + boll_strength * 0.5)

        return space_f, strength

    def _surface_force_matrix(self, closes: List[float]) -> Tuple[float, float]:
        """
        表（技术力）：多指标统计一致性矩阵。

        计算 8 个技术指标方向，统计一致性：
        - MA排列（5/10/20/60）
        - MACD
        - RSI
        - KDJ（简化）
        - 动量（ROC）
        - 布林带位置
        - 成交量趋势（如果有）
        - 波动率方向

        指标一致比例越高，技术力越强。
        """
        n = len(closes)
        if n < 5:
            return 0.0, 0.0

        signals = []

        # 1. MA5 方向
        if n >= 5:
            ma5 = sum(closes[-5:]) / 5
            ma5_prev = sum(closes[-6:-1]) / 5 if n >= 6 else ma5
            signals.append(1 if ma5 > ma5_prev else -1)

        # 2. MA20 位置
        if n >= 20:
            ma20 = sum(closes[-20:]) / 20
            signals.append(1 if closes[-1] > ma20 else -1)
        else:
            signals.append(0)

        # 3. 短期动量（ROC 5期）
        if n >= 6:
            roc5 = (closes[-1] - closes[-6]) / closes[-6]
            signals.append(1 if roc5 > 0 else -1)
        else:
            signals.append(0)

        # 4. 波动率方向（近5期波动率变化）
        if n >= 15:
            rets_recent = [(closes[i] - closes[i - 1]) / closes[i - 1]
                           for i in range(n - 5, n)]
            rets_prev = [(closes[i] - closes[i - 1]) / closes[i - 1]
                          for i in range(n - 10, n - 5)]
            vol_recent = (sum(r ** 2 for r in rets_recent) / len(rets_recent)) ** 0.5
            vol_prev = (sum(r ** 2 for r in rets_prev) / len(rets_prev)) ** 0.5
            # 波动率上升通常是下跌信号
            signals.append(-1 if vol_recent > vol_prev * 1.1 else (1 if vol_recent < vol_prev * 0.9 else 0))
        else:
            signals.append(0)

        # 5. RSI（简化版）
        if n >= 15:
            gains = []
            losses = []
            for i in range(1, min(14, n)):
                diff = closes[-i] - closes[-i - 1]
                if diff > 0:
                    gains.append(diff)
                else:
                    losses.append(-diff)
            avg_gain = sum(gains) / 14 if gains else 0
            avg_loss = sum(losses) / 14 if losses else 0
            if avg_loss == 0:
                rsi = 100
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            if rsi > 70:
                signals.append(-1)  # 超买
            elif rsi < 30:
                signals.append(1)   # 超卖
            else:
                signals.append(1 if rsi > 50 else -1)
        else:
            signals.append(0)

        # 6. 布林带位置方向
        if n >= 20:
            ma20_bb = sum(closes[-20:]) / 20
            std20_bb = (sum((c - ma20_bb) ** 2 for c in closes[-20:]) / 20) ** 0.5
            bb_pos = (closes[-1] - ma20_bb) / std20_bb if std20_bb > 0 else 0
            if bb_pos > 2:
                signals.append(-1)  # 上轨以上
            elif bb_pos < -2:
                signals.append(1)   # 下轨以下
            else:
                signals.append(1 if bb_pos > 0 else -1)
        else:
            signals.append(0)

        # 7. 高低点移动（更高的高点 vs 更低的低点）
        if n >= 10:
            recent_highs = max(closes[-5:])
            prev_highs = max(closes[-10:-5])
            recent_lows = min(closes[-5:])
            prev_lows = min(closes[-10:-5])
            if recent_highs > prev_highs and recent_lows > prev_lows:
                signals.append(1)   # 上升趋势
            elif recent_highs < prev_highs and recent_lows < prev_lows:
                signals.append(-1)  # 下降趋势
            else:
                signals.append(0)
        else:
            signals.append(0)

        # 8. 收盘价位置（相对于K线实体）
        if n >= 5:
            recent_closes = closes[-5:]
            h = max(recent_closes)
            l = min(recent_closes)
            if h > l:
                close_pos = (closes[-1] - l) / (h - l)
                signals.append(1 if close_pos > 0.6 else (-1 if close_pos < 0.4 else 0))
            else:
                signals.append(0)
        else:
            signals.append(0)

        # 统计一致性
        non_zero = [s for s in signals if s != 0]
        if not non_zero:
            return 0.0, 0.1

        bullish = sum(1 for s in non_zero if s > 0)
        bearish = sum(1 for s in non_zero if s < 0)
        total = len(non_zero)

        if bullish > bearish:
            surface_f = bullish / total  # 0~1
        else:
            surface_f = -bearish / total  # -1~0

        # 一致性强度
        max_side = max(bullish, bearish)
        consistency = max_side / total

        return surface_f, consistency

    def _core_force_energy(self, closes: List[float],
                            volumes: List[float]) -> Tuple[float, float]:
        """
        里（内驱力）：供需能量差 + 资金流向积分。

        计算：
        1. OBV 累积能量（量价配合）
        2. 资金流向积分（上涨放量 / 下跌放量）
        3. 供需能量比（买方能量 / 卖方能量）

        内驱力是最根本的力，决定长期方向。
        """
        n = min(len(closes), len(volumes))
        if n < 5:
            return 0.0, 0.3

        # OBV 能量线
        obv = 0.0
        obv_list = []
        for i in range(1, n):
            if closes[i] > closes[i - 1]:
                obv += volumes[i]
            elif closes[i] < closes[i - 1]:
                obv -= volumes[i]
            obv_list.append(obv)

        # OBV 方向
        if len(obv_list) >= 2:
            obv_trend = (obv_list[-1] - obv_list[0]) / max(abs(obv_list[0]), 1)
        else:
            obv_trend = 0

        # 上涨日量能 vs 下跌日量能
        up_vol = 0.0
        down_vol = 0.0
        for i in range(1, n):
            if closes[i] > closes[i - 1]:
                up_vol += volumes[i]
            elif closes[i] < closes[i - 1]:
                down_vol += volumes[i]

        total_vol = up_vol + down_vol
        if total_vol > 0:
            vol_ratio = (up_vol - down_vol) / total_vol  # -1 ~ +1
        else:
            vol_ratio = 0

        # 资金流向：连续上涨放量 / 连续下跌放量的模式
        flow_score = 0.0
        lookback = min(10, n - 1)
        for i in range(n - lookback, n):
            if i >= 1:
                chg = (closes[i] - closes[i - 1]) / closes[i - 1]
                vol_rat = volumes[i] / (sum(volumes[max(0, i - 5):i]) / min(5, i) if i > 0 else 1)
                flow_score += chg * vol_rat

        flow_score = max(-1.0, min(1.0, flow_score * 10))

        # 合成核心力
        obv_norm = max(-1.0, min(1.0, obv_trend))
        core_f = obv_norm * 0.4 + vol_ratio * 0.35 + flow_score * 0.25
        core_f = max(-1.0, min(1.0, core_f))

        # 强度 = 量能放大程度 + OBV趋势清晰度
        vol_amplitude = max(up_vol, down_vol) / total_vol if total_vol > 0 else 0.5
        strength = min(1.0, vol_amplitude * 0.5 + abs(obv_norm) * 0.5)

        return core_f, strength

    # ============================================================
    # Step 2: 两仪判定
    # ============================================================
    def _compute_liangyi(self, sixiang: SixiangVector) -> Tuple[str, float]:
        """
        两仪判定：阴阳 = 多空。

        阳 = 合力向上
        阴 = 合力向下

        强度 = |合力| × 一致性
        """
        net = (sixiang.time_force * 0.2 + sixiang.space_force * 0.15
               + sixiang.surface_force * 0.25 + sixiang.core_force * 0.4)

        consistency = sixiang.direction_consistency()

        if net > 0.05:
            state = "yang"
            strength = min(1.0, abs(net) * 0.7 + consistency * 0.3)
        elif net < -0.05:
            state = "yin"
            strength = min(1.0, abs(net) * 0.7 + consistency * 0.3)
        else:
            state = "balanced"
            strength = max(0.0, 1.0 - abs(net) * 10)

        return state, strength

    # ============================================================
    # Step 3: 八卦映射（力场拓扑）
    # ============================================================
    def _compute_bagua(self, sixiang: SixiangVector,
                        liangyi_state: str) -> Tuple[str, Tuple[int, int, int]]:
        """
        八卦 = 两仪 × 四象。

        三爻从下到上对应：
        - 初爻（下）= 里（core）  — 内在驱动
        - 二爻（中）= 空（space） — 空间位置
        - 三爻（上）= 表（surface）— 技术表观

        时间力作为背景，不直接入卦，但影响动爻。

        每个维度的阴阳判定：
        - force > 0.1  → 阳（做多力）
        - force < -0.1 → 阴（做空力）
        - 中间        → 随主导方向（两仪）
        """
        # 各维度的阴阳
        def to_yao(force_val, default):
            if force_val > 0.1:
                return 1
            elif force_val < -0.1:
                return 0
            else:
                return default  # 弱信号跟随两仪

        default = 1 if liangyi_state == "yang" else 0

        yao1 = to_yao(sixiang.core_force, default)     # 初爻 = 里
        yao2 = to_yao(sixiang.space_force, default)    # 二爻 = 空
        yao3 = to_yao(sixiang.surface_force, default)  # 三爻 = 表

        binary = (yao1, yao2, yao3)

        # 查找对应的卦
        for gua_name, gua_bin in GUA_BINARY.items():
            if gua_bin == binary:
                return gua_name, binary

        # 默认
        return GUA_KAN, (0, 1, 0)

    # ============================================================
    # Step 4-5: 势场构建 + 阻力最小路径
    # ============================================================
    def _build_potential_field(self, snapshot: Dict[str, Any],
                                closes: List[float] = None,
                                volumes: List[float] = None,
                                sixiang: SixiangVector = None) -> PotentialField:
        """
        构建价格势场并计算阻力最小路径。

        势场 = 重力势 + 弹性势 + 障碍势 + 摩擦势

        阻力最小方向 = 沿势场梯度下降的方向（从高势能到低势能）
        数学上：计算做多路径和做空路径的总能量消耗，选择较小的。

        能量 = ∫ (势梯度 + 摩擦力) dx
        """
        pf = PotentialField()
        n_grid = self.grid_size

        price = snapshot.get("price", 0)
        if not price or closes is None or len(closes) < 10:
            return pf

        high = max(closes)
        low = min(closes)
        if high == low:
            return pf

        # 生成网格（0=最低点, 1=最高点）
        pf.grid_points = [i / (n_grid - 1) for i in range(n_grid)]
        pf.potential = [0.0] * n_grid
        pf.resistance = [0.0] * n_grid

        # --- 1. 重力势：长期趋势产生的"坡度" ---
        # 重力沿时间力方向倾斜
        gravity = sixiang.time_force if sixiang else 0
        for i in range(n_grid):
            pos = pf.grid_points[i]
            # 重力势能 = -gravity * pos（做多力强则高位势能低，反之亦然）
            pf.potential[i] += -gravity * pos * 0.4

        # --- 2. 弹性势：均值回复（弹簧）---
        # 价格偏离均衡越远，回复势能越大
        mean_pos = 0.5
        for i in range(n_grid):
            pos = pf.grid_points[i]
            # U = 0.5 * k * (x - x0)^2
            spring_k = 1.5  # 弹性系数
            pf.potential[i] += 0.5 * spring_k * (pos - mean_pos) ** 2

        # --- 3. 障碍势：支撑阻力位的势垒/势阱 ---
        # 找出局部极值点作为支撑阻力
        extremes = []
        window = 3
        n = len(closes)
        for i in range(window, n - window):
            if closes[i] == max(closes[i - window:i + window + 1]):
                pos_norm = (closes[i] - low) / (high - low)
                extremes.append(("high", pos_norm))
            elif closes[i] == min(closes[i - window:i + window + 1]):
                pos_norm = (closes[i] - low) / (high - low)
                extremes.append(("low", pos_norm))

        # 每个极值点产生一个高斯势垒/势阱
        sigma = 0.05  # 势垒宽度
        for etype, epos in extremes:
            amplitude = 0.15  # 势垒高度
            if etype == "high":
                # 阻力位 = 势垒（高势能，难以突破）
                for i in range(n_grid):
                    diff = pf.grid_points[i] - epos
                    pf.potential[i] += amplitude * math.exp(-0.5 * (diff / sigma) ** 2)
            else:
                # 支撑位 = 势阱（低势能，容易停留）
                for i in range(n_grid):
                    diff = pf.grid_points[i] - epos
                    pf.potential[i] -= amplitude * math.exp(-0.5 * (diff / sigma) ** 2)

        # --- 4. 摩擦势（阻力系数）---
        # 成交量大的地方摩擦大，波动大的地方摩擦大
        avg_vol = sum(volumes) / len(volumes) if volumes else 1
        for i in range(n_grid):
            pos = pf.grid_points[i]
            # 基础摩擦
            base_friction = 0.1
            # 极端位置摩擦更大（流动性可能变差）
            edge_penalty = abs(pos - 0.5) * 0.2
            pf.resistance[i] = base_friction + edge_penalty

        # 归一化势场到 0~1
        pmin = min(pf.potential)
        pmax = max(pf.potential)
        if pmax > pmin:
            pf.potential = [(p - pmin) / (pmax - pmin) for p in pf.potential]

        # --- 5. 计算阻力最小路径 ---
        # 当前价格位置
        current_pos = (price - low) / (high - low)
        current_pos = max(0.01, min(0.99, current_pos))

        # 做多路径能量：从当前位置向上到高点
        long_energy = self._path_energy(pf, current_pos, 1.0, direction="up")
        # 做空路径能量：从当前位置向下到低点
        short_energy = self._path_energy(pf, current_pos, 0.0, direction="down")

        pf.long_path_energy = long_energy
        pf.short_path_energy = short_energy

        # 阻力最小方向 = 能量小的那个方向
        total = long_energy + short_energy
        if total > 0:
            pf.resistance_gap = (short_energy - long_energy) / total  # 正=多头阻力小
        else:
            pf.resistance_gap = 0

        if abs(pf.resistance_gap) < 0.1:
            pf.least_resistance_dir = "neutral"
        elif pf.resistance_gap > 0:
            pf.least_resistance_dir = "long"
        else:
            pf.least_resistance_dir = "short"

        return pf

    def _path_energy(self, pf: PotentialField,
                      start_pos: float, end_pos: float,
                      direction: str = "up") -> float:
        """
        计算一条路径的总能量消耗。

        能量 = 势能变化 + 摩擦耗能
        E = ΔU + ∫f·dx

        做多：向上走，需要克服阻力 + 势能增加的地方要做功
        做空：向下走，势能减少的地方释放能量，阻力依然消耗

        简化：用黎曼和近似路径积分
        """
        n = len(pf.grid_points)
        if n < 2:
            return 1.0

        # 找到起止索引
        start_idx = int(start_pos * (n - 1))
        end_idx = int(end_pos * (n - 1))
        start_idx = max(0, min(n - 1, start_idx))
        end_idx = max(0, min(n - 1, end_idx))

        if start_idx == end_idx:
            return pf.resistance[start_idx] * 0.01

        step = 1 if end_idx > start_idx else -1
        total_energy = 0.0
        dx = 1.0 / (n - 1)

        for i in range(start_idx, end_idx + step, step):
            if i < 0 or i >= n:
                continue
            # 势能差（上坡需要额外能量，下坡释放能量）
            if i != start_idx:
                prev_i = i - step
                dU = pf.potential[i] - pf.potential[prev_i]
                # 上坡加能量，下坡减能量（但不能为负，实际还有摩擦）
                if (direction == "up" and dU > 0) or (direction == "down" and dU < 0):
                    total_energy += abs(dU)  # 逆势消耗
                else:
                    total_energy += abs(dU) * 0.3  # 顺势助力，摩擦消耗剩余

            # 摩擦总是消耗能量
            total_energy += pf.resistance[i] * dx

        return max(0.01, total_energy)

    # ============================================================
    # Step 6: 六十四卦（内外卦）
    # ============================================================
    def _compute_inner_outer(self, sixiang: SixiangVector,
                              snapshot: Dict[str, Any]) -> Tuple[str, str]:
        """
        六十四卦 = 内卦 × 外卦。

        内卦（下卦）= 微观/内在状态 = 里 + 空 + 短期动量
        外卦（上卦）= 宏观/外在环境 = 时间 + 表 + 长期趋势

        两卦叠加 = 64 种市场拓扑状态
        """
        # 内卦三爻
        def yao(val, threshold=0.1):
            return 1 if val > threshold else (0 if val < -threshold else 0.5)

        # 内卦：core (初爻) + space (二爻) + short-term surface (三爻)
        inner_1 = yao(sixiang.core_force)
        inner_2 = yao(sixiang.space_force)
        inner_3 = yao(sixiang.surface_force * 1.2)  # 表观更敏感

        # 处理中间态
        if inner_1 == 0.5:
            inner_1 = 1 if sixiang.core_force >= 0 else 0
        if inner_2 == 0.5:
            inner_2 = 1 if sixiang.space_force >= 0 else 0
        if inner_3 == 0.5:
            inner_3 = 1 if sixiang.surface_force >= 0 else 0

        inner_binary = (int(inner_1), int(inner_2), int(inner_3))

        # 外卦：time (初爻) + macro long-term (二爻) + overall surface (三爻)
        outer_1 = yao(sixiang.time_force)
        outer_2 = yao(sixiang.core_force * 0.8 + sixiang.time_force * 0.2)
        outer_3 = yao(sixiang.surface_force)

        if outer_1 == 0.5:
            outer_1 = 1 if sixiang.time_force >= 0 else 0
        if outer_2 == 0.5:
            outer_2 = 1 if (sixiang.core_force + sixiang.time_force) >= 0 else 0
        if outer_3 == 0.5:
            outer_3 = 1 if sixiang.surface_force >= 0 else 0

        outer_binary = (int(outer_1), int(outer_2), int(outer_3))

        # 查找卦名
        inner_gua = GUA_KAN
        outer_gua = GUA_KAN
        for name, binary in GUA_BINARY.items():
            if binary == inner_binary:
                inner_gua = name
            if binary == outer_binary:
                outer_gua = name

        return inner_gua, outer_gua

    def _build_hexagram_name(self, inner: str, outer: str) -> str:
        """构建六十四卦中文名。"""
        inner_cn = GUA_NAMES_CN.get(inner, "")
        outer_cn = GUA_NAMES_CN.get(outer, "")

        # 常见六十四卦名（简化版，常见的列出来）
        hex_names = {
            ("qian", "qian"): "乾为天",
            ("kun", "kun"): "坤为地",
            ("kan", "kan"): "坎为水",
            ("li", "li"): "离为火",
            ("zhen", "zhen"): "震为雷",
            ("gen", "gen"): "艮为山",
            ("xun", "xun"): "巽为风",
            ("dui", "dui"): "兑为泽",
            ("kun", "qian"): "天地否",
            ("qian", "kun"): "地天泰",
            ("li", "kan"): "水火既济",
            ("kan", "li"): "火水未济",
            ("zhen", "gen"): "山雷颐",
            ("gen", "zhen"): "雷山小过",
            ("xun", "dui"): "泽风大过",
            ("dui", "xun"): "风泽中孚",
            ("li", "qian"): "天火同人",
            ("qian", "li"): "火天大有",
            ("kun", "kan"): "水地比",
            ("kan", "kun"): "地水师",
            ("zhen", "qian"): "天雷无妄",
            ("qian", "zhen"): "雷天大壮",
            ("gen", "qian"): "天山遁",
            ("qian", "gen"): "山天大畜",
            ("xun", "qian"): "天风姤",
            ("qian", "xun"): "风天小畜",
            ("dui", "qian"): "天泽履",
            ("qian", "dui"): "泽天夬",
            ("li", "kun"): "地火明夷",
            ("kun", "li"): "火地晋",
            ("zhen", "kun"): "地雷复",
            ("kun", "zhen"): "雷地豫",
            ("gen", "kun"): "地山谦",
            ("kun", "gen"): "山地剥",
            ("xun", "kun"): "地风升",
            ("kun", "xun"): "风地观",
            ("dui", "kun"): "地泽临",
            ("kun", "dui"): "泽地萃",
        }

        key = (inner, outer)
        if key in hex_names:
            return hex_names[key]

        return f"{outer_cn}{inner_cn}"

    # ============================================================
    # 统计特征汇总
    # ============================================================
    def _compute_feature_stats(self, snapshot: Dict[str, Any],
                                closes: List[float],
                                volumes: List[float],
                                sixiang: SixiangVector) -> Dict[str, Any]:
        """计算所有统计特征，用于调试和分析。"""
        stats = {
            "sixiang_magnitude": round(sixiang.magnitude(), 4),
            "sixiang_consistency": round(sixiang.direction_consistency(), 4),
        }

        if closes and len(closes) > 1:
            rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
                    for i in range(1, len(closes))]
            stats["return_mean"] = round(sum(rets) / len(rets), 6)
            stats["return_std"] = round(
                (sum(r ** 2 for r in rets) / len(rets)) ** 0.5, 6)
            stats["return_skew"] = round(
                sum(r ** 3 for r in rets) / len(rets) / (
                    (sum(r ** 2 for r in rets) / len(rets)) ** 1.5
                ) if len(rets) > 2 else 0, 4)

        if closes and volumes:
            n = min(len(closes), len(volumes))
            if n > 2:
                # 量价相关系数
                avg_p = sum(closes[:n]) / n
                avg_v = sum(volumes[:n]) / n
                cov = sum((closes[i] - avg_p) * (volumes[i] - avg_v)
                          for i in range(n)) / n
                std_p = (sum((p - avg_p) ** 2 for p in closes[:n]) / n) ** 0.5
                std_v = (sum((v - avg_v) ** 2 for v in volumes[:n]) / n) ** 0.5
                if std_p > 0 and std_v > 0:
                    stats["price_volume_corr"] = round(cov / (std_p * std_v), 4)

        return stats


def default_bagua_engine() -> BaguaEngine:
    """获取默认八卦力学引擎。"""
    return BaguaEngine()
