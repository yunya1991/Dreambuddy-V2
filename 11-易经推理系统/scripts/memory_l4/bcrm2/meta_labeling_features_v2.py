"""
L2 Meta-Labeling 特征工程模块 V2 — 与L1互补的特征体系

设计原则:
  L1关注: 方向预测 (技术面特征: 八卦、趋势、动量、波动率等)
  L2关注: 信号质量评估 (宏观、跨资产、时间维度)

  互补而非重叠:
    - L1说"这个方向是对的"
    - L2说"这个时机好不好、资金流不支持、宏观环境不利"

特征体系 (5大类，约25个特征):
  1. 时间维度特征 (5个): 周期相位、季节性、时段特征
  2. 宏观环境特征 (5个): BTC.D趋势、风险偏好、资金流向
  3. 信号稀有度特征 (5个): 近期同向信号频率、信号间隔、信号密度
  4. 市场结构特征 (5个): 波动率结构变化、趋势成熟度、反转概率
  5. 跨资产验证特征 (5个): 相关性变化、Beta稳定性、联动强度

核心哲学:
  L2是对L1的"否定"——不是否定方向，而是否定"时机"和"环境"
  当L1给出方向信号时，L2回答"现在是不是好时机"
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class MetaLabelingFeaturesV2:
    """
    L2特征工程 V2 — 与L1互补的特征体系
    
    核心思想: L2不重复L1的技术面判断，而是从宏观、时间、结构维度评估信号质量
    """
    
    def __init__(
        self,
        time_windows: List[int] = [20, 60, 120],
        ref_symbol: str = "BTC",
    ):
        self.time_windows = time_windows
        self.ref_symbol = ref_symbol
    
    def compute_base_features(
        self,
        df: pd.DataFrame,
        l1_pred: np.ndarray,
        l1_proba: np.ndarray,
        ref_df: Optional[pd.DataFrame] = None,
        cycle_phase: Optional[pd.DataFrame] = None,
    ) -> np.ndarray:
        """
        计算完整的L2特征矩阵
        
        Args:
            df: OHLCV原始数据
            l1_pred: L1预测方向 (-1/0/1)
            l1_proba: L1预测概率 (n, 3)
            ref_df: 参考资产OHLCV (如BTC数据，用于跨资产验证)
            cycle_phase: 库存周期阶段数据
            
        Returns:
            L2特征矩阵 (n_samples, n_meta_features)
        """
        n = len(df)
        meta_features = []
        
        # 1. 时间维度特征 (L1不涉及的维度)
        meta_features.append(self._time_dimension_features(df))
        
        # 2. 宏观环境特征 (资金流向、风险偏好)
        meta_features.append(self._macro_environment_features(df, ref_df))
        
        # 3. 信号稀有度特征 (近期同类信号频率)
        meta_features.append(self._signal_rarity_features(l1_pred))
        
        # 4. 市场结构特征 (趋势成熟度、反转概率)
        meta_features.append(self._market_structure_features(df, cycle_phase))
        
        # 5. 跨资产验证特征 (相关性变化、Beta稳定性)
        meta_features.append(self._cross_asset_validation_features(df, ref_df))
        
        # 拼接所有特征
        result = np.hstack(meta_features)
        
        # 处理NaN
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)
        
        return result
    
    # ============================================================
    # 1. 时间维度特征 (L1不涉及的维度)
    # ============================================================
    
    def _time_dimension_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        时间维度特征 — 评估"时机"好坏
        
        特征:
          - time_hour: 交易时段 (亚洲/欧洲/美洲)
          - time_day_of_week: 星期几 (周一效应)
          - time_month_phase: 月内相位 (月初/月中/月末)
          - time_cycle_phase: 库存周期相位 (用周期数据)
          - time_since_last_extreme: 距离上次极值的时间
        """
        n = len(df)
        features = np.zeros((n, 5))
        
        if not isinstance(df.index, pd.DatetimeIndex):
            return features
        
        timestamps = df.index
        
        # 1. 交易时段 (UTC)
        hours = timestamps.hour
        features[:, 0] = np.where(
            (hours >= 0) & (hours < 8), 0.0,  # 亚洲时段
            np.where((hours >= 8) & (hours < 16), 0.5, 1.0)  # 欧洲/美洲时段
        )
        
        # 2. 星期几效应
        dow = timestamps.dayofweek
        features[:, 1] = dow / 6.0  # 0-1标准化
        
        # 3. 月内相位
        dom = timestamps.day
        features[:, 2] = dom / 31.0  # 月初0 → 月末1
        
        # 4. 季节性 (季度)
        month = timestamps.month
        features[:, 3] = ((month - 1) % 3) / 3.0  # 季度内相位
        
        # 5. 距离上次价格极值的时间
        close = df['close'].values
        lookback = min(60, n)
        for i in range(lookback, n):
            window = close[i-lookback:i]
            local_max = np.argmax(window)
            local_min = np.argmin(window)
            dist_to_max = (lookback - local_max) / lookback
            dist_to_min = (lookback - local_min) / lookback
            features[i, 4] = min(dist_to_max, dist_to_min)
        
        return features
    
    # ============================================================
    # 2. 宏观环境特征 (资金流向、风险偏好)
    # ============================================================
    
    def _macro_environment_features(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
    ) -> np.ndarray:
        """
        宏观环境特征 — 评估"环境"是否支持该方向
        
        特征:
          - macro_btcd_trend: BTC.D趋势 (资金在BTC和altcoin之间流转)
          - macro_risk_appetite: 风险偏好 (altcoin相对BTC强弱)
          - macro_capital_flow: 资金流向 (成交量变化)
          - macro_volatility_regime: 波动率状态 (高波动=风险规避)
          - macro_liquidity: 流动性 (成交量/波动率比值)
        """
        n = len(df)
        features = np.zeros((n, 5))
        
        close = df['close'].values
        volume = df['volume'].values if 'volume' in df.columns else np.ones(n)
        high = df['high'].values
        low = df['low'].values
        
        # BTC.D趋势 (如果有参考资产)
        if ref_df is not None and len(ref_df) >= n:
            ref_close = ref_df['close'].values[:n]
            # 相对强弱 = 目标资产/BTC
            ratio = close / (ref_close + 1e-10)
            ratio_ma20 = pd.Series(ratio).rolling(20, min_periods=5).mean().values
            ratio_ma60 = pd.Series(ratio).rolling(60, min_periods=20).mean().values
            features[:, 0] = (ratio_ma20 > ratio_ma60).astype(float)
            features[:, 1] = np.clip((ratio_ma20 - ratio_ma60) / (ratio_ma60 + 1e-10), -0.3, 0.3)
        else:
            # 无参考资产时，用自身动量替代
            ret20 = pd.Series(close).pct_change(20).fillna(0).values
            features[:, 0] = (ret20 > 0).astype(float)
            features[:, 1] = np.clip(ret20, -0.3, 0.3)
        
        # 成交量变化趋势
        vol_ma20 = pd.Series(volume).rolling(20, min_periods=5).mean().values
        vol_ma60 = pd.Series(volume).rolling(60, min_periods=20).mean().values
        features[:, 2] = np.clip((vol_ma20 - vol_ma60) / (vol_ma60 + 1e-10), -0.5, 0.5)
        
        # 波动率状态
        tr = np.maximum(high - low, np.abs(high - np.roll(close, 1)))
        tr[0] = high[0] - low[0]
        atr20 = pd.Series(tr).rolling(20, min_periods=5).mean().values
        atr_pct = atr20 / (close + 1e-10)
        atr_median = np.nanmedian(atr_pct)
        features[:, 3] = (atr_pct > atr_median * 1.2).astype(float)  # 高波动=1
        
        # 流动性 (成交量/波动率)
        liquidity = vol_ma20 / (atr20 + 1e-10)
        liquidity_pct = pd.Series(liquidity).rank(pct=True).fillna(0.5).values
        features[:, 4] = liquidity_pct
        
        return features
    
    # ============================================================
    # 3. 信号稀有度特征
    # ============================================================
    
    def _signal_rarity_features(self, l1_pred: np.ndarray) -> np.ndarray:
        """
        信号稀有度特征 — 评估信号是否"太频繁"
        
        理论: 好的信号应该是稀有的，频繁出现的信号往往质量较差
        
        特征:
          - signal_rarity_up: 近期做多信号频率 (越低越好)
          - signal_rarity_down: 近期做空信号频率
          - signal_interval: 距离上次同向信号的时间
          - signal_density: 近期信号密度
          - signal_consistency: 近期信号方向一致性
        """
        n = len(l1_pred)
        features = np.zeros((n, 5))
        
        for window in [20, 60]:
            up_count = np.zeros(n)
            down_count = np.zeros(n)
            
            for i in range(window, n):
                recent = l1_pred[i-window:i]
                up_count[i] = np.sum(recent == 1) / window
                down_count[i] = np.sum(recent == -1) / window
            
            if window == 20:
                features[:, 0] = up_count
                features[:, 1] = down_count
            else:
                features[:, 2] = np.abs(up_count - down_count)  # 方向一致性
        
        # 距离上次同向信号的时间
        last_up = -np.ones(n)
        last_down = -np.ones(n)
        for i in range(1, n):
            if l1_pred[i-1] == 1:
                last_up[i] = i - 1
            elif l1_pred[i-1] == -1:
                last_down[i] = i - 1
            last_up[i] = last_up[i-1] if last_up[i] < 0 else last_up[i]
            last_down[i] = last_down[i-1] if last_down[i] < 0 else last_down[i]
        
        features[:, 3] = np.clip((i - last_up) / 60, 0, 1)  # 标准化
        features[:, 4] = np.clip((i - last_down) / 60, 0, 1)
        
        return features
    
    # ============================================================
    # 4. 市场结构特征
    # ============================================================
    
    def _market_structure_features(
        self,
        df: pd.DataFrame,
        cycle_phase: Optional[pd.DataFrame] = None,
    ) -> np.ndarray:
        """
        市场结构特征 — 评估趋势成熟度和反转概率
        
        特征:
          - structure_trend_maturity: 趋势成熟度 (趋势运行了多久)
          - structure_reversal_prob: 反转概率 (极值统计)
          - structure_vol_change: 波动率结构变化
          - structure_trend_age: 趋势年龄 (从突破点到现在)
          - structure_cycle_phase: 库存周期相位
        """
        n = len(df)
        features = np.zeros((n, 5))
        
        close = df['close'].values
        high = df['high'].values
        low = df['low'].values
        
        # EMA趋势
        ema20 = pd.Series(close).rolling(20, min_periods=10).mean().values
        ema60 = pd.Series(close).rolling(60, min_periods=30).mean().values
        trend = (ema20 > ema60).astype(float)
        
        # 趋势成熟度 (趋势持续的K线数)
        trend_duration = np.zeros(n)
        for i in range(60, n):
            if trend[i] == trend[i-1]:
                trend_duration[i] = trend_duration[i-1] + 1
            else:
                trend_duration[i] = 0
        features[:, 0] = np.clip(trend_duration / 100, 0, 1)  # 标准化
        
        # 反转概率 (距离上次极值)
        lookback = min(60, n)
        for i in range(lookback, n):
            window_high = high[i-lookback:i]
            window_low = low[i-lookback:i]
            last_high_idx = np.argmax(window_high)
            last_low_idx = np.argmin(window_low)
            dist_to_high = (lookback - last_high_idx) / lookback
            dist_to_low = (lookback - last_low_idx) / lookback
            
            # 如果距离极值很近，反转概率高
            features[i, 1] = 1 - min(dist_to_high, dist_to_low)
        
        # 波动率结构变化
        tr = np.maximum(high - low, np.abs(high - np.roll(close, 1)))
        tr[0] = high[0] - low[0]
        atr20 = pd.Series(tr).rolling(20, min_periods=5).mean().values
        atr60 = pd.Series(tr).rolling(60, min_periods=20).mean().values
        features[:, 2] = np.clip((atr20 - atr60) / (atr60 + 1e-10), -0.5, 0.5)
        
        # 趋势年龄 (从MA交叉到现在)
        cross = np.sign(ema20 - ema60)
        trend_age = np.zeros(n)
        for i in range(60, n):
            if cross[i] != cross[i-1]:
                trend_age[i] = 0
            else:
                trend_age[i] = trend_age[i-1] + 1
        features[:, 3] = np.clip(trend_age / 100, 0, 1)
        
        # 库存周期相位
        if cycle_phase is not None and 'ic_phase' in cycle_phase.columns:
            features[:, 4] = cycle_phase['ic_phase'].values / 3.0  # 0-1标准化
        
        return features
    
    # ============================================================
    # 5. 跨资产验证特征
    # ============================================================
    
    def _cross_asset_validation_features(
        self,
        df: pd.DataFrame,
        ref_df: Optional[pd.DataFrame] = None,
    ) -> np.ndarray:
        """
        跨资产验证特征 — 用BTC走势验证altcoin信号
        
        特征:
          - cross_beta: 相对BTC的Beta值
          - cross_correlation: 与BTC的相关性
          - cross_momentum_diff: 动量差 (目标资产vs BTC)
          - cross_vol_ratio: 波动率比值
          - cross_lead_lag: 领先/滞后关系
        """
        n = len(df)
        features = np.zeros((n, 5))
        
        if ref_df is None or len(ref_df) < n:
            return features
        
        close = df['close'].values
        ref_close = ref_df['close'].values[:n]
        
        # Beta (滚动回归简化版)
        ret = pd.Series(close).pct_change().fillna(0).values
        ref_ret = pd.Series(ref_close).pct_change().fillna(0).values
        
        for window in [20, 60]:
            beta = np.zeros(n)
            corr = np.zeros(n)
            
            for i in range(window, n):
                y = ret[i-window:i]
                x = ref_ret[i-window:i]
                
                # 简化Beta: cov(y,x) / var(x)
                cov = np.cov(y, x)[0, 1] if len(y) > 1 else 0
                var_x = np.var(x) if len(x) > 1 else 1
                
                beta[i] = cov / (var_x + 1e-10)
                corr[i] = np.corrcoef(y, x)[0, 1] if len(y) > 1 else 0
            
            if window == 20:
                features[:, 0] = np.clip(beta, -3, 3) / 3  # 标准化
                features[:, 1] = np.clip(corr, -1, 1)
            else:
                features[:, 2] = np.clip(beta - features[:, 0] * 3, -1, 1)  # Beta变化
        
        # 动量差
        mom_target = pd.Series(close).pct_change(20).fillna(0).values
        mom_ref = pd.Series(ref_close).pct_change(20).fillna(0).values
        features[:, 3] = np.clip(mom_target - mom_ref, -0.3, 0.3)
        
        # 波动率比值
        tr_target = np.maximum(df['high'].values - df['low'].values, 
                               np.abs(df['high'].values - np.roll(close, 1)))
        tr_ref = np.maximum(ref_df['high'].values[:n] - ref_df['low'].values[:n],
                           np.abs(ref_df['high'].values[:n] - np.roll(ref_close, 1)))
        atr_target = pd.Series(tr_target).rolling(20, min_periods=5).mean().values
        atr_ref = pd.Series(tr_ref).rolling(20, min_periods=5).mean().values
        features[:, 4] = np.clip(atr_target / (atr_ref + 1e-10), 0.5, 2.0) - 1.0
        
        return features
    
    # ============================================================
    # 工具函数
    # ============================================================
    
    def get_feature_names(self) -> List[str]:
        """返回所有L2特征名"""
        names = []
        
        # 1. 时间维度特征
        names.extend([
            'time_hour', 'time_day_of_week', 'time_month_phase',
            'time_season_phase', 'time_since_extreme',
        ])
        
        # 2. 宏观环境特征
        names.extend([
            'macro_btcd_trend', 'macro_risk_appetite', 'macro_capital_flow',
            'macro_volatility_regime', 'macro_liquidity',
        ])
        
        # 3. 信号稀有度特征
        names.extend([
            'signal_rarity_up', 'signal_rarity_down', 'signal_consistency',
            'signal_interval_up', 'signal_interval_down',
        ])
        
        # 4. 市场结构特征
        names.extend([
            'structure_trend_maturity', 'structure_reversal_prob',
            'structure_vol_change', 'structure_trend_age', 'structure_cycle_phase',
        ])
        
        # 5. 跨资产验证特征
        names.extend([
            'cross_beta', 'cross_correlation', 'cross_beta_change',
            'cross_momentum_diff', 'cross_vol_ratio',
        ])
        
        return names


def kelly_criterion(prob_win: float, win_loss_ratio: float) -> float:
    """凯利公式: 计算最优仓位比例"""
    if win_loss_ratio <= 0:
        return 0.0
    f = (prob_win * win_loss_ratio - (1 - prob_win)) / win_loss_ratio
    return max(0.0, min(1.0, f))


def calibrate_probability(proba: np.ndarray, reference: Optional[np.ndarray] = None) -> np.ndarray:
    """概率校准 (ECDF)"""
    if reference is None:
        reference = proba
    sorted_probs = np.sort(reference)
    calibrated = np.searchsorted(sorted_probs, proba, side='left') / (len(sorted_probs) + 1)
    return calibrated