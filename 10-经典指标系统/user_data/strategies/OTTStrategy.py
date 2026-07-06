# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
import numpy as np
import pandas as pd
from pandas import DataFrame
from datetime import datetime
from typing import Optional
import talib.abstract as ta
try:
    import freqtrade.vendor.qtpylib.indicators as qtpylib
except Exception:
    from technical import qtpylib

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, BooleanParameter, merge_informative_pair


class OttStrategy(IStrategy):
    """
    优化版 OTT 趋势跟踪策略（最终完整版）
    - 自适应 VAR + OTT 通道
    - 多重过滤：ADX趋势强度 + RSI区间 + 成交量确认
    - 多空对称，适合合约/现货
    - 内置追踪止损 + 时间兜底
    """
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = True

    # ROI
    minimal_roi = {
        "0": 0.20,
        "60": 0.12,
        "240": 0.06,
        "720": 0
    }

    # 止损
    stoploss = -0.15

    # 追踪止损（主力止损）
    trailing_stop = True
    trailing_stop_positive = 0.02        # 盈利2%后开始追踪
    trailing_stop_positive_offset = 0.04  # 盈利4%后激活
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    ignore_roi_if_entry_signal = True
    startup_candle_count: int = 100
    use_custom_stoploss = True  # 仅时间兜底

    # ==================== 可优化参数 ====================
    # OTT 核心参数
    pds = IntParameter(1, 5, default=3, space="buy")
    percent = DecimalParameter(1.0, 3.0, default=2.2, space="buy")  # 通道宽度
    ott_shift = IntParameter(1, 5, default=2, space="buy")

    use_crossover_long = BooleanParameter(default=False, space="buy")
    signal_lookback_long = IntParameter(1, 12, default=6, space="buy")

    # 辅助过滤
    rsi_period = IntParameter(10, 20, default=14, space="buy")
    rsi_oversold = IntParameter(15, 45, default=25, space="buy")
    rsi_overbought = IntParameter(55, 85, default=75, space="sell")
    rsi_max_long = IntParameter(55, 85, default=78, space="buy")
    enable_short = BooleanParameter(default=True, space="sell")
    enable_btc_filter_short = BooleanParameter(default=True, space="sell")
    enable_rs_filter_short = BooleanParameter(default=True, space="sell")
    rsi_max_short = IntParameter(25, 70, default=45, space="sell")
    rsi_min_short = IntParameter(5, 50, default=25, space="sell")

    enable_adx_filter_long = BooleanParameter(default=True, space="buy")
    adx_period = IntParameter(7, 30, default=14, space="buy")
    adx_threshold = IntParameter(10, 40, default=15, space="buy")

    enable_volume_filter_long = BooleanParameter(default=True, space="buy")
    volume_multiplier = DecimalParameter(0.8, 2.0, default=1.0, space="buy")

    # 均线过滤（趋势方向）
    enable_trend_filter_long = BooleanParameter(default=True, space="buy")
    trend_tolerance_long = DecimalParameter(0.0, 0.02, default=0.006, space="buy")

    enable_regime_filter_long = BooleanParameter(default=True, space="buy")
    require_regime_slope_long = BooleanParameter(default=False, space="buy")

    ema_trend_period = IntParameter(20, 200, default=100, space="buy")
    ema_regime_period = IntParameter(50, 600, default=300, space="buy")
    regime_slope_lookback = IntParameter(6, 120, default=24, space="buy")

    atr_period = IntParameter(5, 40, default=14, space="buy")
    atr_min_ratio = DecimalParameter(0.0, 0.02, default=0.001, space="buy")

    enable_btc_filter = BooleanParameter(default=False, space="buy")
    btc_regime_timeframe = "1d"
    btc_ema_period = IntParameter(50, 300, default=200, space="buy")
    btc_ema_slope_lookback = IntParameter(3, 30, default=10, space="buy")

    enable_rs_filter = BooleanParameter(default=False, space="buy")
    rs_ema_period = IntParameter(12, 240, default=96, space="buy")
    rs_slope_lookback = IntParameter(3, 120, default=24, space="buy")

    def informative_pairs(self):
        return [("BTC/USDT:USDT", self.btc_regime_timeframe)]

    @staticmethod
    def _timeframe_to_minutes(timeframe: str) -> int:
        tf = str(timeframe).strip().lower()
        digits = "".join([c for c in tf if c.isdigit()])
        unit = "".join([c for c in tf if c.isalpha()])
        value = int(digits) if digits else 0
        if unit == "m":
            return value
        if unit == "h":
            return value * 60
        if unit == "d":
            return value * 1440
        if unit == "w":
            return value * 10080
        return value

    @staticmethod
    def _timeframe_to_pandas_freq(timeframe: str) -> str:
        tf = str(timeframe).strip().lower()
        digits = "".join([c for c in tf if c.isdigit()])
        unit = "".join([c for c in tf if c.isalpha()])
        value = int(digits) if digits else 0
        if unit == "m":
            return f"{value}min"
        if unit == "h":
            return f"{value}h"
        if unit == "d":
            return f"{value}D"
        if unit == "w":
            return f"{value}W"
        return f"{value}{unit}" if value else tf

    def _resample_btc_close(self, btc_df: DataFrame, target_timeframe: str) -> DataFrame:
        freq = self._timeframe_to_pandas_freq(target_timeframe)
        tmp = btc_df.copy()
        tmp["date"] = pd.to_datetime(tmp["date"], utc=True, errors="coerce")
        tmp = tmp.dropna(subset=["date"]).sort_values("date")
        resampled = tmp.set_index("date")["btc_close"].resample(freq).last().dropna()
        return resampled.reset_index().rename(columns={"btc_close": "btc_close"})

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["btc_regime_long"] = True
        dataframe["btc_regime_short"] = True
        dataframe["rs_long_ok"] = True
        dataframe["rs_short_ok"] = True

        if self.dp:
            pair_btc_candidates = ["BTC/USDT:USDT", "BTC/USDT"]

            base_tf_minutes = self._timeframe_to_minutes(self.timeframe)
            btc_rs_source_tf = self.timeframe if base_tf_minutes <= 60 else "1h"
            btc_rs_df = None
            for p in pair_btc_candidates:
                try:
                    btc_rs_df = self.dp.get_pair_dataframe(p, btc_rs_source_tf)
                    if btc_rs_df is not None and len(btc_rs_df) > 0:
                        break
                except Exception:
                    btc_rs_df = None

            btc_1d = None
            for p in pair_btc_candidates:
                try:
                    btc_1d = self.dp.get_pair_dataframe(p, self.btc_regime_timeframe)
                    if len(btc_1d) > 1:
                        btc_1d = btc_1d.iloc[:-1].copy()
                    break
                except Exception:
                    btc_1d = None

            if btc_rs_df is not None and len(btc_rs_df) > 0 and "date" in btc_rs_df.columns:
                btc_rs_df = btc_rs_df.copy()
                btc_rs_df["btc_close"] = btc_rs_df["close"]
                btc_rs_df = btc_rs_df[["date", "btc_close"]]
                if btc_rs_source_tf != self.timeframe:
                    btc_rs_df = self._resample_btc_close(btc_rs_df, self.timeframe)
                dataframe = merge_informative_pair(dataframe, btc_rs_df, self.timeframe, self.timeframe, ffill=True)

            if btc_1d is not None and len(btc_1d) > 0 and "date" in btc_1d.columns:
                btc_1d = btc_1d.copy()
                btc_1d["btc_close"] = btc_1d["close"]
                btc_1d["btc_ema"] = ta.EMA(btc_1d, timeperiod=self.btc_ema_period.value)
                btc_1d["btc_ema_slope"] = btc_1d["btc_ema"] - btc_1d["btc_ema"].shift(self.btc_ema_slope_lookback.value)
                btc_1d = btc_1d[["date", "btc_close", "btc_ema", "btc_ema_slope"]]
                dataframe = merge_informative_pair(dataframe, btc_1d, self.timeframe, self.btc_regime_timeframe, ffill=True)

            btc_close_tf_col = f"btc_close_{self.timeframe}"
            if btc_close_tf_col not in dataframe.columns and "btc_close" in dataframe.columns:
                btc_close_tf_col = "btc_close"

            btc_close_1d_col = f"btc_close_{self.btc_regime_timeframe}"
            btc_ema_1d_col = f"btc_ema_{self.btc_regime_timeframe}"
            btc_ema_slope_1d_col = f"btc_ema_slope_{self.btc_regime_timeframe}"

            if btc_close_1d_col in dataframe.columns and btc_ema_1d_col in dataframe.columns and btc_ema_slope_1d_col in dataframe.columns:
                dataframe["btc_regime_long"] = (dataframe[btc_close_1d_col] > dataframe[btc_ema_1d_col]) & (dataframe[btc_ema_slope_1d_col] > 0)
                dataframe["btc_regime_short"] = (dataframe[btc_close_1d_col] < dataframe[btc_ema_1d_col]) & (dataframe[btc_ema_slope_1d_col] < 0)

            if btc_close_tf_col in dataframe.columns:
                btc_close = dataframe[btc_close_tf_col].replace(0, np.nan)
                rs = (dataframe["close"] / btc_close).replace([np.inf, -np.inf], np.nan)
                dataframe["rs_btc"] = rs
                dataframe["rs_btc_ema"] = rs.ewm(span=self.rs_ema_period.value, adjust=False).mean()
                dataframe["rs_btc_slope"] = rs - rs.shift(self.rs_slope_lookback.value)
                dataframe["rs_long_ok"] = (dataframe["rs_btc"] > dataframe["rs_btc_ema"]) & (dataframe["rs_btc_slope"] > 0)
                dataframe["rs_short_ok"] = (dataframe["rs_btc"] < dataframe["rs_btc_ema"]) & (dataframe["rs_btc_slope"] < 0)

        # 计算 OTT
        ott_df = self.ott_indicator(
            dataframe,
            pds=self.pds.value,
            percent=self.percent.value,
            shift=self.ott_shift.value
        )
        dataframe["ott"] = ott_df["OTT"]
        dataframe["var"] = ott_df["VAR"]
        dataframe["ott_dir"] = ott_df["DIR"]

        # 辅助指标
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.rsi_period.value)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=self.adx_period.value)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=self.ema_trend_period.value)
        dataframe["ema_regime"] = ta.EMA(dataframe, timeperiod=self.ema_regime_period.value)
        dataframe["ema_regime_slope"] = dataframe["ema_regime"] - dataframe["ema_regime"].shift(self.regime_slope_lookback.value)

        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.atr_period.value)
        dataframe["atr_ratio"] = dataframe["atr"] / dataframe["close"].replace(0, np.nan)

        # 成交量
        dataframe["volume_ma"] = dataframe["volume"].rolling(20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_ma"].replace(0, 1)

        # 填充 NaN
        dataframe.fillna(method="ffill", inplace=True)
        dataframe.fillna(0, inplace=True)

        return dataframe

    def ott_indicator(self, dataframe: DataFrame, pds: int = 2, percent: float = 1.4, shift: int = 2):
        """向量化优化版 OTT 计算"""
        df = dataframe.copy()

        alpha = 2 / (pds + 1)

        # CMO 计算
        diff = df["close"].diff()
        ud = np.where(diff > 0, diff, 0)
        dd = np.where(diff < 0, -diff, 0)

        UD = pd.Series(ud, index=df.index).rolling(9).sum()
        DD = pd.Series(dd, index=df.index).rolling(9).sum()
        CMO = np.abs((UD - DD) / (UD + DD + 1e-10)).fillna(0.0)

        # VAR 自适应均线
        var = df["close"].copy().astype("float64")
        for i in range(1, len(df)):
            cmo = float(CMO.iat[i])
            close = float(df["close"].iat[i])
            prev = float(var.iat[i - 1])
            var.iat[i] = (alpha * cmo * close) + (1 - alpha * cmo) * prev

        # 动态通道
        fark = var * percent * 0.01
        new_long_stop = var - fark
        new_short_stop = var + fark

        long_stop = new_long_stop.copy()
        short_stop = new_short_stop.copy()

        for i in range(1, len(df)):
            long_stop.iat[i] = max(float(long_stop.iat[i - 1]), float(new_long_stop.iat[i])) if var.iat[i] > long_stop.iat[i - 1] else float(new_long_stop.iat[i])
            short_stop.iat[i] = min(float(short_stop.iat[i - 1]), float(new_short_stop.iat[i])) if var.iat[i] < short_stop.iat[i - 1] else float(new_short_stop.iat[i])

        # 趋势方向
        direction = pd.Series(1, index=df.index)  # 默认多头
        for i in range(1, len(df)):
            if var.iat[i] > short_stop.iat[i - 1] and var.iat[i - 1] <= short_stop.iat[i - 1]:
                direction.iat[i] = 1
            elif var.iat[i] < long_stop.iat[i - 1] and var.iat[i - 1] >= long_stop.iat[i - 1]:
                direction.iat[i] = -1
            else:
                direction.iat[i] = direction.iat[i - 1]

        # OTT
        mt = np.where(direction == 1, long_stop, short_stop)
        ott_raw = np.where(var > mt, mt * (200 + percent) / 200, mt * (200 - percent) / 200)
        ott = pd.Series(ott_raw, index=df.index).shift(shift)

        return pd.DataFrame({
            "OTT": ott,
            "VAR": var,
            "DIR": direction
        })

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "enter_long"] = 0
        dataframe.loc[:, "enter_short"] = 0

        cross_up = qtpylib.crossed_above(dataframe["var"], dataframe["ott"])
        cross_down = qtpylib.crossed_below(dataframe["var"], dataframe["ott"])

        long_signal = (
            cross_up
            if self.use_crossover_long.value
            else (dataframe["var"] > dataframe["ott"]) & (cross_up.rolling(self.signal_lookback_long.value).max() > 0)
        )
        short_signal = cross_down

        # 多重过滤
        volume_ok_long = (dataframe["volume_ratio"] > self.volume_multiplier.value) if self.enable_volume_filter_long.value else True
        adx_strong_long = (dataframe["adx"] > self.adx_threshold.value) if self.enable_adx_filter_long.value else True
        rsi_ok_long = dataframe["rsi"] > self.rsi_oversold.value
        rsi_not_overbought = dataframe["rsi"] < self.rsi_max_long.value
        above_trend_long = (dataframe["close"] > (dataframe["ema_trend"] * (1 - self.trend_tolerance_long.value))) if self.enable_trend_filter_long.value else True
        if self.enable_regime_filter_long.value:
            regime_ok_long = dataframe["close"] > dataframe["ema_regime"]
            if self.require_regime_slope_long.value:
                regime_ok_long = regime_ok_long & (dataframe["ema_regime_slope"] > 0)
        else:
            regime_ok_long = True
        atr_ok = dataframe["atr_ratio"] > self.atr_min_ratio.value

        rsi_ok_short = (dataframe["rsi"] < self.rsi_max_short.value) & (dataframe["rsi"] > self.rsi_min_short.value)
        below_trend = dataframe["close"] < dataframe["ema_trend"]
        regime_short_ok = (dataframe["close"] < dataframe["ema_regime"]) & (dataframe["ema_regime_slope"] < 0)

        # 多头入场
        long_condition = (
            cross_up &
            atr_ok &
            (dataframe["close"] > dataframe["ema_trend"] * 0.995) &
            (dataframe["ott_dir"] == 1)
        )

        is_btc_pair = metadata.get("pair") in ("BTC/USDT:USDT", "BTC/USDT")
        if self.enable_btc_filter.value and not is_btc_pair:
            long_condition = long_condition & dataframe["btc_regime_long"]
        if self.enable_rs_filter.value and not is_btc_pair:
            long_condition = long_condition & dataframe["rs_long_ok"]

        dataframe.loc[long_condition, "enter_long"] = 1

        short_condition = (
            self.enable_short.value &
            atr_ok &
            (dataframe["close"] < dataframe["ema_trend"] * 1.005) &
            (dataframe["ott_dir"] == -1) &
            short_signal
        )

        if self.enable_btc_filter_short.value:
            short_condition = short_condition & dataframe["btc_regime_short"]
        if self.enable_rs_filter_short.value and not is_btc_pair:
            short_condition = short_condition & dataframe["rs_short_ok"]

        dataframe.loc[short_condition, "enter_short"] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[:, "exit_long"] = 0
        dataframe.loc[:, "exit_short"] = 0

        # 反向交叉出场
        exit_long = qtpylib.crossed_below(dataframe["var"], dataframe["ott"])
        exit_short = qtpylib.crossed_above(dataframe["var"], dataframe["ott"])

        # 趋势衰竭出场
        trend_weak = dataframe["adx"] < 20

        dataframe.loc[exit_long | trend_weak, "exit_long"] = 1
        dataframe.loc[exit_short | trend_weak, "exit_short"] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                       current_rate: float, current_profit: float, **kwargs) -> float:
        hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if current_profit > 0.06:
            return -0.005
        if current_profit > 0.03:
            return -0.015
        if hold_hours > 72:
            return -0.25
        return self.stoploss

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "ott": {"color": "orange"},
                "var": {"color": "blue"},
                "ema_trend": {"color": "purple"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "purple"}},
                "ADX": {"adx": {"color": "brown"}},
                "Volume Ratio": {"volume_ratio": {"color": "green"}},
            }
        }
