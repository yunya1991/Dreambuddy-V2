"""CrossValidationGate — §5.1 五步交叉验证算法（过去 + 现在 → 未来）.

设计依据：融合方案 §5.1 + §10.4 + §10.11.7
核心流程：
  Step 1-2: 外部输入 G_dim（过去）+ A_dim（现在）
  Step 3:   交叉比对 → 一致(boost 1.15) / 分歧(penalty 0.9 + divergence_count++)
  Step 4:   质变判定 → divergence_count >= persistence AND break_score >= threshold
  Step 5:   head_multipliers 动态调整（仅分歧期间，质变前）

整合 §10.11 五大优化（通过开关控制，默认仅 Q4 降级 + Q5 加权启用）：
  Q1: persistence_threshold Bayesian 校准（默认关闭，使用先验值）
  Q2: head_multipliers floor/ceiling/mean reversion（mean reversion 默认关闭）
  Q3: Granger 重估冷却期（默认启用）
  Q4: 双 None 三级降级模式（默认启用）
  Q5: structural_break 类型加权共识（默认启用）
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np

from dreambuddy_evolution.core.attention_aggregator import C_DIM_TO_3, get_factor_dimensions
from dreambuddy_evolution.core.sprt_monitor import SPRTMonitor

# Q5 结构断裂类型权重（融合方案 §10.11.5）
STRUCTURAL_BREAK_WEIGHTS: dict[str, float] = {
    "market_form_shift": 1.0,       # Hurst 指数，最具结构性
    "correlation_break": 0.6,       # Welch's t-test，中等
    "volatility_regime_shift": 0.4, # Markov-Regression/HMM，较低（易受事件冲击）
}


class CrossValidationGate:
    """交叉验证门 — 实现 §5.1 五步算法."""

    def __init__(
        self,
        persistence_threshold: int = 5,
        confidence_boost: float = 1.15,
        confidence_penalty: float = 0.9,
        head_boost_rate: float = 0.3,
        head_decay_rate: float = 0.2,
        head_floor: float = 0.1,
        head_ceiling: float = 2.0,
        head_reversion_rate: float = 0.15,
        time_cooldown_hours: float = 24.0,
        sample_cooldown_multiplier: float = 2.0,
        structural_break_threshold: float = 0.4,
        enable_degraded_mode: bool = True,
        enable_head_multipliers_mean_reversion: bool = False,
        enable_structural_break_weighting: bool = True,
        dimensions: Optional[list[str]] = None,
    ) -> None:
        if dimensions is None:
            # enable_attention_aggregator 开关控制：关闭时降级为固定3维度映射
            try:
                from dreambuddy_evolution.agi_config import get_switch as _gs_aa
                if _gs_aa("enable_attention_aggregator", True):
                    dimensions = get_factor_dimensions()
                else:
                    dimensions = ["C1", "C2", "C4"]  # 降级：固定3维度
            except Exception:
                dimensions = get_factor_dimensions()  # FAIL-OPEN
        self._dimensions = dimensions

        # 五步算法参数
        self._persistence_threshold = persistence_threshold
        self._confidence_boost = confidence_boost
        self._confidence_penalty = confidence_penalty
        self._head_boost_rate = head_boost_rate
        self._head_decay_rate = head_decay_rate

        # Q2 head 收敛性保护
        self._head_floor = head_floor
        self._head_ceiling = head_ceiling
        self._head_reversion_rate = head_reversion_rate
        self._enable_head_multipliers_mean_reversion = enable_head_multipliers_mean_reversion
        self._enable_structural_break_weighting = enable_structural_break_weighting
        self._head_multipliers: dict[int, float] = {}

        # Q3 冷却期
        self._time_cooldown_hours = time_cooldown_hours
        self._sample_cooldown_multiplier = sample_cooldown_multiplier
        self._last_reestimate_time: float = 0.0
        # 初始化为满足样本冷却的值（系统启动时假设已有足够历史样本），
        # 重估后重置为 0，需重新积累
        self._sample_count_since_last_reestimate: int = int(
            sample_cooldown_multiplier * persistence_threshold
        )
        self._pending_reestimate: Optional[str] = None

        # Q5 共识阈值
        self._structural_break_threshold = structural_break_threshold

        # Q4 降级模式
        self._enable_degraded_mode = enable_degraded_mode
        # Q4a: SPRT 单链路一致性监测
        self._sprt = SPRTMonitor(p0=0.75, p1=0.50, alpha=0.05, beta=0.10)
        self._baseline_dim: Optional[str] = None  # 最近一次双链路一致时的主矛盾维度

        # 状态
        self._divergence_count: int = 0

    # ── 维度 → head 索引映射 ──────────────────────────────────────

    def dim_to_heads(self, dim: str) -> list[int]:
        """返回 3 维度对应的所有 head 索引列表."""
        return [i for i, c in enumerate(self._dimensions) if C_DIM_TO_3.get(c) == dim]

    def head_adjustment_to_array(
        self, head_adjustment: dict[int, float], n_heads: Optional[int] = None
    ) -> np.ndarray:
        """将 head_adjustment dict 转换为 (n_heads,) ndarray.

        未在 dict 中的 head 使用默认值 1.0（不衰减）。
        用于传入 NeuralSDE.forecast(head_multipliers=...)。
        """
        if n_heads is None:
            n_heads = len(self._dimensions)
        arr = np.ones(n_heads, dtype=np.float32)
        for h, val in head_adjustment.items():
            if 0 <= h < n_heads:
                arr[h] = val
        return arr

    # ── Q5: 结构性断裂加权得分 ────────────────────────────────────

    def _structural_break_score(self, structural_break: dict) -> float:
        """计算结构性断裂得分.

        Q5 启用时：类型加权共识（Hurst=1.0 / Welch=0.6 / vol=0.4）
        Q5 关闭时：简单 OR（任一断裂 → 1.0）
        """
        if not self._enable_structural_break_weighting:
            # 无加权：任一断裂类型为 True 即视为断裂
            for key in STRUCTURAL_BREAK_WEIGHTS:
                if structural_break.get(key, False):
                    return 1.0
            return 0.0

        score = 0.0
        for key, weight in STRUCTURAL_BREAK_WEIGHTS.items():
            if structural_break.get(key, False):
                score += weight
        return score

    # ── Q3: 冷却检查 ──────────────────────────────────────────────

    def _cooldown_satisfied(self) -> bool:
        """时间冷却 + 样本冷却双约束."""
        now = time.time()
        time_ok = (now - self._last_reestimate_time) >= self._time_cooldown_hours * 3600
        sample_ok = (
            self._sample_count_since_last_reestimate
            >= self._sample_cooldown_multiplier * self._persistence_threshold
        )
        return time_ok and sample_ok

    # ── 核心五步算法 ──────────────────────────────────────────────

    def compare(
        self,
        G_dim: Optional[str],
        G_conf: Optional[float],
        A_dim: Optional[str],
        A_strength: Optional[float],
        structural_break: Optional[dict] = None,
    ) -> dict:
        """执行 §5.1 五步交叉验证.

        Args:
            G_dim: Granger 过去主矛盾维度 ∈ {technical, fundamental, macro, None}
            G_conf: Granger 置信度 [0,1]（当前未使用，预留）
            A_dim: Attention 现在主矛盾维度 ∈ {technical, fundamental, macro, None}
            A_strength: Attention 强度 [0,1]（当前未使用，预留）
            structural_break: StructuralBreakDetector.detect_all() 输出

        Returns:
            {
                "confidence_mult": float,
                "shift_signal": bool,
                "divergence_count": int,
                "quality_change": bool,
                "new_main_dim": Optional[str],
                "head_adjustment": dict[int, float],
                "granger_reestimate_trigger": bool,
                "degraded_mode": Optional[str],
                "structural_break_score": Optional[float],
            }
        """
        if structural_break is None:
            structural_break = {}

        self._sample_count_since_last_reestimate += 1

        # Q4: 三级降级模式 + SPRT 一致性监测
        if G_dim is None and A_dim is None:
            return self._neutral_result(degraded_mode="both_none")
        if G_dim is None:
            if self._enable_degraded_mode:
                return self._degraded_with_sprt("attention_only", A_dim)
            return self._neutral_result()
        if A_dim is None:
            if self._enable_degraded_mode:
                return self._degraded_with_sprt("granger_only", G_dim)
            return self._neutral_result()

        # 双链路可用：更新 baseline + 重置 SPRT
        if G_dim == A_dim:
            self._baseline_dim = G_dim
            self._sprt.reset()

        # Step 3: 交叉比对
        if G_dim == A_dim:
            confidence_mult = self._confidence_boost
            shift_signal = False
            self._divergence_count = 0
            if self._enable_head_multipliers_mean_reversion:
                self._revert_head_multipliers_to_mean()
        else:
            confidence_mult = self._confidence_penalty
            shift_signal = True
            self._divergence_count += 1

        # Step 4: 质变判定（Q5 类型加权共识）
        quality_change = False
        granger_reestimate_trigger = False
        new_main_dim = None
        break_score = None

        if self._divergence_count >= self._persistence_threshold:
            break_score = self._structural_break_score(structural_break)
            if break_score >= self._structural_break_threshold:
                quality_change = True
                if self._cooldown_satisfied():
                    granger_reestimate_trigger = True
                    new_main_dim = A_dim
                    self._divergence_count = 0
                    self._last_reestimate_time = time.time()
                    self._sample_count_since_last_reestimate = 0
                else:
                    self._pending_reestimate = A_dim

        # Step 5: head_multipliers 动态调整（Q2 floor + ceiling）
        head_adjustment: dict[int, float] = {}
        if shift_signal and not quality_change:
            progress = min(1.0, self._divergence_count / self._persistence_threshold)
            for h in self.dim_to_heads(A_dim):
                val = 1.0 + self._head_boost_rate * progress
                head_adjustment[h] = max(self._head_floor, min(self._head_ceiling, val))
            for h in self.dim_to_heads(G_dim):
                val = 1.0 - self._head_decay_rate * progress
                head_adjustment[h] = max(self._head_floor, min(self._head_ceiling, val))

        return {
            "confidence_mult": confidence_mult,
            "shift_signal": shift_signal,
            "divergence_count": self._divergence_count,
            "quality_change": quality_change,
            "new_main_dim": new_main_dim,
            "head_adjustment": head_adjustment,
            "granger_reestimate_trigger": granger_reestimate_trigger,
            "degraded_mode": None,
            "structural_break_score": break_score if quality_change else None,
        }

    # ── Q2: mean reversion ────────────────────────────────────────

    def _revert_head_multipliers_to_mean(self) -> None:
        """一致状态下 head_multipliers 缓慢回归 1.0."""
        for h in list(self._head_multipliers.keys()):
            cur = self._head_multipliers[h]
            self._head_multipliers[h] = cur + (1.0 - cur) * self._head_reversion_rate

    # ── Q4: 降级 & FAIL-OPEN ──────────────────────────────────────

    def _degraded_with_sprt(self, mode: str, primary_dim: str) -> dict:
        """单链路降级 + SPRT 一致性监测.

        若 SPRT 判定一致率 < 50%（accept_h1），切换至完全中性。
        """
        if self._baseline_dim is not None:
            decision = self._sprt.update(is_consistent=(primary_dim == self._baseline_dim))
            if decision == "accept_h1":
                return self._neutral_result(degraded_mode="both_none")
        return self._degraded_result(mode, primary_dim)

    def _degraded_result(self, mode: str, primary_dim: str) -> dict:
        """单链路降级：不调整置信度和 head 权重，仅输出 primary_dim."""
        return {
            "confidence_mult": 1.0,
            "shift_signal": False,
            "divergence_count": self._divergence_count,
            "quality_change": False,
            "new_main_dim": None,
            "head_adjustment": {},
            "granger_reestimate_trigger": False,
            "degraded_mode": mode,
            "primary_dim": primary_dim,
            "structural_break_score": None,
        }

    def _neutral_result(self, degraded_mode: Optional[str] = None) -> dict:
        """FAIL-OPEN 完全中性返回."""
        return {
            "confidence_mult": 1.0,
            "shift_signal": False,
            "divergence_count": self._divergence_count,
            "quality_change": False,
            "new_main_dim": None,
            "head_adjustment": {},
            "granger_reestimate_trigger": False,
            "degraded_mode": degraded_mode,
            "structural_break_score": None,
        }
