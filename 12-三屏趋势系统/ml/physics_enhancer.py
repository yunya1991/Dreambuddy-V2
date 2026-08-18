"""物理引擎增强器 — 集成信号评估器 + jerk止损 + 动能仓位 + 动能止盈

将9年回测验证的最优物理引擎应用集成到一个统一模块，供 backtest/engine.py 调用。

应用层（按优先级）:
1. 信号质量评估器：双重过滤（波浪置信度 + 物理置信度）+ 仓位调节
2. 动态仓位管理：动能力度仓位（kinetic_score 驱动）
3. 动态风险控制：jerk反转保护追踪止损 + 动能止盈

参考文档: docs/PITD_PHYSICS_APPLICATION_FRAMEWORK.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


@dataclass
class PhysicsEnhancerConfig:
    """物理增强器配置（9年回测最优参数）"""

    # 总开关
    enabled: bool = True

    # Layer 2: 信号质量评估器
    enable_signal_filter: bool = True
    wave_conf_threshold: float = 0.7        # 波浪置信度入场阈值
    phys_conf_threshold: float = 0.5        # 物理置信度过滤阈值

    # Layer 4: 动态仓位管理
    enable_dynamic_sizing: bool = True
    sizing_mode: str = "kinetic"            # "kinetic" | "kelly" | "fixed"
    base_position: float = 0.3
    position_min: float = 0.1
    position_max: float = 1.0

    # Layer 3: 动态风险控制
    enable_dynamic_stoploss: bool = True
    enable_dynamic_takeprofit: bool = True
    base_trailing_pct: float = 0.08
    base_take_profit_pct: float = 0.25
    trailing_mode: str = "combo"            # "combo" | "jerk" | "eta" | "fixed"
    take_profit_mode: str = "kinetic"       # "kinetic" | "fixed"
    trail_min: float = 0.02
    trail_max: float = 0.15
    tp_min: float = 0.08
    tp_max: float = 0.50

    # 物理置信度权重（9年回测最优）
    w_eta: float = 0.211
    w_reversal: float = 0.368
    w_support: float = 0.211
    w_kinetic: float = 0.211

    # 物理量阈值
    eta_strong: float = 0.20
    eta_weak: float = 0.10

    # 凯利式仓位参数
    kelly_fraction: float = 0.5             # 半凯利
    kelly_win_prob_base: float = 0.35
    kelly_win_prob_scale: float = 0.30


@dataclass
class PhysicsState:
    """持仓中的物理状态追踪"""

    entry_price: float = 0.0
    direction: int = 0                      # 1=多, -1=空, 0=空仓
    peak_price: float = 0.0                 # 持仓期间最高价（多头）
    trough_price: float = 0.0               # 持仓期间最低价（空头）
    trailing_stop_price: float = 0.0        # 当前追踪止损价
    current_trail_pct: float = 0.08
    current_tp_pct: float = 0.25
    base_size: float = 0.3


class PhysicsEnhancer:
    """物理引擎增强器

    用法（独立使用，处理信号+仓位序列）:
        enhancer = PhysicsEnhancer(config)
        feats = enhancer.compute_features(prices)
        adjusted_positions = enhancer.enhance_positions(
            prices, base_positions, wave_signals, wave_confs, feats
        )

    用法（逐bar使用，支持追踪止损）:
        enhancer = PhysicsEnhancer(config)
        feats = enhancer.compute_features(prices)
        for i in range(len(prices)):
            action = enhancer.process_bar(i, prices, feats, wave_signals, wave_confs)
            # action包含: position, direction, trail_stop, take_profit
    """

    def __init__(self, config: Optional[PhysicsEnhancerConfig] = None):
        self.config = config or PhysicsEnhancerConfig()
        self._scorer = None
        self._kin_fe = None
        self._dyn_fe = None

    # ------------------------------------------------------------------
    # 特征计算
    # ------------------------------------------------------------------

    def compute_features(self, prices: pd.DataFrame) -> Dict[str, np.ndarray]:
        """预计算全部物理特征（一次性，避免重复计算）

        参数:
            prices: OHLCV DataFrame (columns: open/high/low/close/volume)

        返回:
            物理特征字典，包含:
            - eta: 耦合效率
            - phys_conf: 综合物理置信度 [0,1]
            - trend_score / reversal_score / support_score / kinetic_score
            - volatility / vol_rank
            - momentum / kinetic_energy / friction_ratio
        """
        cfg = self.config
        n = len(prices)

        # 延迟导入，避免循环依赖
        try:
            from ..ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
            from ..ml.pitd_kinematics_engineer import KinematicsEngineer
            from ..ml.pitd_dynamics_engineer import DynamicsEngineer
        except (ImportError, ValueError):
            from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
            from ml.pitd_kinematics_engineer import KinematicsEngineer
            from ml.pitd_dynamics_engineer import DynamicsEngineer

        weights = ConfidenceWeights(
            w_eta=cfg.w_eta,
            w_reversal=cfg.w_reversal,
            w_support=cfg.w_support,
            w_kinetic=cfg.w_kinetic,
            position_lower=0.6,
            position_scale=1.0,
            eta_strong=cfg.eta_strong,
            eta_weak=cfg.eta_weak,
        )
        scorer = PhysicsConfidenceScorer(weights)
        kin_fe = KinematicsEngineer()
        dyn_fe = DynamicsEngineer()

        kin_feats = kin_fe.extract_series(prices)
        dyn_feats = dyn_fe.extract_series(prices, kin_feats)

        eta_series = dyn_feats["dyn_coupling_eta"].values
        ml_pred_neutral = np.full(n, 0.5)
        phys_conf, components = scorer.score_signals(
            prices=prices, ml_predictions=ml_pred_neutral
        )

        # 波动率（风险预算用）
        closes = prices["close"].values
        highs = prices["high"].values
        lows = prices["low"].values
        prev_closes = np.concatenate([[closes[0]], closes[:-1]])
        tr = np.maximum(
            highs - lows,
            np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)),
        )
        atr = pd.Series(tr).rolling(14, min_periods=1).mean().values
        volatility = atr / np.maximum(closes, 1e-10)
        vol_rank = pd.Series(volatility).rank(pct=True).values

        return {
            "eta": eta_series,
            "phys_conf": phys_conf,
            "trend_score": components.get("trend_score", np.full(n, 0.5)),
            "reversal_score": components.get("reversal_score", np.full(n, 0.5)),
            "support_score": components.get("support_score", np.full(n, 0.5)),
            "kinetic_score": components.get("kinetic_score", np.full(n, 0.5)),
            "momentum": dyn_feats["dyn_momentum"].values,
            "kinetic_energy": dyn_feats["dyn_kinetic_energy"].values,
            "friction_ratio": dyn_feats["dyn_friction_ratio"].values,
            "volatility": volatility,
            "vol_rank": vol_rank,
        }

    # ------------------------------------------------------------------
    # Layer 2: 信号质量评估
    # ------------------------------------------------------------------

    def evaluate_signal_quality(
        self,
        i: int,
        wave_signal: str,
        wave_conf: float,
        feats: Dict[str, np.ndarray],
    ) -> Tuple[bool, float]:
        """评估信号质量

        返回:
            (passed, quality_score)
            passed: 是否通过双重过滤
            quality_score: 质量评分 [0,1]
        """
        cfg = self.config

        if not cfg.enable_signal_filter:
            return True, float(feats["phys_conf"][i])

        # 波浪置信度过滤
        if wave_conf < cfg.wave_conf_threshold:
            return False, 0.0

        # 物理置信度过滤
        pc = float(feats["phys_conf"][i])
        if np.isnan(pc):
            pc = 0.5
        if pc < cfg.phys_conf_threshold:
            return False, pc

        return True, pc

    # ------------------------------------------------------------------
    # Layer 4: 动态仓位管理
    # ------------------------------------------------------------------

    def compute_position_size(
        self,
        i: int,
        wave_conf: float,
        feats: Dict[str, np.ndarray],
        state: PhysicsState,
    ) -> float:
        """计算动态仓位大小"""
        cfg = self.config

        if not cfg.enable_dynamic_sizing or cfg.sizing_mode == "fixed":
            size = cfg.base_position * max(wave_conf, 0.5)
            return float(np.clip(size, cfg.position_min, cfg.position_max))

        if cfg.sizing_mode == "kinetic":
            # 动能力度仓位
            ks = float(feats["kinetic_score"][i])
            if np.isnan(ks):
                ks = 0.5
            size = cfg.base_position * (0.5 + 1.5 * ks) * max(wave_conf, 0.5)

        elif cfg.sizing_mode == "kelly":
            # 凯利式物理仓位
            pc = float(feats["phys_conf"][i])
            if np.isnan(pc):
                pc = 0.5
            win_prob = cfg.kelly_win_prob_base + cfg.kelly_win_prob_scale * pc
            odds = state.current_tp_pct / max(state.current_trail_pct, 1e-6)
            kelly_f = (win_prob * odds - (1 - win_prob)) / odds
            size = max(0, kelly_f * cfg.kelly_fraction) * max(wave_conf, 0.5)

        else:
            size = cfg.base_position * max(wave_conf, 0.5)

        # 物理置信度仓位调节
        pc = float(feats["phys_conf"][i])
        if not np.isnan(pc):
            multiplier = 0.6 + 1.0 * pc
            size = size * multiplier

        return float(np.clip(size, cfg.position_min, cfg.position_max))

    # ------------------------------------------------------------------
    # Layer 3: 动态风险控制
    # ------------------------------------------------------------------

    def update_trailing_stop(
        self,
        i: int,
        current_high: float,
        current_low: float,
        feats: Dict[str, np.ndarray],
        state: PhysicsState,
    ) -> float:
        """更新追踪止损价（多头）

        返回: 新的追踪止损价
        """
        cfg = self.config

        if not cfg.enable_dynamic_stoploss:
            trail_pct = cfg.base_trailing_pct
        else:
            trail_pct = self._compute_trail_pct(i, feats)

        state.current_trail_pct = trail_pct

        # 多头：追踪止损只上移
        if state.direction > 0:
            state.peak_price = max(state.peak_price, current_high)
            new_stop = state.peak_price * (1 - trail_pct)
            if new_stop > state.trailing_stop_price:
                state.trailing_stop_price = new_stop

        # 空头：追踪止损只下移
        elif state.direction < 0:
            state.trough_price = min(state.trough_price, current_low)
            new_stop = state.trough_price * (1 + trail_pct)
            if new_stop < state.trailing_stop_price or state.trailing_stop_price == 0:
                state.trailing_stop_price = new_stop

        return state.trailing_stop_price

    def compute_take_profit(self, i: int, feats: Dict[str, np.ndarray], state: PhysicsState) -> float:
        """计算止盈目标比例"""
        cfg = self.config

        if not cfg.enable_dynamic_takeprofit or cfg.take_profit_mode == "fixed":
            tp_pct = cfg.base_take_profit_pct
        else:
            ks = float(feats["kinetic_score"][i])
            if np.isnan(ks):
                ks = 0.5
            tp_factor = 0.5 + 1.5 * ks
            tp_pct = cfg.base_take_profit_pct * tp_factor
            tp_pct = float(np.clip(tp_pct, cfg.tp_min, cfg.tp_max))

        state.current_tp_pct = tp_pct
        return tp_pct

    def _compute_trail_pct(self, i: int, feats: Dict[str, np.ndarray]) -> float:
        """计算追踪止损距离比例"""
        cfg = self.config
        mode = cfg.trailing_mode

        if mode == "fixed":
            return cfg.base_trailing_pct

        ts = float(feats["trend_score"][i])
        rs = float(feats["reversal_score"][i])
        ks = float(feats["kinetic_score"][i])
        if np.isnan(ts):
            ts = 0.5
        if np.isnan(rs):
            rs = 0.5
        if np.isnan(ks):
            ks = 0.5

        if mode == "eta":
            factor = 0.5 + 1.5 * ts
        elif mode == "jerk":
            factor = 0.5 + 1.0 * rs
        elif mode == "combo":
            combined = ts * 0.5 + rs * 0.3 + ks * 0.2
            factor = 0.5 + 1.5 * combined
        else:
            factor = 1.0

        trail = cfg.base_trailing_pct * factor
        return float(np.clip(trail, cfg.trail_min, cfg.trail_max))

    # ------------------------------------------------------------------
    # 检查止损止盈触发
    # ------------------------------------------------------------------

    def check_stop_loss_trigger(
        self, current_low: float, current_high: float, state: PhysicsState
    ) -> bool:
        """检查是否触发追踪止损"""
        if state.direction == 0:
            return False
        if state.direction > 0:
            return current_low <= state.trailing_stop_price
        else:
            return current_high >= state.trailing_stop_price

    def check_take_profit_trigger(
        self, current_high: float, current_low: float, state: PhysicsState
    ) -> bool:
        """检查是否触发止盈"""
        if state.direction == 0 or state.entry_price <= 0:
            return False
        if state.direction > 0:
            tp_price = state.entry_price * (1 + state.current_tp_pct)
            return current_high >= tp_price
        else:
            tp_price = state.entry_price * (1 - state.current_tp_pct)
            return current_low <= tp_price

    # ------------------------------------------------------------------
    # 向量化增强（批量处理）
    # ------------------------------------------------------------------

    def enhance_positions(
        self,
        prices: pd.DataFrame,
        base_positions: np.ndarray,
        wave_signals: Optional[np.ndarray] = None,
        wave_confs: Optional[np.ndarray] = None,
        feats: Optional[Dict[str, np.ndarray]] = None,
    ) -> Tuple[np.ndarray, Dict]:
        """向量化增强仓位序列

        参数:
            prices: OHLCV DataFrame
            base_positions: 基础仓位序列（带方向，正=多，负=空）
            wave_signals: 波浪信号序列（可选）
            wave_confs: 波浪置信度序列（可选）
            feats: 预计算物理特征（可选，不传则内部计算）

        返回:
            (enhanced_positions, stats)
        """
        cfg = self.config
        n = len(prices)

        if feats is None:
            feats = self.compute_features(prices)

        enhanced = base_positions.copy().astype(float)
        stats = {
            "filtered_count": 0,
            "adjusted_count": 0,
            "avg_phys_conf": float(np.nanmean(feats["phys_conf"])),
        }

        # 如果有波浪信号，进行信号质量过滤
        if wave_signals is not None and wave_confs is not None and cfg.enable_signal_filter:
            wave_long = np.isin(wave_signals, ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3"))
            wave_short = np.isin(wave_signals, ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3"))
            has_signal = wave_long | wave_short

            # 波浪置信度过滤
            low_wave_conf = wave_confs < cfg.wave_conf_threshold
            filter1 = has_signal & low_wave_conf

            # 物理置信度过滤
            pc = feats["phys_conf"]
            low_phys_conf = pc < cfg.phys_conf_threshold
            filter2 = has_signal & ~low_wave_conf & low_phys_conf

            # 过滤的bar仓位归零
            enhanced[filter1 | filter2] = 0
            stats["filtered_count"] = int(np.sum(filter1 | filter2))

        # 动态仓位调节
        if cfg.enable_dynamic_sizing and cfg.sizing_mode != "fixed":
            nonzero_mask = enhanced != 0
            if np.any(nonzero_mask):
                ks = feats["kinetic_score"]
                pc = feats["phys_conf"]

                # 动能力度仓位因子
                kinetic_factor = 0.5 + 1.5 * np.where(np.isnan(ks), 0.5, ks)
                # 物理置信度仓位调节
                conf_multiplier = 0.6 + 1.0 * np.where(np.isnan(pc), 0.5, pc)

                # 对非零仓位进行调节（保持方向）
                directions = np.sign(enhanced[nonzero_mask])
                abs_pos = np.abs(enhanced[nonzero_mask])
                adjusted = abs_pos * kinetic_factor[nonzero_mask] * conf_multiplier[nonzero_mask] / kinetic_factor[nonzero_mask]
                # 简化：只应用物理置信度调节
                adjusted = abs_pos * conf_multiplier[nonzero_mask]
                adjusted = np.clip(adjusted, cfg.position_min, cfg.position_max)
                enhanced[nonzero_mask] = adjusted * directions
                stats["adjusted_count"] = int(np.sum(nonzero_mask))

        return enhanced, stats
