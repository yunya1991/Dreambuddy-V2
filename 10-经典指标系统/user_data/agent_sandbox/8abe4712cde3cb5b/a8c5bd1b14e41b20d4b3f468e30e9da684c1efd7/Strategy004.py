# pragma pylint: disable=missing-docstring, invalid-name
# flake8: noqa
# isort: skip_file
import numpy as np
import pandas as pd
from pandas import DataFrame
from typing import Optional, Dict
from datetime import datetime, timedelta, timezone

from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter
from freqtrade.persistence import Trade
import talib.abstract as ta
from technical import qtpylib

#1h突破主策略
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


class BottomConfirmationModule:
    """
    模块化底部确认组件（对称于顶部结构）
    可复用在任何多头策略中
    """
    def __init__(self, accel_thr: float = 0.10):
        self.accel_thr = accel_thr

    def calculate_vwap(self, dataframe: DataFrame, window: int = 50) -> pd.Series:
        typical_price = (dataframe['high'] + dataframe['low'] + dataframe['close']) / 3
        volume_sum = dataframe['volume'].rolling(window=window).sum()
        volume_sum = volume_sum.replace(0, np.nan)
        
        vwap = (typical_price * dataframe['volume']).rolling(window=window).sum() / volume_sum
        return vwap.fillna(method='ffill')

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

        dataframe['ret'] = np.log(dataframe['close'] / dataframe['close'].shift(1))

        dataframe['speed_short'] = dataframe['ret'].rolling(3).mean()
        dataframe['speed_mid'] = dataframe['ret'].rolling(6).mean()
        dataframe['speed_long'] = dataframe['ret'].rolling(12).mean()

        dataframe['pump_acceleration'] = (
            (dataframe['speed_short'] > dataframe['speed_mid'] * (1 + self.accel_thr)) &
            (dataframe['speed_short'] > dataframe['speed_short'].shift(1)) &
            (dataframe['speed_mid'] < dataframe['speed_long']) &
            (dataframe['speed_mid'] < 0) &
            (dataframe['speed_long'] < 0)
        ).astype(int)

        dataframe['vol_mean'] = dataframe['volume'].rolling(20).mean()
        dataframe['vol_std'] = dataframe['volume'].rolling(20).std()
        dataframe['vol_std'] = dataframe['vol_std'].replace(0, np.nan)
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
        dataframe['absorption'] = (
            (dataframe['close'].pct_change() > 0) &
            (dataframe['cvd_delta'] < 0)
        ).astype(int)

        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
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
        )

        return dataframe

    def get_entry_condition(self, dataframe: DataFrame, threshold: int = 2) -> pd.Series:
        return dataframe['bottom_confirmation_score'] >= threshold


class _1hBreakoutStrategy004(IStrategy):
    """
    1h Breakout Strategy with Voting Logic + Bottom Confirmation + Market Regime Control (Spot)
    """
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    minimal_roi = {
        "0": 0.25,
        "22": 0.18,
        "165": 0.12,
        "222": 0
    }

    stoploss = -0.05
    trailing_stop = False

    process_only_new_candles = True
    use_exit_signal = False
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count: int = 100

    enable_short_entries = False

    tolerance_atr_mult = DecimalParameter(0.5, 2.0, default=2.0, space="buy")
    donchian_window = IntParameter(20, 100, default=20, space="buy")
    
    bottom_accel_thr = DecimalParameter(0.05, 0.20, default=0.20, space="buy")
    bottom_confirmation_threshold = IntParameter(1, 5, default=2, space="buy")

    def __init__(self, config: dict) -> None:
        super().__init__(config)
        self.bottom_module = BottomConfirmationModule(accel_thr=self.bottom_accel_thr.value)
        self.regime_control = MarketRegimeControlModule()

    def informative_pairs(self):
        return [("BTC/USDT", "1d")]

    def calculate_cmf(self, dataframe: DataFrame, window=20) -> pd.Series:
        hl_range = dataframe['high'] - dataframe['low']
        hl_range = hl_range.mask(hl_range == 0, np.nan)
        
        mf_multiplier = ((dataframe['close'] - dataframe['low']) - (dataframe['high'] - dataframe['close'])) / hl_range
        mf_multiplier = mf_multiplier.fillna(0)
        mf_volume = mf_multiplier * dataframe['volume']
        
        volume_sum = dataframe['volume'].rolling(window=window).sum()
        volume_sum = volume_sum.mask(volume_sum == 0, np.nan)
        
        cmf = mf_volume.rolling(window=window).sum() / volume_sum
        return cmf.fillna(0)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            return dataframe

        dataframe['atr'] = ta.ATR(dataframe, timeperiod=14)
        dataframe['rsi'] = ta.RSI(dataframe, timeperiod=14)
        dataframe['ema_20'] = ta.EMA(dataframe, timeperiod=20)
        dataframe['ema_50'] = ta.EMA(dataframe, timeperiod=50)

        donchian_window = self.donchian_window.value
        dataframe['donchian_upper'] = dataframe['high'].rolling(window=donchian_window).max()
        dataframe['donchian_lower'] = dataframe['low'].rolling(window=donchian_window).min()
        dataframe['donchian_middle'] = (dataframe['donchian_upper'] + dataframe['donchian_lower']) / 2

        dataframe['volume_mean'] = dataframe['volume'].rolling(window=20).mean()
        dataframe['vroc_12'] = dataframe['volume'].pct_change(periods=12) * 100
        dataframe['vroc_12'] = dataframe['vroc_12'].fillna(0)

        dataframe['close_mean'] = dataframe['close'].rolling(window=20).mean()
        dataframe['close_std'] = dataframe['close'].rolling(window=20).std()
        dataframe['close_std'] = dataframe['close_std'].replace(0, np.nan)
        dataframe['z_score'] = (dataframe['close'] - dataframe['close_mean']) / dataframe['close_std']
        dataframe['z_score'] = dataframe['z_score'].fillna(0)

        dataframe['cmf'] = self.calculate_cmf(dataframe, 20)

        dataframe['obv'] = ta.OBV(dataframe)
        dataframe['obv_high_20'] = dataframe['obv'].rolling(window=20).max()
        dataframe['obv_low_20'] = dataframe['obv'].rolling(window=20).min()

        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['macdhist'] = macd['macdhist']

        dataframe = self.bottom_module.populate_indicators(dataframe)

        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            dataframe['enter_long'] = 0
            dataframe['enter_short'] = 0
            dataframe['enter_tag'] = ''
            dataframe['short_votes'] = 0
            return dataframe

        dataframe['enter_long'] = 0
        dataframe['enter_short'] = 0
        dataframe['enter_tag'] = ''
        dataframe['short_votes'] = 0

        # 市场状态控制检查
        current_time = datetime.utcnow()
        regime = self.regime_control.update_regime(self.dp, current_time)
        if not regime['can_enter']:
            if hasattr(self, 'logger'):
                self.logger.info(f"禁止开仓: {regime['reason']}")
            return dataframe

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

        bottom_confirmed = self.bottom_module.get_entry_condition(
            dataframe, 
            threshold=self.bottom_confirmation_threshold.value
        )

        entry_condition = (
            (dataframe['buy_votes'] >= 3) &
            bottom_confirmed &
            (dataframe['close'] > dataframe['open']) &
            (dataframe['volume'] > 0) &
            (dataframe['rsi'] < 70)
        )

        dataframe.loc[entry_condition, 'enter_long'] = 1
        dataframe.loc[entry_condition, 'enter_tag'] = 'breakout_bottom_confirmed'

        cond_breakdown = (
            dataframe['close'] < (dataframe['donchian_lower'].shift(1) + (dataframe['atr'] * self.tolerance_atr_mult.value))
        )

        cond_volume_spike = (dataframe['volume'] > dataframe['volume_mean'] * 1.5)
        cond_cmf_negative = (dataframe['cmf'] < 0) & (dataframe['cmf'].shift(1) >= 0)
        cond_obv_low = (dataframe['obv'] < dataframe['obv_low_20'].shift(1) * 1.001)
        cond_rsi_oversold = (dataframe['rsi'] < 30)

        dataframe['short_votes'] = (
            cond_breakdown.astype(int) +
            cond_volume_spike.astype(int) +
            cond_cmf_negative.astype(int) +
            cond_obv_low.astype(int) +
            cond_rsi_oversold.astype(int)
        )

        short_entry_condition = (
            (dataframe['short_votes'] >= 3) &
            (dataframe['close'] < dataframe['open']) &
            (dataframe['volume'] > 0)
        )

        if self.enable_short_entries and self.can_short:
            dataframe.loc[short_entry_condition, 'enter_short'] = 1
            dataframe.loc[short_entry_condition, 'enter_tag'] = 'symmetric_short_entry'

        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        if len(dataframe) < 50:
            dataframe['exit_long'] = 0
            return dataframe

        dataframe['exit_long'] = 0
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
            atr_at_entry = entry_candle.get('atr', 0)
            if pd.isna(atr_at_entry) or atr_at_entry <= 0:
                return self.stoploss
                
            current_atr = dataframe['atr'].iloc[-1]
            if pd.isna(current_atr) or current_atr <= 0:
                return self.stoploss
            
            initial_sl_price = trade.open_rate - (atr_at_entry * 2.0)
            
            if current_rate <= initial_sl_price:
                return (initial_sl_price - current_rate) / current_rate
            
            if current_profit > 0.015:
                stop_price = trade.open_rate
                return (stop_price - current_rate) / current_rate
            
            if current_profit > 0.03:
                trail_distance = current_atr * 1.0
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

        if current_profit is not None and current_profit > 0:
            max_profit = getattr(trade, 'max_profit', current_profit)
            if max_profit > 0.05 and (max_profit - current_profit) > 0.03:
                return "trailing_profit_3pct"
            if max_profit > 0.10 and (max_profit - current_profit) > 0.04:
                return "trailing_profit_4pct"
            if max_profit > 0.20 and (max_profit - current_profit) > 0.06:
                return "trailing_profit_6pct"

        if current_profit > 0.20:
            return "quick_profit_20"
        if current_profit > 0.15:
            return "quick_profit_15"
        if current_profit > 0.10:
            return "quick_profit_10"
        
        hold_hours = (current_time - trade.open_date_utc).total_seconds() / 3600
        if hold_hours > 168:
            return "time_exit_7d"
        
        return None

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float,
                           proposed_stake: float, min_stake: float, max_stake: float,
                           entry_tag: Optional[str], side: str, **kwargs) -> float:
        if self.dp.runmode.is_backtest():
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
                    "short_votes": {"color": "#d62728", "type": "bar"},
                },
                "Z-Score": {"z_score": {"color": "#9467bd"}},
                "Bottom Confirmation": {
                    "bottom_confirmation_score": {"color": "#2ca02c", "type": "bar"},
                },
            }
        }
