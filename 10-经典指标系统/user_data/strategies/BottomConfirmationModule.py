import numpy as np
import pandas as pd
from pandas import DataFrame
from typing import Optional

import talib.abstract as ta
from technical import qtpylib
from freqtrade.strategy import DecimalParameter


class BottomConfirmationModule:
    """
    模块化底部确认组件（对称于顶部 pump_deceleration 结构）
    可直接插入任何多头策略的 populate_indicators 和 populate_entry_trend 中
    """

    def __init__(self, config: dict):
        self.config = config
        # 可 Hyperopt 的加速阈值（默认 10% 加速）
        self.accel_thr = DecimalParameter(0.05, 0.20, default=0.10, space="buy")
        # 其他参数可从 config 获取或在此定义

    def populate_indicators(self, dataframe: DataFrame) -> DataFrame:
        """
        在策略的 populate_indicators 中调用此方法
        计算所有底部确认因子并返回增强的 dataframe
        """
        if len(dataframe) < 20:
            return dataframe

        # 1. 动量加速（pump_acceleration）
        # 需要提前计算 speed_short/mid/long（对数收益率均值）
        dataframe['ret'] = np.log(dataframe['close'] / dataframe['close'].shift(1))
        win_s = 3   # 可参数化
        win_m = 6
        win_l = 12
        dataframe['speed_short'] = dataframe['ret'].rolling(win_s).mean()
        dataframe['speed_mid'] = dataframe['ret'].rolling(win_m).mean()
        dataframe['speed_long'] = dataframe['ret'].rolling(win_l).mean()

        accel_thr = self.accel_thr.value
        dataframe['pump_acceleration'] = (
            (dataframe['speed_short'] > dataframe['speed_mid'] * (1 + accel_thr)) &
            (dataframe['speed_short'] > dataframe['speed_short'].shift(1)) &
            (dataframe['speed_mid'] < dataframe['speed_long']) &
            (dataframe['speed_mid'] < 0) &
            (dataframe['speed_long'] < 0)
        ).astype(int)

        # 2. 成交量异常（放量吸筹）
        dataframe['vol_mean'] = dataframe['volume'].rolling(20).mean()
        dataframe['vol_std'] = dataframe['volume'].rolling(20).std().replace(0, np.nan)
        dataframe['vol_z'] = (dataframe['volume'] - dataframe['vol_mean']) / dataframe['vol_std']
        dataframe['vol_anomaly'] = (dataframe['vol_z'] > 2.0).astype(int)

        # 3. VWAP 支撑（价格在 VWAP 下方但被支撑）
        dataframe['vwap'] = qtpylib.rolling_vwap(dataframe, window=50)
        dataframe['vwap_support'] = (
            (dataframe['close'] > dataframe['vwap']) &
            (dataframe['low'] < dataframe['vwap'])
        ).astype(int)

        # 4. 隐形吸筹（absorption）：价格上涨但 CVD 为负（隐藏买盘）
        delta = dataframe['close'] - dataframe['open']
        dataframe['buy_vol'] = np.where(delta > 0, dataframe['volume'], 0)
        dataframe['sell_vol'] = np.where(delta < 0, dataframe['volume'], 0)
        dataframe['cvd'] = (dataframe['buy_vol'] - dataframe['sell_vol']).cumsum()
        dataframe['cvd_delta'] = dataframe['cvd'].diff()
        dataframe['absorption'] = (
            (dataframe['close'].pct_change() > 0) &
            (dataframe['cvd_delta'] < 0)
        ).astype(int)

        # 5. MACD 转强（金叉）
        macd = ta.MACD(dataframe)
        dataframe['macd'] = macd['macd']
        dataframe['macdsignal'] = macd['macdsignal']
        dataframe['momentum_turn_up'] = (
            (dataframe['macd'] > dataframe['macdsignal']) &
            (dataframe['macd'].shift(1) <= dataframe['macdsignal'].shift(1))
        ).astype(int)

        # 底部确认评分（满分 5 分）
        dataframe['bottom_confirmation_score'] = (
            dataframe['pump_acceleration'] +
            dataframe['vol_anomaly'] +
            dataframe['vwap_support'] +
            dataframe['absorption'] +
            dataframe['momentum_turn_up']
        )

        return dataframe

    def get_entry_condition(self, dataframe: DataFrame) -> pd.Series:
        """
        返回底部确认条件（可直接用于入场）
        建议：bottom_confirmation_score >= 3
        """
        return dataframe['bottom_confirmation_score'] >= 3

