# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
from pandas import DataFrame
import pandas as pd
from typing import Optional
from datetime import datetime
import logging

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade
from freqtrade.enums import RunMode
import talib.abstract as ta

class ShortTGEStrategy(IStrategy):
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
    trailing_stop = True
    trailing_stop_positive = 0.015
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    process_only_new_candles = True
    use_exit_signal = True
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 200

    # 参数
    rsi_buy = IntParameter(25, 40, default=35, space="buy")
    rsi_sell = IntParameter(60, 75, default=68, space="sell")
    adx_threshold = IntParameter(20, 40, default=26, space="buy")
    donchian_period = IntParameter(10, 30, default=16, space="buy")
    osc_vote_threshold = IntParameter(2, 3, default=2, space="buy")
    volume_multiplier = DecimalParameter(1.2, 2.0, default=1.577, space="buy")
    black_swan_drop_pct = DecimalParameter(3.0, 8.0, default=4.355, space="buy")  # 黑天鹅跌幅

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
            base = base.dropna(subset=["date"]).set_index("date", drop=False).sort_index()
            btc_weekly = base.resample("1W").agg({
                "date": "last",
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna(subset=["close"]).reset_index(drop=True)

            if not btc_weekly.empty and len(btc_weekly) > 35:
                macd_res = ta.MACD(btc_weekly)
                if isinstance(macd_res, pd.DataFrame):
                    macdhist = macd_res.get("macdhist")
                elif isinstance(macd_res, dict):
                    macdhist = macd_res.get("macdhist")
                else:
                    _, _, macdhist = macd_res

                btc_weekly["macd_hist"] = pd.to_numeric(macdhist, errors="coerce")
                btc_weekly = btc_weekly.loc[btc_weekly["macd_hist"].notna()].copy()
                btc_weekly["macd_hist_up"] = (btc_weekly["macd_hist"] > 0) & (
                    btc_weekly["macd_hist"] > btc_weekly["macd_hist"].shift(1)
                )
                btc_weekly["adx"] = ta.ADX(btc_weekly)
                btc_weekly["trend_up"] = (
                    btc_weekly["macd_hist_up"] & (btc_weekly["adx"] > self.adx_threshold.value)
                )

                btc_weekly[["trend_up"]] = btc_weekly[["trend_up"]].shift(1)
                dataframe = merge_informative_pair(
                    dataframe, btc_weekly[["date", "trend_up"]], self.timeframe, "1w", ffill=True
                )
                dataframe.rename(columns={"trend_up_1w": "btc_weekly_trend_up"}, inplace=True)
            else:
                dataframe["btc_weekly_trend_up"] = True
        else:
            dataframe["btc_weekly_trend_up"] = True

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
                pair_daily = pair_daily.loc[pair_daily["close"].notna()]

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
            
            # MACD相关
            macd_res = ta.MACD(pair_daily)
            if isinstance(macd_res, pd.DataFrame):
                macdhist = macd_res.get("macdhist")
            elif isinstance(macd_res, dict):
                macdhist = macd_res.get("macdhist")
            else:
                _, _, macdhist = macd_res

            pair_daily["macdhist"] = pd.to_numeric(macdhist, errors="coerce")
            pair_daily = pair_daily.loc[pair_daily["macdhist"].notna()]
            pair_daily["macd_hist_up"] = (pair_daily["macdhist"] > 0) & (pair_daily["macdhist"] > pair_daily["macdhist"].shift(1))
            pair_daily["macd_hist_down"] = (pair_daily["macdhist"] < 0) & (pair_daily["macdhist"] < pair_daily["macdhist"].shift(1))
            pair_daily["macd_hist_slope_up"] = pair_daily["macdhist"] > pair_daily["macdhist"].shift(1)
            pair_daily["macd_hist_slope_down"] = pair_daily["macdhist"] < pair_daily["macdhist"].shift(1)
            
            # 成交量
            pair_daily["volume_ma"] = pair_daily["volume"].rolling(20).mean()
            pair_daily["volume_spike"] = pair_daily["volume"] > pair_daily["volume_ma"] * self.volume_multiplier.value
            
            # ====================
            # 第一组：Elder 原版（多空分开）
            # ====================
            # Force Index (13日EMA版)
            pair_daily["raw_force"] = (pair_daily["close"] - pair_daily["close"].shift(1)) * pair_daily["volume"]
            pair_daily["force_index"] = ta.EMA(pair_daily["raw_force"], timeperiod=13)
            
            # 多头：看涨背离
            lookback_period = 20
            pair_daily["price_new_low"] = (
                pair_daily["close"] < pair_daily["close"].rolling(lookback_period).min().shift(1)
            )
            pair_daily["force_higher_low"] = (
                pair_daily["force_index"] > pair_daily["force_index"].rolling(lookback_period).min().shift(1)
            )
            pair_daily["force_double_bottom"] = (
                (pair_daily["force_index"] > pair_daily["force_index"].shift(1)) &
                (pair_daily["force_index"].shift(1) < pair_daily["force_index"].shift(2))
            )
            
            pair_daily["elder_condition_long"] = (
                (pair_daily["rsi"] < 30) &  # RSI超卖
                pair_daily["price_new_low"] &  # 价格创新低
                (pair_daily["force_higher_low"] | pair_daily["force_double_bottom"])  # Force Index背离
            )
            
            # 空头：看跌背离
            pair_daily["price_new_high"] = (
                pair_daily["close"] > pair_daily["close"].rolling(lookback_period).max().shift(1)
            )
            pair_daily["force_lower_high"] = (
                pair_daily["force_index"] < pair_daily["force_index"].rolling(lookback_period).max().shift(1)
            )
            pair_daily["force_double_top"] = (
                (pair_daily["force_index"] < pair_daily["force_index"].shift(1)) &
                (pair_daily["force_index"].shift(1) > pair_daily["force_index"].shift(2))
            )
            
            pair_daily["elder_condition_short"] = (
                (pair_daily["rsi"] > 70) &  # RSI超买
                pair_daily["price_new_high"] &  # 价格创新高
                (pair_daily["force_lower_high"] | pair_daily["force_double_top"])  # Force Index背离
            )
            
            # ====================
            # 第二组：Freqtrade 社区热门（多空分开）
            # ====================
            # 多头
            pair_daily["rsi_oversold"] = pair_daily["rsi"] < self.rsi_buy.value
            pair_daily["stoch_oversold"] = pair_daily["stoch_k"] < 20
            pair_daily["cci_oversold"] = pair_daily["cci"] < -100
            
            pair_daily["freqtrade_vote_long"] = (
                pair_daily["rsi_oversold"].astype(int) +
                pair_daily["stoch_oversold"].astype(int) +
                pair_daily["cci_oversold"].astype(int)
            )
            pair_daily["freqtrade_condition_long"] = pair_daily["freqtrade_vote_long"] >= 2
            
            # 空头
            pair_daily["rsi_overbought"] = pair_daily["rsi"] > self.rsi_sell.value
            pair_daily["stoch_overbought"] = pair_daily["stoch_k"] > 80
            pair_daily["cci_overbought"] = pair_daily["cci"] > 100
            
            pair_daily["freqtrade_vote_short"] = (
                pair_daily["rsi_overbought"].astype(int) +
                pair_daily["stoch_overbought"].astype(int) +
                pair_daily["cci_overbought"].astype(int)
            )
            pair_daily["freqtrade_condition_short"] = pair_daily["freqtrade_vote_short"] >= 2
            
            # ====================
            # 第三组：TradingView Pine Script 经典（多空分开）
            # ====================
            # 多头
            pair_daily["price_near_ema"] = (
                (pair_daily["close"] < pair_daily["ema13"] * 1.02) & 
                (pair_daily["close"] > pair_daily["ema13"] * 0.98)
            )
            pair_daily["tradingview_condition_long"] = (
                (pair_daily["rsi"] < 35) &  # RSI超卖
                pair_daily["macd_hist_up"] &  # MACD柱状图向上
                pair_daily["price_near_ema"]  # 价格回调到EMA13附近
            )
            
            # 空头
            pair_daily["tradingview_condition_short"] = (
                (pair_daily["rsi"] > 65) &  # RSI超买
                pair_daily["macd_hist_down"] &  # MACD柱状图向下
                pair_daily["price_near_ema"]  # 价格反弹到EMA13附近
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
            pair_daily["quant_condition_long"] = (
                (pair_daily["qf_oscillator_vote_long"] >= 2) &
                pair_daily["mean_reversion_long"]
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
            pair_daily["quant_condition_short"] = (
                (pair_daily["qf_oscillator_vote_short"] >= 2) &
                pair_daily["mean_reversion_short"]
            )
            
            # 合并所有条件到主时间框架
            dataframe = merge_informative_pair(
                dataframe, 
                pair_daily[[
                    "date", 
                    "elder_condition_long", "elder_condition_short",
                    "freqtrade_condition_long", "freqtrade_condition_short",
                    "tradingview_condition_long", "tradingview_condition_short",
                    "quant_condition_long", "quant_condition_short",
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
                "volume_spike_1d": "daily_volume_spike",
                "macd_hist_up_1d": "daily_macd_hist_up",
                "macd_hist_down_1d": "daily_macd_hist_down",
                "macd_hist_slope_up_1d": "daily_macd_hist_slope_up",
                "macd_hist_slope_down_1d": "daily_macd_hist_slope_down"
            }, inplace=True)
            
            # NaN处理
            condition_cols = [
                "daily_elder_long", "daily_elder_short",
                "daily_freqtrade_long", "daily_freqtrade_short",
                "daily_tradingview_long", "daily_tradingview_short",
                "daily_quant_long", "daily_quant_short"
            ]
            for col in condition_cols:
                dataframe[col] = dataframe[col].fillna(False)
            
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
                "daily_quant_long", "daily_quant_short"
            ]
            for col in condition_cols:
                dataframe[col] = False
            
            dataframe["daily_volume_spike"] = False
            dataframe["daily_macd_hist_up"] = False
            dataframe["daily_macd_hist_down"] = False
            dataframe["daily_macd_hist_slope_up"] = False
            dataframe["daily_macd_hist_slope_down"] = False

        # 3. 第三屏：1h 指标（放宽：满足任一条件）
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)

        # Donchian 通道
        dataframe["donchian_upper"] = dataframe["high"].rolling(self.donchian_period.value).max()
        dataframe["donchian_lower"] = dataframe["low"].rolling(self.donchian_period.value).min()

        # 1. 突破前一根 K 线高/低点
        dataframe["prev_high"] = dataframe["high"].shift(1)
        dataframe["prev_low"] = dataframe["low"].shift(1)
        breakout_prev_high = dataframe["close"] > dataframe["prev_high"]
        breakout_prev_low = dataframe["close"] < dataframe["prev_low"]

        # 2. 突破 Donchian 通道
        breakout_donchian_long = dataframe["close"] > dataframe["donchian_upper"].shift(1)
        breakout_donchian_short = dataframe["close"] < dataframe["donchian_lower"].shift(1)

        # 3. 锤头/倒锤头/吞没 K 线形态（向量化）
        body = (dataframe["close"] - dataframe["open"]).abs()
        total_range = dataframe["high"] - dataframe["low"]
        lower_shadow = dataframe[["open", "close"]].min(axis=1) - dataframe["low"]
        upper_shadow = dataframe["high"] - dataframe[["open", "close"]].max(axis=1)

        total_range_safe = total_range.replace(0, 1e-10)

        hammer = (
            (lower_shadow > 2 * body) &
            (upper_shadow < body * 0.3) &
            (total_range > 0) &
            (lower_shadow > total_range_safe * 0.6)
        )

        shooting_star = (
            (upper_shadow > 2 * body) &
            (lower_shadow < body * 0.3) &
            (total_range > 0) &
            (upper_shadow > total_range_safe * 0.6)
        )

        engulfing_bull = (
            (dataframe["close"] > dataframe["open"]) &
            (dataframe["close"].shift(1) < dataframe["open"].shift(1)) &
            (dataframe["open"] < dataframe["close"].shift(1)) &
            (dataframe["close"] > dataframe["open"].shift(1))
        )
        engulfing_bear = (
            (dataframe["close"] < dataframe["open"]) &
            (dataframe["close"].shift(1) > dataframe["open"].shift(1)) &
            (dataframe["open"] > dataframe["close"].shift(1)) &
            (dataframe["close"] < dataframe["open"].shift(1))
        )

        candle_confirm_long = hammer | engulfing_bull
        candle_confirm_short = shooting_star | engulfing_bear

        # 第三屏：满足任一条件即可
        third_long = breakout_prev_high | breakout_donchian_long | candle_confirm_long
        third_short = breakout_prev_low | breakout_donchian_short | candle_confirm_short

        dataframe["third_long"] = third_long
        dataframe["third_short"] = third_short

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

        runmode = None
        try:
            runmode = getattr(self.dp, "runmode", None) if getattr(self, "dp", None) is not None else None
        except Exception:
            runmode = None
        if runmode is None:
            runmode = self.config.get('runmode', RunMode.LIVE)

        is_backtest = False
        try:
            is_backtest = bool(getattr(runmode, "is_backtest", lambda: False)())
        except Exception:
            is_backtest = False

        if is_backtest:
            current_time = dataframe["date"].iloc[-1] if "date" in dataframe.columns else datetime.utcnow()
        else:
            current_time = datetime.utcnow()

        current_ts = pd.to_datetime(current_time, utc=True, errors="coerce")

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

        btc_weekly_up = dataframe.get("btc_weekly_trend_up", False).fillna(False)
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
        daily_volume_spike = dataframe.get("daily_volume_spike", False).fillna(False)
        daily_macd_hist_slope_down = dataframe.get("daily_macd_hist_slope_down", False).fillna(False)

        third_long = dataframe.get("third_long", False).fillna(False)
        third_short = dataframe.get("third_short", False).fillna(False)

        long_condition = (
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

        trend_long = (
            btc_weekly_up
            & long_condition
            & third_long
            & ~daily_black_swan
        )

        osc_long = (
            third_long
            & (dataframe["rsi"] <= (self.rsi_buy.value + 20))
            & ~daily_black_swan
        )

        short_filter = daily_volume_spike | daily_macd_hist_slope_down

        trend_short = (
            short_condition
            & third_short
            & short_filter
            & ~daily_black_swan
        )

        osc_short = (
            third_short
            & (dataframe["rsi"] >= (self.rsi_sell.value - 20))
            & ~daily_black_swan
        )

        enter_long = trend_long | osc_long
        enter_short = trend_short | osc_short

        conflict = enter_long & enter_short
        enter_long = enter_long & ~conflict
        enter_short = enter_short & ~conflict

        dataframe.loc[enter_long, "enter_long"] = 1
        dataframe.loc[enter_short, "enter_short"] = 1

        dataframe.loc[enter_long, "enter_tag"] = pd.Series(
            pd.NA, index=dataframe.index, dtype="object"
        )
        dataframe.loc[enter_short, "enter_tag"] = pd.Series(
            pd.NA, index=dataframe.index, dtype="object"
        )

        dataframe.loc[trend_long & enter_long, "enter_tag"] = "trend_long"
        dataframe.loc[osc_long & enter_long, "enter_tag"] = "osc_long"
        dataframe.loc[trend_short & enter_short, "enter_tag"] = "trend_short"
        dataframe.loc[osc_short & enter_short, "enter_tag"] = "osc_short"

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
        return stoploss_pct

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
