# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from pandas import DataFrame
from typing import Optional, Dict, Any

import os
import requests
from urllib.parse import urlparse

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, merge_informative_pair
from freqtrade.persistence import Trade

import talib.abstract as ta
from technical import qtpylib


class MultiGroupStrategy(IStrategy):
    """
    MultiGroup Spot Strategy (Ultimate Fixed Version)
    - 4H 主周期 + 1D 趋势确认
    - 三组入场逻辑
    - ATR 动态止损 + Break-even + Trailing
    - 专业移动止盈
    """
    INTERFACE_VERSION = 3

    timeframe = "4h"
    can_short: bool = True

    startup_candle_count = 240

    minimal_roi = {
        "0": 0.30,
        "720": 0.15,
        "1440": 0.08,
        "2880": 0
    }
    stoploss = -0.20
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    # 参数
    buy_ema_short = IntParameter(15, 30, default=21, space="buy")
    buy_ema_medium = IntParameter(40, 80, default=55, space="buy")
    buy_ema_long = IntParameter(150, 250, default=200, space="buy")

    buy_rsi_period = IntParameter(10, 20, default=14, space="buy")
    buy_atr_period = IntParameter(10, 20, default=14, space="buy")

    buy_g1_rsi_min = IntParameter(45, 65, default=50, space="buy")
    buy_g2_vol_factor = DecimalParameter(1.2, 2.5, default=1.4, space="buy")
    buy_g3_fastk_min = IntParameter(40, 70, default=50, space="buy")

    sell_rsi_threshold = IntParameter(35, 50, default=40, space="sell")

    def informative_pairs(self):
        """返回1D时间框架的交易对"""
        if not hasattr(self, 'dp') or not hasattr(self.dp, 'current_whitelist'):
            return []
        return [(pair, "1d") for pair in self.dp.current_whitelist()]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        # 4H 主周期指标
        dataframe["ema_short"] = ta.EMA(dataframe, timeperiod=self.buy_ema_short.value)
        dataframe["ema_medium"] = ta.EMA(dataframe, timeperiod=self.buy_ema_medium.value)
        dataframe["ema_long"] = ta.EMA(dataframe, timeperiod=self.buy_ema_long.value)

        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=self.buy_rsi_period.value)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=self.buy_atr_period.value)

        stoch = ta.STOCHRSI(dataframe)
        dataframe["fastk"] = stoch["fastk"]
        dataframe["fastd"] = stoch["fastd"]

        dataframe["volume_mean"] = dataframe["volume"].rolling(20).mean()
        dataframe["recent_low"] = dataframe["low"].rolling(5).min()
        dataframe["recent_high"] = dataframe["high"].rolling(5).max()

        # 🔧 修复：安全的1D数据获取和合并
        try:
            # 方法1：通过dp.get_pair_dataframe获取1D数据
            inf_tf = self.dp.get_pair_dataframe(metadata["pair"], "1d")
            
            if inf_tf is not None and not inf_tf.empty and len(inf_tf) > 50:
                # 复制以避免修改原始数据
                inf_tf = inf_tf.copy()
                
                # 计算1D指标
                inf_tf["ema_medium_1d"] = ta.EMA(inf_tf, timeperiod=self.buy_ema_medium.value)
                inf_tf["ema_long_1d"] = ta.EMA(inf_tf, timeperiod=self.buy_ema_long.value)
                inf_tf["rsi_1d"] = ta.RSI(inf_tf, timeperiod=self.buy_rsi_period.value)
                
                stoch_1d = ta.STOCHRSI(inf_tf)
                inf_tf["fastk_1d"] = stoch_1d["fastk"]
                
                # 合并1D数据
                dataframe = merge_informative_pair(
                    dataframe, 
                    inf_tf, 
                    self.timeframe, 
                    "1d", 
                    ffill=True
                )
                
                # 记录合并成功
                if hasattr(self, 'logger'):
                    self.logger.debug(f"成功合并1D数据: {metadata['pair']}, 列: {list(inf_tf.columns)}")
            else:
                # 创建空的1D列
                if hasattr(self, 'logger'):
                    self.logger.warning(f"1D数据不足: {metadata['pair']}, 长度: {len(inf_tf) if inf_tf is not None else 0}")
                
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"合并1D数据失败: {metadata['pair']}, 错误: {e}")

        # 🔧 修复：确保1D列存在（即使为空）
        required_1d_cols = ["ema_medium_1d", "ema_long_1d", "rsi_1d", "fastk_1d"]
        for col in required_1d_cols:
            if col not in dataframe.columns:
                dataframe[col] = np.nan  # 创建列并填充NaN

        # 初始化标签
        if "enter_tag" not in dataframe.columns:
            dataframe["enter_tag"] = ""
        if "enter_long" not in dataframe.columns:
            dataframe["enter_long"] = 0
        if "enter_short" not in dataframe.columns:
            dataframe["enter_short"] = 0
        if "exit_long" not in dataframe.columns:
            dataframe["exit_long"] = 0
        if "exit_short" not in dataframe.columns:
            dataframe["exit_short"] = 0

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if dataframe.empty:
            return dataframe

        dataframe["enter_long"] = 0
        dataframe["enter_short"] = 0
        dataframe["enter_tag"] = ""

        # 🔧 修复：安全的1D列检查和has_1d计算
        required_1d_cols = ["ema_medium_1d", "ema_long_1d", "rsi_1d", "fastk_1d"]
        
        # 检查列是否存在
        has_required_columns = all(col in dataframe.columns for col in required_1d_cols)
        
        if not has_required_columns:
            # 如果列不存在，使用全False序列
            has_1d = pd.Series(False, index=dataframe.index)
        else:
            # 检查是否有有效数据（非NaN）
            has_1d = (
                dataframe["ema_medium_1d"].notna() &
                dataframe["ema_long_1d"].notna() &
                dataframe["fastk_1d"].notna()
            )
        
        required_cols_for_conditions = [
            "ema_medium", "volume_mean", "recent_low", "recent_high",
            "volume", "ema_short", "fastk", "fastd"
        ]
        
        for col in required_cols_for_conditions:
            if col not in dataframe.columns:
                if hasattr(self, 'logger'):
                    self.logger.error(f"缺少必要列: {col}")
                return dataframe

        g1_1d = (
            has_1d &
            (dataframe["ema_medium_1d"] > dataframe["ema_long_1d"]) &
            (dataframe["close"] > dataframe["ema_medium"]) &
            (dataframe["rsi"] > self.buy_g1_rsi_min.value) &
            (dataframe["volume"] > dataframe["volume_mean"])
        )

        g1_no1d = (
            (~has_1d) &
            (dataframe["close"] > dataframe["ema_medium"]) &
            (dataframe["rsi"] > self.buy_g1_rsi_min.value) &
            (dataframe["volume"] > dataframe["volume_mean"] * 0.8)
        )

        g1 = g1_1d | g1_no1d

        g2_1d = (
            has_1d &
            (dataframe["close"] > dataframe["ema_long_1d"]) &
            (dataframe["low"] < dataframe["recent_low"].shift(1)) &
            (dataframe["close"] > dataframe["recent_low"].shift(1)) &
            (dataframe["volume"] > dataframe["volume_mean"] * self.buy_g2_vol_factor.value)
        )

        g2_no1d = (
            (~has_1d) &
            (dataframe["low"] < dataframe["recent_low"].shift(1)) &
            (dataframe["close"] > dataframe["recent_low"].shift(1)) &
            (dataframe["volume"] > dataframe["volume_mean"] * (float(self.buy_g2_vol_factor.value) * 0.8))
        )

        g2 = g2_1d | g2_no1d

        g3_1d = (
            has_1d &
            (dataframe["fastk_1d"] > self.buy_g3_fastk_min.value) &
            (dataframe["close"] > dataframe["ema_short"]) &
            qtpylib.crossed_above(dataframe["fastk"], dataframe["fastd"])
        )

        g3_no1d = (
            (~has_1d) &
            (dataframe["close"] > dataframe["ema_short"]) &
            qtpylib.crossed_above(dataframe["fastk"], dataframe["fastd"])
        )

        g3 = g3_1d | g3_no1d
        g1_short_1d = (
            has_1d &
            (dataframe["ema_medium_1d"] < dataframe["ema_long_1d"]) &
            (dataframe["close"] < dataframe["ema_medium"]) &
            (dataframe["rsi"] < (100 - self.buy_g1_rsi_min.value)) &
            (dataframe["volume"] > dataframe["volume_mean"])
        )
        g1_short_no1d = (
            (~has_1d) &
            (dataframe["close"] < dataframe["ema_medium"]) &
            (dataframe["rsi"] < (100 - self.buy_g1_rsi_min.value)) &
            (dataframe["volume"] > dataframe["volume_mean"] * 0.8)
        )
        g1_short = g1_short_1d | g1_short_no1d
        g2_short_1d = (
            has_1d &
            (dataframe["close"] < dataframe["ema_long_1d"]) &
            (dataframe["high"] > dataframe["recent_high"].shift(1)) &
            (dataframe["close"] < dataframe["recent_high"].shift(1)) &
            (dataframe["volume"] > dataframe["volume_mean"] * self.buy_g2_vol_factor.value)
        )
        g2_short_no1d = (
            (~has_1d) &
            (dataframe["high"] > dataframe["recent_high"].shift(1)) &
            (dataframe["close"] < dataframe["recent_high"].shift(1)) &
            (dataframe["volume"] > dataframe["volume_mean"] * (float(self.buy_g2_vol_factor.value) * 0.8))
        )
        g2_short = g2_short_1d | g2_short_no1d
        g3_short_1d = (
            has_1d &
            (dataframe["fastk_1d"] < (100 - self.buy_g3_fastk_min.value)) &
            (dataframe["close"] < dataframe["ema_short"]) &
            qtpylib.crossed_below(dataframe["fastk"], dataframe["fastd"])
        )
        g3_short_no1d = (
            (~has_1d) &
            (dataframe["close"] < dataframe["ema_short"]) &
            qtpylib.crossed_below(dataframe["fastk"], dataframe["fastd"])
        )
        g3_short = g3_short_1d | g3_short_no1d

        # 设置入场信号
        dataframe.loc[g1, ["enter_long", "enter_tag"]] = [1, "g1_trend"]
        dataframe.loc[g2, ["enter_long", "enter_tag"]] = [1, "g2_liquidity"]
        dataframe.loc[g3, ["enter_long", "enter_tag"]] = [1, "g3_momentum"]
        dataframe.loc[g1_short, ["enter_short", "enter_tag"]] = [1, "g1_trend_short"]
        dataframe.loc[g2_short, ["enter_short", "enter_tag"]] = [1, "g2_liquidity_short"]
        dataframe.loc[g3_short, ["enter_short", "enter_tag"]] = [1, "g3_momentum_short"]

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
                enter_long_now = int(row.get("enter_long", 0) or 0) == 1
                enter_short_now = int(row.get("enter_short", 0) or 0) == 1
                enter_now = enter_long_now or enter_short_now
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
                                    tf = str(getattr(self, "timeframe", "4h") or "4h").lower().strip()
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
                                        features: Dict[str, Any] = {
                                            "close": close_v,
                                            "volume": _sf(row.get("volume", 0.0) or 0.0),
                                            "rsi": _sf(row.get("rsi", 0.0) or 0.0),
                                            "atr": _sf(row.get("atr", 0.0) or 0.0),
                                            "enter_long": _sf(row.get("enter_long", 0.0) or 0.0),
                                            "enter_short": _sf(row.get("enter_short", 0.0) or 0.0),
                                            "ema_short": _sf(row.get("ema_short", 0.0) or 0.0),
                                            "ema_medium": _sf(row.get("ema_medium", 0.0) or 0.0),
                                            "ema_long": _sf(row.get("ema_long", 0.0) or 0.0),
                                            "fastk": _sf(row.get("fastk", 0.0) or 0.0),
                                            "fastd": _sf(row.get("fastd", 0.0) or 0.0),
                                            "ema_medium_1d": _sf(row.get("ema_medium_1d", 0.0) or 0.0),
                                            "ema_long_1d": _sf(row.get("ema_long_1d", 0.0) or 0.0),
                                            "rsi_1d": _sf(row.get("rsi_1d", 0.0) or 0.0),
                                            "fastk_1d": _sf(row.get("fastk_1d", 0.0) or 0.0),
                                        }
                                        features["atr_pct"] = (features["atr"] / close_v) if close_v > 0.0 else 0.0

                                        payload: Dict[str, Any] = {
                                            "venue": "freqtrade",
                                            "pair": str(pair),
                                            "side": ("short" if enter_short_now else "long"),
                                            "action": "open",
                                            "timeframe": tf,
                                            "ts": int(ts_ms),
                                            "bar_open_ms": int(ts_ms),
                                            "bar_close_ms": int(ts_ms) + int(tf_ms),
                                            "bar_closed": True,
                                            "strategy_id": "MultiGroupStrategy",
                                            "strategy_version": "1.0.0",
                                            "group_id": "trend_4h_mtf",
                                            "feature_set_id": "trend_4h_mtf_v1",
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
        if dataframe.empty:
            return dataframe

        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0

        # 确保必要的列存在
        if "rsi" not in dataframe.columns or "ema_medium" not in dataframe.columns:
            return dataframe

        exit_cond = (
            (dataframe["rsi"] < self.sell_rsi_threshold.value) |
            (dataframe["close"] < dataframe["ema_medium"])
        )
        exit_short_cond = (
            (dataframe["rsi"] > (100 - self.sell_rsi_threshold.value)) |
            (dataframe["close"] > dataframe["ema_medium"])
        )

        dataframe.loc[exit_cond, "exit_long"] = 1
        dataframe.loc[exit_short_cond, "exit_short"] = 1
        return dataframe

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime,
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        """专业移动止盈"""
        if current_profit <= 0:
            return None

        # 安全获取max_profit
        max_profit = getattr(trade, 'max_profit', current_profit)

        # 盈利 > 5%：允许 3% 回撤
        if max_profit > 0.05 and (max_profit - current_profit) > 0.03:
            return "trailing_profit_3pct"

        # 盈利 > 10%：允许 4% 回撤
        if max_profit > 0.10 and (max_profit - current_profit) > 0.04:
            return "trailing_profit_4pct"

        # 盈利 > 20%：允许 6% 回撤
        if max_profit > 0.20 and (max_profit - current_profit) > 0.06:
            return "trailing_profit_6pct"

        return None

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        """动态止损"""
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or len(dataframe) < 20:
                return 1.0  # 使用内置止损

            # 获取入场ATR
            entry_date = trade.open_date_utc
            if entry_date.tzinfo is None:
                entry_date = entry_date.replace(tzinfo=timezone.utc)
            
            mask = dataframe.index <= entry_date
            if not mask.any():
                return 1.0
                
            entry_row = dataframe.loc[mask].iloc[-1]
            
            # 确保atr列存在
            if 'atr' not in entry_row:
                return 1.0
                
            entry_atr = entry_row['atr']
            current_atr = dataframe['atr'].iloc[-1] if 'atr' in dataframe.columns else entry_atr
            is_short = bool(getattr(trade, "is_short", False))

            # 初始止损
            initial_sl_price = (trade.open_rate + (entry_atr * 2.0)) if is_short else (trade.open_rate - (entry_atr * 2.0))
            
            # 如果已跌破初始止损
            if is_short:
                if current_rate >= initial_sl_price:
                    return (current_rate - initial_sl_price) / current_rate
            else:
                if current_rate <= initial_sl_price:
                    return (initial_sl_price - current_rate) / current_rate

            # 保本：盈利1.5%
            if current_profit > 0.015:
                # 移动到开仓价
                return 0.0

            # 追踪：盈利3%
            if current_profit > 0.03:
                trail_distance = current_atr * 1.5
                stop_price = min(current_rate + trail_distance, trade.open_rate) if is_short else max(current_rate - trail_distance, trade.open_rate)
                return ((current_rate - stop_price) / current_rate) if is_short else ((stop_price - current_rate) / current_rate)

            # 默认：初始止损
            return ((current_rate - initial_sl_price) / current_rate) if is_short else ((initial_sl_price - current_rate) / current_rate)

        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Custom stoploss error for {pair}: {e}")
            return 1.0  # 使用内置止损

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        """入场前确认"""
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if len(dataframe) < 1:
                return False
                
            last = dataframe.iloc[-1]
            
            checks = [
                last['volume'] > 0,
                'atr' in last and last['atr'] > 0,
                'volume_mean' in last and last['volume'] > last['volume_mean'] * 0.3,
            ]
            
            return all(checks)
            
        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Confirm trade error: {e}")
            return False

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "close": {"color": "black"},
                "ema_short": {"color": "#1f77b4"},
                "ema_medium": {"color": "#ff7f0e"},
                "ema_long": {"color": "#d62728"},
            },
            "subplots": {
                "RSI": {"rsi": {"color": "#ff7f0e"}},
                "StochRSI": {
                    "fastk": {"color": "#2ca02c"},
                    "fastd": {"color": "#9467bd"}
                },
                "Volume": {
                    "volume": {"color": "gray", "type": "bar"},
                    "volume_mean": {"color": "#1f77b4"}
                },
                "1D Trend": {
                    "ema_medium_1d": {"color": "#ff7f0e", "plotly": {"dash": "dash"}},
                    "ema_long_1d": {"color": "#d62728", "plotly": {"dash": "dash"}},
                    "fastk_1d": {"color": "#2ca02c"}
                },
                "ATR": {"atr": {"color": "#7f7f7f"}}
            }
        }
