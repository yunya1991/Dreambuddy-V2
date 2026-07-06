# pragma pylint: disable=missing-docstring, invalid-name, pointless-string-statement
# flake8: noqa: F401
# isort: skip_file
# --- Do not remove these imports ---
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from pandas import DataFrame
from typing import Optional, Dict

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from freqtrade.enums import RunMode
from freqtrade.persistence import Trade

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
                if hasattr(dp, 'logger'):
                    dp.logger.warning("BTC/USDT 日线数据不足")
                return pd.DataFrame()
            return btc_1d.iloc[:-1].copy()  # 只用已闭合日线
        except Exception as e:
            if hasattr(dp, 'logger'):
                dp.logger.error(f"获取BTC/USDT日线失败: {e}")
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

        except Exception as e:
            if hasattr(dp, 'logger'):
                dp.logger.exception(f"市场状态模块计算错误: {e}")
            return {'can_enter': True, 'force_exit': False, 'reason': '模块异常，安全模式允许开仓'}


class TrendConfirmationStrategy(IStrategy):
    """
    4H Trend Confirmation Strategy (Fully Fixed Version - TA-Lib Compatible)
    Long-only multi-indicator trend following with voting system
    """
    INTERFACE_VERSION = 3

    # Strategy settings
    timeframe = "4h"
    can_short: bool = False
    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 200

    # ROI & Stoploss
    minimal_roi = {
        "0": 0.209,
        "153": 0.146,
        "291": 0.076,
        "1048": 0.00
    }

    stoploss = -0.060
    trailing_stop = False  # 使用 custom_stoploss

    # Order settings
    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # Hyperopt parameters
    ema_fast = IntParameter(20, 40, default=26, space="buy")
    ema_medium = IntParameter(40, 60, default=42, space="buy")
    ema_slow = IntParameter(70, 100, default=90, space="buy")
    
    adx_threshold = IntParameter(20, 30, default=22, space="buy")
    volume_mult = DecimalParameter(1.0, 3.0, default=1.10, space="buy")
    
    entry_votes_required = IntParameter(3, 7, default=4, space="buy")
    exit_votes_required = IntParameter(2, 5, default=2, space="sell")
    
    initial_sl_atr_mult = DecimalParameter(2.0, 4.0, default=3.8, space="sell")
    trail_sl_atr_mult = DecimalParameter(1.0, 3.0, default=1.5, space="sell")
    
    st_period = IntParameter(7, 15, default=12, space="buy")
    st_multiplier = DecimalParameter(2.0, 4.0, default=2.6, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        # 嵌入市场状态控制模块
        self.regime_control = MarketRegimeControlModule()

    def informative_pairs(self):
        # 声明BTC日线数据
        return [("BTC/USDT", "1d")]

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 100:
            return dataframe

        if 'enter_tag' not in dataframe.columns:
            dataframe['enter_tag'] = ''

        # 1. EMAs
        dataframe['ema_fast'] = ta.EMA(dataframe, timeperiod=self.ema_fast.value)
        dataframe['ema_medium'] = ta.EMA(dataframe, timeperiod=self.ema_medium.value)
        dataframe['ema_slow'] = ta.EMA(dataframe, timeperiod=self.ema_slow.value)

        # 🔧 修复：分别获取ADX、+DI、-DI
        try:
            dataframe['adx'] = ta.ADX(dataframe)
            dataframe['plus_di'] = ta.PLUS_DI(dataframe)
            dataframe['minus_di'] = ta.MINUS_DI(dataframe)
        except Exception:
            import talib
            dataframe['adx'] = talib.ADX(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)
            dataframe['plus_di'] = talib.PLUS_DI(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)
            dataframe['minus_di'] = talib.MINUS_DI(dataframe['high'], dataframe['low'], dataframe['close'], timeperiod=14)

        # 3. Bollinger Bands
        bb = qtpylib.bollinger_bands(qtpylib.typical_price(dataframe), window=20, stds=2)
        dataframe['bb_middle'] = bb['mid']
        dataframe['bb_upper'] = bb['upper']
        dataframe['bb_lower'] = bb['lower']

        # 4. Volume
        dataframe['volume_mean'] = dataframe['volume'].rolling(window=20).mean()

        # 5. ATR
        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)

        # 6. SuperTrend
        atr_st = ta.ATR(dataframe, timeperiod=self.st_period.value)
        hl2 = (dataframe['high'] + dataframe['low']) / 2
        upper_band = hl2 + (self.st_multiplier.value * atr_st)
        lower_band = hl2 - (self.st_multiplier.value * atr_st)

        close = dataframe['close'].values
        ub = upper_band.values
        lb = lower_band.values

        final_ub = np.zeros(len(dataframe))
        final_lb = np.zeros(len(dataframe))
        trend = np.ones(len(dataframe))

        final_ub[0] = ub[0]
        final_lb[0] = lb[0]

        for i in range(1, len(dataframe)):
            final_ub[i] = ub[i] if (ub[i] < final_ub[i-1] or close[i-1] > final_ub[i-1]) else final_ub[i-1]
            final_lb[i] = lb[i] if (lb[i] > final_lb[i-1] or close[i-1] < final_lb[i-1]) else final_lb[i-1]

            if trend[i-1] == 1:
                trend[i] = -1 if close[i] <= final_lb[i] else 1
            else:
                trend[i] = 1 if close[i] >= final_ub[i] else -1

        dataframe['supertrend_ub'] = final_ub
        dataframe['supertrend_lb'] = final_lb
        dataframe['supertrend_direction'] = trend.astype(int)

        # 7. Chandelier Exit
        atr_22 = ta.ATR(dataframe, timeperiod=22)
        highest_high = dataframe['high'].rolling(window=22).max()
        dataframe['chandelier_long'] = highest_high - (atr_22 * 3.0)

        # 8. Rolling VWAP
        vwap_window = 50
        tp = (dataframe['high'] + dataframe['low'] + dataframe['close']) / 3
        dataframe['vwap'] = (tp * dataframe['volume']).rolling(window=vwap_window).sum() / dataframe['volume'].rolling(window=vwap_window).sum()

        # 9. RSI & MACD
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macd_signal'] = macd['macdsignal']
        dataframe['macd_hist'] = macd['macdhist']

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            return dataframe

        # 市场状态控制检查
        current_time = datetime.utcnow()
        regime = self.regime_control.update_regime(self.dp, current_time)
        if not regime['can_enter']:
            if hasattr(self, 'logger'):
                self.logger.info(f"禁止开仓: {regime['reason']}")
            return dataframe

        conditions = [
            (dataframe['ema_fast'] > dataframe['ema_medium']) & (dataframe['ema_medium'] > dataframe['ema_slow']),
            (dataframe['adx'] >= self.adx_threshold.value) & (dataframe['plus_di'] > dataframe['minus_di']),
            dataframe['close'] > dataframe['bb_middle'],
            (dataframe['low'] > dataframe['ema_medium']) | (dataframe['close'] > dataframe['vwap']),
            dataframe['volume'] >= dataframe['volume_mean'] * self.volume_mult.value,
            dataframe['supertrend_direction'] == 1,
            dataframe['close'] > dataframe['chandelier_long'],
            (dataframe['macd'] > dataframe['macd_signal']) & (dataframe['macd_hist'] > 0),
            (dataframe['rsi'] < 70) & (dataframe['rsi'] > 30),
            (dataframe['close'] > dataframe['close'].shift(1)) | (dataframe['close'] > dataframe['close'].shift(2)),
        ]

        dataframe['entry_votes'] = sum(cond.astype(int) for cond in conditions)

        entry_cond = (
            (dataframe['entry_votes'] >= self.entry_votes_required.value) &
            (dataframe['close'] > dataframe['open']) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi'] < 80)
        )

        dataframe.loc[entry_cond, 'enter_long'] = 1
        dataframe.loc[entry_cond, 'enter_tag'] = 'trend_confirmation'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            dataframe['exit_long'] = 0
            return dataframe

        conditions = [
            (dataframe['ema_fast'] < dataframe['ema_medium']) & (dataframe['ema_medium'] < dataframe['ema_slow']),
            (dataframe['adx'] < 20) | (dataframe['adx'] < dataframe['adx'].shift(1)),
            dataframe['close'] < dataframe['bb_middle'],
            dataframe['high'] < dataframe['ema_medium'],
            dataframe['volume'] < dataframe['volume_mean'] * 0.8,
            dataframe['supertrend_direction'] == -1,
            dataframe['close'] < dataframe['chandelier_long'],
            (dataframe['macd'] < dataframe['macd_signal']) | (dataframe['macd_hist'] < 0),
            (dataframe['rsi'] < 40) | (dataframe['rsi'] > 70),
            (dataframe['close'] < dataframe['close'].shift(1)) | (dataframe['close'] < dataframe['close'].shift(2)),
        ]

        dataframe['exit_votes'] = sum(cond.astype(int) for cond in conditions)

        exit_cond = (
            (dataframe['exit_votes'] >= self.exit_votes_required.value) &
            (dataframe['close'] < dataframe['open']) &
            (dataframe['volume'] > 0)
        )

        dataframe.loc[exit_cond, 'exit_long'] = 1
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
            
            if dataframe.index.tz is None:
                df_index = dataframe.index.tz_localize('UTC')
            else:
                df_index = dataframe.index.tz_convert('UTC')
            dataframe = dataframe.set_index(df_index)

            mask = dataframe.index <= entry_date
            if not mask.any():
                return self.stoploss
                
            entry_candle = dataframe.loc[mask].iloc[-1]
            entry_atr = entry_candle['atr']
            current_atr = dataframe['atr'].iloc[-1]

            initial_sl_price = trade.open_rate - (entry_atr * float(self.initial_sl_atr_mult.value))
            
            if current_rate <= initial_sl_price:
                return (initial_sl_price - current_rate) / current_rate

            entry_atr_pct = entry_atr / trade.open_rate
            if current_profit > 1.0 * entry_atr_pct:
                return 0.0

            if current_profit > 2.0 * entry_atr_pct:
                trail_distance = current_atr * float(self.trail_sl_atr_mult.value)
                stop_price = max(current_rate - trail_distance, trade.open_rate)
                return (stop_price - current_rate) / current_rate

            return (initial_sl_price - current_rate) / current_rate

        except Exception as e:
            if hasattr(self, 'logger'):
                self.logger.error(f"Stoploss error for {pair}: {str(e)}")
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
                "ema_medium": {"color": "#ff7f0e"},
                "ema_slow": {"color": "#d62728"},
                "bb_upper": {"color": "gray", "fill_to": "bb_lower"},
                "bb_middle": {"color": "#9467bd"},
                "bb_lower": {"color": "gray"},
                "supertrend_ub": {"color": "green", "plotly": {"dash": "dash"}},
                "supertrend_lb": {"color": "red", "plotly": {"dash": "dash"}},
                "chandelier_long": {"color": "#2ca02c"},
                "vwap": {"color": "#17becf"},
            },
            "subplots": {
                "Volume": {
                    "volume": {"color": "gray", "type": "bar"},
                    "volume_mean": {"color": "#1f77b4"},
                },
                "ADX & DI": {
                    "adx": {"color": "#9467bd"},
                    "plus_di": {"color": "#2ca02c"},
                    "minus_di": {"color": "#d62728"},
                },
                "RSI": {"rsi": {"color": "#ff7f0e"}},
                "MACD": {
                    "macd": {"color": "#1f77b4"},
                    "macd_signal": {"color": "#ff7f0e"},
                    "macd_hist": {"color": "#98df8a", "type": "bar"},
                },
                "ATR": {"atr": {"color": "#7f7f7f"}},
                "Votes": {
                    "entry_votes": {"color": "#2ca02c", "type": "bar"},
                    "exit_votes": {"color": "#d62728", "type": "bar"},
                },
                "SuperTrend": {
                    "supertrend_direction": {"color": "#2ca02c", "plotly": {"line": {"width": 3}}},
                },
            }
        }
