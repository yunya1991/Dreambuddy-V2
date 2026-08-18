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

    @staticmethod
    def train_calibration(
        prices: pd.DataFrame,
        lookahead: int = 7,
        method: str = "platt",
        warmup_periods: int = 50,
        **strategy_kwargs,
    ) -> tuple:
        """
        从历史数据训练置信度校准参数

        参数:
            prices: OHLCV DataFrame
            lookahead: 预测前瞻天数
            method: 校准方法 "platt" 或 "isotonic"
            warmup_periods: 预热周期
            **strategy_kwargs: 策略其他参数

        返回:
            (calibration_params, ece_before, ece_after)
            calibration_params: Platt的(A,B)元组，或isotonic的校准函数
        """
        from backtest.calibration import (
            collect_calibration_data,
            platt_scaling,
            isotonic_calibration,
            calculate_ece,
        )

        strategy = TrendScreenStrategy(
            warmup_periods=warmup_periods,
            calibration=None,
            **strategy_kwargs,
        )

        cal_data = collect_calibration_data(prices, strategy, lookahead=lookahead)
        confidences = cal_data["confidences"]
        outcomes = cal_data["outcomes"]

        if len(confidences) < 20:
            return (None, 0, 0)

        ece_before = calculate_ece(confidences, outcomes)["ece"]

        if method == "platt":
            calibrate_func, params = platt_scaling(confidences, outcomes)
            calibrated_confs = calibrate_func(confidences)
            ece_after = calculate_ece(calibrated_confs, outcomes)["ece"]
            return ((params["A"], params["B"]), ece_before, ece_after)
        else:
            calibrate_func, params = isotonic_calibration(confidences, outcomes)
            calibrated_confs = calibrate_func(confidences)
            ece_after = calculate_ece(calibrated_confs, outcomes)["ece"]
            return (calibrate_func, ece_before, ece_after)

    @classmethod
    def with_calibration(
        cls,
        prices: pd.DataFrame,
        lookahead: int = 7,
        method: str = "platt",
        warmup_periods: int = 50,
        **kwargs,
    ) -> "TrendScreenStrategy":
        """
        创建一个已训练好校准参数的策略实例

        参数:
            prices: 用于训练校准的历史数据
            lookahead: 预测前瞻天数
            method: 校准方法
            warmup_periods: 预热周期
            **kwargs: 策略其他参数

        返回:
            TrendScreenStrategy 实例（已配置校准参数）
        """
        cal_params, ece_before, ece_after = cls.train_calibration(
            prices,
            lookahead=lookahead,
            method=method,
            warmup_periods=warmup_periods,
            **{k: v for k, v in kwargs.items() if k not in ['calibration', 'calibration_method']},
        )

        strategy = cls(
            warmup_periods=warmup_periods,
            calibration=cal_params,
            calibration_method=method,
            **kwargs,
        )
        strategy._ece_before = ece_before
        strategy._ece_after = ece_after
        return strategy

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


class FullReasoningStrategy(BaseStrategy):
    """完整推理算法策略包装器

    与 TrendScreenStrategy 的差异：
    - 使用 engine.compute_trend_signal_from_dataframes() 完整推理链
    - 包含 BTC 风向标闸门（宏观方向过滤器，最高优先级）
    - 包含 five_algo_decision 完整决策逻辑（趋势一致+Freqtrade同向→入场）
    - 可选启用 LightGBM 集成推理（algo_ensemble.predict_ensemble）

    设计原则：低级策略不能影响高级算法。
    本策略只使用三屏推理算法的完整输出，不混入简单模式等低级回退。
    """

    def __init__(
        self,
        use_wind_vane: bool = True,
        use_ensemble: bool = False,
        max_position: float = 0.60,
        warmup_periods: int = 210,
        update_step: int = 1,
        symbol: str = "BTC",
        is_btc: bool = True,
        require_freqtrade: bool = False,
        fallback_confidence_threshold: float = 70.0,
        btc_prices: Optional[pd.DataFrame] = None,
        use_btc_direction_filter: bool = True,
        use_fundamental: Optional[bool] = None,
    ):
        """
        参数:
            use_wind_vane: 是否启用 BTC 风向标闸门（MA128/MA200 宏观过滤）
            use_ensemble: 是否启用 LightGBM 集成推理（需先训练模型）
            max_position: 最大仓位上限（覆盖算法输出）
            warmup_periods: 预热周期（默认210，覆盖周线MA200需求）
            update_step: 信号更新步长（1=每日，7=每周更新一次提速）
            symbol: 回测标的符号
            is_btc: 是否为BTC币种（影响风向标数据源）
            require_freqtrade: 是否强制要求Freqtrade信号（回测中通常False，缺失时降级到置信度≥70%）
            fallback_confidence_threshold: Freqtrade缺失时的降级入场阈值
            btc_prices: BTC 日线数据 DataFrame（非 BTC 币种趋势跟随过滤用）
            use_btc_direction_filter: 是否启用 BTC 趋势方向过滤（非 BTC 币种跟随 BTC 方向）
        """
        super().__init__(name="full_reasoning")
        self.use_wind_vane = use_wind_vane
        self.use_ensemble = use_ensemble
        self.max_position = max_position
        self.warmup_periods = warmup_periods
        self.update_step = max(1, update_step)
        self.symbol = symbol
        self.is_btc = is_btc
        self.require_freqtrade = require_freqtrade
        self.fallback_confidence_threshold = fallback_confidence_threshold
        self.btc_prices = btc_prices
        self.use_btc_direction_filter = use_btc_direction_filter
        self.use_fundamental = use_fundamental if use_fundamental is not None else True  # 默认启用基本面

        # 统计计数器
        self.stats = {
            "total_bars": 0,
            "enter_long": 0,
            "enter_short": 0,
            "wait": 0,
            "wind_vane_blocked": 0,          # 硬拦截
            "wind_vane_soft_blocked": 0,    # P0: 软拦截
            "reversal_trial": 0,            # P0: 逆转轻仓试探入场
            "strong_consistent": 0,         # P0: 强一致入场
            "dynamic_timing_entry": 0,     # P1: 动态时机入场
            # P2: 趋势阶段统计
            "phase_early": 0,
            "phase_accelerating": 0,
            "phase_maturing": 0,
            "phase_reversing": 0,
            "phase_unknown": 0,
            "phase_adjusted": 0,
            # P2-v2: Elder-ray 背离统计
            "elder_bull_divergence": 0,
            "elder_bear_divergence": 0,
            "elder_divergence_entry": 0,
            "trend_inconsistent": 0,
            "neutral": 0,
            "no_freqtrade_fallback": 0,
            "ensemble_used": 0,
            "ensemble_fallback": 0,
            "btc_direction_blocked": 0,  # BTC趋势方向过滤拦截
        }

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """生成完整推理算法的仓位信号

        遍历每个时间点，构造历史切片，调用完整推理链。
        """
        try:
            from engine import compute_trend_signal_from_dataframes
            import engine as engine_module
        except ImportError:
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from engine import compute_trend_signal_from_dataframes
            import engine as engine_module

        # 可选：LightGBM 集成推理
        ensemble_predict = None
        if self.use_ensemble:
            try:
                from ml.algo_ensemble import predict_ensemble
                ensemble_predict = predict_ensemble
            except Exception:
                print("  [警告] LightGBM 集成推理模块不可用，将仅使用五大算法")
                self.use_ensemble = False

        # 临时切换 BTC 风向标全局开关
        original_wv_enabled = engine_module.BTC_WIND_VANE_ENABLED
        if not self.use_wind_vane:
            engine_module.BTC_WIND_VANE_ENABLED = False

        try:
            return self._run_backtest(prices, compute_trend_signal_from_dataframes, ensemble_predict)
        finally:
            engine_module.BTC_WIND_VANE_ENABLED = original_wv_enabled

    def _run_backtest(self, prices, compute_func, ensemble_predict):
        """执行回测主循环"""
        n = len(prices)
        positions = np.zeros(n)
        actions = ["WAIT"] * n
        confidences = np.zeros(n)
        directions = ["NEUTRAL"] * n

        warmup = min(self.warmup_periods, n - 10)
        step = max(1, self.update_step)

        last_pos = 0.0
        last_action = "WAIT"
        last_conf = 0.0
        last_dir = "NEUTRAL"

        # ── BTC 趋势方向预计算（非 BTC 币种趋势跟随过滤用）──
        btc_directions_cache = {}  # {bar_idx: "BULL"/"BEAR"/"NEUTRAL"}
        if self.use_btc_direction_filter and not self.is_btc and self.btc_prices is not None:
            btc_n = len(self.btc_prices)
            btc_warmup = min(self.warmup_periods, btc_n - 10)
            for bi in range(btc_warmup, btc_n):
                if (bi - btc_warmup) % step == 0 or bi == btc_warmup:
                    btc_daily = self.btc_prices.iloc[:bi + 1].copy()
                    btc_weekly = self._resample_to_weekly(btc_daily)
                    if len(btc_weekly) >= 30:
                        try:
                            btc_result = compute_func(
                                weekly_df=btc_weekly,
                                daily_df=btc_daily,
                                symbol="BTC",
                                price=float(btc_daily["close"].iloc[-1]),
                                fundamental_data=None,
                                freqtrade_signals=None,
                                is_btc=True,
                                btc_daily_df=btc_daily,
                                btc_weekly_df=btc_weekly,
                                btc_trend_direction=None,
                            )
                            btc_fs = btc_result.get("final_signal", {})
                            btc_directions_cache[bi] = btc_fs.get("direction", "NEUTRAL")
                        except Exception:
                            btc_directions_cache[bi] = "NEUTRAL"

        for i in range(warmup, n):
            if (i - warmup) % step == 0 or i == warmup:
                daily_slice = prices.iloc[:i + 1].copy()
                weekly_slice = self._resample_to_weekly(daily_slice)

                if len(weekly_slice) >= 30:
                    try:
                        # 获取当前 BTC 趋势方向（用于非 BTC 币种过滤）
                        current_btc_dir = None
                        if self.use_btc_direction_filter and not self.is_btc:
                            current_btc_dir = btc_directions_cache.get(i, None)

                        result = compute_func(
                            weekly_df=weekly_slice,
                            daily_df=daily_slice,
                            symbol=self.symbol,
                            price=float(daily_slice["close"].iloc[-1]),
                            fundamental_data=None,
                            freqtrade_signals=None,
                            is_btc=self.is_btc,
                            btc_daily_df=daily_slice if self.is_btc else None,
                            btc_weekly_df=weekly_slice if self.is_btc else None,
                            btc_trend_direction=current_btc_dir,
                            use_fundamental=self.use_fundamental,
                        )

                        fs = result.get("final_signal", {})
                        action = fs.get("action", "WAIT")
                        conf = float(fs.get("confidence", 0))
                        direction = fs.get("direction", "NEUTRAL")
                        pos_pct = float(fs.get("position", {}).get("position_pct", 0))
                        wv_blocked = fs.get("wind_vane_blocked", False)

                        # 可选：用 LightGBM 集成推理覆盖决策
                        if self.use_ensemble and not wv_blocked and direction != "NEUTRAL":
                            try:
                                ens = ensemble_predict(result)
                                if ens.get("source") == "ensemble":
                                    self.stats["ensemble_used"] += 1
                                    ens_dir = ens["direction"]
                                    ens_conf = ens["confidence"]
                                    # 集成推理方向与五大算法一致时，使用集成置信度
                                    if ens_dir == direction:
                                        conf = max(conf, ens_conf)
                                        if ens_conf >= 60 and action == "WAIT":
                                            # 集成推理置信度足够，允许入场（仅当无Freqtrade要求时）
                                            if not self.require_freqtrade:
                                                action = "ENTER_LONG" if ens_dir == "BULL" else "ENTER_SHORT"
                                                pos_pct = max(pos_pct, 0.15)
                                else:
                                    self.stats["ensemble_fallback"] += 1
                            except Exception:
                                self.stats["ensemble_fallback"] += 1

                        # 映射 action → 目标仓位
                        if action == "ENTER_LONG":
                            target_pos = min(pos_pct, self.max_position)
                        elif action == "ENTER_SHORT":
                            target_pos = -min(pos_pct, self.max_position)
                        else:
                            target_pos = 0.0

                        last_pos = target_pos
                        last_action = action
                        last_conf = conf
                        last_dir = direction

                        # 统计计数
                        self.stats["total_bars"] += 1
                        if action == "ENTER_LONG":
                            self.stats["enter_long"] += 1
                        elif action == "ENTER_SHORT":
                            self.stats["enter_short"] += 1
                        else:
                            self.stats["wait"] += 1
                        if wv_blocked:
                            self.stats["wind_vane_blocked"] += 1
                        # P0 新增统计
                        if fs.get("wind_vane_soft_blocked", False):
                            self.stats["wind_vane_soft_blocked"] += 1
                        if fs.get("reversal_trial", False):
                            self.stats["reversal_trial"] += 1
                        if fs.get("consistency_level") == "STRONG_CONSISTENT":
                            self.stats["strong_consistent"] += 1
                        # P1 新增统计
                        if fs.get("dynamic_timing_entry", False):
                            self.stats["dynamic_timing_entry"] += 1
                        # P2 新增统计：趋势阶段
                        phase = fs.get("trend_phase", "UNKNOWN")
                        if phase == "EARLY":
                            self.stats["phase_early"] += 1
                        elif phase == "ACCELERATING":
                            self.stats["phase_accelerating"] += 1
                        elif phase == "MATURING":
                            self.stats["phase_maturing"] += 1
                        elif phase == "REVERSING":
                            self.stats["phase_reversing"] += 1
                        else:
                            self.stats["phase_unknown"] += 1
                        if fs.get("phase_adjusted", False):
                            self.stats["phase_adjusted"] += 1
                        # P2-v2: Elder-ray 背离统计
                        er = fs.get("elder_ray", {})
                        if er and er.get("bear_divergence", {}).get("detected", False):
                            self.stats["elder_bull_divergence"] += 1
                        if er and er.get("bull_divergence", {}).get("detected", False):
                            self.stats["elder_bear_divergence"] += 1
                        if fs.get("elder_ray_divergence_entry", False):
                            self.stats["elder_divergence_entry"] += 1
                        if fs.get("btc_direction_blocked", False):
                            self.stats["btc_direction_blocked"] += 1
                        if not fs.get("trend_consistent", False):
                            self.stats["trend_inconsistent"] += 1
                        if direction == "NEUTRAL":
                            self.stats["neutral"] += 1
                        # 检测降级入场（无Freqtrade信号但置信度≥70%）
                        decision_reason = fs.get("decision_reason", "")
                        if "降级入场" in decision_reason:
                            self.stats["no_freqtrade_fallback"] += 1

                    except Exception:
                        pass

            positions[i] = last_pos
            actions[i] = last_action
            confidences[i] = last_conf
            directions[i] = last_dir

        signals = pd.Series(positions, index=prices.index, name="position")
        self._actions = actions
        self._confidences = confidences
        self._directions = directions
        return signals

    def _resample_to_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """将日线数据重采样为周线"""
        if len(daily_df) == 0:
            return daily_df

        df = daily_df.copy()
        if "date" in df.columns:
            df = df.set_index("date")
        else:
            df.index = pd.to_datetime(df.index)

        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        return weekly

    def get_stats(self) -> dict:
        """获取回测统计信息"""
        return self.stats.copy()


class LeastResistanceStrategy(BaseStrategy):
    """纯最小阻力方向策略（第一性原理）

    绕过 calc_trend_consistency 的完整推理链，
    直接用 compute_least_resistance_3d 的 D/V/A 模型生成仓位。

    时间三维 × 五维阻力 → 最小阻力三维模型 → 方向 + 入场信号
    - 周线定方向（Direction）
    - 日线定时机（Velocity）
    - 小周期精细入场（Acceleration）
    - 量变积累→质变突破：提前推理方向
    """

    def __init__(
        self,
        max_position: float = 0.60,
        min_confidence: float = 40.0,
        trial_confidence: float = 25.0,
        trial_position_ratio: float = 0.3,
        warmup_periods: int = 80,
        update_step: int = 1,
        use_fundamental: bool = False,
        min_holding_bars: int = 5,
        signal_confirm_bars: int = 2,
        enable_trend_filter: bool = True,
        bear_short_only: bool = True,
        bull_long_only: bool = False,
    ):
        super().__init__(name="least_resistance")
        self.max_position = max_position
        self.min_confidence = min_confidence
        self.trial_confidence = trial_confidence
        self.trial_position_ratio = trial_position_ratio
        self.warmup_periods = warmup_periods
        self.update_step = max(1, update_step)
        self.use_fundamental = use_fundamental
        self.min_holding_bars = max(1, min_holding_bars)
        self.signal_confirm_bars = max(1, signal_confirm_bars)
        self.enable_trend_filter = enable_trend_filter
        self.bear_short_only = bear_short_only
        self.bull_long_only = bull_long_only
        self.stats = {
            "total_bars": 0,
            "must_enter": 0,
            "timing": 0,
            "wait": 0,
            "accumulation": 0,
            "breakthrough_imminent": 0,
            "breakthrough_confirmed": 0,
            "continuation": 0,
            "late_continuation": 0,
            "accumulation_mode": 0,
            "weakening": 0,
            "trend_filter_blocks": 0,
            "holding_wait": 0,
            "confirm_wait": 0,
        }

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        try:
            from core.least_resistance import compute_least_resistance_3d
        except ImportError:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from core.least_resistance import compute_least_resistance_3d

        n = len(prices)
        positions = np.zeros(n)
        warmup = min(self.warmup_periods, n - 10)
        step = max(1, self.update_step)

        history_3d = []
        daily_history_diffs = []
        last_pos = 0.0

        ma200 = prices["close"].rolling(window=200, min_periods=200).mean().values
        ma50 = prices["close"].rolling(window=50, min_periods=50).mean().values
        weekly_ma20 = prices["close"].rolling(window=20, min_periods=20).mean().values

        signal_buffer = []
        holding_count = 0
        holding_direction = "NEUTRAL"

        for i in range(warmup, n):
            if (i - warmup) % step == 0 or i == warmup:
                daily_slice = prices.iloc[:i + 1].copy()
                weekly_df = self._resample_to_weekly(daily_slice)

                if len(weekly_df) >= 10:
                    try:
                        result = compute_least_resistance_3d(
                            weekly_df, daily_slice,
                            daily_history_diffs=daily_history_diffs if daily_history_diffs else None,
                            history_3d=history_3d if history_3d else None,
                        )

                        direction = result["direction"]
                        confidence = result["confidence"]
                        entry_signal = result["entry_signal"]
                        daily_diff = result.get("daily_diff", 0.0)

                        daily_history_diffs.append(daily_diff)
                        if len(daily_history_diffs) > 30:
                            daily_history_diffs = daily_history_diffs[-30:]

                        history_3d.append({
                            "direction": direction,
                            "velocity": result["velocity"],
                            "acceleration": result["acceleration"],
                        })
                        if len(history_3d) > 20:
                            history_3d = history_3d[-20:]

                        signal_buffer.append(direction)
                        if len(signal_buffer) > self.signal_confirm_bars:
                            signal_buffer = signal_buffer[-self.signal_confirm_bars:]

                        if holding_count > 0:
                            holding_count -= 1
                            if holding_count == 0:
                                holding_direction = "NEUTRAL"
                            self.stats["holding_wait"] += 1
                        else:
                            confirmed_direction = self._get_confirmed_direction(signal_buffer)
                            raw_pos = self._signal_to_position(confirmed_direction, confidence, entry_signal)
                            filtered_pos = self._apply_trend_filter(raw_pos, i, ma200, ma50, weekly_ma20)

                            if filtered_pos != last_pos:
                                last_pos = filtered_pos
                                if abs(filtered_pos) > 0:
                                    holding_count = self.min_holding_bars
                                    holding_direction = "BULL" if filtered_pos > 0 else "BEAR"
                            else:
                                if confirmed_direction != direction and len(signal_buffer) >= self.signal_confirm_bars:
                                    self.stats["confirm_wait"] += 1

                        self.stats["total_bars"] += 1
                        if entry_signal == "MUST_ENTER":
                            self.stats["must_enter"] += 1
                        elif entry_signal == "TIMING":
                            self.stats["timing"] += 1
                        else:
                            self.stats["wait"] += 1

                        acc = result.get("accumulation", {})
                        stage = acc.get("stage", "NONE")
                        if stage == "ACCUMULATION":
                            self.stats["accumulation"] += 1
                        elif stage == "BREAKTHROUGH_IMMINENT":
                            self.stats["breakthrough_imminent"] += 1
                        elif stage == "BREAKTHROUGH_CONFIRMED":
                            self.stats["breakthrough_confirmed"] += 1

                        dm = result.get("drive_mode", {})
                        dm_mode = dm.get("mode", "NONE")
                        if dm_mode == "CONTINUATION":
                            self.stats["continuation"] += 1
                        elif dm_mode == "LATE_CONTINUATION":
                            self.stats["late_continuation"] += 1
                        elif dm_mode == "ACCUMULATION":
                            self.stats["accumulation_mode"] += 1
                        elif dm_mode == "WEAKENING":
                            self.stats["weakening"] += 1

                    except Exception:
                        pass

            positions[i] = last_pos

        return pd.Series(positions, index=prices.index, name="position")

    def _get_confirmed_direction(self, signal_buffer):
        if len(signal_buffer) < self.signal_confirm_bars:
            return "NEUTRAL"
        last_n = signal_buffer[-self.signal_confirm_bars:]
        if all(d == "BULL" for d in last_n):
            return "BULL"
        if all(d == "BEAR" for d in last_n):
            return "BEAR"
        return "NEUTRAL"

    def _apply_trend_filter(self, pos, i, ma200, ma50, weekly_ma20):
        if not self.enable_trend_filter:
            return pos

        if abs(pos) < 0.01:
            return pos

        in_bull = (i < len(ma200) and not np.isnan(ma200[i]) and ma200[i] > 0 and
                   i < len(ma50) and not np.isnan(ma50[i]) and ma50[i] > ma200[i])

        in_bear = (i < len(ma200) and not np.isnan(ma200[i]) and ma200[i] > 0 and
                   i < len(ma50) and not np.isnan(ma50[i]) and ma50[i] < ma200[i])

        if pos > 0:
            if self.bear_short_only and in_bear:
                self.stats["trend_filter_blocks"] += 1
                return 0.0
        elif pos < 0:
            if in_bull:
                self.stats["trend_filter_blocks"] += 1
                return 0.0

        return pos

    def _signal_to_position(self, direction: str, confidence: float, entry_signal: str) -> float:
        if direction == "NEUTRAL" or entry_signal == "WAIT":
            return 0.0

        if entry_signal == "MUST_ENTER":
            pos_ratio = min(confidence / 100.0, 1.0) * self.max_position
        elif entry_signal == "TIMING":
            if confidence < self.trial_confidence:
                return 0.0
            pos_ratio = (
                min(confidence / 100.0, 1.0)
                * self.max_position
                * self.trial_position_ratio
            )
        else:
            return 0.0

        if direction == "BULL":
            return pos_ratio
        elif direction == "BEAR":
            return -pos_ratio
        return 0.0

    def _resample_to_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        if len(daily_df) == 0:
            return daily_df

        df = daily_df.copy()
        if "date" in df.columns:
            df = df.set_index("date")
        else:
            df.index = pd.to_datetime(df.index)

        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        return weekly

    def get_stats(self) -> dict:
        return self.stats.copy()


class AdaptiveLeastResistanceStrategy(BaseStrategy):
    """自适应市场状态的最小阻力策略

    根据MA200/MA50动态判断牛市/熊市/震荡，切换最优参数：
    - 牛市: 长持仓(15天)+低确认(1天)+满仓 → 趋势跟踪
    - 熊市: 短持仓(3天)+低确认(1天)+满仓 → 快进快出做空
    - 震荡: 短持仓(3天)+高确认(2天)+低仓(0.4) → 保守防御
    """

    REGIME_PARAMS = {
        "bull":      {"min_holding_bars": 15, "signal_confirm_bars": 1, "max_position": 1.0},
        "bear":      {"min_holding_bars": 3,  "signal_confirm_bars": 1, "max_position": 1.0},
        "sideways":  {"min_holding_bars": 3,  "signal_confirm_bars": 2, "max_position": 0.4},
    }

    def __init__(
        self,
        warmup_periods: int = 80,
        update_step: int = 1,
        regime_params: dict = None,
        enable_trend_filter: bool = True,
    ):
        super().__init__(name="adaptive_lr")
        self.warmup_periods = warmup_periods
        self.update_step = max(1, update_step)
        self.enable_trend_filter = enable_trend_filter
        self.regime_params = regime_params or self.REGIME_PARAMS
        self.stats = {
            "total_bars": 0,
            "regime_bull": 0,
            "regime_bear": 0,
            "regime_sideways": 0,
            "regime_switches": 0,
            "trend_filter_blocks": 0,
        }

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        try:
            from core.least_resistance import compute_least_resistance_3d
        except ImportError:
            import sys, os
            sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
            from core.least_resistance import compute_least_resistance_3d

        n = len(prices)
        positions = np.zeros(n)
        warmup = min(self.warmup_periods, n - 10)
        step = max(1, self.update_step)

        close = prices["close"]
        ma200 = close.rolling(window=200, min_periods=200).mean().values
        ma50 = close.rolling(window=50, min_periods=50).mean().values
        ma200_slope = close.rolling(window=200, min_periods=200).mean().pct_change(periods=20).values

        history_3d = []
        daily_history_diffs = []
        signal_buffer = []
        holding_count = 0
        last_pos = 0.0
        last_regime = "sideways"

        for i in range(warmup, n):
            # 实时判断市场状态
            current_regime = self._detect_regime(i, ma200, ma50, ma200_slope)
            if current_regime != last_regime:
                self.stats["regime_switches"] += 1
                last_regime = current_regime
            self.stats[f"regime_{current_regime}"] += 1

            # 获取当前状态的参数
            params = self.regime_params.get(current_regime, self.regime_params["sideways"])
            min_holding = params["min_holding_bars"]
            confirm_bars = params["signal_confirm_bars"]
            max_position = params["max_position"]

            if (i - warmup) % step == 0 or i == warmup:
                daily_slice = prices.iloc[:i + 1].copy()
                weekly_df = self._resample_to_weekly(daily_slice)

                if len(weekly_df) >= 10:
                    try:
                        result = compute_least_resistance_3d(
                            weekly_df, daily_slice,
                            daily_history_diffs=daily_history_diffs if daily_history_diffs else None,
                            history_3d=history_3d if history_3d else None,
                        )

                        direction = result["direction"]
                        confidence = result["confidence"]
                        entry_signal = result["entry_signal"]
                        daily_diff = result.get("daily_diff", 0.0)

                        daily_history_diffs.append(daily_diff)
                        if len(daily_history_diffs) > 30:
                            daily_history_diffs = daily_history_diffs[-30:]

                        history_3d.append({
                            "direction": direction,
                            "velocity": result["velocity"],
                            "acceleration": result["acceleration"],
                        })
                        if len(history_3d) > 20:
                            history_3d = history_3d[-20:]

                        signal_buffer.append(direction)
                        if len(signal_buffer) > confirm_bars:
                            signal_buffer = signal_buffer[-confirm_bars:]

                        if holding_count > 0:
                            holding_count -= 1
                        else:
                            confirmed = self._get_confirmed_direction(signal_buffer, confirm_bars)
                            raw_pos = self._signal_to_position(
                                confirmed, confidence, entry_signal, max_position
                            )
                            filtered_pos = self._apply_trend_filter(raw_pos, i, ma200, ma50)

                            if filtered_pos != last_pos:
                                last_pos = filtered_pos
                                if abs(filtered_pos) > 0:
                                    holding_count = min_holding

                        self.stats["total_bars"] += 1

                    except Exception:
                        pass

            positions[i] = last_pos

        return pd.Series(positions, index=prices.index, name="position")

    def _detect_regime(self, i, ma200, ma50, ma200_slope):
        if i >= len(ma200) or np.isnan(ma200[i]) or ma200[i] <= 0:
            return "sideways"
        if i >= len(ma50) or np.isnan(ma50[i]) or ma50[i] <= 0:
            return "sideways"

        price_above = ma50[i] > ma200[i]
        slope_up = ma200_slope[i] > 0 if (i < len(ma200_slope) and not np.isnan(ma200_slope[i])) else False

        if price_above and slope_up:
            return "bull"
        elif not price_above and not slope_up:
            return "bear"
        return "sideways"

    def _get_confirmed_direction(self, signal_buffer, confirm_bars):
        if len(signal_buffer) < confirm_bars:
            return "NEUTRAL"
        last_n = signal_buffer[-confirm_bars:]
        if all(d == "BULL" for d in last_n):
            return "BULL"
        if all(d == "BEAR" for d in last_n):
            return "BEAR"
        return "NEUTRAL"

    def _signal_to_position(self, direction, confidence, entry_signal, max_position):
        if direction == "NEUTRAL" or entry_signal == "WAIT":
            return 0.0
        if entry_signal == "MUST_ENTER":
            pos_ratio = min(confidence / 100.0, 1.0) * max_position
        elif entry_signal == "TIMING":
            if confidence < 25.0:
                return 0.0
            pos_ratio = min(confidence / 100.0, 1.0) * max_position * 0.3
        else:
            return 0.0
        if direction == "BULL":
            return pos_ratio
        elif direction == "BEAR":
            return -pos_ratio
        return 0.0

    def _apply_trend_filter(self, pos, i, ma200, ma50):
        if not self.enable_trend_filter or abs(pos) < 0.01:
            return pos
        if i >= len(ma200) or np.isnan(ma200[i]) or ma200[i] <= 0:
            return pos
        if i >= len(ma50) or np.isnan(ma50[i]) or ma50[i] <= 0:
            return pos

        in_bull = ma50[i] > ma200[i]
        in_bear = ma50[i] < ma200[i]

        if pos > 0 and in_bear:
            self.stats["trend_filter_blocks"] += 1
            return 0.0
        if pos < 0 and in_bull:
            self.stats["trend_filter_blocks"] += 1
            return 0.0
        return pos

    def _resample_to_weekly(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        if len(daily_df) == 0:
            return daily_df
        df = daily_df.copy()
        if "date" in df.columns:
            df = df.set_index("date")
        else:
            df.index = pd.to_datetime(df.index)
        weekly = df.resample("W").agg({
            "open": "first", "high": "max", "low": "min",
            "close": "last", "volume": "sum",
        }).dropna()
        return weekly

    def get_stats(self) -> dict:
        return self.stats.copy()

class MA200TrendFollowingStrategy(BaseStrategy):
    """MA200牛熊经验法则策略

    核心逻辑：
    - 牛市开启：收盘价 > MA200 且 MA200的5日斜率 > 0 → ALL IN 做多
    - 熊市开启：收盘价 < MA200 且 MA200的5日斜率 < 0 → ALL IN 做空
    - 震荡期：  空仓

    经典趋势跟踪经验法则，确保大趋势下不空仓。
    """

    def __init__(
        self,
        ma_period: int = 200,
        slope_period: int = 5,
        max_position: float = 1.0,
        sideways_mode: str = "flat",
        warmup_periods: int = 210,
    ):
        super().__init__(name="ma200_trend")
        self.ma_period = ma_period
        self.slope_period = slope_period
        self.max_position = max_position
        self.sideways_mode = sideways_mode
        self.warmup_periods = warmup_periods
        self.stats = {
            "bull_days": 0,
            "bear_days": 0,
            "sideways_days": 0,
            "trend_switches": 0,
        }

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values
        ma_series = pd.Series(close).rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        ma = ma_series.values

        ma_slope = np.zeros(n)
        for i in range(self.warmup_periods, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                ma_slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100

        last_state = "init"
        for i in range(self.warmup_periods, n):
            if np.isnan(ma[i]) or ma[i] <= 0:
                positions[i] = 0.0
                continue

            price_above = close[i] > ma[i]
            slope_pos = ma_slope[i] > 0
            slope_neg = ma_slope[i] < 0

            if price_above and slope_pos:
                current_state = "bull"
                positions[i] = self.max_position
                self.stats["bull_days"] += 1
            elif not price_above and slope_neg:
                current_state = "bear"
                positions[i] = -self.max_position
                self.stats["bear_days"] += 1
            else:
                current_state = "sideways"
                positions[i] = 0.0
                self.stats["sideways_days"] += 1

            if current_state != last_state and last_state != "init":
                self.stats["trend_switches"] += 1
            last_state = current_state

        return pd.Series(positions, index=prices.index, name="position")

    def get_stats(self) -> dict:
        return self.stats.copy()


class EnhancedMA200Strategy(BaseStrategy):
    """增强版MA200牛熊经验法则策略 v2

    三条核心法则：
    1. 比特币价格跌至周线MA200，分仓抄底（越跌越买）
    2. BTC有效跌破MA200允许3层仓位做空；MA200的5日斜率为负时加仓至5成；
       止盈位按斐波那契数列(23.6%, 38.2%, 50%, 61.8%)分阶段止盈
    3. 小币在熊市禁止开仓，不做多也不做空；只有BTC和自身都处于牛市才做多

    BTC策略矩阵：
    - 牛市(价>MA200且斜率>0): 满仓做多
    - 跌破MA200(价<MA200): 3成空仓
    - 跌破MA200 + 斜率<0: 5成空仓
    - 价格接近/跌破周线MA200: 分仓抄底(覆盖做空/空仓状态)
    - 斐波那契止盈: 做空盈利达到23.6%/38.2%/50%/61.8%时分批减仓

    小币策略矩阵：
    - BTC牛市 且 自身牛市: 满仓做多
    - 其他所有状态: 空仓（不做多也不做空）
    """

    def __init__(
        self,
        ma_period: int = 200,
        slope_period: int = 5,
        max_position: float = 1.0,
        warmup_periods: int = 210,
        symbol: str = "BTC",
        is_btc: bool = True,
        btc_prices: Optional[pd.DataFrame] = None,
        weekly_ma200_dip_buy: bool = True,
        dip_buy_max_position: float = 0.8,
        dip_buy_levels: int = 4,
        dip_buy_step_pct: float = 5.0,
        bear_short_level1_pct: float = 0.3,
        bear_short_level2_pct: float = 0.5,
        fib_take_profit: bool = True,
        fib_levels: Optional[list] = None,
        alt_bear_no_trade: bool = True,
    ):
        super().__init__(name="enhanced_ma200_v2")
        self.ma_period = ma_period
        self.slope_period = slope_period
        self.max_position = max_position
        self.warmup_periods = warmup_periods
        self.symbol = symbol
        self.is_btc = is_btc
        self.btc_prices = btc_prices
        self.weekly_ma200_dip_buy = weekly_ma200_dip_buy
        self.dip_buy_max_position = dip_buy_max_position
        self.dip_buy_levels = dip_buy_levels
        self.dip_buy_step_pct = dip_buy_step_pct
        self.bear_short_level1_pct = bear_short_level1_pct
        self.bear_short_level2_pct = bear_short_level2_pct
        self.fib_take_profit = fib_take_profit
        self.fib_levels = fib_levels or [0.236, 0.382, 0.5, 0.618]
        self.alt_bear_no_trade = alt_bear_no_trade
        self.stats = {
            "bull_days": 0,
            "bear_short_l1_days": 0,
            "bear_short_l2_days": 0,
            "bear_flat_days": 0,
            "sideways_days": 0,
            "dip_buy_days": 0,
            "fib_tp_days": 0,
            "trend_switches": 0,
        }

    def _resample_to_weekly(self, prices: pd.DataFrame) -> pd.DataFrame:
        df = prices.copy()
        if "date" in df.columns:
            df = df.set_index("date")
        else:
            df.index = pd.to_datetime(df.index)
        weekly = df.resample("W").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()
        return weekly

    def _compute_weekly_ma200(self, prices: pd.DataFrame) -> np.ndarray:
        weekly = self._resample_to_weekly(prices)
        weekly_close = weekly["close"].values
        if len(weekly_close) < 200:
            return np.full(len(prices), np.nan)
        weekly_ma200 = pd.Series(weekly_close).rolling(window=200, min_periods=200).mean().values
        daily_ma200 = np.full(len(prices), np.nan)
        weekly_idx = 0
        for i in range(len(prices)):
            current_date = prices.index[i]
            while weekly_idx < len(weekly) and weekly.index[weekly_idx] <= current_date:
                weekly_idx += 1
            if weekly_idx >= 200:
                daily_ma200[i] = weekly_ma200[weekly_idx - 1]
        return daily_ma200

    def _compute_btc_regime(self) -> Optional[np.ndarray]:
        if self.btc_prices is None or self.is_btc:
            return None
        btc_close = self.btc_prices["close"].values
        n_btc = len(btc_close)
        btc_ma = pd.Series(btc_close).rolling(window=self.ma_period, min_periods=self.ma_period).mean().values
        btc_slope = np.zeros(n_btc)
        for i in range(self.warmup_periods, n_btc):
            if not np.isnan(btc_ma[i]) and not np.isnan(btc_ma[i - self.slope_period]):
                btc_slope[i] = (btc_ma[i] / btc_ma[i - self.slope_period] - 1) * 100
        btc_regime = np.full(n_btc, "sideways", dtype=object)
        for i in range(self.warmup_periods, n_btc):
            if np.isnan(btc_ma[i]):
                continue
            price_above = btc_close[i] > btc_ma[i]
            slope_pos = btc_slope[i] > 0
            slope_neg = btc_slope[i] < 0
            if price_above and slope_pos:
                btc_regime[i] = "bull"
            elif not price_above:
                btc_regime[i] = "bear"
            else:
                btc_regime[i] = "sideways"
        return btc_regime

    def _calc_fib_tp_position(
        self,
        current_price: float,
        entry_price: float,
        is_short: bool,
        current_short_pos: float,
    ) -> float:
        """根据斐波那契止盈位计算当前应持有的空仓比例"""
        if not self.fib_take_profit or not is_short or entry_price <= 0:
            return current_short_pos
        profit_pct = (entry_price - current_price) / entry_price
        if profit_pct <= 0:
            return current_short_pos
        remaining_ratio = 1.0
        n_levels = len(self.fib_levels)
        portion_per_level = 1.0 / n_levels
        for level in self.fib_levels:
            if profit_pct >= level:
                remaining_ratio -= portion_per_level
        remaining_ratio = max(remaining_ratio, 0.0)
        return current_short_pos * remaining_ratio

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)
        close = prices["close"].values
        ma_series = pd.Series(close).rolling(window=self.ma_period, min_periods=self.ma_period).mean()
        ma = ma_series.values
        ma_slope = np.zeros(n)
        for i in range(self.warmup_periods, n):
            if not np.isnan(ma[i]) and not np.isnan(ma[i - self.slope_period]):
                ma_slope[i] = (ma[i] / ma[i - self.slope_period] - 1) * 100
        weekly_ma200 = self._compute_weekly_ma200(prices) if (self.is_btc and self.weekly_ma200_dip_buy) else None
        btc_regime = self._compute_btc_regime() if (not self.is_btc and self.alt_bear_no_trade) else None
        last_state = "init"
        short_entry_price = None
        for i in range(self.warmup_periods, n):
            if np.isnan(ma[i]) or ma[i] <= 0:
                positions[i] = 0.0
                continue
            price_above = close[i] > ma[i]
            slope_pos = ma_slope[i] > 0
            slope_neg = ma_slope[i] < 0
            current_state = "sideways"
            target_pos = 0.0
            if self.is_btc:
                if price_above and slope_pos:
                    current_state = "bull"
                    target_pos = self.max_position
                    self.stats["bull_days"] += 1
                    short_entry_price = None
                elif not price_above:
                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                        if weekly_below_pct > 0:
                            levels_filled = min(
                                int(weekly_below_pct / self.dip_buy_step_pct),
                                self.dip_buy_levels
                            )
                            if levels_filled > 0:
                                dip_buy_pos = (levels_filled / self.dip_buy_levels) * self.dip_buy_max_position
                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        target_pos = dip_buy_pos
                        self.stats["dip_buy_days"] += 1
                        short_entry_price = None
                    else:
                        base_short = 0.0
                        if slope_neg:
                            base_short = self.bear_short_level2_pct
                            current_state = "bear_short_l2"
                            self.stats["bear_short_l2_days"] += 1
                        else:
                            base_short = self.bear_short_level1_pct
                            current_state = "bear_short_l1"
                            self.stats["bear_short_l1_days"] += 1
                        if base_short > 0 and short_entry_price is None:
                            short_entry_price = close[i]
                        if base_short > 0 and short_entry_price is not None and self.fib_take_profit:
                            fib_pos = self._calc_fib_tp_position(
                                close[i], short_entry_price, True, base_short
                            )
                            if fib_pos < base_short:
                                self.stats["fib_tp_days"] += 1
                            target_pos = -fib_pos
                        else:
                            target_pos = -base_short
                else:
                    dip_buy_pos = 0.0
                    if self.weekly_ma200_dip_buy and not np.isnan(weekly_ma200[i]) and weekly_ma200[i] > 0:
                        weekly_below_pct = (weekly_ma200[i] - close[i]) / weekly_ma200[i] * 100
                        if weekly_below_pct > 0:
                            levels_filled = min(
                                int(weekly_below_pct / self.dip_buy_step_pct),
                                self.dip_buy_levels
                            )
                            if levels_filled > 0:
                                dip_buy_pos = (levels_filled / self.dip_buy_levels) * self.dip_buy_max_position
                    if dip_buy_pos > 0:
                        current_state = "dip_buy"
                        target_pos = dip_buy_pos
                        self.stats["dip_buy_days"] += 1
                        short_entry_price = None
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
                        short_entry_price = None
            else:
                if self.alt_bear_no_trade:
                    btc_in_bull = False
                    if btc_regime is not None and i < len(btc_regime):
                        btc_in_bull = btc_regime[i] == "bull"
                    if price_above and slope_pos and btc_in_bull:
                        current_state = "bull"
                        target_pos = self.max_position
                        self.stats["bull_days"] += 1
                    else:
                        current_state = "bear_flat"
                        target_pos = 0.0
                        self.stats["bear_flat_days"] += 1
                else:
                    if price_above and slope_pos:
                        current_state = "bull"
                        target_pos = self.max_position
                        self.stats["bull_days"] += 1
                    elif not price_above and slope_neg:
                        current_state = "bear_short_l1"
                        target_pos = -self.bear_short_level1_pct
                        self.stats["bear_short_l1_days"] += 1
                    else:
                        current_state = "sideways"
                        target_pos = 0.0
                        self.stats["sideways_days"] += 1
            positions[i] = target_pos
            if current_state != last_state and last_state != "init":
                self.stats["trend_switches"] += 1
            last_state = current_state
        return pd.Series(positions, index=prices.index, name="position")

    def get_stats(self) -> dict:
        return self.stats.copy()
