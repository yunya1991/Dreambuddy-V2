# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
import pandas as pd
import numpy as np
from pandas import DataFrame
from typing import Optional
from datetime import datetime, timedelta

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade
import talib.abstract as ta


class Strategy006(IStrategy):
    """
    第二屏日线多头信号 + 第三屏1h确认 + ATR波动率自适应系统（最终完整修复版）
    - 已彻底解决 merge_informative_pair KeyError 'date' 问题
    - 日线数据清洗后 reset_index()，保留 date 列供 merge 使用
    - 所有先前问题已修复（duplicate labels、类型错误、RSI 出场、MACD 过滤等）
    """

    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    minimal_roi = {
        "0": 0.20,
        "240": 0.12,
        "720": 0.08,
        "1440": 0.04,
        "2880": 0
    }

    stoploss = -0.08

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    ignore_roi_if_entry_signal = True
    startup_candle_count: int = 300

    # 基础参数
    rsi_buy = IntParameter(30, 40, default=35, space="buy")
    donchian_period = IntParameter(15, 30, default=20, space="buy")
    volume_multiplier = DecimalParameter(1.2, 2.0, default=1.3, space="buy")
    require_volume_spike = True
    require_macd_hist_up = True

    # ATR动态止损参数
    atr_period = IntParameter(10, 20, default=14, space="buy")
    atr_multiplier_stoploss = DecimalParameter(1.5, 3.0, default=2.0, space="buy")
    volatility_adaptive = True

    # 入场控制参数
    min_entry_interval_hours = IntParameter(4, 24, default=6, space="buy")
    max_open_trades = IntParameter(3, 10, default=5, space="buy")

    def informative_pairs(self):
        pairs = self.dp.current_whitelist()
        return [(pair, "1d") for pair in pairs]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 初始化关键列
        dataframe["daily_long_signal"] = False
        dataframe["third_screen_confirm"] = False

        # === 日线第二屏信号 ===
        pair_daily = self.dp.get_pair_dataframe(metadata["pair"], "1d")
        if pair_daily is not None and not pair_daily.empty:
            # 日线数据清洗（去重、排序、时间转换）
            if "date" in pair_daily.columns:
                pair_daily["date"] = pd.to_datetime(pair_daily["date"], utc=True, errors="coerce")
                pair_daily = pair_daily.dropna(subset=["date"])
                pair_daily = pair_daily.sort_values("date")
                pair_daily = pair_daily.drop_duplicates(subset=["date"], keep="last")

            for col in ("open", "high", "low", "close", "volume"):
                if col in pair_daily.columns:
                    pair_daily[col] = pd.to_numeric(pair_daily[col], errors="coerce")
            pair_daily = pair_daily[pair_daily["close"].notna()]

            # 基础指标（强制转为 numeric）
            pair_daily["rsi"] = pd.to_numeric(ta.RSI(pair_daily, timeperiod=14), errors="coerce")
            pair_daily["ema13"] = pd.to_numeric(ta.EMA(pair_daily, timeperiod=13), errors="coerce")
            slowk, _ = ta.STOCH(pair_daily)
            pair_daily["stoch_k"] = pd.to_numeric(slowk, errors="coerce")
            pair_daily["cci"] = pd.to_numeric(ta.CCI(pair_daily, timeperiod=20), errors="coerce")

            # MACD
            macd, macdsignal, macdhist = ta.MACD(
                pair_daily["close"],
                fastperiod=12,
                slowperiod=26,
                signalperiod=9
            )
            pair_daily["macdhist"] = pd.to_numeric(macdhist, errors="coerce")
            pair_daily["macd_hist_positive_slope"] = pair_daily["macdhist"] > pair_daily["macdhist"].shift(1)

            # 成交量放大
            pair_daily["volume_ma20"] = pair_daily["volume"].rolling(20).mean()
            pair_daily["volume_spike"] = pair_daily["volume"] > pair_daily["volume_ma20"] * self.volume_multiplier.value

            # Elder Ray 多头背离
            pair_daily["raw_force"] = (pair_daily["close"] - pair_daily["close"].shift(1)) * pair_daily["volume"]
            pair_daily["force_index"] = pd.to_numeric(ta.EMA(pair_daily["raw_force"], timeperiod=13), errors="coerce")
            lookback = 20
            pair_daily["price_new_low"] = pair_daily["close"] < pair_daily["close"].rolling(lookback).min().shift(1)
            pair_daily["force_higher_low"] = pair_daily["force_index"] > pair_daily["force_index"].rolling(lookback).min().shift(1)
            pair_daily["force_double_bottom"] = (
                (pair_daily["force_index"] > pair_daily["force_index"].shift(1)) &
                (pair_daily["force_index"].shift(1) < pair_daily["force_index"].shift(2))
            )
            pair_daily["elder_long"] = (
                (pair_daily["rsi"] < 30) &
                pair_daily["price_new_low"] &
                (pair_daily["force_higher_low"] | pair_daily["force_double_bottom"])
            )

            # Freqtrade 投票
            pair_daily["freqtrade_vote_long"] = (
                (pair_daily["rsi"] < self.rsi_buy.value).astype(int) +
                (pair_daily["stoch_k"] < 20).astype(int) +
                (pair_daily["cci"] < -100).astype(int)
            )
            pair_daily["freqtrade_long"] = pair_daily["freqtrade_vote_long"] >= 2

            # TradingView 回调
            pair_daily["price_near_ema"] = (pair_daily["close"] < pair_daily["ema13"] * 1.02) & (pair_daily["close"] > pair_daily["ema13"] * 0.98)
            pair_daily["tradingview_long"] = (
                (pair_daily["rsi"] < 35) &
                (pair_daily["macdhist"] > pair_daily["macdhist"].shift(1)) &
                pair_daily["price_near_ema"]
            )

            # 量化均值回归
            pair_daily["williams_r"] = pd.to_numeric(ta.WILLR(pair_daily, timeperiod=14), errors="coerce")
            pair_daily["qf_vote_long"] = (
                (pair_daily["rsi"] < 30).astype(int) +
                (pair_daily["stoch_k"] < 20).astype(int) +
                (pair_daily["williams_r"] < -80).astype(int)
            )
            pair_daily["mean"] = pair_daily["close"].rolling(20).mean()
            pair_daily["std"] = pair_daily["close"].rolling(20).std().replace(0, 1e-10)
            pair_daily["lower_band"] = pair_daily["mean"] - 1.5 * pair_daily["std"]
            pair_daily["quant_long"] = (
                (pair_daily["qf_vote_long"] >= 2) &
                (pair_daily["close"] < pair_daily["lower_band"])
            )

            # 四组任一满足
            pair_daily["any_screen_long"] = (
                pair_daily["elder_long"] |
                pair_daily["freqtrade_long"] |
                pair_daily["tradingview_long"] |
                pair_daily["quant_long"]
            )

            #if self.require_volume_spike:
                #pair_daily["any_screen_long"] &= pair_daily["volume_spike"]
            #if self.require_macd_hist_up:
                #pair_daily["any_screen_long"] &= (pair_daily["macdhist"] > pair_daily["macdhist"].shift(1))

            # 关键修复：reset_index() 保留 date 列供 merge_informative_pair 使用
            pair_daily = pair_daily.reset_index()

            # 合并日线信号（包含 date 列）
            informative = pair_daily[["date", "any_screen_long", "macd_hist_positive_slope"]].copy()
            dataframe = merge_informative_pair(
                dataframe,
                informative,
                self.timeframe,
                "1d",
                ffill=True
            )
            dataframe["daily_long_signal"] = dataframe["any_screen_long_1d"].fillna(False)
            dataframe["daily_macd_hist_positive_slope"] = dataframe["macd_hist_positive_slope_1d"].fillna(False)
            dataframe.drop(columns=["any_screen_long_1d", "macd_hist_positive_slope_1d"], inplace=True, errors="ignore")

        # === 第三屏：1h确认 ===
        dataframe["donchian_upper"] = dataframe["high"].rolling(self.donchian_period.value).max()
        dataframe["donchian_lower"] = dataframe["low"].rolling(self.donchian_period.value).min()

        dataframe["prev_high"] = dataframe["high"].shift(1)
        breakout_prev_high = dataframe["close"] > dataframe["prev_high"]
        breakout_donchian = dataframe["close"] > dataframe["donchian_upper"].shift(1)

        body_abs = (dataframe["close"] - dataframe["open"]).abs()
        body_abs_safe = body_abs.replace(0, np.finfo(float).eps)
        total_range = dataframe["high"] - dataframe["low"]
        total_range_safe = total_range.replace(0, np.finfo(float).eps)
        lower_shadow = dataframe[["open", "close"]].min(axis=1) - dataframe["low"]
        upper_shadow = dataframe["high"] - dataframe[["open", "close"]].max(axis=1)

        hammer = (
            (lower_shadow > 2 * body_abs_safe) &
            (upper_shadow < body_abs_safe * 0.3) &
            (total_range > 0) &
            (lower_shadow / total_range_safe > 0.6)
        )

        engulfing_bull = (
            (dataframe["close"] > dataframe["open"]) &
            (dataframe["close"].shift(1) < dataframe["open"].shift(1)) &
            (dataframe["open"] < dataframe["close"].shift(1)) &
            (dataframe["close"] > dataframe["open"].shift(1))
        )

        candle_confirm = hammer | engulfing_bull
        dataframe["third_screen_confirm"] = breakout_prev_high | breakout_donchian | candle_confirm

        # === 1h RSI（用于出场） ===
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # === ATR波动率指标 ===
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period.value)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]

        atr_sma = dataframe["atr"].rolling(20).mean()
        dataframe["volatility_state"] = 1
        dataframe.loc[dataframe["atr"] > atr_sma * 1.2, "volatility_state"] = 2
        dataframe.loc[dataframe["atr"] < atr_sma * 0.8, "volatility_state"] = 0

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["daily_long_signal"]) &
            (dataframe["third_screen_confirm"]),
            "enter_long"
        ] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 通道突破出场（连续2根确认）
        channel_exit = (
            (dataframe["close"].shift(1) < dataframe["donchian_lower"].shift(2)) &
            (dataframe["close"] < dataframe["donchian_lower"].shift(1))
        )

        # RSI 出场：连续两根回落（从超买区连续下降）
        rsi_pullback_1 = (dataframe["rsi"].shift(1) > 70) & (dataframe["rsi"] <= dataframe["rsi"].shift(1))
        rsi_pullback_2 = (dataframe["rsi"].shift(2) > dataframe["rsi"].shift(1)) & (dataframe["rsi"].shift(1) > dataframe["rsi"])
        rsi_continuous_pullback = rsi_pullback_1 & rsi_pullback_2

        dataframe.loc[
            channel_exit | rsi_continuous_pullback,
            "exit_long"
        ] = 1
        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty or len(dataframe) < 20:
            return self.stoploss

        latest = dataframe.iloc[-1]
        fallback_atr_pct = ((dataframe["high"] - dataframe["low"]) / dataframe["close"]).rolling(20).mean().iloc[-1]
        fallback_atr_pct = fallback_atr_pct if pd.notna(fallback_atr_pct) else 0.02
        atr_pct = latest.get("atr_pct", fallback_atr_pct)

        volatility_state = latest.get("volatility_state", 1)

        base_stoploss = self.atr_multiplier_stoploss.value * atr_pct

        if self.volatility_adaptive:
            if volatility_state == 2:
                base_stoploss *= 0.8
            elif volatility_state == 0:
                base_stoploss *= 1.2

        if current_profit > 0.10:
            base_stoploss *= 0.7
        elif current_profit > 0.05:
            base_stoploss *= 0.85

        final_stoploss = max(min(base_stoploss, 0.15), 0.03)
        return -final_stoploss

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: Optional[float], max_stake: float,
                            leverage: float = 1.0, entry_tag: Optional[str] = None, side: str = "long",
                            **kwargs) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe.empty:
            return proposed_stake

        latest = dataframe.iloc[-1]
        volatility_state = latest.get("volatility_state", 1)
        atr_pct = latest.get("atr_pct", 0.02)

        multiplier = 1.0
        if volatility_state == 2:
            multiplier = 0.6
        elif volatility_state == 0:
            multiplier = 1.4

        if atr_pct > 0.08:
            multiplier *= 0.5
        elif atr_pct > 0.06:
            multiplier *= 0.7
        elif atr_pct < 0.02:
            multiplier *= 1.2

        adjusted = proposed_stake * multiplier
        if min_stake and adjusted < min_stake:
            return min_stake
        if adjusted > max_stake:
            return max_stake
        return adjusted

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if not dataframe.empty:
            latest = dataframe.iloc[-1]
            atr_pct = latest.get("atr_pct", 0.02)
            volatility_state = latest.get("volatility_state", 1)
            if atr_pct > 0.10 or (volatility_state == 2 and atr_pct > 0.08):
                return False

            daily_macd_hist_positive_slope = latest.get("daily_macd_hist_positive_slope", False)
            if not daily_macd_hist_positive_slope:
                return False

        open_trades = Trade.get_trades([Trade.is_open.is_(True)])
        if len(open_trades) >= self.max_open_trades.value:
            return False

        closed_trades = Trade.get_trades([Trade.pair == pair, Trade.is_open.is_(False)])
        if closed_trades:
            last_close = max(getattr(t, 'close_date_utc', t.close_date) for t in closed_trades)
            if (current_time - last_close).total_seconds() < self.min_entry_interval_hours.value * 3600:
                return False

        return True

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "enter_long": {"color": "green", "type": "scatter", "marker": {"symbol": "triangle-up", "size": 15}},
                "donchian_upper": {"color": "blue", "linewidth": 1},
                "donchian_lower": {"color": "blue", "linewidth": 1},
            },
            "subplots": {
                "ATR %": {"atr_pct": {"color": "orange"}},
                "Volatility State (0=low,1=normal,2=high)": {"volatility_state": {"color": "purple"}},
                "RSI": {"rsi": {"color": "purple"}}
            }
        }