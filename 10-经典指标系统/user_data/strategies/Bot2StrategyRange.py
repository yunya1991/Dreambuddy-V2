# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class Bot2Strategy(IStrategy):
    """
    Bot2Strategy (Fully Fixed & Optimized Version)
    Dual-mode strategy: Range (mean-reversion) + Trend following
    Based on BTC volatility regime
    """
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short: bool = False

    minimal_roi = {
        "0": 0.098,
        "65": 0.024,
        "138": 0.020,
        "208": 0.00,
    }

    stoploss = -0.105
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = 200

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    order_time_in_force = {
        "entry": "GTC",
        "exit": "GTC",
    }

    # Hyperopt parameters
    buy_ema_fast_period = IntParameter(10, 30, default=28, space="buy")
    buy_ema_slow_period = IntParameter(40, 80, default=45, space="buy")
    buy_ema_trend_period = IntParameter(150, 250, default=213, space="buy")
    buy_rsi_range = IntParameter(10, 40, default=14, space="buy")
    buy_mr_ema_dev = DecimalParameter(0.005, 0.03, default=0.029, decimals=3, space="buy")
    buy_adx_trend = IntParameter(15, 40, default=36, space="buy")
    buy_volume_factor = DecimalParameter(1.0, 3.0, default=1.84, decimals=2, space="buy")
    buy_vol_threshold = DecimalParameter(0.01, 0.05, default=0.012, decimals=3, space="buy")

    sell_rsi_range = IntParameter(40, 80, default=70, space="sell")
    sell_rsi_trend = IntParameter(50, 90, default=70, space="sell")
    sell_atr_mult = DecimalParameter(1.0, 4.0, default=2.0, decimals=2, space="sell")

    # === 新增：追涨过滤 Hyperopt 参数 ===
    anti_chase_max_dev = DecimalParameter(0.08, 0.25, default=0.111, decimals=3, space="buy")
    anti_chase_max_rsi = IntParameter(65, 80, default=73, space="buy")
    anti_chase_bb_percent = DecimalParameter(0.90, 0.98, default=0.95, decimals=2, space="buy")
    anti_chase_adx_slope_min = DecimalParameter(-5.0, 0.0, default=-3.0, decimals=1, space="buy")
    anti_chase_recent_pump_max = DecimalParameter(0.05, 0.15, default=0.10, decimals=2, space="buy")
    anti_chase_lookback = IntParameter(12, 48, default=32, space="buy")  # 1~4小时

    def informative_pairs(self):
        return [("BTC/USDT", "4h")]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Main 5m indicators
        dataframe["rsi"] = ta.RSI(dataframe)

        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.buy_ema_fast_period.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.buy_ema_slow_period.value)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=self.buy_ema_trend_period.value)

        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lower"] = bollinger["lower"]
        dataframe["bb_mid"] = bollinger["mid"]
        dataframe["bb_upper"] = bollinger["upper"]

        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(50).mean()

        # 🔧 修复：BTC 4h volatility regime
        try:
            btc_df = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe="4h")
            if btc_df is not None and not btc_df.empty and len(btc_df) > 20:
                btc_df["btc_atr_4h"] = ta.ATR(btc_df, timeperiod=14)
                btc_df["btc_volatility_4h"] = btc_df["btc_atr_4h"] / btc_df["close"]
                btc_df = btc_df[["date", "btc_volatility_4h"]].copy()

                dataframe = merge_informative_pair(
                    dataframe,
                    btc_df,
                    self.timeframe,
                    "4h",
                    ffill=True
                )

                if 'btc_volatility_4h_4h' in dataframe.columns:
                    dataframe.rename(columns={'btc_volatility_4h_4h': 'btc_volatility_4h'}, inplace=True)
                elif 'btc_volatility_4h' not in dataframe.columns:
                    dataframe['btc_volatility_4h'] = 0.0
            else:
                dataframe['btc_volatility_4h'] = 0.0
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"BTC volatility calculation failed: {e}")
            dataframe['btc_volatility_4h'] = 0.0

        if 'btc_volatility_4h' not in dataframe.columns:
            dataframe['btc_volatility_4h'] = 0.0

        dataframe['btc_volatility_4h'] = dataframe['btc_volatility_4h'].fillna(0.0)

        # Regime classification
        vol_threshold = self.buy_vol_threshold.value
        dataframe["regime_trend"] = (dataframe["btc_volatility_4h"] >= vol_threshold).astype(int)

        # === 追涨过滤模块所需指标 ===
        dataframe["adx_slope"] = dataframe["adx"].diff(3)

        dataframe["bb_percent"] = (dataframe["close"] - dataframe["bb_lower"]) / (dataframe["bb_upper"] - dataframe["bb_lower"])

        lookback = self.anti_chase_lookback.value
        dataframe["max_high_lookback"] = dataframe["high"].rolling(lookback).max()
        dataframe["recent_pump"] = (dataframe["close"] / dataframe["max_high_lookback"].shift(1)) - 1

        # 安全处理 NaN
        dataframe["adx_slope"] = dataframe["adx_slope"].fillna(0)
        dataframe["bb_percent"] = dataframe["bb_percent"].fillna(0.5)
        dataframe["recent_pump"] = dataframe["recent_pump"].fillna(0.0)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0

        # Mean-reversion conditions
        mr_cond1 = dataframe["close"] < dataframe["bb_lower"]
        mr_cond2 = dataframe["rsi"] < self.buy_rsi_range.value
        mr_cond3 = dataframe["close"] < dataframe["ema_fast"] * (1 - self.buy_mr_ema_dev.value)
        dataframe["mr_score"] = mr_cond1.astype(int) + mr_cond2.astype(int) + mr_cond3.astype(int)

        # Trend following conditions
        trend_cond1 = (
            (dataframe["close"] > dataframe["ema_fast"]) &
            (dataframe["ema_fast"] > dataframe["ema_slow"]) &
            (dataframe["ema_slow"] > dataframe["ema_trend"])
        )
        trend_cond2 = dataframe["adx"] > self.buy_adx_trend.value
        trend_cond3 = dataframe["volume"] > dataframe["volume_mean"] * self.buy_volume_factor.value
        dataframe["trend_score"] = trend_cond1.astype(int) + trend_cond2.astype(int) + trend_cond3.astype(int)

        range_entry = (dataframe["regime_trend"] == 0) & (dataframe["mr_score"] >= 2) & (dataframe["volume"] > 0)
        trend_entry = (dataframe["regime_trend"] == 1) & (dataframe["trend_score"] >= 2) & (dataframe["volume"] > 0)

        initial_entry = range_entry | trend_entry

        # === 追涨过滤模块：任意一个条件触发即禁止开仓 ===
        try:
            anti_chase_conditions = [
                dataframe["close"] > dataframe["ema_trend"] * (1 + self.anti_chase_max_dev.value),
                dataframe["rsi"] >= self.anti_chase_max_rsi.value,
                dataframe["bb_percent"] >= self.anti_chase_bb_percent.value,
                dataframe["adx_slope"] < self.anti_chase_adx_slope_min.value,
                dataframe["recent_pump"] >= self.anti_chase_recent_pump_max.value,
            ]
            chase_risk = pd.concat(anti_chase_conditions, axis=1).any(axis=1)
            chase_risk = chase_risk.fillna(False)
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"Anti-chase calculation error for {metadata['pair']}: {e}")
            chase_risk = pd.Series(False, index=dataframe.index)

        dataframe.loc[initial_entry & ~chase_risk, "enter_long"] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0

        # Range exit
        range_exit_cond1 = dataframe["rsi"] > self.sell_rsi_range.value
        range_exit_cond2 = dataframe["close"] > dataframe["bb_mid"]
        range_exit_cond3 = dataframe["close"] > dataframe["ema_fast"]
        dataframe["range_exit_score"] = range_exit_cond1.astype(int) + range_exit_cond2.astype(int) + range_exit_cond3.astype(int)

        # Trend exit
        trend_exit_cond1 = dataframe["rsi"] > self.sell_rsi_trend.value
        trend_exit_cond2 = dataframe["close"] < dataframe["ema_fast"]
        trend_exit_cond3 = dataframe["volume"] < dataframe["volume_mean"]
        dataframe["trend_exit_score"] = trend_exit_cond1.astype(int) + trend_exit_cond2.astype(int) + trend_exit_cond3.astype(int)

        range_exit = (dataframe["regime_trend"] == 0) & (dataframe["range_exit_score"] >= 2) & (dataframe["volume"] > 0)
        trend_exit = (dataframe["regime_trend"] == 1) & (dataframe["trend_exit_score"] >= 2) & (dataframe["volume"] > 0)

        dataframe.loc[range_exit | trend_exit, "exit_long"] = 1

        return dataframe

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                return self.stoploss

            entry_date = trade.open_date_utc
            if entry_date.tzinfo is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)

            mask = dataframe.index <= entry_date
            if not mask.any():
                return self.stoploss

            entry_candle = dataframe.loc[mask].iloc[-1]
            atr_at_entry = float(entry_candle.get("atr", 0.0))

            if atr_at_entry <= 0:
                return self.stoploss

            sl_atr = self.sell_atr_mult.value * atr_at_entry
            base_sl = max(self.stoploss, -sl_atr / trade.open_rate)

            if current_profit <= 0:
                return base_sl

            sl = base_sl
            if current_profit > 0.03:
                sl = max(sl, -0.01)
            if current_profit > 0.06:
                sl = max(sl, current_profit - 0.03)
            if current_profit > 0.10:
                sl = max(sl, current_profit - 0.05)

            return sl

        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Custom stoploss error for {pair}: {str(e)}")
            return self.stoploss

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "candles": True,
                "close": {"color": "black"},
                "ema_fast": {"color": "#1f77b4"},
                "ema_slow": {"color": "#ff7f0e"},
                "ema_trend": {"color": "#d62728"},
                "bb_lower": {"color": "gray", "fill_to": "bb_upper"},
                "bb_mid": {"color": "#9467bd"},
                "bb_upper": {"color": "gray"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "#ff7f0e"}},
                "ADX": {"adx": {"color": "#9467bd"}},
                "Volume": {"volume": {"color": "gray", "type": "bar"}, "volume_mean": {"color": "#1f77b4"}},
                "Regime": {"regime_trend": {"color": "#2ca02c", "type": "bar"}},
                "Scores": {
                    "mr_score": {"color": "#2ca02c", "type": "bar"},
                    "trend_score": {"color": "#d62728", "type": "bar"},
                },
            }
        }
