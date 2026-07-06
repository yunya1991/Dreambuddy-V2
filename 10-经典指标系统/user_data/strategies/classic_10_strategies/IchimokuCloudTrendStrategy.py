import pandas as pd
from datetime import datetime
from pandas import DataFrame
from typing import Optional

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, stoploss_from_open
from freqtrade.persistence import Trade

import talib.abstract as ta


class IchimokuCloudTrendStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short: bool = True

    minimal_roi = {
        "0": 0.094,
        "21": 0.069,
        "63": 0.018,
        "147": 0,
    }

    stoploss = -0.271
    trailing_stop = False
    use_custom_stoploss = True

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 300

    tenkan_period = IntParameter(5, 20, default=9, space="buy")
    kijun_period = IntParameter(10, 60, default=26, space="buy")
    senkou_b_period = IntParameter(30, 120, default=52, space="buy")
    displacement = IntParameter(10, 60, default=26, space="buy")

    atr_multiplier = DecimalParameter(1.5, 3.0, default=2.0, space="sell")
    trail_atr_multiplier = DecimalParameter(1.0, 2.0, default=1.5, space="sell")

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

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        high = dataframe["high"]
        low = dataframe["low"]

        tenkan = int(self.tenkan_period.value)
        kijun = int(self.kijun_period.value)
        senkou_b = int(self.senkou_b_period.value)
        disp = int(self.displacement.value)

        tenkan_sen = (high.rolling(tenkan).max() + low.rolling(tenkan).min()) / 2.0
        kijun_sen = (high.rolling(kijun).max() + low.rolling(kijun).min()) / 2.0

        span_a_raw = (tenkan_sen + kijun_sen) / 2.0
        span_b_raw = (high.rolling(senkou_b).max() + low.rolling(senkou_b).min()) / 2.0

        dataframe["tenkan_sen"] = tenkan_sen
        dataframe["kijun_sen"] = kijun_sen

        dataframe["span_a"] = span_a_raw
        dataframe["span_b"] = span_b_raw
        dataframe["cloud_top"] = pd.concat([span_a_raw, span_b_raw], axis=1).max(axis=1)
        dataframe["cloud_bottom"] = pd.concat([span_a_raw, span_b_raw], axis=1).min(axis=1)

        dataframe["span_a_plot"] = span_a_raw.shift(disp)
        dataframe["span_b_plot"] = span_b_raw.shift(disp)

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        prev_tenkan = dataframe["tenkan_sen"].shift(1)
        prev_kijun = dataframe["kijun_sen"].shift(1)

        cross_up = (dataframe["tenkan_sen"] > dataframe["kijun_sen"]) & (prev_tenkan <= prev_kijun)
        cross_dn = (dataframe["tenkan_sen"] < dataframe["kijun_sen"]) & (prev_tenkan >= prev_kijun)

        above_cloud = dataframe["close"] > dataframe["cloud_top"]
        below_cloud = dataframe["close"] < dataframe["cloud_bottom"]

        vol_ok = dataframe["volume"] > 0
        dataframe.loc[above_cloud & cross_up & vol_ok, ["enter_long", "enter_tag"]] = [1, "ichimoku_cloud_long"]
        dataframe.loc[below_cloud & cross_dn & vol_ok, ["enter_short", "enter_tag"]] = [1, "ichimoku_cloud_short"]

        conflict = (dataframe["enter_long"] == 1) & (dataframe["enter_short"] == 1)
        dataframe.loc[conflict, ["enter_long", "enter_short", "enter_tag"]] = [0, 0, ""]
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        prev_tenkan = dataframe["tenkan_sen"].shift(1)
        prev_kijun = dataframe["kijun_sen"].shift(1)
        cross_dn = (dataframe["tenkan_sen"] < dataframe["kijun_sen"]) & (prev_tenkan >= prev_kijun)
        cross_up = (dataframe["tenkan_sen"] > dataframe["kijun_sen"]) & (prev_tenkan <= prev_kijun)

        vol_ok = dataframe["volume"] > 0
        dataframe.loc[((dataframe["close"] < dataframe["kijun_sen"]) | cross_dn) & vol_ok, "exit_long"] = 1
        dataframe.loc[((dataframe["close"] > dataframe["kijun_sen"]) | cross_up) & vol_ok, "exit_short"] = 1
        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> float:
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
            if hasattr(self, "log"):
                self.log.error(f"Custom stoploss error for {pair}: {str(e)}")
            return 1.0

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        if current_profit <= 0:
            return None

        max_profit = trade.max_profit if hasattr(trade, "max_profit") else current_profit

        if max_profit > 0.05 and (max_profit - current_profit) > 0.03:
            return "trailing_profit_3pct"
        if max_profit > 0.10 and (max_profit - current_profit) > 0.04:
            return "trailing_profit_4pct"
        if max_profit > 0.15 and (max_profit - current_profit) > 0.05:
            return "trailing_profit_5pct"

        if current_profit > 0.10:
            return "take_profit_10"
        if current_profit > 0.05:
            return "take_profit_5"

        hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hold_hours > 24 and current_profit > 0.02:
            return "time_exit_profit"

        return None

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "close": {"color": "black"},
                "tenkan_sen": {"color": "blue"},
                "kijun_sen": {"color": "orange"},
                "span_a_plot": {"color": "gray", "fill_to": "span_b_plot"},
                "span_b_plot": {"color": "gray"},
            },
            "subplots": {
                "ATR": {"atr": {"color": "white"}},
                "Volume": {"volume": {"color": "gray", "type": "bar"}, "volume_mean": {"color": "blue"}},
            },
        }

