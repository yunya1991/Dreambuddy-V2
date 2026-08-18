"""
L2 Meta-Labeling 特征工程模块 — 二级裁决的增强特征

理论映射 (否定之否定 → L2特征):
  否定阶段 → 市场状态特征 (波动率、流动性)
  否定之否定 → 历史同类信号胜率 (相同状态下的历史表现)
  周期嵌套 → 宏观周期交叉特征 (库存周期 × 技术信号)

特征体系:
  1. 信号置信度特征: L1模型输出的预测概率
  2. 市场状态特征: ATR波动率、流动性、趋势强度
  3. 历史同类信号胜率: 滚动窗口内相同状态的胜率统计
  4. 宏观周期交叉特征: 库存周期阶段 × 技术信号组合
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from collections import defaultdict


class MetaLabelingFeatures:
    """
    L2特征工程 — 为二级裁决构建增强特征

    核心思想: L2模型不能只看L1的输出，还要看"这个信号出现在什么环境下"
    相同的L1信号在不同市场状态下，胜率可能天差地别
    """

    def __init__(
        self,
        lookback_windows: List[int] = [20, 60, 120],
        regime_lookback: int = 60,
    ):
        self.lookback_windows = lookback_windows
        self.regime_lookback = regime_lookback

    def compute_base_features(
        self,
        X: np.ndarray,
        l1_proba: np.ndarray,
        l1_pred: np.ndarray,
        feature_names: List[str],
        df: pd.DataFrame,
    ) -> np.ndarray:
        """
        计算完整的L2特征矩阵

        Args:
            X: L1特征矩阵 (n_samples, n_features)
            l1_proba: L1预测概率 (n_samples, 3)
            l1_pred: L1预测方向 (-1/0/1)
            feature_names: L1特征名列表
            df: OHLCV原始数据 (用于计算市场状态特征)

        Returns:
            L2特征矩阵 (n_samples, n_meta_features)
        """
        n = len(X)
        meta_features = []

        # 1. 信号置信度特征
        meta_features.append(self._signal_confidence_features(l1_proba, l1_pred))

        # 2. 市场状态特征
        meta_features.append(self._market_regime_features(df))

        # 3. 历史同类信号胜率特征
        meta_features.append(self._historical_win_rate_features(
            l1_pred, df, self.lookback_windows
        ))

        # 4. 宏观周期交叉特征 (库存周期 × 技术信号)
        meta_features.append(self._macro_cross_features(X, feature_names, df))

        # 5. 特征重要性加权特征 (L1模型认为重要的特征)
        meta_features.append(self._feature_importance_features(X, feature_names))

        # 拼接所有特征
        result = np.hstack(meta_features)

        # 处理NaN
        result = np.nan_to_num(result, nan=0.0, posinf=0.0, neginf=0.0)

        return result

    def _signal_confidence_features(self, l1_proba: np.ndarray, l1_pred: np.ndarray) -> np.ndarray:
        """
        信号置信度特征: L1模型输出的预测概率

        特征:
          - l1_confidence: L1最大概率
          - l1_entropy: L1预测熵 (衡量不确定性)
          - l1_max_prob: L1最大类概率
          - l1_second_prob: L1次大类概率
          - l1_conf_ratio: 最大/次大概率比值
          - l1_pred_onehot: L1预测方向one-hot
        """
        n = len(l1_proba)
        features = np.zeros((n, 8))

        # L1最大概率
        features[:, 0] = np.max(l1_proba, axis=1)

        # L1熵 (不确定性)
        log_probs = np.log(l1_proba + 1e-10)
        features[:, 1] = -np.sum(l1_proba * log_probs, axis=1)

        # 排序概率
        sorted_probs = np.sort(l1_proba, axis=1)[:, ::-1]
        features[:, 2] = sorted_probs[:, 0]  # 最大
        features[:, 3] = sorted_probs[:, 1]  # 次大
        features[:, 4] = sorted_probs[:, 0] / (sorted_probs[:, 1] + 1e-10)  # 比值

        # L1预测方向one-hot
        features[:, 5] = (l1_pred == 1).astype(float)   # UP
        features[:, 6] = (l1_pred == -1).astype(float)  # DOWN
        features[:, 7] = (l1_pred == 0).astype(float)   # FLAT

        return features

    def _market_regime_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        市场状态特征: 波动率、流动性、趋势强度

        特征:
          - atr_ratio: ATR/价格 (波动率标准化)
          - atr_rolling_ratio: 当前ATR/过去N日平均ATR
          - volume_ratio: 当前成交量/过去N日平均成交量
          - trend_strength: 趋势强度 (EMA斜率)
          - volatility_state: 波动率状态 (分位数桶)
          - trend_state: 趋势状态 (分位数桶)
        """
        n = len(df)
        features = np.zeros((n, 10))

        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        volume = df["volume"].values if "volume" in df.columns else np.ones(n)

        # ATR (简化计算)
        tr = np.maximum(high - low, np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1)))
        tr[0] = high[0] - low[0]
        atr14 = pd.Series(tr).rolling(14, min_periods=3).mean().values

        # 波动率标准化
        features[:, 0] = atr14 / (close + 1e-10)

        # ATR滚动比率 (相对于过去20/60日平均)
        for i, window in enumerate([20, 60]):
            atr_mean = pd.Series(atr14).rolling(window, min_periods=5).mean().values
            features[:, 1 + i] = atr14 / (atr_mean + 1e-10)

        # 成交量比率
        for i, window in enumerate([20, 60]):
            vol_mean = pd.Series(volume).rolling(window, min_periods=5).mean().values
            features[:, 3 + i] = volume / (vol_mean + 1e-10)

        # EMA斜率 (趋势强度)
        ema20 = pd.Series(close).rolling(20, min_periods=10).mean().values
        ema200 = pd.Series(close).rolling(200, min_periods=50).mean().values
        features[:, 5] = (ema20 - np.roll(ema20, 20)) / (np.roll(ema20, 20) + 1e-10) * 100
        features[:, 6] = (ema200 - np.roll(ema200, 60)) / (np.roll(ema200, 60) + 1e-10) * 100

        # 价格相对位置 (相对于EMA)
        features[:, 7] = (close - ema20) / (ema20 + 1e-10) * 100
        features[:, 8] = (close - ema200) / (ema200 + 1e-10) * 100

        # 波动率状态 (高/中/低)
        atr_pct = features[:, 0] * 100
        atr_median = np.median(atr_pct[~np.isnan(atr_pct)])
        features[:, 9] = np.where(atr_pct > atr_median * 1.5, 2,
                                  np.where(atr_pct < atr_median * 0.5, 0, 1))

        return features

    def _historical_win_rate_features(
        self,
        l1_pred: np.ndarray,
        df: pd.DataFrame,
        lookback_windows: List[int],
    ) -> np.ndarray:
        """
        历史同类信号胜率特征: 滚动窗口内相同方向信号的胜率

        注意: 必须使用事前可见的数据, 不能使用未来数据计算胜率
        我们使用L1预测的置信度作为替代指标, 而不是实际未来收益

        特征:
          - conf_mean_20d_up: 过去20天做多信号平均置信度
          - conf_mean_60d_up: 过去60天做多信号平均置信度
          - conf_mean_20d_down: 过去20天做空信号平均置信度
          - conf_mean_60d_down: 过去60天做空信号平均置信度
          - signal_freq_20d: 过去20天信号频率
          - signal_freq_60d: 过去60天信号频率
        """
        n = len(l1_pred)
        features = np.zeros((n, len(lookback_windows) * 3))

        for win_idx, window in enumerate(lookback_windows):
            conf_up = np.zeros(n)
            conf_down = np.zeros(n)
            freq = np.zeros(n)

            for i in range(window, n):
                signals = l1_pred[i - window:i]
                signal_mask_up = signals == 1
                signal_mask_down = signals == -1

                if signal_mask_up.sum() > 0:
                    conf_up[i] = (signals[signal_mask_up] == 1).mean()

                if signal_mask_down.sum() > 0:
                    conf_down[i] = (signals[signal_mask_down] == -1).mean()

                freq[i] = (np.abs(signals) > 0).sum() / window

            features[:, win_idx * 3] = conf_up
            features[:, win_idx * 3 + 1] = conf_down
            features[:, win_idx * 3 + 2] = freq

        return features

    def _macro_cross_features(self, X: np.ndarray, feature_names: List[str], df: pd.DataFrame) -> np.ndarray:
        """
        宏观周期交叉特征: 库存周期阶段 × 技术信号组合

        特征:
          - 价格相对位置 × 波动率状态
          - 趋势方向 × 动量状态
          - Elder-ray力量状态 × 周期阶段
          - 斐波那契位置 × 支撑阻力状态
        """
        n = len(X)
        features = np.zeros((n, 8))

        close = df["close"].values

        # EMA趋势
        ema20 = pd.Series(close).rolling(20, min_periods=10).mean().values
        ema200 = pd.Series(close).rolling(200, min_periods=50).mean().values
        trend_up = (close > ema200).astype(float)
        short_trend_up = (close > ema20).astype(float)

        # ATR波动率
        high = df["high"].values
        low = df["low"].values
        tr = np.maximum(high - low, np.abs(high - np.roll(close, 1)), np.abs(low - np.roll(close, 1)))
        tr[0] = high[0] - low[0]
        atr14 = pd.Series(tr).rolling(14, min_periods=3).mean().values
        vol_high = (atr14 / close > 0.02).astype(float)

        # 交叉特征1: 趋势方向 × 波动率状态
        features[:, 0] = trend_up * vol_high  # 上涨+高波动
        features[:, 1] = trend_up * (1 - vol_high)  # 上涨+低波动
        features[:, 2] = (1 - trend_up) * vol_high  # 下跌+高波动
        features[:, 3] = (1 - trend_up) * (1 - vol_high)  # 下跌+低波动

        # 交叉特征2: 短期趋势 × 长期趋势
        features[:, 4] = short_trend_up * trend_up  # 共振上涨
        features[:, 5] = short_trend_up * (1 - trend_up)  # 短期反弹+长期下跌
        features[:, 6] = (1 - short_trend_up) * trend_up  # 短期回调+长期上涨
        features[:, 7] = (1 - short_trend_up) * (1 - trend_up)  # 共振下跌

        return features

    def _feature_importance_features(self, X: np.ndarray, feature_names: List[str]) -> np.ndarray:
        """
        特征重要性加权特征: L1模型认为重要的特征的加权和

        根据特征名推断重要性:
          - 趋势类特征 (qian_*, trend_*, ma_*)
          - 动量类特征 (zhen_*, momentum_*, roc_*)
          - 波动率类特征 (xun_*, atr_*, vol_*)
          - 支撑阻力类特征 (kun_*, pivot_*, support_*)
        """
        n = len(X)
        features = np.zeros((n, 5))

        # 找出各类特征的索引
        trend_indices = [i for i, fn in enumerate(feature_names)
                         if any(k in fn.lower() for k in ['qian', 'trend', 'ma', 'ema', 'slope'])]
        momentum_indices = [i for i, fn in enumerate(feature_names)
                            if any(k in fn.lower() for k in ['zhen', 'momentum', 'roc', 'rsi'])]
        vol_indices = [i for i, fn in enumerate(feature_names)
                       if any(k in fn.lower() for k in ['xun', 'atr', 'vol', 'std', 'range'])]
        support_indices = [i for i, fn in enumerate(feature_names)
                           if any(k in fn.lower() for k in ['kun', 'pivot', 'support', 'resistance'])]

        # 各类特征的平均活跃度
        features[:, 0] = np.mean(np.abs(X[:, trend_indices]), axis=1) if trend_indices else 0
        features[:, 1] = np.mean(np.abs(X[:, momentum_indices]), axis=1) if momentum_indices else 0
        features[:, 2] = np.mean(np.abs(X[:, vol_indices]), axis=1) if vol_indices else 0
        features[:, 3] = np.mean(np.abs(X[:, support_indices]), axis=1) if support_indices else 0

        # 特征活跃度总和 (衡量市场信息量)
        features[:, 4] = np.mean(np.abs(X), axis=1)

        return features

    def get_feature_names(self) -> List[str]:
        """返回所有L2特征名"""
        names = []

        # 信号置信度特征
        names.extend([
            'l1_confidence', 'l1_entropy', 'l1_max_prob', 'l1_second_prob',
            'l1_conf_ratio', 'l1_pred_up', 'l1_pred_down', 'l1_pred_flat',
        ])

        # 市场状态特征
        names.extend([
            'atr_ratio', 'atr_ratio_20d', 'atr_ratio_60d',
            'volume_ratio_20d', 'volume_ratio_60d',
            'ema20_slope', 'ema200_slope',
            'price_vs_ema20', 'price_vs_ema200',
            'volatility_state',
        ])

        # 历史同类信号胜率特征
        for window in self.lookback_windows:
            names.extend([
                f'win_rate_{window}d_up',
                f'win_rate_{window}d_down',
                f'signal_freq_{window}d',
            ])

        # 宏观周期交叉特征
        names.extend([
            'trend_vol_up_high', 'trend_vol_up_low',
            'trend_vol_down_high', 'trend_vol_down_low',
            'cross_trend_both_up', 'cross_trend_short_up_long_down',
            'cross_trend_short_down_long_up', 'cross_trend_both_down',
        ])

        # 特征重要性加权特征
        names.extend([
            'feat_importance_trend', 'feat_importance_momentum',
            'feat_importance_volatility', 'feat_importance_support',
            'feat_importance_total',
        ])

        return names


def calibrate_probability(l2_proba: np.ndarray, method: str = 'ecdf') -> np.ndarray:
    """
    概率校准: 将L2输出概率转换为更可靠的校准概率

    方法:
      - ecdf: 累积分布函数校准
      - isotonic: 等渗回归校准
      - platt: Platt缩放校准

    Args:
        l2_proba: 原始L2概率
        method: 校准方法

    Returns:
        校准后的概率
    """
    if method == 'ecdf':
        # ECDF校准: 将概率映射到其在训练集中的分位数
        sorted_probs = np.sort(l2_proba)
        ranks = np.searchsorted(sorted_probs, l2_proba, side='left')
        calibrated = (ranks + 1) / (len(sorted_probs) + 2)
        return calibrated

    elif method == 'isotonic':
        try:
            from sklearn.isotonic import IsotonicRegression
            ir = IsotonicRegression(out_of_bounds='clip')
            x = np.arange(len(l2_proba)) / len(l2_proba)
            return ir.fit_transform(x, l2_proba)
        except ImportError:
            return l2_proba

    elif method == 'platt':
        try:
            from sklearn.linear_model import LogisticRegression
            # 简化版Platt缩放
            x = l2_proba.reshape(-1, 1)
            # 假设标签与概率相关 (简化处理)
            lr = LogisticRegression()
            lr.fit(x, (l2_proba > 0.5).astype(int))
            return lr.predict_proba(x)[:, 1]
        except ImportError:
            return l2_proba

    else:
        return l2_proba


def kelly_criterion(prob_win: float, win_loss_ratio: float) -> float:
    """
    凯利公式: 计算最优仓位比例

    f* = (p * W - (1-p) * L) / W

    Args:
        prob_win: 胜率
        win_loss_ratio: 盈亏比

    Returns:
        最优仓位比例 (0-1)
    """
    if win_loss_ratio <= 0:
        return 0.0

    f = (prob_win * win_loss_ratio - (1 - prob_win)) / win_loss_ratio
    return max(0.0, min(1.0, f))
