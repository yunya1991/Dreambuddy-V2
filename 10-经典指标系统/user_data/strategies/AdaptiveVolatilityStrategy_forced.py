# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from pandas import DataFrame
from typing import Optional, Dict, Any

import os
import requests
from urllib.parse import urlparse

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade
from freqtrade.enums import RunMode

import talib.abstract as ta
from technical import qtpylib


class MarketRegimeControlModule:
    """
    现货专用市场状态控制模块（可复用在任何现货多头策略）
    - BTC日线MA5连续2日下行 → 全局禁开48小时
    - 底部信号 ≥2 → 允许开仓4小时（信号增强则循环）
    - 顶部信号 ≥2 → 强制平仓 + 禁开时间递增（8→24→48→72小时）
    """
    def __init__(self):
        self.ban_until: Optional[datetime] = None
        self.allow_window_until: Optional[datetime] = None
        self.top_conditions_count: int = 0
        self.bottom_conditions_count: int = 0

    def _get_closed_btc_daily(self, dp) -> DataFrame:
        """安全获取BTC日线数据（Gate.io现货格式 BTC/USDT）"""
        try:
            btc_1d = dp.get_pair_dataframe("BTC/USDT", "1d")
            if len(btc_1d) < 61:
                return pd.DataFrame()
            return btc_1d.iloc[:-1].copy()  # 只用已闭合日线
        except Exception:
            return pd.DataFrame()

    def update_regime(self, dp, current_time: datetime) -> Dict:
        btc_closed = self._get_closed_btc_daily(dp)
        if btc_closed.empty or len(btc_closed) < 60:
            return {'can_enter': True, 'force_exit': False, 'reason': 'BTC日线数据不足'}

        try:
            latest = btc_closed.iloc[-1]
            prev = btc_closed.iloc[-2]

            # 计算指标
            btc_closed['ma5'] = ta.SMA(btc_closed, timeperiod=5)
            btc_closed['ma5_slope'] = btc_closed['ma5'].diff(1)
            btc_closed['ema5'] = ta.EMA(btc_closed, timeperiod=5)
            btc_closed['bb_upper'], _, btc_closed['bb_lower'] = ta.BBANDS(btc_closed['close'], timeperiod=20)
            btc_closed['rsi'] = ta.RSI(btc_closed, timeperiod=14)
            btc_closed['price_ema5_dev_pct'] = (btc_closed['close'] - btc_closed['ema5']) / btc_closed['ema5'] * 100

            support = btc_closed['low'].rolling(50).min().iloc[-1]
            resistance = btc_closed['high'].rolling(50).max().iloc[-1]

            recent = btc_closed[-60:]
            wave_high = recent['high'].max()
            wave_low = recent['low'].min()
            diff = wave_high - wave_low if wave_high > wave_low else 0.000001
            fib_bottom = [wave_high - diff * r for r in [0.236, 0.382, 0.5, 0.618, 0.786]]
            fib_top = [wave_high + diff * r for r in [0.272, 0.618, 1.0]]

            # 1. 空头趋势禁开
            if pd.notna(latest['ma5_slope']) and pd.notna(prev['ma5_slope']) and latest['ma5_slope'] < 0 and prev['ma5_slope'] < 0:
                if self.ban_until is None or current_time > self.ban_until:
                    self.ban_until = current_time + timedelta(hours=48)
                    self.allow_window_until = None
                    self.top_conditions_count = 0
                    self.bottom_conditions_count = 0
                return {'can_enter': False, 'force_exit': False, 'reason': 'BTC MA5连续2日下行，禁开48小时'}

            # 2. 顶部见顶信号
            top_conditions = 0
            if latest['close'] >= latest['bb_upper'] * 0.99:
                top_conditions += 1
            if latest['rsi'] >= 70:
                top_conditions += 1
            if latest['price_ema5_dev_pct'] >= 10.0:
                top_conditions += 1
            if pd.notna(resistance) and latest['close'] >= resistance * 0.99:
                top_conditions += 1
            if any(abs(latest['close'] - fib) / fib <= 0.01 for fib in fib_top if pd.notna(fib)):
                top_conditions += 1

            if top_conditions >= 2:
                if top_conditions > self.top_conditions_count:
                    ban_hours = {2: 8, 3: 24, 4: 48, 5: 72}.get(top_conditions, 72)
                    self.ban_until = current_time + timedelta(hours=ban_hours)
                    self.allow_window_until = None
                    self.top_conditions_count = top_conditions
                return {'can_enter': False, 'force_exit': True, 'reason': f'顶部信号{top_conditions}个，强制平仓'}

            # 3. 底部允许开仓
            bottom_conditions = 0
            if latest['close'] <= latest['bb_lower'] * 1.01:
                bottom_conditions += 1
            if latest['rsi'] <= 30:
                bottom_conditions += 1
            if latest['price_ema5_dev_pct'] <= -10.0:
                bottom_conditions += 1
            if pd.notna(support) and latest['close'] <= support * 1.01:
                bottom_conditions += 1
            if any(abs(latest['close'] - fib) / fib <= 0.01 for fib in fib_bottom if pd.notna(fib)):
                bottom_conditions += 1

            if bottom_conditions >= 2:
                if self.allow_window_until and current_time < self.allow_window_until:
                    return {'can_enter': True, 'force_exit': False, 'reason': '底部窗口内'}

                if (self.allow_window_until is None or current_time >= self.allow_window_until + timedelta(hours=8)):
                    if bottom_conditions > self.bottom_conditions_count:
                        self.allow_window_until = current_time + timedelta(hours=4)
                        self.bottom_conditions_count = bottom_conditions
                        return {'can_enter': True, 'force_exit': False, 'reason': '底部信号增强，新开4小时窗口'}

            return {'can_enter': False, 'force_exit': False, 'reason': '无有效信号'}

        except Exception:
            return {'can_enter': True, 'force_exit': False, 'reason': '模块异常，安全模式允许开仓'}


class Bot2Strategy(IStrategy):
    """
    Bot2Strategy (Fully Fixed & Optimized Version)
    Dual-mode strategy: Range (mean-reversion) + Trend following
    Based on BTC volatility regime + Market Regime Control
    """
    INTERFACE_VERSION = 3

    timeframe = "5m"
    can_short: bool = False

    minimal_roi = {
        "0": 0.098,
        "65": 0.024,
        "138": 0.020,
        "208": 0.00,
    }

    stoploss = -0.105
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    startup_candle_count: int = 200

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

    # Hyperopt parameters
    buy_ema_fast_period = IntParameter(10, 30, default=28, space="buy")
    buy_ema_slow_period = IntParameter(40, 80, default=45, space="buy")
    buy_ema_trend_period = IntParameter(150, 250, default=213, space="buy")
    buy_rsi_range = IntParameter(10, 40, default=14, space="buy")
    buy_mr_ema_dev = DecimalParameter(0.005, 0.03, default=0.029, decimals=3, space="buy")
    buy_adx_trend = IntParameter(15, 40, default=36, space="buy")
    buy_volume_factor = DecimalParameter(1.0, 3.0, default=1.84, decimals=2, space="buy")
    buy_vol_threshold = DecimalParameter(0.01, 0.05, default=0.012, decimals=3, space="buy")

    sell_rsi_range = IntParameter(40, 80, default=70, space="sell")
    sell_rsi_trend = IntParameter(50, 90, default=70, space="sell")
    sell_atr_mult = DecimalParameter(1.0, 4.0, default=2.0, decimals=2, space="sell")

    # === 新增：追涨过滤 Hyperopt 参数 ===
    anti_chase_max_dev = DecimalParameter(0.08, 0.25, default=0.111, decimals=3, space="buy")
    anti_chase_max_rsi = IntParameter(65, 80, default=73, space="buy")
    anti_chase_bb_percent = DecimalParameter(0.90, 0.98, default=0.95, decimals=2, space="buy")
    anti_chase_adx_slope_min = DecimalParameter(-5.0, 0.0, default=-3.0, decimals=1, space="buy")
    anti_chase_recent_pump_max = DecimalParameter(0.05, 0.15, default=0.10, decimals=2, space="buy")
    anti_chase_lookback = IntParameter(12, 48, default=32, space="buy")  # 1~4小时

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # 嵌入市场状态控制模块
        self.regime_control = MarketRegimeControlModule()

    def informative_pairs(self):
        # 声明BTC日线数据（现货格式 BTC/USDT）
        return [("BTC/USDT", "1d")]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Main 5m indicators
        dataframe["rsi"] = ta.RSI(dataframe)

        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=self.buy_ema_fast_period.value)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=self.buy_ema_slow_period.value)
        dataframe["ema_trend"] = ta.EMA(dataframe, timeperiod=self.buy_ema_trend_period.value)

        bollinger = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe["bb_lower"] = bollinger["lower"]
        dataframe["bb_mid"] = bollinger["mid"]
        dataframe["bb_upper"] = bollinger["upper"]

        dataframe["adx"] = ta.ADX(dataframe)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["volume_mean"] = dataframe["volume"].rolling(50).mean()

        # 🔧 修复：BTC 4h volatility regime
        try:
            btc_df = self.dp.get_pair_dataframe(pair="BTC/USDT", timeframe="4h")
            if btc_df is not None and not btc_df.empty and len(btc_df) > 20:
                btc_df["btc_atr_4h"] = ta.ATR(btc_df, timeperiod=14)
                btc_df["btc_volatility_4h"] = btc_df["btc_atr_4h"] / btc_df["close"]
                btc_df = btc_df[["date", "btc_volatility_4h"]].copy()

                dataframe = merge_informative_pair(
                    dataframe,
                    btc_df,
                    self.timeframe,
                    "4h",
                    ffill=True
                )

                if 'btc_volatility_4h_4h' in dataframe.columns:
                    dataframe.rename(columns={'btc_volatility_4h_4h': 'btc_volatility_4h'}, inplace=True)
                elif 'btc_volatility_4h' not in dataframe.columns:
                    dataframe['btc_volatility_4h'] = 0.0
            else:
                dataframe['btc_volatility_4h'] = 0.0
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"BTC volatility calculation failed: {e}")
            dataframe['btc_volatility_4h'] = 0.0

        if 'btc_volatility_4h' not in dataframe.columns:
            dataframe['btc_volatility_4h'] = 0.0

        dataframe['btc_volatility_4h'] = dataframe['btc_volatility_4h'].fillna(0.0)

        # Regime classification
        vol_threshold = self.buy_vol_threshold.value
        dataframe["regime_trend"] = (dataframe["btc_volatility_4h"] >= vol_threshold).astype(int)

        # === 追涨过滤模块所需指标 ===
        dataframe["adx_slope"] = dataframe["adx"].diff(3)

        dataframe["bb_percent"] = (dataframe["close"] - dataframe["bb_lower"]) / (dataframe["bb_upper"] - dataframe["bb_lower"])

        lookback = self.anti_chase_lookback.value
        dataframe["max_high_lookback"] = dataframe["high"].rolling(lookback).max()
        dataframe["recent_pump"] = (dataframe["close"] / dataframe["max_high_lookback"].shift(1)) - 1

        # 安全处理 NaN
        dataframe["adx_slope"] = dataframe["adx_slope"].fillna(0)
        dataframe["bb_percent"] = dataframe["bb_percent"].fillna(0.5)
        dataframe["recent_pump"] = dataframe["recent_pump"].fillna(0.0)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        dataframe["regime_can_enter"] = 1
        dataframe["regime_force_exit"] = 0
        dataframe["regime_top_conditions"] = 0
        dataframe["regime_bottom_conditions"] = 0

        # 市场状态控制检查
        current_time = datetime.utcnow()
        regime = self.regime_control.update_regime(self.dp, current_time)
        try:
            dataframe["regime_can_enter"] = int(bool(regime.get("can_enter", True)))
            dataframe["regime_force_exit"] = int(bool(regime.get("force_exit", False)))
            dataframe["regime_top_conditions"] = float(getattr(self.regime_control, "top_conditions_count", 0) or 0)
            dataframe["regime_bottom_conditions"] = float(getattr(self.regime_control, "bottom_conditions_count", 0) or 0)
        except Exception:
            pass
        if not regime['can_enter']:
            if hasattr(self, 'logger'):
                self.logger.info(f"禁止开仓: {regime['reason']}")
            return dataframe

        # Mean-reversion conditions
        mr_cond1 = dataframe["close"] < dataframe["bb_lower"]
        mr_cond2 = dataframe["rsi"] < self.buy_rsi_range.value
        mr_cond3 = dataframe["close"] < dataframe["ema_fast"] * (1 - self.buy_mr_ema_dev.value)
        dataframe["mr_score"] = mr_cond1.astype(int) + mr_cond2.astype(int) + mr_cond3.astype(int)

        # Trend following conditions
        trend_cond1 = (
            (dataframe["close"] > dataframe["ema_fast"]) &
            (dataframe["ema_fast"] > dataframe["ema_slow"]) &
            (dataframe["ema_slow"] > dataframe["ema_trend"])
        )
        trend_cond2 = dataframe["adx"] > self.buy_adx_trend.value
        trend_cond3 = dataframe["volume"] > dataframe["volume_mean"] * self.buy_volume_factor.value
        dataframe["trend_score"] = trend_cond1.astype(int) + trend_cond2.astype(int) + trend_cond3.astype(int)

        range_entry = (dataframe["regime_trend"] == 0) & (dataframe["mr_score"] >= 2) & (dataframe["volume"] > 0)
        trend_entry = (dataframe["regime_trend"] == 1) & (dataframe["trend_score"] >= 2) & (dataframe["volume"] > 0)

        initial_entry = range_entry | trend_entry

        # === 追涨过滤模块：任意一个条件触发即禁止开仓 ===
        try:
            anti_chase_conditions = [
                dataframe["close"] > dataframe["ema_trend"] * (1 + self.anti_chase_max_dev.value),
                dataframe["rsi"] >= self.anti_chase_max_rsi.value,
                dataframe["bb_percent"] >= self.anti_chase_bb_percent.value,
                dataframe["adx_slope"] < self.anti_chase_adx_slope_min.value,
                dataframe["recent_pump"] >= self.anti_chase_recent_pump_max.value,
            ]
            chase_risk = pd.concat(anti_chase_conditions, axis=1).any(axis=1)
            chase_risk = chase_risk.fillna(False)
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.warning(f"Anti-chase calculation error for {metadata['pair']}: {e}")
            chase_risk = pd.Series(False, index=dataframe.index)

        entry_mask = initial_entry & ~chase_risk
        dataframe.loc[entry_mask, "enter_long"] = 1
        dataframe.loc[entry_mask & range_entry, "enter_tag"] = "range_entry"
        dataframe.loc[entry_mask & trend_entry, "enter_tag"] = "trend_entry"

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

            decision_url = _normalize_signals_url(os.environ.get("ML_EXPORT_URL", ""))
            if decision_url:
                row = dataframe.iloc[-1]
                enter_now = int(row.get("enter_long", 0) or 0) == 1
                if enter_now:
                        pair = metadata.get("pair")
                        if pair:
                            ts_ms = None
                            try:
                                if "date" in row and row.get("date") is not None:
                                    dt = pd.to_datetime(row.get("date"), utc=True, errors="coerce")
                                    if dt is not None and (not pd.isna(dt)):
                                        ts_ms = int(pd.Timestamp(dt).timestamp() * 1000)
                            except Exception:
                                ts_ms = None
                            if ts_ms is None:
                                try:
                                    if isinstance(row.name, pd.Timestamp):
                                        ts_ms = int(pd.Timestamp(row.name).timestamp() * 1000)
                                except Exception:
                                    ts_ms = None

                            if ts_ms is not None:
                                last_map = getattr(self, "_ml_export_last_ts_by_pair", None)
                                if not isinstance(last_map, dict):
                                    last_map = {}
                                    setattr(self, "_ml_export_last_ts_by_pair", last_map)
                                last_ts = last_map.get(pair)
                                if last_ts is None or int(ts_ms) > int(last_ts):
                                    tf = str(getattr(self, "timeframe", "5m") or "5m").lower().strip()
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
                                    bar_closed = bool(tf_ms > 0 and now_ms >= int(ts_ms) + int(tf_ms) - 2_000)
                                    if bar_closed:
                                        tag = row.get("enter_tag")
                                        if tag is None or (pd is not None and pd.isna(tag)):
                                            tag = None
                                        else:
                                            tag = str(tag)

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

                                        close_v = _sf(row.get("close", 0.0) or 0.0)
                                        atr_v = _sf(row.get("atr", 0.0) or 0.0)
                                        features: Dict[str, float] = {
                                            "close": close_v,
                                            "volume": _sf(row.get("volume", 0.0) or 0.0),
                                            "rsi": _sf(row.get("rsi", 0.0) or 0.0),
                                            "ema_fast": _sf(row.get("ema_fast", 0.0) or 0.0),
                                            "ema_slow": _sf(row.get("ema_slow", 0.0) or 0.0),
                                            "ema_trend": _sf(row.get("ema_trend", 0.0) or 0.0),
                                            "adx": _sf(row.get("adx", 0.0) or 0.0),
                                            "atr": atr_v,
                                            "atr_pct": (atr_v / close_v) if close_v > 0.0 else 0.0,
                                            "btc_volatility_4h": _sf(row.get("btc_volatility_4h", 0.0) or 0.0),
                                            "regime_trend": _sf(row.get("regime_trend", 0.0) or 0.0),
                                            "mr_score": _sf(row.get("mr_score", 0.0) or 0.0),
                                            "trend_score": _sf(row.get("trend_score", 0.0) or 0.0),
                                            "bb_percent": _sf(row.get("bb_percent", 0.0) or 0.0),
                                            "adx_slope": _sf(row.get("adx_slope", 0.0) or 0.0),
                                            "recent_pump": _sf(row.get("recent_pump", 0.0) or 0.0),
                                        }

                                        payload: Dict[str, Any] = {
                                            "venue": "freqtrade",
                                            "pair": str(pair),
                                            "side": "long",
                                            "action": "open",
                                            "timeframe": tf,
                                            "ts": int(ts_ms),
                                            "bar_open_ms": int(ts_ms),
                                            "bar_close_ms": int(ts_ms) + int(tf_ms),
                                            "bar_closed": True,
                                            "strategy_id": "Bot2Strategy",
                                            "strategy_version": "1.0.0",
                                            "group_id": "adaptive_5m_regime",
                                            "feature_set_id": "adaptive_5m_v1",
                                            "tag": tag,
                                            "confidence": 1.0,
                                            "features": features,
                                        }

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

                                        timeout_s = 0.5
                                        try:
                                            timeout_s = float(str(os.environ.get("ML_EXPORT_TIMEOUT", "0.5") or "0.5").strip() or 0.5)
                                        except Exception:
                                            timeout_s = 0.5
                                        requests.post(decision_url, json=payload, timeout=timeout_s)
                                        last_map[pair] = int(ts_ms)
        except Exception:
            pass

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0

        # Range exit
        range_exit_cond1 = dataframe["rsi"] > self.sell_rsi_range.value
        range_exit_cond2 = dataframe["close"] > dataframe["bb_mid"]
        range_exit_cond3 = dataframe["close"] > dataframe["ema_fast"]
        dataframe["range_exit_score"] = range_exit_cond1.astype(int) + range_exit_cond2.astype(int) + range_exit_cond3.astype(int)

        # Trend exit
        trend_exit_cond1 = dataframe["rsi"] > self.sell_rsi_trend.value
        trend_exit_cond2 = dataframe["close"] < dataframe["ema_fast"]
        trend_exit_cond3 = dataframe["volume"] < dataframe["volume_mean"]
        dataframe["trend_exit_score"] = trend_exit_cond1.astype(int) + trend_exit_cond2.astype(int) + trend_exit_cond3.astype(int)

        range_exit = (dataframe["regime_trend"] == 0) & (dataframe["range_exit_score"] >= 2) & (dataframe["volume"] > 0)
        trend_exit = (dataframe["regime_trend"] == 1) & (dataframe["trend_exit_score"] >= 2) & (dataframe["volume"] > 0)

        dataframe.loc[range_exit | trend_exit, "exit_long"] = 1

        return dataframe

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> float:
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                return self.stoploss

            entry_date = trade.open_date_utc
            if entry_date.tzinfo is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)

            mask = dataframe.index <= entry_date
            if not mask.any():
                return self.stoploss

            entry_candle = dataframe.loc[mask].iloc[-1]
            atr_at_entry = float(entry_candle.get("atr", 0.0))

            if atr_at_entry <= 0:
                return self.stoploss

            sl_atr = self.sell_atr_mult.value * atr_at_entry
            base_sl = max(self.stoploss, -sl_atr / trade.open_rate)

            if current_profit <= 0:
                return base_sl

            sl = base_sl
            if current_profit > 0.03:
                sl = max(sl, -0.01)
            if current_profit > 0.06:
                sl = max(sl, current_profit - 0.03)
            if current_profit > 0.10:
                sl = max(sl, current_profit - 0.05)

            return sl

        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Custom stoploss error for {pair}: {str(e)}")
            return self.stoploss

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, 
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        regime = self.regime_control.update_regime(self.dp, current_time)
        if regime['force_exit']:
            return "regime_force_exit"

        if current_profit > 0.15:
            return "quick_profit_15"
        if current_profit > 0.10:
            return "quick_profit_10"
        if current_profit > 0.05:
            return "quick_profit_5"

        hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hold_hours > 120:
            return "time_exit_profit" if current_profit > 0.03 else "time_exit_loss"
        return None

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                           proposed_stake: float, min_stake: float, max_stake: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        try:
            if getattr(self, 'dp', None) is not None and getattr(self.dp, 'runmode', None) == RunMode.BACKTEST:
                return proposed_stake
        except Exception:
            pass

        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 1:
                return proposed_stake
                
            atr_pct = dataframe['atr'].iloc[-1] / current_rate
            
            total = self.wallets.get_total_stake_amount()
            base = total * 0.02
            
            if atr_pct > 0.04:
                size = base * 0.5
            elif atr_pct > 0.02:
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
        regime = self.regime_control.update_regime(self.dp, current_time)
        if not regime['can_enter']:
            if hasattr(self, 'logger'):
                self.logger.info(f"拒绝开仓 {pair}: {regime['reason']}")
            return False

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if len(dataframe) < 1:
            return False
            
        last = dataframe.iloc[-1]
        
        checks = [
            last.get('volume', 0) > 0,
            last.get('atr', 0) > 0,
            last.get('rsi', 100) < 75,
            last.get('volume', 0) > last.get('volume_mean', 0) * 0.5,
        ]
        
        return all(checks)

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "candles": True,
                "close": {"color": "black"},
                "ema_fast": {"color": "#1f77b4"},
                "ema_slow": {"color": "#ff7f0e"},
                "ema_trend": {"color": "#d62728"},
                "bb_lower": {"color": "gray", "fill_to": "bb_upper"},
                "bb_mid": {"color": "#9467bd"},
                "bb_upper": {"color": "gray"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "#ff7f0e"}},
                "ADX": {"adx": {"color": "#9467bd"}},
                "Volume": {"volume": {"color": "gray", "type": "bar"}, "volume_mean": {"color": "#1f77b4"}},
                "Regime": {"regime_trend": {"color": "#2ca02c", "type": "bar"}},
                "Scores": {
                    "mr_score": {"color": "#2ca02c", "type": "bar"},
                    "trend_score": {"color": "#d62728", "type": "bar"},
                },
            }
        }
