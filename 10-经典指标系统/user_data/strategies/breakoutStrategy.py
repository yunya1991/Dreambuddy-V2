# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
import numpy as np
import pandas as pd
from pandas import DataFrame
from typing import Optional, Dict
from datetime import datetime, timedelta
from datetime import timezone
import os
import requests
from urllib.parse import urlparse

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade
import talib.abstract as ta


class BottomConfirmationModule:
    """
    模块化底部确认组件
    """
    def __init__(self, accel_thr: float = 0.10):
        self.accel_thr = accel_thr

    def calculate_vwap(self, dataframe: DataFrame, window: int = 50) -> pd.Series:
        typical_price = (dataframe['high'] + dataframe['low'] + dataframe['close']) / 3
        volume_sum = dataframe['volume'].rolling(window=window, min_periods=1).sum()
        # 安全处理：volume_sum 为 0 时用 1 代替，避免 NaN
        volume_sum = volume_sum.replace(0, 1)
        
        vwap = (typical_price * dataframe['volume']).rolling(window=window, min_periods=1).sum() / volume_sum
        return vwap.ffill()

    def calculate_cvd(self, dataframe: DataFrame) -> pd.Series:
        price_change = dataframe['close'].diff()
        buy_vol = np.where(price_change > 0, dataframe['volume'], 0)
        sell_vol = np.where(price_change < 0, dataframe['volume'], 0)
        
        cvd = (buy_vol - sell_vol).cumsum()
        return cvd

    def populate_indicators(self, dataframe: DataFrame) -> DataFrame:
        if len(dataframe) < 20:
            dataframe['bottom_confirmation_score'] = 0
            return dataframe

        # 安全计算收益率
        close_shifted = dataframe['close'].shift(1)
        close_shifted = close_shifted.replace(0, np.nan)
        close_shifted = close_shifted.fillna(dataframe['close'])
        dataframe['ret'] = np.log(dataframe['close'] / close_shifted)

        dataframe['speed_short'] = dataframe['ret'].rolling(3, min_periods=1).mean()
        dataframe['speed_mid'] = dataframe['ret'].rolling(6, min_periods=1).mean()
        dataframe['speed_long'] = dataframe['ret'].rolling(12, min_periods=1).mean()

        dataframe['pump_acceleration'] = (
            (dataframe['speed_short'] > dataframe['speed_mid'] * (1 + self.accel_thr)) &
            (dataframe['speed_short'] > dataframe['speed_short'].shift(1)) &
            (dataframe['speed_mid'] < dataframe['speed_long']) &
            (dataframe['speed_mid'] < 0) &
            (dataframe['speed_long'] <= 0)
        ).astype(int)

        dataframe['vol_mean'] = dataframe['volume'].rolling(20, min_periods=1).mean()
        dataframe['vol_std'] = dataframe['volume'].rolling(20, min_periods=1).std()
        # 安全处理除零：用极小值代替 0
        dataframe['vol_std'] = dataframe['vol_std'].replace(0, 1e-8)
        dataframe['vol_z'] = (dataframe['volume'] - dataframe['vol_mean']) / dataframe['vol_std']
        dataframe['vol_z'] = dataframe['vol_z'].fillna(0)
        dataframe['vol_anomaly'] = (dataframe['vol_z'] > 2.0).astype(int)

        dataframe['vwap'] = self.calculate_vwap(dataframe, window=50)
        dataframe['vwap_support'] = (
            (dataframe['close'] > dataframe['vwap']) &
            (dataframe['low'] < dataframe['vwap'])
        ).astype(int)

        dataframe['cvd'] = self.calculate_cvd(dataframe)
        dataframe['cvd_delta'] = dataframe['cvd'].diff()
        pct_change = dataframe['close'].pct_change()
        dataframe['absorption'] = (
            (pct_change > 0) &
            (dataframe['cvd_delta'] < 0)
        ).astype(int)

        macd_line, macd_signal, macd_hist = ta.MACD(dataframe['close'])
        dataframe['macd'] = macd_line
        dataframe['macdsignal'] = macd_signal
        dataframe['momentum_turn_up'] = (
            (dataframe['macd'] > dataframe['macdsignal']) &
            (dataframe['macd'].shift(1) <= dataframe['macdsignal'].shift(1))
        ).astype(int)

        dataframe['bottom_confirmation_score'] = (
            dataframe['pump_acceleration'] +
            dataframe['vol_anomaly'] +
            dataframe['vwap_support'] +
            dataframe['absorption'] +
            dataframe['momentum_turn_up']
        ).fillna(0)

        return dataframe

    def get_entry_condition(self, dataframe: DataFrame, threshold: int = 2) -> pd.Series:
        return dataframe['bottom_confirmation_score'] >= threshold


class BreakoutStrategy(IStrategy):
    """
    1h Breakout Strategy with Voting Logic + Bottom Confirmation (Spot)
    - 入场过滤：纯4h BTC MACD Histogram 斜率为正
    - 出场信号：4h MACD Histogram 连续2根斜率为负
    - RSI 出场改为超买 >70
    """
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = True

    minimal_roi = {
        "0": 0.50,
        "22": 0.20,
        "165": 0.10,
        "222": 0
    }

    stoploss = -0.05
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 100

    tolerance_atr_mult = DecimalParameter(0.5, 2.0, default=2.0, space="buy")
    donchian_window = IntParameter(20, 100, default=20, space="buy")
    
    bottom_accel_thr = DecimalParameter(0.05, 0.20, default=0.20, space="buy")
    bottom_confirmation_threshold = IntParameter(1, 5, default=2, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.bottom_module = BottomConfirmationModule(accel_thr=self.bottom_accel_thr.value)
        self._ml_export_last_ts_by_pair: Dict[str, int] = {}
        self._ml_decision_last_ts_by_pair: Dict[str, int] = {}

    def informative_pairs(self):
        return [("BTC/USDT", "4h")]

    def calculate_cmf(self, dataframe: DataFrame, window=20) -> pd.Series:
        hl_range = dataframe['high'] - dataframe['low']
        hl_range = hl_range.replace(0, 1e-8)  # 防止除零
        
        mf_multiplier = ((dataframe['close'] - dataframe['low']) - (dataframe['high'] - dataframe['close'])) / hl_range
        mf_multiplier = mf_multiplier.fillna(0)
        mf_volume = mf_multiplier * dataframe['volume']
        
        volume_sum = dataframe['volume'].rolling(window=window, min_periods=1).sum()
        volume_sum = volume_sum.replace(0, 1)  # 防止除零
        
        cmf = mf_volume.rolling(window=window, min_periods=1).sum() / volume_sum
        return cmf.fillna(0)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if "date" in dataframe.columns:
            dataframe["date"] = pd.to_datetime(dataframe["date"], utc=True, errors="coerce")

        try:
            self.bottom_module.accel_thr = float(self.bottom_accel_thr.value)
        except Exception as e:
            bad_val = getattr(self.bottom_accel_thr, "value", None)
            if getattr(self, "_logged_bottom_accel_thr_error", None) != bad_val:
                if hasattr(self, "logger"):
                    self.logger.warning(f"Invalid bottom_accel_thr={bad_val}: {e}")
                self._logged_bottom_accel_thr_error = bad_val

        # 默认4h信号为 False（安全失败）
        dataframe["btc_4h_macd_hist_positive_slope"] = False
        dataframe["btc_4h_macd_hist_negative_slope_2"] = False

        if len(dataframe) < 50:
            return dataframe

        dataframe['atr'] = ta.ATR(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)
        dataframe['rsi'] = ta.RSI(dataframe['close'], timeperiod=14)
        dataframe['ema_20'] = ta.EMA(dataframe['close'], timeperiod=20)
        dataframe['ema_50'] = ta.EMA(dataframe['close'], timeperiod=50)

        donchian_window = self.donchian_window.value
        dataframe['donchian_upper'] = dataframe['high'].rolling(window=donchian_window, min_periods=1).max()
        dataframe['donchian_lower'] = dataframe['low'].rolling(window=donchian_window, min_periods=1).min()
        dataframe['donchian_middle'] = (dataframe['donchian_upper'] + dataframe['donchian_lower']) / 2

        dataframe['volume_mean'] = dataframe['volume'].rolling(window=20, min_periods=1).mean()
        dataframe['vroc_12'] = dataframe['volume'].pct_change(periods=12) * 100
        dataframe['vroc_12'] = dataframe['vroc_12'].fillna(0)

        dataframe['close_mean'] = dataframe['close'].rolling(window=20, min_periods=1).mean()
        dataframe['close_std'] = dataframe['close'].rolling(window=20, min_periods=1).std()
        dataframe['close_std'] = dataframe['close_std'].replace(0, 1e-8)
        dataframe['z_score'] = (dataframe['close'] - dataframe['close_mean']) / dataframe['close_std']
        dataframe['z_score'] = dataframe['z_score'].fillna(0)

        dataframe['cmf'] = self.calculate_cmf(dataframe, 20)

        dataframe['obv'] = ta.OBV(dataframe['close'], dataframe['volume'])
        dataframe['obv_high_20'] = dataframe['obv'].rolling(window=20, min_periods=1).max()
        dataframe['obv_low_20'] = dataframe['obv'].rolling(window=20, min_periods=1).min()

        macd_line, macd_signal, macd_hist = ta.MACD(dataframe['close'])
        dataframe['macd'] = macd_line
        dataframe['macdsignal'] = macd_signal
        dataframe['macdhist'] = macd_hist

        dataframe = self.bottom_module.populate_indicators(dataframe)

        # 4h BTC MACD Histogram 斜率
        btc_4h = self.dp.get_pair_dataframe("BTC/USDT", "4h")
        if btc_4h is not None and not btc_4h.empty and len(btc_4h) > 26:  # 确保足够数据计算MACD
            if "date" in btc_4h.columns:
                btc_4h["date"] = pd.to_datetime(btc_4h["date"], utc=True, errors="coerce")
                btc_4h = btc_4h.dropna(subset=["date"])
                btc_4h = btc_4h.sort_values("date")
                btc_4h = btc_4h.drop_duplicates(subset=["date"], keep="last")
                if len(btc_4h) > 1:
                    btc_4h = btc_4h.iloc[:-1].copy()

            macd_line, macd_signal, macd_hist = ta.MACD(btc_4h["close"], fastperiod=12, slowperiod=26, signalperiod=9)
            btc_4h["macdhist"] = pd.to_numeric(macd_hist, errors="coerce")
            btc_4h["macd_hist_positive_slope"] = btc_4h["macdhist"] > btc_4h["macdhist"].shift(1)
            btc_4h["macd_hist_negative_slope_2"] = (btc_4h["macdhist"] < btc_4h["macdhist"].shift(1)) & (btc_4h["macdhist"].shift(1) < btc_4h["macdhist"].shift(2))

            informative_4h = btc_4h[["date", "macd_hist_positive_slope", "macd_hist_negative_slope_2"]].copy()
            dataframe = merge_informative_pair(dataframe, informative_4h, self.timeframe, "4h", ffill=True)
            dataframe["btc_4h_macd_hist_positive_slope"] = dataframe["macd_hist_positive_slope_4h"].fillna(False)
            dataframe["btc_4h_macd_hist_negative_slope_2"] = dataframe["macd_hist_negative_slope_2_4h"].fillna(False)
            dataframe.drop(columns=["macd_hist_positive_slope_4h", "macd_hist_negative_slope_2_4h"], inplace=True, errors="ignore")

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            dataframe['enter_long'] = 0
            dataframe['enter_short'] = 0
            dataframe['enter_tag'] = ''
            return dataframe

        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = ''

        cond_breakout = (
            dataframe['close'] > (dataframe['donchian_upper'].shift(1) - (dataframe['atr'] * self.tolerance_atr_mult.value))
        )

        cond_volume_mix = (
            (dataframe['volume'] > dataframe['volume_mean'] * 1.5) |
            (dataframe['vroc_12'] > 15) |
            (dataframe['z_score'] > 1.5)
        )

        cond_cmf = (dataframe['cmf'] > 0)

        cond_obv = (dataframe['obv'] > dataframe['obv_high_20'].shift(1) * 0.995)

        cond_vroc_explosive = (dataframe['vroc_12'] > 40)

        dataframe['buy_votes'] = (
            cond_breakout.astype(int) +
            cond_volume_mix.astype(int) +
            cond_cmf.astype(int) +
            cond_obv.astype(int) +
            cond_vroc_explosive.astype(int)
        )
        cond_breakdown_short = (
            dataframe['close'] < (dataframe['donchian_lower'].shift(1) + (dataframe['atr'] * self.tolerance_atr_mult.value))
        )
        cond_volume_mix_short = (
            (dataframe['volume'] > dataframe['volume_mean'] * 1.5) |
            (dataframe['vroc_12'] < -15) |
            (dataframe['z_score'] < -1.5)
        )
        cond_cmf_short = (dataframe['cmf'] < 0)
        cond_obv_short = (dataframe['obv'] < dataframe['obv_low_20'].shift(1) * 1.005)
        cond_vroc_explosive_short = (dataframe['vroc_12'] < -40)
        dataframe['sell_votes'] = (
            cond_breakdown_short.astype(int) +
            cond_volume_mix_short.astype(int) +
            cond_cmf_short.astype(int) +
            cond_obv_short.astype(int) +
            cond_vroc_explosive_short.astype(int)
        )

        bottom_confirmed = self.bottom_module.get_entry_condition(
            dataframe, 
            threshold=self.bottom_confirmation_threshold.value
        )
        dataframe["bottom_confirmed"] = bottom_confirmed.fillna(False).astype(bool)
        atr_pct = (dataframe["atr"] / dataframe["close"]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        min_votes_long = np.where(atr_pct > 0.018, 3, 2)
        min_votes_short = np.where(atr_pct > 0.018, 3, 2)
        cooldown_long_bars = 10
        cooldown_short_bars = 10
        trend_up = dataframe["ema_20"] > dataframe["ema_50"]
        trend_down = dataframe["ema_20"] < dataframe["ema_50"]
        breakout_followthrough_long = (
            dataframe["close"] > (dataframe["donchian_upper"].shift(1) + 0.10 * dataframe["atr"])
        ) & (dataframe["close"] > dataframe["close"].shift(1))
        breakdown_followthrough_short = (
            dataframe["close"] < (dataframe["donchian_lower"].shift(1) - 0.10 * dataframe["atr"])
        ) & (dataframe["close"] < dataframe["close"].shift(1))
        breakout_quality_long = cond_breakout & trend_up & breakout_followthrough_long & (dataframe["volume"] > dataframe["volume_mean"] * 0.8)
        breakdown_quality_short = cond_breakdown_short & trend_down & breakdown_followthrough_short & (dataframe["volume"] > dataframe["volume_mean"] * 0.8)
        tradable_vol_regime = (atr_pct >= 0.004) & (atr_pct <= 0.05)
        breakout_base_long = breakout_quality_long & (dataframe["rsi"] < 75)
        breakdown_base_short = breakdown_quality_short & (dataframe["rsi"] > 25)

        entry_condition_raw = (
            ((dataframe['buy_votes'] >= min_votes_long) | breakout_base_long) &
            (dataframe['close'] > dataframe['open']) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi'] < 70) &
            (dataframe["btc_4h_macd_hist_positive_slope"] | trend_up)
        )
        short_entry_condition_raw = (
            ((dataframe['sell_votes'] >= min_votes_short) | breakdown_base_short) &
            (dataframe['close'] < dataframe['open']) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi'] > 30) &
            (dataframe["btc_4h_macd_hist_negative_slope_2"] | trend_down)
        )
        recent_long_signal = entry_condition_raw.shift(1).fillna(False).rolling(window=cooldown_long_bars, min_periods=1).max().astype(bool)
        recent_short_signal = short_entry_condition_raw.shift(1).fillna(False).rolling(window=cooldown_short_bars, min_periods=1).max().astype(bool)
        entry_condition = entry_condition_raw & (~recent_long_signal) & tradable_vol_regime
        short_entry_condition = short_entry_condition_raw & (~recent_short_signal) & tradable_vol_regime

        dataframe.loc[entry_condition, 'enter_long'] = 1
        dataframe.loc[short_entry_condition, 'enter_short'] = 1
        dataframe.loc[entry_condition & bottom_confirmed, 'enter_tag'] = 'breakout_4h_up_bc'
        dataframe.loc[entry_condition & (~bottom_confirmed.fillna(False)), 'enter_tag'] = 'breakout_4h_up'
        dataframe.loc[short_entry_condition, 'enter_tag'] = 'breakout_4h_down'

        try:
            def _normalize_signals_url(raw: str) -> str:
                raw = str(raw or "").strip()
                if not raw:
                    return ""
                try:
                    u = urlparse(raw)
                except Exception:
                    return ""
                if not u.scheme or not u.netloc:
                    return ""

                pth = u.path or ""
                if "/signals" in pth:
                    return raw

                if "/decision" in pth:
                    new_path = "/signals"
                elif pth in ("", "/"):
                    new_path = "/signals"
                else:
                    new_path = pth.rstrip("/") + "/signals"
                return u._replace(path=new_path).geturl()

            decision_url_raw = os.environ.get("ML_EXPORT_URL", "")
            feature_url_raw = os.environ.get("ML_FEATURE_EXPORT_URL", "")
            decision_url = _normalize_signals_url(decision_url_raw)
            feature_url = _normalize_signals_url(feature_url_raw)
            if (not feature_url) and decision_url:
                feature_url = decision_url

            if feature_url or decision_url:
                row0 = dataframe.iloc[-1]

                def _sf(v: object, default: float = 0.0) -> float:
                    try:
                        if v is None or pd.isna(v):
                            return float(default)
                        f = float(v)
                        if not np.isfinite(f):
                            return float(default)
                        return f
                    except Exception:
                        return float(default)

                def _ss(v: object) -> Optional[str]:
                    try:
                        if v is None or pd.isna(v):
                            return None
                        s = str(v)
                        return s if s != "" else None
                    except Exception:
                        return None

                buy_votes0 = _sf(row0.get("buy_votes", 0.0) or 0.0)
                sell_votes0 = _sf(row0.get("sell_votes", 0.0) or 0.0)
                if max(buy_votes0, sell_votes0) >= 2:
                    tf = str(getattr(self, "timeframe", "1h") or "1h").lower().strip()
                    tf_ms = 0
                    try:
                        if tf.endswith("m"):
                            tf_ms = int(float(tf[:-1]) * 60_000)
                        elif tf.endswith("h"):
                            tf_ms = int(float(tf[:-1]) * 3_600_000)
                        elif tf.endswith("d"):
                            tf_ms = int(float(tf[:-1]) * 86_400_000)
                    except Exception:
                        tf_ms = 0

                    now_ms = int(pd.Timestamp.utcnow().timestamp() * 1000)

                    ts_ms = None
                    try:
                        if "date" in row0 and row0.get("date") is not None:
                            dt = pd.to_datetime(row0.get("date"), utc=True, errors="coerce")
                            if dt is not None and (not pd.isna(dt)):
                                ts_ms = int(pd.Timestamp(dt).timestamp() * 1000)
                    except Exception:
                        ts_ms = None
                    if ts_ms is None:
                        try:
                            if isinstance(row0.name, pd.Timestamp):
                                ts_ms = int(pd.Timestamp(row0.name).timestamp() * 1000)
                        except Exception:
                            ts_ms = None

                    if ts_ms is not None and tf_ms > 0:
                        try:
                            ts_ms = int((int(ts_ms) // int(tf_ms)) * int(tf_ms))
                        except Exception:
                            ts_ms = int(ts_ms)

                    bar_closed0 = bool(tf_ms > 0 and ts_ms is not None and now_ms >= int(ts_ms) + int(tf_ms) - 2_000)
                    row = row0
                    if (not bar_closed0) and len(dataframe) >= 2:
                        row1 = dataframe.iloc[-2]
                        ts1 = None
                        try:
                            if "date" in row1 and row1.get("date") is not None:
                                dt1 = pd.to_datetime(row1.get("date"), utc=True, errors="coerce")
                                if dt1 is not None and (not pd.isna(dt1)):
                                    ts1 = int(pd.Timestamp(dt1).timestamp() * 1000)
                        except Exception:
                            ts1 = None
                        if ts1 is None:
                            try:
                                if isinstance(row1.name, pd.Timestamp):
                                    ts1 = int(pd.Timestamp(row1.name).timestamp() * 1000)
                            except Exception:
                                ts1 = None
                        if ts1 is not None and tf_ms > 0:
                            try:
                                ts1 = int((int(ts1) // int(tf_ms)) * int(tf_ms))
                            except Exception:
                                ts1 = int(ts1)

                        bar_closed1 = bool(tf_ms > 0 and ts1 is not None and now_ms >= int(ts1) + int(tf_ms) - 2_000)
                        if bar_closed1:
                            row = row1
                            ts_ms = ts1
                            bar_closed0 = True

                    pair = metadata.get("pair")
                    if ts_ms is not None and pair:
                        def _emit(url: str, allow_trigger_decision: bool) -> None:
                            try:
                                pth = ""
                                try:
                                    pth = urlparse(url).path or ""
                                except Exception:
                                    pth = ""
                                if "/decision/" in pth:
                                    return
                                if "/signals" not in pth:
                                    return

                                bottom_ok = bool(row.get("bottom_confirmed", False))
                                tag = _ss(row.get("enter_tag"))
                                if tag is None:
                                    tag = "breakout_vote2_bc" if bottom_ok else "breakout_vote2"

                                close_v = _sf(row.get("close", 0.0) or 0.0)
                                atr_v = _sf(row.get("atr", 0.0) or 0.0)
                                enter_v = 1.0 if int(row.get("enter_long", 0) or 0) == 1 else 0.0
                                enter_short_v = 1.0 if int(row.get("enter_short", 0) or 0) == 1 else 0.0
                                side = "short" if enter_short_v > enter_v else "long"
                                trigger_enter_v = enter_short_v if side == "short" else enter_v

                                bar_closed = bool(bar_closed0)

                                action = "open" if (allow_trigger_decision and trigger_enter_v == 1.0 and bar_closed) else "observe"
                                if not bar_closed:
                                    action = "observe"

                                features = {
                                    "close": close_v,
                                    "volume": _sf(row.get("volume", 0.0) or 0.0),
                                    "rsi": _sf(row.get("rsi", 0.0) or 0.0),
                                    "atr": atr_v,
                                    "atr_pct": (atr_v / close_v) if close_v > 0.0 else 0.0,
                                    "buy_votes": _sf(row.get("buy_votes", 0.0) or 0.0),
                                    "sell_votes": _sf(row.get("sell_votes", 0.0) or 0.0),
                                    "enter_long": enter_v,
                                    "enter_short": enter_short_v,
                                    "z_score": _sf(row.get("z_score", 0.0) or 0.0),
                                    "vroc_12": _sf(row.get("vroc_12", 0.0) or 0.0),
                                    "cmf": _sf(row.get("cmf", 0.0) or 0.0),
                                    "obv": _sf(row.get("obv", 0.0) or 0.0),
                                    "ema_20": _sf(row.get("ema_20", 0.0) or 0.0),
                                    "ema_50": _sf(row.get("ema_50", 0.0) or 0.0),
                                    "donchian_upper": _sf(row.get("donchian_upper", 0.0) or 0.0),
                                    "donchian_lower": _sf(row.get("donchian_lower", 0.0) or 0.0),
                                    "donchian_middle": _sf(row.get("donchian_middle", 0.0) or 0.0),
                                    "macdhist": _sf(row.get("macdhist", 0.0) or 0.0),
                                    "btc_4h_macd_hist_positive_slope": 1.0 if bool(row.get("btc_4h_macd_hist_positive_slope", False)) else 0.0,
                                    "btc_4h_macd_hist_negative_slope_2": 1.0 if bool(row.get("btc_4h_macd_hist_negative_slope_2", False)) else 0.0,
                                    "bottom_confirmed": 1.0 if bottom_ok else 0.0,
                                    "bottom_confirmation_score": _sf(row.get("bottom_confirmation_score", 0.0) or 0.0),
                                    "pump_acceleration": _sf(row.get("pump_acceleration", 0.0) or 0.0),
                                    "vol_anomaly": _sf(row.get("vol_anomaly", 0.0) or 0.0),
                                    "vwap_support": _sf(row.get("vwap_support", 0.0) or 0.0),
                                    "absorption": _sf(row.get("absorption", 0.0) or 0.0),
                                    "momentum_turn_up": _sf(row.get("momentum_turn_up", 0.0) or 0.0),
                                    "regime": "trend",
                                }

                                bar_close_ms = int(ts_ms)
                                if tf_ms > 0:
                                    bar_close_ms = int(ts_ms) + int(tf_ms)

                                payload = {
                                    "venue": "freqtrade",
                                    "pair": pair,
                                    "side": side,
                                    "action": action,
                                    "timeframe": tf,
                                    "ts": int(ts_ms),
                                    "bar_open_ms": int(ts_ms),
                                    "bar_close_ms": int(bar_close_ms),
                                    "bar_closed": bool(bar_closed),
                                    "strategy_id": "BreakoutStrategy",
                                    "strategy_version": "1.0.0",
                                    "group_id": "breakout_1h_confirmed",
                                    "feature_set_id": "breakout_1h_v1",
                                    "tag": tag,
                                    "confidence": 1.0,
                                    "features": features,
                                }

                                if allow_trigger_decision and trigger_enter_v == 1.0 and action == "open":
                                    trigger_raw = str(os.environ.get("ML_EXPORT_TRIGGER_DECISION", "")).strip().lower()
                                    if trigger_raw in ("1", "true", "yes", "y", "on"):
                                        payload["trigger_decision"] = True
                                        thr_raw = str(os.environ.get("ML_EXPORT_THRESHOLD", "")).strip()
                                        if thr_raw:
                                            try:
                                                payload["threshold"] = float(thr_raw)
                                            except Exception:
                                                pass
                                        size_raw = str(os.environ.get("ML_EXPORT_SIZE", "")).strip()
                                        if size_raw:
                                            try:
                                                payload["size"] = float(size_raw)
                                            except Exception:
                                                pass

                                for k, v in payload["features"].items():
                                    if hasattr(v, "item"):
                                        payload["features"][k] = v.item()

                                timeout_s = 0.5
                                try:
                                    timeout_s = float(str(os.environ.get("ML_EXPORT_TIMEOUT", "0.5") or "0.5").strip() or 0.5)
                                except Exception:
                                    timeout_s = 0.5

                                requests.post(url, json=payload, timeout=timeout_s)
                            except Exception:
                                return

                        def _feature_ok_to_send() -> bool:
                            last_ts = self._ml_export_last_ts_by_pair.get(pair)
                            if last_ts is not None and ts_ms <= last_ts:
                                return False

                            min_interval_s = 0.0
                            try:
                                raw = os.environ.get("ML_FEATURE_EXPORT_MIN_INTERVAL_SEC", os.environ.get("ML_EXPORT_MIN_INTERVAL_SEC", "0"))
                                min_interval_s = float(str(raw or "0").strip() or 0.0)
                            except Exception:
                                min_interval_s = 0.0

                            if min_interval_s <= 0.0 or last_ts is None:
                                return True
                            return (ts_ms - last_ts) >= int(min_interval_s * 1000.0)

                        def _decision_ok_to_send() -> bool:
                            last_ts = self._ml_decision_last_ts_by_pair.get(pair)
                            return last_ts is None or ts_ms > last_ts

                        enter_now = (int(row.get("enter_long", 0) or 0) == 1) or (int(row.get("enter_short", 0) or 0) == 1)
                        if feature_url and (feature_url != decision_url) and _feature_ok_to_send():
                            _emit(feature_url, allow_trigger_decision=False)
                            self._ml_export_last_ts_by_pair[pair] = ts_ms

                        if enter_now and decision_url and _decision_ok_to_send():
                            _emit(decision_url, allow_trigger_decision=True)
                            self._ml_decision_last_ts_by_pair[pair] = ts_ms
                            if decision_url == feature_url:
                                self._ml_export_last_ts_by_pair[pair] = ts_ms
                        elif feature_url and _feature_ok_to_send() and (feature_url == decision_url):
                            _emit(feature_url, allow_trigger_decision=False)
                            self._ml_export_last_ts_by_pair[pair] = ts_ms
        except Exception:
            pass

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            dataframe['exit_long'] = 0
            dataframe['exit_short'] = 0
            return dataframe

        dataframe['exit_long'] = 0
        dataframe['exit_short'] = 0

        cond_breakdown = (
            dataframe['close'] < (dataframe['donchian_lower'].shift(1) + (dataframe['atr'] * self.tolerance_atr_mult.value))
        )

        cond_volume_spike = (dataframe['volume'] > dataframe['volume_mean'] * 1.5)

        cond_cmf_negative = (dataframe['cmf'] < 0) & (dataframe['cmf'].shift(1) >= 0)

        cond_obv_low = (dataframe['obv'] < dataframe['obv_low_20'].shift(1) * 1.001)

        cond_rsi_overbought = (dataframe['rsi'] > 70)

        dataframe['exit_votes'] = (
            cond_breakdown.astype(int) +
            cond_volume_spike.astype(int) +
            cond_cmf_negative.astype(int) +
            cond_obv_low.astype(int) +
            cond_rsi_overbought.astype(int)
        )

        exit_condition = (
            (dataframe['exit_votes'] >= 3) &
            (dataframe['close'] < dataframe['open']) &
            (dataframe['volume'] > 0)
        )
        cond_breakup_short = (
            dataframe['close'] > (dataframe['donchian_upper'].shift(1) - (dataframe['atr'] * self.tolerance_atr_mult.value))
        )
        cond_cmf_positive_short = (dataframe['cmf'] > 0) & (dataframe['cmf'].shift(1) <= 0)
        cond_obv_high_short = (dataframe['obv'] > dataframe['obv_high_20'].shift(1) * 0.995)
        cond_rsi_oversold_short = (dataframe['rsi'] < 30)
        dataframe['exit_short_votes'] = (
            cond_breakup_short.astype(int) +
            cond_volume_spike.astype(int) +
            cond_cmf_positive_short.astype(int) +
            cond_obv_high_short.astype(int) +
            cond_rsi_oversold_short.astype(int)
        )
        exit_short_condition = (
            (dataframe['exit_short_votes'] >= 3) &
            (dataframe['close'] > dataframe['open']) &
            (dataframe['volume'] > 0)
        )

        dataframe.loc[exit_condition | dataframe["btc_4h_macd_hist_negative_slope_2"], 'exit_long'] = 1
        dataframe.loc[exit_short_condition | dataframe["btc_4h_macd_hist_positive_slope"], 'exit_short'] = 1
        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 20:
                return self.stoploss

            entry_date = trade.open_date_utc
            if entry_date.tzinfo is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)
            
            temp_df = dataframe.copy()
            if temp_df.index.tz is None:
                temp_df.index = temp_df.index.tz_localize('UTC')
            else:
                temp_df.index = temp_df.index.tz_convert('UTC')

            mask = temp_df.index <= entry_date
            if not mask.any():
                return self.stoploss
                
            entry_candle = temp_df.loc[mask].iloc[-1]
            atr_at_entry = entry_candle.get('atr', 0)
            if pd.isna(atr_at_entry) or atr_at_entry <= 0:
                return self.stoploss
                
            current_atr = temp_df['atr'].iloc[-1]
            if pd.isna(current_atr) or current_atr <= 0:
                return self.stoploss
            is_short = bool(getattr(trade, "is_short", False))
            if is_short:
                initial_sl_price = trade.open_rate + (atr_at_entry * 2.0)
                if current_rate >= initial_sl_price:
                    return (current_rate - initial_sl_price) / current_rate
                if current_profit > 0.03:
                    trail_distance = current_atr * 1.7
                    stop_price = min(current_rate + trail_distance, trade.open_rate)
                    return (current_rate - stop_price) / current_rate
                if current_profit > 0.015:
                    stop_price = trade.open_rate
                    return (current_rate - stop_price) / current_rate
                return (current_rate - initial_sl_price) / current_rate
            initial_sl_price = trade.open_rate - (atr_at_entry * 2.0)
            if current_rate <= initial_sl_price:
                return (initial_sl_price - current_rate) / current_rate
            if current_profit > 0.03:
                trail_distance = current_atr * 1.7
                stop_price = max(current_rate - trail_distance, trade.open_rate)
                return (stop_price - current_rate) / current_rate
            if current_profit > 0.015:
                stop_price = trade.open_rate
                return (stop_price - current_rate) / current_rate
            return (initial_sl_price - current_rate) / current_rate
            
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Stoploss error for {pair}: {str(e)}")
            return self.stoploss

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, 
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        if current_profit > 0.15:
            return "quick_profit_15"
        if current_profit > 0.10:
            return "quick_profit_10"
        if current_profit > 0.07:
            return "quick_profit_7"
        
        hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hold_hours > 168:
            return "time_exit_7d"
        
        return None

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                           proposed_stake: float, min_stake: float, max_stake: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        runmode = getattr(self.dp, "runmode", None)
        if runmode is not None and "backtest" in str(runmode).lower():
            return proposed_stake

        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 1:
                return proposed_stake
                
            last = dataframe.iloc[-1]
            atr = last.get('atr', 0)
            if pd.isna(atr) or atr <= 0:
                return proposed_stake
                
            atr_pct = atr / current_rate
            
            total = self.wallets.get_total_stake_amount()
            base = total * 0.02
            
            if atr_pct > 0.05:
                size = base * 0.5
            elif atr_pct > 0.03:
                size = base * 0.75
            elif atr_pct < 0.01:
                size = base * 1.5
            else:
                size = base
            
            return max(min(size, max_stake), min_stake)
            
        except Exception:
            return proposed_stake

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 1:
            return False
            
        last = dataframe.iloc[-1]
        
        checks = [
            last.get('volume', 0) > 0,
            last.get('atr', 0) > 0,
            last.get('volume', 0) > last.get('volume_mean', 0) * 0.5,
        ]
        if str(side).lower().strip() == "short":
            checks.append(last.get('rsi', 0) > 25)
            checks.append(bool(last.get('btc_4h_macd_hist_negative_slope_2', False)) or (last.get('ema_20', 0) < last.get('ema_50', 0)))
        else:
            checks.append(last.get('rsi', 100) < 75)
            checks.append(bool(last.get('btc_4h_macd_hist_positive_slope', False)) or (last.get('ema_20', 0) > last.get('ema_50', 0)))
        return all(checks)

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "candles": True,
                "close": {"color": "black"},
                "donchian_upper": {"color": "#1f77b4", "fill_to": "donchian_lower"},
                "donchian_middle": {"color": "#ff7f0e"},
                "donchian_lower": {"color": "#1f77b4"},
                "ema_20": {"color": "#9467bd"},
                "ema_50": {"color": "#d62728"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "#ff7f0e"}},
                "ATR": {"atr": {"color": "#7f7f7f"}},
                "CMF": {"cmf": {"color": "#2ca02c"}},
                "OBV": {
                    "obv": {"color": "#9467bd"},
                    "obv_high_20": {"color": "#2ca02c", "plotly": {"dash": "dash"}},
                    "obv_low_20": {"color": "#d62728", "plotly": {"dash": "dash"}},
                },
                "MACD": {
                    "macd": {"color": "#1f77b4"},
                    "macdsignal": {"color": "#ff7f0e"},
                    "macdhist": {"color": "#98df8a", "type": "bar"},
                },
                "Volume": {
                    "volume": {"color": "gray", "type": "bar"},
                    "volume_mean": {"color": "#1f77b4"},
                },
                "Votes": {
                    "buy_votes": {"color": "#2ca02c", "type": "bar"},
                    "exit_votes": {"color": "#d62728", "type": "bar"},
                },
                "Z-Score": {"z_score": {"color": "#9467bd"}},
                "Bottom Confirmation": {
                    "bottom_confirmation_score": {"color": "#2ca02c", "type": "bar"},
                },
            }
        }
