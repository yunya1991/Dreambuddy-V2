"""阶段识别器 — PhaseClassifier。

基于三阶段闭环方法论（P1预期→P2盈收→P3修复），识别标的基本面所处阶段。
输入 E5/E6 信号 + 估值分位 + 事件时间线，输出当前阶段 + 置信度。

三个经典案例对应三阶段：
  - CRCL：P1 预期驱动（主网上线预期，落地后短期风险升）
  - UNI：P2 盈收扩张（Robinhood 接入带来费用收入大增）
  - HYPE：P3 估值修复（盈收强+估值稳，大跌后强势修复）

Shadow 模式：只计算 + 记录，不参与交易决策。
开关：enable_phase_classifier（默认 False）

混合规则（三因子组合，任一触发即评估切换）：
1. 事件驱动：主网落地/盈收公告 → P1→P2 或 P2→P3 边界
2. 信号阈值：E6 质变跌破 0.3（预期消退）/ E5 收缩跌破 0.3（盈收放缓）
3. 估值分位：>80 → P3 倾向；30-80 → P2 倾向；<30 + E6>0.5 → P1 倾向
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)


# ===========================================================================
# 开关
# ===========================================================================

# 总开关（默认 False，Shadow 模式：只计算 + 记录，不参与交易决策）
ENABLE_PHASE_CLASSIFIER = False


# ===========================================================================
# 阶段枚举
# ===========================================================================

P1_EXPECTATION = "P1_EXPECTATION"
P2_REVENUE_EXPANSION = "P2_REVENUE_EXPANSION"
P3_VALUATION_RECOVERY = "P3_VALUATION_RECOVERY"

# 预期事件类型（触发 P1 识别或 P1→P2 切换）
_EXPECTATION_EVENT_TYPES = ("mainnet_launch", "upgrade", "partnership")


# ===========================================================================
# 数据类
# ===========================================================================

@dataclass
class PhaseClassification:
    """阶段识别结果 — Shadow 模式输出。

    current_phase: P1_EXPECTATION / P2_REVENUE_EXPANSION / P3_VALUATION_RECOVERY
    phase_confidence: [0, 1] 三因子一致性程度
    switch_triggers: 触发评估的事件/阈值清单
    evidence: E5/E6/估值分位等输入证据
    strategy_hint: 来自阶段匹配策略映射表的提示
    """
    coin: str
    current_phase: str
    phase_confidence: float
    switch_triggers: List[str] = field(default_factory=list)
    evidence: Dict[str, float] = field(default_factory=dict)
    strategy_hint: Dict[str, Any] = field(default_factory=dict)


# ===========================================================================
# 阶段识别
# ===========================================================================

def classify_phase(
    coin: str,
    sub_signals: Dict[str, float],
    valuation_percentile: float,
    event_timeline: Optional[List[Dict]] = None,
) -> PhaseClassification:
    """识别标的基本面所处阶段。

    混合规则（三因子组合）：
    1. 信号阈值：E5 供给收缩强度 + E6 价值捕获质变
    2. 估值分位：高/中/低决定 P3/P2/P1 倾向
    3. 事件驱动：主网落地/盈收公告触发阶段切换

    匹配顺序：P3 → P1 → P2 → 默认 P2。
    事件驱动可覆盖规则匹配（pending→P1，landed→P1转P2）。

    FAIL-OPEN：无信号或异常 → 默认 P2（中性）+ 低 confidence。
    """
    try:
        e5 = float(sub_signals.get("supply_shrinkage_intensity", 0.0))
        e6 = float(sub_signals.get("value_capture_delta", 0.0))
        e7 = float(sub_signals.get("revenue_sustainability", 0.0))
    except (TypeError, ValueError):
        e5, e6, e7 = 0.0, 0.0, 0.0

    try:
        val = float(valuation_percentile) if valuation_percentile is not None else 50.0
    except (TypeError, ValueError):
        val = 50.0

    # BDSM 综合评分 = RQ(E7)*40% + MB(E6)*30% + SI(E5)*30%
    bds_score = e7 * 0.4 + e6 * 0.3 + e5 * 0.3

    evidence = {"e5": e5, "e6": e6, "e7": e7, "valuation_percentile": val, "bds_score": bds_score}
    triggers: List[str] = []

    # --- 规则匹配（顺序：P3 → P1 → P2）---

    phase = P2_REVENUE_EXPANSION  # 默认中性
    confidence = 0.3

    # P3：估值高位 + E5 仍正 + BDS≥0(B级) → 估值修复阶段（HYPE 案例）
    # BDS 门槛：P2→P3 需回购驱动力可持续性达标（BDSM 模型）
    if val > 80 and e5 > 0.3 and bds_score >= 0.0:
        phase = P3_VALUATION_RECOVERY
        confidence = min(1.0, 0.5 + e5 * 0.3)
        triggers.append("valuation_high_e5_positive_bds_pass")

    # P1：E6 质变强 + 估值低 → 预期驱动阶段（CRCL 案例）
    elif e6 > 0.5 and val < 30:
        phase = P1_EXPECTATION
        confidence = min(1.0, 0.5 + e6 * 0.3)
        triggers.append("e6_high_val_low")

    # P2：E5 收缩强 + E6 正 → 盈收扩张阶段（UNI 案例）
    elif e5 > 0.5 and e6 > 0.3:
        phase = P2_REVENUE_EXPANSION
        confidence = min(1.0, 0.5 + e5 * 0.3)
        triggers.append("e5_high_e6_positive")

    else:
        # 无强匹配 → 默认 P2 低 confidence
        triggers.append("default_neutral")

    # --- 事件驱动覆盖 ---

    if event_timeline:
        for evt in event_timeline:
            if not isinstance(evt, dict):
                continue
            evt_type = str(evt.get("type", ""))
            evt_status = str(evt.get("status", ""))

            # 预期事件 pending → 强化 P1（CRCL 主网预期阶段）
            if evt_type in _EXPECTATION_EVENT_TYPES and evt_status == "pending":
                if phase != P1_EXPECTATION:
                    phase = P1_EXPECTATION
                    triggers.append("event_pending_override")
                confidence = min(1.0, confidence + 0.2)

            # 预期事件 landed → P1→P2 切换（预期落地转盈收跟踪）
            elif evt_type in _EXPECTATION_EVENT_TYPES and evt_status == "landed":
                if phase == P1_EXPECTATION:
                    phase = P2_REVENUE_EXPANSION
                    triggers.append("event_landed_switch_p1_to_p2")
                confidence = min(1.0, confidence + 0.1)

    return PhaseClassification(
        coin=coin,
        current_phase=phase,
        phase_confidence=confidence,
        switch_triggers=triggers,
        evidence=evidence,
    )
