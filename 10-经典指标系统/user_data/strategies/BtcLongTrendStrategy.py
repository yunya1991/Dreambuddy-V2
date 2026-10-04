# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
import functools
from datetime import datetime, timezone
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class BtcLongTrendStrategy(IStrategy):
    """
    比特币多头趋势策略
    基于 EMA 趋势过滤 + RSI 回调 + MACD 动能确认的顺势做多策略，适用于 1h 周期。
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
    buy_rsi_min = IntParameter(30, 55, default=40, space="buy", optimize=True)
    buy_rsi_max = IntParameter(55, 75, default=65, space="buy", optimize=True)
    buy_ema_fast = IntParameter(10, 30, default=20, space="buy", optimize=True)
    buy_ema_slow = IntParameter(40, 100, default=50, space="buy", optimize=True)
    buy_ema_trend = IntParameter(100, 200, default=200, space="buy", optimize=True)

    sell_rsi = IntParameter(65, 90, default=78, space="sell", optimize=True)
    sell_ema_fast = IntParameter(10, 30, default=20, space="sell", optimize=True)

    # ── 指标计算 ───────────────────────────────────────────────────
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """计算策略所需的技术指标。"""
        # 趋势均线
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_fast.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_slow.value))
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=int(self.buy_ema_trend.value))

        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe, fastperiod=12, slowperiod=26, signalperiod=9)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # 成交量均线
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()

        # ATR 用于辅助判断波动
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        return dataframe

    # ── 入场信号 ───────────────────────────────────────────────────
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义入场信号。"""
        conditions = []

        # 1. 趋势向上：快线在慢线之上，且价格在长期趋势线之上
        conditions.append(dataframe["ema_fast"] > dataframe["ema_slow"])
        conditions.append(dataframe["close"] > dataframe["ema_trend"])

        # 2. RSI 处于健康回调区间（不超买也不弱势）
        conditions.append(dataframe["rsi"] > self.buy_rsi_min.value)
        conditions.append(dataframe["rsi"] < self.buy_rsi_max.value)

        # 3. MACD 动能向上
        conditions.append(dataframe["macd"] > dataframe["macdsignal"])

        # 4. 成交量确认
        conditions.append(dataframe["volume"] > 0)

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x & y, conditions),
                'enter_long',
            ] = 1

        return dataframe

    # ── 出场信号 ───────────────────────────────────────────────────
    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """定义出场信号。"""
        conditions = []

        # 1. RSI 超买，动能衰竭
        conditions.append(dataframe["rsi"] > self.sell_rsi.value)

        # 2. 价格跌破快线（趋势转弱）
        conditions.append(dataframe["close"] < dataframe["ema_fast"])

        # 3. MACD 死叉（动能转空）
        conditions.append(dataframe["macd"] < dataframe["macdsignal"])

        # 4. 价格跌破长期趋势线（趋势破坏）
        conditions.append(dataframe["close"] < dataframe["ema_trend"])

        if conditions:
            dataframe.loc[
                functools.reduce(lambda x, y: x | y, conditions),
                'exit_long',
            ] = 1

        return dataframe