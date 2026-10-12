"""P7: L4 jev 全局裁决 — L4 元认知层集成
=====================================================
所有非 skip 场景都经 jev 裁决，确保决策质量。
纯规则零 token（预测误差 + Believability + HOT），仅 <5% 场景升级 LLM。

裁决规则:
  1. Fast-path: match_score >= 0.8 且 case_density >= 5 → 返回原始决策
  2. 预测误差 > 0.3 且 CONTINUE → REDO
  3. believability = density * match < 0.5 且 CONTINUE → INSERT_BEFORE
  4. HOT: REDO/EARLY_TERMINATE + density >= 3 + match >= 0.6 → CONTINUE

防震荡三重机制:
  1. 连续超过 MAX_CONSECUTIVE_OVERRIDE 次改写 → 信任原始决策
  2. 连续达到 DEGRADATION_THRESHOLD 次改写 → jev 临时降级
  3. 降级期间始终信任原始；需 RECOVERY_COUNT 次未改写才能恢复

关联:
  - SPEC: 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md §2.4
  - C-Drive Agent: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py
  - 决策常量: 34-前端应用训练系统/core/decision_deriver.py
"""
from typing import Dict, List, Optional, Tuple

# ============================================================
# 常量 — 对齐 decision_deriver.py
# ============================================================

CONTINUE = "CONTINUE"
REDO = "REDO"
INSERT_BEFORE = "INSERT_BEFORE"
JUMP_TO = "JUMP_TO"
EARLY_TERMINATE = "EARLY_TERMINATE"

# ============================================================
# jev_gate 参数（对齐 SPEC §2.4.1）
# ============================================================

# Fast-path 跳过阈值
FAST_PATH_MATCH = 0.8       # match_score >= 0.8
FAST_PATH_DENSITY = 5      # case_density >= 5

# 预测误差门控
PREDICTION_ERROR_THRESHOLD = 0.3  # > 0.3 降级

# Believability-weighted
BELIEVABILITY_THRESHOLD = 0.5  # < 0.5 降级

# HOT Self-Model
HOT_DENSITY_THRESHOLD = 3   # case_density >= 3
HOT_MATCH_THRESHOLD = 0.6   # match_score >= 0.6


# ============================================================
# 防震荡参数（对齐 SPEC §2.4.2）
# ============================================================

MAX_CONSECUTIVE_OVERRIDE = 2   # 连续改写上限，第 3 次信任原始
DEGRADATION_THRESHOLD = 3      # 连续改写触发衰减的阈值
RECOVERY_COUNT = 5             # 衰减后恢复 jev 权限所需未改写次数


# ============================================================
# jev_gate — 纯规则零 token 裁决
# ============================================================

def jev_gate(
    decision: str,
    match_score: float,
    case_density: int,
    rea_confidence: float,
    debate_result: Optional[Dict],
) -> str:
    """L4 全局裁决门控（纯规则，零 token）。

    所有非 skip 场景的决策都经此门控，确保决策质量。
    纯规则实现，不调用任何 LLM。

    Args:
        decision: 原始决策（CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE）
        match_score: 匹配度评分 (0.0-1.0)，来自 P5 evaluate_match
        case_density: 案例密度，recall 返回的记忆数量
        rea_confidence: 33-REA 解析的 confidence
        debate_result: 辩论结果 dict（含 bull_confidence），可为 None

    Returns:
        裁决后的决策字符串

    裁决优先级:
      0. Fast-path: match_score >= 0.8 且 density >= 5 → 跳过（高可信度无需裁决）
      1. 预测误差 > 0.3 且 CONTINUE → REDO
      2. believability < 0.5 且 CONTINUE → INSERT_BEFORE
      3. HOT: REDO/EARLY_TERMINATE + density >= 3 + match >= 0.6 → CONTINUE
      4. 无触发 → 返回原始决策
    """
    # 0. Fast-path: 高可信度跳过
    if match_score >= FAST_PATH_MATCH and case_density >= FAST_PATH_DENSITY:
        return decision

    # 1. 预测误差门控
    expected = match_score
    # actual: rea_confidence 优先，否则 debate_result.bull_confidence，否则 0.5
    if rea_confidence:
        actual = rea_confidence
    elif debate_result:
        actual = debate_result.get("bull_confidence", 0.5)
    else:
        actual = 0.5

    prediction_error = abs(expected - actual)
    if prediction_error > PREDICTION_ERROR_THRESHOLD and decision == CONTINUE:
        return REDO

    # 2. Believability-weighted
    believability = case_density * match_score
    if believability < BELIEVABILITY_THRESHOLD and decision == CONTINUE:
        return INSERT_BEFORE

    # 3. HOT Self-Model — 元认知"我觉得对吗"
    if (
        decision in (REDO, EARLY_TERMINATE)
        and case_density >= HOT_DENSITY_THRESHOLD
        and match_score >= HOT_MATCH_THRESHOLD
    ):
        return CONTINUE

    # 4. 无触发 → 返回原始
    return decision


# ============================================================
# JevAntiOscillation — 防震荡控制器
# ============================================================

class JevAntiOscillation:
    """jev 防震荡控制器。

    防止 jev 全局门控导致的"决策震荡"——
    jev 改写 CONTINUE→REDO，下次 recall 仍高匹配→CONTINUE，jev 又改回 REDO。

    三重机制:
      1. 连续超过 MAX_CONSECUTIVE_OVERRIDE 次改写 → 信任原始决策
      2. 连续达到 DEGRADATION_THRESHOLD 次改写 → jev 临时降级
      3. 降级期间始终信任原始；需 RECOVERY_COUNT 次未改写才能恢复
    """

    def __init__(self):
        self._consecutive_overrides: int = 0     # 连续改写计数
        self._last_decision: Optional[str] = None  # 上次原始决策
        self._override_history: List[Tuple[str, str]] = []  # 改写历史
        self._jev_degraded: bool = False         # jev 是否已降级
        self._degradation_count: int = 0         # 恢复 jev 权限还需未改写次数

    def check_oscillation(self, original_decision: str, jev_decision: str) -> str:
        """检查并防止决策震荡。

        Args:
            original_decision: 原始决策（jev 裁决前）
            jev_decision: jev 裁决后的决策

        Returns:
            最终决策（可能是 jev_decision 或 original_decision）

        规则:
          1. jev 已降级 → 信任原始决策（但仍追踪恢复进度）
          2. 未改写 → 重置计数，返回 jev_decision
          3. 发生改写 → 计数+1
          4. 超过改写上限 → 信任原始
          5. 同时达到衰减阈值 → jev 临时降级
        """
        self._last_decision = original_decision

        # 1. jev 已降级 → 信任原始决策（追踪恢复进度）
        if self._jev_degraded:
            if original_decision == jev_decision:
                # 未改写 → 递减恢复计数
                self._degradation_count -= 1
                if self._degradation_count <= 0:
                    self._jev_degraded = False
                    self._consecutive_overrides = 0
            return original_decision  # 降级期间始终信任原始

        # 2. 未改写 → 重置计数
        if original_decision == jev_decision:
            self._consecutive_overrides = 0
            return jev_decision

        # 3. 发生改写
        self._consecutive_overrides += 1
        self._override_history.append((original_decision, jev_decision))

        # 4. 超过改写上限 → 信任原始
        if self._consecutive_overrides >= MAX_CONSECUTIVE_OVERRIDE + 1:
            # 5. 同时达到衰减阈值 → jev 临时降级
            if self._consecutive_overrides >= DEGRADATION_THRESHOLD:
                self._jev_degraded = True
                self._degradation_count = RECOVERY_COUNT
            return original_decision

        # 未超上限 → 允许 jev 改写
        return jev_decision
