"""多任务学习模型

同时预测三个目标：
1. 方向分类（上涨/下跌）— 二分类
2. 置信度回归（未来收益幅度）— 回归
3. 驱动模式分类（CONTINUATION / LATE_CONTINUATION / ACCUMULATION / WEAKENING）— 多分类

架构：
- 共享底层特征（LightGBM 多输出）
- 三个任务头分别优化
- 任务间权重自适应

参考：
- 微软 QLib 多任务学习
- LightGBM native multi-output 支持
- MTL (Multi-Task Learning) 在量化中的应用
"""

from typing import Dict, List, Optional, Any, Tuple
import numpy as np
import pandas as pd
import sys, os

sys.path.insert(0, os.path.dirname(__file__))
from models import MLModel, LightGBMModel


class MultiTaskLightGBM:
    """多任务 LightGBM 模型

    三个任务共享特征，分别训练三个 LightGBM 模型：
    - task_direction: 方向分类（binary）
    - task_confidence: 置信度回归（regression，预测未来收益幅度）
    - task_drive_mode: 驱动模式分类（multiclass，4类）

    优势：
    - 特征共享，减少过拟合
    - 多任务互补，提升泛化能力
    - 输出更丰富，支持更精细的决策
    """

    DRIVE_MODES = ["CONTINUATION", "LATE_CONTINUATION", "ACCUMULATION", "WEAKENING"]

    def __init__(
        self,
        direction_params: Optional[Dict] = None,
        confidence_params: Optional[Dict] = None,
        drive_mode_params: Optional[Dict] = None,
        task_weights: Optional[Dict[str, float]] = None,
        conf_scale_factor: float = 10.0,
    ):
        """
        参数:
            direction_params: 方向分类模型参数
            confidence_params: 置信度回归模型参数
            drive_mode_params: 驱动模式分类模型参数
            task_weights: 任务权重，用于最终融合 {direction, confidence, drive_mode}
            conf_scale_factor: 置信度缩放因子（回归值×因子 → 0~1）
        """
        self.direction_model = LightGBMModel(direction_params or {})
        self.confidence_model = LightGBMModel(confidence_params or {
            'objective': 'regression',
            'metric': 'mse',
        })
        self.drive_mode_model = LightGBMModel(drive_mode_params or {
            'objective': 'multiclass',
            'metric': 'multi_logloss',
            'num_class': 4,
        })

        self.task_weights = task_weights or {
            'direction': 0.5,
            'confidence': 0.3,
            'drive_mode': 0.2,
        }

        self.conf_scale_factor = conf_scale_factor
        self.feature_names: List[str] = []
        self.is_trained = False

    def fit(
        self,
        X: pd.DataFrame,
        y_direction: pd.Series,
        y_confidence: Optional[pd.Series] = None,
        y_drive_mode: Optional[pd.Series] = None,
        X_val: Optional[pd.DataFrame] = None,
        y_val_direction: Optional[pd.Series] = None,
        y_val_confidence: Optional[pd.Series] = None,
        y_val_drive_mode: Optional[pd.Series] = None,
    ) -> "MultiTaskLightGBM":
        """训练多任务模型

        参数:
            X: 特征 DataFrame
            y_direction: 方向标签（0/1）
            y_confidence: 置信度标签（未来收益率，可 None）
            y_drive_mode: 驱动模式标签（0-3 整数，可 None）
            X_val: 验证特征
            y_val_direction: 验证方向标签
            y_val_confidence: 验证置信度标签
            y_val_drive_mode: 验证驱动模式标签
        """
        self.feature_names = list(X.columns)

        # 任务 1: 方向分类
        print("  [1/3] 训练方向分类模型...")
        self.direction_model.fit(
            X, y_direction,
            X_val=X_val, y_val=y_val_direction
        )

        # 任务 2: 置信度回归（如果有标签）
        if y_confidence is not None:
            print("  [2/3] 训练置信度回归模型...")
            try:
                self.confidence_model.fit(
                    X, y_confidence,
                    X_val=X_val, y_val=y_val_confidence
                )
            except Exception as e:
                print(f"    置信度回归训练跳过: {e}")
                self.confidence_model = None
        else:
            self.confidence_model = None

        # 任务 3: 驱动模式分类（如果有标签）
        if y_drive_mode is not None and y_drive_mode.nunique() > 1:
            print("  [3/3] 训练驱动模式分类模型...")
            try:
                self.drive_mode_model.fit(
                    X, y_drive_mode,
                    X_val=X_val, y_val=y_val_drive_mode
                )
            except Exception as e:
                print(f"    驱动模式训练跳过: {e}")
                self.drive_mode_model = None
        else:
            self.drive_mode_model = None

        self.is_trained = True
        return self

    def predict(self, X: pd.DataFrame) -> Dict[str, Any]:
        """多任务预测

        返回:
            {
                'direction_prob': float,        # 上涨概率 (0~1)
                'direction': int,                # 预测方向 (0/1)
                'confidence': float,             # 预测置信度/收益幅度
                'drive_mode_probs': np.ndarray,  # 4类驱动模式概率
                'drive_mode': int,               # 预测驱动模式 (0-3)
                'final_score': float,            # 综合得分 (-1~1)
            }
        """
        if not self.is_trained:
            raise ValueError("模型未训练")

        result = {}

        # 方向预测
        dir_proba = self.direction_model.predict_proba(X)
        result['direction_prob'] = dir_proba
        result['direction'] = (dir_proba > 0.5).astype(int)

        # 置信度预测
        if self.confidence_model is not None:
            raw_conf = self.confidence_model.predict_proba(X)
            # 回归模型预测的是收益率，用 tanh 归一化到 0~1
            result['confidence_raw'] = raw_conf
            result['confidence'] = np.tanh(np.abs(raw_conf) * self.conf_scale_factor)
        else:
            # 用方向概率的绝对值作为置信度代理
            result['confidence'] = np.abs(dir_proba - 0.5) * 2

        # 驱动模式预测
        if self.drive_mode_model is not None:
            dm_proba = self.drive_mode_model.predict_proba(X)
            # LightGBM multiclass 返回 shape=(n, num_class)
            if len(dm_proba.shape) == 2 and dm_proba.shape[1] > 1:
                result['drive_mode_probs'] = dm_proba
                result['drive_mode'] = np.argmax(dm_proba, axis=1)
            else:
                result['drive_mode_probs'] = np.zeros((len(X), 4))
                result['drive_mode'] = np.zeros(len(X), dtype=int)
        else:
            result['drive_mode_probs'] = np.zeros((len(X), 4))
            result['drive_mode'] = np.zeros(len(X), dtype=int)

        # 综合得分：方向概率强度 × 置信度 × 驱动模式加成
        dir_strength = (result['direction_prob'] - 0.5) * 2  # -1~1
        conf_level = np.clip(result['confidence'], 0, 1)     # 0~1

        # 驱动模式加成
        if self.drive_mode_model is not None:
            # CONTINUATION(0): 趋势延续，置信度增强 +20%
            # LATE_CONTINUATION(1): 后期，保持但谨慎
            # ACCUMULATION(2): 积累期，反向关注
            # WEAKENING(3): 减弱期，降低置信度
            dm_bonus = np.zeros(len(X))
            for i, dm in enumerate(result['drive_mode']):
                if dm == 0:  # CONTINUATION
                    dm_bonus[i] = 0.2
                elif dm == 1:  # LATE_CONTINUATION
                    dm_bonus[i] = 0.0
                elif dm == 2:  # ACCUMULATION
                    dm_bonus[i] = -0.1
                else:  # WEAKENING
                    dm_bonus[i] = -0.2
        else:
            dm_bonus = 0

        final_score = dir_strength * conf_level * (1 + dm_bonus)
        result['final_score'] = np.clip(final_score, -1, 1)

        return result

    def feature_importance(self, task: str = 'direction') -> pd.Series:
        """特征重要性

        参数:
            task: 'direction' | 'confidence' | 'drive_mode' | 'all'
        """
        if task == 'all':
            # 平均三个任务的重要性
            importances = []
            for model in [self.direction_model, self.confidence_model, self.drive_mode_model]:
                if model is not None:
                    imp = model.feature_importance()
                    if not imp.empty:
                        importances.append(imp)
            if importances:
                combined = pd.concat(importances, axis=1).mean(axis=1)
                return combined.sort_values(ascending=False)
            return pd.Series()
        elif task == 'direction':
            return self.direction_model.feature_importance()
        elif task == 'confidence' and self.confidence_model:
            return self.confidence_model.feature_importance()
        elif task == 'drive_mode' and self.drive_mode_model:
            return self.drive_mode_model.feature_importance()
        return pd.Series()

    def select_features(
        self,
        X: pd.DataFrame,
        top_k: int = 30,
        task: str = 'all',
    ) -> List[str]:
        """特征选择：返回 Top K 最重要的特征名

        参数:
            X: 特征 DataFrame
            top_k: 选择前 K 个特征
            task: 参考哪个任务的重要性

        返回:
            选中的特征名列表
        """
        importance = self.feature_importance(task)
        if importance.empty:
            return list(X.columns)
        return list(importance.head(top_k).index)

    def save(self, path: str):
        """保存模型"""
        import pickle
        with open(path, 'wb') as f:
            pickle.dump({
                'direction_model': self.direction_model,
                'confidence_model': self.confidence_model,
                'drive_mode_model': self.drive_mode_model,
                'task_weights': self.task_weights,
                'feature_names': self.feature_names,
                'is_trained': self.is_trained,
            }, f)

    @classmethod
    def load(cls, path: str) -> "MultiTaskLightGBM":
        """加载模型"""
        import pickle
        with open(path, 'rb') as f:
            data = pickle.load(f)
        instance = cls()
        instance.direction_model = data['direction_model']
        instance.confidence_model = data['confidence_model']
        instance.drive_mode_model = data['drive_mode_model']
        instance.task_weights = data['task_weights']
        instance.feature_names = data['feature_names']
        instance.is_trained = data['is_trained']
        return instance


class DynamicWeightFusion:
    """动态融合权重引擎

    根据市场环境自动调整 AI 预测与规则引擎的权重：

    核心逻辑：
    - 趋势强度：趋势越强，规则权重越高（大趋势不可违）
    - 波动率：波动越大，AI 权重越高（规则难以适应剧烈变化）
    - 成交量：量能异动时，AI 权重越高（量在价先）
    - 趋势延续时间：延续越久，AI 权重越高（趋势可能即将反转）

    权重计算公式：
        rule_weight = base_rule_weight
                      + trend_strength * trend_sensitivity
                      - volatility * vol_sensitivity
                      - volume_spike * volume_sensitivity
                      - trend_duration * duration_sensitivity

        ai_weight = 1 - rule_weight
    """

    def __init__(
        self,
        base_rule_weight: float = 0.55,
        min_rule_weight: float = 0.2,
        max_rule_weight: float = 0.9,
        trend_sensitivity: float = 0.25,
        vol_sensitivity: float = 0.25,
        volume_sensitivity: float = 0.2,
        duration_sensitivity: float = 0.25,
    ):
        """
        参数:
            base_rule_weight: 基础规则权重（默认 0.6，规则为主）
            min_rule_weight: 规则权重下限
            max_rule_weight: 规则权重上限
            trend_sensitivity: 趋势强度敏感度（趋势越强→规则越重）
            vol_sensitivity: 波动率敏感度（波动越大→AI越重）
            volume_sensitivity: 成交量敏感度（量异动→AI越重）
            duration_sensitivity: 趋势时长敏感度（延续越久→AI越重）
        """
        self.base_rule_weight = base_rule_weight
        self.min_rule_weight = min_rule_weight
        self.max_rule_weight = max_rule_weight
        self.trend_sensitivity = trend_sensitivity
        self.vol_sensitivity = vol_sensitivity
        self.volume_sensitivity = volume_sensitivity
        self.duration_sensitivity = duration_sensitivity

    def calculate_weights(
        self,
        trend_strength: float = 0.5,
        volatility: float = 0.5,
        volume_spike: float = 0.0,
        trend_duration: float = 0.0,
        market_regime: str = "normal",
    ) -> Dict[str, float]:
        """计算当前市场环境下的融合权重

        参数:
            trend_strength: 趋势强度 (0~1)
            volatility: 波动率水平 (0~1，归一化)
            volume_spike: 成交量异动程度 (0~1)
            trend_duration: 趋势延续时长 (0~1，归一化)
            market_regime: 市场环境 ('trending' | 'range' | 'volatile' | 'normal')

        返回:
            {'rule_weight': float, 'ai_weight': float, 'reason': str}
        """
        # 基础权重
        rule_weight = self.base_rule_weight

        # 趋势强度：趋势越强，规则权重越高
        rule_weight += trend_strength * self.trend_sensitivity

        # 波动率：波动越大，AI 权重越高（规则权重越低）
        rule_weight -= volatility * self.vol_sensitivity

        # 成交量异动：量异动时 AI 权重更高
        rule_weight -= volume_spike * self.volume_sensitivity

        # 趋势时长：延续越久，AI 权重越高（可能反转）
        rule_weight -= trend_duration * self.duration_sensitivity

        # 市场环境修正
        regime_adj = {
            'trending': 0.1,    # 趋势市：规则加权重
            'range': -0.1,      # 震荡市：AI 加权重
            'volatile': -0.2,   # 高波动：AI 加权重
            'normal': 0.0,
        }
        rule_weight += regime_adj.get(market_regime, 0.0)

        # 裁剪到合法范围
        rule_weight = max(self.min_rule_weight, min(self.max_rule_weight, rule_weight))
        ai_weight = 1.0 - rule_weight

        # 生成原因说明
        reasons = []
        if trend_strength > 0.6:
            reasons.append(f"强趋势(+{trend_strength*self.trend_sensitivity:.2f})")
        if volatility > 0.6:
            reasons.append(f"高波动(-{volatility*self.vol_sensitivity:.2f})")
        if volume_spike > 0.3:
            reasons.append(f"量异动(-{volume_spike*self.volume_sensitivity:.2f})")
        if trend_duration > 0.7:
            reasons.append(f"趋势久(-{trend_duration*self.duration_sensitivity:.2f})")
        reasons.append(f"环境={market_regime}")

        return {
            'rule_weight': round(rule_weight, 4),
            'ai_weight': round(ai_weight, 4),
            'reason': ', '.join(reasons),
            'factors': {
                'trend_strength': trend_strength,
                'volatility': volatility,
                'volume_spike': volume_spike,
                'trend_duration': trend_duration,
                'market_regime': market_regime,
            }
        }

    def fuse_decision(
        self,
        rule_direction: str,
        rule_confidence: float,
        ai_direction: str,
        ai_confidence: float,
        **kwargs,
    ) -> Tuple[str, float, Dict]:
        """融合规则引擎和 AI 的决策

        参数:
            rule_direction: 规则方向 ('LONG'/'SHORT'/'NEUTRAL')
            rule_confidence: 规则置信度 (0~1)
            ai_direction: AI 方向 ('LONG'/'SHORT'/'NEUTRAL')
            ai_confidence: AI 置信度 (0~1)
            **kwargs: 传递给 calculate_weights 的市场环境参数

        返回:
            (final_direction, final_confidence, weights_info)
        """
        # 计算动态权重
        weights = self.calculate_weights(**kwargs)
        rule_w = weights['rule_weight']
        ai_w = weights['ai_weight']

        # 方向转数值
        def dir_to_val(d: str) -> float:
            if d == 'LONG':
                return 1.0
            elif d == 'SHORT':
                return -1.0
            return 0.0

        rule_val = dir_to_val(rule_direction) * rule_confidence
        ai_val = dir_to_val(ai_direction) * ai_confidence

        # 加权融合
        fused_val = rule_val * rule_w + ai_val * ai_w

        # 转回方向 + 置信度
        if abs(fused_val) < 0.1:
            final_direction = 'NEUTRAL'
            final_confidence = 0.0
        elif fused_val > 0:
            final_direction = 'LONG'
            final_confidence = min(fused_val, 1.0)
        else:
            final_direction = 'SHORT'
            final_confidence = min(abs(fused_val), 1.0)

        info = {
            **weights,
            'rule_val': round(rule_val, 4),
            'ai_val': round(ai_val, 4),
            'fused_val': round(fused_val, 4),
        }

        return final_direction, final_confidence, info
