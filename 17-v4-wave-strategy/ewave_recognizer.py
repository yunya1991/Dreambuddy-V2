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
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class WavePoint:
    """波浪转折点"""
    idx: int
    price: float
    point_type: str
    timestamp: Optional[pd.Timestamp] = None


@dataclass
class WaveStructure:
    """识别出的波浪结构"""
    waves: List[WavePoint]
    wave_label: str
    current_wave: int
    signal: str
    confidence: float


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
        wave2_retrace_max: float = 1.0,
        wave3_min_ratio: float = 0.382,
        wave4_overlap_max: float = 0.0,
    ):
        self.zigzag_threshold = zigzag_threshold
        self.fractal_window = fractal_window
        self.min_wave_points = min_wave_points
        self.wave2_retrace_max = wave2_retrace_max
        self.wave3_min_ratio = wave3_min_ratio
        self.wave4_overlap_max = wave4_overlap_max

    def _compute_zigzag(self, highs: np.ndarray, lows: np.ndarray) -> List[WavePoint]:
        """ZigZag算法识别转折点"""
        n = len(highs)
        if n < 5:
            return []

        points = []
        trend = 0
        last_extreme_idx = 0
        last_extreme_price = highs[0] if highs[0] > lows[0] else lows[0]

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

        for i in range(last_extreme_idx + 1, n):
            if trend == 1:
                if highs[i] > last_extreme_price:
                    last_extreme_price = highs[i]
                    last_extreme_idx = i
                retrace = (last_extreme_price - lows[i]) / last_extreme_price
                if retrace >= self.zigzag_threshold:
                    points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='HIGH'))
                    trend = -1
                    last_extreme_price = lows[i]
                    last_extreme_idx = i
            else:
                if lows[i] < last_extreme_price:
                    last_extreme_price = lows[i]
                    last_extreme_idx = i
                retrace = (highs[i] - last_extreme_price) / last_extreme_price
                if retrace >= self.zigzag_threshold:
                    points.append(WavePoint(idx=last_extreme_idx, price=last_extreme_price, point_type='LOW'))
                    trend = 1
                    last_extreme_price = highs[i]
                    last_extreme_idx = i

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
        """用分形确认转折点（过滤噪声）"""
        if not points:
            return points

        w = self.fractal_window
        confirmed = []
        for p in points:
            i = p.idx
            if i < w or i >= len(highs) - w:
                confirmed.append(p)
                continue

            if p.point_type == 'HIGH':
                is_fractal = True
                for j in range(i - w, i + w + 1):
                    if j == i:
                        continue
                    if highs[j] >= highs[i]:
                        is_fractal = False
                        break
                if is_fractal:
                    confirmed.append(p)
            else:
                is_fractal = True
                for j in range(i - w, i + w + 1):
                    if j == i:
                        continue
                    if lows[j] <= lows[i]:
                        is_fractal = False
                        break
                if is_fractal:
                    confirmed.append(p)

        if len(confirmed) < self.min_wave_points // 2:
            return points
        return confirmed

    def _classify_impulse_wave(
        self, points: List[WavePoint], is_bull: bool = True
    ) -> Tuple[str, int, float]:
        """判定五浪推动结构"""
        if len(points) < self.min_wave_points:
            return ('INCOMPLETE', 0, 0.0)

        recent = points[-6:]
        if is_bull:
            expected_pattern = ['LOW', 'HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH']
        else:
            expected_pattern = ['HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH', 'LOW']

        actual_pattern = [p.point_type for p in recent]
        if actual_pattern != expected_pattern:
            return ('INCOMPLETE', 0, 0.0)

        if is_bull:
            p0, p1, p2, p3, p4, p5 = recent
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
            wave1_high = p1.price
            wave4_low = p4.price

        if wave1_height <= 0:
            return ('INCOMPLETE', 0, 0.0)

        rule1_ok = wave2_retrace < wave1_height * self.wave2_retrace_max
        wave3_min_ok = wave3_height >= wave1_height * self.wave3_min_ratio
        if is_bull:
            rule3_ok = wave4_low > wave1_high * (1 - self.wave4_overlap_max)
        else:
            rule3_ok = wave4_low < wave1_high * (1 + self.wave4_overlap_max)

        rules_passed = sum([rule1_ok, rule3_ok])
        confidence = 0.0

        if wave5_height > 0:
            if rule1_ok and rule3_ok and wave3_min_ok:
                wave3_longest = wave3_height >= max(wave1_height, wave5_height)
                if wave3_longest:
                    confidence = 0.9
                else:
                    confidence = 0.7
                return ('IMPULSE_5', 5, confidence)
            else:
                return ('INCOMPLETE', 5, 0.3)

        if wave3_height > 0 and wave4_retrace > 0:
            if rule1_ok and rule3_ok:
                return ('IMPULSE_5', 4, 0.7)
            else:
                return ('INCOMPLETE', 4, 0.3)

        if wave3_height > 0:
            if rule1_ok:
                wave3_strength = wave3_height / wave1_height
                if wave3_strength >= 1.0:
                    confidence = 0.85
                elif wave3_strength >= 0.618:
                    confidence = 0.7
                else:
                    confidence = 0.5
                return ('IMPULSE_5', 3, confidence)
            else:
                return ('INCOMPLETE', 3, 0.3)

        if wave2_retrace > 0:
            retrace_ratio = wave2_retrace / wave1_height
            if 0.3 <= retrace_ratio <= 0.8:
                return ('IMPULSE_5', 2, 0.6)
            else:
                return ('INCOMPLETE', 2, 0.3)

        return ('IMPULSE_5', 1, 0.4)

    def identify_waves(self, prices: pd.DataFrame) -> WaveStructure:
        """识别波浪结构（含实时状态判断）"""
        highs = prices['high'].values
        lows = prices['low'].values
        closes = prices['close'].values
        current_price = float(closes[-1]) if len(closes) > 0 else 0.0

        points = self._compute_zigzag(highs, lows)
        points = self._confirm_with_fractals(points, highs, lows)

        if len(points) < 3:
            return WaveStructure(
                waves=points, wave_label='INCOMPLETE',
                current_wave=0, signal='WAIT', confidence=0.0
            )

        last_point = points[-1]
        recent = points[-6:] if len(points) >= 6 else points

        if len(recent) >= 2:
            if recent[-2].point_type == 'LOW' and recent[-1].point_type == 'HIGH':
                is_bull = True
            elif recent[-2].point_type == 'HIGH' and recent[-1].point_type == 'LOW':
                is_bull = False
            else:
                is_bull = True
        else:
            is_bull = True

        label, current_wave, confidence = self._classify_realtime_wave(
            points, current_price, is_bull
        )

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
        """实时波浪状态判断"""
        n_pts = len(points)
        recent = points[-6:] if n_pts >= 6 else points

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
            if n_pts < 3:
                return ('INCOMPLETE', 0, 0.0)

            if last_low is None or last_high is None:
                return ('INCOMPLETE', 0, 0.0)

            bull_pattern = ['LOW', 'HIGH', 'LOW', 'HIGH', 'LOW', 'HIGH']
            actual_pattern = [p.point_type for p in recent]

            match_start = -1
            for offset in range(len(actual_pattern) - 5, -1, -1):
                if actual_pattern[offset:offset + 6] == bull_pattern:
                    match_start = offset
                    break

            if match_start < 0:
                return self._classify_partial_wave(points, current_price, is_bull)

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

            if current_price < p5.price and last_high.idx >= p5.idx:
                if rule1_ok and rule3_ok:
                    wave3_longest = wave3_height >= max(wave1_height, wave5_height)
                    conf = 0.9 if wave3_longest else 0.7
                    return ('IMPULSE_5', 5, conf)
                else:
                    return ('INCOMPLETE', 5, 0.3)

            if current_price > p4.price and last_high.idx < p5.idx + 5:
                if rule1_ok:
                    return ('IMPULSE_5', 5, 0.6)
                return ('INCOMPLETE', 5, 0.3)

            return ('IMPULSE_5', 5, 0.5)

        else:
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
        """部分转折点模式下的浪判定"""
        recent = points[-5:] if len(points) >= 5 else points

        if is_bull:
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

                    if current_price > p2.price:
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
                        return ('IMPULSE_5', 5, 0.6)
                    elif rule3_ok:
                        return ('IMPULSE_5', 4, 0.5)
                    else:
                        return ('INCOMPLETE', 4, 0.3)

        else:
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
        """根据当前浪位置生成信号"""
        if label != 'IMPULSE_5':
            return 'WAIT'

        if is_bull:
            if current_wave == 2:
                return 'ENTER_LONG_W3' if confidence >= 0.5 else 'WAIT'
            elif current_wave == 4:
                return 'ENTER_LONG_W5' if confidence >= 0.5 else 'WAIT'
            elif current_wave == 5:
                return 'EXIT_LONG_W5' if confidence >= 0.6 else 'WAIT'
            elif current_wave == 3:
                return 'HOLD_LONG_W3'
            else:
                return 'WAIT'
        else:
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
        """生成时间序列形式的波浪信号（用于回测）"""
        n = len(prices)
        signals = []
        labels = []
        waves = []
        confs = []

        min_window = 60
        for i in range(n):
            if i < min_window:
                signals.append('WAIT')
                labels.append('INCOMPLETE')
                waves.append(0)
                confs.append(0.0)
                continue

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
