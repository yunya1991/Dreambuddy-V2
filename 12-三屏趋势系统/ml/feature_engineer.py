"""基于趋势延续理论的特征工程

理论基础：趋势具有延续性，预测趋势需要捕捉三个维度：
1. 现有方向 (Direction): 当前趋势的方向和强度
2. 变化方向 (Change Direction): 趋势是否在加速/减速/逆转
3. 变化速率 (Change Rate): 趋势变化的速度

核心原理：大趋势决定小趋势，小趋势累积形成大趋势逆转

参考：Alexander Elder的三重滤网系统 + Elder-ray指标
- Elder-ray作为第二屏力量分析，检测趋势衰竭与背离
- 多空力量变化方向预测趋势逆转
"""

from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np

try:
    import sys
    sys.path.insert(0, "/Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/10-经典指标系统")
    from talib import abstract as ta
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False


class TrendFeatureEngineer:
    """基于趋势延续理论的特征工程

    从5个理论维度提取特征，用于ML模型训练和预测：
    1. 趋势方向 (direction): EMA斜率、价格位置、趋势一致性
    2. 趋势变化 (change): Elder-ray背离、力量穿越、动量转折
    3. 趋势速率 (velocity): 一阶/二阶导数、ATR归一化速度
    4. Elder-ray力量 (power): 多空力量、力量趋势、力量平衡
    5. 多尺度层级 (hierarchy): 大周期→小周期、小周期累积→逆转

    所有特征向前滚动计算，无未来函数。
    """

    def __init__(self, views: Optional[List[str]] = None):
        """
        参数:
            views: 要启用的视角列表，None=全部启用
                   ['direction', 'change', 'velocity', 'power', 'hierarchy']
        """
        all_views = ['direction', 'change', 'velocity', 'power', 'hierarchy']
        self.views = views or all_views
        self.feature_names: List[str] = []

    def create_features(self, df: pd.DataFrame, label_lookahead: int = 7) -> pd.DataFrame:
        """从OHLCV数据提取趋势理论驱动的特征

        参数:
            df: OHLCV DataFrame (open/high/low/close/volume)
            label_lookahead: 标签的前瞻期（天）

        返回:
            DataFrame with features + label columns
        """
        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        ohlcv = df  # 完整OHLCV供ELDER_RAY等函数使用

        result = pd.DataFrame(index=df.index)
        feature_cols = []

        # ========== 1. 趋势方向特征 ==========
        if 'direction' in self.views and TALIB_AVAILABLE:
            feats = self._direction_features(close, high, low)
            for name, values in feats.items():
                result[name] = values
                feature_cols.append(name)

        # ========== 2. 趋势变化方向特征 ==========
        if 'change' in self.views and TALIB_AVAILABLE:
            feats = self._change_direction_features(close, high, low, ohlcv)
            for name, values in feats.items():
                result[name] = values
                feature_cols.append(name)

        # ========== 3. 趋势变化速率特征 ==========
        if 'velocity' in self.views and TALIB_AVAILABLE:
            feats = self._velocity_features(close, high, low)
            for name, values in feats.items():
                result[name] = values
                feature_cols.append(name)

        # ========== 4. Elder-ray力量特征 ==========
        if 'power' in self.views and TALIB_AVAILABLE:
            feats = self._power_features(close, high, low, ohlcv)
            for name, values in feats.items():
                result[name] = values
                feature_cols.append(name)

        # ========== 5. 多尺度趋势层级特征 ==========
        if 'hierarchy' in self.views:
            feats = self._hierarchy_features(close, high, low, volume, df)
            for name, values in feats.items():
                result[name] = values
                feature_cols.append(name)

        # ========== 标签：未来N天收益方向 ==========
        future_return = close.shift(-label_lookahead) / close - 1.0
        result['future_return'] = future_return
        result['label'] = (future_return > 0).astype(int)
        result['label_reg'] = future_return

        self.feature_names = feature_cols
        return result

    def _direction_features(self, close, high, low) -> Dict[str, np.ndarray]:
        """趋势方向特征：现有方向是什么？

        理论：趋势方向由EMA斜率决定，多周期一致性确认趋势强度。
        Elder理论中EMA13为"共识价值"，斜率方向即趋势方向。
        """
        feats = {}

        # --- EMA斜率（核心方向信号）---
        # EMA斜率 > 0 = 上升趋势，< 0 = 下降趋势
        for period in [13, 26, 50, 100]:
            ema = ta.EMA(close, timeperiod=period)
            # 斜率 = (EMA_t - EMA_{t-1}) / EMA_{t-1}
            slope = ema.pct_change()
            feats[f'ema_slope_{period}'] = slope.values

            # 价格相对EMA的位置（归一化）
            feats[f'price_vs_ema_{period}'] = ((close - ema) / (ema + 1e-9)).values

        # --- 趋势一致性（多周期EMA排列）---
        # 短期EMA > 中期EMA > 长期EMA = 多头排列（强上升趋势）
        ema13 = ta.EMA(close, timeperiod=13)
        ema26 = ta.EMA(close, timeperiod=26)
        ema50 = ta.EMA(close, timeperiod=50)
        ema100 = ta.EMA(close, timeperiod=100)

        # 多头排列得分：有多少对EMA满足短期>长期
        bull_alignment = (
            (ema13 > ema26).astype(int) +
            (ema26 > ema50).astype(int) +
            (ema50 > ema100).astype(int) +
            (ema13 > ema50).astype(int) +
            (ema26 > ema100).astype(int) +
            (ema13 > ema100).astype(int)
        ) / 6.0  # 归一化到 0-1
        feats['trend_alignment'] = bull_alignment.values

        # EMA13斜率方向（Elder的核心趋势判断）
        ema13_slope = ema13.pct_change()
        feats['ema13_slope_dir'] = np.sign(ema13_slope).values

        # --- 价格位置特征 ---
        for period in [20, 60]:
            rolling_high = close.rolling(period).max()
            rolling_low = close.rolling(period).min()
            position = (close - rolling_low) / (rolling_high - rolling_low + 1e-9)
            feats[f'hl_position_{period}'] = position.values

        return feats

    def _change_direction_features(self, close, high, low, ohlcv) -> Dict[str, np.ndarray]:
        """趋势变化方向特征：趋势在加速还是减速？是否在逆转？

        理论：通过背离检测和力量穿越来判断趋势变化方向。
        Elder-ray背离是核心信号——价格创新高/低但力量不创新高/低。
        """
        feats = {}

        # --- Elder-ray 背离检测 ---
        elder = ta.ELDER_RAY(ohlcv, period=13)
        bull_power = elder['bull_power']
        bear_power = elder['bear_power']

        # 看涨背离：价格下跌（新低），但Bear Power上升（未创新低）
        # 实现方式：价格ROC为负，但Bear Power变化为正
        price_roc = close.pct_change(10)
        bear_power_change = bear_power.diff(10)

        # 看涨背离信号强度（价格跌但空头力量减弱）
        bullish_divergence = np.where(
            (price_roc < 0) & (bear_power_change > 0),
            np.abs(price_roc) * np.minimum(np.abs(bear_power_change), 1.0),
            0.0
        )
        feats['bullish_divergence'] = bullish_divergence

        # 看跌背离：价格上涨（新高），但Bull Power下降（未创新高）
        bull_power_change = bull_power.diff(10)
        bearish_divergence = np.where(
            (price_roc > 0) & (bull_power_change < 0),
            np.abs(price_roc) * np.minimum(np.abs(bull_power_change), 1.0),
            0.0
        )
        feats['bearish_divergence'] = bearish_divergence

        # --- 力量穿越信号（趋势逆转信号）---
        # Bull Power转为负：空头完全凌驾（多头失控）
        feats['bull_power_negative'] = (bull_power < 0).astype(float).values
        # Bear Power转为正：多头完全主控（空头失控）
        feats['bear_power_positive'] = (bear_power > 0).astype(float).values

        # --- MACD柱状图变化方向（动量转折）---
        macd_result = ta.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        if isinstance(macd_result, dict):
            hist = macd_result['macdhist']
        else:
            hist = macd_result[2]

        # MACD柱变化率（二阶动量）
        hist_change = hist.diff(5)
        feats['macd_hist_change'] = (hist_change / (close + 1e-9)).values

        # MACD柱方向反转信号
        hist_sign = np.sign(hist)
        hist_sign_prev = hist_sign.shift(3)
        macd_reversal = ((hist_sign != hist_sign_prev) & (hist_sign != 0)).astype(float).values
        feats['macd_reversal_signal'] = macd_reversal

        # --- 动量转折（一阶导数符号变化）---
        for period in [10, 20]:
            mom = close.pct_change(period)
            mom_sign = np.sign(mom)
            mom_sign_prev = mom_sign.shift(3)
            momentum_turn = ((mom_sign != mom_sign_prev) & (mom_sign != 0)).astype(float).values
            feats[f'momentum_turn_{period}'] = momentum_turn

        # --- RSI背离 ---
        rsi = ta.RSI(close, timeperiod=14)
        rsi_change = rsi.diff(10)
        # 价格涨但RSI跌 = 看跌背离
        rsi_bear_div = np.where(
            (price_roc > 0) & (rsi_change < 0),
            np.abs(rsi_change) / 100.0,
            0.0
        )
        feats['rsi_bear_divergence'] = rsi_bear_div
        # 价格跌但RSI涨 = 看涨背离
        rsi_bull_div = np.where(
            (price_roc < 0) & (rsi_change > 0),
            np.abs(rsi_change) / 100.0,
            0.0
        )
        feats['rsi_bull_divergence'] = rsi_bull_div

        return feats

    def _velocity_features(self, close, high, low) -> Dict[str, np.ndarray]:
        """趋势变化速率特征：趋势变化有多快？

        理论：一阶导数（速度）= 价格变化率，二阶导数（加速度）= 速度的变化率。
        速度递增=趋势加速，速度递减=趋势减速。
        ATR归一化后的速度更具跨资产可比性。
        """
        feats = {}

        # --- 一阶导数：价格速度（多周期ROC）---
        for period in [5, 10, 20]:
            roc = close.pct_change(period)
            feats[f'price_velocity_{period}'] = roc.values

        # --- 二阶导数：价格加速度 ---
        # 加速度 = ROC的变化率
        for period in [10, 20]:
            roc = close.pct_change(period)
            acceleration = roc.diff(period)
            feats[f'price_acceleration_{period}'] = acceleration.values

        # --- ATR归一化速度（跨资产可比）---
        atr_14 = ta.ATR(high, low, close, timeperiod=14)
        atr_20 = ta.ATR(high, low, close, timeperiod=20)

        # 价格速度 / ATR = 波动率调整后的趋势速度
        for period in [5, 10, 20]:
            roc = close.pct_change(period)
            vol_adj_velocity = roc / (atr_14 / close + 1e-9)
            feats[f'vol_adj_velocity_{period}'] = vol_adj_velocity.values

        # --- EMA斜率速度（共识价值的变化速率）---
        ema13 = ta.EMA(close, timeperiod=13)
        ema_slope = ema13.pct_change()
        # 斜率的变化率 = 趋势在加速还是减速
        slope_acceleration = ema_slope.diff(5)
        feats['ema13_slope_accel'] = slope_acceleration.values

        # --- 动量速度的加速度 ---
        mom_10 = close.pct_change(10)
        mom_10_change = mom_10.diff(5)
        feats['momentum_accel_10'] = mom_10_change.values

        return feats

    def _power_features(self, close, high, low, ohlcv) -> Dict[str, np.ndarray]:
        """Elder-ray力量特征：多空双方的真实力量对比

        理论：Elder-ray是市场的"X光"，
        - Bull Power > 0 且上升：多头力量增强
        - Bull Power > 0 但下降：多头力量衰竭
        - Bear Power < 0 且下降：空头力量增强
        - Bear Power < 0 但上升：空头力量衰竭
        """
        feats = {}

        elder = ta.ELDER_RAY(ohlcv, period=13)
        bull_power = elder['bull_power']
        bear_power = elder['bear_power']
        ema = elder['ema']

        # --- 归一化多空力量 ---
        bull_power_norm = bull_power / (close + 1e-9)
        bear_power_norm = bear_power / (close + 1e-9)
        feats['bull_power_norm'] = bull_power_norm.values
        feats['bear_power_norm'] = bear_power_norm.values

        # --- 力量趋势（上升/下降）---
        bull_power_slope = bull_power_norm.diff(5)
        bear_power_slope = bear_power_norm.diff(5)
        feats['bull_power_slope'] = bull_power_slope.values
        feats['bear_power_slope'] = bear_power_slope.values

        # --- 力量衰竭信号 ---
        # 多头衰竭：Bull Power > 0 但在下降
        bull_exhaustion = np.where(
            (bull_power_norm > 0) & (bull_power_slope < 0),
            np.abs(bull_power_slope),
            0.0
        )
        feats['bull_exhaustion'] = bull_exhaustion

        # 空头衰竭：Bear Power < 0 但在上升（向0靠近）
        bear_exhaustion = np.where(
            (bear_power_norm < 0) & (bear_power_slope > 0),
            np.abs(bear_power_slope),
            0.0
        )
        feats['bear_exhaustion'] = bear_exhaustion

        # --- 多空力量平衡 ---
        power_balance = bull_power_norm - bear_power_norm
        feats['power_balance'] = power_balance.values

        # 力量平衡的变化方向
        power_balance_change = power_balance.diff(5)
        feats['power_balance_change'] = power_balance_change.values

        # --- 力量同时减弱信号（变盘前兆）---
        # Bull Power > 0 下降 + Bear Power < 0 上升 = 双方力量均减弱
        both_weakening = np.where(
            (bull_power_norm > 0) & (bull_power_slope < 0) &
            (bear_power_norm < 0) & (bear_power_slope > 0),
            1.0,
            0.0
        )
        feats['both_weakening'] = both_weakening

        # --- 力量穿越零线 ---
        # Bull Power从正转负
        bull_cross_negative = (
            (bull_power_norm < 0) & (bull_power_norm.shift(1) >= 0)
        ).astype(float).values
        feats['bull_cross_negative'] = bull_cross_negative

        # Bear Power从负转正
        bear_cross_positive = (
            (bear_power_norm > 0) & (bear_power_norm.shift(1) <= 0)
        ).astype(float).values
        feats['bear_cross_positive'] = bear_cross_positive

        return feats

    def _hierarchy_features(self, close, high, low, volume, df) -> Dict[str, np.ndarray]:
        """多尺度趋势层级特征：大趋势→小趋势，小趋势累积→大趋势逆转

        理论：
        - 大趋势（EMA50/100斜率）决定小趋势的方向偏好
        - 小趋势（EMA13/26斜率）的累积可以预示大趋势逆转
        - 当小周期动量持续与大趋势相反时，可能预示趋势逆转

        实现：用不同EMA周期模拟多时间尺度
        - "周线级别" ≈ EMA50/100
        - "日线级别" ≈ EMA13/26
        """
        feats = {}

        if not TALIB_AVAILABLE:
            # 纯pandas回退
            ema13 = close.ewm(span=13, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            ema50 = close.ewm(span=50, adjust=False).mean()
            ema100 = close.ewm(span=100, adjust=False).mean()
        else:
            ema13 = ta.EMA(close, timeperiod=13)
            ema26 = ta.EMA(close, timeperiod=26)
            ema50 = ta.EMA(close, timeperiod=50)
            ema100 = ta.EMA(close, timeperiod=100)

        # --- 大趋势方向（周线级别）---
        macro_slope = ema100.pct_change(20)  # 20天≈1月的大趋势方向
        feats['macro_trend_slope'] = macro_slope.values
        feats['macro_trend_dir'] = np.sign(macro_slope).values

        # --- 小趋势方向（日线级别）---
        micro_slope = ema13.pct_change(5)
        feats['micro_trend_slope'] = micro_slope.values

        # --- 大小趋势一致性 ---
        # 大趋势向上 + 小趋势向上 = 强多头
        # 大趋势向上 + 小趋势向下 = 回调（可能买入机会）
        # 大趋势向下 + 小趋势向上 = 反弹（可能做空机会）
        # 大趋势向下 + 小趋势向下 = 强空头
        trend_alignment = np.sign(macro_slope) * np.sign(micro_slope)
        feats['trend_scale_alignment'] = trend_alignment.values

        # --- 小趋势累积信号（预示大趋势逆转）---
        # 当小周期动量持续与大趋势相反时，累积到一定程度预示逆转
        micro_momentum = close.pct_change(5)
        macro_dir = np.sign(macro_slope)

        # 小趋势与大趋势反向的累积强度
        counter_trend = np.where(
            macro_dir != 0,
            -macro_dir * micro_momentum,  # 反向时为正
            0.0
        )
        counter_trend_series = pd.Series(counter_trend, index=close.index)

        # 20天累积反向动量
        counter_trend_accum_20 = counter_trend_series.rolling(20).sum()
        feats['counter_trend_accum_20'] = counter_trend_accum_20.values

        # 10天累积反向动量
        counter_trend_accum_10 = counter_trend_series.rolling(10).sum()
        feats['counter_trend_accum_10'] = counter_trend_accum_10.values

        # --- 趋势逆转预警信号 ---
        # 大趋势方向 + 小趋势持续反向累积 > 阈值
        reversal_warning = np.where(
            (np.abs(counter_trend_accum_20) > 0.05) &
            (np.sign(counter_trend_accum_20) != macro_dir),
            np.abs(counter_trend_accum_20),
            0.0
        )
        feats['reversal_warning'] = reversal_warning

        # --- 波动率压缩/扩张（大趋势的前兆）---
        # 低波动率后常有趋势突破
        ret = close.pct_change()
        vol_20 = ret.rolling(20).std()
        vol_60 = ret.rolling(60).std()
        vol_ratio = vol_20 / (vol_60 + 1e-9)
        feats['vol_compression'] = (1.0 / (vol_ratio + 1e-9)).clip(0, 10).values  # 压缩=高值

        # --- 量价配合（趋势确认）---
        vol_ma20 = volume.rolling(20).mean()
        vol_ratio_20 = volume / (vol_ma20 + 1e-9)
        # 放量上涨 vs 放量下跌
        up_volume = np.where(ret > 0, vol_ratio_20, 0.0)
        down_volume = np.where(ret < 0, vol_ratio_20, 0.0)

        up_vol_sum = pd.Series(up_volume, index=close.index).rolling(20).sum()
        down_vol_sum = pd.Series(down_volume, index=close.index).rolling(20).sum()
        vol_trend = (up_vol_sum - down_vol_sum) / (up_vol_sum + down_vol_sum + 1e-9)
        feats['volume_trend_20'] = vol_trend.values

        return feats

    def get_feature_names(self) -> List[str]:
        """获取所有特征列名"""
        return self.feature_names

    def get_valid_data(self, features_df: pd.DataFrame) -> pd.DataFrame:
        """获取有效数据（去除含NaN的行）"""
        return features_df.dropna(subset=self.feature_names + ['label'])

    def get_feature_groups(self) -> Dict[str, List[str]]:
        """获取特征分组（用于分析和特征选择）"""
        groups = {
            'direction': [f for f in self.feature_names if any(
                f.startswith(p) for p in ['ema_slope_', 'price_vs_ema_', 'trend_alignment',
                                          'ema13_slope_dir', 'hl_position_']
            )],
            'change': [f for f in self.feature_names if any(
                f.startswith(p) for p in ['bullish_divergence', 'bearish_divergence',
                                          'bull_power_negative', 'bear_power_positive',
                                          'macd_hist_change', 'macd_reversal',
                                          'momentum_turn_', 'rsi_bear_div', 'rsi_bull_div']
            )],
            'velocity': [f for f in self.feature_names if any(
                f.startswith(p) for p in ['price_velocity_', 'price_acceleration_',
                                          'vol_adj_velocity_', 'ema13_slope_accel',
                                          'momentum_accel_']
            )],
            'power': [f for f in self.feature_names if any(
                f.startswith(p) for p in ['bull_power_', 'bear_power_', 'power_balance',
                                          'bull_exhaustion', 'bear_exhaustion',
                                          'both_weakening', 'bull_cross', 'bear_cross']
            )],
            'hierarchy': [f for f in self.feature_names if any(
                f.startswith(p) for p in ['macro_trend_', 'micro_trend_',
                                          'trend_scale_', 'counter_trend_',
                                          'reversal_warning', 'vol_compression',
                                          'volume_trend_']
            )],
        }
        return groups
