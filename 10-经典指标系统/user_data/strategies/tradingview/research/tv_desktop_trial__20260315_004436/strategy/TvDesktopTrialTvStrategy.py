import numpy as np
from pandas import DataFrame
from typing import Any, Dict, Optional
from datetime import datetime

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, stoploss_from_open
import talib.abstract as ta
from technical import qtpylib


class TvDesktopTrialTvStrategy(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1h"
    can_short: bool = False
    minimal_roi = {"0": 0.03, "120": 0.01, "300": 0.0}
    stoploss = -0.12
    use_custom_stoploss = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 50
    buy_rsi = IntParameter(20, 40, default=30, space="buy")
    sell_rsi = IntParameter(60, 85, default=70, space="sell")
    bb_std = DecimalParameter(1.5, 3.0, default=2.0, space="buy")
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    @property
    def plot_config(self) -> Dict[str, Any]:
        return {
            "main_plot": {
                "bb_lowerband": {},
                "bb_middleband": {},
                "bb_upperband": {}
            },
            "subplots": {
                "RSI": {
                    "rsi": {}
                }
            }
        }

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=float(self.bb_std.value))
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""
        dataframe.loc[
            (
                (dataframe["rsi"] < self.buy_rsi.value) &
                (dataframe["close"] < dataframe["bb_lowerband"]) &
                (dataframe["volume"] > 0)
            ),
            ["enter_long", "enter_tag"]
        ] = [1, "tv_long"]

        conflict = (dataframe["enter_long"] == 1) & (dataframe["enter_short"] == 1)
        dataframe.loc[conflict, ["enter_long", "enter_short", "enter_tag"]] = [0, 0, ""]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        dataframe.loc[
            (
                (dataframe["rsi"] > self.sell_rsi.value) |
                (dataframe["close"] > dataframe["bb_middleband"])
            ),
            "exit_long"
        ] = 1

        return dataframe
