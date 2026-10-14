"""
智能决策推导器 — C 层 expected_decision 智能推导
================================================
P1 修复：替代硬编码 CONTINUE，基于 outcome + confidence + action/learned 语义推导多样化反射决策。
P2 增强：集成 C-Drive Agent 反思逻辑（阈值对齐 c_drive_agent.py CONF_REDO/CONF_SUPPLEMENT）。

推导优先级：
  1. C-Drive Agent 反思（P2）：debate 元数据可用时走 _reflect_after_debate 逻辑
  2. outcome 信号（P1）：成功/失败/部分/未知
  3. confidence 信号（P1）：<0.3 REDO / 0.3-0.6 INSERT_BEFORE / >=0.6 CONTINUE
  4. action 关键词（P1）：retry→REDO / supplement→INSERT_BEFORE / skip→JUMP_TO / abort→EARLY_TERMINATE
  5. learned 关键词（P1）：补充语义信号

设计原则：
  - 纯函数，无副作用，无外部依赖
  - FAIL-OPEN：信号不足时安全降级为 CONTINUE
  - 可扩展：P3 接入辩论引擎 run_fast/run_deep

关联：
  - C 层训练循环: 3.1-FRONTEND/src/lib/c-reflection-training-loop.ts
  - C-Drive Agent: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py
  - 辩论引擎: 1-ARCHITECTURE/dream-harness-bridge/packages/python-server/debate_engine.py
"""
import re
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 常量
# ============================================================

# 反射决策类型（对齐前端 ReflectionDecision）
CONTINUE = "CONTINUE"
REDO = "REDO"
INSERT_BEFORE = "INSERT_BEFORE"
JUMP_TO = "JUMP_TO"
EARLY_TERMINATE = "EARLY_TERMINATE"

# confidence 阈值（对齐 C-Drive Agent 的 CONF_REDO/CONF_SUPPLEMENT 语义）
CONF_REDO_THRESHOLD = 0.3       # < 0.3 → 极低置信度 → REDO
CONF_SUPPLEMENT_THRESHOLD = 0.6  # < 0.6 → 中低置信度 → INSERT_BEFORE

# P2: C-Drive Agent 反思阈值（严格对齐 c_drive_agent.py L206-207）
CDRIVE_CONF_REDO = 0.20          # 置信度 < 0.20 → REDO
CDRIVE_CONF_SUPPLEMENT = 0.30    # max(bull, bear) < 0.30 → SUPPLEMENT→INSERT_BEFORE

# C-Drive Action → 前端 ReflectionDecision 映射
CDRIVE_ACTION_MAP = {
    "continue": CONTINUE,
    "redo": REDO,
    "jump": JUMP_TO,
    "supplement": INSERT_BEFORE,
    # debate 不直接映射为 expected_decision，由辩论结果推导
}

# action 关键词 → 决策映射（按优先级排序）
_ACTION_KEYWORD_MAP: List[Tuple[str, str]] = [
    (r"retry|redo|重做|重来|重新", REDO),
    (r"insert|supplement|补充|插入|加补|追加", INSERT_BEFORE),
    (r"skip|jump|跳过|跳转|换路|改路", JUMP_TO),
    (r"abort|terminate|终止|放弃|中止|退出", EARLY_TERMINATE),
]

# learned 关键词 → 决策映射
_LEARNED_KEYWORD_MAP: List[Tuple[str, str]] = [
    (r"should\s+redo|need\s+retry|需要重做|应该重试|重做", REDO),
    (r"missing\s+info|need\s+supplement|缺少.*信息|需要补充|补充信息", INSERT_BEFORE),
    (r"wrong\s+path|should\s+skip|错误.*路径|应该跳过|换路", JUMP_TO),
    (r"waste|should\s+stop|浪费|应该终止|应该放弃|无效", EARLY_TERMINATE),
]


# ============================================================
# 核心推导函数
# ============================================================

def derive_expected_decision(
    intent: str,
    actions: List[str],
    outcome: str,
    outcome_text: str = "",
    learned: Optional[List[str]] = None,
    confidence: float = 0.4,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """根据训练案例语义信号推导 expected_decision。

    参数:
        intent: 任务/意图描述
        actions: 执行的动作列表
        outcome: 结果状态 (success/failure/partial/unknown)
        outcome_text: 结果文本描述
        learned: 经验教训列表
        confidence: 置信度 (0-1)
        metadata: 额外元数据

    返回:
        反射决策字符串 (CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE)
    """
    learned = learned or []
    metadata = metadata or {}

    # ── 1. outcome 信号（主信号） ──
    if outcome == "success":
        # 成功 → 继续执行
        return CONTINUE

    if outcome == "failure":
        # 失败 → 需要纠正，按 action/learned 语义推导纠正方向
        correction = _derive_correction_from_semantics(actions, learned)
        if correction:
            return correction
        # 无语义信号 → 默认 EARLY_TERMINATE（失败后安全降级）
        return EARLY_TERMINATE

    if outcome == "partial":
        # 部分成功 → 可能需要补充信息或重做
        # 优先看 action/learned 语义
        correction = _derive_correction_from_semantics(actions, learned)
        if correction:
            return correction
        # 无语义信号 → confidence 决定
        if confidence < CONF_REDO_THRESHOLD:
            return REDO
        return INSERT_BEFORE  # 部分成功通常需要补充

    # unknown → 降级 CONTINUE（安全默认）
    # ── 2. confidence 信号（次信号） ──
    if confidence < CONF_REDO_THRESHOLD:
        return REDO
    if confidence < CONF_SUPPLEMENT_THRESHOLD:
        return INSERT_BEFORE
    return CONTINUE


def derive_expected_decision_from_case(case: Any) -> str:
    """从 TrainingCase 对象推导 expected_decision（便捷封装）。

    参数:
        case: TrainingCase 对象（需有 intent/actions/outcome_text/learned/metadata/confidence 属性）

    返回:
        反射决策字符串
    """
    outcome_map = {
        "success": "success",
        "failure": "failure",
        "partial": "partial",
        "unknown": "partial",
    }
    outcome = outcome_map.get(
        case.metadata.get("outcome", "unknown") if case.metadata else "unknown",
        "partial",
    )

    return derive_expected_decision(
        intent=case.intent,
        actions=case.actions,
        outcome=outcome,
        outcome_text=case.outcome_text or "",
        learned=case.learned,
        confidence=getattr(case, "confidence", 0.4),
        metadata=case.metadata,
    )


# ============================================================
# P2: C-Drive Agent 反思逻辑集成
# ============================================================

def derive_with_cdrive_reflection(
    confidence: float,
    bull_confidence: Optional[float] = None,
    bear_confidence: Optional[float] = None,
) -> Optional[str]:
    """C-Drive Agent 反思逻辑（对齐 c_drive_agent.py _reflect_after_debate / _reflect_no_debate）。

    当 debate 元数据（bull/bear confidence）可用时走 _reflect_after_debate 逻辑：
      - confidence < CDRIVE_CONF_REDO → REDO
      - max(bull, bear) < CDRIVE_CONF_SUPPLEMENT → INSERT_BEFORE（映射自 SUPPLEMENT）
      - 否则 → CONTINUE

    当 debate 元数据不可用时走 _reflect_no_debate 逻辑：
      - confidence < CDRIVE_CONF_REDO → REDO
      - 否则 → CONTINUE

    参数:
        confidence: 原始置信度
        bull_confidence: Bull 方置信度（可选，来自辩论引擎）
        bear_confidence: Bear 方置信度（可选，来自辩论引擎）

    返回:
        反射决策字符串，或 None（当 confidence 不足以触发任何 C-Drive 阈值时）
    """
    # C-Drive 无辩论反思（c_drive_agent.py L524-537）
    if confidence < CDRIVE_CONF_REDO:
        return REDO

    # C-Drive 辩论后反思（c_drive_agent.py L539-574）
    if bull_confidence is not None and bear_confidence is not None:
        if max(bull_confidence, bear_confidence) < CDRIVE_CONF_SUPPLEMENT:
            return INSERT_BEFORE  # SUPPLEMENT → INSERT_BEFORE
        # 辩论后继续
        return None  # 不覆盖，交由 P1 逻辑继续推导

    # 无辩论且 confidence 不够低 → 不覆盖
    return None


def derive_expected_decision_with_cdrive(
    case: Any,
) -> str:
    """增强版决策推导：先走 C-Drive Agent 反思，再走 P1 语义推导。

    集成链路：
      1. 检查 case.metadata 是否含 debate 元数据（bull_confidence/bear_confidence）
      2. 有 → 调用 derive_with_cdrive_reflection() 走 C-Drive 反思
      3. C-Drive 返回非 None → 直接使用
      4. C-Drive 返回 None → 降级到 P1 derive_expected_decision

    参数:
        case: TrainingCase 对象

    返回:
        反射决策字符串
    """
    metadata = getattr(case, "metadata", None) or {}
    confidence = getattr(case, "confidence", 0.4)

    # P2: TDD 阶段显式映射（优先于通用推导）
    #   RED(测试失败/缺实现) → INSERT_BEFORE（需补充实现步骤）
    #   GREEN(测试通过/已实现) → CONTINUE（决策序列有效）
    tdd_phase = metadata.get("tdd_phase")
    if tdd_phase == "red":
        return INSERT_BEFORE
    if tdd_phase == "green":
        return CONTINUE

    # 提取 debate 元数据（由 33-REA 或辩论引擎注入）
    debate_meta = metadata.get("debate", {})
    bull_conf = debate_meta.get("bull_confidence")
    bear_conf = debate_meta.get("bear_confidence")

    # P2: 先走 C-Drive 反思
    cdrive_decision = derive_with_cdrive_reflection(
        confidence=confidence,
        bull_confidence=bull_conf,
        bear_confidence=bear_conf,
    )
    if cdrive_decision is not None:
        return cdrive_decision

    # P1: 降级到语义推导
    return derive_expected_decision_from_case(case)


# ============================================================
# 内部辅助函数
# ============================================================

def _derive_correction_from_semantics(
    actions: List[str],
    learned: List[str],
) -> Optional[str]:
    """从 action 和 learned 关键词推导纠正决策。

    参数:
        actions: 执行的动作列表
        learned: 经验教训列表

    返回:
        匹配到的决策字符串，无匹配返回 None
    """
    # 合并所有文本用于关键词匹配
    action_text = " ".join(actions).lower()
    learned_text = " ".join(learned).lower()

    # action 关键词优先（更直接反映执行意图）
    for pattern, decision in _ACTION_KEYWORD_MAP:
        if re.search(pattern, action_text, re.IGNORECASE):
            return decision

    # learned 关键词次之（反映事后反思）
    for pattern, decision in _LEARNED_KEYWORD_MAP:
        if re.search(pattern, learned_text, re.IGNORECASE):
            return decision

    return None


# ============================================================
# 统计辅助（用于调试/验证决策分布）
# ============================================================

def derive_decision_distribution(cases: List[Any]) -> Dict[str, int]:
    """批量推导决策分布（用于验证多样性）。

    参数:
        cases: TrainingCase 列表

    返回:
        {decision: count} 字典
    """
    dist = {
        CONTINUE: 0,
        REDO: 0,
        INSERT_BEFORE: 0,
        JUMP_TO: 0,
        EARLY_TERMINATE: 0,
    }
    for case in cases:
        decision = derive_expected_decision_from_case(case)
        dist[decision] = dist.get(decision, 0) + 1
    return dist
