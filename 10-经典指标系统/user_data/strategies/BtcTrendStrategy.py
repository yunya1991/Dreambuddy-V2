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


class BtcTrendStrategy(IStrategy):
    """
    BTC 趋势策略
    基于 EMA 快慢线趋势过滤 + RSI 动量 + MACD 确认的多头趋势跟随策略，适用于 1h 周期。
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
    buy_ema_fast = IntParameter(10, 40, default=20, space="buy", optimize=True)
    buy_ema_slow = IntParameter(40, 120, default=60, space="buy", optimize=True)
    buy_ema_trend = IntParameter(100, 200, default=150, space="buy", optimize=True)
    buy_rsi_min = IntParameter(40, 60, default=50, space="buy", optimize=True)
    buy_rsi_max = IntParameter(65, 85, default=75, space="buy", optimize=True)

    sell_rsi = IntParameter(70, 90, default=80, space="sell", optimize=True)
    sell_ema_fast = IntParameter(10, 40, default=20, space="sell", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算策略所需的技术指标。"""
        # EMA 均线组
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.buy_ema_fast.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.buy_ema_slow.value)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=self.buy_ema_trend.value)

        # 出场用 EMA
        dataframe["ema_exit"] = ta.EMA(dataframe, timeperiod=self.sell_ema_fast.value)

        # RSI 动量
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD 确认
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # ADX 趋势强度过滤
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)

        # 成交量均线
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义入场信号。"""
        conditions = []

        # 1. 快线在慢线之上（多头排列）
        conditions.append(dataframe["ema_fast"] > dataframe["ema_slow"])
        # 2. 慢线在长期趋势线之上（大趋势向上）
        conditions.append(dataframe["ema_slow"] > dataframe["ema_trend"])
        # 3. 价格在快线之上
        conditions.append(dataframe["close"] > dataframe["ema_fast"])
        # 4. RSI 处于健康多头区间
        conditions.append(dataframe["rsi"] > self.buy_rsi_min.value)
        conditions.append(dataframe["rsi"] < self.buy_rsi_max.value)
        # 5. MACD 多头
        conditions.append(dataframe["macd"] > dataframe["macdsignal"])
        # 6. ADX 趋势强度足够
        conditions.append(dataframe["adx"] > 20)
        # 7. 成交量确认
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

        # 1. RSI 超买，动量过热
        conditions.append(dataframe["rsi"] > self.sell_rsi.value)
        # 2. 价格跌破出场 EMA（趋势走弱）
        conditions.append(dataframe["close"] < dataframe["ema_exit"])
        # 3. MACD 死叉（柱状图转负）
        conditions.append(dataframe["macdhist"] < 0)
        # 4. 快线跌破慢线（趋势反转）
        conditions.append(dataframe["ema_fast"] < dataframe["ema_slow"])

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x | y, conditions),
                'exit_long',
            ] = 1

        return dataframe