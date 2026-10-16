# -*- coding: utf-8 -*-
"""P2: L1 路由置信度门控信号 — C3 匹配度 + C4 预测误差 → route_confidence。

依据: `PLAN-L0L1L2-implementation.md` P2 + SSoT v4.0 §16.5 / CDrive SPEC §7.7。

阈值跨系统唯一（禁止第二套），直接引用 C3/C4 已落地常量:
  THRESHOLD_HIGH       = 0.7   （L1 直答门限）
  CASE_DENSITY_MIN     = 3     （= cognitive_router.TIER1_DENSITY_THRESHOLD）
  PREDICTION_ERROR_MAX = 0.3   （= jev_gate.PREDICTION_ERROR_THRESHOLD）
  FAST_PATH            = match≥0.8 & density≥5（= jev_gate.FAST_PATH_MATCH/DENSITY）

公式（SSoT §16.5）:
  route_confidence = match_score
                     − 0.3 (若 prediction_error > 0.3)
                     − 0.2 (若 case_density < 3)
路由:
  route_confidence >= 0.7 → L1_DIRECT（零 token 直答）
  route_confidence <  0.7 → L2_HANDOFF（转 L2，透传 l1_intent_hint）

FAIL-OPEN:
  - recall 空/超时（memories 为空）→ route_confidence=0 → L2_HANDOFF；
  - C4 不可用（无 rea/debate 信号或 C4 计算异常）→ 退化为纯 C3（不扣 0.3）；
  - 认知系统整体不可用（cognitive_available=False）→ 退回注册表静态置信度。

C3 匹配度复用 core.cognitive_router.evaluate_match（不重写）。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from core.cognitive_router import TIER1_DENSITY_THRESHOLD, evaluate_match
from core.jev_gate import (
    FAST_PATH_DENSITY,
    FAST_PATH_MATCH,
    PREDICTION_ERROR_THRESHOLD,
)

# ============================================================
# 阈值（单一事实源：数值只引用 C3/C4 既有常量）
# ============================================================

THRESHOLD_HIGH = 0.7
CASE_DENSITY_MIN = TIER1_DENSITY_THRESHOLD          # 3
PREDICTION_ERROR_MAX = PREDICTION_ERROR_THRESHOLD   # 0.3

# FAST_PATH 仅作信号透传；门控决策严格以 route_confidence 公式为准
FAST_PATH_MATCH_CONST = FAST_PATH_MATCH             # 0.8
FAST_PATH_DENSITY_CONST = FAST_PATH_DENSITY         # 5

# 扣分系数（SSoT §16.5 公式常量）
PENALTY_PREDICTION_ERROR = 0.3
PENALTY_LOW_DENSITY = 0.2

# 浮点容差：prediction_error 恰好等于阈值（如 abs(0.9-0.6) 的二进制误差）不扣分
_EPS = 1e-9

# 路由决策
L1_DIRECT = "L1_DIRECT"
L2_HANDOFF = "L2_HANDOFF"

# reasons 标记
R_RECALL_EMPTY = "recall_empty"
R_PREDICTION_ERROR = "prediction_error_penalty"
R_LOW_DENSITY = "low_density_penalty"
R_C4_UNAVAILABLE = "c4_unavailable"
R_STATIC_FALLBACK = "cognitive_unavailable_static_fallback"


@dataclass
class RouteConfidenceResult:
    """门控信号结果（可 to_dict 序列化透传给前端/L2）。"""

    route_confidence: float
    decision: str
    match_score: float
    case_density: int
    prediction_error: Optional[float]
    fast_path: bool
    degraded: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================
# C4: 预测误差（actual 取值顺序对齐 jev_gate.jev_gate）
# ============================================================

def compute_prediction_error(
    match_score: float,
    rea_confidence: Optional[float] = None,
    debate_result: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """计算 |expected − actual|；无任何 C4 实际值信号时返回 None（视为 C4 不可用）。

    actual 优先级: rea_confidence → debate_result["bull_confidence"]（缺省 0.5）。
    """
    if rea_confidence:
        actual = rea_confidence
    elif debate_result:
        actual = debate_result.get("bull_confidence", 0.5)
    else:
        return None
    return abs(match_score - actual)


# ============================================================
# 公式
# ============================================================

def compute_route_confidence(
    match_score: float,
    case_density: int,
    prediction_error: Optional[float] = None,
    c4_available: bool = True,
) -> tuple:
    """按 SSoT §16.5 公式计算 route_confidence。

    Returns:
        (route_confidence, reasons)
    """
    route_confidence = match_score
    reasons: List[str] = []
    if c4_available and prediction_error is not None \
            and prediction_error > PREDICTION_ERROR_MAX + _EPS:
        route_confidence -= PENALTY_PREDICTION_ERROR
        reasons.append(R_PREDICTION_ERROR)
    if case_density < CASE_DENSITY_MIN:
        route_confidence -= PENALTY_LOW_DENSITY
        reasons.append(R_LOW_DENSITY)
    # 置信度归一到 [0, 1]（match_score 本身非负，防御性 clamp）
    route_confidence = max(0.0, min(1.0, route_confidence))
    return route_confidence, reasons


# ============================================================
# 门控主入口
# ============================================================

def evaluate_route(
    memories: Optional[List[Any]],
    *,
    rea_confidence: Optional[float] = None,
    debate_result: Optional[Dict[str, Any]] = None,
    c4_available: bool = True,
    cognitive_available: bool = True,
    static_confidence: Optional[float] = None,
) -> RouteConfidenceResult:
    """C3+C4 → route_confidence → L1_DIRECT / L2_HANDOFF（全程 FAIL-OPEN）。

    Args:
        memories: recall 返回的记忆列表（元素需有 .score 或 ["score"]）；None/[] 视为召回空。
        rea_confidence: C4 实际值信号 1（33-REA confidence）。
        debate_result: C4 实际值信号 2（含 bull_confidence）。
        c4_available: C4 是否可用；False → 纯 C3（不扣预测误差分）。
        cognitive_available: 认知系统整体是否可用；False → 退回 static_confidence。
        static_confidence: 注册表静态置信度（认知整体不可用时的兜底）。
    """
    # 1) 认知整体不可用 → 注册表静态置信度兜底
    if not cognitive_available:
        sc = float(static_confidence) if static_confidence is not None else 0.0
        return RouteConfidenceResult(
            route_confidence=sc,
            decision=L1_DIRECT if sc >= THRESHOLD_HIGH else L2_HANDOFF,
            match_score=sc,
            case_density=0,
            prediction_error=None,
            fast_path=False,
            degraded=True,
            reasons=[R_STATIC_FALLBACK],
        )

    # 2) recall 空（无命中/超时）→ route_confidence=0 → 强制 L2
    if not memories:
        return RouteConfidenceResult(
            route_confidence=0.0,
            decision=L2_HANDOFF,
            match_score=0.0,
            case_density=0,
            prediction_error=None,
            fast_path=False,
            degraded=True,
            reasons=[R_RECALL_EMPTY],
        )

    # 3) C3 匹配度（复用既有实现）
    match_score, case_density = evaluate_match(memories)

    # 4) C4 预测误差（任何异常/无信号 → 退化为纯 C3，FAIL-OPEN）
    prediction_error: Optional[float] = None
    reasons: List[str] = []
    c4_ok = c4_available
    if not c4_ok:
        reasons.append(R_C4_UNAVAILABLE)
    else:
        try:
            prediction_error = compute_prediction_error(
                match_score, rea_confidence, debate_result)
            if prediction_error is None:
                c4_ok = False
                reasons.append(R_C4_UNAVAILABLE)
        except Exception:
            c4_ok = False
            prediction_error = None
            reasons.append(R_C4_UNAVAILABLE)

    # 5) 公式 + 路由
    route_confidence, formula_reasons = compute_route_confidence(
        match_score, case_density, prediction_error, c4_available=c4_ok)
    reasons = reasons + formula_reasons
    fast_path = (
        match_score >= FAST_PATH_MATCH_CONST
        and case_density >= FAST_PATH_DENSITY_CONST
    )
    return RouteConfidenceResult(
        route_confidence=route_confidence,
        decision=L1_DIRECT if route_confidence >= THRESHOLD_HIGH else L2_HANDOFF,
        match_score=match_score,
        case_density=case_density,
        prediction_error=prediction_error,
        fast_path=fast_path,
        degraded=False,
        reasons=reasons,
    )


def should_handle_l1(memories: Optional[List[Any]], **kwargs: Any) -> bool:
    """便捷布尔入口: True=L1 零 token 直答；False=转 L2。kwargs 透传 evaluate_route。"""
    return evaluate_route(memories, **kwargs).decision == L1_DIRECT
