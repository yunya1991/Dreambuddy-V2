import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone
from pandas import DataFrame
from typing import Dict, Optional, Union, Tuple

from freqtrade.strategy import IStrategy
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib

from BottomConfirmationModule import BottomConfirmationModule


class BottomConfirmationStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"

    can_short: bool = False

    minimal_roi = {
        "60": 0.01,
        "30": 0.02,
        "0": 0.04
    }

    stoploss = -0.10

    trailing_stop = False

    process_only_new_candles = True

    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = 30

    buy_rsi = 30
    sell_rsi = 70

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False
    }

    order_time_in_force = {
        "entry": "GTC",
        "exit": "GTC"
    }

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.bottom_module = BottomConfirmationModule(config)

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "tema": {},
                "sar": {"color": "white"},
            },
            "subplots": {
                "MACD": {
                    "macd": {"color": "blue"},
                    "macdsignal": {"color": "orange"},
                },
                "RSI": {
                    "rsi": {"color": "red"},
                },
                "BottomConfirm": {
                    "bottom_confirmation_score": {"color": "green"},
                },
            }
        }

    def informative_pairs(self):
        return []

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe)

        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]

        dataframe["tema"] = ta.TEMA(dataframe, timeperiod=9)

        dataframe["sar"] = ta.SAR(dataframe)

        dataframe = self.bottom_module.populate_indicators(dataframe)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        bottom_cond = self.bottom_module.get_entry_condition(dataframe)

        dataframe.loc[
            (
                bottom_cond &
                (dataframe["rsi"] < self.buy_rsi) &
                (dataframe["tema"] <= dataframe["bb_middleband"]) &
                (dataframe["tema"] > dataframe["tema"].shift(1)) &
                (dataframe["volume"] > 0)
            ),
            "enter_long"] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (
                (dataframe["rsi"] > self.sell_rsi) &
                (dataframe["tema"] > dataframe["bb_middleband"]) &
                (dataframe["tema"] < dataframe["tema"].shift(1)) &
                (dataframe["volume"] > 0)
            ),
            "exit_long"] = 1
        return dataframe
