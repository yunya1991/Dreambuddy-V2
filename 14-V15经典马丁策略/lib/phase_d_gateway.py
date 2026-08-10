"""
Phase D Gateway — BiLSTM-Attention 爆仓预警 + PatchTST 回撤预测 的三大闸门实现

严格对齐 AI_ENHANCEMENT_ROADMAP.md §4.2 输出空间 & §3.3 边界：
  G-D1 (Skip Open)  : PatchTST 预测回撤 ≤ -32%  或  BiLSTM P_bust ≥ 0.60 → 不开首单
  G-D2 (Trim Addons): BiLSTM P_bust ≥ 0.55 → max_addons_eff = max(1, baseline-1)（丢弃最深档）
  G-D3 (Timing Relax): regime=UNCLEAR  AND  patchtst_drawdown > -10%  AND  P_bust < 0.30
                        → timing_score × ≤1.05 放宽，size_power × ≥0.90 放宽（惩罚减弱）

最高优先级铁律 (§3.3 最后一行):
    **AI 只能否决开仓或微调，永远不能在基线判定 WAIT 时强制开仓**
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# ================================================================
# §3.3 双层 clamp（相对边界 + 绝对铁壳）—— 纯函数独立导出
# ================================================================
def apply_iron_clamp(
    ai_value: float,
    baseline_value: float,
    relative_lower: float,
    relative_upper: float,
    absolute_lo: float,
    absolute_hi: float,
) -> float:
    """§3.3 通用 clamp 公式：先相对边界，再绝对铁壳

    Args:
        ai_value:          模型输出原始建议
        baseline_value:    v15-final 基线决策值 (X_base)
        relative_lower:    下边界倍率，如 0.70 表示最多降到基线 70%
        relative_upper:    上边界倍率，如 1.20 表示最多升到基线 120%
        absolute_lo:       外层铁壳下限（任何情况不能低于此绝对值）
        absolute_hi:       外层铁壳上限（任何情况不能高于此绝对值）

    Returns:
        双层 clamp 后的最终生效值
    """
    if baseline_value == 0:
        # 防除 0：退化为只有绝对铁壳
        lo, hi = absolute_lo, absolute_hi
    else:
        lo = baseline_value * relative_lower
        hi = baseline_value * relative_upper
    step1 = max(lo, min(hi, float(ai_value)))
    step2 = max(float(absolute_lo), min(float(absolute_hi), step1))
    return step2


def clamp_max_addons_delta(ai_delta: int, current_max: int) -> int:
    """§3.3 max_addons 专用 clamp：只允许 {-1, 0}，绝不允许 +1（扩到第 5 档）

    同时 -1 是最小缩档（不能一下缩 2 档）。
    """
    if ai_delta >= 1:
        # 硬拒绝：AI 试图扩档到 5（或更多）→ 完全不生效，保持 current_max 不变
        return current_max
    if ai_delta <= -2:
        # 一下缩 2 档太激进，只允许 -1（按 LOWER=-1 档）
        return max(1, current_max - 1)
    # ai_delta in (-1, 0)
    return max(1, current_max + int(ai_delta))


# ================================================================
# Phase D Gateway 类
# ================================================================
@dataclass
class PhaseDGateway:
    """
    实盘/回测通用闸门。加载失败时 Phase 关闭保证字节等价基线。

    Args:
        enabled:              V15_AI_ENABLED and V15_AI_PHASE_D_ENABLED（默认 False，等价基线）
        bilstm_model_path:    模型权重文件路径；None = 走 mock 或禁用
        patchtst_model_path:  同上
        g_d1_drawdown_threshold:   PatchTST 触发 G-D1 的阈值（默认 -32% = 5 单马丁总跨度）
        g_d1_bust_threshold:       BiLSTM 爆仓概率触发 G-D1 的阈值（默认 0.60）
        g_d2_bust_threshold:       BiLSTM 爆仓概率触发 G-D2 缩档（默认 0.55）
        g_d3_drawdown_threshold:   UNCLEAR 放松所需「浅回撤」阈值（默认 > -10%）
        g_d3_bust_threshold:       UNCLEAR 放松所需「低爆仓风险」阈值（默认 < 0.30）
        g_d3_max_score_relax:      G-D3 最多放松 timing_score 的倍数（默认 ≤1.05）
        g_d3_min_power_shrink:     G-D3 最多放宽 size_power 的比率（默认 ≥0.90，乘到原值上得更小=更宽容）
    """

    enabled: bool = False
    bilstm_model_path: Optional[str] = None
    patchtst_model_path: Optional[str] = None
    g_d1_drawdown_threshold: float = -0.32
    g_d1_bust_threshold: float = 0.60
    g_d2_bust_threshold: float = 0.55
    g_d3_drawdown_threshold: float = -0.10
    g_d3_bust_threshold: float = 0.30
    g_d3_max_score_relax: float = 1.05
    g_d3_min_power_shrink: float = 0.90

    # ---- TDD / 诊断辅助字段（不参与启用逻辑） ----
    last_gate_code: Optional[str] = field(default=None, repr=False)
    _mock_bilstm: Optional[float] = field(default=None, repr=False)  # 仅 _for_testing_use_mock_predictor 用
    _mock_patchtst: Optional[float] = field(default=None, repr=False)

    # ================================================================
    # TDD 工厂：用 mock 预测值（不加载真实模型），便于单测
    # ================================================================
    @classmethod
    def _for_testing_use_mock_predictor(
        cls,
        mock_patchtst_drawdown: float,
        mock_bilstm_p_bust: float,
    ) -> "PhaseDGateway":
        return cls(
            enabled=True,
            _mock_patchtst=float(mock_patchtst_drawdown),
            _mock_bilstm=float(mock_bilstm_p_bust),
        )

    # ================================================================
    # 预测函数：真实加载模型 & 推理；或走 mock（TDD 场景）
    # 此处先以 mock + 随机兜底实现，真实模型权重在训练脚本交付后注入
    # ================================================================
    def _predict_patchtst_drawdown(self, ctx: Dict[str, Any]) -> float:
        """PatchTST: 预测未来 24 根 1H K 线 max drawdown (负值, -1=-100%)"""
        if not self.enabled:
            return -0.0
        # MVP 桥接：外部 heuristic 预估值直接通过 ctx 注入（正数→负数转换）
        if ctx and "p_dd" in ctx:
            _v = float(ctx["p_dd"])
            return -abs(_v) if _v > 0 else _v  # 确保负值（drawdown 约定）
        if self._mock_patchtst is not None:
            return float(self._mock_patchtst)
        # 真实模型加载兜底：权重不存在时返回 0（中性=对基线无影响）
        if self.patchtst_model_path and os.path.isfile(self.patchtst_model_path):
            try:
                return self._run_real_patchtst(ctx)
            except Exception:
                return -0.0
        return -0.0

    def _predict_bilstm_p_bust(self, ctx: Dict[str, Any]) -> float:
        """BiLSTM-Attention: 爆仓概率 P([0,1])"""
        if not self.enabled:
            return 0.0
        # MVP 桥接：外部 heuristic 预估值直接通过 ctx 注入
        if ctx and "p_bust" in ctx:
            return float(ctx["p_bust"])
        if self._mock_bilstm is not None:
            return float(self._mock_bilstm)
        if self.bilstm_model_path and os.path.isfile(self.bilstm_model_path):
            try:
                return self._run_real_bilstm(ctx)
            except Exception:
                return 0.0
        return 0.0

    def _run_real_patchtst(self, ctx: Dict[str, Any]) -> float:  # pragma: no cover - 训练完成后接入
        """Phase D 训练脚本交付权重后替换实现"""
        raise NotImplementedError("PatchTST 实盘推理将在训练完成后注入")

    def _run_real_bilstm(self, ctx: Dict[str, Any]) -> float:  # pragma: no cover - 训练完成后接入
        raise NotImplementedError("BiLSTM-Attention 实盘推理将在训练完成后注入")

    # ================================================================
    # G-D1 · Skip Open（含 §3.3 最高优先级铁律：baseline_wait 必须 Skip）
    # ================================================================
    def should_skip_open(self, ctx: Dict[str, Any]) -> bool:
        """只看 AI 模型本身信号（不含 baseline_wait 覆盖），供测试/诊断使用。"""
        self.last_gate_code = None
        if not self.enabled:
            return False
        p_dd = self._predict_patchtst_drawdown(ctx)
        p_bust = self._predict_bilstm_p_bust(ctx)
        if p_dd <= self.g_d1_drawdown_threshold:
            self.last_gate_code = "G-D1-SKIP-DRAWDOWN"
            return True
        if p_bust >= self.g_d1_bust_threshold:
            self.last_gate_code = "G-D1-SKIP-BUST"
            return True
        return False

    def should_skip_open_with_baseline(self, ctx: Dict[str, Any]) -> Tuple[bool, str]:
        """实盘真正调用版本：结合基线信号，保证最高优先级铁律。

        ctx 必须含键 baseline_can_open (bool) = v15 基线 16 层决策 + DirectionGate 判定的「是否能开」。
        返回 (must_skip, reason)
        """
        baseline_can_open = bool(ctx.get("baseline_can_open", False))

        # ---- 最高优先级铁律：基线不同意开 → 必须 Skip（AI 不得强开） ----
        if not baseline_can_open:
            self.last_gate_code = "G-D1-FORCED-BY-BASELINE-WAIT"
            return True, "baseline_wait: AI 不得违反 §3.3 最高优先级规则强制开仓"

        # 基线同意开的情况下，AI 可以否决
        skip_ai = self.should_skip_open(ctx)
        if skip_ai:
            return True, f"ai_{self.last_gate_code or 'unknown'}"
        return False, "baseline_agrees_and_ai_has_no_objection"

    # ================================================================
    # G-D2 · Trim Addons（缩最深档 addon4）
    # ================================================================
    def compute_effective_max_addons(
        self,
        coin: str,
        pos: Dict[str, Any],
        baseline_max_addons: int,
        addon_budgets: Dict[str, float],
    ) -> Tuple[int, Dict[str, float]]:
        """返回 (effective_max_addons, trimmed_addon_budgets)

        - BiLSTM P_bust ≥ g_d2_bust_threshold 时，max_addons = clamp_max_addons_delta(-1, baseline)
        - 最深档（最高编号 addonN_usd）设为 0
        """
        self.last_gate_code = None
        if not self.enabled:
            return int(baseline_max_addons), dict(addon_budgets)

        _ctx = {"coin": coin, "pos": pos}
        # 透传外部 heuristic 预估（MVP 桥接）
        if isinstance(pos, dict):
            if "p_bust" in pos:
                _ctx["p_bust"] = pos["p_bust"]
            if "p_dd" in pos:
                _ctx["p_dd"] = pos["p_dd"]
        p_bust = self._predict_bilstm_p_bust(_ctx)
        if p_bust >= self.g_d2_bust_threshold:
            eff = clamp_max_addons_delta(-1, int(baseline_max_addons))
            trimmed = dict(addon_budgets)
            # 丢弃最高编号 addon：addon4 > addon3 > ...
            keys_sorted = sorted(
                (k for k in trimmed if k.startswith("addon") and k.endswith("_usd")),
                key=lambda k: int("".join(ch for ch in k if ch.isdigit()) or "0"),
                reverse=True,
            )
            # 多退少补：从高编号开始按 (baseline - eff) 个清零
            to_remove = max(0, int(baseline_max_addons) - eff)
            for k in keys_sorted[:to_remove]:
                trimmed[k] = 0.0
            self.last_gate_code = f"G-D2-TRIM-ADDON{4 if to_remove and 4<=baseline_max_addons else baseline_max_addons}"
            return eff, trimmed

        return int(baseline_max_addons), dict(addon_budgets)

    # ================================================================
    # G-D3 · Timing Relaxation（UNCLERA 浅回撤 低爆仓风险 才放行）
    # ================================================================
    def apply_timing_relaxation(
        self,
        symbol: str,
        timing_score: float,
        size_power: float,
        regime: str,
        ctx: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, float]:
        """返回 (adjusted_timing_score, adjusted_size_power)

        若不满足 UNCLEAR + 浅回撤 + 低爆仓，严格原值返回。
        ctx 可携带外部 heuristic 预估（p_bust / p_dd），用于 MVP 桥接。
        """
        self.last_gate_code = None
        orig_score, orig_power = float(timing_score), float(size_power)

        if not self.enabled:
            return orig_score, orig_power
        if str(regime).upper() != "UNCLEAR":
            return orig_score, orig_power

        _ctx = {"symbol": symbol, "regime": regime}
        if ctx:
            _ctx.update(ctx)
        p_dd = self._predict_patchtst_drawdown(_ctx)
        p_bust = self._predict_bilstm_p_bust(_ctx)

        if not (p_dd > self.g_d3_drawdown_threshold and p_bust < self.g_d3_bust_threshold):
            return orig_score, orig_power

        # ---- 满足 G-D3 条件：按 §3.3 边界内做轻微放松 ----
        relax_score_mul = self.g_d3_max_score_relax  # 1.05 default
        shrink_power_mul = self.g_d3_min_power_shrink  # 0.90 default

        new_score = apply_iron_clamp(
            ai_value=orig_score * relax_score_mul,
            baseline_value=orig_score,
            relative_lower=1.0,  # G-D3 只放松，不收紧（LOWER 1.0 保证不会比基线更小）
            relative_upper=relax_score_mul,
            absolute_lo=0.0,
            absolute_hi=1.0,  # timing_score 绝对 ∈[0,1]
        )
        # size_power: LOWER=0.60 来自 §3.3 表第 2 行；这里我们只往 0.9 倍的最小方向挪
        new_power = apply_iron_clamp(
            ai_value=orig_power * shrink_power_mul,
            baseline_value=orig_power,
            relative_lower=0.60,
            relative_upper=1.0,  # G-D3 只放宽（往更小 size_power），不收紧
            absolute_lo=1.00,   # §3.3 外层铁壳 [1.00, 4.00]
            absolute_hi=4.00,
        )
        self.last_gate_code = "G-D3-RELAX-UNCLEAR"
        return new_score, new_power
