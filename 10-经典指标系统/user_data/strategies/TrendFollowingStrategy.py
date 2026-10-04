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


class TrendFollowingStrategy(IStrategy):
    """
    趋势跟随策略
    使用EMA快慢线交叉配合RSI确认趋势方向，顺势入场并设置止损。
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

    # ── Hyperopt 参数 ──────────────────────────────────────────────
    buy_ema_fast = IntParameter(5, 30, default=12, space="buy", optimize=True)
    buy_ema_slow = IntParameter(30, 100, default=50, space="buy", optimize=True)
    buy_rsi_low = IntParameter(30, 55, default=45, space="buy", optimize=True)
    buy_rsi_high = IntParameter(55, 80, default=70, space="buy", optimize=True)

    sell_ema_fast = IntParameter(5, 30, default=12, space="sell", optimize=True)
    sell_ema_slow = IntParameter(30, 100, default=50, space="sell", optimize=True)
    sell_rsi = IntParameter(40, 70, default=55, space="sell", optimize=True)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算策略所需的技术指标。"""
        # EMA 快慢线（使用最大范围以便 hyperopt 复用）
        for val in self.buy_ema_fast.range:
            dataframe[f"ema_fast_{val}"] = ta.EMA(dataframe, timeperiod=val)
        for val in self.buy_ema_slow.range:
            dataframe[f"ema_slow_{val}"] = ta.EMA(dataframe, timeperiod=val)

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # 成交量均值，用于过滤
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义入场信号。"""
        conditions = []

        # 快线在慢线之上（趋势向上）
        conditions.append(
            dataframe[f"ema_fast_{self.buy_ema_fast.value}"]
            > dataframe[f"ema_slow_{self.buy_ema_slow.value}"]
        )
        # 快线上穿慢线（金叉）
        conditions.append(
            qtpylib.crossed_above(
                dataframe[f"ema_fast_{self.buy_ema_fast.value}"],
                dataframe[f"ema_slow_{self.buy_ema_slow.value}"],
            )
        )
        # RSI 处于健康区间，确认动能
        conditions.append(dataframe["rsi"] > self.buy_rsi_low.value)
        conditions.append(dataframe["rsi"] < self.buy_rsi_high.value)
        # 成交量确认
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

        # 快线下穿慢线（死叉）离场
        conditions.append(
            qtpylib.crossed_below(
                dataframe[f"ema_fast_{self.sell_ema_fast.value}"],
                dataframe[f"ema_slow_{self.sell_ema_slow.value}"],
            )
        )
        # RSI 走弱确认
        conditions.append(dataframe["rsi"] < self.sell_rsi.value)
        # 成交量确认
        conditions.append(dataframe["volume"] > 0)

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x & y, conditions),
                'exit_long',
            ] = 1

        return dataframe