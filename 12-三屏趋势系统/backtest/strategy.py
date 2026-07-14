"""三屏趋势系统 — 策略基类与三屏策略包装器

将三屏趋势系统包装为回测可用的策略类。
策略的职责：根据历史数据，生成每个时间点的目标仓位。
"""

from typing import Dict, Optional, List
import pandas as pd
import numpy as np


class BaseStrategy:
    """策略基类

    子类需要实现 generate_signals() 方法，
    返回目标仓位序列（-1~1，正=多，负=空）。
    """

    def __init__(self, name: str = "base_strategy"):
        self.name = name

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """
        根据价格数据生成目标仓位信号

        参数:
            prices: OHLCV DataFrame

        返回:
            position_sizes: 目标仓位比例序列（-1~1）
        """
        raise NotImplementedError("子类必须实现 generate_signals()")


class BuyAndHoldStrategy(BaseStrategy):
    """买入持有策略（基准）"""

    def __init__(self):
        super().__init__(name="buy_and_hold")

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        position = pd.Series(1.0, index=prices.index)
        return position


class MovingAverageStrategy(BaseStrategy):
    """双均线趋势策略（基准对比）"""

    def __init__(self, fast_window: int = 20, slow_window: int = 200):
        super().__init__(name=f"ma_{fast_window}_{slow_window}")
        self.fast_window = fast_window
        self.slow_window = slow_window

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        close = prices["close"]

        ma_fast = close.rolling(self.fast_window).mean()
        ma_slow = close.rolling(self.slow_window).mean()

        position = pd.Series(0.0, index=prices.index)
        position[ma_fast > ma_slow] = 1.0
        position[ma_fast < ma_slow] = -1.0

        position.iloc[:self.slow_window] = 0.0

        return position


class TrendScreenStrategy(BaseStrategy):
    """三屏趋势系统策略包装器

    将三屏趋势系统包装为回测策略：
    - 使用日线数据生成趋势信号
    - 置信度映射为仓位大小
    - 支持仅趋势模式（忽略Freqtrade信号）
    """

    def __init__(
        self,
        use_freqtrade: bool = False,
        max_position: float = 1.0,
        min_confidence: float = 45.0,
        trial_confidence: float = 55.0,
        trial_position_ratio: float = 0.3,
        require_consistent: bool = False,
        warmup_periods: int = 50,
        update_step: int = 1,
        calibration: Optional[float] = None,
        calibration_method: str = "platt",
        use_counter_indicators: bool = True,
        use_risk_control: bool = True,
        initial_capital: float = 10000.0,
    ):
        """
        参数:
            use_freqtrade: 是否使用Freqtrade入场信号（回测中默认False）
            max_position: 最大仓位比例
            min_confidence: 最低置信度阈值（低于此值不持仓）
            trial_confidence: 试探仓位置信度阈值（趋势不一致时，达到此值可轻仓）
            trial_position_ratio: 试探仓位比例（相对max_position的比率）
            require_consistent: 是否强制要求趋势一致才开仓（默认False，允许试探）
            warmup_periods: 预热周期（默认50，自适应数据量）
            update_step: 信号更新步长（每N天更新一次，默认1；趋势策略可用7提速）
            calibration: 置信度校准参数，(A, B) for Platt，或None表示不校准
            calibration_method: 校准方法 "platt"
            use_counter_indicators: 是否启用反方指标（Phase 2）
            use_risk_control: 是否启用极端行情风控（Phase 2）
            initial_capital: 初始资金（风控计算用）
        """
        super().__init__(name="trend_screen")
        self.use_freqtrade = use_freqtrade
        self.max_position = max_position
        self.min_confidence = min_confidence
        self.trial_confidence = trial_confidence
        self.trial_position_ratio = trial_position_ratio
        self.require_consistent = require_consistent
        self.warmup_periods = warmup_periods
        self.update_step = max(1, update_step)
        self.calibration = calibration  # (A, B) tuple for Platt scaling
        self.calibration_method = calibration_method
        self.use_counter_indicators = use_counter_indicators
        self.use_risk_control = use_risk_control
        self.initial_capital = initial_capital

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """
        生成三屏趋势策略的仓位信号

        参数:
            prices: 日线 OHLCV DataFrame

        返回:
            目标仓位比例序列
        """
        try:
            from core import (
                calc_trend_consistency,
                calc_bayesian_confidence,
                calc_classic_indicator_confidence,
            )
            from core.fusion import fuse_technical_fundamental
        except ImportError:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from core import (
                calc_trend_consistency,
                calc_bayesian_confidence,
                calc_classic_indicator_confidence,
            )
            from core.fusion import fuse_technical_fundamental

        n = len(prices)
        positions = np.zeros(n)
        directions = ["NEUTRAL"] * n
        confidences = np.zeros(n)
        trend_consistent_flags = np.zeros(n, dtype=bool)

        warmup = min(self.warmup_periods, n - 10)
        step = max(1, self.update_step)

        last_pos = 0.0
        last_dir = "NEUTRAL"
        last_conf = 0.0
        last_consistent = False

        for i in range(warmup, n):
            if (i - warmup) % step == 0 or i == warmup:
                daily_slice = prices.iloc[:i + 1].copy()
                weekly_df = self._resample_to_weekly(daily_slice)

                if len(weekly_df) >= 10:
                    try:
                        trend_consistency = calc_trend_consistency(weekly_df, daily_slice)
                        bayesian_conf = calc_bayesian_confidence(weekly_df, daily_slice)

                        direction = bayesian_conf["direction"]
                        confidence = self._calibrate_confidence(bayesian_conf["confidence"])
                        is_consistent = trend_consistency["consistent"]

                        pos = self._confidence_to_position(direction, confidence, is_consistent)
                        last_pos = pos
                        last_dir = direction
                        last_conf = confidence
                        last_consistent = is_consistent
                    except Exception:
                        pass

            positions[i] = last_pos
            directions[i] = last_dir
            confidences[i] = last_conf
            trend_consistent_flags[i] = last_consistent

        signals = pd.Series(positions, index=prices.index, name="position")

        # Phase 2.1: 反方指标调整
        if self.use_counter_indicators:
            signals = self._apply_counter_indicators(signals, prices)

        # Phase 2.3: 极端行情风控
        if self.use_risk_control:
            signals = self._apply_risk_control(signals, prices)

        return signals

    def _apply_counter_indicators(self, signals: pd.Series, prices: pd.DataFrame) -> pd.Series:
        """应用反方指标调整仓位

        反方指标与趋势方向相反时，降低仓位（对冲确认偏误）
        """
        try:
            from core.indicators import calc_indicator_dynamics
            from core.config import COUNTER_INDICATORS
        except ImportError:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from core.indicators import calc_indicator_dynamics
            from core.config import COUNTER_INDICATORS

        adjusted = signals.copy()
        warmup = min(self.warmup_periods, len(prices) - 10)
        step = max(1, self.update_step)

        for i in range(warmup, len(prices)):
            if (i - warmup) % step != 0 and i != warmup:
                continue

            pos = signals.iloc[i]
            if abs(pos) < 0.01:
                continue

            daily_slice = prices.iloc[:i + 1]
            counter_votes = 0
            total_counters = 0

            for ind_name in COUNTER_INDICATORS:
                try:
                    dyn = calc_indicator_dynamics(daily_slice, ind_name)
                    total_counters += 1
                    if pos > 0 and dyn["direction"] == "BEAR":
                        counter_votes += 1
                    elif pos < 0 and dyn["direction"] == "BULL":
                        counter_votes += 1
                except Exception:
                    pass

            if total_counters > 0 and counter_votes > 0:
                # 反方指标越多，仓位降得越多
                counter_ratio = counter_votes / total_counters
                # 最多降50%仓位
                reduction = min(counter_ratio * 0.5, 0.5)
                adjusted.iloc[i] = pos * (1 - reduction)

        return adjusted

    def _apply_risk_control(self, signals: pd.Series, prices: pd.DataFrame) -> pd.Series:
        """应用极端行情风控"""
        try:
            from core.risk_control import apply_risk_control
        except ImportError:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from core.risk_control import apply_risk_control

        try:
            adjusted, events = apply_risk_control(signals, prices, self.initial_capital)
            if events:
                print(f"  [风控] 触发{len(events)}次风控事件")
            return adjusted
        except Exception:
            return signals

    def _resample_to_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """将日线数据重采样为周线"""
        if len(daily_df) == 0:
            return daily_df

        if "date" in daily_df.columns:
            df = daily_df.set_index("date")
        else:
            df = daily_df.copy()

        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        return weekly.reset_index(drop=False) if "date" not in daily_df.columns else weekly

    def _calibrate_confidence(self, confidence: float) -> float:
        """对置信度进行Platt校准

        校准公式: calibrated = sigmoid(A * raw/100 + B) * 100
        """
        if self.calibration is None:
            return confidence

        try:
            A, B = self.calibration
            c = min(max(confidence, 0), 100) / 100.0
            import math
            calibrated = 1.0 / (1.0 + math.exp(-(A * c + B)))
            return calibrated * 100.0
        except Exception:
            return confidence

    def _confidence_to_position(
        self, direction: str, confidence: float, trend_consistent: bool
    ) -> float:
        """根据方向、置信度、趋势一致性计算仓位

        仓位逻辑：
        1. 趋势一致 + 置信度≥min_confidence → 正常仓位
        2. 趋势不一致 + 置信度≥trial_confidence → 试探仓位（轻仓）
        3. 其他 → 空仓
        """
        if direction == "NEUTRAL":
            return 0.0

        if trend_consistent:
            if confidence < self.min_confidence:
                return 0.0
            position_ratio = min(confidence / 100.0, 1.0) * self.max_position
        else:
            if self.require_consistent:
                return 0.0
            if confidence < self.trial_confidence:
                return 0.0
            position_ratio = (
                min(confidence / 100.0, 1.0)
                * self.max_position
                * self.trial_position_ratio
            )

        if direction == "BULL":
            return position_ratio
        elif direction == "BEAR":
            return -position_ratio
        else:
            return 0.0
