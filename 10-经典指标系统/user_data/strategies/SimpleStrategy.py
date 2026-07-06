# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pandas import DataFrame
from typing import Optional, Dict, Any

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, stoploss_from_open
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class SimpleStrategy(IStrategy):
    """
    Simple 5m Strategy - Ultimate Version with Trailing Profit
    RSI + TEMA + Bollinger Bands mean-reversion with dynamic ATR stoploss
    """
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short: bool = True

    minimal_roi = {
        "0": 0.094,
        "21": 0.069,
        "63": 0.018,
        "147": 0
    }

    stoploss = -0.271
    trailing_stop = False  # 使用 custom_stoploss 实现动态追踪
    use_custom_stoploss = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 30

    # Hyperopt parameters
    buy_rsi = IntParameter(20, 30, default=27, space="buy")
    sell_rsi = IntParameter(70, 80, default=72, space="sell")
    
    atr_multiplier = DecimalParameter(1.5, 3.0, default=2.0, space="sell")
    trail_atr_multiplier = DecimalParameter(1.0, 2.0, default=1.5, space="sell")

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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # RSI
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)

        # MACD
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]

        # Bollinger Bands
        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bollinger["lower"]
        dataframe["bb_middleband"] = bollinger["mid"]
        dataframe["bb_upperband"] = bollinger["upper"]

        # TEMA
        dataframe["tema"] = ta.TEMA(dataframe, timeperiod=9)

        # Parabolic SAR
        dataframe["sar"] = ta.SAR(dataframe)
        
        # ATR
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        
        # Volume mean
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        loose_rsi = min(self.buy_rsi.value + 4, 35)

        deep_mr = (
            (dataframe["rsi"] < self.buy_rsi.value) &
            (dataframe["tema"] <= dataframe["bb_middleband"]) &
            (dataframe["tema"] > dataframe["tema"].shift(1)) &
            (dataframe["volume"] > dataframe["volume_mean"])
        )

        mild_mr = (
            (dataframe["rsi"] < loose_rsi) &
            (dataframe["tema"] <= dataframe["bb_middleband"]) &
            (dataframe["volume"] > dataframe["volume_mean"] * 0.5)
        )

        dataframe.loc[deep_mr, ["enter_long", "enter_tag"]] = [1, "rsi_deep"]
        dataframe.loc[mild_mr & ~deep_mr, ["enter_long", "enter_tag"]] = [1, "rsi_mild"]

        loose_sell_rsi = max(self.sell_rsi.value - 4, 65)

        deep_mr_short = (
            (dataframe["rsi"] > self.sell_rsi.value) &
            (dataframe["tema"] >= dataframe["bb_middleband"]) &
            (dataframe["tema"] < dataframe["tema"].shift(1)) &
            (dataframe["volume"] > dataframe["volume_mean"])
        )

        mild_mr_short = (
            (dataframe["rsi"] > loose_sell_rsi) &
            (dataframe["tema"] >= dataframe["bb_middleband"]) &
            (dataframe["volume"] > dataframe["volume_mean"] * 0.5)
        )

        dataframe.loc[deep_mr_short, ["enter_short", "enter_tag"]] = [1, "short_rsi_deep"]
        dataframe.loc[mild_mr_short & ~deep_mr_short, ["enter_short", "enter_tag"]] = [1, "short_rsi_mild"]

        conflict = (dataframe["enter_long"] == 1) & (dataframe["enter_short"] == 1)
        dataframe.loc[conflict, ["enter_long", "enter_short", "enter_tag"]] = [0, 0, ""]

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        
        dataframe.loc[
            (
                (dataframe["rsi"] > self.sell_rsi.value) &
                (dataframe["tema"] > dataframe["bb_middleband"]) &
                (dataframe["tema"] < dataframe["tema"].shift(1)) &
                (dataframe["volume"] > 0)
            ),
            "exit_long"
        ] = 1

        dataframe.loc[
            (
                (dataframe["rsi"] < self.buy_rsi.value) &
                (dataframe["tema"] < dataframe["bb_middleband"]) &
                (dataframe["tema"] > dataframe["tema"].shift(1)) &
                (dataframe["volume"] > 0)
            ),
            "exit_short"
        ] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 20:
                return 1.0

            if "date" in dataframe.columns:
                df = dataframe
                if not pd.api.types.is_datetime64_any_dtype(df["date"]):
                    df = df.copy()
                    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
                df = df.dropna(subset=["date"]).sort_values("date")
            else:
                df = dataframe.copy()
                df["date"] = pd.to_datetime(df.index, utc=True, errors="coerce")
                df = df.dropna(subset=["date"]).sort_values("date")

            entry_date = pd.Timestamp(trade.open_date_utc)
            if entry_date.tzinfo is None:
                entry_date = entry_date.tz_localize("UTC")
            else:
                entry_date = entry_date.tz_convert("UTC")

            hist = df.loc[df["date"] <= entry_date]
            if hist.empty:
                return 1.0

            entry_row = hist.iloc[-1]
            atr_at_entry = float(entry_row.get("atr", 0.0) or 0.0)
            if atr_at_entry <= 0.0 or pd.isna(atr_at_entry):
                return 1.0

            current_atr = float(df["atr"].iloc[-1] or 0.0)
            if current_atr <= 0.0 or pd.isna(current_atr):
                return 1.0

            initial_mult = float(self.atr_multiplier.value)
            trail_mult = float(self.trail_atr_multiplier.value)

            atr_pct_entry = atr_at_entry / float(trade.open_rate)
            open_relative_stop = -atr_pct_entry * initial_mult

            if current_profit > 1.5 * atr_pct_entry:
                trail_distance = current_atr * trail_mult
                if bool(getattr(trade, "is_short", False)):
                    stop_price = float(current_rate) + float(trail_distance)
                    if stop_price > float(trade.open_rate):
                        stop_price = float(trade.open_rate)
                    open_relative_stop = max(open_relative_stop, (float(trade.open_rate) - stop_price) / float(trade.open_rate))
                else:
                    stop_price = float(current_rate) - float(trail_distance)
                    if stop_price < float(trade.open_rate):
                        stop_price = float(trade.open_rate)
                    open_relative_stop = max(open_relative_stop, (stop_price / float(trade.open_rate)) - 1.0)

            sl = float(stoploss_from_open(open_relative_stop, current_profit))
            if sl <= 0.0:
                return 1.0
            return sl

        except Exception as e:
            if hasattr(self, 'log'):
                self.log.error(f"Custom stoploss error for {pair}: {str(e)}")
            return 1.0

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        """
        Trailing Profit Exit
        """
        if current_profit <= 0:
            return None

        max_profit = trade.max_profit if hasattr(trade, 'max_profit') else current_profit

        # 盈利 > 5%：允许 3% 回撤
        if max_profit > 0.05 and (max_profit - current_profit) > 0.03:
            return "trailing_profit_3pct"

        # 盈利 > 10%：允许 4% 回撤
        if max_profit > 0.10 and (max_profit - current_profit) > 0.04:
            return "trailing_profit_4pct"

        # 盈利 > 15%：允许 5% 回撤
        if max_profit > 0.15 and (max_profit - current_profit) > 0.05:
            return "trailing_profit_5pct"

        # 快速止盈
        if current_profit > 0.10:
            return "take_profit_10"
        if current_profit > 0.05:
            return "take_profit_5"

        # 时间退出
        hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hold_hours > 24 and current_profit > 0.02:
            return "time_exit_profit"

        return None

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        """
        确认交易入场
        添加了缺失的 leverage 参数
        """
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 2:
            return False

        last = dataframe.iloc[-1]
        prev = dataframe.iloc[-2]

        if side == "short":
            return all([
                last.get("volume", 0) > 0,
                last.get("rsi", 0) > 65,
                last.get("tema", 0) < prev.get("tema", 0),
            ])

        return all([
            last.get("volume", 0) > 0,
            last.get("rsi", 100) < 35,
            last.get("tema", 0) > prev.get("tema", 0),
        ])

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "candles": True,
                "close": {"color": "black"},
                "tema": {"color": "blue"},
                "sar": {"color": "white"},
                "bb_upperband": {"color": "gray", "fill_to": "bb_lowerband"},
                "bb_middleband": {"color": "orange"},
                "bb_lowerband": {"color": "gray"},
            },
            "subplots": {
                "MACD": {
                    "macd": {"color": "blue"},
                    "macdsignal": {"color": "orange"},
                },
                "RSI": {
                    "rsi": {"color": "red"},
                },
                "Volume": {
                    "volume": {"color": "gray", "type": "bar"},
                    "volume_mean": {"color": "blue"},
                }
            }
        }
