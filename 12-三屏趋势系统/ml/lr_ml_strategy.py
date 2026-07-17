"""最小阻力 AI 策略

将最小阻力三维特征 + LightGBM 模型 与规则引擎融合：

架构：
┌─────────────────────────────────────────────────────────┐
│  输入：三屏K线数据（周/日/小周期）+ 基本面数据            │
├─────────────────────────────────────────────────────────┤
│  特征工程：lr_feature_engineer                           │
│    ├─ 五维阻力特征（日/周）                              │
│    ├─ 三维动态特征（速度/加速度）                         │
│    ├─ 跨周期一致性特征                                   │
│    └─ 多窗口统计特征                                     │
├─────────────────────────────────────────────────────────┤
│  AI 模型：LightGBM（Walk-Forward 滚动训练）              │
│    预测：未来 N 日上涨概率                               │
├─────────────────────────────────────────────────────────┤
│  规则引擎约束：                                          │
│    ├─ 周线方向 = 大趋势方向（潮汐约束）                   │
│    ├─ 趋势强度阈值 = 强趋势时仓位放大                     │
│    └─ 量变积累信号 = 反转预警仓位收缩                    │
├─────────────────────────────────────────────────────────┤
│  输出：方向 + 置信度 + 仓位                              │
└─────────────────────────────────────────────────────────┘

标签定义：
- 二分类：未来 label_lookahead 日收盘价 > 当前收盘价 → 1（上涨）
- 回归目标：未来收益率（可选，用于置信度校准）
"""

from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest.strategy import BaseStrategy
from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from ml.models import LightGBMModel


def _resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """将日线数据重采样为周线（用于测试/回测）"""
    weekly = df.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()
    return weekly


class LeastResistanceAIStrategy(BaseStrategy):
    """最小阻力 AI 增强策略

    融合规则引擎（最小阻力方向）+ LightGBM AI 预测：
    - AI 预测同向 → 置信度增强 → 仓位放大
    - AI 预测反向 → 置信度削弱 → 仓位减小或空仓
    - Walk-Forward 滚动训练，避免未来函数和过拟合
    """

    def __init__(
        self,
        label_lookahead: int = 7,
        train_window: int = 365,
        retrain_interval: int = 30,
        ml_weight: float = 0.4,
        min_ml_confidence: float = 0.55,
        weekly_lr_weight: float = 0.5,
        enable_walk_forward: bool = True,
        feature_engineer: Optional[LeastResistanceFeatureEngineer] = None,
        model: Optional[LightGBMModel] = None,
        fundamental_data: Optional[Dict] = None,
    ):
        """
        参数:
            label_lookahead: 标签前瞻天数（预测未来 N 日方向）
            train_window: 滚动训练窗口（天）
            retrain_interval: 重训练间隔（天）
            ml_weight: ML 预测在最终决策中的权重 (0-1)
            min_ml_confidence: ML 最低置信度阈值（低于此值不参与决策）
            weekly_lr_weight: 周线规则引擎权重（大趋势约束）
            enable_walk_forward: 是否启用 Walk-Forward 滚动训练
            feature_engineer: 特征工程器，None 则用默认
            model: 预训练模型，None 则在回测中动态训练
            fundamental_data: 基本面数据
        """
        super().__init__(name="lr_ai")
        self.label_lookahead = label_lookahead
        self.train_window = train_window
        self.retrain_interval = retrain_interval
        self.ml_weight = ml_weight
        self.min_ml_confidence = min_ml_confidence
        self.weekly_lr_weight = weekly_lr_weight
        self.enable_walk_forward = enable_walk_forward
        self.feature_engineer = feature_engineer or LeastResistanceFeatureEngineer()
        self.model = model
        self.fundamental_data = fundamental_data

        self._last_train_idx = -1
        self._prediction_cache: Dict[int, Tuple[str, float]] = {}

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """生成仓位信号

        参数:
            prices: 日线 OHLCV 数据

        返回:
            pd.Series: 仓位（-1 到 1）
        """
        n = len(prices)
        positions = np.zeros(n)

        if n < 120:
            return pd.Series(positions, index=prices.index, name="position")

        # 重采样周线
        weekly_df = _resample_to_weekly(prices)
        if len(weekly_df) < 30:
            return pd.Series(positions, index=prices.index, name="position")

        # 提取特征
        try:
            features_df = self.feature_engineer.create_features(
                weekly_df, prices,
                fundamental_data=self.fundamental_data,
                label_lookahead=self.label_lookahead,
            )
        except Exception as e:
            print(f"  [WARN] 特征提取失败: {e}")
            return pd.Series(positions, index=prices.index, name="position")

        feature_cols = [c for c in features_df.columns if not c.startswith("label_")]
        label_col = "label_direction"

        # 有效数据起始位置（去除预热期 NaN）
        first_valid = features_df[feature_cols].dropna().index
        if len(first_valid) == 0:
            return pd.Series(positions, index=prices.index, name="position")
        start_idx = features_df.index.get_loc(first_valid[0])

        # ===== Walk-Forward 滚动训练与预测 =====
        if self.enable_walk_forward:
            positions = self._walk_forward_predict(
                features_df, feature_cols, label_col,
                start_idx, n, prices.index
            )
        else:
            # 单次训练（不推荐，会有未来函数）
            positions = self._single_train_predict(
                features_df, feature_cols, label_col,
                start_idx, n, prices.index
            )

        return pd.Series(positions, index=prices.index, name="position")

    def _walk_forward_predict(
        self,
        features_df: pd.DataFrame,
        feature_cols: List[str],
        label_col: str,
        start_idx: int,
        n: int,
        price_index: pd.Index,
    ) -> np.ndarray:
        """Walk-Forward 滚动训练与预测"""
        positions = np.zeros(n)
        current_model = None

        for i in range(start_idx, n):
            # 检查是否需要重训练
            need_train = (
                current_model is None or
                (i - self._last_train_idx) >= self.retrain_interval
            )

            if need_train and i >= self.train_window + self.label_lookahead + 10:
                # 训练窗口：[i - train_window, i - label_lookahead - 1]
                train_end = i - self.label_lookahead - 1
                train_start = max(start_idx, train_end - self.train_window)

                if train_end > train_start + 50:
                    train_data = features_df.iloc[train_start:train_end].dropna(subset=feature_cols + [label_col])

                    if len(train_data) >= 100:
                        X_train = train_data[feature_cols]
                        y_train = train_data[label_col]

                        current_model = LightGBMModel()
                        try:
                            current_model.fit(X_train, y_train)
                            self._last_train_idx = i
                        except Exception as e:
                            print(f"  [WARN] 第 {i} 行训练失败: {e}")
                            current_model = None

            # 预测
            if current_model is not None:
                try:
                    row = features_df.iloc[[i]][feature_cols]
                    if not row.isna().any().any():
                        prob = current_model.predict_proba(row)[0]
                        direction, confidence = self._fuse_decision(
                            features_df, i, prob
                        )
                        positions[i] = self._direction_to_position(direction, confidence)
                except Exception:
                    pass

        return positions

    def _single_train_predict(
        self,
        features_df: pd.DataFrame,
        feature_cols: List[str],
        label_col: str,
        start_idx: int,
        n: int,
        price_index: pd.Index,
    ) -> np.ndarray:
        """单次训练（仅用于快速验证，会有未来函数）"""
        positions = np.zeros(n)

        train_data = features_df.dropna(subset=feature_cols + [label_col])
        if len(train_data) < 100:
            return positions

        X_train = train_data[feature_cols]
        y_train = train_data[label_col]

        model = LightGBMModel()
        try:
            model.fit(X_train, y_train)
        except Exception:
            return positions

        for i in range(start_idx, n):
            try:
                row = features_df.iloc[[i]][feature_cols]
                if not row.isna().any().any():
                    prob = model.predict_proba(row)[0]
                    direction, confidence = self._fuse_decision(
                        features_df, i, prob
                    )
                    positions[i] = self._direction_to_position(direction, confidence)
            except Exception:
                pass

        return positions

    def _fuse_decision(
        self,
        features_df: pd.DataFrame,
        idx: int,
        ml_prob: float,
    ) -> Tuple[str, float]:
        """融合 AI 预测 + 规则引擎

        参数:
            features_df: 特征 DataFrame
            idx: 当前行索引
            ml_prob: ML 预测的上涨概率

        返回:
            (direction, confidence): 方向（LONG/SHORT/NEUTRAL）和置信度
        """
        row = features_df.iloc[idx]

        # 规则引擎方向（基于周线阻力差）
        weekly_dir = row.get("weekly_res_diff", 0)
        weekly_conf = row.get("weekly_confidence", 0)
        daily_dir = row.get("daily_res_diff", 0)
        daily_conf = row.get("daily_confidence", 0)

        # 规则引擎方向判定
        if weekly_dir > 0.05:
            rule_direction = "LONG"
            rule_confidence = weekly_conf * self.weekly_lr_weight + daily_conf * (1 - self.weekly_lr_weight)
        elif weekly_dir < -0.05:
            rule_direction = "SHORT"
            rule_confidence = weekly_conf * self.weekly_lr_weight + daily_conf * (1 - self.weekly_lr_weight)
        else:
            # 周线中性，看日线
            if daily_dir > 0.05:
                rule_direction = "LONG"
                rule_confidence = daily_conf * 0.5
            elif daily_dir < -0.05:
                rule_direction = "SHORT"
                rule_confidence = daily_conf * 0.5
            else:
                rule_direction = "NEUTRAL"
                rule_confidence = 0.0

        # ML 方向判定
        if ml_prob > 0.55:
            ml_direction = "LONG"
            ml_confidence = (ml_prob - 0.5) * 2  # 0.5-1.0 映射到 0-1.0
        elif ml_prob < 0.45:
            ml_direction = "SHORT"
            ml_confidence = (0.5 - ml_prob) * 2
        else:
            ml_direction = "NEUTRAL"
            ml_confidence = 0.0

        # ML 置信度过低则不参与
        if ml_confidence < self.min_ml_confidence:
            return rule_direction, rule_confidence

        # ===== 融合逻辑 =====
        # 同向 → 置信度增强
        if rule_direction == ml_direction and rule_direction != "NEUTRAL":
            final_confidence = (
                rule_confidence * (1 - self.ml_weight) +
                ml_confidence * self.ml_weight
            )
            final_direction = rule_direction
        # 反向 → 置信度削弱
        elif rule_direction != ml_direction and rule_direction != "NEUTRAL" and ml_direction != "NEUTRAL":
            final_confidence = max(0.0, rule_confidence * 0.5 - ml_confidence * self.ml_weight)
            if final_confidence < 0.2:
                final_direction = "NEUTRAL"
            else:
                final_direction = rule_direction
        # 规则中性，ML 有方向
        elif rule_direction == "NEUTRAL" and ml_direction != "NEUTRAL":
            final_direction = ml_direction
            final_confidence = ml_confidence * 0.6  # 没有大趋势支撑，权重打折
        # ML 中性，规则有方向
        else:
            final_direction = rule_direction
            final_confidence = rule_confidence

        return final_direction, min(final_confidence, 1.0)

    def _direction_to_position(self, direction: str, confidence: float) -> float:
        """方向 + 置信度 → 仓位"""
        if direction == "LONG":
            return min(confidence, 1.0)
        elif direction == "SHORT":
            return -min(confidence, 1.0)
        else:
            return 0.0

    def get_feature_importance(self) -> pd.Series:
        """获取特征重要性（需先训练）"""
        if self.model is not None:
            return self.model.feature_importance()
        return pd.Series()
