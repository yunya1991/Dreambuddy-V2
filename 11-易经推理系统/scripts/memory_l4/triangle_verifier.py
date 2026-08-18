#!/usr/bin/env python3
"""
五角校验器（v4 风险评分风控版）— 基于五源风险信号综合评分实现双向风控。

定位变更（2026-08-05 v4）：
    v3 纯风控版仅双预警止损收紧，五角校验未真正发挥作用。
    v4 引入风险评分驱动的双向风控，让五角校验主动管理仓位/杠杆/止盈止损。

    与 v2 的本质区别：
        - v2: 五源方向投票 → 一致性 → 置信度/仓位调整（方向驱动，已证伪）
        - v4: 五源风险信号 → 风险评分 → 仓位/杠杆/止盈止损调控（风险驱动）

    ✅ 核心机制：
        1. 五源风险信号综合评分 (0=安全, 1=高危)
           - 不投票方向，只评估风险等级
           - 风险注意力动态加权（追踪各源风险预警准确率）
        2. 双向风控调控：
           - 低风险 → 加仓/提杠杆/提高止盈
           - 高风险 → 降仓/降杠杆/收紧止损
        3. v3 双预警止损收紧保留（TDA+Ising 同时触发 → sl_tighten=0.85 底线）

    ❌ 仍然不做：
        - 方向投票（BCRM2 主导方向）
        - 开仓阻断（不阻止 BCRM2 信号）
        - 置信度调整（不修改 BCRM2 置信度）
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List, Tuple
import logging
import numpy as np
import json
from pathlib import Path
from collections import deque

logger = logging.getLogger(__name__)

# ================================================================
# v4 风险评分风控版参数
# ================================================================
@dataclass
class PentagonParams:
    """五角校验 v4 参数 — 风险评分驱动的双向风控。

    核心参数：
        - 风险评分阈值 + 对应的仓位/杠杆/止盈/止损系数
        - 风险注意力参数（追踪各源风险预警准确率）
        - v3 双预警止损收紧保留（底线）
    """
    # ── v3 保留：双预警止损收紧底线 ──
    sl_tighten_double: float = 0.85  # TDA+Ising 同时触发 → 收紧15%
    sl_tighten_single: float = 1.0

    # ── v4 新增：风险评分风控参数 ──
    # 风险评分分档阈值（risk_score 0=安全, 1=高危）
    risk_threshold_low: float = 0.15    # < 0.15 → 低风险（加仓/提杠杆）
    risk_threshold_mid: float = 0.50    # 0.15-0.50 → 正常
    risk_threshold_high: float = 0.70   # 0.50-0.70 → 中风险（降仓）
    # >= 0.70 → 高风险（大幅降仓/收紧止损）

    # 低风险档：温和加仓/提杠杆/提高止盈
    pos_factor_low_risk: float = 1.10
    leverage_factor_low_risk: float = 1.05
    tp_mult_low_risk: float = 1.10

    # 正常档：不调整
    pos_factor_normal: float = 1.0
    leverage_factor_normal: float = 1.0
    tp_mult_normal: float = 1.0

    # 中风险档：降仓/降杠杆/略降止盈/略收紧止损
    pos_factor_mid_risk: float = 0.85
    leverage_factor_mid_risk: float = 0.90
    tp_mult_mid_risk: float = 0.95
    sl_tighten_mid_risk: float = 0.95

    # 高风险档：大幅降仓/降杠杆/降止盈/收紧止损
    pos_factor_high_risk: float = 0.60
    leverage_factor_high_risk: float = 0.70
    tp_mult_high_risk: float = 0.90
    sl_tighten_high_risk: float = 0.85

    # ── v4 新增：风险注意力参数 ──
    risk_attention_enabled: bool = True
    risk_attention_window: int = 30      # 追踪窗口
    risk_attention_decay: float = 0.97   # 指数衰减系数
    risk_attention_min_weight: float = 0.10
    risk_attention_max_weight: float = 0.40

    # ── v4 新增：五源风险信号基础权重（初始等权）──
    risk_weight_bcrm2: float = 0.20
    risk_weight_force: float = 0.20
    risk_weight_a0: float = 0.20
    risk_weight_ising: float = 0.20
    risk_weight_tda: float = 0.20

    # ── 接口兼容（v3 遗留，全部中性）──
    weight_bcrm2: float = 0.20
    weight_force: float = 0.20
    weight_a0: float = 0.20
    weight_ising: float = 0.20
    weight_tda: float = 0.20
    bonus_strong_agree: float = 0.0
    bonus_majority: float = 0.0
    penalty_divergent: float = 0.0
    penalty_conflict: float = 0.0
    penalty_reversal: float = 0.0
    penalty_ising_alert: float = 0.0
    penalty_tda_warning: float = 0.0
    penalty_double_warning: float = 0.0
    max_total_penalty: float = 0.0
    attention_enabled: bool = False
    attention_window: int = 30
    attention_decay: float = 1.0
    attention_min_weight: float = 0.20
    attention_max_weight: float = 0.20
    pos_factor_strong_agree: float = 1.0
    pos_factor_majority: float = 1.0
    pos_factor_divergent: float = 1.0
    pos_factor_single_warning: float = 1.0
    pos_factor_double_warning: float = 1.0
    pos_factor_reversal: float = 1.0
    fail_closed_threshold: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "PentagonParams":
        known = {k: v for k, v in d.items() if k in cls().__dict__}
        return cls(**known)


@dataclass
class TriangleVerificationResult:
    """五角校验结果（保留类名向后兼容）"""
    # 五源方向 (-1=空, 0=中性, +1=多)
    bcrm2_direction: int = 0
    force_direction: int = 0
    a0_direction: int = 0
    ising_direction: int = 0        # Ising相变方向（P1新增）
    tda_direction: int = 0          # TDA拓扑方向（P2新增）

    # 校验结果
    agreement_score: float = 0.0     # 一致性得分 0-1
    confidence_adjustment: float = 0.0  # 置信度调整 -0.2~+0.2
    reversal_alert: bool = False     # 强反转预警
    reversal_strength: float = 0.0   # 反转强度
    risk_warnings: List[str] = field(default_factory=list)
    should_fail_closed: bool = False  # 是否建议 fail_closed

    # 各源详情
    force_result_dict: Optional[dict] = None
    ising_result_dict: Optional[dict] = None
    tda_result_dict: Optional[dict] = None  # TDA拓扑详情（P2新增）

    # 校验模式
    verdict: str = ""  # STRONG_AGREE / MAJORITY_AGREE / DIVERGENT / CONFLICT

    # P3预警联动策略（v3保留）
    position_factor: float = 1.0     # 仓位系数（1.0=正常, 0.5=降仓50%, 1.15=加仓15%）
    sl_tighten_factor: float = 1.0   # 止损收紧系数（1.0=正常, 0.85=收紧15%）
    early_exit_signal: bool = False  # 提前退出信号（TDA+Ising双重预警）

    # v4 新增：风险评分风控
    risk_score: float = 0.0          # 综合风险评分 0=安全, 1=高危
    risk_level: str = "NORMAL"       # LOW / NORMAL / MID / HIGH
    leverage_factor: float = 1.0     # 杠杆系数（1.0=正常, 1.15=提杠杆15%, 0.7=降杠杆30%）
    tp_adjustment: float = 1.0       # 止盈调整系数（1.0=正常, 1.1=提高止盈10%）

    def to_dict(self) -> dict:
        return {
            "bcrm2_direction": self.bcrm2_direction,
            "force_direction": self.force_direction,
            "a0_direction": self.a0_direction,
            "ising_direction": self.ising_direction,
            "tda_direction": self.tda_direction,
            "agreement_score": round(self.agreement_score, 4),
            "confidence_adjustment": round(self.confidence_adjustment, 4),
            "reversal_alert": self.reversal_alert,
            "reversal_strength": round(self.reversal_strength, 4),
            "risk_warnings": self.risk_warnings,
            "should_fail_closed": self.should_fail_closed,
            "force_result": self.force_result_dict,
            "ising_result": self.ising_result_dict,
            "tda_result": self.tda_result_dict,
            "verdict": self.verdict,
            "position_factor": round(self.position_factor, 3),
            "sl_tighten_factor": round(self.sl_tighten_factor, 3),
            "early_exit_signal": self.early_exit_signal,
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level,
            "leverage_factor": round(self.leverage_factor, 3),
            "tp_adjustment": round(self.tp_adjustment, 3),
        }


class TriangleVerifier:
    """五角校验器（v4 风险评分风控版）：五源风险信号综合评分 → 双向风控调控。

    核心流程：
        1. 提取五源风险信号（不投票方向）
        2. 风险注意力动态加权 → 综合风险评分
        3. 风险评分分档 → 仓位/杠杆/止盈/止损双向调控
        4. v3 双预警止损收紧叠加（底线保护）
    """

    SOURCE_NAMES = ["bcrm2", "force", "a0", "ising", "tda"]

    def __init__(self, params: Optional[PentagonParams] = None):
        self.params = params or PentagonParams()
        self._force_engine = None
        self._ising_detector = None
        self._tda_detector = None
        self._init_force_engine()
        self._init_ising_detector()
        self._init_tda_detector()

        # v4 风险注意力：追踪各源风险预警准确率（预警后市场是否恶化）
        self._risk_warning_history: Dict[str, deque] = {
            name: deque(maxlen=self.params.risk_attention_window)
            for name in self.SOURCE_NAMES
        }
        self._risk_dynamic_weights: Dict[str, float] = {
            "bcrm2": self.params.risk_weight_bcrm2,
            "force": self.params.risk_weight_force,
            "a0": self.params.risk_weight_a0,
            "ising": self.params.risk_weight_ising,
            "tda": self.params.risk_weight_tda,
        }
        # 记录上一笔风险信号，用于 record_outcome 时核对
        self._last_risk_signals: Optional[Dict[str, float]] = None

    def _init_force_engine(self):
        """延迟初始化力学引擎"""
        try:
            try:
                from bcrm.force_engine import ForceEngine
            except ImportError:
                from scripts.memory_l4.bcrm.force_engine import ForceEngine
            self._force_engine = ForceEngine()
            logger.info("[五角校验] 力学引擎已加载")
        except Exception as e:
            logger.warning(f"[五角校验] 力学引擎加载失败: {e}")

    def _init_ising_detector(self):
        """延迟初始化Ising相变检测器"""
        try:
            try:
                from bcrm.ising_phase_detector import IsingPhaseDetector
            except ImportError:
                from scripts.memory_l4.bcrm.ising_phase_detector import IsingPhaseDetector
            self._ising_detector = IsingPhaseDetector()
            logger.info("[五角校验] Ising相变检测器已加载")
        except Exception as e:
            logger.warning(f"[五角校验] Ising相变检测器加载失败: {e}")

    def _init_tda_detector(self):
        """延迟初始化TDA拓扑检测器（P2新增）"""
        try:
            try:
                from bcrm.tda_early_warning import TDAEarlyWarning
            except ImportError:
                from scripts.memory_l4.bcrm.tda_early_warning import TDAEarlyWarning
            self._tda_detector = TDAEarlyWarning()
            logger.info("[五角校验] TDA拓扑检测器已加载")
        except Exception as e:
            logger.warning(f"[五角校验] TDA拓扑检测器加载失败: {e}")

    def verify(
        self,
        bcrm2_direction: str,
        bcrm2_confidence: float,
        a0_result_dict: Optional[dict],
        market_snapshot: Dict[str, Any],
        df: Optional["pd.DataFrame"] = None,
    ) -> TriangleVerificationResult:
        """
        执行五角校验（v4 风险评分风控版）。

        流程：
            1. 运行五源检测器
            2. 提取五源风险信号（0=安全, 1=高危）
            3. 风险注意力动态加权 → 综合风险评分
            4. 风险评分分档 → 仓位/杠杆/止盈/止损双向调控
            5. v3 双预警止损收紧叠加（底线保护）

        不干预：方向投票、置信度调整、开仓阻断。
        """
        result = TriangleVerificationResult()
        p = self.params

        # 方向记录（仅诊断）
        result.bcrm2_direction = self._dir_str_to_int(bcrm2_direction)
        if a0_result_dict:
            bias = a0_result_dict.get("direction_bias", 0)
            result.a0_direction = 1 if bias > 0.1 else (-1 if bias < -0.1 else 0)

        # ── 1. 运行五源检测器 ──
        _, force_reversal, force_strength, force_dict = self._run_force_engine(market_snapshot, df)
        result.force_result_dict = force_dict

        _, ising_alert, ising_phase, ising_dict = self._run_ising_detector(market_snapshot, df)
        result.ising_result_dict = ising_dict

        _, tda_warning, tda_strength, tda_dict = self._run_tda_detector(market_snapshot, df)
        result.tda_result_dict = tda_dict

        # ── 2. 提取五源风险信号 (0=安全, 1=高危) ──
        a0_tension = a0_result_dict.get("overall_tension", 0) if a0_result_dict else 0
        a0_trauma = a0_result_dict.get("trauma_signal", False) if a0_result_dict else False

        risk_signals = {
            "bcrm2": max(0.0, 1.0 - bcrm2_confidence),           # 置信度低→风险高
            "force": 0.8 if force_reversal else 0.2,               # 力学反转→高风险
            "a0": min(1.0, a0_tension + (0.3 if a0_trauma else 0.0)),  # tension+trauma→风险
            "ising": 0.9 if ising_alert else 0.1,                  # 相变→高风险
            "tda": 0.9 if tda_warning else 0.1,                    # 拓扑突变→高风险
        }
        self._last_risk_signals = risk_signals.copy()

        # ── 3. 风险注意力动态加权 → 综合风险评分 ──
        weights = self._get_risk_weights()
        total_w = sum(weights.values())
        risk_score = sum(weights[k] * risk_signals[k] for k in self.SOURCE_NAMES) / max(total_w, 1e-6)
        risk_score = max(0.0, min(1.0, risk_score))
        result.risk_score = risk_score

        # ── 4. 风险评分分档 → 双向风控调控 ──
        if risk_score < p.risk_threshold_low:
            # 低风险：加仓/提杠杆/提高止盈
            result.risk_level = "LOW"
            result.position_factor = p.pos_factor_low_risk
            result.leverage_factor = p.leverage_factor_low_risk
            result.tp_adjustment = p.tp_mult_low_risk
            result.sl_tighten_factor = 1.0
        elif risk_score < p.risk_threshold_mid:
            # 正常：不调整
            result.risk_level = "NORMAL"
            result.position_factor = p.pos_factor_normal
            result.leverage_factor = p.leverage_factor_normal
            result.tp_adjustment = p.tp_mult_normal
            result.sl_tighten_factor = 1.0
        elif risk_score < p.risk_threshold_high:
            # 中风险：降仓/降杠杆/略降止盈/略收紧止损
            result.risk_level = "MID"
            result.position_factor = p.pos_factor_mid_risk
            result.leverage_factor = p.leverage_factor_mid_risk
            result.tp_adjustment = p.tp_mult_mid_risk
            result.sl_tighten_factor = p.sl_tighten_mid_risk
        else:
            # 高风险：大幅降仓/降杠杆/降止盈/收紧止损
            result.risk_level = "HIGH"
            result.position_factor = p.pos_factor_high_risk
            result.leverage_factor = p.leverage_factor_high_risk
            result.tp_adjustment = p.tp_mult_high_risk
            result.sl_tighten_factor = p.sl_tighten_high_risk

        # ── 5. v3 双预警止损收紧叠加（底线保护）──
        if tda_warning and ising_alert:
            result.early_exit_signal = True
            result.reversal_alert = True
            result.reversal_strength = 0.5 + tda_strength * 0.5
            # 取风险评分和双预警中更紧的止损
            result.sl_tighten_factor = min(result.sl_tighten_factor, p.sl_tighten_double)
            result.risk_warnings.append(
                f"P3双重预警：TDA({tda_strength:.2f}) + Ising({ising_phase or 'UNKNOWN'}) "
                f"→ 止损收紧至{result.sl_tighten_factor*100:.0f}%"
            )

        # ── 预警记录（诊断）──
        if ising_alert:
            result.risk_warnings.append(
                f"Ising相变预警：相态={ising_phase or 'UNKNOWN'}"
            )
        if tda_warning:
            result.risk_warnings.append(
                f"TDA拓扑突变预警：强度={tda_strength:.2f}"
            )
        if force_reversal and a0_tension > 0.5:
            result.risk_warnings.append(
                f"力学+A0反转预警（强度{(force_strength+a0_tension)/2:.2f}）"
            )
        if a0_trauma:
            if self._force_engine:
                self._force_engine.reset_velocity()
            result.risk_warnings.append("创伤信号：力学引擎速度已重置")

        # v4 中性值：不干预置信度/方向/阻断
        result.confidence_adjustment = 0.0
        result.should_fail_closed = False
        result.agreement_score = 0.5
        result.verdict = f"P4_RISK_CONTROL_{result.risk_level}"

        if result.risk_warnings:
            logger.debug(f"[五角校验v4] {result.risk_warnings}")
        logger.info(
            f"[五角校验v4] risk_score={risk_score:.3f} level={result.risk_level} "
            f"pos_factor={result.position_factor:.2f} lev_factor={result.leverage_factor:.2f} "
            f"tp_adj={result.tp_adjustment:.2f} sl_tighten={result.sl_tighten_factor:.2f} "
            f"ising={ising_alert} tda={tda_warning}"
        )

        return result

    # ================================================================
    # v4 风险注意力机制
    # ================================================================
    def record_outcome(self, source_directions: Dict[str, int], actual_direction: int,
                       actual_pnl_pct: Optional[float] = None):
        """记录交易结果，更新风险注意力权重。

        v4 改为追踪风险预警准确率：
            - 某源发出高风险信号(risk>0.5)后，市场确实恶化(pnl<0) → 准确
            - 某源发出高风险信号后，市场没恶化(pnl>0) → 不准确
            - 某源发出低风险信号(risk<0.3)后，市场恶化(pnl<0) → 不准确

        兼容旧接口：若 actual_pnl_pct 为 None，退化用方向匹配。
        """
        if not self.params.risk_attention_enabled or self._last_risk_signals is None:
            return

        # 判断市场是否恶化
        if actual_pnl_pct is not None:
            market_deteriorated = actual_pnl_pct < 0
        else:
            # 退化：方向不匹配视为恶化
            market_deteriorated = False
            for name in self.SOURCE_NAMES:
                src_dir = source_directions.get(name, 0)
                if src_dir != 0 and src_dir != actual_direction:
                    market_deteriorated = True
                    break

        # 核对各源风险信号准确性
        for name in self.SOURCE_NAMES:
            risk_val = self._last_risk_signals.get(name, 0.0)
            if risk_val > 0.5:
                # 高风险预警：市场恶化=准确，没恶化=不准确
                correct = market_deteriorated
            elif risk_val < 0.3:
                # 低风险信号：市场没恶化=准确，恶化=不准确
                correct = not market_deteriorated
            else:
                # 中间区域不评分
                continue
            self._risk_warning_history[name].append(1.0 if correct else 0.0)

        self._update_risk_weights()

    def _update_risk_weights(self):
        """指数衰减更新风险注意力权重。"""
        if not self.params.risk_attention_enabled:
            return

        p = self.params
        new_weights = {}
        for name in self.SOURCE_NAMES:
            history = self._risk_warning_history[name]
            if len(history) < 3:
                # 样本不足，保持初始权重
                new_weights[name] = self._risk_dynamic_weights[name]
                continue

            # 指数加权准确率
            accs = list(history)
            decay = p.risk_attention_decay
            ewma_acc = 0.0
            weight_sum = 0.0
            for i, acc in enumerate(reversed(accs)):
                w = decay ** i
                ewma_acc += acc * w
                weight_sum += w
            ewma_acc /= max(weight_sum, 1e-6)

            # 准确率高 → 权重增大；准确率低 → 权重减小
            # 基础权重 0.20，按准确率偏离 0.5 的程度调整
            base = 0.20
            adjustment = (ewma_acc - 0.5) * 0.40  # -0.20 ~ +0.20
            new_w = base + adjustment
            new_w = max(p.risk_attention_min_weight, min(p.risk_attention_max_weight, new_w))
            new_weights[name] = new_w

        self._risk_dynamic_weights = new_weights

    def _get_risk_weights(self) -> Dict[str, float]:
        """获取当前风险注意力权重。"""
        if not self.params.risk_attention_enabled:
            return {
                "bcrm2": self.params.risk_weight_bcrm2,
                "force": self.params.risk_weight_force,
                "a0": self.params.risk_weight_a0,
                "ising": self.params.risk_weight_ising,
                "tda": self.params.risk_weight_tda,
            }
        return self._risk_dynamic_weights.copy()

    def _get_effective_weights(self) -> Dict[str, float]:
        """兼容旧接口：返回风险注意力权重。"""
        return self._get_risk_weights()

    def get_attention_stats(self) -> Dict[str, dict]:
        """获取各源风险注意力统计。"""
        stats = {}
        for name in self.SOURCE_NAMES:
            history = self._risk_warning_history[name]
            acc = sum(history) / len(history) if len(history) > 0 else 0.0
            stats[name] = {
                "samples": len(history),
                "accuracy": round(acc, 4),
                "current_weight": round(self._risk_dynamic_weights[name], 4),
            }
        return stats

    # ================================================================
    # 力学引擎执行
    # ================================================================
    def _run_force_engine(self, snapshot: Dict, df=None):
        """运行力学引擎，返回 (方向, 反转预警, 趋势强度, 结果字典)"""
        if self._force_engine is None:
            return 0, False, 0.0, None

        try:
            # 从 df 补充快照数据
            if df is not None and len(df) >= 50:
                snapshot = self._enrich_snapshot(snapshot, df)

            force_result = self._force_engine.infer(snapshot)

            direction = 0
            if force_result.direction == "UP":
                direction = 1
            elif force_result.direction == "DOWN":
                direction = -1

            return (
                direction,
                force_result.reversal_warning,
                force_result.trend_strength,
                force_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[四角校验] 力学引擎执行失败: {e}")
            return 0, False, 0.0, None

    # ================================================================
    # Ising相变检测执行（P1新增）
    # ================================================================
    def _run_ising_detector(self, snapshot: Dict, df=None):
        """
        运行Ising相变检测。

        Returns:
            (方向, 相变预警, 相态, 结果字典)
            方向: -1=空, 0=中性, +1=多
            相变预警: bool（能量突变 或 临界相）
            相态: "ORDERED"/"DISORDERED"/"CRITICAL"/"UNKNOWN"
        """
        if self._ising_detector is None:
            return 0, False, "UNKNOWN", None

        try:
            # 从df提取收益率序列
            returns = None
            volatility = float(snapshot.get("volatility", 0.03))

            if df is not None and len(df) >= 20:
                import numpy as np
                closes = df["close"].values.astype(float)
                if len(closes) >= 2:
                    returns = np.diff(np.log(closes[-100:]))  # 最近100根K线收益
                    returns = returns[~np.isnan(returns)]
                    # 更新波动率
                    if len(returns) > 1:
                        volatility = float(np.std(returns[-20:])) if len(returns) >= 20 else float(np.std(returns))

            if returns is None or len(returns) < 5:
                return 0, False, "UNKNOWN", None

            ising_result = self._ising_detector.detect(returns, volatility)

            # 方向转换
            direction = 0
            if ising_result.direction == "UP":
                direction = 1
            elif ising_result.direction == "DOWN":
                direction = -1

            # 相变预警：能量突变 或 临界相
            alert = ising_result.phase_transition_alert or ising_result.phase == "CRITICAL"

            return (
                direction,
                alert,
                ising_result.phase,
                ising_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[五角校验] Ising相变检测失败: {e}")
            return 0, False, "UNKNOWN", None

    # ================================================================
    # TDA拓扑检测执行（P2新增）
    # ================================================================
    def _run_tda_detector(self, snapshot: Dict, df=None):
        """
        运行TDA拓扑检测。

        Returns:
            (方向, 拓扑预警, 预警强度, 结果字典)
            方向: -1=空, 0=中性, +1=多
            拓扑预警: bool（Betti突增 或 瓶颈距离突增）
            预警强度: [0, 1]
        """
        if self._tda_detector is None:
            return 0, False, 0.0, None

        try:
            # 从df提取价格序列
            price_series = None
            if df is not None and len(df) >= 30:
                closes = df["close"].values.astype(float)
                price_series = closes[-100:] if len(closes) >= 100 else closes

            if price_series is None or len(price_series) < 25:
                return 0, False, 0.0, None

            tda_result = self._tda_detector.detect(price_series)

            # 数据不足时跳过
            if not tda_result.has_sufficient_data:
                return 0, False, 0.0, tda_result.to_dict()

            # 方向转换
            direction = 0
            if tda_result.direction == "UP":
                direction = 1
            elif tda_result.direction == "DOWN":
                direction = -1

            return (
                direction,
                tda_result.early_warning,
                tda_result.warning_strength,
                tda_result.to_dict(),
            )
        except Exception as e:
            logger.warning(f"[五角校验] TDA拓扑检测失败: {e}")
            return 0, False, 0.0, None

    def _enrich_snapshot(self, snapshot: Dict, df) -> Dict:
        """从 K线数据补充力学引擎需要的快照字段"""
        import numpy as np
        closes = df["close"].values.astype(float)
        volumes = df["volume"].values.astype(float) if "volume" in df else np.ones(len(closes))

        if len(closes) < 50:
            return snapshot

        # 技术评分
        ma_short = np.mean(closes[-5:])
        ma_mid = np.mean(closes[-20:])
        ma_long = np.mean(closes[-50:])
        tech_score = 0.5 + (ma_short - ma_mid) / max(abs(ma_mid), 1) * 5
        tech_score = max(0, min(1, tech_score))

        # 价格位置
        recent_high = np.max(closes[-50:])
        recent_low = np.min(closes[-50:])
        price_position = (closes[-1] - recent_low) / max(recent_high - recent_low, 1e-8)

        # RSI
        deltas = np.diff(closes[-15:])
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        avg_gain = np.mean(gains) if len(gains) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0
        rsi = 100 - 100 / (1 + (avg_gain / max(avg_loss, 1e-8))) if avg_loss > 0 else 100

        # 波动率
        returns = np.diff(np.log(closes[-20:]))
        volatility = float(np.std(returns)) if len(returns) > 1 else 0.02

        # 均线方向
        ma_direction = 0
        if len(closes) >= 5:
            ma_direction = (np.mean(closes[-5:]) - np.mean(closes[-10:])) / max(abs(np.mean(closes[-10:])), 1)

        # 量比
        vol_ratio = 1.0
        if len(volumes) >= 20:
            vol_ratio = volumes[-1] / max(np.mean(volumes[-20:]), 1e-8)

        # 补充快照
        enriched = snapshot.copy()
        enriched.setdefault("technical_score", tech_score)
        enriched.setdefault("price_position", price_position)
        enriched.setdefault("rsi", rsi)
        enriched.setdefault("volatility", volatility)
        enriched.setdefault("ma_direction", ma_direction)
        enriched.setdefault("macd_signal", ma_direction * 0.8)
        enriched.setdefault("volume_ratio", vol_ratio)

        # 内驱力维度（如果没有）
        enriched.setdefault("supply_demand_score", 0.5 + (vol_ratio - 1) * 0.1)
        enriched.setdefault("capital_flow_score", 0.5 + ma_direction * 2)
        enriched.setdefault("sentiment_score", 0.5 + (rsi - 50) / 100)

        # 周期位置（如果没有）
        enriched.setdefault("long_cycle_position", 0.5 + (closes[-1] - ma_long) / max(abs(ma_long), 1) * 3)
        enriched.setdefault("mid_cycle_position", price_position)
        enriched.setdefault("short_cycle_position", 0.5 + (ma_short - ma_mid) / max(abs(ma_mid), 1) * 3)
        enriched.setdefault("trend_strength", abs(ma_direction) * 10)

        return enriched

    # ================================================================
    # 校验模式判定
    # ================================================================
    def _determine_verdict(self, directions: List[int], agreement: float) -> str:
        """判定校验模式"""
        non_zero = [d for d in directions if d != 0]

        if len(non_zero) <= 1:
            return "INSUFFICIENT_SOURCES"

        if agreement >= 1.0:
            return "STRONG_AGREE"
        elif agreement >= 0.67:
            return "MAJORITY_AGREE"
        elif agreement >= 0.5:
            return "DIVERGENT"
        else:
            return "CONFLICT"

    @staticmethod
    def _dir_str_to_int(direction: str) -> int:
        if direction == "UP":
            return 1
        elif direction == "DOWN":
            return -1
        return 0
