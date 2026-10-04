"""SKILL 亲和力成熟 — 基于 usage 统计调整 triggers / 建议 deprecated

借鉴免疫系统亲和力成熟：
- 高调用 + 高成功率 → suggest_activate（shadow→active）
- 高调用 + 低成功率 → suggest_deprecate 或 refine_triggers
- 低调用 → 暂不建议（数据不足）

数据来源：skill_circulation_stats.py 的 invocation 记录
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


# 阈值
DEFAULT_MIN_INVOCATIONS = 3
DEFAULT_ACTIVATE_SUCCESS_RATE = 0.8
DEFAULT_DEPRECATE_SUCCESS_RATE = 0.3


def _load_stats(stats_path: Path) -> dict:
    """加载 circulation stats JSON。"""
    if not stats_path.exists():
        return {}
    try:
        with open(stats_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}  # FAIL-OPEN


def analyze_affinity(
    stats_path: Path | str,
    min_invocations: int = DEFAULT_MIN_INVOCATIONS,
    activate_success_rate: float = DEFAULT_ACTIVATE_SUCCESS_RATE,
    deprecate_success_rate: float = DEFAULT_DEPRECATE_SUCCESS_RATE,
) -> list[dict]:
    """分析所有 SKILL 的亲和力状态，返回建议动作列表。

    Returns:
        [{skill, action, reason, success_rate, invocation_count}]
        action ∈ {suggest_activate, suggest_deprecate, refine_triggers, no_action}
    """
    stats_path = Path(stats_path)
    stats = _load_stats(stats_path)
    if not stats:
        return []

    actions: list[dict] = []
    for skill, record in stats.items():
        if not isinstance(record, dict):
            continue
        count = record.get("invocation_count", 0)
        successes = record.get("success_count", 0)
        if count < min_invocations:
            continue  # 数据不足
        rate = successes / count if count > 0 else 0.0

        if rate >= activate_success_rate:
            action = "suggest_activate"
            reason = f"高成功率 {rate:.0%}，建议从 shadow 转为 active"
        elif rate <= deprecate_success_rate:
            action = "suggest_deprecate"
            reason = f"低成功率 {rate:.0%}，建议 deprecated 或重新设计"
        else:
            action = "refine_triggers"
            reason = f"中等成功率 {rate:.0%}，建议优化 triggers 提升召回精度"

        actions.append({
            "skill": skill,
            "action": action,
            "reason": reason,
            "success_rate": round(rate, 4),
            "invocation_count": count,
        })

    actions.sort(key=lambda a: a["invocation_count"], reverse=True)
    return actions


def apply_affinity_action(
    skill_name: str,
    action: str,
    stats_path: Path | str,
    skill_path: Optional[Path] = None,
) -> bool:
    """应用亲和力动作（仅写入 status 变更，不改逻辑）。

    目前仅支持记录建议，实际 frontmatter 写回由 skill_lifecycle_writer 负责。
    """
    # 记录到 stats 的 suggestions 字段
    stats_path = Path(stats_path)
    stats = _load_stats(stats_path)
    if skill_name not in stats:
        return False
    if "suggestions" not in stats[skill_name]:
        stats[skill_name]["suggestions"] = []
    stats[skill_name]["suggestions"].append({
        "action": action,
        "applied_at": __import__("datetime").datetime.now().isoformat(),
    })
    try:
        with open(stats_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
