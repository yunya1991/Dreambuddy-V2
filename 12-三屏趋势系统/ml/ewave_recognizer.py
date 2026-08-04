"""艾略特波浪识别器 (Elliott Wave Recognizer)

识别艾略特五浪结构中的可交易浪：
- 推动浪 5 浪结构 (1-2-3-4-5)
- 调整浪 3 浪结构 (A-B-C)
- 浪3 主升浪（最长、最强）
- 浪5 末升浪（可能衰竭）

识别方法：
1. ZigZag 算法识别关键转折点（高低点交替）
2. 分形（Fractal）辅助转折点确认
3. 艾略特三大硬规则判定五浪结构：
   - 规则1：浪2不能完全回撤浪1（浪2低点 > 浪1起点）
   - 规则2：浪3不能是推动浪中最短的一浪
   - 规则3：浪4不能与浪1价格区间重叠（浪4低点 > 浪1高点，多头情况）

信号触发：
- ENTER_LONG_3: 浪2结束、浪3启动（最强信号）
- ENTER_LONG_5: 浪4结束、浪5启动（次强信号）
- EXIT_LONG_5: 浪5结束（顶部离场）
- ENTER_SHORT_C: 浪5结束后调整浪A或C启动（做空信号）

物理引擎评估器：
- 复用 PhysicsConfidenceScorer
- 评估波浪信号的物理置信度
- 调节仓位（基础3成 × 物理系数）

文件: ml/ewave_recognizer.py
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class WavePoint:
    """波浪转折点"""
    idx: int           # 在 DataFrame 中的位置索引
    price: float       # 转折点价格
    point_type: str    # 'HIGH' or 'LOW'
    timestamp: Optional[pd.Timestamp] = None


@dataclass
class WaveStructure:
    """识别出的波浪结构"""
    waves: List[WavePoint]   # 转折点序列
    wave_label: str          # 'IMPULSE_5' / 'CORRECTIVE_3' / 'INCOMPLETE'
    current_wave: int        # 当前所在浪号 (1-5 for impulse, 1-3 for corrective)
    signal: str              # 信号类型
    confidence: float        # 信号置信度 [0, 1]


class ElliottWaveRecognizer:
    """艾略特波浪识别器

    用法:
        recognizer = ElliottWaveRecognizer(zigzag_threshold=0.05)
        waves = recognizer.identify_waves(daily_df)
        signal = recognizer.generate_signal(waves, current_price)
    """

    def __init__(
        self,
        zigzag_threshold: float = 0.05,
        fractal_window: int = 5,
        min_wave_points: int = 6,
        wave2_retrace_max: float = 1.0,    # 浪2最大回撤比例（不能完全回撤浪1）
        wave3_min_ratio: float = 0.382,    # 浪3最短比例（相对浪1）
        wave4_overlap_max: float = 0.0,    # 浪4与浪1最大重叠（0=不能重叠）
    ):
        """初始化波浪识别器

        参数:
            zigzag_threshold: ZigZag转折阈值（5%表示5%以上反转才识别为转折点）
            fractal_window: 分形识别窗口（前后各N根K线）
            min_wave_points: 识别五浪结构所需最小转折点数
            wave2_retrace_max: 浪2最大回撤比例
            wave3_min_ratio: 浪3最短比例（相对浪1的斐波那契0.382）
            wave4_overlap_max: 浪4与浪1最大重叠比例
        """
        self.zigzag_threshold = zigzag_threshold
        self.fractal_window = fractal_window
        self.min_wave_points = min_wave_points
        self.wave2_retrace_max = wave2_retrace_max
        self.wave3_min_ratio = wave3_min_ratio
        self.wave4_overlap_max = wave4_overlap_max

    def _compute_zigzag(self, highs: np.ndarray, lows: np.ndarray) -> List[WavePoint]:
        """ZigZag算法识别转折点

        算法：
        1. 从起点开始追踪当前趋势（上升/下降）
        2. 当价格反转超过阈值时，标记转折点
        3. 高低点交替出现
        """
        n = len(highs)
        if n < 5:
            return []

        # 初始化：找第一个转折点
        points = []
        trend = 0  # 0=未知, 1=上升, -1=下降
        last_extreme_idx = 0
        last_extreme_price = highs[0] if highs[0] > lows[0] else lows[0]

        # 先找初始方向
        for i in range(1, n):
            up_move = (highs[i] - last_extreme_price) / last_extreme_price
            down_move = (last_extreme_price - lows[i]) / last_extreme_price
            if up_move >= self.zigzag_threshold:
                trend = 1
                points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='LOW'))
                last_extreme_idx = i
                last_extreme_price = highs[i]
                break
            elif down_move >= self.zigzag_threshold:
                trend = -1
                points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='HIGH'))
                last_extreme_idx = i
                last_extreme_price = lows[i]
                break

        if trend == 0:
            return []

        # 持续追踪转折点
        for i in range(last_extreme_idx + 1, n):
            if trend == 1:  # 上升中，寻找下一个高点
                if highs[i] > last_extreme_price:
                    last_extreme_price = highs[i]
                    last_extreme_idx = i
                # 检查反转
                retrace = (last_extreme_price - lows[i]) / last_extreme_price
                if retrace >= self.zigzag_threshold:
                    points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='HIGH'))
                    trend = -1
                    last_extreme_price = lows[i]
                    last_extreme_idx = i
            else:  # 下降中，寻找下一个低点
                if lows[i] < last_extreme_price:
                    last_extreme_price = lows[i]
                    last_extreme_idx = i
                # 检查反转
                retrace = (highs[i] - last_extreme_price) / last_extreme_price
                if retrace >= self.zigzag_threshold:
                    points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='LOW'))
                    trend = 1
                    last_extreme_price = highs[i]
                    last_extreme_idx = i

        # 添加最后一个未确认的转折点
        if len(points) > 0:
            last_type = points[-1].point_type
            if last_type == 'HIGH' and trend == -1:
                points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='LOW'))
            elif last_type == 'LOW' and trend == 1:
                points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='HIGH'))

        return points

    def _confirm_with_fractals(
        self, points: List[WavePoint], highs: np.ndarray, lows: np.ndarray
    ) -> List[WavePoint]:
        """用分形确认转折点（过滤噪声）

        分形定义：N根K线中，中间K线的高点最高=上分形，低点最低=下分形
        """
        if not points:
            return points

        w = self.fractal_window
        confirmed = []
        for p in points:
            i = p.idx
            if i < w or i >= len(highs) - w:
                confirmed.append(p)  # 边界点直接保留
                continue

            if p.point_type == 'HIGH':
                # 检查是否为上分形
                is_fractal = True
                for j in range(i - w, i + w + 1):
                    if j == i:
                        continue
                    if highs[j] >= highs[i]:
                        is_fractal = False
                        break
                if is_fractal:
                    confirmed.append(p)
            else:  # LOW
                is_fractal = True
                for j in range(i - w, i + w + 1):
                    if j == i:
                        continue
                    if lows[j] <= lows[i]:
                        is_fractal = False
                        break
                if is_fractal:
                    confirmed.append(p)

        # 如果过滤太多，保留原始
        if len(confirmed) < self.min_wave_points // 2:
            return points
        return confirmed

    def _classify_impulse_wave(
        self, points: List[WavePoint], is_bull: bool = True
    ) -> Tuple[str, int, float]:
        """判定五浪推动结构

        多头推动浪：低-高-低-高-低-高（5浪上升）
        空头推动浪：高-低-高-低-高-低（5浪下降）

        返回: (wave_label, current_wave, confidence)
        """
        if len(points) < self.min_wave_points:
            return ('INCOMPLETE', 0, 0.0)

        # 取最后6个转折点（对应完整的5浪结构）
        recent = points[-6:]
        if is_bull:
            # 多头推动浪结构：LOW-HIGH-LOW-HIGH-LOW-HIGH
            expected_pattern = ['LOW', 'HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH']
        else:
            # 空头推动浪结构：HIGH-LOW-HIGH-LOW-HIGH-LOW
            expected_pattern = ['HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH', 'LOW']

        actual_pattern = [p.point_type for p in recent]
        if actual_pattern != expected_pattern:
            return ('INCOMPLETE', 0, 0.0)

        # 多头情况：浪1=recent[0]→recent[1], 浪2=recent[1]→recent[2], ...
        # 各浪端点
        if is_bull:
            p0, p1, p2, p3, p4, p5 = recent  # p0=浪1起点, p1=浪1顶/浪2起点, ...
            wave1_height = p1.price - p0.price
            wave2_retrace = p1.price - p2.price
            wave3_height = p3.price - p2.price
            wave4_retrace = p3.price - p4.price
            wave5_height = p5.price - p4.price
            wave1_high = p1.price
            wave4_low = p4.price
        else:
            p0, p1, p2, p3, p4, p5 = recent
            wave1_height = p0.price - p1.price
            wave2_retrace = p2.price - p1.price
            wave3_height = p2.price - p3.price
            wave4_retrace = p4.price - p3.price
            wave5_height = p4.price - p5.price
            wave1_high = p1.price  # 空头浪1的低点
            wave4_low = p4.price   # 空头浪4的高点

        if wave1_height <= 0:
            return ('INCOMPLETE', 0, 0.0)

        # 规则1：浪2不能完全回撤浪1
        rule1_ok = wave2_retrace < wave1_height * self.wave2_retrace_max
        # 规则2：浪3不能是最短推动浪
        wave3_min_ok = wave3_height >= wave1_height * self.wave3_min_ratio
        # 规则3：浪4不重叠浪1（多头情况：浪4低点 > 浪1高点）
        if is_bull:
            rule3_ok = wave4_low > wave1_high * (1 - self.wave4_overlap_max)
        else:
            rule3_ok = wave4_low < wave1_high * (1 + self.wave4_overlap_max)

        # 计算规则满足度（用于置信度）
        rules_passed = sum([rule1_ok, rule3_ok])  # 规则2单独评估
        confidence = 0.0

        # 判定当前所在浪
        # 如果5个浪都完整，可能在浪5结束或调整浪中
        if wave5_height > 0:
            # 五浪完整
            if rule1_ok and rule3_ok and wave3_min_ok:
                # 三大规则全部满足，是有效的五浪结构
                # 判断浪3是否最长（最强信号）
                wave3_longest = wave3_height >= max(wave1_height, wave5_height)
                if wave3_longest:
                    confidence = 0.9
                else:
                    confidence = 0.7
                return ('IMPULSE_5', 5, confidence)
            else:
                return ('INCOMPLETE', 5, 0.3)

        # 如果浪5未确认，可能在浪3或浪4
        if wave3_height > 0 and wave4_retrace > 0:
            # 浪4进行中
            if rule1_ok and rule3_ok:
                return ('IMPULSE_5', 4, 0.7)
            else:
                return ('INCOMPLETE', 4, 0.3)

        if wave3_height > 0:
            # 浪3进行中
            if rule1_ok:
                # 浪3主升浪
                wave3_strength = wave3_height / wave1_height
                if wave3_strength >= 1.0:  # 浪3延伸
                    confidence = 0.85
                elif wave3_strength >= 0.618:
                    confidence = 0.7
                else:
                    confidence = 0.5
                return ('IMPULSE_5', 3, confidence)
            else:
                return ('INCOMPLETE', 3, 0.3)

        if wave2_retrace > 0:
            # 浪2进行中（浪2结束=浪3启动信号）
            retrace_ratio = wave2_retrace / wave1_height
            # 浪2典型回撤0.5-0.618
            if 0.3 <= retrace_ratio <= 0.8:
                return ('IMPULSE_5', 2, 0.6)
            else:
                return ('INCOMPLETE', 2, 0.3)

        # 浪1进行中
        return ('IMPULSE_5', 1, 0.4)

    def identify_waves(self, prices: pd.DataFrame) -> WaveStructure:
        """识别波浪结构（含实时状态判断）

        参数:
            prices: 日线OHLCV DataFrame

        返回:
            WaveStructure 对象

        实时状态判断逻辑：
        - 转折点是事后确认的，单纯依靠ZigZag转折点无法识别"当前所在浪"
        - 通过最后一个转折点类型 + 当前价格相对位置，推断当前所在浪
        """
        highs = prices['high'].values
        lows = prices['low'].values
        closes = prices['close'].values
        current_price = float(closes[-1]) if len(closes) > 0 else 0.0

        # 1. ZigZag识别转折点
        points = self._compute_zigzag(highs, lows)

        # 2. 分形确认
        points = self._confirm_with_fractals(points, highs, lows)

        if len(points) < 3:
            return WaveStructure(
                waves=points, wave_label='INCOMPLETE',
                current_wave=0, signal='WAIT', confidence=0.0
            )

        # 3. 实时状态判断：基于最后一个转折点 + 当前价格位置
        # 多头推动浪结构：LOW(p0)-HIGH(p1)-LOW(p2)-HIGH(p3)-LOW(p4)-HIGH(p5)
        # 空头推动浪结构：HIGH(p0)-LOW(p1)-HIGH(p2)-LOW(p3)-HIGH(p4)-LOW(p5)
        last_point = points[-1]
        # 取最近的转折点序列（最多6个）
        recent = points[-6:] if len(points) >= 6 else points

        # 判断大方向：用最近两个转折点的趋势
        if len(recent) >= 2:
            # 如果倒数第二个是LOW、最后一个是HIGH → 上升趋势
            # 如果倒数第二个是HIGH、最后一个是LOW → 下降趋势
            if recent[-2].point_type == 'LOW' and recent[-1].point_type == 'HIGH':
                is_bull = True
            elif recent[-2].point_type == 'HIGH' and recent[-1].point_type == 'LOW':
                is_bull = False
            else:
                # 默认多头
                is_bull = True
        else:
            is_bull = True

        # 4. 根据转折点数量和当前价格位置判定当前浪
        label, current_wave, confidence = self._classify_realtime_wave(
            points, current_price, is_bull
        )

        # 5. 生成信号
        signal = self._generate_signal(label, current_wave, confidence, is_bull)

        return WaveStructure(
            waves=points,
            wave_label=label,
            current_wave=current_wave,
            signal=signal,
            confidence=confidence,
        )

    def _classify_realtime_wave(
        self, points: List[WavePoint], current_price: float, is_bull: bool
    ) -> Tuple[str, int, float]:
        """实时波浪状态判断

        基于转折点序列 + 当前价格位置，推断当前所在浪

        多头推动浪：LOW(p0)-HIGH(p1)-LOW(p2)-HIGH(p3)-LOW(p4)-HIGH(p5)
        - p0=浪1起点, p1=浪1顶/浪2起, p2=浪2底/浪3起, p3=浪3顶/浪4起,
          p4=浪4底/浪5起, p5=浪5顶

        实时状态：
        - 当前价 > p2.price（且p2是LOW）= 浪3进行中
        - 当前价 < p3.price（且p3是HIGH）= 浪4进行中
        - 当前价 > p4.price（且p4是LOW）= 浪5进行中
        - 当前价 < p5.price（且p5是HIGH）= 浪5结束/调整浪
        """
        n_pts = len(points)
        recent = points[-6:] if n_pts >= 6 else points

        # P1 修复: 在函数开头初始化 last_low/last_high，避免
        # 多头分支赋值、空头分支引用导致 UnboundLocalError:
        # "cannot access local variable 'last_low' where it is not
        # associated with a value"
        last_low = None
        last_high = None
        for p in reversed(points):
            if p.point_type == 'LOW' and last_low is None:
                last_low = p
            elif p.point_type == 'HIGH' and last_high is None:
                last_high = p
            if last_low is not None and last_high is not None:
                break

        if is_bull:
            # 多头推动浪
            if n_pts < 3:
                return ('INCOMPLETE', 0, 0.0)

            # 取最近转折点，按位置判断当前浪
            # 多头推动浪期望模式：LOW-HIGH-LOW-HIGH-LOW-HIGH
            # 但实际中转折点可能不完整，按当前可用转折点判断

            if last_low is None or last_high is None:
                return ('INCOMPLETE', 0, 0.0)

            # 检查三大规则（基于可用的转折点）
            # 多头：浪1=first_LOW→first_HIGH, 浪2=first_HIGH→second_LOW
            # 取最近的6个转折点（如果有）
            bull_pattern = ['LOW', 'HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH']
            actual_pattern = [p.point_type for p in recent]

            # 找到模式匹配的起始位置
            match_start = -1
            for offset in range(len(actual_pattern) - 5, -1, -1):
                if actual_pattern[offset:offset + 6] == bull_pattern:
                    match_start = offset
                    break

            if match_start < 0:
                # 模式不匹配，尝试3-4转折点的简化判定
                return self._classify_partial_wave(points, current_price, is_bull)

            # 完整6转折点模式匹配
            p0, p1, p2, p3, p4, p5 = recent[match_start:match_start + 6]
            wave1_height = p1.price - p0.price
            wave2_retrace = p1.price - p2.price
            wave3_height = p3.price - p2.price
            wave4_retrace = p3.price - p4.price
            wave5_height = p5.price - p4.price

            if wave1_height <= 0:
                return ('INCOMPLETE', 0, 0.0)

            rule1_ok = wave2_retrace < wave1_height * self.wave2_retrace_max
            rule3_ok = p4.price > p1.price * (1 - self.wave4_overlap_max)

            # 判定当前所在浪（基于当前价格相对位置）
            # 浪5顶=p5.price, 浪5底=p4.price, 浪4底=p4.price, 浪3顶=p3.price

            # 浪5结束（当前价 < p5.price 且 p5是最后确认的转折点）
            if current_price < p5.price and last_high.idx >= p5.idx:
                # 浪5已结束
                if rule1_ok and rule3_ok:
                    wave3_longest = wave3_height >= max(wave1_height, wave5_height)
                    conf = 0.9 if wave3_longest else 0.7
                    return ('IMPULSE_5', 5, conf)
                else:
                    return ('INCOMPLETE', 5, 0.3)

            # 浪5进行中（当前价 > p4.price 且 p5未确认）
            if current_price > p4.price and last_high.idx < p5.idx + 5:
                # 浪5进行中
                if rule1_ok:
                    return ('IMPULSE_5', 5, 0.6)
                return ('INCOMPLETE', 5, 0.3)

            # 默认返回浪5
            return ('IMPULSE_5', 5, 0.5)

        else:
            # 空头推动浪：HIGH-LOW-HIGH-LOW-HIGH-LOW
            # 保护：last_low/last_high 在函数开头已初始化，但若数据不全仍可能为 None
            if last_low is None or last_high is None:
                return ('INCOMPLETE', 0, 0.0)

            bear_pattern = ['HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH', 'LOW']
            actual_pattern = [p.point_type for p in recent]

            match_start = -1
            for offset in range(len(actual_pattern) - 5, -1, -1):
                if actual_pattern[offset:offset + 6] == bear_pattern:
                    match_start = offset
                    break

            if match_start < 0:
                return self._classify_partial_wave(points, current_price, is_bull)

            p0, p1, p2, p3, p4, p5 = recent[match_start:match_start + 6]
            wave1_height = p0.price - p1.price
            wave2_retrace = p2.price - p1.price
            wave3_height = p2.price - p3.price
            wave4_retrace = p4.price - p3.price
            wave5_height = p4.price - p5.price

            if wave1_height <= 0:
                return ('INCOMPLETE', 0, 0.0)

            rule1_ok = wave2_retrace < wave1_height * self.wave2_retrace_max
            rule3_ok = p4.price < p1.price * (1 + self.wave4_overlap_max)

            if current_price > p5.price and last_low.idx >= p5.idx:
                if rule1_ok and rule3_ok:
                    wave3_longest = wave3_height >= max(wave1_height, wave5_height)
                    conf = 0.9 if wave3_longest else 0.7
                    return ('IMPULSE_5', 5, conf)
                else:
                    return ('INCOMPLETE', 5, 0.3)

            if current_price < p4.price and last_low.idx < p5.idx + 5:
                if rule1_ok:
                    return ('IMPULSE_5', 5, 0.6)
                return ('INCOMPLETE', 5, 0.3)

            return ('IMPULSE_5', 5, 0.5)

    def _classify_partial_wave(
        self, points: List[WavePoint], current_price: float, is_bull: bool
    ) -> Tuple[str, int, float]:
        """部分转折点模式下的浪判定

        当只有3-5个转折点匹配模式时，根据当前价格位置判断
        """
        recent = points[-5:] if len(points) >= 5 else points

        if is_bull:
            # 多头：寻找 LOW-HIGH-LOW 模式
            # 浪1=LOW→HIGH, 浪2=HIGH→LOW, 浪3=LOW→current
            for i in range(len(recent) - 2):
                if (recent[i].point_type == 'LOW' and
                    recent[i+1].point_type == 'HIGH' and
                    recent[i+2].point_type == 'LOW'):
                    p0, p1, p2 = recent[i], recent[i+1], recent[i+2]
                    wave1_height = p1.price - p0.price
                    wave2_retrace = p1.price - p2.price

                    if wave1_height <= 0:
                        continue

                    rule1_ok = wave2_retrace < wave1_height * self.wave2_retrace_max
                    retrace_ratio = wave2_retrace / wave1_height

                    # 当前价 > p2.price = 浪3进行中
                    if current_price > p2.price:
                        # 浪3进行中
                        if rule1_ok and 0.3 <= retrace_ratio <= 0.8:
                            # 浪2典型回撤，浪3启动信号
                            return ('IMPULSE_5', 3, 0.7)
                        elif rule1_ok:
                            return ('IMPULSE_5', 3, 0.5)
                        else:
                            return ('INCOMPLETE', 3, 0.3)
                    else:
                        # 浪2进行中
                        if 0.3 <= retrace_ratio <= 0.8:
                            return ('IMPULSE_5', 2, 0.6)
                        return ('INCOMPLETE', 2, 0.3)

            # 寻找 LOW-HIGH-LOW-HIGH-LOW 模式（浪4结束/浪5启动）
            for i in range(len(recent) - 4):
                if (recent[i].point_type == 'LOW' and
                    recent[i+1].point_type == 'HIGH' and
                    recent[i+2].point_type == 'LOW' and
                    recent[i+3].point_type == 'HIGH' and
                    recent[i+4].point_type == 'LOW'):
                    p0, p1, p2, p3, p4 = recent[i], recent[i+1], recent[i+2], recent[i+3], recent[i+4]
                    wave1_height = p1.price - p0.price
                    wave3_height = p3.price - p2.price
                    rule3_ok = p4.price > p1.price * (1 - self.wave4_overlap_max)

                    if current_price > p4.price and rule3_ok:
                        # 浪5进行中
                        return ('IMPULSE_5', 5, 0.6)
                    elif rule3_ok:
                        return ('IMPULSE_5', 4, 0.5)
                    else:
                        return ('INCOMPLETE', 4, 0.3)

        else:
            # 空头
            for i in range(len(recent) - 2):
                if (recent[i].point_type == 'HIGH' and
                    recent[i+1].point_type == 'LOW' and
                    recent[i+2].point_type == 'HIGH'):
                    p0, p1, p2 = recent[i], recent[i+1], recent[i+2]
                    wave1_height = p0.price - p1.price
                    wave2_retrace = p2.price - p1.price

                    if wave1_height <= 0:
                        continue

                    rule1_ok = wave2_retrace < wave1_height * self.wave2_retrace_max
                    retrace_ratio = wave2_retrace / wave1_height

                    if current_price < p2.price:
                        if rule1_ok and 0.3 <= retrace_ratio <= 0.8:
                            return ('IMPULSE_5', 3, 0.7)
                        elif rule1_ok:
                            return ('IMPULSE_5', 3, 0.5)
                        else:
                            return ('INCOMPLETE', 3, 0.3)
                    else:
                        if 0.3 <= retrace_ratio <= 0.8:
                            return ('IMPULSE_5', 2, 0.6)
                        return ('INCOMPLETE', 2, 0.3)

            for i in range(len(recent) - 4):
                if (recent[i].point_type == 'HIGH' and
                    recent[i+1].point_type == 'LOW' and
                    recent[i+2].point_type == 'HIGH' and
                    recent[i+3].point_type == 'LOW' and
                    recent[i+4].point_type == 'HIGH'):
                    p0, p1, p2, p3, p4 = recent[i], recent[i+1], recent[i+2], recent[i+3], recent[i+4]
                    wave1_height = p0.price - p1.price
                    wave3_height = p2.price - p3.price
                    rule3_ok = p4.price < p1.price * (1 + self.wave4_overlap_max)

                    if current_price < p4.price and rule3_ok:
                        return ('IMPULSE_5', 5, 0.6)
                    elif rule3_ok:
                        return ('IMPULSE_5', 4, 0.5)
                    else:
                        return ('INCOMPLETE', 4, 0.3)

        return ('INCOMPLETE', 0, 0.0)

    def _generate_signal(
        self, label: str, current_wave: int, confidence: float, is_bull: bool
    ) -> str:
        """根据当前浪位置生成信号

        关键入场点：
        - 浪2结束、浪3启动：最强入场信号
        - 浪4结束、浪5启动：次强入场信号
        - 浪5结束：离场信号

        关键离场点：
        - 浪5完成：顶部离场
        """
        if label != 'IMPULSE_5':
            return 'WAIT'

        if is_bull:
            # 多头推动浪
            if current_wave == 2:
                # 浪2结束，浪3启动信号
                return 'ENTER_LONG_W3' if confidence >= 0.5 else 'WAIT'
            elif current_wave == 4:
                # 浪4结束，浪5启动信号
                return 'ENTER_LONG_W5' if confidence >= 0.5 else 'WAIT'
            elif current_wave == 5:
                # 浪5结束，离场信号
                return 'EXIT_LONG_W5' if confidence >= 0.6 else 'WAIT'
            elif current_wave == 3:
                # 浪3进行中，持有
                return 'HOLD_LONG_W3'
            else:
                return 'WAIT'
        else:
            # 空头推动浪
            if current_wave == 2:
                return 'ENTER_SHORT_W3' if confidence >= 0.5 else 'WAIT'
            elif current_wave == 4:
                return 'ENTER_SHORT_W5' if confidence >= 0.5 else 'WAIT'
            elif current_wave == 5:
                return 'EXIT_SHORT_W5' if confidence >= 0.6 else 'WAIT'
            elif current_wave == 3:
                return 'HOLD_SHORT_W3'
            else:
                return 'WAIT'

    def generate_signal_series(self, prices: pd.DataFrame) -> pd.DataFrame:
        """生成时间序列形式的波浪信号（用于回测）

        参数:
            prices: 日线OHLCV DataFrame

        返回:
            DataFrame，包含每根K线的波浪识别结果
        """
        n = len(prices)
        signals = []
        labels = []
        waves = []
        confs = []

        # 滚动识别（每根K线用之前所有数据识别当前波浪状态）
        min_window = 60  # 最小识别窗口
        for i in range(n):
            if i < min_window:
                signals.append('WAIT')
                labels.append('INCOMPLETE')
                waves.append(0)
                confs.append(0.0)
                continue

            # 用截止到当前K线的数据识别
            slice_df = prices.iloc[:i + 1]
            try:
                wave_struct = self.identify_waves(slice_df)
                signals.append(wave_struct.signal)
                labels.append(wave_struct.wave_label)
                waves.append(wave_struct.current_wave)
                confs.append(wave_struct.confidence)
            except Exception:
                signals.append('WAIT')
                labels.append('INCOMPLETE')
                waves.append(0)
                confs.append(0.0)

        return pd.DataFrame({
            'wave_signal': signals,
            'wave_label': labels,
            'current_wave': waves,
            'wave_confidence': confs,
        }, index=prices.index)


# 信号类型枚举
WAVE_SIGNALS = {
    'WAIT': '观望',
    'ENTER_LONG_W3': '浪2结束入场做多（最强）',
    'ENTER_LONG_W5': '浪4结束入场做多（次强）',
    'HOLD_LONG_W3': '持有做多（浪3进行中）',
    'EXIT_LONG_W5': '浪5结束离场做多',
    'ENTER_SHORT_W3': '浪2结束入场做空（最强）',
    'ENTER_SHORT_W5': '浪4结束入场做空（次强）',
    'HOLD_SHORT_W3': '持有做空（浪3进行中）',
    'EXIT_SHORT_W5': '浪5结束离场做空',
}
