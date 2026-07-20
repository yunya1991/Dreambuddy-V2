"""PITD 物理推理引擎 (Physics Reasoning Engine)

不依赖ML，直接用物理定律构建交易信号。
基于Phase 1-3已验证的物理量：
- η (耦合效率): 理论1验证, 2.86x单调递增 → 趋势强度
- jerk (加加速度): 反转点放大3.14x → 突变检测
- 势能梯度: 阻力最小方向 → 支撑阻力
- 动量/动能: 方向100%正确 → 趋势确认

推理逻辑:
1. 趋势状态判断: η分级 (强趋势/弱趋势/无趋势)
2. 突变检测: jerk异常 → 反转预警
3. 阻力方向: 势能梯度 → 支撑阻力判断
4. 信号融合: 多物理量加权 → 综合信号

输出:
- physics_signal: [-1, +1] 综合物理信号 (负=看空, 正=看多)
- physics_confidence: [0, 1] 信号置信度
- physics_regime: 趋势状态分类
- physics_components: 各分量信号详情

文件: ml/pitd_reasoning_engine.py
"""

import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional
from dataclasses import dataclass, field

from ml.pitd_kinematics_engineer import KinematicsEngineer
from ml.pitd_dynamics_engineer import DynamicsEngineer
from ml.pitd_potential_field import PotentialFieldEngineer


@dataclass
class PhysicsSignal:
    """物理信号数据类"""
    # 综合信号
    signal: float = 0.0           # [-1, +1] 综合信号
    confidence: float = 0.0       # [0, 1] 置信度
    regime: str = "unknown"       # 趋势状态

    # 分量信号
    trend_signal: float = 0.0     # 趋势信号 (基于η+动量)
    reversal_signal: float = 0.0  # 反转信号 (基于jerk)
    support_signal: float = 0.0   # 支撑阻力信号 (基于势能梯度)
    momentum_signal: float = 0.0  # 动量确认信号

    # 原始物理量
    eta: float = 0.0              # 耦合效率
    velocity_D: float = 0.0       # 日线速度
    velocity_W: float = 0.0       # 周线速度
    jerk_D: float = 0.0           # 日线加加速度
    jerk_W: float = 0.0           # 周线加加速度
    gradient: float = 0.0         # 势能梯度
    momentum: float = 0.0         # 动量
    kinetic_energy: float = 0.0   # 动能

    # 风险标记
    reversal_warning: bool = False  # 反转预警
    strong_trend: bool = False      # 强趋势标记


class PhysicsReasoningEngine:
    """物理推理引擎

    用法:
        engine = PhysicsReasoningEngine()
        signals = engine.compute_signals(prices)  # 批量计算
        # 或
        signal = engine.compute_single(prices)    # 单时间点
    """

    def __init__(
        self,
        # η阈值（基于Phase 2验证的分档数据）
        eta_strong: float = 0.20,      # η > 0.20 → 强趋势
        eta_weak: float = 0.10,         # η < 0.10 → 弱趋势
        # jerk阈值（基于Phase 1的3.14x放大）
        jerk_threshold_pct: float = 90,  # jerk绝对值>历史90分位 → 突变
        # 势能梯度阈值
        gradient_strong: float = 10.0,   # |梯度| > 10 → 强阻力/支撑
        # 信号权重
        weight_trend: float = 0.35,
        weight_reversal: float = 0.25,
        weight_support: float = 0.20,
        weight_momentum: float = 0.20,
        # 质量模式
        mass_mode: str = "constant",
    ):
        """初始化物理推理引擎

        参数:
            eta_strong: 强趋势η阈值
            eta_weak: 弱趋势η阈值
            jerk_threshold_pct: jerk突变分位数阈值
            gradient_strong: 强梯度阈值
            weight_*: 各分量信号权重
            mass_mode: 质量模式（constant/volume_normalized/stablecoin_mcap）
        """
        self.eta_strong = eta_strong
        self.eta_weak = eta_weak
        self.jerk_threshold_pct = jerk_threshold_pct
        self.gradient_strong = gradient_strong
        self.weight_trend = weight_trend
        self.weight_reversal = weight_reversal
        self.weight_support = weight_support
        self.weight_momentum = weight_momentum
        self.mass_mode = mass_mode

        # 子引擎
        self._kin_fe = KinematicsEngineer()
        self._dyn_fe = DynamicsEngineer(mass_mode=mass_mode)
        self._pf_fe = PotentialFieldEngineer()

        # jerk历史分位数缓存
        self._jerk_d_threshold = None
        self._jerk_w_threshold = None

    def _compute_features(self, prices: pd.DataFrame) -> Dict[str, pd.DataFrame]:
        """计算所有物理特征"""
        kin = self._kin_fe.extract_series(prices)
        dyn = self._dyn_fe.extract_series(prices, kin)
        pf = self._pf_fe.extract_series(prices)
        return {"kinematics": kin, "dynamics": dyn, "potential": pf}

    def _compute_trend_signal(
        self, eta: float, v_D: float, v_W: float, momentum: float
    ) -> Tuple[float, str]:
        """计算趋势信号

        基于理论1：η高=趋势强(顺势), η低=趋势弱(独立)

        返回: (signal, regime)
        """
        # 趋势状态分类
        if eta > self.eta_strong:
            regime = "strong_trend"
            # 强趋势：顺势信号，方向由动量决定
            signal = np.sign(momentum) * min(1.0, eta / 0.3)  # 归一化到[0,1]
        elif eta < self.eta_weak:
            regime = "weak_trend"
            # 弱趋势：小周期独立，信号减弱
            signal = np.sign(momentum) * eta / self.eta_weak * 0.5  # 减半
        else:
            regime = "normal"
            # 正常趋势：中等信号
            signal = np.sign(momentum) * (eta - self.eta_weak) / (self.eta_strong - self.eta_weak)

        return float(signal), regime

    def _compute_reversal_signal(
        self, jerk_D: float, jerk_W: float,
        jerk_d_threshold: float, jerk_w_threshold: float,
        v_D: float, v_W: float,
    ) -> Tuple[float, bool]:
        """计算反转信号

        基于Phase 1发现：反转点jerk放大3.14x

        返回: (signal, warning)
        """
        warning = False
        signal = 0.0

        # 检测jerk异常（突变）
        if abs(jerk_D) > jerk_d_threshold or abs(jerk_W) > jerk_w_threshold:
            warning = True
            # jerk方向与当前速度相反 → 反转信号
            if np.sign(jerk_D) != np.sign(v_D) and abs(v_D) > 1e-8:
                # jerk负+速度正 → 减速 → 看空信号
                signal = -np.sign(v_D) * min(1.0, abs(jerk_D) / jerk_d_threshold)
            elif np.sign(jerk_W) != np.sign(v_W) and abs(v_W) > 1e-8:
                signal = -np.sign(v_W) * min(1.0, abs(jerk_W) / jerk_w_threshold)
            else:
                # jerk与速度同向 → 加速 → 看多信号
                signal = np.sign(v_D) * min(1.0, abs(jerk_D) / jerk_d_threshold) * 0.5

        return float(signal), warning

    def _compute_support_signal(self, gradient: float, v_D: float) -> float:
        """计算支撑阻力信号

        基于理论4：市场沿阻力最小方向运动
        梯度负 → 阻力向上 → 看多
        梯度正 → 阻力向下 → 看空
        """
        if abs(gradient) < 1e-6:
            return 0.0

        # 阻力方向信号
        direction = -np.sign(gradient)  # 阻力最小方向

        # 信号强度（梯度绝对值归一化）
        strength = min(1.0, abs(gradient) / self.gradient_strong)

        # 与动量方向一致性增强
        if np.sign(direction) == np.sign(v_D):
            strength *= 1.2  # 动量确认，增强

        return float(direction * strength)

    def _compute_momentum_signal(
        self, momentum: float, kinetic_energy: float, v_D: float, v_W: float
    ) -> float:
        """计算动量确认信号

        动量方向100%正确（Phase 2验证），作为趋势确认
        """
        if abs(momentum) < 1e-10:
            return 0.0

        # 基础动量方向信号
        direction = np.sign(momentum)

        # 动能强度归一化（动能越大，信号越强）
        #动能分布范围较大，用对数压缩
        ke_normalized = min(1.0, np.log1p(kinetic_energy * 1000) / 5)

        # 大小周期动量一致性增强
        if np.sign(v_D) == np.sign(v_W) and abs(v_W) > 1e-8:
            ke_normalized *= 1.3

        return float(direction * ke_normalized)

    def compute_single(
        self, prices: pd.DataFrame, features: Optional[Dict] = None
    ) -> PhysicsSignal:
        """单时间点计算物理信号

        参数:
            prices: 日线OHLCV（至少100天）
            features: 预计算的物理特征（避免重复计算）

        返回:
            PhysicsSignal 对象
        """
        if features is None:
            features = self._compute_features(prices)

        kin = features["kinematics"]
        dyn = features["dynamics"]
        pf = features["potential"]

        # 获取最新值
        eta = float(dyn["dyn_coupling_eta"].iloc[-1])
        v_D = float(kin["kin_velocity_D"].iloc[-1])
        v_W = float(kin["kin_velocity_W"].iloc[-1])
        jerk_D = float(kin["kin_jerk_D"].iloc[-1])
        jerk_W = float(kin["kin_jerk_W"].iloc[-1])
        gradient = float(pf["field_gradient_total"].iloc[-1])
        momentum = float(dyn["dyn_momentum"].iloc[-1])
        kinetic_energy = float(dyn["dyn_kinetic_energy"].iloc[-1])

        # 计算jerk阈值（历史分位数）
        jerk_d_abs = np.abs(kin["kin_jerk_D"].values)
        jerk_w_abs = np.abs(kin["kin_jerk_W"].values)
        # 过滤零值后计算分位数
        jerk_d_nonzero = jerk_d_abs[jerk_d_abs > 1e-8]
        jerk_w_nonzero = jerk_w_abs[jerk_w_abs > 1e-8]
        jerk_d_thresh = np.percentile(jerk_d_nonzero, self.jerk_threshold_pct) if len(jerk_d_nonzero) > 10 else 0.05
        jerk_w_thresh = np.percentile(jerk_w_nonzero, self.jerk_threshold_pct) if len(jerk_w_nonzero) > 10 else 0.05

        # 计算各分量信号
        trend_sig, regime = self._compute_trend_signal(eta, v_D, v_W, momentum)
        reversal_sig, reversal_warning = self._compute_reversal_signal(
            jerk_D, jerk_W, jerk_d_thresh, jerk_w_thresh, v_D, v_W
        )
        support_sig = self._compute_support_signal(gradient, v_D)
        momentum_sig = self._compute_momentum_signal(momentum, kinetic_energy, v_D, v_W)

        # 信号融合（加权平均）
        # 反转预警时降低趋势信号权重
        if reversal_warning:
            w_trend = self.weight_trend * 0.5
            w_reversal = self.weight_reversal * 1.5
        else:
            w_trend = self.weight_trend
            w_reversal = self.weight_reversal

        total_weight = w_trend + w_reversal + self.weight_support + self.weight_momentum
        signal = (
            w_trend * trend_sig
            + w_reversal * reversal_sig
            + self.weight_support * support_sig
            + self.weight_momentum * momentum_sig
        ) / total_weight

        # 信号裁剪到[-1, 1]
        signal = float(np.clip(signal, -1.0, 1.0))

        # 置信度计算
        # 强趋势+动量一致 → 高置信度
        # 弱趋势+jerk突变 → 中置信度（反转预警）
        # 无趋势+信号弱 → 低置信度
        if regime == "strong_trend":
            confidence = min(1.0, eta / 0.3) * 0.8
            if np.sign(trend_sig) == np.sign(momentum_sig):
                confidence = min(1.0, confidence + 0.2)
        elif regime == "weak_trend" and reversal_warning:
            confidence = 0.6
        elif regime == "normal":
            confidence = 0.4 + 0.3 * abs(signal)
        else:
            confidence = 0.3 + 0.3 * abs(signal)

        confidence = float(np.clip(confidence, 0.0, 1.0))

        return PhysicsSignal(
            signal=signal,
            confidence=confidence,
            regime=regime,
            trend_signal=trend_sig,
            reversal_signal=reversal_sig,
            support_signal=support_sig,
            momentum_signal=momentum_sig,
            eta=eta,
            velocity_D=v_D,
            velocity_W=v_W,
            jerk_D=jerk_D,
            jerk_W=jerk_W,
            gradient=gradient,
            momentum=momentum,
            kinetic_energy=kinetic_energy,
            reversal_warning=reversal_warning,
            strong_trend=(regime == "strong_trend"),
        )

    def compute_signals(self, prices: pd.DataFrame) -> pd.DataFrame:
        """批量计算物理信号

        参数:
            prices: 日线OHLCV

        返回:
            DataFrame, 包含物理信号序列
        """
        n = len(prices)
        features = self._compute_features(prices)

        # 预计算jerk阈值（全局）
        jerk_d_abs = np.abs(features["kinematics"]["kin_jerk_D"].values)
        jerk_w_abs = np.abs(features["kinematics"]["kin_jerk_W"].values)
        jerk_d_nonzero = jerk_d_abs[jerk_d_abs > 1e-8]
        jerk_w_nonzero = jerk_w_abs[jerk_w_abs > 1e-8]
        jerk_d_thresh = np.percentile(jerk_d_nonzero, self.jerk_threshold_pct) if len(jerk_d_nonzero) > 10 else 0.05
        jerk_w_thresh = np.percentile(jerk_w_nonzero, self.jerk_threshold_pct) if len(jerk_w_nonzero) > 10 else 0.05

        results = []
        for i in range(n):
            # 截取到第i天的特征
            kin_i = features["kinematics"].iloc[: i + 1]
            dyn_i = features["dynamics"].iloc[: i + 1]
            pf_i = features["potential"].iloc[: i + 1]

            eta = float(dyn_i["dyn_coupling_eta"].iloc[-1])
            v_D = float(kin_i["kin_velocity_D"].iloc[-1])
            v_W = float(kin_i["kin_velocity_W"].iloc[-1])
            jerk_D = float(kin_i["kin_jerk_D"].iloc[-1])
            jerk_W = float(kin_i["kin_jerk_W"].iloc[-1])
            gradient = float(pf_i["field_gradient_total"].iloc[-1])
            momentum = float(dyn_i["dyn_momentum"].iloc[-1])
            kinetic_energy = float(dyn_i["dyn_kinetic_energy"].iloc[-1])

            trend_sig, regime = self._compute_trend_signal(eta, v_D, v_W, momentum)
            reversal_sig, reversal_warning = self._compute_reversal_signal(
                jerk_D, jerk_W, jerk_d_thresh, jerk_w_thresh, v_D, v_W
            )
            support_sig = self._compute_support_signal(gradient, v_D)
            momentum_sig = self._compute_momentum_signal(momentum, kinetic_energy, v_D, v_W)

            # 信号融合
            if reversal_warning:
                w_trend = self.weight_trend * 0.5
                w_reversal = self.weight_reversal * 1.5
            else:
                w_trend = self.weight_trend
                w_reversal = self.weight_reversal

            total_weight = w_trend + w_reversal + self.weight_support + self.weight_momentum
            signal = (
                w_trend * trend_sig
                + w_reversal * reversal_sig
                + self.weight_support * support_sig
                + self.weight_momentum * momentum_sig
            ) / total_weight
            signal = float(np.clip(signal, -1.0, 1.0))

            # 置信度
            if regime == "strong_trend":
                confidence = min(1.0, eta / 0.3) * 0.8
                if np.sign(trend_sig) == np.sign(momentum_sig):
                    confidence = min(1.0, confidence + 0.2)
            elif regime == "weak_trend" and reversal_warning:
                confidence = 0.6
            elif regime == "normal":
                confidence = 0.4 + 0.3 * abs(signal)
            else:
                confidence = 0.3 + 0.3 * abs(signal)
            confidence = float(np.clip(confidence, 0.0, 1.0))

            results.append({
                "date": prices.index[i],
                "physics_signal": signal,
                "physics_confidence": confidence,
                "physics_regime": regime,
                "trend_signal": trend_sig,
                "reversal_signal": reversal_sig,
                "support_signal": support_sig,
                "momentum_signal": momentum_sig,
                "eta": eta,
                "velocity_D": v_D,
                "velocity_W": v_W,
                "jerk_D": jerk_D,
                "jerk_W": jerk_W,
                "gradient": gradient,
                "momentum": momentum,
                "kinetic_energy": kinetic_energy,
                "reversal_warning": reversal_warning,
                "strong_trend": (regime == "strong_trend"),
            })

        return pd.DataFrame(results).set_index("date")
