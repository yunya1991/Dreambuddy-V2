"""波浪策略适配器 (Elliott Wave Strategy Adapter)

主力策略：V4 + 波浪互斥融合（V4定方向，波浪择时加仓）
- V4 减半周期策略：主策略，定方向（多/空/空仓）
- 波浪策略：择时加仓，同向时叠加仓位，反向时以 V4 为主
- 物理引擎：信号评估 + 动态止损止盈 + 动能力度仓位

互斥融合规则（9年回测验证，BTC年化 56.43%，夏普 1.4112）：
- V4 多头 + 波浪看多 → V4 仓位 + 波浪加仓（同向叠加）
- V4 多头 + 波浪中性/看空 → 保持 V4 仓位（互斥：V4 优先）
- V4 空仓 + 波浪看多 → 波浪轻仓抄底（上限 30%）
- V4 空仓 + 波浪看空 → 空仓观望
- V4 空头 + 波浪看空 → 保持 V4 空头
- V4 空头 + 波浪看多 → V4 空头减半（波浪提示反弹）

集成的4项物理增强：
1. 动能力度仓位: base × (0.5 + 1.5 × kinetic_score)
2. 仓位调节: × (0.6 + 1.0 × phys_conf)
3. 宽追踪止损(jerk反转保护): combo模式, 范围[6%, 15%]
4. 动能止盈: kinetic模式, 范围[13%, 50%]

调用方式：
    from ml.ewave_strategy_adapter import EWaveStrategyAdapter, WaveConfig
    adapter = EWaveStrategyAdapter(WaveConfig())
    wave_result = adapter.evaluate(daily_df, v4_action, v4_direction, v4_position_pct)
    # wave_result 包含: wave_signal, wave_position, wave_direction, total_position, fusion_rule

文件: ml/ewave_strategy_adapter.py
"""

import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, Optional
from dataclasses import dataclass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from ml.ewave_recognizer import ElliottWaveRecognizer, WAVE_SIGNALS
from ml.pitd_confidence_scorer import PhysicsConfidenceScorer, ConfidenceWeights
from ml.pitd_kinematics_engineer import KinematicsEngineer
from ml.pitd_dynamics_engineer import DynamicsEngineer


@dataclass
class WaveConfig:
    """波浪策略配置（V4+波浪互斥融合最优参数）

    主力策略：V4 + 波浪互斥融合（V4定方向，波浪择时加仓）
    - V4 多头 + 波浪看多 → V4 仓位 + 波浪加仓（同向叠加）
    - V4 多头 + 波浪中性/看空 → 保持 V4 仓位（V4 优先）
    - V4 空仓 + 波浪看多 → 波浪轻仓抄底（上限 50%）
    - V4 空仓 + 波浪看空 → 空仓观望
    - V4 空头 + 波浪看空 → 保持 V4 空头
    - V4 空头 + 波浪看多 → V4 空头减半（波浪提示反弹）

    9年回测验证（BTC，valid_start=730，样本外已验证）：
    - 纯V4基线：年化 62.89%，夏普 1.374，回撤 -44.37%，Calmar 1.418
    - 默认参数融合：年化 66.64%，夏普 1.407，回撤 -43.31%，Calmar 1.539
    - 优化参数融合：年化 70.31%，夏普 1.455，回撤 -42.52%，Calmar 1.654（+3.67pp）
    - 样本外：优化 57.56% vs 默认 55.76%（+1.80pp），Calmar 2.61 vs 2.53（+0.08）

    配置要点（贝叶斯优化 Optuna TPE 50 trials）：
    - ZigZag=0.05：信号活跃度与准确性平衡
    - 信号过滤关闭：由互斥融合规则统一筛选
    - 保留4项物理增强：jerk止损 + 动能止盈 + 动能力度仓位 + 仓位调节
    - wave_weight=0.6：波浪加仓权重（同向时叠加 0.6×wave_conf，优化值）
    - confirm_threshold=0.6：波浪置信度确认阈值
    - bottom_position_cap=0.5：抄底仓位上限（优化值，原0.3）
    """

    # 基础仓位
    base_position: float = 0.3           # 波浪基础仓位（3成）
    max_position: float = 0.5            # 波浪最大仓位上限（5成）

    # 波浪识别参数（融合最优：0.05信号更活跃）
    zigzag_threshold: float = 0.05       # ZigZag转折阈值

    # 信号质量过滤（互斥融合中关闭，纯波浪独立运行时开启）
    wave_conf_threshold: float = 0.0     # 0.0=关闭，0.7=纯波浪最优
    phys_conf_threshold: float = 0.0     # 0.0=关闭，0.5=纯波浪最优

    # 动态风险控制（宽追踪+动能止盈+jerk反转保护）
    enable_dynamic_stoploss: bool = True
    enable_dynamic_takeprofit: bool = True
    base_trailing_pct: float = 0.08      # 基础追踪止损距离8%
    base_take_profit_pct: float = 0.25   # 基础止盈目标25%
    trailing_mode: str = "combo"         # 综合追踪（trend+reversal+kinetic）
    take_profit_mode: str = "kinetic"    # 动能止盈
    trail_min: float = 0.06              # 追踪止损下限6%
    trail_max: float = 0.15              # 追踪止损上限15%
    tp_min: float = 0.13                 # 止盈下限13%
    tp_max: float = 0.50                 # 止盈上限50%

    # 动态仓位管理（动能力度仓位）
    enable_dynamic_sizing: bool = True
    sizing_mode: str = "kinetic"         # 动能力度仓位

    # 互斥融合参数（V4+波浪互斥融合：V4定方向，波浪择时加仓）
    # 贝叶斯优化 Optuna TPE 50 trials 最优参数（2026-07-19，样本外已验证）
    mutex_fusion: bool = True            # 启用互斥融合模式
    wave_weight: float = 0.6             # 波浪加仓权重（优化值，原0.3）
    confirm_threshold: float = 0.6       # 波浪置信度确认阈值
    bottom_position_cap: float = 0.5     # V4空仓时波浪抄底仓位上限（优化值，原0.3）
    total_position_cap: float = 1.0      # 总仓位上限
    keep_v4_dip_buy: bool = True         # V4空仓但有dip_buy仓位时保留（8年+4年回测验证通过）

    # 物理评估器权重（9年回测最优）
    enable_physics: bool = True
    w_eta: float = 0.211
    w_reversal: float = 0.368            # 反转风险权重最高
    w_support: float = 0.211
    w_kinetic: float = 0.211
    position_lower: float = 0.6          # 仓位调节下限（0.6+1.0×phys_conf）
    position_scale: float = 1.0          # 仓位调节幅度
    eta_strong: float = 0.20
    eta_weak: float = 0.10


class EWaveStrategyAdapter:
    """波浪策略适配器

    将波浪识别器+物理引擎评估器封装为一个独立的策略模块，
    与V4主策略配合实现互斥融合：V4定方向，波浪择时加仓。

    用法:
        adapter = EWaveStrategyAdapter(WaveConfig())
        result = adapter.evaluate(daily_df,
                                  v4_action='ENTER_LONG',
                                  v4_direction='BULL',
                                  v4_position_pct=0.6)
    """

    def __init__(self, config: WaveConfig = None):
        self.config = config or WaveConfig()
        self.recognizer = ElliottWaveRecognizer(
            zigzag_threshold=self.config.zigzag_threshold
        )
        # 复用物理增强器（集成信号评估器 + jerk止损 + 动能仓位 + 动能止盈）
        if self.config.enable_physics:
            from ml.physics_enhancer import PhysicsEnhancer, PhysicsEnhancerConfig
            phys_cfg = PhysicsEnhancerConfig(
                enabled=True,
                enable_signal_filter=True,
                wave_conf_threshold=self.config.wave_conf_threshold,
                phys_conf_threshold=self.config.phys_conf_threshold,
                enable_dynamic_sizing=self.config.enable_dynamic_sizing,
                sizing_mode=self.config.sizing_mode,
                base_position=self.config.base_position,
                enable_dynamic_stoploss=self.config.enable_dynamic_stoploss,
                enable_dynamic_takeprofit=self.config.enable_dynamic_takeprofit,
                base_trailing_pct=self.config.base_trailing_pct,
                base_take_profit_pct=self.config.base_take_profit_pct,
                trailing_mode=self.config.trailing_mode,
                take_profit_mode=self.config.take_profit_mode,
                trail_min=self.config.trail_min,
                trail_max=self.config.trail_max,
                tp_min=self.config.tp_min,
                tp_max=self.config.tp_max,
                w_eta=self.config.w_eta,
                w_reversal=self.config.w_reversal,
                w_support=self.config.w_support,
                w_kinetic=self.config.w_kinetic,
                eta_strong=self.config.eta_strong,
                eta_weak=self.config.eta_weak,
            )
            self.physics_enhancer = PhysicsEnhancer(phys_cfg)
            # 保留 physics_scorer 作为兼容接口（延迟初始化）
            self.physics_scorer = None
        else:
            self.physics_enhancer = None
            self.physics_scorer = None

    def evaluate(
        self,
        daily_df: pd.DataFrame,
        v4_action: str = "WAIT",
        v4_direction: str = "NEUTRAL",
        v4_position_pct: float = 0.0,
        symbol: str = None,
    ) -> Dict:
        """评估波浪策略信号并计算互斥融合后的总仓位

        主力策略：V4 + 波浪互斥融合（V4定方向，波浪择时加仓）
        - V4 多头 + 波浪看多 → V4 仓位 + 波浪加仓
        - V4 多头 + 波浪中性/看空 → 保持 V4 仓位
        - V4 空仓 + 波浪看多 → 波浪轻仓抄底
        - V4 空仓 + 波浪看空 → 空仓观望
        - V4 空头 + 波浪看空 → 保持 V4 空头
        - V4 空头 + 波浪看多 → V4 空头减半

        参数:
            daily_df: 日线OHLCV数据
            v4_action: V4主策略action (ENTER_LONG/ENTER_SHORT/WAIT)
            v4_direction: V4主策略方向 (BULL/BEAR/NEUTRAL)
            v4_position_pct: V4主策略仓位比例
            symbol: 币种符号（用于基于市值动态调整 confirm_threshold）

        返回:
            Dict 包含:
                - wave_signal: 波浪信号类型
                - wave_label: 波浪结构标签
                - current_wave: 当前浪号
                - wave_confidence: 波浪置信度
                - wave_direction: 波浪方向 (LONG/SHORT/NEUTRAL)
                - wave_position_pct: 波浪仓位比例
                - wave_physics_confidence: 物理置信度
                - wave_eta: 当前η值
                - total_position_pct: 融合后总仓位
                - final_action: 融合后最终action
                - fusion_rule: 融合规则说明
        """
        result = {
            "wave_signal": "WAIT",
            "wave_label": "INCOMPLETE",
            "current_wave": 0,
            "wave_confidence": 0.0,
            "wave_direction": "NEUTRAL",
            "wave_position_pct": 0.0,
            "wave_physics_confidence": None,
            "wave_eta": None,
            "wave_kinetic_score": None,
            "wave_trailing_stop_pct": None,
            "wave_take_profit_pct": None,
            "total_position_pct": v4_position_pct,
            "final_action": v4_action,
            "final_direction": v4_direction,
            "fusion_rule": "no_wave_data",
            "enabled": True,
        }

        if daily_df is None or len(daily_df) < 90:
            result["fusion_rule"] = "insufficient_data"
            result["enabled"] = False
            return result

        try:
            # 1. 识别波浪结构
            wave_struct = self.recognizer.identify_waves(daily_df)
            result["wave_signal"] = wave_struct.signal
            result["wave_label"] = wave_struct.wave_label
            result["current_wave"] = wave_struct.current_wave
            result["wave_confidence"] = round(wave_struct.confidence, 4)

            # 2. 解析波浪方向
            wave_dir = self._parse_wave_direction(wave_struct.signal)
            result["wave_direction"] = wave_dir

            # 3. 计算波浪仓位
            wave_pos = self._compute_wave_position(
                daily_df, wave_struct, v4_action, v4_direction
            )
            result["wave_position_pct"] = round(wave_pos, 4)

            # 4. 计算物理置信度及动态止损止盈（如启用）
            if self.config.enable_physics and self.physics_enhancer is not None:
                try:
                    feats = self.physics_enhancer.compute_features(daily_df)
                    n = len(daily_df)
                    last_idx = n - 1

                    current_eta = float(feats["eta"][last_idx]) if not np.isnan(feats["eta"][last_idx]) else 0.0
                    result["wave_eta"] = round(current_eta, 4)

                    current_conf = float(feats["phys_conf"][last_idx]) if not np.isnan(feats["phys_conf"][last_idx]) else 0.5
                    result["wave_physics_confidence"] = round(current_conf, 4)

                    current_ks = float(feats["kinetic_score"][last_idx]) if not np.isnan(feats["kinetic_score"][last_idx]) else 0.5
                    result["wave_kinetic_score"] = round(current_ks, 4)

                    # 动态追踪止损距离（jerk反转保护 + 综合模式）
                    from ml.physics_enhancer import PhysicsState
                    tmp_state = PhysicsState(direction=1 if wave_dir == "LONG" else -1)
                    trail_pct = self.physics_enhancer._compute_trail_pct(last_idx, feats)
                    result["wave_trailing_stop_pct"] = round(trail_pct, 4)

                    # 动能止盈目标
                    tp_pct = self.physics_enhancer.compute_take_profit(last_idx, feats, tmp_state)
                    result["wave_take_profit_pct"] = round(tp_pct, 4)
                except Exception as e:
                    result["wave_eta"] = None
                    result["wave_physics_confidence"] = None
                    result["physics_error"] = str(e)

            # 5. 融合 V4 + 波浪仓位（互斥融合：V4定方向，波浪择时加仓）
            # 5.1 基于市值动态调整 confirm_threshold（BTC等超大盘币种阈值降为0.4）
            original_threshold = self.config.confirm_threshold
            if symbol:
                try:
                    from ml.market_cap_provider import get_confirm_threshold_by_symbol
                    dynamic_threshold = get_confirm_threshold_by_symbol(symbol)
                    if dynamic_threshold != original_threshold:
                        self.config.confirm_threshold = dynamic_threshold
                        result["dynamic_confirm_threshold"] = dynamic_threshold
                except Exception:
                    pass

            total_pos, final_action, final_dir, fusion_rule = self._fuse_positions(
                v4_action, v4_direction, v4_position_pct,
                wave_struct.signal, wave_dir, wave_pos
            )

            # 恢复原始阈值，避免影响其他调用
            self.config.confirm_threshold = original_threshold

            result["total_position_pct"] = round(total_pos, 4)
            result["final_action"] = final_action
            result["final_direction"] = final_dir
            result["fusion_rule"] = fusion_rule

        except Exception as e:
            result["enabled"] = False
            result["fusion_rule"] = f"error: {str(e)}"

        return result

    def _parse_wave_direction(self, wave_signal: str) -> str:
        """解析波浪信号方向"""
        if wave_signal.startswith("ENTER_LONG") or wave_signal.startswith("HOLD_LONG"):
            return "LONG"
        elif wave_signal.startswith("ENTER_SHORT") or wave_signal.startswith("HOLD_SHORT"):
            return "SHORT"
        elif wave_signal.startswith("EXIT_LONG"):
            return "EXIT_LONG"
        elif wave_signal.startswith("EXIT_SHORT"):
            return "EXIT_SHORT"
        return "NEUTRAL"

    def _compute_wave_position(
        self,
        daily_df: pd.DataFrame,
        wave_struct,
        v4_action: str,
        v4_direction: str,
    ) -> float:
        """计算波浪仓位（集成物理增强器）

        集成三层物理增强：
        1. 信号质量过滤：波浪置信度 ≥ wave_conf_threshold AND 物理置信度 ≥ phys_conf_threshold
           （融合策略中关闭过滤=0.0，纯波浪独立运行时开启=0.7/0.5）
        2. 动态仓位管理：动能力度仓位 base × (0.5 + 1.5 × kinetic_score)
        3. 仓位调节：最终仓位 = 基础仓位 × (0.6 + 1.0 × phys_conf)
        """
        sig = wave_struct.signal
        wave_conf = max(wave_struct.confidence, 0.5)

        is_enter_long = sig in ("ENTER_LONG_W3", "ENTER_LONG_W5", "HOLD_LONG_W3")
        is_enter_short = sig in ("ENTER_SHORT_W3", "ENTER_SHORT_W5", "HOLD_SHORT_W3")
        is_exit = sig in ("EXIT_LONG_W5", "EXIT_SHORT_W5")

        if is_exit or not (is_enter_long or is_enter_short):
            return 0.0

        # Layer 1: 波浪置信度过滤
        if wave_conf < self.config.wave_conf_threshold:
            return 0.0

        # 基础仓位
        base_pos = self.config.base_position * wave_conf

        # 物理增强：信号过滤 + 动态仓位 + 仓位调节
        if self.config.enable_physics and self.physics_enhancer is not None:
            try:
                # 预计算物理特征（最后一个bar）
                feats = self.physics_enhancer.compute_features(daily_df)
                n = len(daily_df)
                last_idx = n - 1

                # Layer 1: 物理置信度过滤
                pc = float(feats["phys_conf"][last_idx])
                if np.isnan(pc):
                    pc = 0.5
                if pc < self.config.phys_conf_threshold:
                    return 0.0  # 物理置信度不足，拒绝入场

                # Layer 2: 动能力度仓位
                ks = float(feats["kinetic_score"][last_idx])
                if np.isnan(ks):
                    ks = 0.5
                if self.config.enable_dynamic_sizing and self.config.sizing_mode == "kinetic":
                    kinetic_factor = 0.5 + 1.5 * ks
                    base_pos = base_pos * kinetic_factor

                # Layer 3: 物理置信度仓位调节
                # 最终仓位 = 基础仓位 × (0.6 + 1.0 × phys_conf)
                multiplier = 0.6 + 1.0 * pc
                base_pos = base_pos * multiplier

                # 记录物理信息到结果
                self._last_phys_conf = pc
                self._last_kinetic_score = ks
                self._last_eta = float(feats["eta"][last_idx]) if not np.isnan(feats["eta"][last_idx]) else 0.0
            except Exception:
                pass  # 物理增强失败，保持基础仓位

        # 限制在最大仓位内
        return float(np.clip(base_pos, 0.0, self.config.max_position))

    def _fuse_positions(
        self,
        v4_action: str,
        v4_direction: str,
        v4_position_pct: float,
        wave_signal: str,
        wave_direction: str,
        wave_position_pct: float,
    ) -> tuple:
        """融合 V4 主策略和波浪仓位（互斥融合：V4定方向，波浪择时加仓）

        互斥融合规则（9年回测验证，BTC年化 56.43%，夏普 1.4112）：
        1. V4 多头 + 波浪看多 → V4 仓位 + 波浪加仓（同向叠加）
        2. V4 多头 + 波浪中性/看空 → 保持 V4 仓位（互斥：V4 优先）
        3. V4 空仓 + 波浪看多 → 波浪轻仓抄底（上限 bottom_position_cap）
        4. V4 空仓 + 波浪看空 → 空仓观望
        5. V4 空头 + 波浪看空 → 保持 V4 空头
        6. V4 空头 + 波浪看多 → V4 空头减半（波浪提示反弹）

        返回: (total_position, final_action, final_direction, fusion_rule)
        """
        cap = self.config.total_position_cap
        wave_weight = self.config.wave_weight
        confirm_threshold = self.config.confirm_threshold
        bottom_cap = self.config.bottom_position_cap

        v4_long = v4_action == "ENTER_LONG"
        v4_short = v4_action == "ENTER_SHORT"
        v4_wait = v4_action == "WAIT"

        wave_long = wave_direction == "LONG"
        wave_short = wave_direction == "SHORT"
        wave_exit_long = wave_direction == "EXIT_LONG"
        wave_exit_short = wave_direction == "EXIT_SHORT"

        # 解析波浪置信度（从 wave_position_pct 推断：wave_pos = base × wave_conf × ...）
        # 简化：wave_position_pct > 0 表示波浪有信号
        wave_has_signal = wave_position_pct > 0
        # 通过 wave_position_pct / base_position 估算置信度
        estimated_wave_conf = min(wave_position_pct / max(self.config.base_position, 1e-6), 1.0) if wave_has_signal else 0.0
        wave_confirmed = estimated_wave_conf >= confirm_threshold

        # 规则1: V4 多头
        if v4_long:
            if wave_long and wave_confirmed:
                # 1a: V4多头 + 波浪看多 → V4仓位 + 波浪加仓（同向叠加）
                add_amount = wave_weight * max(estimated_wave_conf, 0.5)
                total = min(v4_position_pct + add_amount, cap)
                return total, "ENTER_LONG", "BULL", "v4_long_wave_add"
            else:
                # 1b: V4多头 + 波浪中性/看空 → 保持 V4 仓位
                return v4_position_pct, "ENTER_LONG", "BULL", "v4_long_keep"

        # 规则2: V4 空仓
        if v4_wait:
            if wave_long and wave_confirmed:
                bottom_pos = wave_weight * max(estimated_wave_conf, 0.5)
                bottom_pos = min(bottom_pos, bottom_cap)
                return bottom_pos, "ENTER_LONG", "BULL", "v4_wait_wave_bottom"
            elif self.config.keep_v4_dip_buy and v4_position_pct > 0.001:
                return v4_position_pct, "ENTER_LONG", "BULL", "v4_wait_keep_dip_buy"
            else:
                return 0.0, "WAIT", "NEUTRAL", "v4_wait_wave_wait"

        # 规则3: V4 空头
        if v4_short:
            if wave_long and wave_confirmed:
                # 3a: V4空头 + 波浪看多 → V4空头减半（波浪提示反弹）
                return v4_position_pct * 0.5, "ENTER_SHORT", "BEAR", "v4_short_wave_reduce"
            else:
                # 3b: V4空头 + 波浪中性/看空 → 保持 V4 空头
                return v4_position_pct, "ENTER_SHORT", "BEAR", "v4_short_keep"

        # 默认：保持 V4 决策
        return v4_position_pct, v4_action, v4_direction, "v4_default"


# 默认适配器实例（3成基础仓位）
DEFAULT_ADAPTER = EWaveStrategyAdapter(WaveConfig(base_position=0.3))
