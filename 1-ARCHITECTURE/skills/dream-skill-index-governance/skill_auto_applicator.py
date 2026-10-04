"""SKILL 自动 apply — 减少人工干预

核心思想：SKILL 属于知识范畴、风险不高，当行为适应度 + 语义适应度双高分时，
自动写回 status（shadow→active 或 deprecated），仅在边界条件下需人工 gate。

决策矩阵（行为分 success_rate × 语义分 overall）：
┌──────────────┬────────────────┬──────────────┬──────────────┐
│              │ 语义高(≥8)      │ 语义中(4-8)   │ 语义低(<4)    │
├──────────────┼────────────────┼──────────────┼──────────────┤
│ 行为高(≥0.8)  │ auto_activate  │ refine       │ needs_human  │
│ 行为中(0.3-0.8)│ refine        │ refine       │ needs_human  │
│ 行为低(<0.3)  │ needs_human    │ refine       │ auto_deprecate│
└──────────────┴────────────────┴──────────────┴──────────────┘

安全边界：
- 仅 SKILL 治理域生效，不涉及交易决策（HC-9）
- invocation_count < 3 → 不自动 apply（数据不足）
- auto_activate 仅从 shadow→active，不跳过 proposed
- auto_deprecate 仅从 active/shadow→deprecated，不删文件
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional


# 阈值
MIN_INVOCATIONS = 3
BEHAVIOR_HIGH = 0.8
BEHAVIOR_LOW = 0.3
SEMANTIC_HIGH = 8.0
SEMANTIC_LOW = 4.0


def decide_action(
    behavior: dict,
    semantic: Optional[dict],
) -> dict:
    """根据行为适应度 + 语义适应度决定自动 apply 动作。

    Args:
        behavior: {success_rate, invocation_count}
        semantic: {overall, ...} 或 None（语义评估不可用时降级为仅行为分）

    Returns:
        {action, confidence, reason}
        action ∈ {auto_activate, auto_deprecate, refine_triggers, needs_human_review}
    """
    success_rate = behavior.get("success_rate", 0.0)
    invocations = behavior.get("invocation_count", 0)
    semantic_score = semantic.get("overall", 5.0) if semantic else None

    # 数据不足 → 不自动 apply
    if invocations < MIN_INVOCATIONS:
        return {
            "action": "needs_human_review",
            "confidence": "low",
            "reason": f"数据不足（调用 {invocations} < {MIN_INVOCATIONS}），暂不自动 apply",
        }

    # 语义分不可用 → 仅用行为分（保守策略，不自动激活）
    if semantic_score is None:
        if success_rate <= BEHAVIOR_LOW:
            return {
                "action": "auto_deprecate",
                "confidence": "medium",
                "reason": f"行为成功率 {success_rate:.0%} 过低，语义分不可用，建议 deprecated",
            }
        return {
            "action": "needs_human_review",
            "confidence": "low",
            "reason": "语义分不可用，保守策略需人工确认",
        }

    # 双适应度决策矩阵
    beh_high = success_rate >= BEHAVIOR_HIGH
    beh_low = success_rate <= BEHAVIOR_LOW
    sem_high = semantic_score >= SEMANTIC_HIGH
    sem_low = semantic_score <= SEMANTIC_LOW

    if beh_high and sem_high:
        return {
            "action": "auto_activate",
            "confidence": "high",
            "reason": f"行为 {success_rate:.0%} + 语义 {semantic_score} 双高分，自动激活",
        }
    if beh_low and sem_low:
        return {
            "action": "auto_deprecate",
            "confidence": "high",
            "reason": f"行为 {success_rate:.0%} + 语义 {semantic_score} 双低分，自动 deprecated",
        }
    if beh_high and sem_low:
        return {
            "action": "needs_human_review",
            "confidence": "medium",
            "reason": f"行为好但语义差（{semantic_score}），需人工判断是否文档问题",
        }
    if beh_low and sem_high:
        return {
            "action": "needs_human_review",
            "confidence": "medium",
            "reason": f"语义好但行为差（{success_rate:.0%}），需人工判断是否 trigger 不精准",
        }
    # 中间分数段
    return {
        "action": "refine_triggers",
        "confidence": "medium",
        "reason": f"行为 {success_rate:.0%} / 语义 {semantic_score} 中等，建议优化 triggers",
    }


def apply_decision(
    skill_path: Path | str,
    action: str,
    reason: str,
    write_status_fn: Optional[Callable] = None,
) -> bool:
    """应用决策：写回 SKILL.md 的 status 字段。

    Args:
        skill_path: SKILL.md 文件路径或其所在目录
        action: auto_activate / auto_deprecate / refine_triggers / needs_human_review
        reason: 决策原因（写入 evidence）
        write_status_fn: skill_lifecycle_writer.write_lifecycle 函数（可注入 mock）

    Returns:
        是否成功写回
    """
    from skill_lifecycle_writer import write_lifecycle as _default_write_lifecycle

    if write_status_fn is None:
        write_status_fn = _default_write_lifecycle

    status_map = {
        "auto_activate": "active",
        "auto_deprecate": "deprecated",
        "refine_triggers": None,  # 不改 status，仅记录建议
        "needs_human_review": None,
    }
    target_status = status_map.get(action)
    if target_status is None:
        return False  # 不需要写回 status

    # 兼容文件路径和目录路径
    p = Path(skill_path)
    skill_dir = p.parent if p.is_file() or p.suffix == ".md" else p

    try:
        result = write_status_fn(
            skill_dir=skill_dir,
            target_status=target_status,
            evidence=[f"auto_applicator:{reason}"],
        )
        return bool(result.get("ok", False))
    except Exception:
        return False  # FAIL-OPEN
