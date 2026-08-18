# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime
from pandas import DataFrame
from typing import Optional, Dict

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.enums import RunMode
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class _4hTrendStrategy003(IStrategy):
    INTERFACE_VERSION = 3
    #4h趋势+马丁格尔
    timeframe = "1h"
    can_short: bool = False
    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 200
    position_adjustment_enable = True
    max_entry_position_adjustment = 8

    minimal_roi = {
        "0": 0.209,
        "153": 0.146,
        "291": 0.076,
        "1048": 0.00
    }

    stoploss = -0.99
    trailing_stop = False

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    ema_fast = IntParameter(20, 40, default=26, space="buy")
    ema_medium = IntParameter(40, 60, default=42, space="buy")
    ema_slow = IntParameter(70, 100, default=90, space="buy")
    adx_threshold = IntParameter(20, 30, default=22, space="buy")
    volume_mult = DecimalParameter(1.0, 3.0, default=1.10, space="buy")
    entry_votes_required = IntParameter(3, 7, default=4, space="buy")
    st_period = IntParameter(7, 15, default=12, space="buy")
    st_multiplier = DecimalParameter(2.0, 4.0, default=2.6, space="buy")

    martingale_layers = IntParameter(1, 8, default=5, space="buy")
    martingale_multiplier = DecimalParameter(1.2, 3.0, default=2.0, space="buy")
    price_drop_threshold = DecimalParameter(0.01, 0.10, default=0.04, space="buy")
    min_add_position_interval_seconds = 1800
    max_atr_pct = DecimalParameter(0.01, 0.10, default=0.03, space="buy")

    weekly_filter_enable = IntParameter(0, 1, default=1, space="buy")
    weekly_allow_bear_rising = IntParameter(0, 1, default=1, space="buy")
    weekly_min_hist_slope_pct = DecimalParameter(0.0, 0.02, default=0.0, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.last_add_position_time: Dict[str, datetime] = {}

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: Optional[float],
        max_stake: float,
        leverage: float,
        entry_tag: Optional[str],
        side: str,
        **kwargs,
    ) -> float:
        layers = int(self.martingale_layers.value)
        multiplier = float(self.martingale_multiplier.value)
        if layers <= 0:
            target = proposed_stake
        elif multiplier <= 1.0:
            target = proposed_stake / float(layers + 1)
        else:
            total = sum(multiplier**k for k in range(layers + 1))
            target = proposed_stake / float(total)

        if min_stake is not None:
            target = max(float(min_stake), float(target))
        if max_stake is not None:
            target = min(float(max_stake), float(target))
        return float(target)

    def _weekly_market_pair(self) -> str:
        return "BTC/USDT:USDT" if self.config.get("trading_mode") == "futures" else "BTC/USDT"

    def informative_pairs(self):
        pairs = []
        try:
            pairs = self.dp.current_whitelist()
        except Exception:
            pairs = []
        return [(p, "4h") for p in pairs] + [(self._weekly_market_pair(), "1w")]

    def _compute_1w_market_filter(self, pair_1w: DataFrame) -> DataFrame:
        if pair_1w is None or pair_1w.empty or len(pair_1w) < 60:
            return DataFrame()

        df = pair_1w.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "close" in df.columns:
            df = df.loc[df["close"].notna()]
        if df.empty:
            return DataFrame()

        macd = ta.MACD(df)
        df["macd"] = macd["macd"]
        df["macd_signal"] = macd["macdsignal"]
        df["macd_hist"] = macd["macdhist"]

        df["macd_hist_pct"] = (df["macd_hist"] / df["close"]).replace([np.inf, -np.inf], np.nan)
        df["macd_hist_slope_pct"] = (df["macd_hist_pct"] - df["macd_hist_pct"].shift(1)).fillna(0.0)

        min_slope = float(self.weekly_min_hist_slope_pct.value)
        allow_bear_rising = int(self.weekly_allow_bear_rising.value) == 1

        bull = (df["macd_hist_pct"] > 0) & (df["macd_hist_slope_pct"] > min_slope)
        bear_rising = (df["macd_hist_pct"] < 0) & (df["macd_hist_slope_pct"] > min_slope)
        weekly_ok = bull | (bear_rising if allow_bear_rising else False)

        if "date" in df.columns:
            out = df[["date"]].copy()
            out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
        else:
            out = pd.DataFrame({"date": df.index})
            out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
        out["weekly_ok"] = weekly_ok.astype(int)
        return out

    def _compute_4h_entry_signal(self, pair_4h: DataFrame) -> DataFrame:
        if pair_4h is None or pair_4h.empty or len(pair_4h) < 100:
            return DataFrame()

        df = pair_4h.copy()
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "close" in df.columns:
            df = df.loc[df["close"].notna()]
        if df.empty:
            return DataFrame()

        df["ema_fast"] = ta.EMA(df, timeperiod=self.ema_fast.value)
        df["ema_medium"] = ta.EMA(df, timeperiod=self.ema_medium.value)
        df["ema_slow"] = ta.EMA(df, timeperiod=self.ema_slow.value)

        df["adx"] = ta.ADX(df)
        df["plus_di"] = ta.PLUS_DI(df)
        df["minus_di"] = ta.MINUS_DI(df)

        bb = qtpylib.bollinger_bands(qtpylib.typical_price(df), window=20, stds=2)
        df["bb_middle"] = bb["mid"]
        df["bb_upper"] = bb["upper"]
        df["bb_lower"] = bb["lower"]
        df["volume_mean"] = df["volume"].rolling(window=20).mean()

        atr_st = ta.ATR(df, timeperiod=self.st_period.value)
        hl2 = (df["high"] + df["low"]) / 2
        upper_band = hl2 + (self.st_multiplier.value * atr_st)
        lower_band = hl2 - (self.st_multiplier.value * atr_st)

        close = df["close"].values
        ub = upper_band.values
        lb = lower_band.values
        final_ub = np.zeros(len(df))
        final_lb = np.zeros(len(df))
        trend = np.ones(len(df))
        final_ub[0] = ub[0]
        final_lb[0] = lb[0]
        for i in range(1, len(df)):
            final_ub[i] = ub[i] if (ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1]) else final_ub[i - 1]
            final_lb[i] = lb[i] if (lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1]) else final_lb[i - 1]
            if trend[i - 1] == 1:
                trend[i] = -1 if close[i] <= final_lb[i] else 1
            else:
                trend[i] = 1 if close[i] >= final_ub[i] else -1
        df["supertrend_direction"] = trend.astype(int)

        atr_22 = ta.ATR(df, timeperiod=22)
        highest_high = df["high"].rolling(window=22).max()
        df["chandelier_long"] = highest_high - (atr_22 * 3.0)

        vwap_window = 50
        tp = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap"] = (tp * df["volume"]).rolling(window=vwap_window).sum() / df["volume"].rolling(window=vwap_window).sum()

        df["rsi"] = ta.RSI(df, timeperiod=14)
        macd = ta.MACD(df)
        df["macd"] = macd["macd"]
        df["macd_signal"] = macd["macdsignal"]
        df["macd_hist"] = macd["macdhist"]

        conditions = [
            (df["ema_fast"] > df["ema_medium"]) & (df["ema_medium"] > df["ema_slow"]),
            (df["adx"] >= self.adx_threshold.value) & (df["plus_di"] > df["minus_di"]),
            df["close"] > df["bb_middle"],
            (df["low"] > df["ema_medium"]) | (df["close"] > df["vwap"]),
            df["volume"] >= df["volume_mean"] * self.volume_mult.value,
            df["supertrend_direction"] == 1,
            df["close"] > df["chandelier_long"],
            (df["macd"] > df["macd_signal"]) & (df["macd_hist"] > 0),
            (df["rsi"] < 70) & (df["rsi"] > 30),
            (df["close"] > df["close"].shift(1)) | (df["close"] > df["close"].shift(2)),
        ]
        df["entry_votes"] = sum(cond.astype(int) for cond in conditions)
        entry_cond = (
            (df["entry_votes"] >= self.entry_votes_required.value)
            & (df["close"] > df["open"])
            & (df["volume"] > 0)
            & (df["rsi"] < 80)
        )
        if "date" in df.columns:
            out = df[["date"]].copy()
            out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
        else:
            out = pd.DataFrame({"date": df.index})
            out["date"] = pd.to_datetime(out["date"], utc=True, errors="coerce")
        out["entry_long"] = entry_cond.astype(int)
        return out

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe is None or dataframe.empty:
            return dataframe

        if "date" in dataframe.columns:
            dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")

        for col in ("open", "high", "low", "close", "volume"):
            if col in dataframe.columns:
                dataframe[col] = pd.to_numeric(dataframe[col], errors="coerce")
        if "close" in dataframe.columns:
            dataframe = dataframe.loc[dataframe["close"].notna()]
        if dataframe.empty:
            return dataframe

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = (dataframe["atr"] / dataframe["close"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)

        runmode = getattr(self.dp, "runmode", None) or self.config.get("runmode", RunMode.LIVE)

        pair_4h = None
        try:
            pair_4h = self.dp.get_pair_dataframe(metadata["pair"], "4h")
        except Exception:
            pair_4h = None

        sig_4h = self._compute_4h_entry_signal(pair_4h) if pair_4h is not None else DataFrame()
        if sig_4h is not None and not sig_4h.empty:
            dataframe = merge_informative_pair(dataframe, sig_4h, self.timeframe, "4h", ffill=True)
            if "entry_long_4h" in dataframe.columns:
                dataframe.rename(columns={"entry_long_4h": "entry_long_4h_signal"}, inplace=True)
        else:
            dataframe["entry_long_4h_signal"] = 0

        weekly_ok_default = 1
        if int(self.weekly_filter_enable.value) == 1:
            btc_weekly = None
            try:
                btc_weekly = self.dp.get_pair_dataframe(self._weekly_market_pair(), "1w")
                if runmode in [RunMode.LIVE, RunMode.DRY_RUN]:
                    if btc_weekly is not None and not btc_weekly.empty:
                        btc_weekly = btc_weekly.iloc[:-1].copy()
            except Exception:
                btc_weekly = None

            weekly_df = self._compute_1w_market_filter(btc_weekly) if btc_weekly is not None else DataFrame()
            if weekly_df is not None and not weekly_df.empty:
                dataframe = merge_informative_pair(dataframe, weekly_df[["date", "weekly_ok"]], self.timeframe, "1w", ffill=True)
                if "weekly_ok_1w" in dataframe.columns:
                    dataframe.rename(columns={"weekly_ok_1w": "weekly_ok_1w_filter"}, inplace=True)
                elif "weekly_ok" in dataframe.columns:
                    dataframe.rename(columns={"weekly_ok": "weekly_ok_1w_filter"}, inplace=True)
            else:
                dataframe["weekly_ok_1w_filter"] = weekly_ok_default
        else:
            dataframe["weekly_ok_1w_filter"] = weekly_ok_default

        if runmode in [RunMode.LIVE, RunMode.DRY_RUN]:
            current_ts = pd.Timestamp.utcnow()
            if "date_1w" in dataframe.columns:
                last_ts = pd.to_datetime(dataframe["date_1w"].iloc[-1], utc=True, errors="coerce")
                if pd.notna(last_ts) and (current_ts - last_ts) > pd.Timedelta(days=7):
                    dataframe["weekly_ok_1w_filter"] = 0

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        signal = dataframe.get("entry_long_4h_signal", 0)
        weekly_ok = dataframe.get("weekly_ok_1w_filter", 1)
        if isinstance(signal, pd.Series):
            signal_int = signal.fillna(0).astype(int)
            if int(self.weekly_filter_enable.value) == 1:
                weekly_ok_int = weekly_ok.fillna(1).astype(int) if isinstance(weekly_ok, pd.Series) else pd.Series(1, index=dataframe.index)
                effective = (signal_int == 1) & (weekly_ok_int == 1)
            else:
                effective = signal_int == 1
            enter_cond = effective & (~effective.shift(1).fillna(False))
            dataframe.loc[enter_cond, "enter_long"] = 1
        else:
            allow = True
            if int(self.weekly_filter_enable.value) == 1:
                allow = int(weekly_ok) == 1
            dataframe.loc[dataframe.index[-1], "enter_long"] = 1 if (int(signal) == 1 and allow) else 0
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        return dataframe

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        min_stake: Optional[float],
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ) -> Optional[float]:
        pair = trade.pair

        last_time = self.last_add_position_time.get(pair)
        if last_time is not None:
            ct = current_time
            lt = last_time
            if (ct.tzinfo is None) != (lt.tzinfo is None):
                if lt.tzinfo is None and ct.tzinfo is not None:
                    lt = lt.replace(tzinfo=ct.tzinfo)
                elif lt.tzinfo is not None and ct.tzinfo is None:
                    ct = ct.replace(tzinfo=lt.tzinfo)

            if (ct - lt).total_seconds() < self.min_add_position_interval_seconds:
                return None

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        df = None
        if dataframe is not None and not dataframe.empty:
            df = dataframe
            ts = pd.Timestamp(current_time)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            else:
                ts = ts.tz_convert("UTC")
            if "date" in df.columns:
                dt = pd.to_datetime(df["date"], utc=True, errors="coerce")
                df = df.loc[dt < ts]
            elif isinstance(df.index, pd.DatetimeIndex):
                df = df.loc[df.index < ts]

        profit_check = float(current_profit)
        if df is not None and not df.empty and "close" in df.columns:
            last_close = float(df["close"].iloc[-1])
            profit_check = (last_close - float(trade.open_rate)) / float(trade.open_rate)
        if profit_check >= 0:
            return None

        ref_rate = float(current_rate)
        if df is not None and not df.empty and "low" in df.columns:
            ref_rate = min(ref_rate, float(df["low"].iloc[-1]))

        price_change_pct = (ref_rate - float(trade.open_rate)) / float(trade.open_rate)
        if price_change_pct >= -float(self.price_drop_threshold.value):
            return None

        if df is not None and not df.empty and "atr_pct" in df.columns:
            if float(df["atr_pct"].iloc[-1]) > float(self.max_atr_pct.value):
                return None

        filled_entries = trade.select_filled_orders(trade.entry_side)
        if not filled_entries or len(filled_entries) - 1 >= self.martingale_layers.value:
            return None

        multiplier = float(self.martingale_multiplier.value) ** len(filled_entries)
        first_stake = filled_entries[0].cost
        target_stake = first_stake * multiplier
        if max_stake is not None:
            stake_amount = min(float(target_stake), float(max_stake))
        else:
            stake_amount = float(target_stake)

        if min_stake is not None:
            stake_amount = max(float(min_stake), float(stake_amount))

        if stake_amount <= 0:
            return None

        self.last_add_position_time[pair] = current_time
        return float(stake_amount)
