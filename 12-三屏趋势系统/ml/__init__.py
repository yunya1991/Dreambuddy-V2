"""三屏趋势系统 — AI/ML 模块

Phase 3: AI时代三屏理论进化
基于趋势延续理论的特征工程：
- 趋势方向（EMA斜率、多周期一致性）
- 趋势变化（Elder-ray背离、力量穿越、动量转折）
- 趋势速率（一阶/二阶导数、ATR归一化速度）
- Elder-ray力量（多空力量、衰竭检测、力量平衡）
- 多尺度层级（大趋势→小趋势、小趋势累积→逆转）

Phase 4: 最小阻力 AI 模型
时间三维 × 五维阻力 → 最小阻力三维模型 → AI推理 → 双向驱动判定 → 最小阻力方向

特征工程 (lr_feature_engineer):
- 五维阻力特征（日/周）：价格/量能/动量/趋势/基本面
- 三维动态特征：方向(D)/速度(V)/加速度(A)
- 跨周期一致性特征：周-日方向差、置信度比
- 多窗口统计特征：均值/标准差/斜率

模型策略 (lr_ml_strategy):
- LightGBM 基线模型
- Walk-Forward 滚动训练（无未来函数）
- AI预测 + 规则引擎约束融合
"""

from .feature_engineer import TrendFeatureEngineer
from .models import MLModel, LightGBMModel, XGBoostModel, LogisticModel
from .tuner import ModelTuner
from .version_manager import ModelVersionManager
from .ml_strategy import MLTrendStrategy
from .lr_feature_engineer import LeastResistanceFeatureEngineer
from .lr_ml_strategy import LeastResistanceAIStrategy
from .lr_ml_strategy_v2 import LeastResistanceAIStrategyV2
from .fundamental_adapter import FundamentalFeatureAdapter
from .multitask_model import MultiTaskLightGBM, DynamicWeightFusion

# 向后兼容别名
MultiViewFeatureEngineer = TrendFeatureEngineer

__all__ = [
    "TrendFeatureEngineer",
    "MultiViewFeatureEngineer",
    "MLModel",
    "LightGBMModel",
    "XGBoostModel",
    "LogisticModel",
    "ModelTuner",
    "ModelVersionManager",
    "MLTrendStrategy",
    # Phase 4: 最小阻力 AI 模型
    "LeastResistanceFeatureEngineer",
    "LeastResistanceAIStrategy",
    "LeastResistanceAIStrategyV2",
    "FundamentalFeatureAdapter",
    # Phase 4.3: 多任务学习 + 动态权重
    "MultiTaskLightGBM",
    "DynamicWeightFusion",
]
