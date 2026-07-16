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
