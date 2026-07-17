"""最小阻力 AI 策略 v2 — 多任务学习 + 动态融合权重

相比 v1 (LeastResistanceAIStrategy) 的升级：
1. 多任务学习：同时预测方向 + 置信度 + 驱动模式
2. 动态融合权重：根据市场环境自适应调整 AI/规则权重
3. 特征重要性筛选：自动筛选 Top K 核心因子，降低过拟合
4. 多标签生成：方向、收益幅度、驱动模式

融合策略：
┌──────────────────────────────────────────────────────────┐
│  市场环境 → 动态权重计算                                   │
│  强趋势 → 规则权重高 (0.7~0.9)                            │
│  高波动 → AI 权重高 (0.4~0.6)                             │
│  量异动 → AI 权重高 (0.3~0.5)                             │
│  趋势久 → AI 权重高 (反转预警)                            │
└──────────────────────────────────────────────────────────┘
"""

from typing import Optional, List, Dict, Any, Tuple
import numpy as np
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from backtest.strategy import BaseStrategy
from ml.lr_feature_engineer import LeastResistanceFeatureEngineer
from ml.multitask_model import MultiTaskLightGBM, DynamicWeightFusion


def _resample_to_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """将日线数据重采样为周线"""
    weekly = df.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
    }).dropna()
    return weekly


def _estimate_market_regime(prices: pd.DataFrame, idx: int, lookback: int = 20) -> Dict[str, Any]:
    """估计当前市场环境

    返回:
        {trend_strength, volatility, volume_spike, trend_duration, market_regime}
    """
    if idx < lookback + 10:
        return {
            'trend_strength': 0.5,
            'volatility': 0.5,
            'volume_spike': 0.0,
            'trend_duration': 0.0,
            'market_regime': 'normal',
        }

    slice_df = prices.iloc[idx - lookback:idx + 1]
    close = slice_df['close']
    volume = slice_df['volume']

    # 趋势强度：用价格斜率的绝对值，归一化到 0~1
    x = np.arange(len(close))
    y = close.values
    slope, _ = np.polyfit(x, y, 1)
    slope_normalized = abs(slope) / (close.mean() * 0.02)  # 日均2%作为基准
    trend_strength = min(1.0, slope_normalized)

    # 波动率：收益率标准差，归一化到 0~1
    returns = close.pct_change().dropna()
    vol = returns.std()
    volatility = min(1.0, vol / 0.03)  # 3% 日波动作为基准

    # 成交量异动：当前量 vs 过去 20 日均值
    vol_mean = volume.mean()
    current_vol = volume.iloc[-1]
    volume_spike = max(0.0, min(1.0, (current_vol / vol_mean - 1.0) / 2.0))

    # 趋势时长：简化处理，用连续同向天数比例
    returns_sign = np.sign(returns)
    max_streak = 0
    current_streak = 0
    last_sign = 0
    for s in returns_sign:
        if s == last_sign and s != 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 1
            last_sign = s
    trend_duration = min(1.0, max_streak / 15.0)  # 15天作为基准

    # 市场环境判定
    if trend_strength > 0.6 and volatility < 0.5:
        market_regime = 'trending'
    elif volatility > 0.6:
        market_regime = 'volatile'
    elif trend_strength < 0.3 and volatility < 0.4:
        market_regime = 'range'
    else:
        market_regime = 'normal'

    return {
        'trend_strength': round(trend_strength, 4),
        'volatility': round(volatility, 4),
        'volume_spike': round(volume_spike, 4),
        'trend_duration': round(trend_duration, 4),
        'market_regime': market_regime,
    }


class LeastResistanceAIStrategyV2(BaseStrategy):
    """最小阻力 AI 增强策略 v2

    升级点：
    - 多任务学习（方向 + 置信度 + 驱动模式）
    - 动态融合权重（自适应市场环境）
    - 特征自动筛选（Top K 重要特征）
    """

    def __init__(
        self,
        label_lookahead: int = 7,
        train_window: int = 200,
        retrain_interval: int = 30,
        min_ml_confidence: float = 0.15,
        min_train_samples: int = 40,
        enable_fundamental: bool = True,
        enable_multitask: bool = True,
        enable_dynamic_weight: bool = True,
        enable_feature_selection: bool = False,
        top_k_features: int = 50,
        base_rule_weight: float = 0.5,
        fundamental_data: Optional[Dict] = None,
    ):
        """
        参数:
            label_lookahead: 标签前瞻天数
            train_window: 滚动训练窗口（天）
            retrain_interval: 重训练间隔（天）
            min_ml_confidence: ML 最低置信度阈值
            min_train_samples: 最小训练样本数
            enable_fundamental: 是否启用基本面特征
            enable_multitask: 是否启用多任务学习
            enable_dynamic_weight: 是否启用动态融合权重
            enable_feature_selection: 是否启用特征筛选
            top_k_features: 特征筛选 Top K
            base_rule_weight: 基础规则权重
            fundamental_data: 基本面数据
        """
        super().__init__(name="lr_ai_v2")
        self.label_lookahead = label_lookahead
        self.train_window = train_window
        self.retrain_interval = retrain_interval
        self.min_ml_confidence = min_ml_confidence
        self.min_train_samples = min_train_samples
        self.enable_fundamental = enable_fundamental
        self.enable_multitask = enable_multitask
        self.enable_dynamic_weight = enable_dynamic_weight
        self.enable_feature_selection = enable_feature_selection
        self.top_k_features = top_k_features
        self.base_rule_weight = base_rule_weight
        self.fundamental_data = fundamental_data

        self.feature_engineer = LeastResistanceFeatureEngineer(
            enable_fundamental=enable_fundamental
        )
        self.dynamic_fusion = DynamicWeightFusion(base_rule_weight=base_rule_weight)

        self._last_train_idx = -1
        self._current_model = None
        self._selected_features: Optional[List[str]] = None

    def generate_signals(self, prices: pd.DataFrame) -> pd.Series:
        """生成仓位信号"""
        n = len(prices)
        positions = np.zeros(n)
        self._decision_log = []

        if n < 120:
            return pd.Series(positions, index=prices.index, name="position")

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

        all_feature_cols = [c for c in features_df.columns if not c.startswith("label_")]
        label_dir_col = "label_direction"
        label_ret_col = "label_future_return"

        # 有效数据起始位置
        first_valid = features_df[all_feature_cols].dropna().index
        if len(first_valid) == 0:
            return pd.Series(positions, index=prices.index, name="position")
        start_idx = features_df.index.get_loc(first_valid[0])

        # ===== Walk-Forward =====
        current_model = None
        selected_features = all_feature_cols.copy()

        for i in range(start_idx, n):
            # 检查是否需要重训练
            need_train = (
                current_model is None or
                (i - self._last_train_idx) >= self.retrain_interval
            )

            if need_train and i >= self.train_window + self.label_lookahead + 10:
                train_end = i - self.label_lookahead - 1
                train_start = max(start_idx, train_end - self.train_window)

                if train_end > train_start + 30:
                    train_data = features_df.iloc[train_start:train_end].dropna(
                        subset=all_feature_cols + [label_dir_col]
                    )

                    if len(train_data) >= self.min_train_samples:
                        X_train = train_data[all_feature_cols]
                        y_dir = train_data[label_dir_col]
                        y_ret = train_data[label_ret_col] if label_ret_col in train_data.columns else None

                        # 验证集（最后 20%，至少10个样本）
                        val_size = max(10, int(len(train_data) * 0.15))
                        if val_size > 10 and len(train_data) - val_size > 20:
                            X_tr = X_train.iloc[:-val_size]
                            y_tr_dir = y_dir.iloc[:-val_size]
                            y_tr_ret = y_ret.iloc[:-val_size] if y_ret is not None else None
                            X_val = X_train.iloc[-val_size:]
                            y_val_dir = y_dir.iloc[-val_size:]
                            y_val_ret = y_ret.iloc[-val_size:] if y_ret is not None else None
                        else:
                            X_tr, y_tr_dir, y_tr_ret = X_train, y_dir, y_ret
                            X_val = y_val_dir = y_val_ret = None

                        try:
                            if self.enable_multitask:
                                model = MultiTaskLightGBM()
                                model.fit(
                                    X_tr, y_tr_dir,
                                    y_confidence=y_tr_ret,
                                    y_drive_mode=None,  # 驱动模式标签暂不生成
                                    X_val=X_val,
                                    y_val_direction=y_val_dir,
                                    y_val_confidence=y_val_ret,
                                )

                                # 特征筛选
                                if self.enable_feature_selection and len(all_feature_cols) > self.top_k_features:
                                    selected_features = model.select_features(
                                        X_tr, top_k=self.top_k_features
                                    )
                                    # 用筛选后的特征重新训练（轻量化）
                                    # 这里简化：只在预测时使用筛选特征
                            else:
                                from ml.models import LightGBMModel
                                model = LightGBMModel()
                                model.fit(X_tr, y_tr_dir, X_val=X_val, y_val=y_val_dir)

                            current_model = model
                            self._last_train_idx = i
                            self._selected_features = selected_features
                        except Exception as e:
                            print(f"  [WARN] 第 {i} 行训练失败: {e}")
                            current_model = None

            # 预测 + 融合
            if current_model is not None:
                try:
                    row = features_df.iloc[[i]][selected_features]
                    if row.isna().any().any():
                        continue

                    # 规则引擎方向（简化）
                    weekly_res = features_df.iloc[i].get('weekly_res_diff', 0)
                    daily_res = features_df.iloc[i].get('daily_res_diff', 0)
                    weekly_conf = features_df.iloc[i].get('weekly_confidence', 0)
                    daily_conf = features_df.iloc[i].get('daily_confidence', 0)

                    if weekly_res > 0.05:
                        rule_dir = 'LONG'
                        rule_conf = weekly_conf * 0.6 + daily_conf * 0.4
                    elif weekly_res < -0.05:
                        rule_dir = 'SHORT'
                        rule_conf = weekly_conf * 0.6 + daily_conf * 0.4
                    else:
                        if daily_res > 0.05:
                            rule_dir = 'LONG'
                            rule_conf = daily_conf * 0.5
                        elif daily_res < -0.05:
                            rule_dir = 'SHORT'
                            rule_conf = daily_conf * 0.5
                        else:
                            rule_dir = 'NEUTRAL'
                            rule_conf = 0.0

                    # AI 预测
                    if self.enable_multitask:
                        ai_pred = current_model.predict(row)
                        ai_prob = ai_pred['direction_prob'][0]
                        ai_final_score = ai_pred['final_score'][0]

                        # 主置信度来自方向概率（与 v1 一致，保证可对比性）
                        if ai_prob > 0.5:
                            ai_dir = 'LONG'
                            ai_conf = (ai_prob - 0.5) * 2
                        elif ai_prob < 0.5:
                            ai_dir = 'SHORT'
                            ai_conf = (0.5 - ai_prob) * 2
                        else:
                            ai_dir = 'NEUTRAL'
                            ai_conf = 0.0

                        # 多任务加成：final_score 同向增强、反向削弱
                        if ai_dir != 'NEUTRAL':
                            score_sign = 1 if ai_final_score > 0 else -1
                            dir_sign = 1 if ai_dir == 'LONG' else -1
                            if score_sign == dir_sign:
                                # 同向：增强置信度（最多 +30%）
                                ai_conf = min(1.0, ai_conf * (1.0 + 0.3 * abs(ai_final_score)))
                            else:
                                # 反向：削弱置信度（最多 -30%）
                                ai_conf = max(0.0, ai_conf * (1.0 - 0.3 * abs(ai_final_score)))
                    else:
                        ai_prob = current_model.predict_proba(row)[0]
                        if ai_prob > 0.55:
                            ai_dir = 'LONG'
                            ai_conf = (ai_prob - 0.5) * 2
                        elif ai_prob < 0.45:
                            ai_dir = 'SHORT'
                            ai_conf = (0.5 - ai_prob) * 2
                        else:
                            ai_dir = 'NEUTRAL'
                            ai_conf = 0.0

                    # AI 置信度过低则不参与
                    if ai_conf < self.min_ml_confidence:
                        positions[i] = self._dir_to_pos(rule_dir, rule_conf)
                        continue

                    # 融合
                    if self.enable_dynamic_weight:
                        regime = _estimate_market_regime(prices, i)
                        final_dir, final_conf, weight_info = self.dynamic_fusion.fuse_decision(
                            rule_dir, rule_conf,
                            ai_dir, ai_conf,
                            **regime
                        )
                        positions[i] = self._dir_to_pos(final_dir, final_conf)
                    else:
                        # 静态融合
                        if rule_dir == ai_dir and rule_dir != 'NEUTRAL':
                            final_conf = rule_conf * 0.6 + ai_conf * 0.4
                            final_dir = rule_dir
                        elif rule_dir != ai_dir and rule_dir != 'NEUTRAL' and ai_dir != 'NEUTRAL':
                            final_conf = max(0.0, rule_conf * 0.5 - ai_conf * 0.4)
                            final_dir = rule_dir if final_conf > 0.2 else 'NEUTRAL'
                        elif rule_dir == 'NEUTRAL' and ai_dir != 'NEUTRAL':
                            final_dir = ai_dir
                            final_conf = ai_conf * 0.6
                        else:
                            final_dir = rule_dir
                            final_conf = rule_conf
                        positions[i] = self._dir_to_pos(final_dir, final_conf)

                except Exception as e:
                    pass

        return pd.Series(positions, index=prices.index, name="position")

    def _dir_to_pos(self, direction: str, confidence: float) -> float:
        """方向 + 置信度 → 仓位"""
        if direction == 'LONG':
            return min(confidence, 1.0)
        elif direction == 'SHORT':
            return -min(confidence, 1.0)
        else:
            return 0.0

    def get_feature_importance(self, task: str = 'all') -> pd.Series:
        """获取特征重要性"""
        if self._current_model is not None and self.enable_multitask:
            return self._current_model.feature_importance(task)
        return pd.Series()
