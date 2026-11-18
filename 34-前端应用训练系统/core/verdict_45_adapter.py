# -*- coding: utf-8 -*-
"""45 消费 UncertaintyVerdict 的统一适配器（T3.4）。

定位: 纯映射,不做业务判定。
  UncertaintyVerdict → 45 verdict 语义（PASS/BLOCK/INCONCLUSIVE）
  45 gate 结果 + verdict 检查 → 统一 GateDecision

规则（SPEC §3.6 / §8.4）:
  supported + 级别达标 + 45 PASS → PASS
  contradicted / 45 BLOCK        → BLOCK
  inconclusive / needs_human / 45 INCONCLUSIVE/TIMEOUT/ERROR → INCONCLUSIVE
  缺裁决 / 级别不足              → INCONCLUSIVE（不自动放行）
  shadow 模式: 一律 allow=True,但记录 would_block 供误拦率统计
  硬约束: FAIL-OPEN,坏输入返回 degraded 决策,不抛异常。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

VERDICT_TO_45 = {
    "supported": "PASS",
    "contradicted": "BLOCK",
    "inconclusive": "INCONCLUSIVE",
    "needs_human": "INCONCLUSIVE",
}
_LEVEL_RANK = {"U0": 0, "U1": 1, "U2": 2, "U3": 3}
_45_DECIDED = ("PASS", "BLOCK", "INCONCLUSIVE")


def to_45_verdict(uncertainty_verdict: Optional[Dict[str, Any]]) -> str:
    """UncertaintyVerdict → 45 verdict 三值。非法/缺失 → INCONCLUSIVE。"""
    if not isinstance(uncertainty_verdict, dict):
        return "INCONCLUSIVE"
    return VERDICT_TO_45.get(uncertainty_verdict.get("verdict"), "INCONCLUSIVE")


def to_gate_context(
    ticket: Optional[Dict[str, Any]],
    uncertainty_verdict: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """构建交给 45 gate / settle 的上下文（只读快照）。"""
    t = ticket if isinstance(ticket, dict) else {}
    v = uncertainty_verdict if isinstance(uncertainty_verdict, dict) else {}
    return {
        "task_id": t.get("ticket_id"),
        "trace_id": t.get("trace_id") or v.get("trace_id"),
        "required_verdict_level": t.get("required_verdict_level"),
        "claims": list(t.get("claims") or []),
        "uncertainty_verdict": v or None,
        "verdict_45": to_45_verdict(v),
        "evidence_refs": list(v.get("evidence_refs") or []),
        "poe_score": v.get("poe_score"),
        "confidence": v.get("confidence"),
    }


def _verdict_failure(
    uncertainty_verdict: Optional[Dict[str, Any]],
    required_level: Optional[str],
) -> Optional[str]:
    if not required_level:
        return None  # Ticket 未声明 → 不强制判决
    if not isinstance(uncertainty_verdict, dict):
        return "verdict_missing"
    level = uncertainty_verdict.get("level")
    if level not in _LEVEL_RANK:
        return "verdict_level_invalid"
    if _LEVEL_RANK[level] < _LEVEL_RANK.get(required_level, 0):
        return "verdict_level_insufficient"
    if uncertainty_verdict.get("verdict") == "contradicted":
        return "verdict_contradicted"
    if uncertainty_verdict.get("verdict") != "supported":
        return "verdict_inconclusive"
    if not uncertainty_verdict.get("evidence_refs"):
        return "verdict_evidence_empty"
    return None


def merge_gate_decision(
    uncertainty_verdict: Optional[Dict[str, Any]],
    required_level: Optional[str],
    gate_allowed: bool,
    gate_report: Optional[Dict[str, Any]],
    mode: str = "hard",
) -> Dict[str, Any]:
    """把 verdict 检查与 45 gate 结果合并成统一决策（纯函数）。"""
    try:
        v = uncertainty_verdict if isinstance(uncertainty_verdict, dict) else None
        report = gate_report if isinstance(gate_report, dict) else {}
        reasons = []

        v_fail = _verdict_failure(v, required_level)
        if v_fail:
            reasons.append(v_fail)

        gate_verdict = report.get("verdict")
        if gate_verdict not in _45_DECIDED:
            gate_verdict = "INCONCLUSIVE"
            reasons.append("gate_not_decided")
        elif gate_verdict != "PASS":
            reasons.append(f"gate_{str(gate_verdict).lower()}")

        if gate_verdict == "BLOCK" or v_fail == "verdict_contradicted":
            decision = "BLOCK"
        elif gate_verdict == "PASS" and not v_fail:
            decision = "PASS"
        else:
            decision = "INCONCLUSIVE"

        hard_allow = bool(gate_allowed) and decision == "PASS"
        allow = hard_allow if mode == "hard" else True

        return {
            "ok": True,
            "allow": allow,
            "would_block": not hard_allow,
            "decision": decision,
            "reasons": reasons,
            "mode": mode,
            "uncertainty_verdict": v,
            "gate_verdict": gate_verdict,
            "eval_id": report.get("eval_id"),
            "evidence_uri": report.get("evidence_uri"),
            "trace_id": report.get("trace_id") or (v or {}).get("trace_id"),
        }
    except Exception:
        return {
            "ok": False,
            "allow": False,
            "would_block": True,
            "decision": "INCONCLUSIVE",
            "reasons": ["adapter_degraded"],
            "degraded": True,
        }


def build_verdict_45_gate(
    gate_fn: Any,
    verdict_provider: Any,
    required_level: Optional[str] = None,
    mode: str = "hard",
) -> Optional[Any]:
    """包装现有 45 gate: 先查 verdict,再调 45,最后合并裁决。

    gate_fn(context) -> (allowed, report)
    verdict_provider(context) -> dict | None
    任一不可调用 → None（FAIL-OPEN，调用侧退回无门禁）。
    """
    if not callable(gate_fn) or not callable(verdict_provider):
        return None

    def gate(context: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        ctx = context if isinstance(context, dict) else {}
        try:
            uv = verdict_provider(ctx)
        except Exception:
            uv = None
        level = ctx.get("required_verdict_level") or required_level
        try:
            allowed, report = gate_fn(ctx)
        except Exception:
            allowed, report = False, {"verdict": "ERROR"}
        merged = merge_gate_decision(uv, level, allowed, report, mode=mode)
        return bool(merged.get("allow")), merged

    return gate
