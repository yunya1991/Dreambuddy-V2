#!/usr/bin/env python3
"""事后校验：行动链 vs 原版 SKILL.md 的 Checklist + HARD-GATE（设计节 4.4）。

Task 12 遗漏交付物补齐——供 Task 18/19 的 cognitive_session 调用。

关键创新：HARD-GATE 的"违反"判定不是正向匹配，是反向排除（看相对时序）。
例如 TDD 的 HARD-GATE "先写代码后补测试且未删除=违反"——
判定条件：行动链中写代码先于写测试，且测试后无删除代码段记录。
"""
import re
from typing import Any, Dict, List

from cognitive_superpowers import SuperpowersSkill

FOLLOW_SCORE_THRESHOLD = 0.35  # 设计节 4.3


def compute_follow_score(
    checklist_matched: int,
    checklist_total: int,
    gate_respected: int,
    gate_total: int,
) -> float:
    """设计节 4.3：follow_score = checklist*0.6 + gate*0.4。"""
    check_pct = checklist_matched / max(1, checklist_total)
    gate_pct = gate_respected / max(1, gate_total)
    return check_pct * 0.6 + gate_pct * 0.4


def verify_skill_followed(
    skill: SuperpowersSkill, action_chain: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """事后校验：行动链 vs 原版 SKILL.md 的 Checklist + HARD-GATE。

    Returns: {followed, score, checklist_matched, checklist_missed,
              gate_violations, gate_respected, detail}
    """
    action_text = " ".join(
        str(a.get("detail", "")) for a in action_chain
    ).lower()
    file_events = [
        a for a in action_chain if a.get("action_type") == "file_change"
    ]
    tools_used = {
        a.get("tool", "")
        for a in action_chain
        if a.get("action_type") == "tool_call"
    }
    commits = [
        a for a in action_chain if a.get("action_type") == "git_commit"
    ]

    checklist_matched, checklist_missed = [], []
    for item in skill.checklists:
        if _checklist_hit(item, action_text, file_events, tools_used, commits):
            checklist_matched.append(item)
        else:
            checklist_missed.append(item)

    gate_violations, gate_respected = [], []
    for gate in skill.hard_gates:
        if _gate_violated(gate, action_text, file_events, commits):
            gate_violations.append(gate)
        else:
            gate_respected.append(gate)

    score = compute_follow_score(
        len(checklist_matched), len(skill.checklists),
        len(gate_respected), len(skill.hard_gates),
    )

    return {
        "followed": score >= FOLLOW_SCORE_THRESHOLD,
        "score": round(score, 2),
        "checklist_matched": checklist_matched,
        "checklist_missed": checklist_missed,
        "gate_violations": gate_violations,
        "gate_respected": gate_respected,
        "detail": (
            f"checklist {len(checklist_matched)}/{len(skill.checklists)} "
            f"HARD-GATE respected {len(gate_respected)}/{len(skill.hard_gates)}"
        ),
    }


def _checklist_hit(
    item: str,
    action_text: str,
    file_events: list,
    tools_used: set,
    commits: list,
) -> bool:
    """Checklist 项命中判定：关键词出现在行动链文本中。"""
    item_lower = item.lower()
    keywords = re.findall(r"[a-zA-Z]+|[\u4e00-\u9fff]+", item_lower)
    if not keywords:
        return False
    hits = sum(1 for kw in keywords if kw in action_text)
    return hits >= max(1, len(keywords) // 3)  # 至少命中 1/3 关键词


def _gate_violated(
    gate: str, action_text: str, file_events: list, commits: list
) -> bool:
    """HARD-GATE 违反判定（反向时序排除，设计节 4.4）。

    例如 TDD "NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST"：
      - 检测：写代码（.py/.ts 非测试文件）先于写测试（test_*.py/tests/）
      - 且测试后无"删除代码"记录
      → 判定违反
    """
    gate_lower = gate.lower()
    # TDD 类 gate：检测代码先于测试
    if "failing test" in gate_lower or "test first" in gate_lower:
        code_indices = []
        test_indices = []
        for i, ev in enumerate(file_events):
            f = ev.get("file", "").lower()
            is_test = "test" in f or "/tests/" in f or "test_" in f
            is_code = not is_test and (
                f.endswith(".py") or f.endswith(".ts")
            )
            if is_test:
                test_indices.append(i)
            elif is_code:
                code_indices.append(i)
        if code_indices and test_indices:
            first_code = min(code_indices)
            first_test = min(test_indices)
            if first_code < first_test:
                # 检查测试后是否有删除代码记录
                has_delete = any(
                    "delete" in ev.get("detail", "").lower()
                    or "remove" in ev.get("detail", "").lower()
                    for ev in file_events[first_test:]
                )
                if not has_delete:
                    return True  # 违反
    # 通用 gate：若 gate 提到 "commit" 但无 commit 记录
    if "commit" in gate_lower and "before" in gate_lower and not commits:
        return True
    return False
