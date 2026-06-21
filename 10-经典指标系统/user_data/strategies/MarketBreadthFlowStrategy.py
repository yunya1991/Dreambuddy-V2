# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
import os
import json
import time
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pandas import DataFrame
from typing import Optional, Dict

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
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
            return {
                'can_enter': True,
                'force_exit': False,
                'regime_state': 0,
                'ban_until': self.ban_until,
                'allow_window_until': self.allow_window_until,
                'reason': 'BTC日线数据不足',
            }

        try:
            latest = btc_closed.iloc[-1]
            prev = btc_closed.iloc[-2]

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

            regime_state = 0

            if pd.notna(latest['ma5_slope']) and pd.notna(prev['ma5_slope']) and latest['ma5_slope'] < 0 and prev['ma5_slope'] < 0:
                if self.ban_until is None or current_time > self.ban_until:
                    self.ban_until = current_time + timedelta(hours=48)
                    self.allow_window_until = None
                    self.top_conditions_count = 0
                    self.bottom_conditions_count = 0
                return {
                    'can_enter': False,
                    'force_exit': False,
                    'regime_state': -1,
                    'ban_until': self.ban_until,
                    'allow_window_until': self.allow_window_until,
                    'reason': 'BTC MA5连续2日下行，禁开48小时',
                }

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
                return {
                    'can_enter': False,
                    'force_exit': True,
                    'regime_state': -1,
                    'ban_until': self.ban_until,
                    'allow_window_until': self.allow_window_until,
                    'reason': f'顶部信号{top_conditions}个，强制平仓',
                }

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
                regime_state = 1
                if self.allow_window_until and current_time < self.allow_window_until:
                    return {
                        'can_enter': True,
                        'force_exit': False,
                        'regime_state': regime_state,
                        'ban_until': self.ban_until,
                        'allow_window_until': self.allow_window_until,
                        'reason': '底部窗口内',
                    }

                if (self.allow_window_until is None or current_time >= self.allow_window_until + timedelta(hours=8)):
                    if bottom_conditions > self.bottom_conditions_count:
                        self.allow_window_until = current_time + timedelta(hours=4)
                        self.bottom_conditions_count = bottom_conditions
                        return {
                            'can_enter': True,
                            'force_exit': False,
                            'regime_state': regime_state,
                            'ban_until': self.ban_until,
                            'allow_window_until': self.allow_window_until,
                            'reason': '底部信号增强，新开4小时窗口',
                        }

            if self.ban_until is not None and current_time < self.ban_until:
                return {
                    'can_enter': False,
                    'force_exit': False,
                    'regime_state': -1,
                    'ban_until': self.ban_until,
                    'allow_window_until': self.allow_window_until,
                    'reason': '处于禁开窗口',
                }

            return {
                'can_enter': True,
                'force_exit': False,
                'regime_state': regime_state,
                'ban_until': self.ban_until,
                'allow_window_until': self.allow_window_until,
                'reason': '中性环境允许开仓' if regime_state == 0 else '无底部增强信号',
            }

        except Exception:
            return {
                'can_enter': True,
                'force_exit': False,
                'regime_state': 0,
                'ban_until': self.ban_until,
                'allow_window_until': self.allow_window_until,
                'reason': '模块异常，安全模式允许开仓',
            }


class BreadthFlow1HStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1d"
    can_short = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count = 500

    minimal_roi = {
        "0": 0.032,
        "76": 0.012,
        "122": 0.00
    }
    stoploss = -0.063

    trailing_stop = True
    trailing_stop_positive = 0.02
    trailing_stop_positive_offset = 0.03
    trailing_only_offset_is_reached = True

    breadth_threshold = IntParameter(50, 70, default=57, space="buy")
    atr_mult_sl = DecimalParameter(1.0, 3.0, default=2.9, space="sell")
    atr_mult_trail = DecimalParameter(0.5, 2.0, default=1.6, space="sell")

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "limit",
        "stoploss_on_exchange": False
    }

    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # 嵌入市场状态控制模块
        self.regime_control = MarketRegimeControlModule()

    def informative_pairs(self):
        pairs = []
        if hasattr(self, 'dp') and self.dp:
            for p in self.dp.current_whitelist():
                pairs.append((p, "15m"))
                pairs.append((p, "5m"))
        # 声明BTC日线数据
        pairs.append(("BTC/USDT", "1d"))
        return pairs

    def _funding_ma_slope(self, symbol: str, window: int = 5) -> float:
        try:
            path = "user_data/models/funding_cache.json"
            if not os.path.exists(path):
                return 0.0
            with open(path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            series = cache.get(symbol, [])
            series.sort(key=lambda x: x.get("t", 0))
            if len(series) < window:
                return 0.0
            vals = pd.Series([x['v'] for x in series[-window:]])
            return float(vals.iloc[-1] - vals.iloc[0])
        except Exception:
            return 0.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe['obv'] = ta.OBV(dataframe)
        mf_mult = ((dataframe['close'] - dataframe['low']) - (dataframe['high'] - dataframe['close'])) / (dataframe['high'] - dataframe['low']).replace(0, np.nan)
        mf_mult = mf_mult.fillna(0)
        dataframe['mf_volume'] = mf_mult * dataframe['volume']
        dataframe['cmf'] = dataframe['mf_volume'].rolling(window=20, min_periods=1).sum() / dataframe['volume'].rolling(window=20, min_periods=1).sum()
        dataframe['mfi'] = ta.MFI(dataframe)
        dataframe['vwap'] = qtpylib.rolling_vwap(dataframe, window=24)
        dataframe['ema20'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema50'] = ta.EMA(dataframe, timeperiod=50)
        bb_upper, bb_middle, bb_lower = ta.BBANDS(dataframe['close'], timeperiod=20)
        dataframe['bb_upper'] = bb_upper
        dataframe['bb_middle'] = bb_middle
        dataframe['bb_lower'] = bb_lower
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']
        dataframe['ma5'] = ta.SMA(dataframe, timeperiod=5)
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['natr'] = ta.NATR(dataframe, timeperiod=14)
        return dataframe

    def _btc_ma5_slope(self) -> float:
        try:
            df = self.dp.get_pair_dataframe("BTC/USDT", self.timeframe)
            if df is None or len(df) < 6:
                return 0.0
            ma = ta.SMA(df, timeperiod=5)
            return float(ma.iloc[-1] - ma.iloc[-6])
        except Exception:
            return 0.0

    def _depth_ratio(self, pair: str) -> float:
        try:
            now = int(time.time())
            if not hasattr(self, "_depth_cache"):
                self._depth_cache = {}
            self._depth_cache = {k: v for k, v in self._depth_cache.items() if now - v[0] < 60}

            if pair in self._depth_cache:
                ts, val = self._depth_cache[pair]
                return val

            ob = None
            try:
                ob = self.exchange.fetch_order_book(pair, limit=10)
            except Exception:
                ob = self.exchange._api.fetch_order_book(pair, limit=10)

            bids = ob.get('bids', [])
            asks = ob.get('asks', [])
            bsum = float(sum([b[1] for b in bids])) if bids else 0.0
            asum = float(sum([a[1] for a in asks])) if asks else 0.0
            val = bsum / asum if asum != 0 else 1.0
            self._depth_cache[pair] = (now, val)
            return val
        except Exception:
            return 1.0

    def _batch_get_breadth_data(self):
        try:
            pairs = self.dp.current_whitelist()
            data = {}
            for p in pairs[:20]:
                try:
                    df, _ = self.dp.get_analyzed_dataframe(p, self.timeframe)
                    data[p] = df
                except Exception:
                    continue
            return data
        except Exception:
            return {}

    def _calculate_breadth(self, all_data, up=True):
        try:
            cnt, total = 0, 0
            for pair, df in all_data.items():
                if df is None or len(df) < 2:
                    continue
                c = df.iloc[-1]
                if 'ema20' in c and 'macd' in c and 'macdsignal' in c:
                    total += 1
                    if up and c['close'] > c['ema20'] and c['macd'] > c['macdsignal']:
                        cnt += 1
                    elif not up and c['close'] < c['ema20'] and c['macd'] < c['macdsignal']:
                        cnt += 1
            return (cnt / float(total)) if total > 0 else 0.0
        except Exception:
            return 0.0

    def _breadth_up(self) -> float:
        now = int(time.time())
        if hasattr(self, "_breadth_cache"):
            ts, val = self._breadth_cache
            if now - ts < 60:
                return val
        all_data = self._batch_get_breadth_data()
        val = self._calculate_breadth(all_data, up=True)
        self._breadth_cache = (now, val)
        return val

    def _breadth_down(self) -> float:
        now = int(time.time())
        if hasattr(self, "_breadth_down_cache"):
            ts, val = self._breadth_down_cache
            if now - ts < 60:
                return val
        all_data = self._batch_get_breadth_data()
        val = self._calculate_breadth(all_data, up=False)
        self._breadth_down_cache = (now, val)
        return val

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if 'enter_long' not in dataframe.columns:
            dataframe['enter_long'] = 0

        if dataframe.empty:
            return dataframe

        current_time = datetime.utcnow()
        regime = self.regime_control.update_regime(self.dp, current_time)
        if not regime.get('can_enter', True):
            if hasattr(self, 'logger'):
                self.logger.info(f"禁止开仓: {regime.get('reason', '')}")
            return dataframe

        if len(dataframe) >= 6:
            dataframe['obv_up'] = dataframe['obv'] > dataframe['obv'].shift(6)
            dataframe['cmf_up'] = dataframe['cmf'] > 0
            dataframe['mfi_up'] = (dataframe['mfi'] > 50) & (dataframe['mfi'] > dataframe['mfi'].shift(6))
            dataframe['vwap_up'] = dataframe['close'] > dataframe['vwap']
            dataframe['flow_bull'] = dataframe[['obv_up', 'cmf_up', 'mfi_up', 'vwap_up']].astype(int).sum(axis=1)
        else:
            dataframe['flow_bull'] = 0

        last = dataframe.iloc[-1]
        pair = metadata['pair']

        breadth = self._breadth_up()
        depth = self._depth_ratio(pair)
        btc_slope = self._btc_ma5_slope()
        fund_slope = self._funding_ma_slope("BTC/USDT:USDT", 5)

        natrp = float(last['natr']) / 100.0 if 'natr' in dataframe.columns else 0.0
        base_breadth = float(self.breadth_threshold.value) / 100.0
        dyn_breadth = base_breadth
        if natrp > 0.03:
            dyn_breadth = max(0.50, base_breadth - 0.05)
        elif natrp < 0.015:
            dyn_breadth = min(0.70, base_breadth + 0.05)

        min_breadth = 0.35
        if breadth < min_breadth:
            return dataframe

        if btc_slope < 0:
            return dataframe

        if last['close'] < last['ema50']:
            return dataframe

        flow_bull_last = int(last.get('flow_bull', 0))
        if flow_bull_last <= 0:
            return dataframe

        market_score = 0
        if breadth >= dyn_breadth:
            market_score += 1
        if depth > 1.05:
            market_score += 1
        if flow_bull_last >= 2:
            market_score += 1
        if btc_slope > 0:
            market_score += 1
        if fund_slope > 0:
            market_score += 1
        if last['close'] > last['ema20']:
            market_score += 1
        if last['close'] > last['vwap']:
            market_score += 1

        ema20 = float(last['ema20'])
        ema50 = float(last['ema50'])
        macd_val = float(last['macd'])
        macd_signal = float(last['macdsignal'])
        close_price = float(last['close'])
        bb_middle_last = float(last['bb_middle']) if 'bb_middle' in dataframe.columns else ema20
        bb_lower_last = float(last['bb_lower']) if 'bb_lower' in dataframe.columns else ema50

        pattern_a = False
        trend_a = ((ema20 > ema50 and close_price > ema50) and (macd_val > macd_signal))
        if trend_a and len(dataframe) >= 12:
            window = dataframe.iloc[-11:-1]
            hist_close = window['close']
            hist_ema20 = window['ema20']
            if 'bb_middle' in window.columns and 'bb_lower' in window.columns:
                hist_bb_middle = window['bb_middle']
                hist_bb_lower = window['bb_lower']
            else:
                hist_bb_middle = hist_ema20
                hist_bb_lower = window['ema50']

            th = 0.005
            near_ema20 = (hist_close - hist_ema20).abs() / hist_close <= th
            near_bb_middle = (hist_close - hist_bb_middle).abs() / hist_close <= th
            near_bb_lower = (hist_close - hist_bb_lower).abs() / hist_close <= th
            touched = (near_ema20 | near_bb_middle | near_bb_lower).any()

            rebound = (close_price > ema20) and (close_price > bb_middle_last)

            if touched and rebound and flow_bull_last >= 2 and market_score >= 4:
                pattern_a = True

        pattern_b = False
        if len(dataframe) >= 15:
            window_consol = dataframe.iloc[-11:-1]
            high_window = float(window_consol['high'].max())
            low_window = float(window_consol['low'].min())
            range_pct = 0.0
            if close_price > 0 and high_window > low_window:
                range_pct = (high_window - low_window) / close_price

            if range_pct < 0.05:
                if len(dataframe) >= 21:
                    window_break = dataframe.iloc[-21:-1]
                else:
                    window_break = dataframe.iloc[:-1]
                recent_high = float(window_break['high'].max())

                breakout = False
                if close_price > recent_high:
                    breakout = True
                elif recent_high > 0 and close_price > recent_high * 0.999:
                    breakout = True

                moderate_move = True
                if len(dataframe) >= 2 and natrp > 0:
                    prev_close = float(dataframe['close'].iloc[-2])
                    if prev_close > 0:
                        daily_ret = (close_price / prev_close) - 1.0
                        if daily_ret > natrp * 2.0:
                            moderate_move = False

                if breakout and moderate_move and flow_bull_last >= 2 and market_score >= 4:
                    pattern_b = True

        pattern_c = False
        if len(dataframe) >= 2:
            prev = dataframe.iloc[-2]
            prev_close = float(prev['close'])
            prev_ema20 = float(prev['ema20'])
            prev_ema50 = float(prev['ema50'])
            flow_bull_prev = int(prev.get('flow_bull', 0))

            trend_c = ((ema20 > ema50 and close_price > ema20) and (macd_val > macd_signal))
            minor_pullback = (prev_close < prev_ema20 and prev_close > prev_ema50 and close_price > ema20 and close_price > prev_close)
            flow_reversal = (flow_bull_prev <= 1 and flow_bull_last >= 2)

            moderate_bar = True
            if len(dataframe) >= 2 and natrp > 0 and prev_close > 0:
                daily_ret_c = (close_price / prev_close) - 1.0
                if daily_ret_c > natrp * 1.5:
                    moderate_bar = False

            extra_filter = (close_price > float(last['vwap'])) and (natrp > 0.015)

            if trend_c and minor_pullback and flow_reversal and market_score >= 5 and moderate_bar and extra_filter:
                pattern_c = True

        if (pattern_a or pattern_b or pattern_c) and last['volume'] > 0:
            dataframe.at[dataframe.index[-1], 'enter_long'] = 1

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if 'exit_long' not in dataframe.columns:
            dataframe['exit_long'] = 0

        if len(dataframe) >= 6:
            dataframe['obv_down'] = dataframe['obv'] < dataframe['obv'].shift(6)
            dataframe['cmf_down'] = dataframe['cmf'] < 0
            dataframe['mfi_down'] = (dataframe['mfi'] < 50) & (dataframe['mfi'] < dataframe['mfi'].shift(6))
            dataframe['vwap_down'] = dataframe['close'] < dataframe['vwap']
            dataframe['flow_bear'] = dataframe[['obv_down', 'cmf_down', 'mfi_down', 'vwap_down']].astype(int).sum(axis=1)
        else:
            dataframe['flow_bear'] = 0

        last = dataframe.iloc[-1]

        breadth_down = self._breadth_down()
        depth = self._depth_ratio(metadata['pair'])
        btc_slope = self._btc_ma5_slope()
        fund_slope = self._funding_ma_slope("BTC/USDT:USDT", 5)

        natrp = float(last['natr']) / 100.0 if 'natr' in dataframe.columns else 0.0
        dyn_breadth_low = 0.4
        if natrp > 0.03:
            dyn_breadth_low = min(0.45, dyn_breadth_low + 0.05)
        elif natrp < 0.015:
            dyn_breadth_low = max(0.35, dyn_breadth_low - 0.05)

        flow_bear_last = int(last.get('flow_bear', 0))

        votes = 0
        if breadth_down >= dyn_breadth_low:
            votes += 1
        if depth < 0.95:
            votes += 1
        if flow_bear_last >= 2:
            votes += 1
        if btc_slope < 0:
            votes += 1
        if fund_slope < 0:
            votes += 1
        if last['close'] < last['vwap']:
            votes += 1

        if votes >= 3 and last['volume'] > 0:
            dataframe.at[dataframe.index[-1], 'exit_long'] = 1

        return dataframe

    def custom_stoploss(self, pair: str, trade, current_time: datetime,
                        current_rate: float, current_profit: float, **kwargs) -> float:
        try:
            df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if df is None or len(df) < 20:
                return -abs(self.stoploss)

            atrp = float(df['natr'].iloc[-1]) / 100.0
            dyn_sl = max(abs(self.stoploss), atrp * float(self.atr_mult_sl.value))

            if current_profit is not None and current_profit > 0:
                trail = max(0.01, atrp * float(self.atr_mult_trail.value))
                if trail < dyn_sl:
                    return -trail
                else:
                    return -dyn_sl * 0.8

            return -dyn_sl
        except Exception:
            return -abs(self.stoploss)

    def custom_exit(self, pair: str, trade, current_time: datetime, 
                    current_rate: float, current_profit: float, **kwargs) -> Optional[str]:
        regime = self.regime_control.update_regime(self.dp, current_time)
        if regime['force_exit']:
            return "regime_force_exit"

        if current_profit is None or current_profit <= 0:
            return None

        breadth_down = self._breadth_down()
        depth = self._depth_ratio(pair)
        if current_profit > 0.02 and (breadth_down >= 0.6 or depth < 0.95):
            return "sell"
        return None

    def confirm_trade_entry(self, pair: str, order_type: str, amount: float, rate: float,
                            time_in_force: str, current_time: datetime, entry_tag: Optional[str],
                            side: str, **kwargs) -> bool:
        regime = self.regime_control.update_regime(self.dp, current_time)
        if not regime['can_enter']:
            if hasattr(self, 'logger'):
                self.logger.info(f"拒绝开仓 {pair}: {regime['reason']}")
            return False

        return True

    @property
    def plot_config(self):
        return {
            "main_plot": {
                "candles": True,
                "close": {"color": "black"},
                "ema20": {"color": "blue"},
                "ema50": {"color": "red"},
                "vwap": {"color": "orange", "plotly": {"dash": "dash"}},
            },
            "subplots": {
                "Volume & OBV": {
                    "volume": {"color": "gray", "type": "bar"},
                    "obv": {"color": "green", "secondary_y": True},
                },
                "Money Flow": {
                    "cmf": {"color": "blue"},
                    "mfi": {"color": "orange", "secondary_y": True},
                },
                "MACD": {
                    "macd": {"color": "blue"},
                    "macdsignal": {"color": "orange"},
                },
                "ATR & NATR": {
                    "atr": {"color": "red"},
                    "natr": {"color": "purple", "secondary_y": True},
                },
                "Flow Signals": {
                    "flow_bull": {"color": "green", "type": "bar"},
                    "flow_bear": {"color": "red", "type": "bar"},
                }
            }
        }
