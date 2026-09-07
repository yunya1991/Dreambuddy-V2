"""战略映射器 —— 力向量综合结果 → war_state / cap / style_mask 映射。

对应 Spec §四 strategic_mapper。
FAIL-OPEN: 异常时返回保守默认（FREEZE, cap=0.1, 仅 emergency）。
"""
from __future__ import annotations

import os as _os
import sys as _sys
from dataclasses import replace

# ============================================================
# 注入「9-基本面分析」到 sys.path（与 force_vector_calculator 保持一致）
# ============================================================
try:  # noqa: E402
    _HERE = _os.path.dirname(_os.path.abspath(__file__))          # force_vector
    _SCRIPTS = _os.path.dirname(_HERE)                            # scripts
    _YIJING = _os.path.dirname(_SCRIPTS)                          # 11-易经推理系统
    _ROOT = _os.path.dirname(_YIJING)                             # dreambuddy-v2
    _9_FUND_PATH = _os.path.join(_ROOT, "9-基本面分析")
    if _os.path.isdir(_9_FUND_PATH) and _9_FUND_PATH not in _sys.path:
        _sys.path.insert(0, _9_FUND_PATH)
except Exception:
    pass

from force_vector.models import (  # noqa: E402
    ContradictionTransform,
    StrategicLayerOutput,
)


# 样式键集合（固定，保证下游 mask 字段一致）
_STYLE_KEYS = ("trend_follow", "breakout", "momentum", "mean_revert", "emergency")

# magnitude 归一化参考：达到该强度即取 cap 区间上限
_MAG_REF = 1.0


def _mask(trend_follow: bool, breakout: bool, momentum: bool,
          mean_revert: bool, emergency: bool) -> dict:
    """构造 style_mask 字典，保证键集合固定。"""
    return {
        "trend_follow": trend_follow,
        "breakout": breakout,
        "momentum": momentum,
        "mean_revert": mean_revert,
        "emergency": emergency,
    }


# 仅 emergency 的保守 mask（FAIL-OPEN 与 divergence 共用）
_EMERGENCY_ONLY = _mask(False, False, False, False, True)


class StrategicMapper:
    """将力向量综合结果映射到战略层 war_state / cap / style_mask。

    映射规则（详见模块 docstring 与 Spec §四）：
      - war_state: final_score + resonance_state → ALLOW/COOLDOWN/FREEZE（保守优先）
      - cap: 按 resonance_state 分档，magnitude 决定区间内位置
      - style_mask: 按 resonance_state + 方向 开放策略白名单
      - 矛盾转化: transforming=True 时按 transform_type 调整 cap/mask/war_state
      - enable_force_vector=False → force_vectors=None（字节等价）
    """

    def map(self, final_direction: float, final_magnitude: float,
            resonance_state: str,
            contradiction: ContradictionTransform = None,
            force_vectors: dict = None,
            five_scores: dict = None,
            enable_force_vector: bool = False) -> StrategicLayerOutput:
        """映射到 war_state/cap/mask + force_vectors。"""
        try:
            return self._map_impl(
                final_direction, final_magnitude, resonance_state,
                contradiction, force_vectors, five_scores, enable_force_vector,
            )
        except Exception:
            # FAIL-OPEN: 任何异常 → 保守默认
            return self._conservative_default(
                final_direction, final_magnitude, resonance_state,
                contradiction, five_scores,
            )

    # ============================================================
    # 内部实现
    # ============================================================
    def _map_impl(self, final_direction, final_magnitude, resonance_state,
                  contradiction, force_vectors, five_scores, enable_force_vector):
        # final_score: [-1,+1] → [0,100]
        final_score = (final_direction + 1) / 2 * 100

        # 基准 war_state / cap / mask
        war_state = self._war_state(final_score, resonance_state)
        cap, mask = self._base_cap_and_mask(
            final_direction, final_magnitude, resonance_state)
        position_mult = 1.0

        # 力向量透传（enable_force_vector=False → None，字节等价保证）
        out_force_vectors = self._resolve_force_vectors(
            force_vectors, enable_force_vector)

        # 矛盾转化调整（transforming=True 时生效）
        if contradiction is not None and contradiction.transforming:
            cap, mask, war_state, position_mult, out_force_vectors = \
                self._apply_contradiction(
                    contradiction, cap, mask, war_state, position_mult,
                    out_force_vectors)

        # 监控点透传
        monitoring_points = (
            list(contradiction.monitoring_points)
            if contradiction is not None else []
        )

        return StrategicLayerOutput(
            war_state=war_state,
            aggregate_position_cap_pct=cap,
            allowed_style_mask=mask,
            position_mult=position_mult,
            five_scores=dict(five_scores) if five_scores else {},
            force_vectors=out_force_vectors,
            pca_result=None,
            cycle_comparison=None,
            final_direction=final_direction,
            final_magnitude=final_magnitude,
            resonance_state=resonance_state,
            elasticity_beta=None,
            contradiction_transform=contradiction,
            primary_contradiction="",
            monitoring_points=monitoring_points,
        )

    # ------------------------------------------------------------
    # war_state 映射（优先级 FREEZE > COOLDOWN > ALLOW，保守优先）
    # ------------------------------------------------------------
    @staticmethod
    def _war_state(final_score: float, resonance_state: str) -> str:
        # FREEZE: 分数过低 或 共振发散/观察
        if final_score < 50 or resonance_state in ("divergence", "observation"):
            return "FREEZE"
        # COOLDOWN: 中段 或 共振萌发/转折
        if final_score < 65 or resonance_state in ("emerging", "turning"):
            return "COOLDOWN"
        # ALLOW: 高分 且 共振/持续
        if final_score >= 65 and resonance_state in ("resonance", "persistent"):
            return "ALLOW"
        # 兜底保守
        return "COOLDOWN"

    # ------------------------------------------------------------
    # 基准 cap + style_mask 映射
    # ------------------------------------------------------------
    @staticmethod
    def _base_cap_and_mask(final_direction, final_magnitude, resonance_state):
        # magnitude 归一化到 [0,1]，决定 cap 在区间内的位置
        frac = min(1.0, max(0.0, final_magnitude / _MAG_REF))
        if final_direction > 0 and resonance_state == "resonance":
            # resonance + 方向>0 → 0.50~1.00，trend_follow/breakout/momentum 全开
            cap = 0.50 + 0.50 * frac
            mask = _mask(True, True, True, False, True)
        elif final_direction > 0 and resonance_state == "persistent":
            # persistent + 方向>0 → 0.30~0.80，mean_revert/momentum 开
            cap = 0.30 + 0.50 * frac
            mask = _mask(False, False, True, True, True)
        elif resonance_state in ("emerging", "turning"):
            # emerging/turning → 0.20~0.50，仅 mean_revert/emergency
            cap = 0.20 + 0.30 * frac
            mask = _mask(False, False, False, True, True)
        elif resonance_state in ("divergence", "observation"):
            # divergence/observation → 0.10~0.20，仅 emergency
            cap = 0.10 + 0.10 * frac
            mask = _mask(False, False, False, False, True)
        else:
            # 方向非正向的 resonance/persistent 或未知状态 → 保守（仅 emergency）
            cap = 0.10 + 0.10 * frac
            mask = _mask(False, False, False, False, True)
        return cap, mask

    # ------------------------------------------------------------
    # 力向量透传
    # ------------------------------------------------------------
    @staticmethod
    def _resolve_force_vectors(force_vectors, enable_force_vector):
        # enable_force_vector=False → None（字节等价保证）
        if not enable_force_vector:
            return None
        if force_vectors is None:
            return None
        # 浅拷贝字典，避免后续调整污染调用方
        return dict(force_vectors)

    # ------------------------------------------------------------
    # 矛盾转化调整
    # ------------------------------------------------------------
    def _apply_contradiction(self, contradiction, cap, mask, war_state,
                             position_mult, out_force_vectors):
        ttype = contradiction.transform_type
        if ttype == "elasticity_decay":
            # cap ×0.5, 禁 trend_follow/breakout, war_state=COOLDOWN
            cap *= 0.5
            mask["trend_follow"] = False
            mask["breakout"] = False
            war_state = "COOLDOWN"
        elif ttype == "elasticity_amplification":
            # cap 不变, position_mult ×1.2, 开 mean_revert/emergency
            position_mult *= 1.2
            mask["mean_revert"] = True
            mask["emergency"] = True
        elif ttype == "dominant_shift":
            # cap ×0.7, 仅 mean_revert/emergency, COOLDOWN
            cap *= 0.7
            mask = _mask(False, False, False, True, True)
            war_state = "COOLDOWN"
        elif ttype == "resonance_break":
            # cap ×0.6, 仅 emergency, FREEZE
            cap *= 0.6
            mask = _mask(False, False, False, False, True)
            war_state = "FREEZE"
        elif ttype == "cbr_divergence":
            # cap ×0.8, 维持当前 mask / war_state
            cap *= 0.8
        elif ttype == "data_quality_warning":
            # cap / mask / war_state 维持；force_vectors confidence ×0.7
            out_force_vectors = self._scale_confidence(out_force_vectors, 0.7)
        # transform_type == "none" 或未知 → 不调整
        return cap, mask, war_state, position_mult, out_force_vectors

    @staticmethod
    def _scale_confidence(force_vectors, factor):
        """对 force_vectors 中每个 ForceVector 的 confidence 乘以 factor。

        使用 dataclasses.replace 创建新对象，不修改原始输入。
        """
        if not force_vectors:
            return force_vectors
        scaled = {}
        for dim, fv in force_vectors.items():
            scaled[dim] = replace(fv, confidence=fv.confidence * factor)
        return scaled

    # ------------------------------------------------------------
    # FAIL-OPEN 保守默认
    # ------------------------------------------------------------
    @staticmethod
    def _conservative_default(final_direction, final_magnitude, resonance_state,
                              contradiction, five_scores):
        """异常兜底：FREEZE, cap=0.1, 仅 emergency。"""
        return StrategicLayerOutput(
            war_state="FREEZE",
            aggregate_position_cap_pct=0.1,
            allowed_style_mask=dict(_EMERGENCY_ONLY),
            position_mult=1.0,
            five_scores=dict(five_scores) if five_scores else {},
            force_vectors=None,
            pca_result=None,
            cycle_comparison=None,
            final_direction=final_direction,
            final_magnitude=final_magnitude,
            resonance_state=resonance_state,
            elasticity_beta=None,
            contradiction_transform=contradiction,
            primary_contradiction="",
            monitoring_points=list(contradiction.monitoring_points)
            if contradiction is not None else [],
        )
