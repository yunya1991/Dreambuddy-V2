# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
from pandas import DataFrame
import pandas as pd
import os
from typing import Optional, Tuple
from datetime import datetime, timedelta
import logging

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade
from freqtrade.enums import RunMode
import talib.abstract as ta

class ShortBTCStrategy(IStrategy):
    """
    最终优化版经典三屏交易法（合约多空）
    - 第一屏（周线）：BTC 周线 MACD 柱向上 + ADX > 25
    - 第二屏（日线，多空不对称）：
      - 多头更宽松：四组经典组合（Elder、Freqtrade、TradingView、量化机构），任一组达到即可
      - 空头更严格：四组经典组合任一组达 + 成交量放大 + MACD Histogram 斜率确认
    - 第三屏（1h）：只需满足任一：
      1. 突破前一根 K 线高/低点（Elder 原版）
      2. 突破 Donchian 通道
      3. 锤头/吞没 K 线形态
    - 多空不对称：空头更严格（至少两组超买 + 资金费率 > 0.05%）
    - 止损：前一根 K 线低/高点 ± 1.5 ATR
    - 止盈：1:3 RR + 追踪止盈
    """

    INTERFACE_VERSION = 3

    timeframe = "1h"  # 第三屏
    can_short = True

    minimal_roi = {
        "0": 0.15,
        "60": 0.08,
        "240": 0.05,
        "720": 0
    }

    stoploss = -0.05
    use_custom_stoploss = True
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 200

    PB_NO_TRADE = 0
    PB_TREND_BREAKOUT = 1
    PB_TREND_PULLBACK = 2
    PB_MEAN_REVERSION = 3

    # 参数
    rsi_buy = IntParameter(25, 40, default=35, space="buy")
    rsi_sell = IntParameter(60, 75, default=68, space="sell")
    adx_threshold = IntParameter(20, 40, default=26, space="buy")
    donchian_period = IntParameter(10, 30, default=16, space="buy")
    osc_vote_threshold = IntParameter(2, 3, default=2, space="buy")
    volume_multiplier = DecimalParameter(1.2, 2.0, default=1.577, space="buy")
    black_swan_drop_pct = DecimalParameter(3.0, 8.0, default=4.355, space="buy")  # 黑天鹅跌幅

    def _get_env_float(self, key: str, default: float) -> float:
        v = os.environ.get(key)
        if v is None or v == "":
            return float(default)
        try:
            return float(v)
        except Exception:
            return float(default)

    def _get_btc_informative_pair(self) -> str:
        whitelist = []
        try:
            if hasattr(self, 'dp') and self.dp is not None:
                whitelist = list(self.dp.current_whitelist() or [])
        except Exception:
            whitelist = []

        if not whitelist:
            whitelist = list(self.config.get('exchange', {}).get('pair_whitelist', []) or [])

        btc_candidates = [p for p in whitelist if isinstance(p, str) and 'BTC' in p.upper()]
        if btc_candidates:
            perp = next((p for p in btc_candidates if ':' in p), None)
            return perp or btc_candidates[0]

        if str(self.config.get('trading_mode', '')).lower() == 'futures':
            return 'BTC/USDT:USDT'
        return 'BTC/USDT'

    def informative_pairs(self):
        pairs = []
        try:
            if hasattr(self, 'dp') and self.dp is not None:
                pairs = list(self.dp.current_whitelist() or [])
        except Exception:
            pairs = []

        informative_pairs = [(pair, '1d') for pair in pairs]
        btc_pair = self._get_btc_informative_pair()
        informative_pairs.append((btc_pair, '1d'))

        seen = set()
        deduped = []
        for p, tf in informative_pairs:
            key = (p, tf)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)
        return deduped

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        for col in ("open", "high", "low", "close", "volume"):
            if col in dataframe.columns:
                dataframe[col] = pd.to_numeric(dataframe[col], errors="coerce")
        if "close" in dataframe.columns:
            dataframe = dataframe.loc[dataframe["close"].notna()]

        # 1. 第一屏：用 BTC 日线重采样生成周线（避免缺失 1w 数据）
        btc_pair = self._get_btc_informative_pair()
        btc_daily = None
        try:
            btc_daily = self.dp.get_pair_dataframe(btc_pair, '1d')
        except Exception:
            btc_daily = None
        if btc_daily is None or btc_daily.empty:
            alt = 'BTC/USDT' if ':' in btc_pair else 'BTC/USDT:USDT'
            try:
                btc_daily = self.dp.get_pair_dataframe(alt, '1d')
            except Exception:
                btc_daily = None
        if btc_daily is not None and not btc_daily.empty:
            for col in ("open", "high", "low", "close", "volume"):
                if col in btc_daily.columns:
                    btc_daily[col] = pd.to_numeric(btc_daily[col], errors="coerce")
            btc_daily = btc_daily.loc[btc_daily["close"].notna()].copy()

            base = btc_daily[["date", "open", "high", "low", "close", "volume"]].copy()
            base["date"] = pd.to_datetime(base["date"], utc=True, errors="coerce")
            base = base.dropna(subset=["date"]).sort_values("date")
            week_start = base["date"] - pd.to_timedelta((base["date"].dt.dayofweek + 1) % 7, unit="D")
            base["week_start"] = week_start
            btc_weekly = (
                base.groupby("week_start", as_index=False)
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna(subset=["close"])
            )
            btc_weekly["date"] = pd.to_datetime(btc_weekly["week_start"], utc=True, errors="coerce")
            btc_weekly = btc_weekly.drop(columns=["week_start"]).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

            if not btc_weekly.empty and len(btc_weekly) > 35:
                screen1_require_adx = int(os.environ.get("FT_SCREEN1_REQUIRE_ADX", "1") or "1") != 0

                macd_res = ta.MACD(btc_weekly)
                if isinstance(macd_res, pd.DataFrame):
                    macdhist = macd_res.get("macdhist")
                elif isinstance(macd_res, dict):
                    macdhist = macd_res.get("macdhist")
                else:
                    _, _, macdhist = macd_res

                btc_weekly["macd_hist"] = pd.to_numeric(macdhist, errors="coerce")
                btc_weekly = btc_weekly.loc[btc_weekly["macd_hist"].notna()].copy()
                btc_weekly["macd_hist_slope"] = btc_weekly["macd_hist"] - btc_weekly["macd_hist"].shift(1)
                btc_weekly[["macd_hist_slope"]] = btc_weekly[["macd_hist_slope"]].shift(1)
                btc_weekly["adx"] = ta.ADX(btc_weekly)
                btc_weekly[["adx"]] = btc_weekly[["adx"]].shift(1)

                btc_daily_map = btc_daily[["date"]].copy()
                btc_daily_map["date"] = pd.to_datetime(btc_daily_map["date"], utc=True, errors="coerce")
                btc_daily_map = btc_daily_map.dropna(subset=["date"]).sort_values("date")
                btc_daily_map["week_start"] = btc_daily_map["date"] - pd.to_timedelta(
                    (btc_daily_map["date"].dt.dayofweek + 1) % 7, unit="D"
                )

                btc_weekly_map = btc_weekly[["date", "macd_hist_slope", "adx"]].copy()
                btc_weekly_map = btc_weekly_map.rename(columns={
                    "date": "week_start",
                    "macd_hist_slope": "btc_w_macd_hist_slope",
                    "adx": "btc_w_adx",
                })
                btc_daily_map = btc_daily_map.merge(btc_weekly_map, on="week_start", how="left")
                btc_daily_map = btc_daily_map[["date", "btc_w_macd_hist_slope", "btc_w_adx"]]

                dataframe = merge_informative_pair(
                    dataframe, btc_daily_map, self.timeframe, "1d", ffill=True
                )

                btc_w_slope = pd.to_numeric(dataframe.get("btc_w_macd_hist_slope_1d"), errors="coerce")
                btc_w_slope_up = btc_w_slope > 0
                btc_w_slope_down = btc_w_slope < 0
                btc_w_adx = pd.to_numeric(dataframe.get("btc_w_adx_1d"), errors="coerce").fillna(0.0)

                if screen1_require_adx:
                    dataframe["btc_weekly_trend_up"] = btc_w_slope_up & (btc_w_adx > self.adx_threshold.value)
                else:
                    dataframe["btc_weekly_trend_up"] = btc_w_slope_up

                dataframe["btc_weekly_trend_down"] = btc_w_slope_down
                dataframe["btc_weekly_trend_strong"] = btc_w_adx > self.adx_threshold.value

                btc_up = dataframe.get("btc_weekly_trend_up")
                btc_down = dataframe.get("btc_weekly_trend_down")
                btc_up = btc_up.fillna(False) if btc_up is not None else pd.Series(False, index=dataframe.index)
                btc_down = btc_down.fillna(False) if btc_down is not None else pd.Series(False, index=dataframe.index)

                dataframe["btc_weekly_trend_up"] = btc_up
                dataframe["btc_weekly_trend_down"] = btc_down
                dataframe["btc_weekly_trend_strong"] = dataframe.get("btc_weekly_trend_strong", False).fillna(False)

                dataframe["btc_weekly_dir"] = pd.Series(0, index=dataframe.index, dtype="int64")
                dataframe.loc[btc_up & ~btc_down, "btc_weekly_dir"] = 1
                dataframe.loc[btc_down & ~btc_up, "btc_weekly_dir"] = -1
            else:
                dataframe["btc_weekly_trend_up"] = True
                dataframe["btc_weekly_trend_down"] = False
                dataframe["btc_weekly_trend_strong"] = False
                dataframe["btc_weekly_dir"] = pd.Series(0, index=dataframe.index, dtype="int64")
        else:
            dataframe["btc_weekly_trend_up"] = True
            dataframe["btc_weekly_trend_down"] = False
            dataframe["btc_weekly_trend_strong"] = False
            dataframe["btc_weekly_dir"] = pd.Series(0, index=dataframe.index, dtype="int64")

        # 2. 第二屏：四组独立过滤器（多空分开）
        pair_daily = None
        try:
            pair_daily = self.dp.get_pair_dataframe(metadata["pair"], "1d")
        except Exception:
            pair_daily = None

        if pair_daily is None or pair_daily.empty:
            spot_pair = metadata["pair"].split(":", 1)[0] if ":" in metadata["pair"] else None
            if spot_pair:
                try:
                    pair_daily = self.dp.get_pair_dataframe(spot_pair, "1d")
                except Exception:
                    pair_daily = None

        if pair_daily is None or pair_daily.empty:
            if "date" in dataframe.columns and not dataframe.empty:
                base = dataframe[["date", "open", "high", "low", "close", "volume"]].copy()
                base = base.dropna(subset=["date"]).set_index("date", drop=False).sort_index()
                pair_daily = base.resample("1D").agg({
                    "date": "last",
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }).dropna(subset=["close"]).reset_index(drop=True)

        if pair_daily is not None and not pair_daily.empty:
            for col in ("open", "high", "low", "close", "volume"):
                if col in pair_daily.columns:
                    pair_daily[col] = pd.to_numeric(pair_daily[col], errors="coerce")
            if "close" in pair_daily.columns:
                pair_daily = pair_daily.loc[pair_daily["close"].notna()].copy()

            # 基本指标计算（四组共用）
            pair_daily["rsi"] = ta.RSI(pair_daily, timeperiod=14)
            pair_daily["ema13"] = ta.EMA(pair_daily, timeperiod=13)
            stoch_res = ta.STOCH(pair_daily)  # 默认参数(14,3,3)
            if isinstance(stoch_res, pd.DataFrame):
                slowk = stoch_res.get("slowk")
            elif isinstance(stoch_res, dict):
                slowk = stoch_res.get("slowk")
            else:
                slowk, _ = stoch_res

            pair_daily["stoch_k"] = pd.to_numeric(slowk, errors="coerce")
            pair_daily["cci"] = ta.CCI(pair_daily, timeperiod=20)
            pair_daily["adx"] = ta.ADX(pair_daily, timeperiod=14)

            pair_daily["atr"] = ta.ATR(pair_daily, timeperiod=14)
            close_safe = pair_daily["close"].replace(0, pd.NA)
            pair_daily["atr_pct"] = (pair_daily["atr"] / close_safe).replace([float("inf"), float("-inf")], pd.NA)
            
            # MACD相关
            macd_res = ta.MACD(pair_daily)
            if isinstance(macd_res, pd.DataFrame):
                macdhist = macd_res.get("macdhist")
            elif isinstance(macd_res, dict):
                macdhist = macd_res.get("macdhist")
            else:
                _, _, macdhist = macd_res

            pair_daily["macdhist"] = pd.to_numeric(macdhist, errors="coerce")
            pair_daily = pair_daily.loc[pair_daily["macdhist"].notna()].copy()
            pair_daily["macd_hist_up"] = (pair_daily["macdhist"] > 0) & (pair_daily["macdhist"] > pair_daily["macdhist"].shift(1))
            pair_daily["macd_hist_down"] = (pair_daily["macdhist"] < 0) & (pair_daily["macdhist"] < pair_daily["macdhist"].shift(1))
            pair_daily["macd_hist_slope_up"] = pair_daily["macdhist"] > pair_daily["macdhist"].shift(1)
            pair_daily["macd_hist_slope_down"] = pair_daily["macdhist"] < pair_daily["macdhist"].shift(1)
            
            # 成交量
            pair_daily["volume_ma"] = pair_daily["volume"].rolling(20).mean()
            pair_daily["volume_spike"] = pair_daily["volume"] > pair_daily["volume_ma"] * self.volume_multiplier.value

            disable_daily_filter_groups = int(os.environ.get("FT_DISABLE_DAILY_FILTER_GROUPS", "1") or "1") != 0
            
            # ====================
            # 第一组：Elder 原版（多空分开）
            # ====================
            if disable_daily_filter_groups:
                pair_daily["elder_condition_long"] = False
                pair_daily["elder_condition_short"] = False
            else:
                pair_daily["raw_force"] = (pair_daily["close"] - pair_daily["close"].shift(1)) * pair_daily["volume"]
                pair_daily["force_index"] = ta.EMA(pair_daily["raw_force"], timeperiod=13)

                lookback_period = 20
                pair_daily["price_new_low"] = (
                    pair_daily["close"] < pair_daily["close"].rolling(lookback_period).min().shift(1)
                )
                pair_daily["force_higher_low"] = (
                    pair_daily["force_index"] > pair_daily["force_index"].rolling(lookback_period).min().shift(1)
                )
                pair_daily["force_double_bottom"] = (
                    (pair_daily["force_index"] > pair_daily["force_index"].shift(1))
                    & (pair_daily["force_index"].shift(1) < pair_daily["force_index"].shift(2))
                )

                pair_daily["elder_condition_long"] = (
                    (pair_daily["rsi"] < 30)
                    & pair_daily["price_new_low"]
                    & (pair_daily["force_higher_low"] | pair_daily["force_double_bottom"])
                )

                pair_daily["price_new_high"] = (
                    pair_daily["close"] > pair_daily["close"].rolling(lookback_period).max().shift(1)
                )
                pair_daily["force_lower_high"] = (
                    pair_daily["force_index"] < pair_daily["force_index"].rolling(lookback_period).max().shift(1)
                )
                pair_daily["force_double_top"] = (
                    (pair_daily["force_index"] < pair_daily["force_index"].shift(1))
                    & (pair_daily["force_index"].shift(1) > pair_daily["force_index"].shift(2))
                )

                pair_daily["elder_condition_short"] = (
                    (pair_daily["rsi"] > 70)
                    & pair_daily["price_new_high"]
                    & (pair_daily["force_lower_high"] | pair_daily["force_double_top"])
                )
            
            # ====================
            # 第二组：Freqtrade 社区热门（多空分开）
            # ====================
            if disable_daily_filter_groups:
                pair_daily["freqtrade_condition_long"] = False
                pair_daily["freqtrade_condition_short"] = False
            else:
                pair_daily["rsi_oversold"] = pair_daily["rsi"] < self.rsi_buy.value
                pair_daily["stoch_oversold"] = pair_daily["stoch_k"] < 20
                pair_daily["cci_oversold"] = pair_daily["cci"] < -100

                pair_daily["freqtrade_vote_long"] = (
                    pair_daily["rsi_oversold"].astype(int)
                    + pair_daily["stoch_oversold"].astype(int)
                    + pair_daily["cci_oversold"].astype(int)
                )
                pair_daily["freqtrade_condition_long"] = pair_daily["freqtrade_vote_long"] >= 2

                pair_daily["rsi_overbought"] = pair_daily["rsi"] > self.rsi_sell.value
                pair_daily["stoch_overbought"] = pair_daily["stoch_k"] > 80
                pair_daily["cci_overbought"] = pair_daily["cci"] > 100

                pair_daily["freqtrade_vote_short"] = (
                    pair_daily["rsi_overbought"].astype(int)
                    + pair_daily["stoch_overbought"].astype(int)
                    + pair_daily["cci_overbought"].astype(int)
                )
                pair_daily["freqtrade_condition_short"] = pair_daily["freqtrade_vote_short"] >= 2
            
            # ====================
            # 第三组：TradingView Pine Script 经典（多空分开）
            # ====================
            if disable_daily_filter_groups:
                pair_daily["tradingview_condition_long"] = False
                pair_daily["tradingview_condition_short"] = False
            else:
                pair_daily["price_near_ema"] = (
                    (pair_daily["close"] < pair_daily["ema13"] * 1.02)
                    & (pair_daily["close"] > pair_daily["ema13"] * 0.98)
                )
                pair_daily["tradingview_condition_long"] = (
                    (pair_daily["rsi"] < 35)
                    & pair_daily["macd_hist_up"]
                    & pair_daily["price_near_ema"]
                )

                pair_daily["tradingview_condition_short"] = (
                    (pair_daily["rsi"] > 65)
                    & pair_daily["macd_hist_down"]
                    & pair_daily["price_near_ema"]
                )
            
            # ====================
            # 第四组：量化机构风格（多空分开）
            # ====================
            # Williams %R (14日)
            pair_daily["williams_r"] = ta.WILLR(pair_daily, timeperiod=14)
            
            # 多头
            pair_daily["williams_oversold"] = pair_daily["williams_r"] < -80
            pair_daily["rsi_oversold_qf"] = pair_daily["rsi"] < 30
            pair_daily["stoch_oversold_qf"] = pair_daily["stoch_k"] < 20
            pair_daily["qf_oscillator_vote_long"] = (
                pair_daily["rsi_oversold_qf"].astype(int) +
                pair_daily["stoch_oversold_qf"].astype(int) +
                pair_daily["williams_oversold"].astype(int)
            )
            pair_daily["mean"] = pair_daily["close"].rolling(20).mean()
            pair_daily["std"] = pair_daily["close"].rolling(20).std().replace(0, 1e-10)
            pair_daily["lower_band"] = pair_daily["mean"] - 1.5 * pair_daily["std"]
            pair_daily["mean_reversion_long"] = pair_daily["close"] < pair_daily["lower_band"]
            if disable_daily_filter_groups:
                pair_daily["quant_condition_long"] = False
            else:
                pair_daily["quant_condition_long"] = (
                    (pair_daily["qf_oscillator_vote_long"] >= 2)
                    & pair_daily["mean_reversion_long"]
                )
            
            # 空头
            pair_daily["williams_overbought"] = pair_daily["williams_r"] > -20
            pair_daily["rsi_overbought_qf"] = pair_daily["rsi"] > 70
            pair_daily["stoch_overbought_qf"] = pair_daily["stoch_k"] > 80
            pair_daily["qf_oscillator_vote_short"] = (
                pair_daily["rsi_overbought_qf"].astype(int) +
                pair_daily["stoch_overbought_qf"].astype(int) +
                pair_daily["williams_overbought"].astype(int)
            )
            pair_daily["upper_band"] = pair_daily["mean"] + 1.5 * pair_daily["std"]
            pair_daily["mean_reversion_short"] = pair_daily["close"] > pair_daily["upper_band"]
            if disable_daily_filter_groups:
                pair_daily["quant_condition_short"] = False
            else:
                pair_daily["quant_condition_short"] = (
                    (pair_daily["qf_oscillator_vote_short"] >= 2)
                    & pair_daily["mean_reversion_short"]
                )

            mean_safe = pair_daily["mean"].replace(0, pd.NA)
            pair_daily["bb_width"] = ((pair_daily["upper_band"] - pair_daily["lower_band"]) / mean_safe).replace([float("inf"), float("-inf")], pd.NA)

            bb_width_ma_len = int(os.environ.get("FT_DAILY_BB_WIDTH_MA", "20") or "20")
            bb_width_ma_len = max(2, bb_width_ma_len)
            pair_daily["bb_width_ma"] = pair_daily["bb_width"].rolling(bb_width_ma_len).mean()
            pair_daily["bb_width_expand"] = (
                (pair_daily["bb_width"] > pair_daily["bb_width"].shift(1))
                & (pair_daily["bb_width"] > pair_daily["bb_width_ma"])
            ).fillna(False)

            kc_len = int(os.environ.get("FT_DAILY_KC_LEN", "20") or "20")
            kc_mult = float(abs(self._get_env_float("FT_DAILY_KC_MULT", 1.5)))
            kc_len = max(2, kc_len)
            pair_daily["kc_mid"] = ta.EMA(pair_daily, timeperiod=kc_len)
            pair_daily["kc_upper"] = pair_daily["kc_mid"] + (pair_daily["atr"] * kc_mult)
            pair_daily["kc_lower"] = pair_daily["kc_mid"] - (pair_daily["atr"] * kc_mult)
            pair_daily["bb_squeeze_on"] = (
                (pair_daily["upper_band"] < pair_daily["kc_upper"]) & (pair_daily["lower_band"] > pair_daily["kc_lower"])
            ).fillna(False)

            prev_h = pair_daily["high"].shift(1)
            prev_l = pair_daily["low"].shift(1)
            prev_c = pair_daily["close"].shift(1)
            pair_daily["pivot_pp"] = (prev_h + prev_l + prev_c) / 3.0
            pair_daily["pivot_r1"] = (2.0 * pair_daily["pivot_pp"]) - prev_l
            pair_daily["pivot_s1"] = (2.0 * pair_daily["pivot_pp"]) - prev_h

            enable_daily_trend_follow = int(os.environ.get("FT_DAILY_TREND_FOLLOW", "1") or "1") != 0
            if enable_daily_trend_follow:
                tf_ema_fast = int(os.environ.get("FT_DAILY_TF_EMA_FAST", "20") or "20")
                tf_ema_slow = int(os.environ.get("FT_DAILY_TF_EMA_SLOW", "50") or "50")
                tf_pullback_pct = self._get_env_float("FT_DAILY_TF_PULLBACK_PCT", 0.015)
                tf_min_adx = self._get_env_float("FT_DAILY_TF_MIN_ADX", 18.0)
                tf_require_macd_hist_up = int(os.environ.get("FT_DAILY_TF_REQUIRE_MACD_HIST_UP", "0") or "0") != 0

                tf_ema_fast = max(2, tf_ema_fast)
                tf_ema_slow = max(tf_ema_fast + 1, tf_ema_slow)
                tf_pullback_pct = max(0.0, float(tf_pullback_pct))
                tf_min_adx = max(0.0, float(tf_min_adx))

                pair_daily["tf_ema_fast"] = ta.EMA(pair_daily, timeperiod=tf_ema_fast)
                pair_daily["tf_ema_slow"] = ta.EMA(pair_daily, timeperiod=tf_ema_slow)

                tf_trend_ok = (pair_daily["tf_ema_fast"] > pair_daily["tf_ema_slow"]) & (pair_daily["close"] > pair_daily["tf_ema_slow"])
                tf_pullback_touch = pair_daily["low"] <= (pair_daily["tf_ema_fast"] * (1.0 + tf_pullback_pct))
                tf_reclaim = pair_daily["close"] > pair_daily["tf_ema_fast"]

                if tf_min_adx > 0:
                    tf_adx_ok = pair_daily["adx"] > tf_min_adx
                else:
                    tf_adx_ok = pd.Series(True, index=pair_daily.index)

                if tf_require_macd_hist_up:
                    tf_macd_ok = pair_daily["macd_hist_up"]
                else:
                    tf_macd_ok = pd.Series(True, index=pair_daily.index)

                pair_daily["trend_follow_condition_long"] = tf_trend_ok & tf_pullback_touch & tf_reclaim & tf_adx_ok & tf_macd_ok
                pair_daily["tf_trend_ok"] = tf_trend_ok
                pair_daily["tf_pullback_touch"] = tf_pullback_touch
                pair_daily["tf_reclaim"] = tf_reclaim
                pair_daily["tf_adx_ok"] = tf_adx_ok
                pair_daily["tf_macd_ok"] = tf_macd_ok
            else:
                pair_daily["trend_follow_condition_long"] = False
                pair_daily["tf_ema_fast"] = pd.NA
                pair_daily["tf_ema_slow"] = pd.NA
                pair_daily["tf_trend_ok"] = False
                pair_daily["tf_pullback_touch"] = False
                pair_daily["tf_reclaim"] = False
                pair_daily["tf_adx_ok"] = False
                pair_daily["tf_macd_ok"] = False

            daily_vol_thr = abs(self._get_env_float("FT_DAILY_VOL_ATR_PCT", 0.02))
            daily_donchian_period = int(os.environ.get("FT_DAILY_DONCHIAN_PERIOD", "20") or "20")
            daily_donchian_period = max(2, daily_donchian_period)
            pair_daily["d_donchian_high"] = pair_daily["high"].rolling(daily_donchian_period).max().shift(1)
            pair_daily["d_donchian_low"] = pair_daily["low"].rolling(daily_donchian_period).min().shift(1)
            d_breakout_long = pair_daily["close"] > pair_daily["d_donchian_high"]
            d_breakout_short = pair_daily["close"] < pair_daily["d_donchian_low"]

            d_ema_fast = int(os.environ.get("FT_DAILY_TIMING_EMA_FAST", "20") or "20")
            d_ema_slow = int(os.environ.get("FT_DAILY_TIMING_EMA_SLOW", "50") or "50")
            d_ema_fast = max(2, d_ema_fast)
            d_ema_slow = max(d_ema_fast + 1, d_ema_slow)
            pair_daily["d_ema_fast"] = ta.EMA(pair_daily, timeperiod=d_ema_fast)
            pair_daily["d_ema_slow"] = ta.EMA(pair_daily, timeperiod=d_ema_slow)
            d_trend_up = (pair_daily["d_ema_fast"] > pair_daily["d_ema_slow"]) & (pair_daily["close"] > pair_daily["d_ema_slow"])
            d_trend_down = (pair_daily["d_ema_fast"] < pair_daily["d_ema_slow"]) & (pair_daily["close"] < pair_daily["d_ema_slow"])
            d_trend_soft_up = pair_daily["d_ema_fast"] > pair_daily["d_ema_slow"]
            d_trend_soft_down = pair_daily["d_ema_fast"] < pair_daily["d_ema_slow"]

            d_pullback_pct = abs(self._get_env_float("FT_DAILY_TIMING_PULLBACK_PCT", 0.012))
            d_pullback_touch_long = pair_daily["low"] <= (pair_daily["d_ema_fast"] * (1.0 + d_pullback_pct))
            d_reclaim_long = pair_daily["close"] > pair_daily["d_ema_fast"]
            d_pullback_touch_short = pair_daily["high"] >= (pair_daily["d_ema_fast"] * (1.0 - d_pullback_pct))
            d_reclaim_short = pair_daily["close"] < pair_daily["d_ema_fast"]

            d_body = (pair_daily["close"] - pair_daily["open"]).abs()
            d_total_range = pair_daily["high"] - pair_daily["low"]
            d_lower_shadow = pair_daily[["open", "close"]].min(axis=1) - pair_daily["low"]
            d_upper_shadow = pair_daily["high"] - pair_daily[["open", "close"]].max(axis=1)
            d_total_range_safe = d_total_range.replace(0, 1e-10)

            d_hammer = (
                (d_lower_shadow > 2 * d_body)
                & (d_upper_shadow < d_body * 0.3)
                & (d_total_range > 0)
                & (d_lower_shadow > d_total_range_safe * 0.6)
            )
            d_shooting_star = (
                (d_upper_shadow > 2 * d_body)
                & (d_lower_shadow < d_body * 0.3)
                & (d_total_range > 0)
                & (d_upper_shadow > d_total_range_safe * 0.6)
            )
            d_engulfing_bull = (
                (pair_daily["close"] > pair_daily["open"])
                & (pair_daily["close"].shift(1) < pair_daily["open"].shift(1))
                & (pair_daily["open"] < pair_daily["close"].shift(1))
                & (pair_daily["close"] > pair_daily["open"].shift(1))
            )
            d_engulfing_bear = (
                (pair_daily["close"] < pair_daily["open"])
                & (pair_daily["close"].shift(1) > pair_daily["open"].shift(1))
                & (pair_daily["open"] > pair_daily["close"].shift(1))
                & (pair_daily["close"] < pair_daily["open"].shift(1))
            )
            pair_daily["d_bull_reversal"] = (d_hammer | d_engulfing_bull).fillna(False)
            pair_daily["d_bear_reversal"] = (d_shooting_star | d_engulfing_bear).fillna(False)

            d_dir = (pair_daily["close"] > pair_daily["close"].shift(1)).astype(int) - (pair_daily["close"] < pair_daily["close"].shift(1)).astype(int)
            pair_daily["d_obv"] = (d_dir.fillna(0) * pair_daily["volume"].fillna(0)).cumsum()
            pair_daily["d_obv_slope_up"] = pair_daily["d_obv"] > pair_daily["d_obv"].shift(1)
            pair_daily["d_obv_slope_down"] = pair_daily["d_obv"] < pair_daily["d_obv"].shift(1)

            d_rsi_up = pair_daily["rsi"] > pair_daily["rsi"].shift(1)
            d_rsi_down = pair_daily["rsi"] < pair_daily["rsi"].shift(1)
            d_vol_high = pair_daily["atr_pct"].fillna(0.0) >= float(daily_vol_thr)
            pair_daily["d_vol_high"] = d_vol_high

            d_swing_hl = (pair_daily["low"] > pair_daily["low"].shift(1)) & (pair_daily["close"] > pair_daily["open"])
            d_swing_lh = (pair_daily["high"] < pair_daily["high"].shift(1)) & (pair_daily["close"] < pair_daily["open"])

            d_pivot_break_long = pair_daily["close"] > pair_daily["pivot_r1"]
            d_pivot_break_short = pair_daily["close"] < pair_daily["pivot_s1"]

            d_squeeze_release_long = (
                pair_daily["bb_squeeze_on"].shift(1).fillna(False)
                & (~pair_daily["bb_squeeze_on"])
                & (pair_daily["close"] > pair_daily["mean"])
            ).fillna(False)
            d_squeeze_release_short = (
                pair_daily["bb_squeeze_on"].shift(1).fillna(False)
                & (~pair_daily["bb_squeeze_on"])
                & (pair_daily["close"] < pair_daily["mean"])
            ).fillna(False)

            breakout_min_votes = int(os.environ.get("FT_DAILY_TIMING_BREAKOUT_MIN_VOTES", "2") or "2")
            pullback_min_votes = int(os.environ.get("FT_DAILY_TIMING_PULLBACK_MIN_VOTES", "2") or "2")
            mr_min_votes = int(os.environ.get("FT_DAILY_TIMING_MR_MIN_VOTES", "2") or "2")
            breakout_min_votes = max(1, breakout_min_votes)
            pullback_min_votes = max(1, pullback_min_votes)
            mr_min_votes = max(1, mr_min_votes)

            d_breakout_votes_long = (
                d_trend_up.astype(int)
                + (d_breakout_long | d_pivot_break_long | d_squeeze_release_long).astype(int)
                + pair_daily["volume_spike"].astype(int)
                + pair_daily["macd_hist_slope_up"].astype(int)
                + pair_daily["d_bull_reversal"].astype(int)
                + (d_vol_high | pair_daily["bb_width_expand"]).astype(int)
                + pair_daily["d_obv_slope_up"].astype(int)
                + d_swing_hl.astype(int)
            )
            d_breakout_votes_short = (
                d_trend_down.astype(int)
                + (d_breakout_short | d_pivot_break_short | d_squeeze_release_short).astype(int)
                + pair_daily["volume_spike"].astype(int)
                + pair_daily["macd_hist_slope_down"].astype(int)
                + pair_daily["d_bear_reversal"].astype(int)
                + (d_vol_high | pair_daily["bb_width_expand"]).astype(int)
                + pair_daily["d_obv_slope_down"].astype(int)
                + d_swing_lh.astype(int)
            )
            pair_daily["d_vote_breakout_long"] = d_breakout_votes_long
            pair_daily["d_vote_breakout_short"] = d_breakout_votes_short

            breakout_gate_long = (
                (d_trend_up | d_trend_soft_up | pair_daily["macd_hist_up"].fillna(False))
                & (d_breakout_long | d_pivot_break_long | d_squeeze_release_long)
            )
            breakout_gate_short = (
                (d_trend_down | d_trend_soft_down | pair_daily["macd_hist_down"].fillna(False))
                & (d_breakout_short | d_pivot_break_short | d_squeeze_release_short)
            )
            breakout_confirm_long = d_vol_high | pair_daily["volume_spike"].fillna(False) | pair_daily["bb_width_expand"].fillna(False)
            breakout_confirm_short = d_vol_high | pair_daily["volume_spike"].fillna(False) | pair_daily["bb_width_expand"].fillna(False)

            pair_daily["timing_breakout_long"] = (
                breakout_gate_long
                & breakout_confirm_long
                & (d_breakout_votes_long >= breakout_min_votes)
            ).fillna(False)
            pair_daily["timing_breakout_short"] = (
                breakout_gate_short
                & breakout_confirm_short
                & (d_breakout_votes_short >= breakout_min_votes)
            ).fillna(False)

            d_pullback_votes_long = (
                d_trend_up.astype(int)
                + d_pullback_touch_long.astype(int)
                + d_reclaim_long.astype(int)
                + pair_daily["macd_hist_slope_up"].astype(int)
                + d_rsi_up.astype(int)
                + pair_daily["d_bull_reversal"].astype(int)
                + pair_daily["d_obv_slope_up"].astype(int)
                + d_swing_hl.astype(int)
                + (pair_daily["close"] > pair_daily["pivot_pp"]).astype(int)
            )
            d_pullback_votes_short = (
                d_trend_down.astype(int)
                + d_pullback_touch_short.astype(int)
                + d_reclaim_short.astype(int)
                + pair_daily["macd_hist_slope_down"].astype(int)
                + d_rsi_down.astype(int)
                + pair_daily["d_bear_reversal"].astype(int)
                + pair_daily["d_obv_slope_down"].astype(int)
                + d_swing_lh.astype(int)
                + (pair_daily["close"] < pair_daily["pivot_pp"]).astype(int)
            )
            pair_daily["d_vote_pullback_long"] = d_pullback_votes_long
            pair_daily["d_vote_pullback_short"] = d_pullback_votes_short
            pullback_gate_long = (
                pair_daily["trend_follow_condition_long"].fillna(False)
                | (d_trend_up & d_pullback_touch_long & d_reclaim_long)
            )
            pair_daily["timing_pullback_long"] = (
                pullback_gate_long
                & (d_pullback_votes_long >= pullback_min_votes)
            ).fillna(False)
            pair_daily["timing_pullback_short"] = (
                d_trend_down
                & d_pullback_touch_short
                & d_reclaim_short
                & (d_pullback_votes_short >= pullback_min_votes)
            ).fillna(False)

            mr_max_adx = float(abs(self._get_env_float("FT_DAILY_TIMING_MR_MAX_ADX", 20.0)))
            mr_z_thr = float(abs(self._get_env_float("FT_DAILY_TIMING_MR_Z", 1.5)))
            z = (pair_daily["close"] - pair_daily["mean"]) / pair_daily["std"].replace(0, 1e-10)
            mr_z_long = z <= (-mr_z_thr)
            mr_z_short = z >= mr_z_thr

            d_mr_votes_long = (
                mr_z_long.astype(int)
                + pair_daily["mean_reversion_long"].astype(int)
                + (pair_daily["qf_oscillator_vote_long"] >= 2).astype(int)
                + pair_daily["d_bull_reversal"].astype(int)
                + (pair_daily["rsi"] < self.rsi_buy.value).astype(int)
                + pair_daily["bb_squeeze_on"].astype(int)
            )
            d_mr_votes_short = (
                mr_z_short.astype(int)
                + pair_daily["mean_reversion_short"].astype(int)
                + (pair_daily["qf_oscillator_vote_short"] >= 2).astype(int)
                + pair_daily["d_bear_reversal"].astype(int)
                + (pair_daily["rsi"] > self.rsi_sell.value).astype(int)
                + pair_daily["bb_squeeze_on"].astype(int)
            )

            mr_base_long = (
                mr_z_long
                | pair_daily["mean_reversion_long"].fillna(False)
                | (pair_daily["qf_oscillator_vote_long"].fillna(0) >= 2)
            ).fillna(False)
            mr_base_short = (
                mr_z_short
                | pair_daily["mean_reversion_short"].fillna(False)
                | (pair_daily["qf_oscillator_vote_short"].fillna(0) >= 2)
            ).fillna(False)
            pair_daily["d_vote_mr_long"] = d_mr_votes_long
            pair_daily["d_vote_mr_short"] = d_mr_votes_short
            pair_daily["timing_mr_long"] = (
                (pair_daily["adx"].fillna(0.0) <= mr_max_adx)
                & mr_base_long
                & (d_mr_votes_long >= mr_min_votes)
            ).fillna(False)
            pair_daily["timing_mr_short"] = (
                (pair_daily["adx"].fillna(0.0) <= mr_max_adx)
                & mr_base_short
                & (d_mr_votes_short >= mr_min_votes)
            ).fillna(False)
            
            # 合并所有条件到主时间框架
            dataframe = merge_informative_pair(
                dataframe, 
                pair_daily[[
                    "date", 
                    "elder_condition_long", "elder_condition_short",
                    "freqtrade_condition_long", "freqtrade_condition_short",
                    "tradingview_condition_long", "tradingview_condition_short",
                    "quant_condition_long", "quant_condition_short",
                    "trend_follow_condition_long",
                    "pivot_pp", "pivot_r1", "pivot_s1",
                    "bb_width_ma", "bb_width_expand", "bb_squeeze_on",
                    "d_donchian_high", "d_donchian_low",
                    "d_ema_fast", "d_ema_slow",
                    "d_vol_high",
                    "d_vote_breakout_long", "d_vote_breakout_short",
                    "d_vote_pullback_long", "d_vote_pullback_short",
                    "d_vote_mr_long", "d_vote_mr_short",
                    "timing_breakout_long", "timing_breakout_short",
                    "timing_pullback_long", "timing_pullback_short",
                    "timing_mr_long", "timing_mr_short",
                    "tf_ema_fast", "tf_ema_slow",
                    "tf_trend_ok", "tf_pullback_touch", "tf_reclaim", "tf_adx_ok", "tf_macd_ok",
                    "adx",
                    "atr_pct", "bb_width",
                    "volume_spike", "macd_hist_up", "macd_hist_down", "macd_hist_slope_up", "macd_hist_slope_down"
                ]], 
                self.timeframe, "1d", ffill=True
            )
            
            dataframe.rename(columns={
                "elder_condition_long_1d": "daily_elder_long",
                "elder_condition_short_1d": "daily_elder_short",
                "freqtrade_condition_long_1d": "daily_freqtrade_long",
                "freqtrade_condition_short_1d": "daily_freqtrade_short",
                "tradingview_condition_long_1d": "daily_tradingview_long",
                "tradingview_condition_short_1d": "daily_tradingview_short",
                "quant_condition_long_1d": "daily_quant_long",
                "quant_condition_short_1d": "daily_quant_short",
                "trend_follow_condition_long_1d": "daily_trend_follow_long",
                "d_donchian_high_1d": "diag_daily_donchian_high",
                "d_donchian_low_1d": "diag_daily_donchian_low",
                "d_ema_fast_1d": "diag_daily_timing_ema_fast",
                "d_ema_slow_1d": "diag_daily_timing_ema_slow",
                "d_vol_high_1d": "diag_daily_vol_high",
                "d_vote_breakout_long_1d": "diag_daily_vote_breakout_long",
                "d_vote_breakout_short_1d": "diag_daily_vote_breakout_short",
                "d_vote_pullback_long_1d": "diag_daily_vote_pullback_long",
                "d_vote_pullback_short_1d": "diag_daily_vote_pullback_short",
                "d_vote_mr_long_1d": "diag_daily_vote_mr_long",
                "d_vote_mr_short_1d": "diag_daily_vote_mr_short",
                "pivot_pp_1d": "diag_daily_pivot_pp",
                "pivot_r1_1d": "diag_daily_pivot_r1",
                "pivot_s1_1d": "diag_daily_pivot_s1",
                "bb_width_ma_1d": "diag_daily_bb_width_ma",
                "bb_width_expand_1d": "daily_bb_width_expand",
                "bb_squeeze_on_1d": "daily_bb_squeeze_on",
                "timing_breakout_long_1d": "daily_timing_breakout_long",
                "timing_breakout_short_1d": "daily_timing_breakout_short",
                "timing_pullback_long_1d": "daily_timing_pullback_long",
                "timing_pullback_short_1d": "daily_timing_pullback_short",
                "timing_mr_long_1d": "daily_timing_mr_long",
                "timing_mr_short_1d": "daily_timing_mr_short",
                "tf_ema_fast_1d": "diag_daily_tf_ema_fast",
                "tf_ema_slow_1d": "diag_daily_tf_ema_slow",
                "tf_trend_ok_1d": "diag_daily_tf_trend_ok",
                "tf_pullback_touch_1d": "diag_daily_tf_pullback_touch",
                "tf_reclaim_1d": "diag_daily_tf_reclaim",
                "tf_adx_ok_1d": "diag_daily_tf_adx_ok",
                "tf_macd_ok_1d": "diag_daily_tf_macd_ok",
                "adx_1d": "daily_adx",
                "volume_spike_1d": "daily_volume_spike",
                "macd_hist_up_1d": "daily_macd_hist_up",
                "macd_hist_down_1d": "daily_macd_hist_down",
                "macd_hist_slope_up_1d": "daily_macd_hist_slope_up",
                "macd_hist_slope_down_1d": "daily_macd_hist_slope_down",
                "atr_pct_1d": "daily_atr_pct",
                "bb_width_1d": "daily_bb_width"
            }, inplace=True)
            
            # NaN处理
            condition_cols = [
                "daily_elder_long", "daily_elder_short",
                "daily_freqtrade_long", "daily_freqtrade_short",
                "daily_tradingview_long", "daily_tradingview_short",
                "daily_quant_long", "daily_quant_short",
                "daily_trend_follow_long",
                "daily_timing_breakout_long", "daily_timing_breakout_short",
                "daily_timing_pullback_long", "daily_timing_pullback_short",
                "daily_timing_mr_long", "daily_timing_mr_short"
            ]
            for col in condition_cols:
                dataframe[col] = dataframe[col].fillna(False)

            dataframe["daily_bb_width_expand"] = dataframe.get("daily_bb_width_expand", False).fillna(False)
            dataframe["daily_bb_squeeze_on"] = dataframe.get("daily_bb_squeeze_on", False).fillna(False)

            dataframe["daily_adx"] = pd.to_numeric(dataframe.get("daily_adx"), errors="coerce").fillna(0.0)
            dataframe["daily_atr_pct"] = pd.to_numeric(dataframe.get("daily_atr_pct"), errors="coerce").fillna(0.0)
            dataframe["daily_bb_width"] = pd.to_numeric(dataframe.get("daily_bb_width"), errors="coerce").fillna(0.0)

            dataframe["diag_daily_pivot_pp"] = pd.to_numeric(dataframe.get("diag_daily_pivot_pp"), errors="coerce")
            dataframe["diag_daily_pivot_r1"] = pd.to_numeric(dataframe.get("diag_daily_pivot_r1"), errors="coerce")
            dataframe["diag_daily_pivot_s1"] = pd.to_numeric(dataframe.get("diag_daily_pivot_s1"), errors="coerce")
            dataframe["diag_daily_bb_width_ma"] = pd.to_numeric(dataframe.get("diag_daily_bb_width_ma"), errors="coerce")

            dataframe["diag_daily_donchian_high"] = pd.to_numeric(dataframe.get("diag_daily_donchian_high"), errors="coerce")
            dataframe["diag_daily_donchian_low"] = pd.to_numeric(dataframe.get("diag_daily_donchian_low"), errors="coerce")
            dataframe["diag_daily_timing_ema_fast"] = pd.to_numeric(dataframe.get("diag_daily_timing_ema_fast"), errors="coerce")
            dataframe["diag_daily_timing_ema_slow"] = pd.to_numeric(dataframe.get("diag_daily_timing_ema_slow"), errors="coerce")
            dataframe["diag_daily_vol_high"] = dataframe.get("diag_daily_vol_high", False).fillna(False)
            dataframe["diag_daily_vote_breakout_long"] = pd.to_numeric(dataframe.get("diag_daily_vote_breakout_long"), errors="coerce").fillna(0).astype("int64")
            dataframe["diag_daily_vote_breakout_short"] = pd.to_numeric(dataframe.get("diag_daily_vote_breakout_short"), errors="coerce").fillna(0).astype("int64")
            dataframe["diag_daily_vote_pullback_long"] = pd.to_numeric(dataframe.get("diag_daily_vote_pullback_long"), errors="coerce").fillna(0).astype("int64")
            dataframe["diag_daily_vote_pullback_short"] = pd.to_numeric(dataframe.get("diag_daily_vote_pullback_short"), errors="coerce").fillna(0).astype("int64")
            dataframe["diag_daily_vote_mr_long"] = pd.to_numeric(dataframe.get("diag_daily_vote_mr_long"), errors="coerce").fillna(0).astype("int64")
            dataframe["diag_daily_vote_mr_short"] = pd.to_numeric(dataframe.get("diag_daily_vote_mr_short"), errors="coerce").fillna(0).astype("int64")

            dataframe["diag_daily_tf_ema_fast"] = pd.to_numeric(dataframe.get("diag_daily_tf_ema_fast"), errors="coerce")
            dataframe["diag_daily_tf_ema_slow"] = pd.to_numeric(dataframe.get("diag_daily_tf_ema_slow"), errors="coerce")
            dataframe["diag_daily_tf_trend_ok"] = dataframe.get("diag_daily_tf_trend_ok", False).fillna(False)
            dataframe["diag_daily_tf_pullback_touch"] = dataframe.get("diag_daily_tf_pullback_touch", False).fillna(False)
            dataframe["diag_daily_tf_reclaim"] = dataframe.get("diag_daily_tf_reclaim", False).fillna(False)
            dataframe["diag_daily_tf_adx_ok"] = dataframe.get("diag_daily_tf_adx_ok", False).fillna(False)
            dataframe["diag_daily_tf_macd_ok"] = dataframe.get("diag_daily_tf_macd_ok", False).fillna(False)
            
            dataframe["daily_volume_spike"] = dataframe["daily_volume_spike"].fillna(False)
            dataframe["daily_macd_hist_up"] = dataframe["daily_macd_hist_up"].fillna(False)
            dataframe["daily_macd_hist_down"] = dataframe["daily_macd_hist_down"].fillna(False)
            dataframe["daily_macd_hist_slope_up"] = dataframe.get("daily_macd_hist_slope_up", False).fillna(False)
            dataframe["daily_macd_hist_slope_down"] = dataframe.get("daily_macd_hist_slope_down", False).fillna(False)
        
        else:
            # 如果没有日线数据，将所有条件设为False
            condition_cols = [
                "daily_elder_long", "daily_elder_short",
                "daily_freqtrade_long", "daily_freqtrade_short",
                "daily_tradingview_long", "daily_tradingview_short",
                "daily_quant_long", "daily_quant_short",
                "daily_trend_follow_long",
                "daily_timing_breakout_long", "daily_timing_breakout_short",
                "daily_timing_pullback_long", "daily_timing_pullback_short",
                "daily_timing_mr_long", "daily_timing_mr_short"
            ]
            for col in condition_cols:
                dataframe[col] = False

            dataframe["daily_adx"] = 0.0
            dataframe["daily_atr_pct"] = 0.0
            dataframe["daily_bb_width"] = 0.0
            dataframe["daily_bb_width_expand"] = False
            dataframe["daily_bb_squeeze_on"] = False
            dataframe["daily_volume_spike"] = False
            dataframe["daily_macd_hist_up"] = False
            dataframe["daily_macd_hist_down"] = False
            dataframe["daily_macd_hist_slope_up"] = False
            dataframe["daily_macd_hist_slope_down"] = False

            dataframe["diag_daily_tf_ema_fast"] = pd.NA
            dataframe["diag_daily_tf_ema_slow"] = pd.NA
            dataframe["diag_daily_tf_trend_ok"] = False
            dataframe["diag_daily_tf_pullback_touch"] = False
            dataframe["diag_daily_tf_reclaim"] = False
            dataframe["diag_daily_tf_adx_ok"] = False
            dataframe["diag_daily_tf_macd_ok"] = False

            dataframe["diag_daily_donchian_high"] = pd.NA
            dataframe["diag_daily_donchian_low"] = pd.NA
            dataframe["diag_daily_timing_ema_fast"] = pd.NA
            dataframe["diag_daily_timing_ema_slow"] = pd.NA
            dataframe["diag_daily_pivot_pp"] = pd.NA
            dataframe["diag_daily_pivot_r1"] = pd.NA
            dataframe["diag_daily_pivot_s1"] = pd.NA
            dataframe["diag_daily_bb_width_ma"] = pd.NA
            dataframe["diag_daily_vol_high"] = False
            dataframe["diag_daily_vote_breakout_long"] = 0
            dataframe["diag_daily_vote_breakout_short"] = 0
            dataframe["diag_daily_vote_pullback_long"] = 0
            dataframe["diag_daily_vote_pullback_short"] = 0
            dataframe["diag_daily_vote_mr_long"] = 0
            dataframe["diag_daily_vote_mr_short"] = 0

        daily_vol_thr = abs(self._get_env_float("FT_DAILY_VOL_ATR_PCT", 0.02))
        daily_vol_high = pd.to_numeric(dataframe.get("daily_atr_pct"), errors="coerce").fillna(0.0) >= float(daily_vol_thr)
        dataframe["diag_daily_vol_high"] = daily_vol_high

        regime_adx_thr = self._get_env_float("FT_REGIME_ADX_THRESHOLD", 25.0)
        regime_adx_series = pd.to_numeric(dataframe.get("daily_adx"), errors="coerce").fillna(0.0)
        dataframe["regime_trend"] = regime_adx_series >= float(regime_adx_thr)

        btc_weekly_dir = pd.to_numeric(dataframe.get("btc_weekly_dir"), errors="coerce").fillna(0).astype("int64")
        btc_weekly_trend_strong = dataframe.get("btc_weekly_trend_strong", False).fillna(False)

        playbook_long = pd.Series(self.PB_MEAN_REVERSION, index=dataframe.index, dtype="int64")
        playbook_short = pd.Series(self.PB_MEAN_REVERSION, index=dataframe.index, dtype="int64")

        regime_trend = dataframe.get("regime_trend", False).fillna(False)
        long_trend_mask = regime_trend & (btc_weekly_dir > 0)
        short_trend_mask = regime_trend & (btc_weekly_dir < 0)
        playbook_long.loc[long_trend_mask & daily_vol_high] = self.PB_TREND_BREAKOUT
        playbook_long.loc[long_trend_mask & ~daily_vol_high] = self.PB_TREND_PULLBACK
        playbook_long.loc[btc_weekly_trend_strong & (btc_weekly_dir < 0)] = self.PB_NO_TRADE

        playbook_short.loc[short_trend_mask & daily_vol_high] = self.PB_TREND_BREAKOUT
        playbook_short.loc[short_trend_mask & ~daily_vol_high] = self.PB_TREND_PULLBACK
        playbook_short.loc[btc_weekly_trend_strong & (btc_weekly_dir > 0)] = self.PB_NO_TRADE

        dataframe["playbook_long"] = playbook_long
        dataframe["playbook_short"] = playbook_short

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["donchian_upper"] = dataframe["high"].rolling(self.donchian_period.value).max()
        dataframe["donchian_lower"] = dataframe["low"].rolling(self.donchian_period.value).min()

        # 黑天鹅保护：基于 BTC/USDT 日线
        btc_daily_data = None
        try:
            btc_daily_data = self.dp.get_pair_dataframe(btc_pair, '1d')
        except Exception:
            btc_daily_data = None
        if btc_daily_data is None or btc_daily_data.empty:
            alt = 'BTC/USDT' if ':' in btc_pair else 'BTC/USDT:USDT'
            try:
                btc_daily_data = self.dp.get_pair_dataframe(alt, '1d')
            except Exception:
                btc_daily_data = None
        if btc_daily_data is not None and not btc_daily_data.empty:
            btc_daily_data["daily_drop"] = btc_daily_data["close"].pct_change()
            btc_daily_data["black_swan"] = btc_daily_data["daily_drop"] < -self.black_swan_drop_pct.value / 100
            try:
                dataframe = merge_informative_pair(dataframe, btc_daily_data[["date", "black_swan"]], self.timeframe, "1d", ffill=True)
                dataframe.rename(columns={"black_swan_1d": "daily_black_swan"}, inplace=True)
            except Exception as e:
                logging.getLogger(__name__).warning("Black swan merge failed: %s", e)
                dataframe["daily_black_swan"] = False
        else:
            dataframe["daily_black_swan"] = False

        btc_weekly_up = dataframe.get("btc_weekly_trend_up", False).fillna(False)
        daily_black_swan = dataframe.get("daily_black_swan", False).fillna(False)

        screen1_disable = int(os.environ.get("FT_DISABLE_SCREEN1", "0") or "0") != 0
        weekly_ok = pd.Series(True, index=dataframe.index) if screen1_disable else btc_weekly_up
        screen1_mask = weekly_ok & ~daily_black_swan
        dataframe["diag_stat_rows"] = int(len(dataframe))
        dataframe["diag_stat_screen1_n"] = int(screen1_mask.sum())

        runmode = None
        try:
            runmode = getattr(self.dp, "runmode", None) if getattr(self, "dp", None) is not None else None
        except Exception:
            runmode = None
        if runmode is None:
            runmode = self.config.get('runmode', RunMode.LIVE)

        is_backtest = False
        try:
            if isinstance(runmode, RunMode):
                is_backtest = runmode in (RunMode.BACKTEST, RunMode.HYPEROPT, RunMode.EDGE)
            else:
                flag = getattr(runmode, "is_backtest", None)
                if callable(flag):
                    is_backtest = bool(flag())
                elif flag is not None:
                    is_backtest = bool(flag)
        except Exception:
            is_backtest = False

        if is_backtest:
            current_time = dataframe["date"].iloc[-1] if "date" in dataframe.columns else datetime.utcnow()
        else:
            current_time = datetime.utcnow()

        current_ts = pd.to_datetime(current_time, utc=True, errors="coerce")

        if not is_backtest:
            if "date_1d" in dataframe.columns:
                last_date = dataframe["date_1d"].iloc[-1]
                last_ts = pd.to_datetime(last_date, utc=True, errors="coerce")
                if pd.notna(current_ts) and pd.notna(last_ts) and (current_ts - last_ts).total_seconds() > 86400 * 2:
                    dataframe["daily_elder_long"] = False
                    dataframe["daily_elder_short"] = False
                    dataframe["daily_freqtrade_long"] = False
                    dataframe["daily_freqtrade_short"] = False
                    dataframe["daily_tradingview_long"] = False
                    dataframe["daily_tradingview_short"] = False
                    dataframe["daily_quant_long"] = False
                    dataframe["daily_quant_short"] = False
                    dataframe["daily_trend_follow_long"] = False
                    dataframe["daily_volume_spike"] = False
                    dataframe["daily_macd_hist_up"] = False
                    dataframe["daily_macd_hist_down"] = False
                    dataframe["daily_macd_hist_slope_up"] = False
                    dataframe["daily_macd_hist_slope_down"] = False

            if "date_1w" in dataframe.columns:
                last_date = dataframe["date_1w"].iloc[-1]
                last_ts = pd.to_datetime(last_date, utc=True, errors="coerce")
                if pd.notna(current_ts) and pd.notna(last_ts) and (current_ts - last_ts).total_seconds() > 86400 * 7:
                    dataframe["btc_weekly_trend_up"] = False

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = None

        screen1_disable = int(os.environ.get("FT_DISABLE_SCREEN1", "0") or "0") != 0
        if screen1_disable:
            btc_weekly_up = pd.Series(True, index=dataframe.index)
            btc_weekly_down = pd.Series(False, index=dataframe.index)
            btc_weekly_trend_strong = pd.Series(False, index=dataframe.index)
            btc_weekly_dir = pd.Series(0, index=dataframe.index, dtype="int64")
        else:
            btc_weekly_up = dataframe.get("btc_weekly_trend_up", False).fillna(False)
            btc_weekly_down = dataframe.get("btc_weekly_trend_down", False).fillna(False)
            btc_weekly_trend_strong = dataframe.get("btc_weekly_trend_strong", False).fillna(False)
            btc_weekly_dir = pd.to_numeric(dataframe.get("btc_weekly_dir"), errors="coerce").fillna(0).astype("int64")
        daily_black_swan = dataframe.get("daily_black_swan", False).fillna(False)

        # 第二屏四组组合（多空分开）
        daily_elder_long = dataframe.get("daily_elder_long", False).fillna(False)
        daily_elder_short = dataframe.get("daily_elder_short", False).fillna(False)
        daily_freqtrade_long = dataframe.get("daily_freqtrade_long", False).fillna(False)
        daily_freqtrade_short = dataframe.get("daily_freqtrade_short", False).fillna(False)
        daily_tradingview_long = dataframe.get("daily_tradingview_long", False).fillna(False)
        daily_tradingview_short = dataframe.get("daily_tradingview_short", False).fillna(False)
        daily_quant_long = dataframe.get("daily_quant_long", False).fillna(False)
        daily_quant_short = dataframe.get("daily_quant_short", False).fillna(False)
        daily_trend_follow_long = dataframe.get("daily_trend_follow_long", False).fillna(False)
        daily_timing_breakout_long = dataframe.get("daily_timing_breakout_long", False).fillna(False)
        daily_timing_breakout_short = dataframe.get("daily_timing_breakout_short", False).fillna(False)
        daily_timing_pullback_long = dataframe.get("daily_timing_pullback_long", False).fillna(False)
        daily_timing_pullback_short = dataframe.get("daily_timing_pullback_short", False).fillna(False)
        daily_timing_mr_long = dataframe.get("daily_timing_mr_long", False).fillna(False)
        daily_timing_mr_short = dataframe.get("daily_timing_mr_short", False).fillna(False)
        daily_volume_spike = dataframe.get("daily_volume_spike", False).fillna(False)
        daily_macd_hist_up = dataframe.get("daily_macd_hist_up", False).fillna(False)
        daily_macd_hist_down = dataframe.get("daily_macd_hist_down", False).fillna(False)
        daily_macd_hist_slope_down = dataframe.get("daily_macd_hist_slope_down", False).fillna(False)

        disable_daily_filter_groups = int(os.environ.get("FT_DISABLE_DAILY_FILTER_GROUPS", "1") or "1") != 0
        if disable_daily_filter_groups:
            daily_elder_long = pd.Series(False, index=dataframe.index)
            daily_elder_short = pd.Series(False, index=dataframe.index)
            daily_freqtrade_long = pd.Series(False, index=dataframe.index)
            daily_freqtrade_short = pd.Series(False, index=dataframe.index)
            daily_tradingview_long = pd.Series(False, index=dataframe.index)
            daily_tradingview_short = pd.Series(False, index=dataframe.index)
            daily_quant_long = pd.Series(False, index=dataframe.index)
            daily_quant_short = pd.Series(False, index=dataframe.index)

        daily_reversion_long_condition = (
            daily_elder_long
            | daily_freqtrade_long
            | daily_tradingview_long
            | daily_quant_long
        )

        short_condition = (
            daily_elder_short
            | daily_freqtrade_short
            | daily_tradingview_short
            | daily_quant_short
        )

        if disable_daily_filter_groups:
            daily_reversion_long_condition = pd.Series(False, index=dataframe.index)
            short_condition = pd.Series(False, index=dataframe.index)
            daily_long_votes = pd.Series(0, index=dataframe.index, dtype="int64")
            daily_short_votes = pd.Series(0, index=dataframe.index, dtype="int64")
            osc_long_daily_ok = pd.Series(True, index=dataframe.index)
            osc_short_daily_ok = pd.Series(True, index=dataframe.index)
            short_daily_ok = pd.Series(True, index=dataframe.index)
        else:
            osc_daily_min_votes = int(os.environ.get("FT_OSC_DAILY_MIN_VOTES", "1") or "1")
            osc_daily_min_votes = max(0, osc_daily_min_votes)
            daily_long_votes = (
                daily_elder_long.astype(int)
                + daily_freqtrade_long.astype(int)
                + daily_tradingview_long.astype(int)
                + daily_quant_long.astype(int)
            )
            daily_short_votes = (
                daily_elder_short.astype(int)
                + daily_freqtrade_short.astype(int)
                + daily_tradingview_short.astype(int)
                + daily_quant_short.astype(int)
            )
            osc_long_daily_ok = daily_long_votes >= osc_daily_min_votes
            osc_short_daily_ok = daily_short_votes >= osc_daily_min_votes

            short_strict_level = int(os.environ.get("FT_SHORT_STRICT_LEVEL", "1") or "1")
            short_strict_level = max(0, short_strict_level)
            short_daily_ok = pd.Series(True, index=dataframe.index)
            if short_strict_level > 0:
                short_daily_ok = daily_short_votes >= short_strict_level
                osc_short_daily_ok = osc_short_daily_ok & short_daily_ok

        osc_short_weekly_gate = int(os.environ.get("FT_OSC_SHORT_REQUIRE_BTC_WEEKLY_NOT_UP", "0") or "0") != 0
        if osc_short_weekly_gate:
            osc_short_weekly_ok = ~btc_weekly_up
        else:
            osc_short_weekly_ok = pd.Series(True, index=dataframe.index)

        pb_long = pd.to_numeric(dataframe.get("playbook_long"), errors="coerce").fillna(self.PB_MEAN_REVERSION).astype("int64")
        pb_short = pd.to_numeric(dataframe.get("playbook_short"), errors="coerce").fillna(self.PB_MEAN_REVERSION).astype("int64")

        enable_mr = int(os.environ.get("FT_ENABLE_OSC_ENTRIES", "1") or "1") != 0

        breakout_long_edge = daily_timing_breakout_long & (~daily_timing_breakout_long.shift(1).fillna(False))
        pullback_long_edge = daily_timing_pullback_long & (~daily_timing_pullback_long.shift(1).fillna(False))
        mr_long_edge = daily_timing_mr_long & (~daily_timing_mr_long.shift(1).fillna(False))

        setup_breakout_long = breakout_long_edge
        setup_pullback_long = pullback_long_edge
        setup_mr_long = mr_long_edge & osc_long_daily_ok

        long_ok = (pb_long != self.PB_NO_TRADE)
        long_breakout = long_ok & (pb_long == self.PB_TREND_BREAKOUT) & setup_breakout_long
        long_pullback = long_ok & (pb_long == self.PB_TREND_PULLBACK) & setup_pullback_long
        long_mr = long_ok & (pb_long == self.PB_MEAN_REVERSION) & setup_mr_long
        if not enable_mr:
            long_mr = pd.Series(False, index=dataframe.index)

        breakout_short_edge = daily_timing_breakout_short & (~daily_timing_breakout_short.shift(1).fillna(False))
        pullback_short_edge = daily_timing_pullback_short & (~daily_timing_pullback_short.shift(1).fillna(False))
        mr_short_edge = daily_timing_mr_short & (~daily_timing_mr_short.shift(1).fillna(False))

        setup_breakout_short = breakout_short_edge & short_daily_ok
        setup_pullback_short = pullback_short_edge & short_daily_ok
        setup_mr_short = mr_short_edge & osc_short_daily_ok & short_daily_ok

        short_ok = (pb_short != self.PB_NO_TRADE) & osc_short_weekly_ok
        short_breakout = short_ok & (pb_short == self.PB_TREND_BREAKOUT) & setup_breakout_short
        short_pullback = short_ok & (pb_short == self.PB_TREND_PULLBACK) & setup_pullback_short
        short_mr = short_ok & (pb_short == self.PB_MEAN_REVERSION) & setup_mr_short
        if not enable_mr:
            short_mr = pd.Series(False, index=dataframe.index)

        enter_long_pre = (long_breakout | long_pullback | long_mr) & (~daily_black_swan)
        enter_short_pre = (short_breakout | short_pullback | short_mr) & (~daily_black_swan)

        regime_enable = int(os.environ.get("FT_REGIME_FILTER", "1") or "1") != 0
        regime_trend = dataframe.get("regime_trend", False).fillna(False)
        regime_trend_eff = regime_trend & (btc_weekly_dir != 0)
        if regime_enable:
            enter_long_pre = enter_long_pre & ((pb_long == self.PB_MEAN_REVERSION) | regime_trend_eff)
            enter_long_pre = enter_long_pre & (~((pb_long == self.PB_MEAN_REVERSION) & regime_trend_eff))

            enter_short_pre = enter_short_pre & ((pb_short == self.PB_MEAN_REVERSION) | regime_trend_eff)
            enter_short_pre = enter_short_pre & (~((pb_short == self.PB_MEAN_REVERSION) & regime_trend_eff))

        enter_long = enter_long_pre
        enter_short = enter_short_pre

        daily_timing_long = long_ok & (
            (pb_long == self.PB_TREND_BREAKOUT) & setup_breakout_long
            | (pb_long == self.PB_TREND_PULLBACK) & setup_pullback_long
            | (pb_long == self.PB_MEAN_REVERSION) & setup_mr_long
        )
        micro_long = daily_timing_long

        daily_timing_short = short_ok & (
            (pb_short == self.PB_TREND_BREAKOUT) & setup_breakout_short
            | (pb_short == self.PB_TREND_PULLBACK) & setup_pullback_short
            | (pb_short == self.PB_MEAN_REVERSION) & setup_mr_short
        )
        micro_short = daily_timing_short

        diag_cols = {
            "diag_entry_weekly_up": btc_weekly_up,
            "diag_entry_weekly_down": btc_weekly_down,
            "diag_entry_weekly_trend_strong": btc_weekly_trend_strong,
            "diag_entry_weekly_dir": btc_weekly_dir,
            "diag_entry_playbook_long": pb_long,
            "diag_entry_playbook_short": pb_short,
            "diag_entry_black_swan": daily_black_swan,
            "diag_entry_daily_reversion_long": daily_reversion_long_condition,
            "diag_entry_daily_trend_follow_long": daily_trend_follow_long,
            "diag_entry_daily_timing_breakout_long": daily_timing_breakout_long,
            "diag_entry_daily_timing_pullback_long": daily_timing_pullback_long,
            "diag_entry_daily_timing_mr_long": daily_timing_mr_long,
            "diag_entry_daily_long_votes": daily_long_votes,
            "diag_entry_osc_long_daily_ok": osc_long_daily_ok,
            "diag_entry_daily_timing_long": daily_timing_long,
            "diag_entry_micro_long": micro_long,
            "diag_entry_daily_any_short": short_condition,
            "diag_entry_daily_timing_breakout_short": daily_timing_breakout_short,
            "diag_entry_daily_timing_pullback_short": daily_timing_pullback_short,
            "diag_entry_daily_timing_mr_short": daily_timing_mr_short,
            "diag_entry_daily_short_votes": daily_short_votes,
            "diag_entry_short_daily_ok": short_daily_ok,
            "diag_entry_osc_short_daily_ok": osc_short_daily_ok,
            "diag_entry_osc_short_weekly_ok": osc_short_weekly_ok,
            "diag_entry_daily_timing_short": daily_timing_short,
            "diag_entry_micro_short": micro_short,
            "diag_entry_regime_enable": bool(regime_enable),
            "diag_entry_regime_trend": regime_trend,
            "diag_entry_enter_long_pre": enter_long_pre,
            "diag_entry_enter_short_pre": enter_short_pre,
        }

        conflict = enter_long & enter_short
        enter_long = enter_long & ~conflict
        enter_short = enter_short & ~conflict

        diag_cols.update({
            "diag_entry_conflict": conflict,
            "diag_entry_enter_long_final": enter_long,
            "diag_entry_enter_short_final": enter_short,
        })

        screen1_mask_long = long_ok & ~daily_black_swan
        screen1_mask_short = short_ok & ~daily_black_swan
        screen1_n = int((screen1_mask_long | screen1_mask_short).sum())
        stats_cols = {
            "diag_stat_rows": int(len(dataframe)),
            "diag_stat_screen1_n": screen1_n,
            "diag_stat_long_playbook_breakout_n": int(((pb_long == self.PB_TREND_BREAKOUT) & screen1_mask_long).sum()),
            "diag_stat_long_playbook_pullback_n": int(((pb_long == self.PB_TREND_PULLBACK) & screen1_mask_long).sum()),
            "diag_stat_long_playbook_mr_n": int(((pb_long == self.PB_MEAN_REVERSION) & screen1_mask_long).sum()),
            "diag_stat_long_timing_n": int((daily_timing_long & screen1_mask_long).sum()),
            "diag_stat_long_micro_n": int((micro_long & screen1_mask_long).sum()),
            "diag_stat_long_block_timing_n": int((screen1_mask_long & ~daily_timing_long).sum()),
            "diag_stat_long_block_micro_n": int(((screen1_mask_long & daily_timing_long) & ~micro_long).sum()),
            "diag_stat_short_playbook_breakout_n": int(((pb_short == self.PB_TREND_BREAKOUT) & screen1_mask_short).sum()),
            "diag_stat_short_playbook_pullback_n": int(((pb_short == self.PB_TREND_PULLBACK) & screen1_mask_short).sum()),
            "diag_stat_short_playbook_mr_n": int(((pb_short == self.PB_MEAN_REVERSION) & screen1_mask_short).sum()),
            "diag_stat_short_timing_n": int((daily_timing_short & screen1_mask_short).sum()),
            "diag_stat_short_micro_n": int((micro_short & screen1_mask_short).sum()),
            "diag_stat_short_block_timing_n": int((screen1_mask_short & ~daily_timing_short).sum()),
            "diag_stat_short_block_micro_n": int(((screen1_mask_short & daily_timing_short) & ~micro_short).sum()),
        }

        dataframe = dataframe.assign(**diag_cols)
        dataframe = dataframe.assign(**stats_cols)

        dataframe.loc[enter_long, "enter_long"] = 1
        dataframe.loc[enter_short, "enter_short"] = 1

        dataframe.loc[enter_long, "enter_tag"] = pd.Series(
            pd.NA, index=dataframe.index, dtype="object"
        )
        dataframe.loc[enter_short, "enter_tag"] = pd.Series(
            pd.NA, index=dataframe.index, dtype="object"
        )

        dataframe.loc[long_breakout & enter_long, "enter_tag"] = "trend_breakout_long"
        dataframe.loc[long_pullback & enter_long, "enter_tag"] = "trend_pullback_long"
        dataframe.loc[long_mr & enter_long, "enter_tag"] = "osc_long"
        dataframe.loc[short_breakout & enter_short, "enter_tag"] = "trend_breakout_short"
        dataframe.loc[short_pullback & enter_short, "enter_tag"] = "trend_pullback_short"
        dataframe.loc[short_mr & enter_short, "enter_tag"] = "osc_short"

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        # 简单退出：突破反向
        dataframe.loc[dataframe["close"] < dataframe["donchian_lower"].shift(1), "exit_long"] = 1
        dataframe.loc[dataframe["close"] > dataframe["donchian_upper"].shift(1), "exit_short"] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < 3:
            return self.stoploss

        last_candle = dataframe.iloc[-1]
        atr = last_candle.get("atr", 0) or 0

        if trade.is_short:
            stop_price = float(dataframe['high'].iloc[-2]) + float(atr) * 1.5
            stoploss_pct = (float(current_rate) - float(stop_price)) / float(current_rate)
        else:
            stop_price = float(dataframe['low'].iloc[-2]) - float(atr) * 1.5
            stoploss_pct = (float(stop_price) - float(current_rate)) / float(current_rate)

        if pd.isna(stoploss_pct) or pd.isnull(stoploss_pct):
            return -0.10

        stoploss_pct = float(stoploss_pct)

        stoploss_pct = max(-0.10, min(-0.0001, stoploss_pct))
        return float(stoploss_pct)

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs):
        open_dt = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if open_dt is None:
            return None

        try:
            age_h = (current_time - open_dt).total_seconds() / 3600.0
        except Exception:
            return None

        osc_mfe_trigger = self._get_env_float("FT_OSC_MFE_TRIGGER", 0.0)
        osc_retrace_frac = self._get_env_float("FT_OSC_RETRACE_FRAC", 0.0)
        osc_exit_min_profit = self._get_env_float("FT_OSC_EXIT_MIN_PROFIT", 0.0)
        osc_min_age_h = self._get_env_float("FT_OSC_MIN_AGE_HOURS", 0.0)
        osc_max_age_h = self._get_env_float("FT_OSC_MAX_AGE_HOURS", 0.0)
        if osc_mfe_trigger > 0 and osc_retrace_frac > 0:
            tag = getattr(trade, "enter_tag", None)
            if tag in ("osc_long", "osc_short"):
                if age_h >= osc_min_age_h and (osc_max_age_h <= 0 or age_h <= osc_max_age_h):
                    open_rate = float(getattr(trade, "open_rate", 0.0) or 0.0)
                    if open_rate > 0:
                        max_rate = float(getattr(trade, "max_rate", 0.0) or 0.0)
                        min_rate = float(getattr(trade, "min_rate", 0.0) or 0.0)
                        if trade.is_short:
                            mfe = (open_rate - min_rate) / open_rate if min_rate > 0 else 0.0
                        else:
                            mfe = (max_rate - open_rate) / open_rate if max_rate > 0 else 0.0

                        retrace_level = float(mfe) * float(osc_retrace_frac)
                        if float(mfe) >= float(osc_mfe_trigger) and float(current_profit) <= float(retrace_level) and float(current_profit) >= float(osc_exit_min_profit):
                            return "osc_retrace_exit"
        return None

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> Tuple[bool, Optional[str]]:
        cooldown_h = self._get_env_float("FT_OSC_COOLDOWN_HOURS", 0.0)
        if cooldown_h > 0 and entry_tag in ("osc_long", "osc_short"):
            until = getattr(self, "_osc_cooldown_until", {}).get(pair)
            if until is not None:
                try:
                    if current_time < until:
                        return False, "osc_cooldown"
                except Exception:
                    pass
        return True, None

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float,
                           rate: float, time_in_force: str, exit_reason: str,
                           current_time: datetime, **kwargs) -> bool:
        block_exit_signal = int(os.environ.get("FT_OSC_BLOCK_EXIT_SIGNAL", "1") or "1") != 0
        if block_exit_signal and str(exit_reason) == "exit_signal":
            tag = getattr(trade, "enter_tag", None) or getattr(trade, "entry_tag", None)
            if tag in ("osc_long", "osc_short"):
                return False

        cooldown_h = self._get_env_float("FT_OSC_COOLDOWN_HOURS", 0.0)
        if cooldown_h > 0 and str(exit_reason) == "osc_retrace_exit":
            if not hasattr(self, "_osc_cooldown_until") or getattr(self, "_osc_cooldown_until") is None:
                self._osc_cooldown_until = {}
            try:
                self._osc_cooldown_until[pair] = current_time + timedelta(hours=float(cooldown_h))
            except Exception:
                pass
        return True

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                            proposed_stake: float, min_stake: float, max_stake: float,
                            entry_tag: Optional[str], side: str, **kwargs) -> float:
        stake = float(proposed_stake) * 0.5
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        if max_stake is not None:
            stake = min(stake, float(max_stake))
        return stake

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "enter_long": {"color": "green", "type": "scatter", "marker": {"symbol": "triangle-up", "size": 12}},
                "enter_short": {"color": "red", "type": "scatter", "marker": {"symbol": "triangle-down", "size": 12}},
                "donchian_upper": {"color": "blue"},
                "donchian_lower": {"color": "blue"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "orange"}},
                "MACD": {"macd": {"color": "blue"}, "macdsignal": {"color": "red"}},
                "ADX": {"adx": {"color": "purple"}},
            }
        }
