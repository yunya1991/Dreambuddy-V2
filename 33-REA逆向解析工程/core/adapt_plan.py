"""改造方案契约与准入（SPEC-33-E §2.6 / T-E5）。

设计边界（硬约束）：
  - 只出方案，**不含 diff / 补丁**，不改任何文件。
  - 缺 `evidence_ref` / `rollback` / `acceptance` 的方案直接丢弃并计 `known_gaps`。
  - 只采纳 hypothesis gate=pass 的方案；无门禁信息时标 `gate=unknown` 且不写认知。
  - 本模块不调用大模型、不联网。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

REQUIRED_FIELDS = (
    "plan_id",
    "target_module",
    "change",
    "evidence_ref",
    "rollback",
    "acceptance",
)


def validate_plan(plan: dict[str, Any]) -> list[str]:
    """校验方案契约，返回错误列表（空列表即合法）。"""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not plan.get(field):
            errors.append(f"缺少必填字段 {field}")
    evidence = plan.get("evidence_ref")
    if evidence is not None and not isinstance(evidence, list):
        errors.append("evidence_ref 必须为数组")
    acceptance = plan.get("acceptance")
    if acceptance is not None and not (
        isinstance(acceptance, list)
        and all(isinstance(item, str) and item.strip() for item in acceptance)
    ):
        errors.append("acceptance 必须为非空字符串数组")
    return errors


def _normalize(plan: dict[str, Any], gate: str) -> dict[str, Any]:
    return {
        "plan_id": plan["plan_id"],
        "hypothesis_id": plan.get("hypothesis_id") or "",
        "target_module": plan["target_module"],
        "source_case": plan.get("source_case") or "",
        "change": plan["change"],
        "evidence_ref": list(plan["evidence_ref"]),
        "risk": list(plan.get("risk") or []),
        "rollback": plan["rollback"],
        "acceptance": list(plan["acceptance"]),
        "priority": plan.get("priority") or "P2",
        "gate": gate,
    }


def build_adapt_plans(
    plans: Iterable[Any],
    *,
    gates: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    """按 §2.6 生成可验收的 adapt_plan 列表。

    Args:
        plans: 宿主给出的方案列表。
        gates: hypothesis_id → gate（pass/review/reject）；缺省表示无门禁信息。

    Returns:
        {"plans": [...], "dropped": [...], "known_gaps": [...],
         "passed_hypotheses": [...]}
    """
    gate_map = dict(gates or {})
    accepted: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    known_gaps: list[str] = []
    passed: set[str] = set()

    for index, raw in enumerate(plans, start=1):
        if not isinstance(raw, dict):
            dropped.append({"plan_id": f"A-{index:03d}", "reason": "方案必须为对象"})
            known_gaps.append(f"adapt_plan 丢弃 A-{index:03d}: 方案必须为对象")
            continue
        plan_id = str(raw.get("plan_id") or f"A-{index:03d}")
        errors = validate_plan(raw)
        if errors:
            dropped.append({"plan_id": plan_id, "reason": "; ".join(errors)})
            known_gaps.append(f"adapt_plan 丢弃 {plan_id}: {', '.join(errors)}")
            continue

        hypothesis_id = str(raw.get("hypothesis_id") or "")
        gate = gate_map.get(hypothesis_id, "unknown") if hypothesis_id else "unknown"
        # 传了门禁结果时只采纳 pass；未传门禁信息时保留方案但标 unknown
        if gate_map and gate != "pass":
            dropped.append(
                {
                    "plan_id": plan_id,
                    "hypothesis_id": hypothesis_id,
                    "reason": f"hypothesis gate={gate}，只采纳 pass",
                }
            )
            known_gaps.append(f"adapt_plan 丢弃 {plan_id}: hypothesis gate={gate}")
            continue

        accepted.append(_normalize(raw, gate))
        if gate == "pass" and hypothesis_id:
            passed.add(hypothesis_id)

    write = [
        {
            "plan_id": item["plan_id"],
            "quality_level": "B",
            "content": f"[REA改造方案][{item['target_module']}] {item['change']}",
        }
        for item in accepted
        if item["gate"] == "pass"
    ]
    skip = [
        {"plan_id": item["plan_id"], "reason": "gate=unknown，未经 PoE 裁判，禁止写入"}
        for item in accepted
        if item["gate"] != "pass"
    ]
    return {
        "plans": accepted,
        "dropped": dropped,
        "known_gaps": known_gaps,
        "passed_hypotheses": sorted(passed),
        "cognitive_hint": {"write": write, "skip": skip},
    }
