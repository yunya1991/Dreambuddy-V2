# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
import numpy as np
import pandas as pd
from pandas import DataFrame
from typing import Optional, Dict
from datetime import datetime, timezone

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, BooleanParameter, merge_informative_pair
from freqtrade.persistence import Trade
import talib.abstract as ta
from technical import qtpylib


class MarketRegimeControlModule:
    def __init__(self):
        self.ban_until: Optional[datetime] = None
        self.allow_window_until: Optional[datetime] = None
        self.top_conditions_count: int = 0
        self.bottom_conditions_count: int = 0

    def _get_closed_btc_daily(self, dp) -> DataFrame:
        try:
            btc_1d = dp.get_pair_dataframe("BTC/USDT", "1d")
            if len(btc_1d) < 61:
                return pd.DataFrame()
            return btc_1d.iloc[:-1].copy()
        except Exception:
            return pd.DataFrame()

    def update_regime(self, dp, current_time: datetime) -> Dict:
        return {"can_enter": True, "force_exit": False, "regime": "trend", "reason": "gate_relaxed"}


class RegimeHybridStrategy(IStrategy):
    """
    Regime Hybrid Strategy
    - Base timeframe: 5m
    - 4h gate / regime detection, trend uses TrendConfirmation-like entry, chop uses SimpleStrategy-like MR
    """
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short: bool = True
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 100

    minimal_roi = {"0": 0.10, "120": 0.05, "360": 0}
    stoploss = -0.25
    trailing_stop = False
    use_custom_stoploss = True

    # Parameters (trend side)
    ema_fast = IntParameter(20, 40, default=26, space="buy")
    ema_medium = IntParameter(40, 60, default=42, space="buy")
    ema_slow = IntParameter(70, 100, default=90, space="buy")
    adx_threshold = IntParameter(20, 30, default=22, space="buy")
    volume_mult = DecimalParameter(1.2, 3.0, default=1.50, space="buy")
    volume_vote_mult = DecimalParameter(1.0, 2.0, default=1.10, space="buy")
    entry_votes_required = IntParameter(3, 6, default=4, space="buy")

    enable_trend_breakout = BooleanParameter(default=False, space="buy")
    breakout_atr_buffer = DecimalParameter(0.0, 0.5, default=0.15, space="buy")
    breakout_volume_factor = DecimalParameter(0.8, 1.5, default=1.0, space="buy")
    breakout_max_atr_extension = DecimalParameter(0.5, 3.0, default=1.5, space="buy")

    adx_4h_trend = IntParameter(18, 40, default=25, space="buy")
    adx_4h_range = IntParameter(10, 25, default=16, space="buy")
    di_spread_min = IntParameter(2, 20, default=6, space="buy")
    bb_width_range_max = DecimalParameter(0.02, 0.20, default=0.08, space="buy")
    bb_width_expand_mult = DecimalParameter(1.05, 2.0, default=1.35, space="buy")
    donchian_period = IntParameter(15, 60, default=20, space="buy")

    # Parameters (chop side)
    buy_rsi = IntParameter(20, 30, default=25, space="buy")
    sell_rsi = IntParameter(70, 80, default=70, space="sell")
    tolerance_atr_mult = DecimalParameter(0.5, 2.0, default=2.0, space="buy")

    # ATR stop
    atr_multiplier = DecimalParameter(1.5, 3.0, default=1.7, space="sell")
    trail_atr_multiplier = DecimalParameter(1.0, 2.0, default=1.2, space="sell")
    short_min_rr = DecimalParameter(0.8, 2.0, default=1.05, space="sell")
    short_max_hold_hours = IntParameter(6, 72, default=24, space="sell")

    enable_vol_targeting = BooleanParameter(default=True, space="buy")
    vt_target_atr_pct = DecimalParameter(0.005, 0.06, default=0.015, space="buy")
    vt_min_scale = DecimalParameter(0.10, 1.00, default=0.25, space="buy")
    vt_max_scale = DecimalParameter(1.00, 3.00, default=1.50, space="buy")

    vr_low_atr_pct = DecimalParameter(0.005, 0.03, default=0.012, space="buy")
    vr_high_atr_pct = DecimalParameter(0.015, 0.08, default=0.030, space="buy")
    vr_sl_mult_low = DecimalParameter(0.60, 1.20, default=0.85, space="sell")
    vr_sl_mult_high = DecimalParameter(0.80, 1.80, default=1.15, space="sell")

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.regime_control = MarketRegimeControlModule()

    def informative_pairs(self):
        return []

    def _bollinger(self, dataframe: DataFrame):
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lowerband"] = bb["lower"]
        dataframe["bb_middleband"] = bb["mid"]
        dataframe["bb_upperband"] = bb["upper"]
    
    def _vwap(self, dataframe: DataFrame, window: int = 20):
        tp = (dataframe["high"] + dataframe["low"] + dataframe["close"]) / 3.0
        vol = dataframe["volume"].fillna(0)
        num = (tp * vol).rolling(window=window, min_periods=1).sum()
        den = vol.rolling(window=window, min_periods=1).sum()
        dataframe["vwap"] = (num / den).replace([np.inf, -np.inf], np.nan).ffill()
    
    def _supertrend(self, dataframe: DataFrame, period: int = 10, multiplier: float = 3.0):
        atr = ta.ATR(dataframe, timeperiod=period)
        if isinstance(atr, pd.Series):
            atr = atr.bfill().ffill().fillna(0)

        hl2 = (dataframe["high"] + dataframe["low"]) / 2.0
        upper_band = hl2 + (multiplier * atr)
        lower_band = hl2 - (multiplier * atr)

        close = dataframe["close"].to_numpy(dtype=float, copy=False)
        ub = upper_band.to_numpy(dtype=float, copy=False)
        lb = lower_band.to_numpy(dtype=float, copy=False)

        final_ub = np.zeros(len(dataframe))
        final_lb = np.zeros(len(dataframe))
        trend = np.ones(len(dataframe))

        final_ub[0] = ub[0]
        final_lb[0] = lb[0]

        for i in range(1, len(dataframe)):
            final_ub[i] = ub[i] if (ub[i] < final_ub[i - 1] or close[i - 1] > final_ub[i - 1]) else final_ub[i - 1]
            final_lb[i] = lb[i] if (lb[i] > final_lb[i - 1] or close[i - 1] < final_lb[i - 1]) else final_lb[i - 1]

            if trend[i - 1] == 1:
                trend[i] = -1 if close[i] <= final_lb[i] else 1
            else:
                trend[i] = 1 if close[i] >= final_ub[i] else -1

        dataframe["supertrend_ub"] = final_ub
        dataframe["supertrend_lb"] = final_lb
        dataframe["supertrend_direction"] = trend.astype(int)
    
    def _chandelier_long(self, dataframe: DataFrame, period: int = 22, k: float = 3.0):
        atr = ta.ATR(dataframe, timeperiod=period)
        hh = dataframe["high"].rolling(window=period, min_periods=1).max()
        dataframe["chandelier_long"] = (hh - atr * k).ffill()

    def _regime_series_from_4h(self, dataframe: DataFrame) -> pd.Series:
        adx = dataframe.get("adx_4h")
        plus_di = dataframe.get("plus_di_4h")
        minus_di = dataframe.get("minus_di_4h")
        bb_width = dataframe.get("bb_width_4h")
        bb_width_ma = dataframe.get("bb_width_ma_4h")
        ema20 = dataframe.get("ema20_4h")
        ema40 = dataframe.get("ema40_4h")

        if adx is None or plus_di is None or minus_di is None or bb_width is None or bb_width_ma is None or ema20 is None or ema40 is None:
            return pd.Series("range", index=dataframe.index)

        a = pd.to_numeric(adx, errors="coerce")
        p = pd.to_numeric(plus_di, errors="coerce")
        m = pd.to_numeric(minus_di, errors="coerce")
        w = pd.to_numeric(bb_width, errors="coerce")
        wma = pd.to_numeric(bb_width_ma, errors="coerce")
        e20 = pd.to_numeric(ema20, errors="coerce")
        e40 = pd.to_numeric(ema40, errors="coerce")

        di_spread = (p - m).abs()
        w_ok = np.isfinite(w)
        is_expanding = w_ok & np.isfinite(wma) & (wma > 0) & (w >= wma * float(self.bb_width_expand_mult.value))

        cond_no_trade_expanding = is_expanding & (a < float(self.adx_4h_trend.value))
        cond_range = (
            (a <= float(self.adx_4h_range.value))
            & (
                (w_ok & (w <= float(self.bb_width_range_max.value)))
                | ((~w_ok) & (di_spread <= 1.5 * float(self.di_spread_min.value)))
            )
        )
        cond_trend = (
            (a >= float(self.adx_4h_trend.value))
            & (p > m)
            & (di_spread >= float(self.di_spread_min.value))
            & np.isfinite(e20)
            & np.isfinite(e40)
            & (e20 >= e40)
        )

        cond_bear_trend = (
            (a >= float(self.adx_4h_trend.value))
            & (m > p)
            & (di_spread >= float(self.di_spread_min.value))
            & np.isfinite(e20)
            & np.isfinite(e40)
            & (e20 < e40)
        )

        cond_no_trade = cond_no_trade_expanding | cond_bear_trend

        regime = pd.Series("range", index=dataframe.index)
        regime = regime.mask(cond_trend.fillna(False), "trend")
        regime = regime.mask(cond_no_trade.fillna(False), "no_trade")
        return regime

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 30:
            return dataframe
        # 5m indicators
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=int(self.ema_fast.value))
        dataframe["ema_medium"] = ta.EMA(dataframe, timeperiod=int(self.ema_medium.value))
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=int(self.ema_slow.value))
        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["plus_di"] = ta.PLUS_DI(dataframe)
        dataframe["minus_di"] = ta.MINUS_DI(dataframe)
        macd = ta.MACD(dataframe)
        dataframe["macd"] = macd["macd"]
        dataframe["macdsignal"] = macd["macdsignal"]
        dataframe["macdhist"] = macd["macdhist"]
        self._bollinger(dataframe)
        dataframe["tema"] = ta.TEMA(dataframe, timeperiod=9)
        dataframe["sar"] = ta.SAR(dataframe)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = (dataframe["atr"] / dataframe["close"]).replace([np.inf, -np.inf], np.nan)
        dataframe["volume_mean"] = dataframe["volume"].rolling(window=20).mean()
        self._vwap(dataframe, window=20)
        self._supertrend(dataframe, period=10, multiplier=3.0)
        self._chandelier_long(dataframe, period=22, k=3.0)

        n = int(self.donchian_period.value)
        dataframe["donchian_high"] = dataframe["high"].rolling(window=n, min_periods=n).max().shift(1)
        dataframe["donchian_low"] = dataframe["low"].rolling(window=n, min_periods=n).min().shift(1)

        if "date" in dataframe.columns:
            base_idx = pd.to_datetime(dataframe["date"], utc=True)
        elif isinstance(dataframe.index, pd.DatetimeIndex):
            base_idx = dataframe.index
            if base_idx.tz is None:
                base_idx = base_idx.tz_localize("UTC")
            else:
                base_idx = base_idx.tz_convert("UTC")
        else:
            base_idx = None

        if base_idx is not None:
            ohlcv = dataframe[["open", "high", "low", "close", "volume"]].copy()
            ohlcv.index = base_idx
            resampled = (
                ohlcv.resample("4H", label="right", closed="right")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna()
            )
            if len(resampled) > 30:
                bb4 = qtpylib.bollinger_bands(qtpylib.typical_price(resampled), window=20, stds=2)
                resampled["bb_lower"] = bb4["lower"]
                resampled["bb_upper"] = bb4["upper"]
                resampled["bb_width"] = ((bb4["upper"] - bb4["lower"]) / bb4["mid"]).replace([np.inf, -np.inf], np.nan)
                resampled["bb_width_ma"] = resampled["bb_width"].rolling(window=10, min_periods=5).mean()
                resampled["bb_middle"] = bb4["mid"]
                resampled["adx"] = ta.ADX(resampled)
                resampled["plus_di"] = ta.PLUS_DI(resampled)
                resampled["minus_di"] = ta.MINUS_DI(resampled)
                resampled["ema20"] = ta.EMA(resampled, timeperiod=20)
                resampled["ema40"] = ta.EMA(resampled, timeperiod=40)
                resampled["ema_fast"] = ta.EMA(resampled, timeperiod=int(self.ema_fast.value))
                resampled["ema_medium"] = ta.EMA(resampled, timeperiod=int(self.ema_medium.value))
                resampled["ema_slow"] = ta.EMA(resampled, timeperiod=int(self.ema_slow.value))
                resampled["volume_mean"] = resampled["volume"].rolling(window=20).mean()
                resampled["atr"] = ta.ATR(resampled, timeperiod=14)
                self._supertrend(resampled, period=10, multiplier=3.0)

                aligned = resampled.reindex(base_idx, method="ffill")
                dataframe["bb_width_4h"] = aligned["bb_width"].to_numpy()
                dataframe["bb_width_ma_4h"] = aligned["bb_width_ma"].to_numpy()
                dataframe["bb_lower_4h"] = aligned["bb_lower"].to_numpy()
                dataframe["bb_middle_4h"] = aligned["bb_middle"].to_numpy()
                dataframe["bb_upper_4h"] = aligned["bb_upper"].to_numpy()
                dataframe["close_4h"] = aligned["close"].to_numpy()
                dataframe["volume_4h"] = aligned["volume"].to_numpy()
                dataframe["adx_4h"] = aligned["adx"].to_numpy()
                dataframe["plus_di_4h"] = aligned["plus_di"].to_numpy()
                dataframe["minus_di_4h"] = aligned["minus_di"].to_numpy()
                dataframe["ema20_4h"] = aligned["ema20"].to_numpy()
                dataframe["ema40_4h"] = aligned["ema40"].to_numpy()
                dataframe["ema_fast_4h"] = aligned["ema_fast"].to_numpy()
                dataframe["ema_medium_4h"] = aligned["ema_medium"].to_numpy()
                dataframe["ema_slow_4h"] = aligned["ema_slow"].to_numpy()
                dataframe["volume_mean_4h"] = aligned["volume_mean"].to_numpy()
                dataframe["supertrend_direction_4h"] = aligned["supertrend_direction"].to_numpy()
                dataframe["atr_4h"] = aligned["atr"].to_numpy()
                dataframe["atr_pct_4h"] = (aligned["atr"] / aligned["close"]).replace([np.inf, -np.inf], np.nan).to_numpy()

        # BTC 4h bear filter
        btc_4h = self.dp.get_pair_dataframe("BTC/USDT", "4h")
        if btc_4h is not None and not btc_4h.empty and len(btc_4h) > 30:
            try:
                btc_4h["btc_ema20"] = ta.EMA(btc_4h, timeperiod=20)
                btc_4h["btc_ema40"] = ta.EMA(btc_4h, timeperiod=40)
            except Exception:
                pass
            btc_inf = btc_4h[["date", "btc_ema20", "btc_ema40"]].copy()
            dataframe = merge_informative_pair(dataframe, btc_inf, self.timeframe, "4h", ffill=True)

        dataframe["regime4h"] = self._regime_series_from_4h(dataframe)

        if "atr_pct_4h" in dataframe.columns:
            atrp4 = pd.to_numeric(dataframe["atr_pct_4h"], errors="coerce")
        else:
            atrp4 = pd.Series(np.nan, index=dataframe.index)
        low_th = float(self.vr_low_atr_pct.value)
        high_th = float(self.vr_high_atr_pct.value)
        vr = pd.Series("mid", index=dataframe.index)
        vr = vr.mask(atrp4 <= low_th, "low")
        vr = vr.mask(atrp4 >= high_th, "high")
        dataframe["vol_regime_4h"] = vr
        e20 = dataframe.get("btc_ema20_4h")
        e40 = dataframe.get("btc_ema40_4h")
        if e20 is None or e40 is None:
            dataframe["btc_bear4h"] = False
        else:
            dataframe["btc_bear4h"] = (pd.to_numeric(e20, errors="coerce") < pd.to_numeric(e40, errors="coerce")).fillna(False)

        return dataframe

    def _regime_from_4h(self, dataframe: DataFrame) -> str:
        s = dataframe.get("regime4h")
        if s is None or len(s) < 1:
            s = self._regime_series_from_4h(dataframe)
        v = s.iloc[-1]
        if v in ("trend", "range", "no_trade"):
            return str(v)
        return "range"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            dataframe["enter_long"] = 0
            dataframe["enter_short"] = 0
            dataframe["enter_tag"] = ""
            return dataframe
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        # relaxed daily gate: always allow

        regime = dataframe.get("regime4h")
        if regime is None:
            regime = self._regime_series_from_4h(dataframe)
        is_trend = regime == "trend"
        is_range = regime == "range"
        is_no_trade = regime == "no_trade"

        vol_regime_4h = dataframe.get("vol_regime_4h")
        if vol_regime_4h is None or isinstance(vol_regime_4h, str):
            vol_regime_4h = pd.Series("mid", index=dataframe.index)
        allow_range_by_vol = (vol_regime_4h != "high")
        bear4h = dataframe.get("btc_bear4h")
        if bear4h is None or isinstance(bear4h, bool):
            bear4h = pd.Series(False, index=dataframe.index)

        pair_bear4h = pd.Series(False, index=dataframe.index)
        if "ema20_4h" in dataframe.columns and "ema40_4h" in dataframe.columns:
            pair_bear4h = (
                pd.to_numeric(dataframe["ema20_4h"], errors="coerce")
                < pd.to_numeric(dataframe["ema40_4h"], errors="coerce")
            ).fillna(False)

        bear_gate = bear4h | pair_bear4h
        bull4h = pd.Series(False, index=dataframe.index)
        if "btc_ema20_4h" in dataframe.columns and "btc_ema40_4h" in dataframe.columns:
            bull4h = (
                pd.to_numeric(dataframe["btc_ema20_4h"], errors="coerce")
                > pd.to_numeric(dataframe["btc_ema40_4h"], errors="coerce")
            ).fillna(False)
        pair_bull4h = pd.Series(False, index=dataframe.index)
        if "ema20_4h" in dataframe.columns and "ema40_4h" in dataframe.columns:
            pair_bull4h = (
                pd.to_numeric(dataframe["ema20_4h"], errors="coerce")
                > pd.to_numeric(dataframe["ema40_4h"], errors="coerce")
            ).fillna(False)
        bull_gate = bull4h | pair_bull4h

        donch_hi = dataframe["donchian_high"]
        trend_filter = (dataframe["close"] > dataframe["ema_medium"]) & (dataframe["supertrend_direction"] == 1)

        vote_conditions_4h = []
        if "ema_fast_4h" in dataframe.columns and "ema_medium_4h" in dataframe.columns and "ema_slow_4h" in dataframe.columns:
            vote_conditions_4h.append(
                (dataframe["ema_fast_4h"] > dataframe["ema_medium_4h"]) & (dataframe["ema_medium_4h"] > dataframe["ema_slow_4h"])
            )
        if "adx_4h" in dataframe.columns and "plus_di_4h" in dataframe.columns and "minus_di_4h" in dataframe.columns:
            vote_conditions_4h.append(
                (dataframe["adx_4h"] >= float(self.adx_4h_trend.value)) & (dataframe["plus_di_4h"] > dataframe["minus_di_4h"])
            )
        if "bb_middle_4h" in dataframe.columns:
            vote_conditions_4h.append(dataframe["close"] > dataframe["bb_middle_4h"])
        if "volume_4h" in dataframe.columns and "volume_mean_4h" in dataframe.columns:
            vote_conditions_4h.append(dataframe["volume_4h"] >= dataframe["volume_mean_4h"] * float(self.volume_vote_mult.value))
        if "supertrend_direction_4h" in dataframe.columns:
            vote_conditions_4h.append(dataframe["supertrend_direction_4h"] == 1)
        if "close_4h" in dataframe.columns:
            vote_conditions_4h.append((dataframe["close_4h"] > dataframe["close_4h"].shift(1)) | (dataframe["close_4h"] > dataframe["close_4h"].shift(2)))

        if vote_conditions_4h:
            dataframe["entry_votes_4h"] = sum(cond.astype(int) for cond in vote_conditions_4h)
        else:
            dataframe["entry_votes_4h"] = 0

        adx_cut = max(float(self.adx_threshold.value) - 5.0, 15.0)
        atr = pd.to_numeric(dataframe["atr"], errors="coerce")
        breakout_level = donch_hi + float(self.breakout_atr_buffer.value) * atr
        breakout_active = donch_hi.notna() & (dataframe["close"] > breakout_level)

        st_stable_ok = (dataframe["supertrend_direction"] == 1) & (dataframe["supertrend_direction"].shift(1) == 1)

        bb4h_ok = pd.Series(True, index=dataframe.index)
        if "bb_width_4h" in dataframe.columns and "bb_width_ma_4h" in dataframe.columns:
            w = pd.to_numeric(dataframe["bb_width_4h"], errors="coerce")
            wma = pd.to_numeric(dataframe["bb_width_ma_4h"], errors="coerce")
            bb4h_ok = (np.isfinite(w) & np.isfinite(wma) & (wma > 0) & (w >= wma)).fillna(False)

        not_too_extended = dataframe["close"] <= (breakout_level + float(self.breakout_max_atr_extension.value) * atr)
        breakout_signal = (
            breakout_active
            & qtpylib.crossed_above(dataframe["close"], breakout_level)
            & st_stable_ok
            & bb4h_ok
            & not_too_extended
            & (dataframe["adx"] >= adx_cut)
            & (dataframe["plus_di"] > dataframe["minus_di"])
            & (dataframe["volume"] >= dataframe["volume_mean"] * float(self.volume_mult.value) * float(self.breakout_volume_factor.value))
            & (dataframe["rsi"] < 70)
        )

        pullback = (
            (dataframe["low"] <= dataframe["ema_medium"]) &
            (dataframe["close"] > dataframe["ema_medium"]) &
            (dataframe["close"] > dataframe["open"]) &
            (dataframe["volume"] >= dataframe["volume_mean"] * 0.5) &
            (dataframe["rsi"] > 35) &
            (dataframe["rsi"] < 75)
        )

        trend_momo_ok = (
            (dataframe["macdhist"] > 0) &
            (dataframe["macd"] >= dataframe["macdsignal"])
        )
        if bool(self.enable_trend_breakout.value):
            dataframe.loc[
                is_trend & (~is_no_trade) & (~bear_gate) & trend_filter & breakout_signal & trend_momo_ok,
                ["enter_long", "enter_tag"],
            ] = [1, "trend_breakout"]
        dataframe.loc[is_trend & (~is_no_trade) & (~bear_gate) & trend_filter & pullback & ~breakout_active & trend_momo_ok, ["enter_long", "enter_tag"]] = [1, "trend_pullback"]

        conditions_5m = [
            (dataframe["ema_fast"] > dataframe["ema_medium"]) & (dataframe["ema_medium"] > dataframe["ema_slow"]),
            (dataframe["adx"] >= float(self.adx_threshold.value)) & (dataframe["plus_di"] > dataframe["minus_di"]),
            dataframe["close"] > dataframe["bb_middleband"],
            (dataframe["low"] > dataframe["ema_medium"]) | (dataframe["close"] > dataframe["vwap"]),
            dataframe["volume"] >= dataframe["volume_mean"] * float(self.volume_mult.value),
            dataframe["supertrend_direction"] == 1,
            dataframe["close"] > dataframe["chandelier_long"],
            (dataframe["macd"] >= dataframe["macdsignal"]) & (dataframe["macdhist"] > 0),
            (dataframe["rsi"] < 70) & (dataframe["rsi"] > 30),
            (dataframe["close"] > dataframe["close"].shift(1)) | (dataframe["close"] > dataframe["close"].shift(2)),
        ]
        dataframe["entry_votes_5m"] = sum(cond.astype(int) for cond in conditions_5m)

        trend_confirm_pullback = (
            (dataframe["low"] <= dataframe["ema_fast"]) &
            (dataframe["close"] > dataframe["ema_fast"]) &
            (dataframe["close"] > dataframe["ema_medium"]) &
            (dataframe["close"] <= (dataframe["ema_fast"] + 0.5 * dataframe["atr"]))
        )

        st_lb = dataframe.get("supertrend_lb")
        if st_lb is None:
            st_lb = pd.Series(np.nan, index=dataframe.index)
        st_dist_ok = dataframe["close"] > (pd.to_numeric(st_lb, errors="coerce") + 0.15 * dataframe["atr"])
        st_stable_ok = (dataframe["supertrend_direction"] == 1) & (dataframe["supertrend_direction"].shift(1) == 1)
        trend_confirm_entry = (
            is_trend
            & (~is_no_trade)
            & (~bear_gate)
            & trend_confirm_pullback
            & st_stable_ok
            & st_dist_ok
            & (dataframe["close"] > dataframe["open"])
            & (~breakout_active)
            & trend_momo_ok
            & (dataframe["volume"] >= dataframe["volume_mean"] * 0.8)
            & (dataframe["rsi"] < 65)
            & (dataframe["rsi"] > 38)
            & (dataframe["close"] < dataframe["bb_upperband"])
        )
        dataframe.loc[trend_confirm_entry, ["enter_long", "enter_tag"]] = [1, "trend_confirm"]

        try:
            entry_votes_req = int(self.entry_votes_required.value)
        except Exception:
            entry_votes_req = 4
        entry_votes_req_short = max(2, entry_votes_req - 1)
        votes5 = pd.to_numeric(dataframe["entry_votes_5m"], errors="coerce").fillna(0)
        votes4 = dataframe.get("entry_votes_4h")
        if votes4 is None or isinstance(votes4, (int, float)):
            votes4 = pd.Series(0, index=dataframe.index)
        votes4 = pd.to_numeric(votes4, errors="coerce").fillna(0)
        votes4_ok = pd.Series(True, index=dataframe.index)
        if "entry_votes_4h" in dataframe.columns:
            votes4_ok = votes4 >= 2
        fallback_trend = (
            (dataframe["enter_long"] == 0)
            & is_trend
            & (~is_no_trade)
            & (~bear_gate)
            & trend_filter
            & votes4_ok
            & (votes5 >= entry_votes_req)
        )
        dataframe.loc[fallback_trend, ["enter_long", "enter_tag"]] = [1, "trend_confirm"]

        was_below_lower = (dataframe["close"].shift(1) < dataframe["bb_lowerband"].shift(1)) | (dataframe["low"] < dataframe["bb_lowerband"])
        range_trend_ok = (dataframe["ema_medium"] >= dataframe["ema_slow"]) & (dataframe["close"] >= dataframe["vwap"])

        range_gate_4h = pd.Series(True, index=dataframe.index)
        if "adx_4h" in dataframe.columns:
            range_gate_4h = range_gate_4h & (pd.to_numeric(dataframe["adx_4h"], errors="coerce") <= float(self.adx_4h_range.value))
        if "bb_width_4h" in dataframe.columns:
            range_gate_4h = range_gate_4h & (pd.to_numeric(dataframe["bb_width_4h"], errors="coerce") <= float(self.bb_width_range_max.value))
        range_gate_4h = range_gate_4h.fillna(False)
        reclaim = (
            was_below_lower &
            (dataframe["close"] > dataframe["bb_lowerband"]) &
            (dataframe["close"] > dataframe["close"].shift(1)) &
            (dataframe["tema"] > dataframe["tema"].shift(1)) &
            (dataframe["rsi"] <= min(int(self.buy_rsi.value) + 12, 45)) &
            (dataframe["volume"] >= dataframe["volume_mean"] * 0.3) &
            ((dataframe["atr"] / dataframe["close"]) <= 0.02)
        )
        dataframe.loc[(dataframe["enter_long"] == 0) & (~is_no_trade) & is_range & allow_range_by_vol & range_gate_4h & reclaim & range_trend_ok & (~bear4h), ["enter_long", "enter_tag"]] = [1, "range_reclaim"]

        dip = (
            (dataframe["close"] < dataframe["bb_lowerband"] * 0.997) &
            (dataframe["close"] > dataframe["close"].shift(1)) &
            (dataframe["tema"] > dataframe["tema"].shift(1)) &
            (dataframe["rsi"] <= min(int(self.buy_rsi.value) + 6, 40)) &
            (dataframe["volume"] >= dataframe["volume_mean"] * 0.3) &
            ((dataframe["atr"] / dataframe["close"]) <= 0.02)
        )
        bear_dip_ok = (
            (dataframe["rsi"] <= min(int(self.buy_rsi.value) + 3, 36))
            & (dataframe["close"] < dataframe["bb_lowerband"] * 0.997)
        )
        dip_ok = (~bear4h) | (bear4h & bear_dip_ok)
        dataframe.loc[(dataframe["enter_long"] == 0) & (~is_no_trade) & is_range & allow_range_by_vol & range_gate_4h & dip & ~reclaim & range_trend_ok & dip_ok, ["enter_long", "enter_tag"]] = [1, "range_dip"]

        donch_lo = dataframe["donchian_low"]
        trend_filter_short = (dataframe["close"] < dataframe["ema_medium"]) & (dataframe["supertrend_direction"] == -1)
        adx_cut_short = max(float(self.adx_threshold.value) - 5.0, 15.0)
        breakdown_level = donch_lo - float(self.breakout_atr_buffer.value) * atr
        breakdown_active = donch_lo.notna() & (dataframe["close"] < breakdown_level)
        st_stable_short_ok = (dataframe["supertrend_direction"] == -1) & (dataframe["supertrend_direction"].shift(1) == -1)
        not_too_extended_short = dataframe["close"] >= (breakdown_level - float(self.breakout_max_atr_extension.value) * atr)
        breakout_signal_short = (
            breakdown_active
            & qtpylib.crossed_below(dataframe["close"], breakdown_level)
            & st_stable_short_ok
            & bb4h_ok
            & not_too_extended_short
            & (dataframe["adx"] >= adx_cut_short)
            & (dataframe["minus_di"] > dataframe["plus_di"])
            & (dataframe["volume"] >= dataframe["volume_mean"] * float(self.volume_mult.value) * float(self.breakout_volume_factor.value))
            & (dataframe["rsi"] > 30)
        )
        breakdown_followthrough = (
            breakdown_active
            & st_stable_short_ok
            & bb4h_ok
            & (dataframe["adx"] >= max(adx_cut_short - 3.0, 13.0))
            & (dataframe["minus_di"] > dataframe["plus_di"])
            & (dataframe["volume"] >= dataframe["volume_mean"] * float(self.volume_mult.value) * 0.8)
            & (dataframe["rsi"] > 32)
            & (dataframe["rsi"] < 68)
        )
        short_stop_dist = (atr * float(self.atr_multiplier.value)).clip(lower=1e-9)
        short_target_price = np.minimum(
            pd.to_numeric(dataframe.get("bb_middleband"), errors="coerce").fillna(dataframe["close"]),
            pd.to_numeric(donch_lo, errors="coerce").fillna(dataframe["close"]),
        )
        short_reward_dist = (dataframe["close"] - short_target_price).clip(lower=0.0)
        short_rr_est = short_reward_dist / short_stop_dist
        short_rr_quality = (
            np.isfinite(short_rr_est)
            & (short_rr_est >= float(self.short_min_rr.value))
            & (short_reward_dist > 0.0015 * dataframe["close"])
        )
        pullback_short = (
            (dataframe["high"] >= dataframe["ema_medium"]) &
            (dataframe["close"] < dataframe["ema_medium"]) &
            (dataframe["close"] < dataframe["open"]) &
            (dataframe["volume"] >= dataframe["volume_mean"] * 0.5) &
            (dataframe["rsi"] < 65) &
            (dataframe["rsi"] > 25)
        )
        trend_momo_short_ok = (
            (dataframe["macdhist"] < 0) &
            (dataframe["macd"] <= dataframe["macdsignal"])
        )
        vol_regime_4h = dataframe.get("vol_regime_4h")
        if vol_regime_4h is None:
            vol_regime_4h = pd.Series("mid", index=dataframe.index)
        vol_high_4h = pd.Series(vol_regime_4h, index=dataframe.index).astype(str).str.lower().eq("high")
        regime_no_trade_4h = pd.Series(regime, index=dataframe.index).astype(str).str.lower().eq("no_trade")
        risk_off_score_short = (
            bear_gate.astype(int)
            + (dataframe["close"] < dataframe["ema_slow"]).astype(int)
            + ((dataframe["minus_di"] > dataframe["plus_di"]) & (dataframe["macdhist"] < 0)).astype(int)
            + (vol_high_4h | regime_no_trade_4h).astype(int)
        )
        risk_off_short_threshold = 1
        risk_off_short_bucket = (risk_off_score_short >= risk_off_short_threshold) & bear_gate
        short_regime_state = is_trend | is_no_trade | is_range
        trend_short_gate = (~bull_gate) | (
            (dataframe["rsi"] > 62)
            & (dataframe["close"] < dataframe["ema_fast"])
            & (dataframe["supertrend_direction"] == -1)
        )
        if bool(self.enable_trend_breakout.value):
            dataframe.loc[
                short_regime_state & risk_off_short_bucket & trend_short_gate & trend_filter_short & short_rr_quality & (breakout_signal_short | breakdown_followthrough) & trend_momo_short_ok,
                ["enter_short", "enter_tag"],
            ] = [1, "trend_breakdown"]
        dataframe.loc[
            short_regime_state & risk_off_short_bucket & trend_short_gate & trend_filter_short & short_rr_quality & pullback_short & ~breakdown_active & trend_momo_short_ok,
            ["enter_short", "enter_tag"],
        ] = [1, "trend_reject"]
        fallback_trend_short = (
            (dataframe["enter_short"] == 0)
            & short_regime_state
            & risk_off_short_bucket
            & trend_short_gate
            & trend_filter_short
            & short_rr_quality
            & votes4_ok
            & (votes5 >= entry_votes_req_short)
            & (dataframe["minus_di"] > dataframe["plus_di"])
            & (dataframe["macdhist"] < 0)
        )
        dataframe.loc[fallback_trend_short, ["enter_short", "enter_tag"]] = [1, "trend_reject"]
        was_above_upper = (dataframe["close"].shift(1) > dataframe["bb_upperband"].shift(1)) | (dataframe["high"] > dataframe["bb_upperband"])
        range_trend_short_ok = (dataframe["ema_medium"] <= dataframe["ema_slow"]) & (dataframe["close"] <= dataframe["vwap"])
        reject = (
            was_above_upper &
            (dataframe["close"] < dataframe["bb_upperband"]) &
            (dataframe["close"] < dataframe["close"].shift(1)) &
            (dataframe["tema"] < dataframe["tema"].shift(1)) &
            (dataframe["rsi"] >= max(int(self.sell_rsi.value) - 12, 55)) &
            (dataframe["volume"] >= dataframe["volume_mean"] * 0.3) &
            ((dataframe["atr"] / dataframe["close"]) <= 0.02)
        )
        dataframe.loc[
            (dataframe["enter_short"] == 0) & (~is_no_trade) & is_range & allow_range_by_vol & range_gate_4h & risk_off_short_bucket & short_rr_quality & reject & range_trend_short_ok & (~bull4h),
            ["enter_short", "enter_tag"],
        ] = [1, "range_reject"]
        pop = (
            (dataframe["close"] > dataframe["bb_upperband"] * 1.003) &
            (dataframe["close"] < dataframe["close"].shift(1)) &
            (dataframe["tema"] < dataframe["tema"].shift(1)) &
            (dataframe["rsi"] >= max(int(self.sell_rsi.value) - 8, 60)) &
            (dataframe["volume"] >= dataframe["volume_mean"] * 0.3) &
            ((dataframe["atr"] / dataframe["close"]) <= 0.02)
        )
        bull_pop_ok = (
            (dataframe["rsi"] >= max(int(self.sell_rsi.value) - 4, 65))
            & (dataframe["close"] > dataframe["bb_upperband"] * 1.003)
        )
        pop_ok = (~bull4h) | (bull4h & bull_pop_ok)
        dataframe.loc[
            (dataframe["enter_short"] == 0) & (~is_no_trade) & is_range & allow_range_by_vol & range_gate_4h & risk_off_short_bucket & short_rr_quality & pop & ~reject & range_trend_short_ok & pop_ok,
            ["enter_short", "enter_tag"],
        ] = [1, "range_pop"]
        range_counter_short = (
            (dataframe["enter_short"] == 0)
            & is_range
            & (~is_no_trade)
            & risk_off_short_bucket
            & short_rr_quality
            & bull_gate
            & (dataframe["close"] > dataframe["bb_upperband"] * 1.008)
            & (dataframe["rsi"] >= max(int(self.sell_rsi.value) - 6, 64))
            & (dataframe["tema"] < dataframe["tema"].shift(1))
            & (dataframe["macdhist"] < dataframe["macdhist"].shift(1))
            & (dataframe["volume"] >= dataframe["volume_mean"] * 0.4)
        )
        dataframe.loc[range_counter_short, ["enter_short", "enter_tag"]] = [1, "range_counter_short"]

        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.populate_entry_trend(dataframe, metadata)
        if "buy" not in dataframe.columns:
            dataframe["buy"] = 0
        if "enter_long" in dataframe.columns:
            dataframe.loc[dataframe["enter_long"] == 1, "buy"] = 1
        if "buy_tag" not in dataframe.columns:
            if "enter_tag" in dataframe.columns:
                dataframe["buy_tag"] = dataframe["enter_tag"].fillna("")
            else:
                dataframe["buy_tag"] = ""
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        exit_long = (
            (dataframe["rsi"] > float(self.sell_rsi.value))
            | (dataframe["close"] < dataframe["ema_medium"])
            | ((dataframe["supertrend_direction"] < 0) & (dataframe["macdhist"] < 0))
        )
        exit_short = (
            (dataframe["rsi"] < float(self.buy_rsi.value))
            | (dataframe["close"] > dataframe["ema_medium"])
            | ((dataframe["supertrend_direction"] > 0) & (dataframe["macdhist"] > 0))
        )
        dataframe.loc[exit_long.fillna(False), "exit_long"] = 1
        dataframe.loc[exit_short.fillna(False), "exit_short"] = 1
        return dataframe

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.populate_exit_trend(dataframe, metadata)
        if "sell" not in dataframe.columns:
            dataframe["sell"] = 0
        if "exit_long" in dataframe.columns:
            dataframe.loc[dataframe["exit_long"] == 1, "sell"] = 1
        if "sell_tag" not in dataframe.columns:
            dataframe["sell_tag"] = ""
        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        try:
            def sl_from_price(stop_price: float) -> float:
                if not np.isfinite(stop_price) or stop_price <= 0 or not np.isfinite(current_rate) or current_rate <= 0:
                    return self.stoploss
                if bool(getattr(trade, "is_short", False)):
                    if stop_price <= current_rate:
                        return 0.0
                    return float((current_rate - stop_price) / current_rate)
                if stop_price >= current_rate:
                    return 0.0
                return float((stop_price / current_rate) - 1.0)

            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 20:
                return self.stoploss

            if isinstance(dataframe.index, pd.DatetimeIndex):
                if dataframe.index.tz is None:
                    dataframe = dataframe.set_index(dataframe.index.tz_localize("UTC"))
                else:
                    dataframe = dataframe.set_index(dataframe.index.tz_convert("UTC"))
            elif "date" in dataframe.columns:
                dataframe = dataframe.set_index(pd.to_datetime(dataframe["date"], utc=True))
            else:
                return self.stoploss
            entry_date = trade.open_date_utc
            if entry_date.tzinfo is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)
            mask = dataframe.index <= entry_date
            if not mask.any():
                return self.stoploss
            entry_row = dataframe.loc[mask].iloc[-1]
            atr_at_entry = entry_row.get("atr", 0)
            if pd.isna(atr_at_entry) or atr_at_entry <= 0:
                return self.stoploss
            current_atr = dataframe["atr"].iloc[-1]
            if pd.isna(current_atr) or current_atr <= 0:
                return self.stoploss

            initial_mult = float(self.atr_multiplier.value)
            trail_mult = float(self.trail_atr_multiplier.value)
            vr = str(entry_row.get("vol_regime_4h", "mid") or "mid")
            if vr == "low":
                adj = float(self.vr_sl_mult_low.value)
            elif vr == "high":
                adj = float(self.vr_sl_mult_high.value)
            else:
                adj = 1.0
            initial_mult *= adj
            trail_mult *= adj
            is_short = bool(getattr(trade, "is_short", False))
            enter_tag = str(getattr(trade, "enter_tag", "") or "")
            if (not is_short) and enter_tag == "trend_confirm":
                tc_mult = max(1.0, initial_mult * 0.75)
                st_lb_entry = float(entry_row.get("supertrend_lb", np.nan))
                st_sl = float("nan")
                if np.isfinite(st_lb_entry) and st_lb_entry > 0:
                    st_sl = st_lb_entry - 0.05 * float(atr_at_entry)
                initial_sl_price = trade.open_rate - (float(atr_at_entry) * tc_mult)
                if np.isfinite(st_sl):
                    initial_sl_price = max(float(initial_sl_price), float(st_sl))
            elif is_short:
                initial_sl_price = trade.open_rate + (atr_at_entry * initial_mult)
            else:
                initial_sl_price = trade.open_rate - (atr_at_entry * initial_mult)
            if is_short:
                if current_rate >= initial_sl_price:
                    return 0.0
            else:
                if current_rate <= initial_sl_price:
                    return 0.0

            r_pct = float((atr_at_entry * initial_mult) / trade.open_rate)
            if np.isfinite(r_pct) and r_pct > 0 and current_profit >= 0.8 * r_pct:
                trail_distance = current_atr * trail_mult
                stop_price = min(current_rate + trail_distance, trade.open_rate) if is_short else max(current_rate - trail_distance, trade.open_rate)
                return sl_from_price(float(stop_price))
            return sl_from_price(float(initial_sl_price))
        except Exception:
            return self.stoploss

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        try:
            hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600.0
            is_short = bool(getattr(trade, "is_short", False))
            if is_short and hold_hours > float(self.short_max_hold_hours.value):
                return "short_time_cap"
            enter_tag = str(getattr(trade, "enter_tag", "") or "")
            if hold_hours > 96 and current_profit < 0.005:
                return "time_cut_96h"
            if hold_hours > 72 and current_profit < -0.02:
                return "time_cut_loss_72h"

            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 50:
                return None

            if isinstance(dataframe.index, pd.DatetimeIndex):
                if dataframe.index.tz is None:
                    dataframe = dataframe.set_index(dataframe.index.tz_localize("UTC"))
                else:
                    dataframe = dataframe.set_index(dataframe.index.tz_convert("UTC"))
            elif "date" in dataframe.columns:
                dataframe = dataframe.set_index(pd.to_datetime(dataframe["date"], utc=True))

            last = dataframe.iloc[-1]
            prev = dataframe.iloc[-2]

            regime4 = self._regime_from_4h(dataframe)
            rsi = float(last.get("rsi", 50.0))
            tema = float(last.get("tema", last.get("close", current_rate)))
            tema_prev = float(prev.get("tema", tema))
            close = float(last.get("close", current_rate))
            bb_mid = float(last.get("bb_middleband", close))
            bb_up = float(last.get("bb_upperband", close))
            bb_low = float(last.get("bb_lowerband", close))

            entry_date = trade.open_date_utc
            if entry_date.tzinfo is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)
            mask = dataframe.index <= entry_date
            if mask.any():
                entry_row = dataframe.loc[mask].iloc[-1]
                atr_at_entry = float(entry_row.get("atr", np.nan))
                vr = str(entry_row.get("vol_regime_4h", "mid") or "mid")
            else:
                atr_at_entry = float("nan")
                vr = "mid"
            initial_mult = float(self.atr_multiplier.value)
            if vr == "low":
                initial_mult *= float(self.vr_sl_mult_low.value)
            elif vr == "high":
                initial_mult *= float(self.vr_sl_mult_high.value)
            if np.isfinite(atr_at_entry) and atr_at_entry > 0 and trade.open_rate > 0:
                r_pct = float((atr_at_entry * initial_mult) / trade.open_rate)
            else:
                r_pct = 0.01

            take_05r = max(0.5 * r_pct, 0.004)
            take_08r = max(0.8 * r_pct, 0.006)
            take_10r = max(1.0 * r_pct, 0.008)
            take_15r = max(1.5 * r_pct, 0.012)
            if current_profit >= max(0.18, 2.0 * take_15r):
                return "take_extreme_short" if is_short else "take_extreme"

            if is_short:
                if regime4 == "trend":
                    st_dir = int(last.get("supertrend_direction", -1))
                    ema_fast = float(last.get("ema_fast", close))
                    ema_med = float(last.get("ema_medium", close))
                    ema_fast_prev = float(prev.get("ema_fast", ema_fast))
                    ema_med_prev = float(prev.get("ema_medium", ema_med))
                    macd = float(last.get("macd", 0.0))
                    macds = float(last.get("macdsignal", 0.0))
                    macdh = float(last.get("macdhist", 0.0))
                    if current_profit >= take_15r and ((tema > tema_prev) or (macd > macds) or (st_dir > 0)):
                        return "trend_take_1p5r_short"
                    if current_profit >= take_10r and ((tema > tema_prev) and (rsi < 45)):
                        return "trend_take_1r_short"
                    if st_dir > 0:
                        return "trend_supertrend_flip_short"
                    if (ema_fast > ema_med) and (ema_fast_prev > ema_med_prev) and (macdh > 0):
                        return "trend_ema_flip_short"
                    if (macd > macds) and (macdh > 0):
                        return "trend_macd_up_short"
                    if hold_hours > 48 and current_profit < -0.01:
                        return "trend_time_cut_48h_short"
                    return None
                if current_profit >= take_08r and close <= bb_mid:
                    return "range_take_mid_short"
                if current_profit >= take_10r and close <= bb_low:
                    return "range_take_low_short"
                if current_profit >= max(take_05r, 0.006) and (tema > tema_prev) and (close < bb_mid):
                    return "range_reject_short"
                if rsi < float(self.buy_rsi.value) and (tema > tema_prev) and (tema < bb_mid):
                    return "range_rsi_tema_up_short"
                if close > bb_up and hold_hours > 12 and current_profit < -0.5 * take_10r:
                    return "range_fail_short"
                return None

            if regime4 == "trend":
                st_dir = int(last.get("supertrend_direction", 1))
                chandelier = float(last.get("chandelier_long", close))
                ema_fast = float(last.get("ema_fast", close))
                ema_med = float(last.get("ema_medium", close))
                ema_fast_prev = float(prev.get("ema_fast", ema_fast))
                ema_med_prev = float(prev.get("ema_medium", ema_med))
                macd = float(last.get("macd", 0.0))
                macds = float(last.get("macdsignal", 0.0))
                macdh = float(last.get("macdhist", 0.0))

                if enter_tag == "trend_confirm":
                    if hold_hours > 3 and current_profit < -0.004 and close < ema_fast:
                        return "tc_fast_fail_3h"
                    if hold_hours > 8 and current_profit < 0.001:
                        return "tc_time_cut_8h"
                    if current_profit < -max(0.006, 0.6 * take_10r) and close < ema_med:
                        return "tc_ema_fail"
                    if current_profit >= take_08r and ((tema < tema_prev) or (close < ema_fast)):
                        return "tc_take_0p8r"
                    if current_profit >= take_05r and (close < ema_fast) and (rsi > 52):
                        return "tc_protect"

                if current_profit >= take_15r and ((tema < tema_prev) or (macd < macds) or (close < chandelier)):
                    return "trend_take_1p5r"
                if current_profit >= take_10r and ((tema < tema_prev) and (rsi > 55)):
                    return "trend_take_1r"

                allow_fast_flip_exit = not (enter_tag == "trend_confirm" and hold_hours < 0.5)
                if allow_fast_flip_exit:
                    if st_dir < 0:
                        return "trend_supertrend_flip"
                    if close < chandelier:
                        return "trend_chandelier_break"
                    if (ema_fast < ema_med) and (ema_fast_prev < ema_med_prev) and (macdh < 0):
                        return "trend_ema_flip"
                    if (macd < macds) and (macdh < 0):
                        return "trend_macd_down"
                if hold_hours > 48 and current_profit < -0.01:
                    return "trend_time_cut_48h"
                return None

            if current_profit >= take_08r and close >= bb_mid:
                return "range_take_mid"
            if current_profit >= take_10r and close >= bb_up:
                return "range_take_up"
            if current_profit >= max(take_05r, 0.006) and (tema < tema_prev) and (close > bb_mid):
                return "range_reject"
            if rsi > float(self.sell_rsi.value) and (tema < tema_prev) and (tema > bb_mid):
                return "range_rsi_tema_down"
            if close < bb_low and hold_hours > 12 and current_profit < -0.5 * take_10r:
                return "range_fail"
            return None
        except Exception:
            return None

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float,
        max_stake: float,
        **kwargs,
    ) -> float:
        if not bool(self.enable_vol_targeting.value):
            return proposed_stake
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 50:
                return proposed_stake

            if isinstance(dataframe.index, pd.DatetimeIndex):
                idx = dataframe.index
                if idx.tz is None:
                    idx = idx.tz_localize("UTC")
                else:
                    idx = idx.tz_convert("UTC")
                dataframe = dataframe.set_index(idx)
            elif "date" in dataframe.columns:
                dataframe = dataframe.set_index(pd.to_datetime(dataframe["date"], utc=True))

            ct = current_time
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            mask = dataframe.index <= ct
            if not mask.any():
                return proposed_stake
            row = dataframe.loc[mask].iloc[-1]
            atr_pct = row.get("atr_pct_4h", np.nan)
            if pd.isna(atr_pct) or not np.isfinite(float(atr_pct)) or float(atr_pct) <= 0:
                atr_pct = row.get("atr_pct", np.nan)
            if pd.isna(atr_pct) or not np.isfinite(float(atr_pct)) or float(atr_pct) <= 0:
                return proposed_stake

            target = float(self.vt_target_atr_pct.value)
            scale = float(target / float(atr_pct))
            scale = float(np.clip(scale, float(self.vt_min_scale.value), float(self.vt_max_scale.value)))
            stake = float(proposed_stake) * scale

            stake = max(float(min_stake), stake)
            if np.isfinite(float(max_stake)) and float(max_stake) > 0:
                stake = min(float(max_stake), stake)
            return float(stake)
        except Exception:
            return proposed_stake

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "candles": True,
                "tema": {"color": "blue"},
                "bb_upperband": {"color": "gray", "fill_to": "bb_lowerband"},
                "bb_middleband": {"color": "orange"},
                "bb_lowerband": {"color": "gray"},
            },
            "subplots": {
                "MACD": {"macd": {"color": "blue"}, "macdsignal": {"color": "orange"}},
                "RSI": {"rsi": {"color": "red"}},
                "Volume": {"volume": {"color": "gray", "type": "bar"}, "volume_mean": {"color": "blue"}},
            },
        }
