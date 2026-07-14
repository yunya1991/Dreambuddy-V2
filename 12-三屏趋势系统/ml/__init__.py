"""三屏趋势系统 — AI/ML 模块

Phase 3: AI时代三屏理论进化
基于趋势延续理论的特征工程：
- 趋势方向（EMA斜率、多周期一致性）
- 趋势变化（Elder-ray背离、力量穿越、动量转折）
- 趋势速率（一阶/二阶导数、ATR归一化速度）
- Elder-ray力量（多空力量、衰竭检测、力量平衡）
- 多尺度层级（大趋势→小趋势、小趋势累积→逆转）

参考: Alexander Elder三重滤网系统 + Elder-ray指标
"""

from .feature_engineer import TrendFeatureEngineer
from .models import MLModel, LightGBMModel, XGBoostModel, LogisticModel
from .tuner import ModelTuner
from .version_manager import ModelVersionManager
from .ml_strategy import MLTrendStrategy

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
]
