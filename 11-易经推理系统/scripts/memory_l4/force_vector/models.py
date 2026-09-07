"""力向量数据结构定义。

对应 Spec §二~§四 全部 dataclass：
  ForceVector / FeatureCorrelation / PrimaryContradiction / PCAResonance /
  CycleComparison / ElasticityBeta / ContradictionTransform / StrategicLayerOutput
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ForceVector:
    """五维力向量（Spec §二 力向量结构）。

    direction/magnitude/confidence/velocity/acceleration 复用 9-基本面 least_resistance 输出。
    """
    dimension: str              # "dao" / "tian" / "di" / "jiang" / "fa"
    direction: float            # [-1.0, +1.0]  ← least_resistance.direction_score
    magnitude: float            # [0.0, +∞)    ← |least_resistance.direction_score|
    confidence: float           # [0.0, 1.0]   ← signal_engine._bayesian_confidence
    velocity: float             # 方向变化率   ← least_resistance.velocity
    acceleration: float         # 方向变化加速度 ← least_resistance.acceleration
    kalman_direction: float      # Kalman平滑后的方向（confidence>0.7时可跳过）
    kalman_magnitude: float      # Kalman平滑后的强度
    dominant: bool               # 是否为主要矛盾维度
    weight: float                # 自适应权重（按|magnitude|分配）


@dataclass
class FeatureCorrelation:
    """特征-价格关联度（Spec §三 Step 4 输出）。"""
    feature_name: str
    dimension: str               # 归属维度 "dao"/"tian"/"di"/"jiang"/"fa"
    ic_30d: float                # 30天滚动信息系数 [-1, 1]
    mi_30d: float                # 30天互信息归一化值 [0, 1]
    combined_score: float       # 综合关联度
    rank: int                     # 排名（1=主要矛盾）
    ic_weight: float              # IC 最优权重
    beta_weight: float            # Beta 后验权重
    final_weight: float           # 最终融合权重


@dataclass
class PrimaryContradiction:
    """主要矛盾识别结果（Spec §三 Step 4-A 维度聚合）。"""
    feature_name: str             # 主要矛盾特征（rank=1）
    dimension: str                # 主要矛盾维度
    combined_score: float
    rank_stability: float         # 排名稳定性（滚动窗口间 Spearman 相关）
    all_features: List[FeatureCorrelation]
    dominant_dimension: str       # 维度聚合后的主导维度
    alignment: str                # "resonance"/"conflict"/"divergence"
    sign_alignment: float         # 同向比例 [0, 1]


@dataclass
class PCAResonance:
    """PCA 五维共振分析输出（Spec §三 Step 4-B）。"""
    explained_ratio: float        # 第一主成分解释方差比 [0, 1]
    sign_alignment: float          # 其他四维与主导维度的同向比例 [0, 1]
    alignment: str                 # "full_resonance"/"strong_resonance"/"weak_resonance"/"conflict"/"full_conflict"
    strength_coefficient: float    # 强度调整系数 [0.3, 1.3]
    dominant_dimension: str        # 主导维度（从 Step 4 传入，PCA 不改变）


@dataclass
class CycleComparison:
    """双窗口周期比对输出（Spec §四 Step 6）。"""
    direction_7d: float
    direction_30d: float
    magnitude_7d: float
    magnitude_30d: float
    resonance_state: str          # "resonance"/"emerging"/"divergence"/"persistent"/"turning"/"observation"
    strength_multiplier: float    # 综合强度系数
    final_direction: float        # 最终方向（取30d为主，7d加权修正）
    final_magnitude: float         # 最终强度 = magnitude_30d × strength_multiplier


@dataclass
class ElasticityBeta:
    """弹性系数β（Spec §三-A Step 3-A-1）。"""
    beta_7d: float                # 近7天弹性系数
    beta_30d: float               # 近30天弹性系数
    beta_ratio: float              # 弹性变化比值 = β_7d / β_30d
    decay_signal: bool             # 弹性衰减信号（β_ratio < 0.5 持续3天）
    amplification_signal: bool     # 弹性放大信号（β_ratio > 2.0 持续3天）
    decay_days: int                # 衰减持续天数
    amplification_days: int        # 放大持续天数


@dataclass
class ContradictionTransform:
    """矛盾转化检测结果（Spec §三-A Step 3-A-2）。

    6 类转化条件：elasticity_decay / elasticity_amplification / dominant_shift /
    resonance_break / cbr_divergence / data_quality_warning
    """
    transforming: bool             # 是否检测到矛盾转化
    transform_type: str            # 转化类型枚举
    trigger_conditions: List[str]  # 触发的条件列表
    confidence: float              # 转化置信度 [0, 1]
    monitoring_points: List[str]   # A0-IRON-5 监控点描述
    data_quality_factor: float     # S3 pass_rate 降级因子（<0.7持续3天→0.7，否则1.0）


@dataclass
class StrategicLayerOutput:
    """战略层最终输出（Spec §四 输出结构）。

    现有字段（war_state/cap/mask）保持下游零改动；
    新增字段（force_vectors等）下游可选消费。
    """
    # === 现有字段（下游零改动）===
    war_state: str                         # ALLOW / COOLDOWN / FREEZE
    aggregate_position_cap_pct: float      # 仓位上限
    allowed_style_mask: Dict[str, bool]    # 策略白名单
    position_mult: float                   # 维度否决乘数
    five_scores: Dict[str, int]            # 五维分数(兼容现有0-100)

    # === 新增力向量字段（下游可选消费）===
    force_vectors: Dict[str, ForceVector]           # 五维力向量
    pca_result: Optional[PCAResonance]               # PCA共振结果
    cycle_comparison: Optional[CycleComparison]     # 双窗口共振校验
    final_direction: float                           # 综合最小阻力方向 [-1,+1]
    final_magnitude: float                           # 综合强度
    resonance_state: str                             # 共振状态
    elasticity_beta: Optional[ElasticityBeta]        # 弹性系数β
    contradiction_transform: Optional[ContradictionTransform]  # 矛盾转化检测结果
    primary_contradiction: str                       # 主要矛盾维度
    monitoring_points: List[str] = field(default_factory=list)  # A0-IRON-5 监控点
