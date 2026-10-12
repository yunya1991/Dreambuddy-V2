"""§3.4 C-Drive v3 路由器 — P4-P8 全链路编排
=====================================================
封装 SPEC §3.4 五步链路:
  Step 1: recall + 匹配度评估 (P5 evaluate_match)
  Step 2: 四层分级路由 (P5 route → Tier1-4 + P4/P6/Debate)
  Step 3: L4 jev 全局裁决 (P7 jev_gate + JevAntiOscillation)
  Step 4: 决策输出
  Step 5: 认知闭环 (P8 close_loop)

灰度策略: CDRIVE_V3_GRAY_PERCENT (0-100)
  - hash(node_id) % 100 < gray_percent → 走 v3
  - 否则走 v1 (原始 run 逻辑)

Feature flag: CDRIVE_V3=true 强制全量启用 (覆盖灰度)

关联:
  - SPEC: 35-广义认知系统协作模块/SPEC-CDrive-CognitiveSystem-Integration.md §3.4
  - C-Drive Agent: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py
  - P4: rea_cdrive_adapter.py (33-REA 零 token 反思)
  - P5: cognitive_router.py (匹配度+案例密度路由)
  - P6: skill_research_layer.py (LLM+SKILL 调研)
  - P7: jev_gate.py (L4 jev 全局裁决)
  - P8: cognitive_loop.py (认知闭环训练进化)
"""
import hashlib
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.cognitive_router import (
    TIER1, TIER2, TIER3, TIER4,
    evaluate_match, route,
)
from core.rea_cdrive_adapter import derive_decision_from_rea
from core.jev_gate import jev_gate, JevAntiOscillation
from core.cognitive_loop import close_loop


# ============================================================
# 常量
# ============================================================

DEFAULT_GRAY_PERCENT = 0  # 默认 0% (完全关闭，向后兼容)

# 决策常量 (对齐 decision_deriver.py)
CONTINUE = "CONTINUE"
REDO = "REDO"
INSERT_BEFORE = "INSERT_BEFORE"
JUMP_TO = "JUMP_TO"
EARLY_TERMINATE = "EARLY_TERMINATE"


# ============================================================
# 灰度策略
# ============================================================

def _hash_node_id(node_id: str) -> int:
    """对 node_id 做 hash，返回 0-99 的整数 (确定性)"""
    h = hashlib.md5(node_id.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 100


def should_use_v3(node_id: str, gray_percent: Optional[int] = None) -> bool:
    """灰度判断: hash(node_id) % 100 < gray_percent

    Args:
        node_id: 节点 ID
        gray_percent: 灰度百分比 (0-100)，None 时读环境变量

    Returns:
        True: 走 v3 路由, False: 走 v1 原始逻辑
    """
    # Feature flag: CDRIVE_V3=true 强制全量启用
    if os.environ.get("CDRIVE_V3", "false").lower() == "true":
        return True

    if gray_percent is None:
        try:
            gray_percent = int(
                os.environ.get("CDRIVE_V3_GRAY_PERCENT", DEFAULT_GRAY_PERCENT))
        except (ValueError, TypeError):
            gray_percent = DEFAULT_GRAY_PERCENT

    if gray_percent <= 0:
        return False
    if gray_percent >= 100:
        return True
    return _hash_node_id(node_id) < gray_percent


# ============================================================
# 多路径检测
# ============================================================

def _detect_multi_path(signals: Optional[List[Dict]]) -> bool:
    """检测信号是否存在多路径冲突 (long+short 共存)"""
    if not signals:
        return False
    has_long = any(s.get("direction") == "long" for s in signals)
    has_short = any(s.get("direction") == "short" for s in signals)
    return has_long and has_short


# ============================================================
# CDriveV3Router — v3 五步链路编排器
# ============================================================

class CDriveV3Router:
    """v3 五步链路编排器

    封装 SPEC §3.4 完整链路:
      Step 1: recall + evaluate_match (P5)
      Step 2: route → Tier1-4 (P5 + P4/P6/Debate)
      Step 3: jev_gate + JevAntiOscillation (P7)
      Step 4: 决策输出
      Step 5: close_loop (P8, 仅当 record_fn 提供)

    用法:
        router = CDriveV3Router(
            recall_fn=my_recall,
            record_fn=my_record,
            verify_fn=my_verify,
        )
        result = router.run_v3(node_id="C1", result=node_result, state={}, signals=[])
    """

    def __init__(
        self,
        recall_fn: Optional[Callable] = None,
        record_fn: Optional[Callable] = None,
        verify_fn: Optional[Callable] = None,
        llm_fn: Optional[Callable[[str], str]] = None,
        debate_fn: Optional[Callable] = None,
        rea_parse_fn: Optional[Callable] = None,
    ):
        """初始化 v3 路由器

        Args:
            recall_fn: 认知检索函数 (context, top_k, min_quality, **kw) -> List[dict]
            record_fn: 认知记录函数 (content, tags, quality_level, **kw) -> dict
            verify_fn: 认知验证函数 (memory_id, success, **kw) -> dict
            llm_fn: LLM 调用函数 (prompt) -> str (Tier3/4 可能用到)
            debate_fn: 辩论函数 (signals, direction) -> dict (Tier4 用)
            rea_parse_fn: 33-REA 解析函数 (code) -> REAParseResult (Tier2 用)
        """
        self._recall_fn = recall_fn
        self._record_fn = record_fn
        self._verify_fn = verify_fn
        self._llm_fn = llm_fn
        self._debate_fn = debate_fn
        self._rea_parse_fn = rea_parse_fn
        self._jev_anti_oscillation = JevAntiOscillation()

    def run_v3(
        self,
        node_id: str,
        result: Any,
        state: Any,
        signals: Optional[List[Dict]] = None,
    ) -> Dict[str, Any]:
        """执行 v3 五步链路

        Args:
            node_id: 节点 ID
            result: 节点结果 (需有 confidence/direction 属性)
            state: 状态对象
            signals: 信号列表

        Returns:
            dict: {
                action, reason, confidence, steps_executed,
                match_score, case_density, tier, jev_decision,
                effort_level, cognitive_result
            }
        """
        steps: List[str] = []
        confidence = float(getattr(result, "confidence", 0.5))
        direction = getattr(result, "direction", None) or "NEUTRAL"
        sigs = signals or []

        # ── Step 1: recall + 匹配度评估 (P5) ──────────────
        memories = []
        if self._recall_fn is not None:
            try:
                memories = self._recall_fn(
                    context=f"node:{node_id} dir:{direction}",
                    top_k=5,
                    min_quality="C",
                ) or []
            except Exception:
                memories = []  # FAIL-OPEN
        match_score, case_density = evaluate_match(memories)
        steps.append("recall")

        # ── Step 2: 四层分级路由 (P5 route) ──────────────
        multi_path = _detect_multi_path(sigs)
        route_result = route(match_score, case_density, multi_path)
        tier = route_result.tier
        steps.append(f"route:{tier}")

        # 根据路由执行对应逻辑
        decision = CONTINUE  # 默认
        debate_result = None
        rea_confidence = confidence  # 默认用原始 confidence

        if tier == TIER1:
            # 高匹配 → 直接推进 (零 token)
            decision = CONTINUE

        elif tier == TIER2:
            # 低匹配 → L1 33-REA 反思 (零 token)
            if self._rea_parse_fn is not None:
                try:
                    rea_result = self._rea_parse_fn()
                    rea_decision = derive_decision_from_rea(rea_result)
                    if rea_decision is not None:
                        decision = rea_decision
                    rea_confidence = float(
                        getattr(rea_result, "confidence", confidence))
                except Exception:
                    pass  # FAIL-OPEN: 用默认 CONTINUE

        elif tier == TIER3:
            # 案例少+低匹配 → L3 SKILL 调研 (P6)
            try:
                from core.skill_research_layer import research_and_analyze
                research_and_analyze(
                    match_score=match_score,
                    case_density=case_density,
                    query=f"node:{node_id} dir:{direction}",
                )
            except Exception:
                pass  # FAIL-OPEN
            # 调研后默认 CONTINUE (调研结果供参考，不强制改决策)

        elif tier == TIER4:
            # 多路径 → L4 Debate 选择
            if self._debate_fn is not None:
                try:
                    debate_result = self._debate_fn(sigs, direction)
                    # 根据辩论结果调整决策
                    if debate_result:
                        bull_conf = debate_result.get("bull_confidence", 0)
                        bear_conf = debate_result.get("bear_confidence", 0)
                        if max(bull_conf, bear_conf) < 0.3:
                            decision = INSERT_BEFORE  # 均弱 → 补充
                        elif bull_conf > bear_conf:
                            decision = CONTINUE  # 多头占优
                except Exception:
                    pass  # FAIL-OPEN

        steps.append(f"decision:{decision}")

        # ── Step 3: L4 jev 全局裁决 (P7) ──────────────────
        try:
            jev_raw = jev_gate(
                decision, match_score, case_density,
                rea_confidence, debate_result,
            )
            # 防震荡
            jev_final = self._jev_anti_oscillation.check_oscillation(
                decision, jev_raw)
        except Exception:
            jev_raw = decision
            jev_final = decision  # FAIL-OPEN: 用原始决策
        steps.append(f"jev:{jev_final}")

        # ── Step 4: 决策输出 ──────────────────────────────
        # jev_final 即最终决策

        # ── Step 5: 认知闭环 (P8 close_loop) ──────────────
        cognitive_result = None
        if self._record_fn is not None:
            try:
                cognitive_result = close_loop(
                    decision=jev_final,
                    outcome="executed",
                    case_value_score=match_score,
                    content=f"v3 node:{node_id} tier:{tier} "
                            f"match:{match_score:.2f} density:{case_density}",
                    tags=f"C-Drive,v3,{tier}",
                    record_fn=self._record_fn,
                    verify_fn=self._verify_fn,
                )
                steps.append("close_loop")
            except Exception:
                pass  # FAIL-OPEN

        # effort_level 映射
        if tier in (TIER3, TIER4):
            effort_level = "deep"
        elif tier == TIER2:
            effort_level = "standard"
        else:
            effort_level = "light"

        return {
            "action": jev_final,
            "reason": (
                f"v3 router: tier={tier} "
                f"match={match_score:.2f} density={case_density} "
                f"jev={jev_final}"
            ),
            "confidence": confidence,
            "steps_executed": steps,
            "match_score": match_score,
            "case_density": case_density,
            "tier": tier,
            "jev_decision": jev_raw,
            "jev_final": jev_final,
            "cognitive_result": cognitive_result,
            "effort_level": effort_level,
        }
