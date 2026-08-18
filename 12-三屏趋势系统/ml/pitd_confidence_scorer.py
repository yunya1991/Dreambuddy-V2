"""PITD 物理置信度评估器 (Physics Confidence Scorer)

物理推理引擎不生成交易信号，而是评估V5.5 ML信号的"可信度"，
用于动态调整仓位。物理规律下的评估更客观，因为物理量基于市场内生结构。

核心逻辑:
  物理置信度 = w1 × η_归一化      (趋势强度)
             + w2 × (1 - 反转预警)  (突变风险)
             + w3 × 顺势度          (阻力支撑一致性)
             + w4 × 动能_归一化      (动能状态)

  最终仓位 = V5.5基础仓位 × (lower_bound + scale × 物理置信度)

权重通过参数寻优确定（网格搜索+Walk-Forward验证），
目标函数为最大化风险调整后收益（夏普比）。

文件: ml/pitd_confidence_scorer.py
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from ml.pitd_kinematics_engineer import KinematicsEngineer
from ml.pitd_dynamics_engineer import DynamicsEngineer
from ml.pitd_potential_field import PotentialFieldEngineer


@dataclass
class ConfidenceWeights:
    """物理置信度权重参数"""
    w_eta: float = 0.30           # 趋势强度权重
    w_reversal: float = 0.25      # 反转风险权重
    w_support: float = 0.25       # 阻力支撑权重
    w_kinetic: float = 0.20       # 动能状态权重
    # 仓位调节参数
    position_lower: float = 0.5   # 仓位下限倍数
    position_scale: float = 1.0   # 仓位调节幅度（最终范围 [lower, lower+scale]）
    # 物理量阈值
    eta_strong: float = 0.20      # 强趋势η阈值
    eta_weak: float = 0.10        # 弱趋势η阈值
    jerk_pct: float = 90          # jerk突变分位数
    gradient_strong: float = 10.0 # 强梯度阈值

    def to_array(self) -> np.ndarray:
        return np.array([
            self.w_eta, self.w_reversal, self.w_support, self.w_kinetic,
            self.position_lower, self.position_scale,
        ])

    @staticmethod
    def from_array(arr: np.ndarray) -> "ConfidenceWeights":
        return ConfidenceWeights(
            w_eta=float(arr[0]),
            w_reversal=float(arr[1]),
            w_support=float(arr[2]),
            w_kinetic=float(arr[3]),
            position_lower=float(arr[4]),
            position_scale=float(arr[5]),
        )

    def normalize_weights(self):
        """归一化w1-w4权重使和为1"""
        total = self.w_eta + self.w_reversal + self.w_support + self.w_kinetic
        if total > 0:
            self.w_eta /= total
            self.w_reversal /= total
            self.w_support /= total
            self.w_kinetic /= total


class PhysicsConfidenceScorer:
    """物理置信度评估器

    用法:
        scorer = PhysicsConfidenceScorer(weights)
        confidence = scorer.score_signals(prices, ml_predictions)
        adjusted_position = base_position * (weights.position_lower + weights.position_scale * confidence)
    """

    def __init__(self, weights: Optional[ConfidenceWeights] = None, mass_mode: str = "constant"):
        """初始化

        参数:
            weights: 权重参数，None则用默认值
            mass_mode: 动力学质量模式
        """
        self.weights = weights or ConfidenceWeights()
        self.mass_mode = mass_mode

        self._kin_fe = KinematicsEngineer()
        self._dyn_fe = DynamicsEngineer(mass_mode=mass_mode)
        self._pf_fe = PotentialFieldEngineer()

    def _compute_physics_features(self, prices: pd.DataFrame) -> Dict[str, np.ndarray]:
        """计算物理特征（用于置信度评估）"""
        kin = self._kin_fe.extract_series(prices)
        dyn = self._dyn_fe.extract_series(prices, kin)
        pf = self._pf_fe.extract_series(prices)

        # 计算jerk突变阈值
        jerk_d_abs = np.abs(kin["kin_jerk_D"].values)
        jerk_w_abs = np.abs(kin["kin_jerk_W"].values)
        j_d_nonzero = jerk_d_abs[jerk_d_abs > 1e-8]
        j_w_nonzero = jerk_w_abs[jerk_w_abs > 1e-8]
        jerk_d_thresh = np.percentile(j_d_nonzero, self.weights.jerk_pct) if len(j_d_nonzero) > 10 else 0.05
        jerk_w_thresh = np.percentile(j_w_nonzero, self.weights.jerk_pct) if len(j_w_nonzero) > 10 else 0.05

        return {
            "eta": dyn["dyn_coupling_eta"].values,
            "velocity_D": kin["kin_velocity_D"].values,
            "velocity_W": kin["kin_velocity_W"].values,
            "jerk_D": kin["kin_jerk_D"].values,
            "jerk_W": kin["kin_jerk_W"].values,
            "jerk_d_thresh": jerk_d_thresh,
            "jerk_w_thresh": jerk_w_thresh,
            "gradient": pf["field_gradient_total"].values,
            "momentum": dyn["dyn_momentum"].values,
            "kinetic_energy": dyn["dyn_kinetic_energy"].values,
            "up_resistance": pf["field_up_resistance"].values,
            "down_support": pf["field_down_support"].values,
        }

    def _score_trend_strength(self, eta: np.ndarray) -> np.ndarray:
        """趋势强度评分 [0, 1]
        η越高，趋势越强，信号越可靠
        """
        w = self.weights
        score = np.clip((eta - w.eta_weak) / (w.eta_strong - w.eta_weak + 1e-10), 0, 1)
        return score

    def _score_reversal_risk(self, jerk_D: np.ndarray, jerk_W: np.ndarray,
                              jerk_d_thresh: float, jerk_w_thresh: float,
                              velocity_D: np.ndarray, velocity_W: np.ndarray) -> np.ndarray:
        """反转风险评分 [0, 1]
        jerk尖峰=反转预警，信号不可靠
        返回: (1 - 反转风险)，越高越可靠
        """
        # 检测jerk突变
        jerk_anomaly = (np.abs(jerk_D) > jerk_d_thresh) | (np.abs(jerk_W) > jerk_w_thresh)

        # 判断突变方向是否与速度相反（反转信号）
        reversal_signal = (
            ((np.sign(jerk_D) != np.sign(velocity_D)) & (np.abs(velocity_D) > 1e-8)) |
            ((np.sign(jerk_W) != np.sign(velocity_W)) & (np.abs(velocity_W) > 1e-8))
        )

        # 反转预警：突变+方向相反 → 高风险
        high_risk = jerk_anomaly & reversal_signal
        # 单纯突变（同向加速）→ 中等风险
        medium_risk = jerk_anomaly & ~reversal_signal

        score = np.ones(len(jerk_D))
        score[medium_risk] = 0.7
        score[high_risk] = 0.3
        return score

    def _score_support_alignment(self, gradient: np.ndarray, velocity_D: np.ndarray,
                                  ml_signal: np.ndarray) -> np.ndarray:
        """阻力支撑一致性评分 [0, 1]
        梯度方向与ML信号一致=顺势，阻力小，信号更可靠
        """
        # 阻力最小方向 = -sign(梯度)
        resistance_dir = -np.sign(gradient)
        # ML信号方向
        ml_dir = np.sign(ml_signal)

        # 方向一致 → 高分
        aligned = (resistance_dir == ml_dir) & (np.abs(gradient) > 1e-6) & (ml_dir != 0)
        # 方向相反 → 低分
        opposed = (resistance_dir == -ml_dir) & (np.abs(gradient) > 1e-6) & (ml_dir != 0)
        # 梯度弱 → 中性
        neutral = ~(aligned | opposed)

        score = np.full(len(gradient), 0.5)
        score[aligned] = 0.8
        score[opposed] = 0.3
        # 梯度越强，一致/相反的影响越大
        w = self.weights
        strength = np.clip(np.abs(gradient) / w.gradient_strong, 0, 1)
        score = np.where(aligned, 0.5 + 0.3 * strength, score)
        score = np.where(opposed, 0.5 - 0.2 * strength, score)

        return np.clip(score, 0, 1)

    def _score_kinetic_energy(self, kinetic_energy: np.ndarray, velocity_D: np.ndarray,
                               velocity_W: np.ndarray) -> np.ndarray:
        """动能状态评分 [0, 1]
        动能充沛=趋势健康，信号更可靠
        但动能过高+速度背离=过热，信号不可靠
        """
        # 动能归一化：用百分位排名而非固定缩放（避免分布偏斜导致失效）
        if len(kinetic_energy) > 10:
            ke_rank = pd.Series(kinetic_energy).rank(pct=True).values
        else:
            ke_rank = np.ones(len(kinetic_energy)) * 0.5

        # 大小周期速度一致性增强
        consistent = (np.sign(velocity_D) == np.sign(velocity_W)) & (np.abs(velocity_W) > 1e-8)
        ke_rank = np.where(consistent, np.clip(ke_rank * 1.2, 0, 1), ke_rank * 0.8)

        return np.clip(ke_rank, 0, 1)

    def score_signals(
        self,
        prices: pd.DataFrame,
        ml_predictions: np.ndarray,
        precomputed_features: Optional[Dict] = None,
    ) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        """计算物理置信度

        参数:
            prices: 日线OHLCV
            ml_predictions: V5.5 ML预测概率 [0, 1]，或信号 [-1, +1]
            precomputed_features: 预计算的物理特征（避免重复计算）

        返回:
            (confidence, components)
            confidence: 物理置信度 [0, 1]
            components: 各分量评分
        """
        if precomputed_features is None:
            feats = self._compute_physics_features(prices)
        else:
            feats = precomputed_features

        w = self.weights

        # ML信号方向（用于阻力一致性判断）
        # 如果ml_predictions在[0,1]，转为[-1,+1]信号
        if ml_predictions.max() <= 1.0 and ml_predictions.min() >= 0.0:
            ml_signal = (ml_predictions - 0.5) * 2  # [0,1] → [-1,+1]
        else:
            ml_signal = ml_predictions

        # 计算四个分量评分
        trend_score = self._score_trend_strength(feats["eta"])
        reversal_score = self._score_reversal_risk(
            feats["jerk_D"], feats["jerk_W"],
            feats["jerk_d_thresh"], feats["jerk_w_thresh"],
            feats["velocity_D"], feats["velocity_W"]
        )
        support_score = self._score_support_alignment(
            feats["gradient"], feats["velocity_D"], ml_signal
        )
        kinetic_score = self._score_kinetic_energy(
            feats["kinetic_energy"], feats["velocity_D"], feats["velocity_W"]
        )

        # 加权融合
        confidence = (
            w.w_eta * trend_score
            + w.w_reversal * reversal_score
            + w.w_support * support_score
            + w.w_kinetic * kinetic_score
        )
        confidence = np.clip(confidence, 0.0, 1.0)

        components = {
            "trend_score": trend_score,
            "reversal_score": reversal_score,
            "support_score": support_score,
            "kinetic_score": kinetic_score,
            "eta": feats["eta"],
            "gradient": feats["gradient"],
            "kinetic_energy": feats["kinetic_energy"],
        }

        return confidence, components

    def adjust_position(
        self, base_position: np.ndarray, confidence: np.ndarray
    ) -> np.ndarray:
        """根据物理置信度调整仓位

        最终仓位 = 基础仓位 × (lower + scale × confidence)
        范围: [base × lower, base × (lower + scale)]

        参数:
            base_position: V5.5基础仓位（如0.5=半仓）
            confidence: 物理置信度 [0, 1]

        返回:
            调整后仓位
        """
        w = self.weights
        multiplier = w.position_lower + w.position_scale * confidence
        adjusted = base_position * multiplier
        return np.clip(adjusted, 0.0, 1.0)  # 仓位上限100%
