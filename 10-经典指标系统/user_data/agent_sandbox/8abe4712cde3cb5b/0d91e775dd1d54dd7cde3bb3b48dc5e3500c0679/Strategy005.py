# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
import numpy as np
import pandas as pd
from pandas import DataFrame
from typing import Optional, Dict, Any
import talib.abstract as ta
import os
import json
import requests
from urllib.parse import urlparse

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair, stoploss_from_open
from freqtrade.persistence import Trade


class Strategy005(IStrategy):
    """
    多经典策略自适应系统（5个经典策略并行，满足任意一个即可入场）
    - 高层：周线（趋势方向）
    - 中层：日线（中级确认）
    - 低层：1h（入场触发）
    - 5个独立经典策略，任一满足即入场
    """
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = True
    position_adjustment_enable = True

    minimal_roi = {
        "0": 0.20,
        "360": 0.12,
        "720": 0.08,
        "1440": 0.04,
        "2880": 0
    }

    stoploss = -0.15

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": False,
    }

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.05
    trailing_only_offset_is_reached = True

    process_only_new_candles = False
    use_exit_signal = True
    exit_profit_only = False
    exit_profit_offset = 0.0
    ignore_roi_if_entry_signal = True
    startup_candle_count: int = 500
    use_custom_stoploss = True

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self._ml_export_last_ts_by_pair: Dict[str, int] = {}
        self._ml_decision_last_ts_by_pair: Dict[str, int] = {}
        self._ml_export_ts_bounds_ms = None
        self._l12_last_reduce_ts_by_pair: Dict[str, int] = {}
        self._exit_l1_enabled = self._env_bool("EXIT_L1_ENABLED", False)
        self._exit_l2_enabled = self._env_bool("EXIT_L2_ENABLED", False)
        self._exit_l12_cooldown_sec = self._env_int("EXIT_L12_COOLDOWN_SEC", 6 * 3600)
        self._exit_l1_min_profit = self._env_float("EXIT_L1_MIN_PROFIT", 0.01)
        self._exit_l2_min_profit = self._env_float("EXIT_L2_MIN_PROFIT", 0.03)
        self._exit_l12_min_peak_profit = self._env_float("EXIT_L12_MIN_PEAK_PROFIT", 0.015)
        self._exit_l12_min_dd = self._env_float("EXIT_L12_MIN_DD", 0.25)
        self._exit_l1_risk_thr = self._env_float("EXIT_L1_RISK_THR", 0.55)
        self._exit_l2_risk_thr = self._env_float("EXIT_L2_RISK_THR", 0.75)
        self._exit_l1_reduce_frac = self._env_float("EXIT_L1_REDUCE_FRAC", 0.25)
        self._exit_l2_reduce_frac = self._env_float("EXIT_L2_REDUCE_FRAC", 0.50)
        default_shift_map = {
            "trend": 0.0,
            "chop": -0.05,
            "highvol": -0.03,
            "uptrend_strong": 0.03,
            "uptrend_reversal": -0.03,
            "downtrend_strong": 0.03,
            "downtrend_reversal": -0.03,
        }
        self._exit_l12_shift_map = self._env_json("EXIT_L12_SHIFT_MAP", default_shift_map)
        if not isinstance(self._exit_l12_shift_map, dict):
            self._exit_l12_shift_map = dict(default_shift_map)
        self._exit_highvol_atr_pct = self._env_float("EXIT_HIGHVOL_ATR_PCT", 0.035)

    def _env_bool(self, key: str, default: bool) -> bool:
        raw = str(os.environ.get(key, "") if key in os.environ else "").strip().lower()
        if raw in ("1", "true", "yes", "y", "on"):
            return True
        if raw in ("0", "false", "no", "n", "off"):
            return False
        return bool(default)

    def _env_int(self, key: str, default: int) -> int:
        raw = str(os.environ.get(key, "") if key in os.environ else "").strip()
        if not raw:
            return int(default)
        try:
            return int(float(raw))
        except Exception:
            return int(default)

    def _env_float(self, key: str, default: float) -> float:
        raw = str(os.environ.get(key, "") if key in os.environ else "").strip()
        if not raw:
            return float(default)
        try:
            v = float(raw)
            return float(v) if np.isfinite(v) else float(default)
        except Exception:
            return float(default)

    def _env_json(self, key: str, default):
        raw = str(os.environ.get(key, "") if key in os.environ else "").strip()
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    def _l12_thr_shift(self, row, regime_is_trend: bool, atr_pct: float) -> float:
        m = getattr(self, "_exit_l12_shift_map", None)
        if not isinstance(m, dict):
            m = {}
        try:
            highvol_thr = float(getattr(self, "_exit_highvol_atr_pct", 0.035) or 0.035)
        except Exception:
            highvol_thr = 0.035
        if float(atr_pct) >= float(highvol_thr):
            v = m.get("highvol")
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        trg = ""
        try:
            if hasattr(row, "get"):
                trg = str(row.get("time_regime", "") or "").strip().lower()
        except Exception:
            trg = ""
        if trg:
            v = m.get(trg)
            if v is not None:
                try:
                    return float(v)
                except Exception:
                    pass
        k = "trend" if bool(regime_is_trend) else "chop"
        v = m.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                return 0.0
        return 0.0

    # Buy parameters:
    # buy_params = {
    #     "bbw_ma_len": 67,
    #     "bbw_period": 40,
    #     "bbw_ratio_thr": 1.035,
    #     "btc_weekly_adx_threshold": 44,
    #     "btc_weekly_macd_slope_pct_thr": 0.002,
    #     "chop_period": 14,
    #     "chop_threshold": 51.655,
    #     "daily_ema_fast": 21,
    #     "daily_ema_slow": 59,
    #     "daily_ma_cross_fast": 66,
    #     "daily_ma_cross_slow": 121,
    #     "dd_circuit_enable": 1,
    #     "dd_lookback_candles": 156,
    #     "dd_max_allowed": 0.064,
    #     "dd_stop_duration_candles": 141,
    #     "dd_trade_limit": 14,
    #     "donchian_period": 19,
    #     "entry_adx_h_threshold": 35,
    #     "entry_adx_slope_lookback": 3,
    #     "entry_adx_slope_thr": 1.654,
    #     "hourly_ema_long": 43,
    #     "hourly_ema_short": 10,
    #     "regime_gate_enable": 1,
    #     "risk_parity_enable": 0,
    #     "rsi_oversold": 40,
    #     "stake_scale_max": 2.156,
    #     "stake_scale_min": 0.561,
    #     "stake_target_atr_pct": 0.03,
    #     "volume_multiplier": 1.526,
    #     "weekly_adx_threshold": 32,
    #     "weekly_ema_fast": 27,
    #     "weekly_ema_slow": 86,
    # }

    # Sell parameters:
    # sell_params = {
    #     "atr_ratio_ma_len": 23,
    #     "atr_ratio_thr": 1.957,
    #     "dd_cut_atr_pct_mult": 15.391,
    #     "dd_cut_max": 0.032,
    #     "dd_cut_min": 0.295,
    #     "emergency_atr_mult": 3.387,
    #     "exit_atr_buffer_mult": 0.08,
    #     "loss_cut_atr_pct_mult": 2.644,
    #     "loss_cut_max": 0.139,
    #     "loss_cut_min": 0.009,
    #     "loss_gate_atr_pct_mult": 4.611,
    #     "loss_gate_max": 0.229,
    #     "loss_gate_min": 0.105,
    #     "panic_atr_ratio_thr": 1.127,
    #     "panic_rsi_long": 54,
    #     "panic_rsi_short": 62,
    #     "rsi_overbought": 80,
    #     "struct_atr_mult": 2.089,
    #     "struct_atr_pct_mult": 1.271,
    #     "struct_atr_ratio_thr": 2.034,
    #     "struct_profit_thr": 0.073,
    #     "tighten_stop_atr_pct_mult": 0.35,
    #     "tighten_stop_max": 0.056,
    #     "tighten_stop_min": 0.043,
    #     "tighten_trigger_atr_pct_mult": 1.636,
    #     "tighten_trigger_min": 0.012,
    #     "time_cut_atr_pct_mult": 8.465,
    #     "time_cut_hours": 78,
    #     "time_cut_max": 0.269,
    #     "time_cut_min": 0.161,
    #     "time_vol_atr_pct_mult": 2.789,
    #     "time_vol_hours": 25,
    #     "time_vol_profit_thr": 0.023,
    # }

    # ROI parameters:
    minimal_roi = {
        "0": 0.30,
        "240": 0.10,
        "480": 0.05,
        "960": 0.02,
        "1440": 0
    }

    # Stoploss parameters:
    stoploss = -0.206

    # Trailing stop parameters:
    trailing_stop = True
    trailing_stop_positive = 0.03
    trailing_stop_positive_offset = 0.06
    trailing_only_offset_is_reached = False

    # ==================== 通用参数 ====================
    # 周线参数
    weekly_ema_fast = IntParameter(10, 30, default=16, space="buy")
    weekly_ema_slow = IntParameter(40, 100, default=48, space="buy")
    weekly_adx_threshold = IntParameter(20, 35, default=29, space="buy")

    btc_weekly_adx_threshold = IntParameter(15, 45, default=31, space="buy")
    btc_weekly_macd_slope_pct_thr = DecimalParameter(0.0, 0.01, default=0.006, space="buy")
    btc_check_enable = IntParameter(0, 1, default=1, space="buy")

    # 日线参数
    daily_ema_fast = IntParameter(10, 30, default=21, space="buy")
    daily_ema_slow = IntParameter(40, 100, default=59, space="buy")
    daily_ma_cross_fast = IntParameter(30, 70, default=66, space="buy")
    daily_ma_cross_slow = IntParameter(80, 150, default=121, space="buy")

    # 1h 参数
    hourly_ema_short = IntParameter(8, 20, default=10, space="buy")
    hourly_ema_long = IntParameter(20, 50, default=43, space="buy")
    donchian_period = IntParameter(15, 40, default=19, space="buy")
    rsi_oversold = IntParameter(20, 40, default=40, space="buy")
    rsi_overbought = IntParameter(60, 80, default=80, space="sell")

    # 成交量过滤
    volume_multiplier = DecimalParameter(1.0, 2.0, default=1.526, space="buy")

    entry_vol_gate_enable = IntParameter(0, 1, default=1, space="buy")
    entry_vol_max_atr_pct = DecimalParameter(0.005, 0.20, default=0.09, space="buy")
    entry_breakout_confirm_bars = IntParameter(1, 3, default=2, space="buy")

    emergency_atr_mult = DecimalParameter(1.5, 4.0, default=3.387, space="sell")
    atr_ratio_thr = DecimalParameter(1.1, 2.5, default=1.957, space="sell")
    atr_ratio_ma_len = IntParameter(10, 80, default=23, space="sell")
    exit_atr_buffer_mult = DecimalParameter(0.0, 1.5, default=0.08, space="sell")
    panic_atr_ratio_thr = DecimalParameter(1.0, 2.5, default=1.127, space="sell")
    panic_rsi_long = IntParameter(30, 55, default=54, space="sell")
    panic_rsi_short = IntParameter(45, 70, default=62, space="sell")

    struct_atr_mult = DecimalParameter(1.0, 5.0, default=2.089, space="sell")
    struct_atr_ratio_thr = DecimalParameter(1.0, 2.5, default=2.034, space="sell")
    struct_profit_thr = DecimalParameter(0.01, 0.10, default=0.073, space="sell")
    struct_atr_pct_mult = DecimalParameter(0.5, 3.0, default=1.271, space="sell")
    time_vol_hours = IntParameter(8, 72, default=25, space="sell")
    time_vol_profit_thr = DecimalParameter(0.01, 0.10, default=0.023, space="sell")
    time_vol_atr_pct_mult = DecimalParameter(0.5, 3.0, default=2.789, space="sell")

    loss_gate_min = DecimalParameter(0.01, 0.15, default=0.05, space="sell")
    loss_gate_atr_pct_mult = DecimalParameter(0.2, 6.0, default=2.5, space="sell")
    loss_gate_max = DecimalParameter(0.02, 0.25, default=0.12, space="sell")

    # 新增：无条件ATR止损（品种自适应核心）
    unconditional_atr_stop_mult = DecimalParameter(1.0, 6.0, default=5.0, space="sell")

    tighten_trigger_min = DecimalParameter(0.001, 0.05, default=0.012, space="sell")
    tighten_trigger_atr_pct_mult = DecimalParameter(0.05, 3.0, default=1.636, space="sell")
    tighten_stop_min = DecimalParameter(0.005, 0.15, default=0.043, space="sell")
    tighten_stop_atr_pct_mult = DecimalParameter(0.2, 8.0, default=0.35, space="sell")
    tighten_stop_max = DecimalParameter(0.01, 0.25, default=0.056, space="sell")
    
    # Panic Entry Parameters (Added for tuning)
    panic_entry_enable = IntParameter(0, 1, default=0, space="buy")
    panic_entry_rsi_long = IntParameter(50, 70, default=55, space="buy")
    panic_entry_rsi_short = IntParameter(30, 50, default=45, space="sell")
    panic_entry_volume_ratio = DecimalParameter(1.0, 3.0, default=1.5, space="sell")
    
    # Strategy 8: Daily Reversal Short Parameters
    daily_rsi_short_min = IntParameter(40, 70, default=50, space="sell")
    daily_willr_short_min = IntParameter(-50, -10, default=-20, space="sell")
    
    loss_cut_min = DecimalParameter(0.005, 0.15, default=0.02, space="sell")
    loss_cut_atr_pct_mult = DecimalParameter(0.2, 6.0, default=4.0, space="sell")
    loss_cut_max = DecimalParameter(0.01, 0.25, default=0.139, space="sell")

    time_cut_hours = IntParameter(8, 120, default=96, space="sell")
    time_cut_min = DecimalParameter(0.01, 0.25, default=0.161, space="sell")
    time_cut_atr_pct_mult = DecimalParameter(0.2, 12.0, default=8.465, space="sell")
    time_cut_max = DecimalParameter(0.02, 0.35, default=0.269, space="sell")

    dd_cut_min = DecimalParameter(0.02, 0.35, default=0.295, space="sell")
    dd_cut_atr_pct_mult = DecimalParameter(0.5, 16.0, default=15.391, space="sell")
    dd_cut_max = DecimalParameter(0.03, 0.50, default=0.032, space="sell")

    # 1. 震荡/假突破过滤器参数 (Regime Filter)
    # 默认关闭，因为Bayesian优化显示在当前数据下开启会导致过度过滤或选择高点入场
    regime_gate_enable = IntParameter(0, 1, default=0, space="buy")
    
    # 均值回归参数 (Mean Reversion)
    bollinger_mean_reversion_enable = IntParameter(0, 1, default=1, space="buy")
    mr_bb_period = IntParameter(14, 40, default=14, space="buy")
    mr_bb_std_dev = DecimalParameter(1.5, 3.0, default=2.58, space="buy")
    mr_rsi_oversold = IntParameter(10, 35, default=35, space="buy")
    mr_rsi_overbought = IntParameter(65, 90, default=78, space="sell")
    mr_adx_max = IntParameter(15, 30, default=15, space="buy")
    mr_profit_target = DecimalParameter(0.01, 0.05, default=0.038, space="sell")
    mr_stop_loss = DecimalParameter(0.02, 0.10, default=0.071, space="sell")

    # CHOP: Lower is stricter (requires stronger trend/less chop). Default 61.8 -> 58.0
    chop_period = IntParameter(10, 30, default=20, space="buy")
    chop_threshold = DecimalParameter(50.0, 70.0, default=62.66, space="buy")
    
    # ADX: Higher is stricter (requires stronger trend). Default 18 -> 25
    entry_adx_h_threshold = IntParameter(10, 35, default=28, space="buy")
    entry_adx_slope_lookback = IntParameter(1, 6, default=1, space="buy")
    entry_adx_slope_thr = DecimalParameter(0.0, 3.0, default=1.675, space="buy")
    
    # BBW Expansion: Higher is stricter (requires more expansion relative to MA). Default 1.0 -> 1.2
    bbw_period = IntParameter(14, 40, default=40, space="buy")
    bbw_ma_len = IntParameter(20, 120, default=67, space="buy")
    bbw_ratio_thr = DecimalParameter(0.70, 1.50, default=1.035, space="buy")

    # 默认关闭风险平价，因为高波动率交易往往导致亏损
    risk_parity_enable = IntParameter(0, 1, default=1, space="buy")
    stake_target_atr_pct = DecimalParameter(0.005, 0.06, default=0.03, space="buy")
    stake_scale_min = DecimalParameter(0.10, 1.00, default=0.561, space="buy")
    stake_scale_max = DecimalParameter(1.00, 3.00, default=2.156, space="buy")

    dd_circuit_enable = IntParameter(0, 1, default=1, space="buy")
    dd_max_allowed = DecimalParameter(0.01, 0.08, default=0.064, space="buy")
    dd_lookback_candles = IntParameter(24, 240, default=156, space="buy")
    dd_stop_duration_candles = IntParameter(12, 240, default=141, space="buy")
    dd_trade_limit = IntParameter(1, 20, default=14, space="buy")

    def _btc_market_pair(self) -> str:
        try:
            if str(self.config.get("trading_mode") or "").strip().lower() == "futures":
                return "BTC/USDT:USDT"
        except Exception:
            pass
        return "BTC/USDT"

    def informative_pairs(self):
        pairs = []
        try:
            pairs = self.dp.current_whitelist()
        except Exception:
            pairs = []

        informative = [(pair, "1d") for pair in pairs]
        informative.append((self._btc_market_pair(), "1d"))

        seen = set()
        deduped = []
        for p, tf in informative:
            key = (p, tf)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(key)

        return deduped

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        pair = metadata["pair"]

        btc_daily = self.dp.get_pair_dataframe(self._btc_market_pair(), "1d")
        if btc_daily is not None and not btc_daily.empty:
            btc_daily = btc_daily.copy()
            btc_daily["date"] = pd.to_datetime(btc_daily["date"], utc=True, errors="coerce")
            for col in ("open", "high", "low", "close", "volume"):
                if col in btc_daily.columns:
                    btc_daily[col] = pd.to_numeric(btc_daily[col], errors="coerce")

            btc_daily = btc_daily.dropna(subset=["date", "close"]).sort_values("date")
            base = btc_daily[["date", "open", "high", "low", "close", "volume"]].copy()
            base["week_start"] = base["date"] - pd.to_timedelta((base["date"].dt.dayofweek + 1) % 7, unit="D")
            btc_weekly = (
                base.groupby("week_start", as_index=False)
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna(subset=["close"])
            )
            btc_weekly["date"] = pd.to_datetime(btc_weekly["week_start"], utc=True, errors="coerce")
            btc_weekly = btc_weekly.drop(columns=["week_start"]).dropna(subset=["date"]).sort_values("date")

            macd = ta.MACD(btc_weekly)
            btc_weekly["btc_macdhist_w"] = pd.to_numeric(macd["macdhist"], errors="coerce")
            btc_weekly["btc_adx_w"] = pd.to_numeric(ta.ADX(btc_weekly, timeperiod=14), errors="coerce")
            btc_weekly["btc_macdhist_slope"] = btc_weekly["btc_macdhist_w"] - btc_weekly["btc_macdhist_w"].shift(1)
            btc_weekly["btc_macdhist_slope_pct"] = btc_weekly["btc_macdhist_slope"] / btc_weekly["close"].replace(0, 1e-10)

            slope_thr = float(self.btc_weekly_macd_slope_pct_thr.value)
            adx_thr = float(self.btc_weekly_adx_threshold.value)
            btc_hist_down = (
                (btc_weekly["btc_macdhist_w"] < 0)
                & (btc_weekly["btc_macdhist_w"] < btc_weekly["btc_macdhist_w"].shift(1))
            )
            btc_weekly["btc_weekly_short_ok"] = (
                btc_hist_down
                & (btc_weekly["btc_adx_w"] > adx_thr)
                & (btc_weekly["btc_macdhist_slope_pct"] < (-slope_thr))
            )
            btc_weekly[["btc_weekly_short_ok", "btc_macdhist_slope_pct", "btc_adx_w"]] = btc_weekly[
                ["btc_weekly_short_ok", "btc_macdhist_slope_pct", "btc_adx_w"]
            ].shift(1)

            btc_daily_map = btc_daily[["date"]].copy()
            btc_daily_map["week_start"] = btc_daily_map["date"] - pd.to_timedelta(
                (btc_daily_map["date"].dt.dayofweek + 1) % 7, unit="D"
            )
            btc_weekly_map = btc_weekly[["date", "btc_weekly_short_ok", "btc_macdhist_slope_pct", "btc_adx_w"]].copy()
            btc_weekly_map = btc_weekly_map.rename(columns={"date": "week_start"})
            btc_daily_map = btc_daily_map.merge(btc_weekly_map, on="week_start", how="left")
            btc_daily_map = btc_daily_map.drop(columns=["week_start"])

            dataframe = merge_informative_pair(dataframe, btc_daily_map, self.timeframe, "1d", ffill=True)
            dataframe.rename(
                columns={
                    "btc_weekly_short_ok_1d": "btc_weekly_short_ok",
                    "btc_macdhist_slope_pct_1d": "btc_macdhist_slope_pct",
                    "btc_adx_w_1d": "btc_adx_w",
                },
                inplace=True,
            )
        else:
            dataframe["btc_weekly_short_ok"] = False
            dataframe["btc_macdhist_slope_pct"] = 0.0
            dataframe["btc_adx_w"] = 0.0

        # 日线指标
        daily_df = self.dp.get_pair_dataframe(pair, "1d")
        if daily_df is not None and len(daily_df) >= self.daily_ema_slow.value:
            daily_df["ema_fast_d"] = ta.EMA(daily_df, timeperiod=self.daily_ema_fast.value)
            daily_df["ema_slow_d"] = ta.EMA(daily_df, timeperiod=self.daily_ema_slow.value)
            daily_df["ma_cross_fast_d"] = ta.EMA(daily_df, timeperiod=self.daily_ma_cross_fast.value)
            daily_df["ma_cross_slow_d"] = ta.EMA(daily_df, timeperiod=self.daily_ma_cross_slow.value)

            # Fix Lookahead Bias: Shift daily indicators by 1 day so we use yesterday's values
            daily_cols = ["ema_fast_d", "ema_slow_d", "ma_cross_fast_d", "ma_cross_slow_d"]
            
            # Additional Indicators for Strategy 8
            daily_df["rsi_d"] = ta.RSI(daily_df, timeperiod=14)
            daily_df["willr_d"] = ta.WILLR(daily_df, timeperiod=14)
            macd_d = ta.MACD(daily_df)
            daily_df["macdhist_d"] = macd_d["macdhist"]
            daily_df["macd_d"] = macd_d["macd"]
            daily_df["macdsignal_d"] = macd_d["macdsignal"]
            
            daily_cols.extend(["rsi_d", "willr_d", "macdhist_d", "macd_d", "macdsignal_d"])
            
            daily_df[daily_cols] = daily_df[daily_cols].shift(1)

            base = daily_df[["date", "open", "high", "low", "close", "volume"]].copy()
            base["date"] = pd.to_datetime(base["date"], utc=True, errors="coerce")
            base = base.dropna(subset=["date"]).sort_values("date")
            base["week_start"] = base["date"] - pd.to_timedelta((base["date"].dt.dayofweek + 1) % 7, unit="D")
            weekly = (
                base.groupby("week_start", as_index=False)
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna(subset=["close"])
            )
            weekly["date"] = pd.to_datetime(weekly["week_start"], utc=True, errors="coerce")
            weekly = weekly.drop(columns=["week_start"]).dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

            if len(weekly) >= int(self.weekly_ema_slow.value):
                weekly["ema_fast_w"] = ta.EMA(weekly, timeperiod=int(self.weekly_ema_fast.value))
                weekly["ema_slow_w"] = ta.EMA(weekly, timeperiod=int(self.weekly_ema_slow.value))
                weekly["adx_w"] = ta.ADX(weekly, timeperiod=14)
                weekly[["ema_fast_w", "ema_slow_w", "adx_w"]] = weekly[["ema_fast_w", "ema_slow_w", "adx_w"]].shift(1)

                daily_map = daily_df[["date"]].copy()
                daily_map["date"] = pd.to_datetime(daily_map["date"], utc=True, errors="coerce")
                daily_map = daily_map.dropna(subset=["date"]).sort_values("date")
                daily_map["week_start"] = daily_map["date"] - pd.to_timedelta((daily_map["date"].dt.dayofweek + 1) % 7, unit="D")

                weekly_map = weekly[["date", "ema_fast_w", "ema_slow_w", "adx_w"]].copy()
                weekly_map = weekly_map.rename(columns={"date": "week_start"})
                daily_map = daily_map.merge(weekly_map, on="week_start", how="left")
                daily_map = daily_map[["date", "ema_fast_w", "ema_slow_w", "adx_w"]]

                daily_df = daily_df.merge(daily_map, on="date", how="left")

            for c in ("ema_fast_w", "ema_slow_w", "adx_w"):
                if c not in daily_df.columns:
                    daily_df[c] = np.nan

            daily_df = daily_df[["date", "ema_fast_d", "ema_slow_d", "ma_cross_fast_d", "ma_cross_slow_d", "ema_fast_w", "ema_slow_w", "adx_w", "rsi_d", "willr_d", "macdhist_d", "macd_d", "macdsignal_d"]].copy()

            dataframe = merge_informative_pair(dataframe, daily_df, self.timeframe, "1d", ffill=True)
            dataframe.rename(
                columns={
                    "ema_fast_d_1d": "ema_fast_d",
                    "ema_slow_d_1d": "ema_slow_d",
                    "ma_cross_fast_d_1d": "ma_cross_fast_d",
                    "ma_cross_slow_d_1d": "ma_cross_slow_d",
                    "ema_fast_w_1d": "ema_fast_w",
                    "ema_slow_w_1d": "ema_slow_w",
                    "adx_w_1d": "adx_w",
                    "rsi_d_1d": "rsi_d",
                    "willr_d_1d": "willr_d",
                    "macdhist_d_1d": "macdhist_d",
                    "macd_d_1d": "macd_d",
                    "macdsignal_d_1d": "macdsignal_d",
                },
                inplace=True,
            )

        dataframe = dataframe.loc[:, ~dataframe.columns.duplicated()].copy()
        for c in (
            "ema_fast_w",
            "ema_slow_w",
            "adx_w",
            "ema_fast_d",
            "ema_slow_d",
            "ma_cross_fast_d",
            "ma_cross_slow_d",
            "rsi_d",
            "willr_d",
            "macdhist_d",
            "macd_d",
            "macdsignal_d",
        ):
            if c not in dataframe.columns:
                dataframe[c] = pd.NA

        # 1h 指标
        dataframe["ema_short_h"] = ta.EMA(dataframe, timeperiod=self.hourly_ema_short.value)
        dataframe["ema_long_h"] = ta.EMA(dataframe, timeperiod=self.hourly_ema_long.value)
        dataframe["rsi_h"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["adx_h"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr_h"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr_h"] / dataframe["close"].replace(0, np.nan)
        atr_ma_len = int(self.atr_ratio_ma_len.value)
        atr_ma_len = max(2, atr_ma_len)
        dataframe["atr_h_ma"] = dataframe["atr_h"].rolling(atr_ma_len).mean()
        dataframe["atr_ratio"] = dataframe["atr_h"] / dataframe["atr_h_ma"].replace(0, 1e-10)

        chop_len = int(self.chop_period.value)
        chop_len = max(2, chop_len)
        tr = ta.TRANGE(dataframe)
        tr_sum = tr.rolling(chop_len).sum()
        high_max = dataframe["high"].rolling(chop_len).max()
        low_min = dataframe["low"].rolling(chop_len).min()
        denom = (high_max - low_min).replace(0, np.nan)
        dataframe["chop_h"] = 100.0 * (np.log10(tr_sum / denom) / np.log10(float(chop_len)))

        bbw_period = int(self.bbw_period.value)
        bbw_period = max(2, bbw_period)
        bb = ta.BBANDS(dataframe, timeperiod=bbw_period, nbdevup=2.0, nbdevdn=2.0, matype=0)
        bb_mid = bb["middleband"].replace(0, np.nan)
        dataframe["bb_width"] = (bb["upperband"] - bb["lowerband"]) / bb_mid
        bbw_ma_len = int(self.bbw_ma_len.value)
        bbw_ma_len = max(2, bbw_ma_len)
        dataframe["bb_width_ma"] = dataframe["bb_width"].rolling(bbw_ma_len).mean()
        dataframe["bb_width_ratio"] = dataframe["bb_width"] / dataframe["bb_width_ma"].replace(0, np.nan)

        # 均值回归专用布林带 (独立参数)
        mr_bb_period = int(self.mr_bb_period.value)
        mr_bb_dev = float(self.mr_bb_std_dev.value)
        mr_bb = ta.BBANDS(dataframe, timeperiod=mr_bb_period, nbdevup=mr_bb_dev, nbdevdn=mr_bb_dev, matype=0)
        dataframe["mr_bb_upper"] = mr_bb["upperband"]
        dataframe["mr_bb_middle"] = mr_bb["middleband"]
        dataframe["mr_bb_lower"] = mr_bb["lowerband"]

        adx_lb = int(self.entry_adx_slope_lookback.value)
        adx_lb = max(1, adx_lb)
        dataframe["adx_h_slope"] = dataframe["adx_h"] - dataframe["adx_h"].shift(adx_lb)

        # Donchian通道
        dataframe["donchian_upper_h"] = dataframe["high"].rolling(self.donchian_period.value).max()
        dataframe["donchian_lower_h"] = dataframe["low"].rolling(self.donchian_period.value).min()

        # 成交量
        dataframe["volume_sma"] = dataframe["volume"].rolling(20).mean()
        dataframe["volume_ratio"] = dataframe["volume"] / dataframe["volume_sma"].replace(0, 1)

        dataframe["mom_ret_1d"] = dataframe["close"] / dataframe["close"].shift(24) - 1.0
        dataframe["mom_ret_3d"] = dataframe["close"] / dataframe["close"].shift(72) - 1.0
        dataframe["mom_rsi_delta"] = dataframe["rsi_h"] - dataframe["rsi_h"].shift(1)
        dataframe["mom_macdhist_delta"] = dataframe["macdhist_d"] - dataframe["macdhist_d"].shift(1)

        v_mean = dataframe["volume"].rolling(20).mean()
        v_std = dataframe["volume"].rolling(20).std(ddof=0).replace(0, np.nan)
        dataframe["vol_z_20"] = (dataframe["volume"] - v_mean) / v_std
        dataframe["vol_ratio_delta"] = dataframe["volume_ratio"] - dataframe["volume_ratio"].shift(1)

        dataframe["pot_adx_delta"] = dataframe["adx_h"] - dataframe["adx_h"].shift(1)
        dataframe["pot_atr_pct"] = dataframe["atr_pct"]
        ema50 = ta.EMA(dataframe, timeperiod=50)
        dataframe["pot_dist_to_ema50"] = (dataframe["close"] - ema50) / dataframe["close"].replace(0, np.nan)

        # 填充NaN
        dataframe.ffill(inplace=True)
        dataframe.fillna(0, inplace=True)

        weekly_up = dataframe["ema_fast_w"] > dataframe["ema_slow_w"]
        weekly_down = dataframe["ema_fast_w"] < dataframe["ema_slow_w"]
        daily_up = dataframe["ma_cross_fast_d"] > dataframe["ma_cross_slow_d"]
        daily_down = dataframe["ma_cross_fast_d"] < dataframe["ma_cross_slow_d"]
        weekly_adx = dataframe["adx_w"].where(dataframe["adx_w"] > 0, dataframe["adx_h"])
        weekly_trend_strong = weekly_adx > float(self.weekly_adx_threshold.value)
        dataframe["weekly_trend"] = np.where(weekly_up, "up", np.where(weekly_down, "down", "flat"))
        dataframe["daily_trend"] = np.where(daily_up, "up", np.where(daily_down, "down", "flat"))
        dataframe["time_regime"] = np.select(
            [
                (~weekly_trend_strong),
                (weekly_trend_strong & weekly_up & daily_up),
                (weekly_trend_strong & weekly_up & daily_down),
                (weekly_trend_strong & weekly_down & daily_down),
                (weekly_trend_strong & weekly_down & daily_up),
            ],
            ["chop", "uptrend_strong", "uptrend_reversal", "downtrend_strong", "downtrend_reversal"],
            default="chop",
        )
        try:
            highvol_thr = float(getattr(self, "_exit_highvol_atr_pct", 0.035) or 0.035)
        except Exception:
            highvol_thr = 0.035
        dataframe["regime"] = np.where(
            dataframe["atr_pct"] >= float(highvol_thr),
            "highvol",
            np.where(dataframe["time_regime"] == "chop", "chop", "trend"),
        )

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0

        volume_ok = dataframe["volume_ratio"] > self.volume_multiplier.value
        btc_weekly_short_ok = dataframe.get("btc_weekly_short_ok", 0).fillna(0).astype(bool)

        total_gate_ok = True
        if int(self.regime_gate_enable.value) == 1:
            chop_ok = dataframe.get("chop_h", 0).fillna(0) < float(self.chop_threshold.value)
            adx_h = dataframe.get("adx_h", 0).fillna(0)
            adx_ok = adx_h > float(self.entry_adx_h_threshold.value)
            adx_slope_ok = dataframe.get("adx_h_slope", 0).fillna(0) > float(self.entry_adx_slope_thr.value)
            bbw_ratio_ok = dataframe.get("bb_width_ratio", 0).fillna(0) > float(self.bbw_ratio_thr.value)
            total_gate_ok = chop_ok & (adx_ok | adx_slope_ok) & bbw_ratio_ok

        btc_slope = dataframe.get("btc_macdhist_slope_pct", 0).fillna(0)
        btc_slope_thr = float(self.btc_weekly_macd_slope_pct_thr.value)
        weekly_down_loose = (
            (dataframe["ema_fast_w"] < dataframe["ema_slow_w"]) |
            (dataframe["close"] < dataframe["ema_slow_w"]) |
            (btc_slope < -0.003)
        )
        weekly_up_loose = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) |
            (dataframe["close"] > dataframe["ema_slow_w"]) |
            (btc_slope > 0.003)
        )

        adx_h_base = dataframe.get("adx_h", 0).fillna(0)
        atr_h = dataframe.get("atr_h", 0).fillna(0)
        close = dataframe.get("close", 0).fillna(0)

        atr_pct = atr_h / close.replace(0, 1e-10)
        vol_gate_ok = True
        if int(self.entry_vol_gate_enable.value) == 1:
            vol_gate_ok = atr_pct < float(self.entry_vol_max_atr_pct.value)

        local_trend = adx_h_base > float(self.mr_adx_max.value)
        local_range = ~local_trend

        if self.btc_check_enable.value:
            is_trend_long_market = local_trend & (btc_slope > -btc_slope_thr)
            is_trend_short_market = local_trend & (btc_slope < btc_slope_thr)
            is_range_market = local_range & (btc_slope.abs() < btc_slope_thr)
        else:
            is_trend_long_market = local_trend
            is_trend_short_market = local_trend
            is_range_market = local_range

        confirm_n = int(self.entry_breakout_confirm_bars.value)
        confirm_n = max(1, confirm_n)

        turtle_long = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) &
            (dataframe["adx_w"] > self.weekly_adx_threshold.value) &
            (dataframe["close"] > dataframe["donchian_upper_h"].shift(confirm_n)) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_long_market
        )
        turtle_short = (
            weekly_down_loose &
            (dataframe["adx_w"] > self.weekly_adx_threshold.value) &
            (dataframe["close"] < dataframe["donchian_lower_h"].shift(confirm_n)) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_short_market
        )

        # ==================== 策略2：多重移动平均线交叉 ====================
        ma_cross_long = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) &
            (dataframe["ma_cross_fast_d"] > dataframe["ma_cross_slow_d"]) &
            (dataframe["ema_short_h"] > dataframe["ema_long_h"]) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_long_market
        )
        ma_cross_short = (
            weekly_down_loose &
            (dataframe["ma_cross_fast_d"] < dataframe["ma_cross_slow_d"]) &
            (dataframe["ema_short_h"] < dataframe["ema_long_h"]) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_short_market
        )

        # ==================== 策略3：一目均衡表（Ichimoku）简化版 ====================
        # 周线云趋势 + 日线转换/基准交叉 + 1h价格突破云（用EMA模拟云）
        ichimoku_long = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) &
            (dataframe["ema_fast_d"] > dataframe["ema_slow_d"]) &
            (dataframe["close"] > dataframe["ema_long_h"]) &
            (dataframe["rsi_h"] > self.rsi_oversold.value) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_long_market
        )
        ichimoku_short = (
            weekly_down_loose &
            (dataframe["ema_fast_d"] < dataframe["ema_slow_d"]) &
            (dataframe["close"] < dataframe["ema_long_h"]) &
            (dataframe["rsi_h"] < self.rsi_overbought.value) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_short_market
        )

        # ==================== 策略4：Donchian通道多时间框架突破 ====================
        donchian_long = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) &
            (dataframe["close"] > dataframe["donchian_upper_h"].shift(confirm_n)) &
            (dataframe["close"] > dataframe["close"].shift(1)) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_long_market
        )
        donchian_short = (
            (dataframe["ema_fast_w"] < dataframe["ema_slow_w"]) &
            (dataframe["close"] < dataframe["donchian_lower_h"].shift(confirm_n)) &
            (dataframe["close"] < dataframe["close"].shift(1)) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_short_market
        )

        # ==================== 策略5：ADX + RSI 多时间框架 ====================
        adx_rsi_long = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) &
            (dataframe["adx_w"] > self.weekly_adx_threshold.value) &
            (dataframe["rsi_h"] < self.rsi_oversold.value) &
            (dataframe["close"] > dataframe["ema_short_h"]) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_long_market
        )
        adx_rsi_short = (
            (dataframe["ema_fast_w"] < dataframe["ema_slow_w"]) &
            (dataframe["adx_w"] > self.weekly_adx_threshold.value) &
            (dataframe["rsi_h"] > self.rsi_overbought.value) &
            (dataframe["close"] < dataframe["ema_short_h"]) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_short_market
        )

        # ==================== Strategy: ADX Slope ====================
        adx_slope_long = (
            (dataframe["ema_fast_w"] > dataframe["ema_slow_w"]) &
            (dataframe["adx_h_slope"] > self.entry_adx_slope_thr.value) &
            (dataframe["close"] > dataframe["ema_short_h"]) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_long_market
        )
        adx_slope_short = (
            (dataframe["ema_fast_w"] < dataframe["ema_slow_w"]) &
            (dataframe["adx_h_slope"] > self.entry_adx_slope_thr.value) &
            (dataframe["close"] < dataframe["ema_short_h"]) &
            volume_ok &
            total_gate_ok &
            vol_gate_ok &
            is_trend_short_market
        )

        # ==================== 策略6：布林带均值回归 (Bollinger Reversion) ====================
        # 仅在低波动/震荡市场开启 (ADX < Threshold)
        # 逻辑：价格跌破下轨 + RSI超卖 -> 回归中轨
        
        # New Strategy 7: Panic Short (Dedicated Short Strategy)
        # Trigger: Relaxed Weekly Down Trend + 1h Breakdown
        panic_enabled = int(self.panic_entry_enable.value) == 1
        panic_short_entry = (
            panic_enabled &
            weekly_down_loose &
            is_trend_short_market &
            (dataframe["close"] < dataframe["donchian_lower_h"].shift(confirm_n)) &
            (dataframe["close"] < dataframe["ema_short_h"]) &
            (dataframe["close"] < dataframe["ema_long_h"]) &
            (dataframe["rsi_h"] < self.panic_entry_rsi_short.value) &
            (dataframe["volume_ratio"] > self.panic_entry_volume_ratio.value) &
            total_gate_ok
        )
        
        # New Strategy 7b: Panic Long (Symmetric)
        panic_long = (
            panic_enabled &
            weekly_up_loose &
            is_trend_long_market &
            (dataframe["close"] > dataframe["donchian_upper_h"].shift(confirm_n)) &
            (dataframe["close"] > dataframe["ema_short_h"]) &
            (dataframe["close"] > dataframe["ema_long_h"]) &
            (dataframe["rsi_h"] > self.panic_entry_rsi_long.value) &
            (dataframe["volume_ratio"] > self.panic_entry_volume_ratio.value) &
            total_gate_ok
        )

        mr_long = (
            (dataframe["close"] < dataframe["mr_bb_lower"]) &
            (dataframe["rsi_h"] < self.mr_rsi_oversold.value) &
            is_range_market &
            volume_ok
        )
        
        mr_short = (
            (dataframe["close"] > dataframe["mr_bb_upper"]) &
            (dataframe["rsi_h"] > self.mr_rsi_overbought.value) &
            is_range_market &
            volume_ok
        )

        # 任意策略满足即可入场
        # 趋势策略需要 total_gate_ok (高波动/强趋势确认)
        # 回归策略需要 is_range_market (低波动确认)，且不需要 total_gate_ok
        
        # ==================== Strategy 8: Daily Reversal Short ====================
        # User Request: Daily MA Death Cross + RSI Overbought + MACD Death Cross
        # Added Williams %R as alternative "Overbought" check (TradFi standard)
        
        # 1. Trend: Daily MA Death Cross (Fast < Slow)
        daily_trend_down = (dataframe["ma_cross_fast_d"] < dataframe["ma_cross_slow_d"])
        
        # 2. Momentum: Daily MACD Death Cross (MACD < Signal) or MACD Hist turning down
        # Checking if MACD is below Signal (Bearish Momentum)
        daily_macd_down = (dataframe["macd_d"] < dataframe["macdsignal_d"])
        
        # 3. Overbought Condition: RSI or Williams %R was high
        # Since we are in a downtrend (MA Cross), RSI might not be super high (>70)
        # So we use a tunable threshold (default > 50 for pullbacks in downtrend)
        daily_rsi_check = (dataframe["rsi_d"] > self.daily_rsi_short_min.value)
        daily_willr_check = (dataframe["willr_d"] > self.daily_willr_short_min.value)
        
        daily_short_strategy = (
            daily_trend_down &
            daily_macd_down &
            (daily_rsi_check | daily_willr_check) &
            volume_ok &
            total_gate_ok &
            is_trend_short_market
        )

        dataframe.loc[turtle_long, "enter_long"] = 1
        dataframe.loc[ma_cross_long, "enter_long"] = 1
        dataframe.loc[ichimoku_long, "enter_long"] = 1
        dataframe.loc[donchian_long, "enter_long"] = 1
        dataframe.loc[adx_rsi_long, "enter_long"] = 1
        dataframe.loc[adx_slope_long, "enter_long"] = 1
        dataframe.loc[panic_long, "enter_long"] = 1
        
        # Mean Reversion Entry (Only if enabled)
        if int(self.bollinger_mean_reversion_enable.value) == 1:
            dataframe.loc[mr_long, "enter_long"] = 1
            dataframe.loc[mr_short, "enter_short"] = 1

        # Tags
        dataframe.loc[turtle_long, "enter_tag"] = "turtle_long"
        dataframe.loc[ma_cross_long, "enter_tag"] = "ma_cross_long"
        dataframe.loc[ichimoku_long, "enter_tag"] = "ichimoku_long"
        dataframe.loc[donchian_long, "enter_tag"] = "donchian_long"
        dataframe.loc[adx_rsi_long, "enter_tag"] = "adx_rsi_long"
        dataframe.loc[adx_slope_long, "enter_tag"] = "adx_slope_long"
        dataframe.loc[panic_long, "enter_tag"] = "panic_long"

        if int(self.bollinger_mean_reversion_enable.value) == 1:
            dataframe.loc[mr_long, "enter_tag"] = "mr_long"
            dataframe.loc[mr_short, "enter_tag"] = "mr_short"

        # Short Strategy Entries
        dataframe.loc[turtle_short, "enter_short"] = 1
        dataframe.loc[ma_cross_short, "enter_short"] = 1
        dataframe.loc[ichimoku_short, "enter_short"] = 1
        dataframe.loc[donchian_short, "enter_short"] = 1
        dataframe.loc[adx_rsi_short, "enter_short"] = 1
        dataframe.loc[adx_slope_short, "enter_short"] = 1
        dataframe.loc[panic_short_entry, "enter_short"] = 1
        dataframe.loc[daily_short_strategy, "enter_short"] = 1

        dataframe.loc[turtle_short, "enter_tag"] = "turtle_short"
        dataframe.loc[ma_cross_short, "enter_tag"] = "ma_cross_short"
        dataframe.loc[ichimoku_short, "enter_tag"] = "ichimoku_short"
        dataframe.loc[donchian_short, "enter_tag"] = "donchian_short"
        dataframe.loc[adx_rsi_short, "enter_tag"] = "adx_rsi_short"
        dataframe.loc[adx_slope_short, "enter_tag"] = "adx_slope_short"
        dataframe.loc[panic_short_entry, "enter_tag"] = "panic_short"
        dataframe.loc[daily_short_strategy, "enter_tag"] = "daily_short_strategy"
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
                pth_n = pth.rstrip("/")
                if "/signals/v1" in pth_n:
                    return raw
                if pth_n == "/signals":
                    return u._replace(path="/signals/v1").geturl()
                if "/signals" in pth:
                    return raw

                if "/decision" in pth:
                    new_path = "/signals/v1"
                elif pth in ("", "/"):
                    new_path = "/signals/v1"
                else:
                    new_path = pth.rstrip("/") + "/signals/v1"
                return u._replace(path=new_path).geturl()

            decision_url = _normalize_signals_url(os.environ.get("ML_EXPORT_URL", ""))
            feature_url = _normalize_signals_url(os.environ.get("ML_FEATURE_EXPORT_URL", ""))
            if (not feature_url) and decision_url:
                feature_url = decision_url

            if feature_url or decision_url:
                pair = metadata.get("pair")
                if pair:
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

                    if "enter_long" in dataframe.columns and "enter_short" in dataframe.columns:
                        sig_df = dataframe.loc[(dataframe["enter_long"] == 1) | (dataframe["enter_short"] == 1)]
                    else:
                        sig_df = dataframe.iloc[0:0]

                    if not sig_df.empty:
                        last_feature_ts = self._ml_export_last_ts_by_pair.get(pair)
                        last_decision_ts = self._ml_decision_last_ts_by_pair.get(pair)
                        last_any = None
                        if last_feature_ts is not None and last_decision_ts is not None:
                            last_any = max(int(last_feature_ts), int(last_decision_ts))
                        elif last_feature_ts is not None:
                            last_any = int(last_feature_ts)
                        elif last_decision_ts is not None:
                            last_any = int(last_decision_ts)

                        if last_any is not None:
                            try:
                                if "date" in sig_df.columns:
                                    sig_df = sig_df.loc[pd.to_datetime(sig_df["date"], utc=True, errors="coerce").astype("int64") // 1_000_000 > int(last_any)]
                            except Exception:
                                pass

                        try:
                            bounds = getattr(self, "_ml_export_ts_bounds_ms", None)
                            if bounds is None:
                                bounds_raw = str(os.environ.get("ML_EXPORT_TIMERANGE", "") or "").strip()
                                lo_ms = None
                                hi_ms = None
                                if bounds_raw and "-" in bounds_raw:
                                    a, b = bounds_raw.split("-", 1)
                                    a = a.strip()
                                    b = b.strip()
                                    if a:
                                        try:
                                            lo_ms = int(pd.Timestamp(a, tz="UTC").timestamp() * 1000)
                                        except Exception:
                                            lo_ms = None
                                    if b:
                                        try:
                                            hi_ms = int(pd.Timestamp(b, tz="UTC").timestamp() * 1000)
                                        except Exception:
                                            hi_ms = None
                                bounds = (lo_ms, hi_ms)
                                self._ml_export_ts_bounds_ms = bounds

                            if bounds and "date" in sig_df.columns:
                                lo_ms, hi_ms = bounds
                                if lo_ms is not None or hi_ms is not None:
                                    dt_ms = pd.to_datetime(sig_df["date"], utc=True, errors="coerce").astype("int64") // 1_000_000
                                    if lo_ms is not None:
                                        sig_df = sig_df.loc[dt_ms >= int(lo_ms)]
                                    if (not sig_df.empty) and hi_ms is not None:
                                        dt_ms = pd.to_datetime(sig_df["date"], utc=True, errors="coerce").astype("int64") // 1_000_000
                                        sig_df = sig_df.loc[dt_ms < int(hi_ms)]
                        except Exception:
                            pass

                        if not sig_df.empty:
                            def _emit(url: str, allow_trigger_decision: bool, row: pd.Series, ts_ms: int, side: str) -> None:
                                try:
                                    pth = ""
                                    try:
                                        pth = urlparse(url).path or ""
                                    except Exception:
                                        pth = ""

                                    is_decision = "/decision/" in pth
                                    if (not allow_trigger_decision) and is_decision:
                                        return

                                    close_v = _sf(row.get("close", 0.0) or 0.0)
                                    atr_h_v = _sf(row.get("atr_h", 0.0) or 0.0)
                                    adx_val = _sf(row.get("adx_h", 0.0) or 0.0)
                                    regime = "trend" if adx_val > float(self.mr_adx_max.value) else "chop"

                                    ema_short_h_v = _sf(row.get("ema_short_h", 0.0) or 0.0)
                                    ema_long_h_v = _sf(row.get("ema_long_h", 0.0) or 0.0)
                                    donchian_upper_h_v = _sf(row.get("donchian_upper_h", 0.0) or 0.0)
                                    donchian_lower_h_v = _sf(row.get("donchian_lower_h", 0.0) or 0.0)
                                    ema_fast_w_v = _sf(row.get("ema_fast_w", 0.0) or 0.0)
                                    ema_slow_w_v = _sf(row.get("ema_slow_w", 0.0) or 0.0)

                                    btc_weekly_short_ok_raw = row.get("btc_weekly_short_ok", False)
                                    if btc_weekly_short_ok_raw is None or pd.isna(btc_weekly_short_ok_raw):
                                        btc_weekly_short_ok_v = 0.0
                                    else:
                                        btc_weekly_short_ok_v = 1.0 if bool(btc_weekly_short_ok_raw) else 0.0

                                    group_id = str(os.environ.get("ML_GROUP_ID", "trend_4h_mtf") or "trend_4h_mtf")
                                    feature_set_id = str(os.environ.get("ML_FEATURE_SET_ID", "trend_4h_mtf_v1") or "trend_4h_mtf_v1")
                                    strategy_version = str(os.environ.get("ML_STRATEGY_VERSION", "1.0.0") or "1.0.0")
                                    bar_close_ms = int(ts_ms)
                                    if tf_ms > 0:
                                        bar_close_ms = int(ts_ms) + int(tf_ms)

                                    payload: Dict[str, Any] = {
                                        "signal_schema_version": 1,
                                        "venue": "freqtrade",
                                        "action": "open",
                                        "strategy_id": self.__class__.__name__,
                                        "strategy_version": strategy_version,
                                        "group_id": group_id,
                                        "feature_set_id": feature_set_id,
                                        "pair": pair,
                                        "side": side,
                                        "tag": _ss(row.get("enter_tag")),
                                        "timeframe": tf,
                                        "bar_open_ms": int(ts_ms),
                                        "bar_close_ms": int(bar_close_ms),
                                        "bar_closed": True,
                                        "ts": int(ts_ms),
                                        "features": {
                                            "close": close_v,
                                            "volume": _sf(row.get("volume", 0.0) or 0.0),
                                            "rsi_d": _sf(row.get("rsi_d", 0.0) or 0.0),
                                            "willr_d": _sf(row.get("willr_d", 0.0) or 0.0),
                                            "macd_d": _sf(row.get("macd_d", 0.0) or 0.0),
                                            "macdsignal_d": _sf(row.get("macdsignal_d", 0.0) or 0.0),
                                            "ma_cross_fast_d": _sf(row.get("ma_cross_fast_d", 0.0) or 0.0),
                                            "ma_cross_slow_d": _sf(row.get("ma_cross_slow_d", 0.0) or 0.0),
                                            "regime": regime,
                                            "atr_h": atr_h_v,
                                            "atr_pct": (atr_h_v / close_v) if close_v > 0.0 else 0.0,
                                            "atr_ratio": _sf(row.get("atr_ratio", 0.0) or 0.0),
                                            "adx_h": adx_val,
                                            "chop_h": _sf(row.get("chop_h", 0.0) or 0.0),
                                            "bb_width_ratio": _sf(row.get("bb_width_ratio", 0.0) or 0.0),
                                            "volume_ratio": _sf(row.get("volume_ratio", 0.0) or 0.0),
                                            "ema_short_dist": ((close_v - ema_short_h_v) / close_v) if close_v > 0.0 else 0.0,
                                            "ema_long_dist": ((close_v - ema_long_h_v) / close_v) if close_v > 0.0 else 0.0,
                                            "donchian_upper_dist": ((close_v - donchian_upper_h_v) / close_v) if close_v > 0.0 else 0.0,
                                            "donchian_lower_dist": ((close_v - donchian_lower_h_v) / close_v) if close_v > 0.0 else 0.0,
                                            "donchian_mid_dist": ((close_v - ((donchian_upper_h_v + donchian_lower_h_v) / 2.0)) / close_v) if close_v > 0.0 else 0.0,
                                            "btc_macdhist_slope_pct": _sf(row.get("btc_macdhist_slope_pct", 0.0) or 0.0),
                                            "weekly_state": 1.0 if ema_fast_w_v > ema_slow_w_v else (-1.0 if ema_fast_w_v < ema_slow_w_v else 0.0),
                                            "btc_weekly_short_ok": btc_weekly_short_ok_v,
                                        },
                                    }

                                    if tf_ms > 0:
                                        payload["bar_closed"] = bool(int(now_ms) >= int(ts_ms) + int(tf_ms) - 2_000)

                                    if allow_trigger_decision:
                                        if not is_decision:
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

                            for _, r in sig_df.iterrows():
                                side = None
                                try:
                                    if int(r.get("enter_short", 0) or 0) == 1:
                                        side = "short"
                                    elif int(r.get("enter_long", 0) or 0) == 1:
                                        side = "long"
                                except Exception:
                                    side = None
                                if side is None:
                                    continue

                                ts_ms = None
                                try:
                                    if "date" in r and r.get("date") is not None:
                                        dt = pd.to_datetime(r.get("date"), utc=True, errors="coerce")
                                        if dt is not None and (not pd.isna(dt)):
                                            ts_ms = int(pd.Timestamp(dt).timestamp() * 1000)
                                except Exception:
                                    ts_ms = None
                                if ts_ms is None:
                                    continue

                                def _feature_ok_to_send() -> bool:
                                    last_ts = self._ml_export_last_ts_by_pair.get(pair)
                                    if last_ts is not None and ts_ms <= int(last_ts):
                                        return False

                                    min_interval_s = 0.0
                                    try:
                                        raw = os.environ.get("ML_FEATURE_EXPORT_MIN_INTERVAL_SEC", os.environ.get("ML_EXPORT_MIN_INTERVAL_SEC", "0"))
                                        min_interval_s = float(str(raw or "0").strip() or 0.0)
                                    except Exception:
                                        min_interval_s = 0.0

                                    if min_interval_s <= 0.0 or last_ts is None:
                                        return True
                                    return (ts_ms - int(last_ts)) >= int(min_interval_s * 1000.0)

                                def _decision_ok_to_send() -> bool:
                                    last_ts = self._ml_decision_last_ts_by_pair.get(pair)
                                    return last_ts is None or ts_ms > int(last_ts)

                                if feature_url and _feature_ok_to_send() and (feature_url != decision_url):
                                    _emit(feature_url, allow_trigger_decision=False, row=r, ts_ms=ts_ms, side=side)
                                    self._ml_export_last_ts_by_pair[pair] = int(ts_ms)

                                if decision_url and _decision_ok_to_send():
                                    _emit(decision_url, allow_trigger_decision=True, row=r, ts_ms=ts_ms, side=side)
                                    self._ml_decision_last_ts_by_pair[pair] = int(ts_ms)
                                    if decision_url == feature_url:
                                        self._ml_export_last_ts_by_pair[pair] = int(ts_ms)
        except Exception:
            pass
        return dataframe

    def populate_buy_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = self.populate_entry_trend(dataframe, metadata)
        dataframe["buy"] = 0
        dataframe.loc[dataframe["enter_long"] == 1, "buy"] = 1
        if "buy_tag" not in dataframe.columns:
            dataframe["buy_tag"] = None
        return dataframe

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: float,
        max_stake: float,
        **kwargs,
    ) -> float:
        if int(self.risk_parity_enable.value) != 1:
            return proposed_stake

        if getattr(self, "dp", None) is None:
            return proposed_stake

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return proposed_stake

        row = dataframe.iloc[-1]
        close = float(row.get("close", 0.0) or 0.0)
        atr_h = float(row.get("atr_h", 0.0) or 0.0)
        if close <= 0.0 or atr_h <= 0.0:
            return proposed_stake

        atr_pct = atr_h / close
        target = float(self.stake_target_atr_pct.value)
        if atr_pct <= 0.0 or target <= 0.0:
            return proposed_stake

        scale = target / atr_pct
        scale = float(np.clip(scale, float(self.stake_scale_min.value), float(self.stake_scale_max.value)))

        stake = proposed_stake * scale
        stake = float(np.clip(stake, min_stake, max_stake))
        return stake

    @property
    def protections(self):
        if int(self.dd_circuit_enable.value) != 1:
            return []

        return [
            {
                "method": "MaxDrawdown",
                "lookback_period_candles": int(self.dd_lookback_candles.value),
                "trade_limit": int(self.dd_trade_limit.value),
                "max_allowed_drawdown": float(self.dd_max_allowed.value),
                "stop_duration_candles": int(self.dd_stop_duration_candles.value),
            }
        ]

    def populate_sell_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return self.populate_exit_trend(dataframe, metadata)

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        close = pd.to_numeric(dataframe.get("close"), errors="coerce")
        ema_short = pd.to_numeric(dataframe.get("ema_short_h"), errors="coerce")
        ema_long = pd.to_numeric(dataframe.get("ema_long_h"), errors="coerce")
        rsi_h = pd.to_numeric(dataframe.get("rsi_h"), errors="coerce")
        ema_fast_w = pd.to_numeric(dataframe.get("ema_fast_w"), errors="coerce")
        ema_slow_w = pd.to_numeric(dataframe.get("ema_slow_w"), errors="coerce")
        adx_w = pd.to_numeric(dataframe.get("adx_w"), errors="coerce").fillna(0.0)
        ma_fast_d = pd.to_numeric(dataframe.get("ma_cross_fast_d"), errors="coerce")
        ma_slow_d = pd.to_numeric(dataframe.get("ma_cross_slow_d"), errors="coerce")
        atr_h = pd.to_numeric(dataframe.get("atr_h"), errors="coerce").fillna(0.0)
        atr_ratio = pd.to_numeric(dataframe.get("atr_ratio"), errors="coerce").fillna(0.0)

        weekly_flip_down = (ema_fast_w < ema_slow_w) & (adx_w > float(self.weekly_adx_threshold.value))
        weekly_flip_up = (ema_fast_w > ema_slow_w) & (adx_w > float(self.weekly_adx_threshold.value))

        daily_bear = ma_fast_d < ma_slow_d
        daily_bull = ma_fast_d > ma_slow_d

        weekly_up = (ema_fast_w > ema_slow_w) & (adx_w > float(self.weekly_adx_threshold.value))
        weekly_down = (ema_fast_w < ema_slow_w) & (adx_w > float(self.weekly_adx_threshold.value))

        buf_mult = float(self.exit_atr_buffer_mult.value)
        ema_long_dn = ema_long - (atr_h * buf_mult)
        ema_long_up = ema_long + (atr_h * buf_mult)

        trend_protect_long = weekly_up & (close > ema_long_dn) & (rsi_h > 35)
        trend_protect_short = weekly_down & (close < ema_long_up) & (rsi_h < 65)

        below_short_2 = (close < ema_short) & (close.shift(1) < ema_short.shift(1))
        above_short_2 = (close > ema_short) & (close.shift(1) > ema_short.shift(1))

        down_2 = (close < close.shift(1)) & (close.shift(1) < close.shift(2))
        up_2 = (close > close.shift(1)) & (close.shift(1) > close.shift(2))

        weak_confirm_long = (atr_ratio > 1.05) | (rsi_h < 35) | down_2
        weak_confirm_short = (atr_ratio > 1.05) | (rsi_h > 65) | up_2

        bounce_long = (atr_ratio < 1.15) & (rsi_h > 40) & (rsi_h > rsi_h.shift(1)) & (close > close.shift(1))
        bounce_short = (atr_ratio < 1.15) & (rsi_h < 60) & (rsi_h < rsi_h.shift(1)) & (close < close.shift(1))

        loss_long = below_short_2 & daily_bear & (close < ema_long_dn) & weak_confirm_long & (~bounce_long) & (~(weekly_up & (atr_ratio < 1.05) & (rsi_h > 38)))
        loss_short = above_short_2 & daily_bull & (close > ema_long_up) & weak_confirm_short & (~bounce_short) & (~(weekly_down & (atr_ratio < 1.05) & (rsi_h < 62)))

        em_mult = float(self.emergency_atr_mult.value)
        atr_thr = float(self.atr_ratio_thr.value)
        panic_thr = float(self.panic_atr_ratio_thr.value)
        panic_rsi_long = float(self.panic_rsi_long.value)
        panic_rsi_short = float(self.panic_rsi_short.value)

        emergency_long = ((close < (ema_long - atr_h * em_mult)) | ((close < ema_long) & (atr_ratio > atr_thr) & (rsi_h < 40))).fillna(False)
        emergency_short = ((close > (ema_long + atr_h * em_mult)) | ((close > ema_long) & (atr_ratio > atr_thr) & (rsi_h > 60))).fillna(False)

        panic_long = (
            (close < ema_long_dn)
            & down_2
            & (
                ((atr_ratio > panic_thr) & (rsi_h < panic_rsi_long))
                | ((atr_ratio > 1.05) & (rsi_h < 40) & (~trend_protect_long))
            )
        ).fillna(False)
        panic_short = (
            (close > ema_long_up)
            & up_2
            & (
                ((atr_ratio > panic_thr) & (rsi_h > panic_rsi_short))
                | ((atr_ratio > 1.05) & (rsi_h > 70) & (~trend_protect_short))
            )
        ).fillna(False)

        overbought_reversal = (rsi_h > 82) & (rsi_h < rsi_h.shift(1)) & (close < ema_short)
        oversold_reversal = (rsi_h < 18) & (rsi_h > rsi_h.shift(1)) & (close > ema_short)

        weekly_exit_long = weekly_flip_down & daily_bear
        weekly_exit_short = weekly_flip_up & daily_bull

        exit_long = (weekly_exit_long | (loss_long & ~trend_protect_long) | overbought_reversal | emergency_long | panic_long).fillna(False)
        exit_short = (weekly_exit_short | (loss_short & ~trend_protect_short) | oversold_reversal | emergency_short | panic_short).fillna(False)

        dataframe.loc[exit_long, "exit_long"] = 1
        dataframe.loc[exit_short, "exit_short"] = 1

        return dataframe

    def _l12_clip(self, v: float, lo: float, hi: float) -> float:
        try:
            return float(np.clip(float(v), float(lo), float(hi)))
        except Exception:
            return float(lo)

    def _l12_peak_profit(self, trade: Trade, current_rate: float) -> float:
        try:
            open_rate = float(getattr(trade, "open_rate", 0.0) or 0.0)
            if open_rate <= 0.0:
                return 0.0
            if bool(getattr(trade, "is_short", False)):
                best_rate = float(getattr(trade, "min_rate", None) or current_rate)
                return (open_rate - best_rate) / open_rate
            best_rate = float(getattr(trade, "max_rate", None) or current_rate)
            return (best_rate - open_rate) / open_rate
        except Exception:
            return 0.0

    def _l12_hold_risk(self, is_short: bool, dd: float, rsi: float, adx: float, chop: float, atr_pct: float) -> float:
        dd_risk = self._l12_clip(dd, 0.0, 1.0)
        adx_weak = self._l12_clip((20.0 - float(adx)) / 12.0, 0.0, 1.0)
        chop_risk = 0.0
        try:
            if float(chop) > 0.0:
                chop_risk = self._l12_clip((float(chop) - 55.0) / 15.0, 0.0, 1.0)
        except Exception:
            chop_risk = 0.0
        atr_risk = 0.0
        try:
            if float(atr_pct) > 0.0:
                atr_risk = self._l12_clip((float(atr_pct) - 0.010) / 0.020, 0.0, 1.0)
        except Exception:
            atr_risk = 0.0

        if is_short:
            rsi_risk = self._l12_clip((40.0 - float(rsi)) / 20.0, 0.0, 1.0)
        else:
            rsi_risk = self._l12_clip((float(rsi) - 60.0) / 20.0, 0.0, 1.0)

        risk = 0.45 * dd_risk + 0.20 * rsi_risk + 0.15 * chop_risk + 0.10 * adx_weak + 0.10 * atr_risk
        return self._l12_clip(float(risk), 0.0, 1.0)

    def _l12_trade_value(self, trade: Trade, current_rate: float) -> float:
        try:
            amt = getattr(trade, "amount", None)
            if amt is not None:
                v = abs(float(amt)) * float(current_rate)
                if np.isfinite(v) and v > 0.0:
                    return float(v)
        except Exception:
            pass
        try:
            stake_amt = float(getattr(trade, "stake_amount", 0.0) or 0.0)
            return float(stake_amt) if np.isfinite(stake_amt) and stake_amt > 0.0 else 0.0
        except Exception:
            return 0.0

    def adjust_trade_position(
        self,
        trade: Trade,
        current_time,
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
        if (not bool(getattr(self, "_exit_l1_enabled", False))) and (not bool(getattr(self, "_exit_l2_enabled", False))):
            return None
        if current_profit is None:
            return None

        pair = str(getattr(trade, "pair", "") or "")
        if not pair:
            return None

        ts = pd.Timestamp(current_time)
        if ts.tz is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        now_s = int(ts.timestamp())

        last_s = self._l12_last_reduce_ts_by_pair.get(pair)
        cooldown = int(getattr(self, "_exit_l12_cooldown_sec", 0) or 0)
        if last_s is not None and cooldown > 0 and (now_s - int(last_s)) < cooldown:
            return None

        dataframe = None
        if getattr(self, "dp", None) is not None:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty or "date" not in dataframe.columns:
            return None

        df = dataframe.loc[pd.to_datetime(dataframe["date"], utc=True, errors="coerce") < ts]
        if df.empty:
            return None
        row = df.iloc[-1]

        close = float(row.get("close", current_rate) or current_rate)
        atr_h = float(row.get("atr_h", 0.0) or 0.0)
        atr_pct = (atr_h / close) if close > 0.0 else 0.0
        rsi_h = float(row.get("rsi_h", 50.0) or 50.0)
        adx_h = float(row.get("adx_h", 0.0) or 0.0)
        chop_h = float(row.get("chop_h", 0.0) or 0.0)

        peak_profit = float(self._l12_peak_profit(trade, current_rate))
        if peak_profit < float(getattr(self, "_exit_l12_min_peak_profit", 0.0) or 0.0):
            return None

        dd = (peak_profit - float(current_profit)) / max(peak_profit, 1e-9)
        dd = self._l12_clip(dd, 0.0, 1.0)
        if dd < float(getattr(self, "_exit_l12_min_dd", 0.0) or 0.0):
            return None

        is_short = bool(getattr(trade, "is_short", False))
        risk = float(self._l12_hold_risk(is_short, dd, rsi_h, adx_h, chop_h, atr_pct))

        regime_is_trend = adx_h > float(self.mr_adx_max.value)
        thr_adj = float(self._l12_thr_shift(row=row, regime_is_trend=bool(regime_is_trend), atr_pct=float(atr_pct)))
        l1_thr = float(getattr(self, "_exit_l1_risk_thr", 0.0) or 0.0) + thr_adj
        l2_thr = float(getattr(self, "_exit_l2_risk_thr", 0.0) or 0.0) + thr_adj

        level = None
        reduce_frac = 0.0
        if bool(getattr(self, "_exit_l2_enabled", False)) and float(current_profit) >= float(getattr(self, "_exit_l2_min_profit", 0.0) or 0.0) and risk >= l2_thr:
            level = "l2"
            reduce_frac = float(getattr(self, "_exit_l2_reduce_frac", 0.0) or 0.0)
        elif bool(getattr(self, "_exit_l1_enabled", False)) and float(current_profit) >= float(getattr(self, "_exit_l1_min_profit", 0.0) or 0.0) and risk >= l1_thr:
            level = "l1"
            reduce_frac = float(getattr(self, "_exit_l1_reduce_frac", 0.0) or 0.0)

        if level is None:
            return None

        reduce_frac = self._l12_clip(reduce_frac, 0.0, 0.95)
        if reduce_frac <= 0.0:
            return None

        trade_value = float(self._l12_trade_value(trade, current_rate))
        if trade_value <= 0.0:
            return None

        reduce_value = float(trade_value * reduce_frac)
        if min_stake is not None:
            try:
                min_stake_v = float(min_stake)
                if (trade_value - reduce_value) < min_stake_v:
                    reduce_value = trade_value - min_stake_v
            except Exception:
                pass

        if reduce_value <= 0.0:
            return None

        self._l12_last_reduce_ts_by_pair[pair] = int(now_s)
        return -float(reduce_value)




    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        if current_profit is None:
            return 1

        open_relative_stop = float(self.stoploss)

        enter_tag = str(getattr(trade, "enter_tag", "") or "")

        # 均值回归策略使用固定止损
        if enter_tag in ["mr_long", "mr_short"]:
            return -float(self.mr_stop_loss.value)

        if current_profit < 0:
            dataframe = None
            if getattr(self, "dp", None) is not None:
                dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)

            if dataframe is not None and (not dataframe.empty) and ("date" in dataframe.columns):
                df = dataframe
                if not pd.api.types.is_datetime64_any_dtype(df["date"]):
                    df = df.copy()
                    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")

                ct = pd.Timestamp(current_time)
                if ct.tzinfo is None:
                    ct = ct.tz_localize("UTC")
                else:
                    ct = ct.tz_convert("UTC")

                try:
                    tf = str(self.timeframe)
                    if tf.endswith("m"):
                        candle_open = ct.floor(f"{int(tf[:-1])}min")
                    elif tf.endswith("h"):
                        candle_open = ct.floor(f"{int(tf[:-1])}H")
                    elif tf.endswith("d"):
                        candle_open = ct.floor(f"{int(tf[:-1])}D")
                    else:
                        candle_open = ct
                except Exception:
                    candle_open = ct

                df = df.dropna(subset=["date"]).sort_values("date")
                hist = df.loc[df["date"] < candle_open]
                if hist.empty:
                    hist = df.loc[df["date"] <= ct]

                if not hist.empty:
                    row = hist.iloc[-1]
                    close = float(row.get("close", 0.0))
                    ema_short = float(row.get("ema_short_h", 0.0))
                    ema_long = float(row.get("ema_long_h", 0.0))
                    rsi_h = float(row.get("rsi_h", 50.0))
                    atr_h = float(row.get("atr_h", 0.0))
                    atr_ratio = float(row.get("atr_ratio", 1.0))
                    volume_ratio = float(row.get("volume_ratio", 1.0))
                    ema_fast_w = float(row.get("ema_fast_w", 0.0))
                    ema_slow_w = float(row.get("ema_slow_w", 0.0))
                    adx_w = float(row.get("adx_w", 0.0))

                    atr_pct = (atr_h / close) if close > 0 else 0.0

                    if enter_tag in ["panic_long", "panic_short"]:
                        panic_stop = 0.06
                        if atr_pct > 0.0:
                            panic_stop = min(panic_stop, atr_pct * 2.0)
                        open_relative_stop = max(open_relative_stop, -float(panic_stop))

                    loss_gate = max(float(self.loss_gate_min.value), atr_pct * float(self.loss_gate_atr_pct_mult.value))
                    loss_gate = min(loss_gate, float(self.loss_gate_max.value))

                    tighten_trigger = max(float(self.tighten_trigger_min.value), atr_pct * float(self.tighten_trigger_atr_pct_mult.value))

                    tighten_stop = max(float(self.tighten_stop_min.value), atr_pct * float(self.tighten_stop_atr_pct_mult.value))
                    tighten_stop = min(tighten_stop, float(self.tighten_stop_max.value))

                    loss_cut_gate = max(float(self.loss_cut_min.value), atr_pct * float(self.loss_cut_atr_pct_mult.value))
                    loss_cut_gate = min(loss_cut_gate, float(self.loss_cut_max.value))

                    weekly_up = (ema_fast_w > ema_slow_w) and (adx_w > float(self.weekly_adx_threshold.value))
                    weekly_down = (ema_fast_w < ema_slow_w) and (adx_w > float(self.weekly_adx_threshold.value))

                    buf_mult = float(self.exit_atr_buffer_mult.value)
                    ema_long_dn = ema_long - (atr_h * buf_mult)
                    ema_long_up = ema_long + (atr_h * buf_mult)

                    trend_protect_long = weekly_up and (close > ema_long_dn) and (rsi_h > 35)
                    trend_protect_short = weekly_down and (close < ema_long_up) and (rsi_h < 65)

                    # 新增：无条件ATR硬止损（品种自适应核心）
                    # 即使在趋势保护下，也不允许单笔亏损超过 N * ATR 或 12%
                    # 修复SOL等高波动币种在趋势中暴跌导致20%+亏损的问题
                    hard_stop_pct = atr_pct * float(self.unconditional_atr_stop_mult.value)
                    hard_stop_pct = min(hard_stop_pct, float(self.loss_gate_max.value))
                    open_relative_stop = max(open_relative_stop, -hard_stop_pct)

                    if bool(getattr(trade, "is_short", False)):
                        if (current_profit <= -tighten_trigger) and (volume_ratio > 2.0) and (atr_ratio > 0.9) and (close > ema_long_up):
                            open_relative_stop = max(open_relative_stop, -tighten_stop)
                        if (not trend_protect_short) and (current_profit <= -loss_cut_gate):
                            open_relative_stop = max(open_relative_stop, -loss_gate)
                    else:
                        if (current_profit <= -tighten_trigger) and (volume_ratio > 2.0) and (atr_ratio > 0.9) and (close < ema_long_dn):
                            open_relative_stop = max(open_relative_stop, -tighten_stop)
                        if (not trend_protect_long) and (current_profit <= -loss_cut_gate):
                            open_relative_stop = max(open_relative_stop, -loss_gate)
            else:
                if current_profit <= -float(self.loss_cut_min.value):
                    open_relative_stop = max(open_relative_stop, -float(self.loss_gate_min.value))

        sl = float(stoploss_from_open(open_relative_stop, current_profit))
        if sl <= 0.0:
            return 1.0
        return sl

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> Optional[str]:
        if current_profit is None:
            return None

        enter_tag = str(getattr(trade, "enter_tag", "") or "")

        if bool(getattr(self, "_exit_l1_enabled", False)) or bool(getattr(self, "_exit_l2_enabled", False)):
            try:
                ts = pd.Timestamp(current_time)
                if ts.tz is None:
                    ts = ts.tz_localize("UTC")
                else:
                    ts = ts.tz_convert("UTC")
            except Exception:
                ts = pd.Timestamp.utcnow().tz_localize("UTC")

            pair_key = str(getattr(trade, "pair", "") or pair or "")
            if pair_key:
                now_s = int(ts.timestamp())
                last_s = self._l12_last_reduce_ts_by_pair.get(pair_key)
                cooldown = int(getattr(self, "_exit_l12_cooldown_sec", 0) or 0)
                if last_s is None or cooldown <= 0 or (now_s - int(last_s)) >= cooldown:
                    dataframe = None
                    if getattr(self, "dp", None) is not None:
                        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
                    if dataframe is not None and (not dataframe.empty) and ("date" in dataframe.columns):
                        df = dataframe.loc[pd.to_datetime(dataframe["date"], utc=True, errors="coerce") < ts]
                        if not df.empty:
                            row = df.iloc[-1]
                            close = float(row.get("close", current_rate) or current_rate)
                            atr_h = float(row.get("atr_h", 0.0) or 0.0)
                            atr_pct = (atr_h / close) if close > 0.0 else 0.0
                            rsi_h = float(row.get("rsi_h", 50.0) or 50.0)
                            adx_h = float(row.get("adx_h", 0.0) or 0.0)
                            chop_h = float(row.get("chop_h", 0.0) or 0.0)

                            peak_profit = float(self._l12_peak_profit(trade, current_rate))
                            if peak_profit >= float(getattr(self, "_exit_l12_min_peak_profit", 0.0) or 0.0):
                                dd = (peak_profit - float(current_profit)) / max(peak_profit, 1e-9)
                                dd = self._l12_clip(dd, 0.0, 1.0)
                                if dd >= float(getattr(self, "_exit_l12_min_dd", 0.0) or 0.0):
                                    is_short = bool(getattr(trade, "is_short", False))
                                    risk = float(self._l12_hold_risk(is_short, dd, rsi_h, adx_h, chop_h, atr_pct))

                                    regime_is_trend = adx_h > float(self.mr_adx_max.value)
                                    thr_adj = float(self._l12_thr_shift(row=row, regime_is_trend=bool(regime_is_trend), atr_pct=float(atr_pct)))
                                    l1_thr = float(getattr(self, "_exit_l1_risk_thr", 0.0) or 0.0) + thr_adj
                                    l2_thr = float(getattr(self, "_exit_l2_risk_thr", 0.0) or 0.0) + thr_adj

                                    level = None
                                    if (
                                        bool(getattr(self, "_exit_l2_enabled", False))
                                        and float(current_profit) >= float(getattr(self, "_exit_l2_min_profit", 0.0) or 0.0)
                                        and risk >= l2_thr
                                    ):
                                        level = "l2"
                                    elif (
                                        bool(getattr(self, "_exit_l1_enabled", False))
                                        and float(current_profit) >= float(getattr(self, "_exit_l1_min_profit", 0.0) or 0.0)
                                        and risk >= l1_thr
                                    ):
                                        level = "l1"

                                    if level is not None:
                                        self._l12_last_reduce_ts_by_pair[pair_key] = int(now_s)
                                        return f"l12_{level}_exit"

        # Optimization: Skip if profit is positive and not a Mean Reversion trade
        if current_profit >= 0 and enter_tag not in ["mr_long", "mr_short"]:
            return None

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None

        df = dataframe.loc[dataframe["date"] <= current_time]
        if df.empty:
            return None

        row = df.iloc[-1]

        # 1. Mean Reversion Logic (Profit Taking)
        if enter_tag == "mr_long" or enter_tag == "mr_short":
            # Target Profit
            if current_profit >= float(self.mr_profit_target.value):
                 return f"mr_profit_target_{enter_tag}"
            
            # BB Midband
            bb_mid = float(row.get("mr_bb_middle", 0.0))
            if enter_tag == "mr_long":
                if current_rate >= bb_mid:
                    return "mr_long_exit_midband"
            elif enter_tag == "mr_short":
                if current_rate <= bb_mid:
                    return "mr_short_exit_midband"

        if current_profit >= 0:
            return None

        close = float(row.get("close", 0.0))
        ema_short = float(row.get("ema_short_h", 0.0))
        ema_long = float(row.get("ema_long_h", 0.0))
        rsi_h = float(row.get("rsi_h", 50.0))
        atr_h = float(row.get("atr_h", 0.0))
        atr_ratio = float(row.get("atr_ratio", 1.0))

        atr_pct = (atr_h / close) if close > 0 else 0.0

        struct_gate = max(float(self.struct_profit_thr.value), atr_pct * float(self.struct_atr_pct_mult.value))
        struct_gate = min(struct_gate, 0.06)
        time_gate = max(float(self.time_vol_profit_thr.value), atr_pct * float(self.time_vol_atr_pct_mult.value))
        time_gate = min(time_gate, 0.06)

        loss_cut_gate = max(float(self.loss_cut_min.value), atr_pct * float(self.loss_cut_atr_pct_mult.value))
        loss_cut_gate = min(loss_cut_gate, float(self.loss_cut_max.value))

        time_cut_gate = max(float(self.time_cut_min.value), atr_pct * float(self.time_cut_atr_pct_mult.value))
        time_cut_gate = min(time_cut_gate, float(self.time_cut_max.value))
        time_cut_hours = float(self.time_cut_hours.value)

        dd_cut_gate = max(float(self.dd_cut_min.value), atr_pct * float(self.dd_cut_atr_pct_mult.value))
        dd_cut_gate = min(dd_cut_gate, float(self.dd_cut_max.value))

        donchian_lower = float(row.get("donchian_lower_h", 0.0))
        donchian_upper = float(row.get("donchian_upper_h", 0.0))
        donchian_mid = (donchian_upper + donchian_lower) / 2.0 if (donchian_upper > 0 and donchian_lower > 0) else 0.0

        ema_fast_w = float(row.get("ema_fast_w", 0.0))
        ema_slow_w = float(row.get("ema_slow_w", 0.0))
        adx_w = float(row.get("adx_w", 0.0))
        ma_fast_d = float(row.get("ma_cross_fast_d", 0.0))
        ma_slow_d = float(row.get("ma_cross_slow_d", 0.0))

        close_1 = float(df["close"].iloc[-2]) if len(df) >= 2 else close
        close_2 = float(df["close"].iloc[-3]) if len(df) >= 3 else close_1
        down_2 = (close < close_1) and (close_1 < close_2)
        up_2 = (close > close_1) and (close_1 > close_2)

        weekly_up = (ema_fast_w > ema_slow_w) and (adx_w > float(self.weekly_adx_threshold.value))
        weekly_down = (ema_fast_w < ema_slow_w) and (adx_w > float(self.weekly_adx_threshold.value))

        daily_bear = ma_fast_d < ma_slow_d
        daily_bull = ma_fast_d > ma_slow_d

        buf_mult = float(self.exit_atr_buffer_mult.value)
        ema_long_dn = ema_long - (atr_h * buf_mult)
        ema_long_up = ema_long + (atr_h * buf_mult)

        trend_protect_long = weekly_up and (close > ema_long_dn) and (rsi_h > 35)
        trend_protect_short = weekly_down and (close < ema_long_up) and (rsi_h < 65)

        struct_k = float(self.struct_atr_mult.value)
        struct_ar = float(self.struct_atr_ratio_thr.value)
        time_h = int(self.time_vol_hours.value)

        age_hours = (current_time - trade.open_date_utc).total_seconds() / 3600.0

        # 品种自适应：无条件ATR止损
        # 无论任何指标状态，只要亏损超过 N * ATR，立即离场
        # 这对高波动币种（如SOL）特别有效，能根据其实际波动率设定合理的底线
        # 增加上限保护：最大不超过12%（防止ATR暴涨导致止损过宽）
        atr_stop_pct = atr_pct * float(self.unconditional_atr_stop_mult.value)
        atr_stop_pct = min(atr_stop_pct, 0.12)
        if current_profit <= -atr_stop_pct:
            return "atr_stop_adaptive"

        if not bool(getattr(trade, "is_short", False)):
            if (current_profit <= -struct_gate) and (not trend_protect_long):
                if (close < (ema_long - atr_h * struct_k)) and (atr_ratio > struct_ar):
                    return "struct_cut_long"
                if (donchian_lower > 0.0) and (close < donchian_lower):
                    return "channel_break_long"
                if (donchian_mid > 0.0) and (close < donchian_mid) and (atr_ratio > struct_ar):
                    return "mid_break_long"

            if (current_profit <= -time_gate) and (age_hours >= time_h) and (atr_ratio > struct_ar) and (close < ema_short) and (not trend_protect_long):
                return "time_vol_cut_long"

            if current_profit <= -dd_cut_gate:
                return "dd_cut_long"

            if (current_profit <= -time_cut_gate) and (age_hours >= time_cut_hours) and (close < ema_long) and (not trend_protect_long):
                return "time_cut_long"

            accel_cut = down_2 and (close < ema_short) and (close < ema_long) and (atr_ratio > 1.08)
            weak_cut = daily_bear and (close < ema_long_dn) and (not trend_protect_long)
            if (current_profit <= -loss_cut_gate) and (accel_cut or weak_cut):
                return "loss_cut_long"
            return None

        if bool(getattr(trade, "is_short", False)):
            dump_gate = max(0.05, atr_pct * 1.6)
            dump_ar = max(struct_ar, 1.08)
            if (current_profit <= -dump_gate) and (atr_ratio > dump_ar) and (close > ema_short) and (not trend_protect_short):
                return "dump_cut_short"

            if (current_profit <= -struct_gate) and (not trend_protect_short):
                if (close > (ema_long + atr_h * struct_k)) and (atr_ratio > struct_ar):
                    return "struct_cut_short"
                if (donchian_upper > 0.0) and (close > donchian_upper):
                    return "channel_break_short"
                if (donchian_mid > 0.0) and (close > donchian_mid) and (atr_ratio > struct_ar):
                    return "mid_break_short"

            if (current_profit <= -time_gate) and (age_hours >= time_h) and (atr_ratio > struct_ar) and (close > ema_short) and (not trend_protect_short):
                return "time_vol_cut_short"

            if current_profit <= -dd_cut_gate:
                return "dd_cut_short"

            if (current_profit <= -time_cut_gate) and (age_hours >= time_cut_hours) and (close > ema_long) and (not trend_protect_short):
                return "time_cut_short"

            accel_cut = up_2 and (close > ema_short) and (close > ema_long) and (atr_ratio > 1.08)
            weak_cut = daily_bull and (close > ema_long_up) and (not trend_protect_short)
            if (current_profit <= -loss_cut_gate) and (accel_cut or weak_cut):
                return "loss_cut_short"
            return None

        return None


    @property
    def plot_config(self):
        return {
            "main_plot": {
                "ema_short_h": {"color": "blue"},
                "ema_long_h": {"color": "red"},
                "donchian_upper_h": {"color": "green"},
                "donchian_lower_h": {"color": "red"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "purple"}},
                "Regime": {
                    "trend_long": {"color": "green", "type": "bar"},
                    "trend_short": {"color": "red", "type": "bar"},
                }
            }
        }
