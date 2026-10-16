# -*- coding: utf-8 -*-
"""SPEC-v1.4 S-1: S 层充分性评估器 — C-Drive 充分性驱动的动态裁剪/提前终止。

依据: SPEC-v1.4-S-layer-design.md §3.1/§3.2。

充分性状态:
  入口（S0）: SUFFICIENT_DIRECT / NEED_PLAN / NEED_CLARIFY / NEED_RESEARCH
  规划（S2）: SUFFICIENT / NEED_DEEPER / NEED_CLARIFY / EARLY_TERMINATE

阈值硬约束（跨系统唯一，禁止第二套数值）:
  只引用 route_confidence.THRESHOLD_HIGH (0.7) / CASE_DENSITY_MIN (3)，
  不确定区间 [CLARIFY_MATCH_MIN, THRESHOLD_HIGH) 由其派生。

规则（入口）:
  - 认知不可用 / recall 空        → NEED_PLAN（FAIL-OPEN 兜底）
  - light 深度 + match≥0.7 + 密度≥3 → SUFFICIENT_DIRECT（跳过规划直接答）
  - match<0.4 且 density<3        → NEED_RESEARCH（双低，触发调研打桩）
  - 0.4≤match<0.7 且 density<3    → NEED_CLARIFY（不确定区间，问用户）
  - 其余                          → NEED_PLAN

规则（规划后）:
  - 展开为空 + 已 deep → EARLY_TERMINATE（不值得做，礼貌退出）
  - 展开为空 + 非 deep → NEED_DEEPER（继续展开）
  - 不确定区间          → NEED_CLARIFY
  - 其余                → SUFFICIENT
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.cognitive_router import evaluate_match
from core.jev_gate import FAST_PATH_DENSITY, jev_gate
from core.route_confidence import (
    CASE_DENSITY_MIN,
    THRESHOLD_HIGH,
    compute_route_confidence,
)

# ============================================================
# 充分性状态常量
# ============================================================

# 入口（S0）四态
SUFFICIENT_DIRECT = "SUFFICIENT_DIRECT"
NEED_PLAN = "NEED_PLAN"
NEED_RESEARCH = "NEED_RESEARCH"

# 规划（S2）四态
SUFFICIENT = "SUFFICIENT"
NEED_DEEPER = "NEED_DEEPER"

# 共享态
NEED_CLARIFY = "NEED_CLARIFY"
EARLY_TERMINATE = "EARLY_TERMINATE"

# 不确定区间下限（由 THRESHOLD_HIGH 派生，非新阈值体系）
CLARIFY_MATCH_MIN = 0.4

# reasons 标记
R_COGNITIVE_UNAVAILABLE = "cognitive_unavailable"
R_RECALL_EMPTY = "recall_empty"
R_LIGHT_FAST_PATH = "light_depth_fast_path"
R_DOUBLE_LOW = "double_low_signals"
R_UNCERTAINTY_BAND = "uncertainty_band"
R_SIGNAL_CONTRADICTION = "signal_contradiction"
R_JEV_OVERRIDE = "jev_override_to_clarify"
R_PLAN_EMPTY = "plan_empty"
R_DEPTH_MAXED = "depth_maxed"


@dataclass
class SufficiencyResult:
    """充分性评估结果（可 to_dict 序列化透传）。"""

    state: str
    match_score: float
    case_density: int
    route_confidence: float
    depth: Optional[str]
    reasons: List[str] = field(default_factory=list)
    jev_decision: Optional[str] = None  # jev 终裁结果；空计划态绕过为 None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _signals(memories: Optional[List[Any]], cognitive_available: bool):
    """提取 match/density/route_confidence 信号（复用 C3 实现与既有公式）。"""
    if not cognitive_available:
        return 0.0, 0, 0.0
    if not memories:
        return 0.0, 0, 0.0
    match_score, case_density = evaluate_match(memories)
    route_confidence, _ = compute_route_confidence(
        match_score, case_density, None, c4_available=False)
    return match_score, case_density, route_confidence


def _in_uncertainty_band(match_score: float, case_density: int) -> bool:
    return (CLARIFY_MATCH_MIN <= match_score < THRESHOLD_HIGH
            and case_density < CASE_DENSITY_MIN)


def _signal_contradiction(match_score: float, case_density: int) -> bool:
    """信号矛盾：高匹配低密度 或 低匹配高密度（密度侧复用 jev FAST_PATH_DENSITY）。"""
    return ((match_score >= THRESHOLD_HIGH and case_density < CASE_DENSITY_MIN)
            or (match_score < CLARIFY_MATCH_MIN
                and case_density >= FAST_PATH_DENSITY))


def _jev_final(
    match_score: float,
    case_density: int,
    anti_oscillation=None,
) -> str:
    """默认分支 jev 终裁。

    rea_confidence=match_score 使 actual==expected（预测误差=0），
    中和预测误差规则（S 层无外部 actual），仅保留 believability/HOT 规则。
    anti_oscillation 传入时经 JevAntiOscillation 三重防振荡。
    """
    raw = "CONTINUE"
    decision = jev_gate(raw, match_score, case_density,
                        rea_confidence=match_score, debate_result=None)
    if anti_oscillation is not None:
        decision = anti_oscillation.check_oscillation(raw, decision)
    return decision


def evaluate_entry_sufficiency(
    memories: Optional[List[Any]],
    *,
    depth: Optional[str] = None,
    cognitive_available: bool = True,
    anti_oscillation=None,
) -> SufficiencyResult:
    """S0 入口充分性评估（规划前）。"""
    if not cognitive_available:
        return SufficiencyResult(NEED_PLAN, 0.0, 0, 0.0, depth,
                                 [R_COGNITIVE_UNAVAILABLE])
    if not memories:
        return SufficiencyResult(NEED_PLAN, 0.0, 0, 0.0, depth, [R_RECALL_EMPTY])

    match_score, case_density, route_confidence = _signals(memories, True)

    if (depth == "light" and match_score >= THRESHOLD_HIGH
            and case_density >= CASE_DENSITY_MIN):
        return SufficiencyResult(SUFFICIENT_DIRECT, match_score, case_density,
                                 route_confidence, depth, [R_LIGHT_FAST_PATH])

    if match_score < CLARIFY_MATCH_MIN and case_density < CASE_DENSITY_MIN:
        return SufficiencyResult(NEED_RESEARCH, match_score, case_density,
                                 route_confidence, depth, [R_DOUBLE_LOW])

    if _signal_contradiction(match_score, case_density):
        return SufficiencyResult(NEED_CLARIFY, match_score, case_density,
                                 route_confidence, depth,
                                 [R_SIGNAL_CONTRADICTION])

    if _in_uncertainty_band(match_score, case_density):
        return SufficiencyResult(NEED_CLARIFY, match_score, case_density,
                                 route_confidence, depth, [R_UNCERTAINTY_BAND])

    jev_decision = _jev_final(match_score, case_density, anti_oscillation)
    if jev_decision != "CONTINUE":
        return SufficiencyResult(NEED_CLARIFY, match_score, case_density,
                                 route_confidence, depth, [R_JEV_OVERRIDE],
                                 jev_decision)

    return SufficiencyResult(NEED_PLAN, match_score, case_density,
                             route_confidence, depth, [], jev_decision)


def evaluate_plan_sufficiency(
    plan: Optional[Dict[str, Any]],
    memories: Optional[List[Any]],
    *,
    depth: Optional[str] = None,
    anti_oscillation=None,
) -> SufficiencyResult:
    """S2 规划充分性再评估（展开后）。空计划态绕过 jev（jev_decision=None）。"""
    match_score, case_density, route_confidence = _signals(memories, True)

    plan_items = (plan or {}).get("plan_items") or []
    if not plan_items:
        if depth == "deep":
            return SufficiencyResult(EARLY_TERMINATE, match_score, case_density,
                                     route_confidence, depth,
                                     [R_PLAN_EMPTY, R_DEPTH_MAXED])
        return SufficiencyResult(NEED_DEEPER, match_score, case_density,
                                 route_confidence, depth, [R_PLAN_EMPTY])

    if memories and _in_uncertainty_band(match_score, case_density):
        return SufficiencyResult(NEED_CLARIFY, match_score, case_density,
                                 route_confidence, depth, [R_UNCERTAINTY_BAND])

    jev_decision = None
    # 双低信号已由入口 NEED_RESEARCH 处置，规划阶段不再经 jev（避免 believability 重复改写）
    double_low = (match_score < CLARIFY_MATCH_MIN
                  and case_density < CASE_DENSITY_MIN)
    if memories and not double_low:
        jev_decision = _jev_final(match_score, case_density, anti_oscillation)
        if jev_decision != "CONTINUE":
            return SufficiencyResult(NEED_CLARIFY, match_score, case_density,
                                     route_confidence, depth, [R_JEV_OVERRIDE],
                                     jev_decision)

    return SufficiencyResult(SUFFICIENT, match_score, case_density,
                             route_confidence, depth, [], jev_decision)
