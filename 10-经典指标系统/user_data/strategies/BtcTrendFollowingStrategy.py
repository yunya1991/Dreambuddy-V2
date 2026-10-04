# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import functools
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class BtcTrendFollowingStrategy(IStrategy):
    """
    BTC 趋势跟随策略
    基于 EMA 趋势方向 + RSI 动量 + MACD 确认，在 1h 周期做多 BTC/USDT。
    """
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short: bool = False

    minimal_roi = {
        "0": 0.10,
        "60": 0.05,
        "120": 0.02,
        "240": 0.00,
    }

    stoploss = -0.05
    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.04
    trailing_only_offset_is_reached = True

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

    # ── Hyperopt 参数 ──────────────────────────────────────────────
    buy_rsi_max = IntParameter(55, 75, default=68, space="buy", optimize=True)
    buy_ema_fast = IntParameter(10, 30, default=20, space="buy", optimize=True)
    buy_ema_slow = IntParameter(40, 80, default=50, space="buy", optimize=True)
    buy_ema_trend = IntParameter(100, 200, default=150, space="buy", optimize=True)

    sell_rsi_min = IntParameter(65, 85, default=75, space="sell", optimize=True)
    sell_ema_fast = IntParameter(10, 30, default=20, space="sell", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算策略所需的技术指标。"""
        # EMA 趋势
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.buy_ema_fast.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.buy_ema_slow.value)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=self.buy_ema_trend.value)

        # RSI 动量
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # 成交量均线
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()

        # ATR 用于波动过滤
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义入场信号。"""
        conditions = []

        # 1. 多头趋势：快线在慢线之上，且价格在长期均线之上
        conditions.append(dataframe["ema_fast"] > dataframe["ema_slow"])
        conditions.append(dataframe["close"] > dataframe["ema_trend"])

        # 2. RSI 处于健康多头区间（未超买）
        conditions.append(dataframe["rsi"] > 50)
        conditions.append(dataframe["rsi"] < self.buy_rsi_max.value)

        # 3. MACD 多头动能
        conditions.append(dataframe["macd"] > dataframe["macdsignal"])

        # 4. 成交量确认
        conditions.append(dataframe["volume"] > 0)

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x & y, conditions),
                'enter_long',
            ] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义出场信号。"""
        conditions = []

        # 1. RSI 超买，动能过热
        conditions.append(dataframe["rsi"] > self.sell_rsi_min.value)

        # 2. 价格跌破快线（趋势走弱）
        conditions.append(dataframe["close"] < dataframe["ema_fast"])

        # 3. MACD 死叉（动能转空）
        conditions.append(dataframe["macd"] < dataframe["macdsignal"])

        # 4. 快线下穿慢线（趋势反转）
        conditions.append(dataframe["ema_fast"] < dataframe["ema_slow"])

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x | y, conditions),
                'exit_long',
            ] = 1

        return dataframe