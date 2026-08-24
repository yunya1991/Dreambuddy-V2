"""ML增强的三屏趋势策略

基于趋势延续理论，将ML模型预测作为第三屏（AI屏）：

Screen 1: 大趋势方向（EMA50/100斜率 → 多尺度层级特征）
Screen 2: Elder-ray力量分析（多空力量、背离、衰竭检测）
Screen 3 (AI屏): ML模型预测概率（基于方向+变化+速率三维度特征）

融合逻辑:
- ML预测与趋势同向时：置信度增强 → 更大仓位
- ML预测与趋势反向时：置信度削弱 → 减小仓位或空仓
- Elder-ray背离信号：趋势逆转预警 → 仓位调整

理论参考：Alexander Elder三重滤网系统
- 第一屏确认大趋势方向（潮汐）
- 第二屏用Elder-ray寻找回调中的背离（波浪）
- 第三屏精确入场（涟漪）
"""

from typing import Optional, List, Dict
import numpy as np
import pandas as pd

try:
    from backtest.strategy import BaseStrategy
    from backtest.engine import BacktestEngine
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from backtest.strategy import BaseStrategy
    from backtest.engine import BacktestEngine

from .feature_engineer import TrendFeatureEngineer
from .models import MLModel, create_model, LightGBMModel
from .tuner import ModelTuner


class MLTrendStrategy(BaseStrategy):
    """ML增强的三屏趋势策略

    融合传统趋势指标 + ML多因子模型预测：
    - 同向时：置信度增强 → 更大仓位
    - 反向时：置信度削弱 → 减小仓位或空仓
    """

    def __init__(
        self,
        base_strategy=None,
        model_type: str = 'lightgbm',
        model: Optional[MLModel] = None,
        feature_engineer: Optional[TrendFeatureEngineer] = None,
        ml_confidence_weight: float = 0.3,
        label_lookahead: int = 7,
        min_ml_confidence: float = 0.55,
        warmup_periods: int = 100,
        train_ratio: float = 0.6,
        enable_tuning: bool = False,
        n_trials: int = 20,
    ):
        """
        参数:
            base_strategy: 基础策略（传统三屏），None则纯ML策略
            model_type: ML模型类型
            model: 预训练模型，None则在generate_signals时训练
            feature_engineer: 特征工程，None则用默认
            ml_confidence_weight: ML置信度权重(0-1)
            label_lookahead: 标签前瞻期
            min_ml_confidence: ML最低置信度阈值
            warmup_periods: 预热期
            train_ratio: 训练集比例（用于训练模型）
            enable_tuning: 是否启用超参优化
            n_trials: 超参优化试验次数
        """
        super().__init__(name=f"ml_trend_{model_type}")
        self.base_strategy = base_strategy
        self.model_type = model_type
        self.model = model
        self.feature_engineer = feature_engineer or TrendFeatureEngineer()
        self.ml_confidence_weight = ml_confidence_weight
        self.label_lookahead = label_lookahead
        self.min_ml_confidence = min_ml_confidence
        self.warmup_periods = warmup_periods
        self.train_ratio = train_ratio
        self.enable_tuning = enable_tuning
        self.n_trials = n_trials

    # ------------------------------------------------------------------
    # H3 灰度接入点：EN_FEATUREHUB_TRIPLE_SCREEN=true → FeatureHub；否则原始 FE
    # 集合 triple_screen_only + strip_prefix=True → 列名与原始 FE 100% 一致
    # （T29 验证：列名交集 100%、数值相关性 1.0000、方向一致率 100%）
    # 异常自动回退原始 FE（fail-open）；秒级回滚=设 EN_FEATUREHUB_TRIPLE_SCREEN=false
    # ------------------------------------------------------------------
    def _compute_features(self, prices: pd.DataFrame) -> pd.DataFrame:
        from feature_hub.h3_wrapper import wrap_featurehub
        return wrap_featurehub(
            strategy_name="triple_screen",
            ohlcv_df=prices,
            symbol="BTC",
            set_name="triple_screen_only",
            original_fe_fn=lambda: self.feature_engineer.create_features(
                prices, self.label_lookahead),
            strip_prefix=True,
        )

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        n = len(prices)
        positions = np.zeros(n)

        if n <= self.warmup_periods + self.label_lookahead + 10:
            return pd.Series(positions, index=prices.index, name="position")

        # 1. 提取特征
        features_df = self._compute_features(prices)

        # 如果有预训练模型，用模型的feature_names（可能做过特征选择）
        if self.model is not None and hasattr(self.model, 'feature_names') and self.model.feature_names:
            feature_names = self.model.feature_names
            # 确保所有需要的特征都存在
            missing = [f for f in feature_names if f not in features_df.columns]
            if missing:
                print(f"[警告] 缺失特征: {missing}，ML模型将使用默认置信度0.5")
                feature_names = []
        else:
            feature_names = self.feature_engineer.feature_names

        # 2. 训练模型（如果没有预训练）
        if self.model is None:
            # 去掉含NaN的行
            valid = features_df.dropna(subset=feature_names + ['label'])
            if len(valid) < 50:
                return pd.Series(positions, index=prices.index, name="position")

            # 用前 train_ratio 的数据训练
            train_size = int(len(valid) * self.train_ratio)
            train_data = valid.iloc[:train_size]

            X_train = train_data[feature_names]
            y_train = train_data['label']

            if self.enable_tuning and len(X_train) > 100:
                tuner = ModelTuner(
                    model_type=self.model_type,
                    n_trials=self.n_trials,
                    metric='accuracy',
                )
                tuner.tune(X_train, y_train)
                self.model = tuner.train_best(X_train, y_train)
            else:
                self.model = create_model(self.model_type)
                self.model.fit(X_train, y_train)

        # 3. 计算基础策略信号
        base_signals = None
        if self.base_strategy:
            base_signals = self.base_strategy.generate_signals(prices)

        # 4. 计算ML预测概率
        ml_probs = np.full(n, 0.5)  # 默认0.5 = 无明确方向
        if len(feature_names) > 0:
            for i in range(self.warmup_periods, n):
                if i < len(features_df):
                    row = features_df.iloc[[i]][feature_names]
                    if not row.isna().any().any():
                        try:
                            ml_probs[i] = self.model.predict_proba(row)[0]
                        except Exception:
                            ml_probs[i] = 0.5

        # 5. 融合信号
        for i in range(self.warmup_periods, n):
            ml_prob = ml_probs[i]

            if base_signals is not None:
                base_pos = base_signals.iloc[i]
                base_dir = 1 if base_pos > 0 else (-1 if base_pos < 0 else 0)

                if base_dir == 0:
                    # 基础策略空仓，ML高置信度时可轻仓试探
                    if ml_prob > 0.6:
                        positions[i] = ml_prob * 0.2  # 最多20%仓位
                    elif ml_prob < 0.4:
                        positions[i] = -ml_prob * 0.2
                    else:
                        positions[i] = 0
                else:
                    # 基础策略有方向，ML同向增强，反向减弱
                    ml_dir = 1 if ml_prob > 0.5 else -1
                    ml_conf = abs(ml_prob - 0.5) * 2  # 0-1

                    if ml_dir == base_dir:
                        # 同向：增强仓位
                        boost = 1 + ml_conf * self.ml_confidence_weight
                        positions[i] = base_pos * min(boost, 1.5)
                    else:
                        # 反向：减弱仓位
                        reduction = ml_conf * self.ml_confidence_weight
                        positions[i] = base_pos * max(1 - reduction, 0.2)
            else:
                # 纯ML策略
                if ml_prob > self.min_ml_confidence:
                    positions[i] = (ml_prob - 0.5) * 2  # 映射到 -1 到 1
                elif ml_prob < 1 - self.min_ml_confidence:
                    positions[i] = (ml_prob - 0.5) * 2
                else:
                    positions[i] = 0

        # 限制仓位在 [-1, 1]
        positions = np.clip(positions, -1, 1)
        return pd.Series(positions, index=prices.index, name="position")

    def get_ml_predictions(self, prices: pd.DataFrame) -> pd.Series:
        """获取ML模型的预测概率序列（用于分析）"""
        if self.model is None:
            return pd.Series(dtype=float)

        features_df = self._compute_features(prices)
        feature_names = self.feature_engineer.feature_names

        probs = []
        for i in range(len(prices)):
            if i < self.warmup_periods or i >= len(features_df):
                probs.append(0.5)
                continue
            row = features_df.iloc[[i]][feature_names]
            if row.isna().any().any():
                probs.append(0.5)
            else:
                try:
                    probs.append(self.model.predict_proba(row)[0])
                except Exception:
                    probs.append(0.5)

        return pd.Series(probs, index=prices.index, name="ml_probability")

    def get_feature_importance(self) -> pd.Series:
        """获取特征重要性"""
        if self.model is None:
            return pd.Series(dtype=float)
        return self.model.feature_importance()


def train_ml_strategy(
    prices: pd.DataFrame,
    base_strategy=None,
    model_type: str = 'lightgbm',
    label_lookahead: int = 7,
    train_ratio: float = 0.6,
    enable_tuning: bool = False,
    n_trials: int = 20,
) -> MLTrendStrategy:
    """训练一个完整的ML增强策略

    便捷函数，返回训练好的MLTrendStrategy实例
    """
    strategy = MLTrendStrategy(
        base_strategy=base_strategy,
        model_type=model_type,
        model=None,
        label_lookahead=label_lookahead,
        warmup_periods=50,
        train_ratio=train_ratio,
        enable_tuning=enable_tuning,
        n_trials=n_trials,
    )
    # 生成信号时会自动训练模型
    _ = strategy.generate_signals(prices)
    return strategy
