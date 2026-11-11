#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4 — PlanCard 校验与 side-B 构造。

契约唯一事实源：`52-lobehub协议集成/schemas/plancard.schema.json`。
本模块为 Python 侧等价手写实现（与 3.1 侧 `src/lib/agent/plancard.ts` 同规则），
不引入 jsonschema 等三方依赖。

边界（硬约束）：PlanCard 只承载规划层产物，不含执行/交易语义；
`plan_steps[].tool` 必须形如 `l0.<shell>.mcp.<tool>` 且须在 47 registry 已注册。
"""

from __future__ import annotations

import random
import re
import time
from typing import Any, Iterable, Sequence

ID_PREFIX = "pc-"
INTENT_MAX_CHARS = 500
OUTCOME_MAX_CHARS = 1000
DEFAULT_EVALUATOR_REF = "45.heuristic@1.0.0"
FALLBACK_TOOL = "l0.cognition.mcp.recall"
CHAIN_UNMAPPED_FLAG = "chain_unmapped"

TOOL_PATTERN = re.compile(r"^l0\.[a-z0-9_-]+\.mcp\.[a-z0-9_]+$")
EVALUATOR_PATTERN = re.compile(r"^45\.[a-z0-9_]+@\d+\.\d+\.\d+$")

# DreamOS 节点 → L0 工具映射（确定性前缀/关键词表，非 LLM 推断）。
# 节点 id 形如 A0..A9 / C1..C5 / F1 / G1 / S1；未命中一律回退 recall 并标 chain_unmapped。
NODE_TOOL_MAP = {
    "S": "l0.cognition.mcp.stats",
    "A": "l0.eval.mcp.eval_analyze",
    "C": "l0.data.mcp.data_fetch",
    "F": "l0.data.mcp.data_fetch",
    "G": "l0.eval.mcp.eval_report",
    "R": "l0.rea.mcp.submit_rea_analyze",
}
NODE_KEYWORD_MAP = (
    ("NEWS", "l0.data.mcp.data_fetch"),
    ("RISK", "l0.eval.mcp.eval_report"),
    ("REA", "l0.rea.mcp.submit_rea_analyze"),
    ("SEMANTIC", "l0.semantic-39.mcp.semantic_lookup"),
    ("ENTITY", "l0.semantic-39.mcp.semantic_lookup"),
    ("EVAL", "l0.eval.mcp.eval_analyze"),
    ("SCAN", "l0.eval.mcp.eval_analyze"),
    ("RECALL", "l0.cognition.mcp.recall"),
    ("MEMORY", "l0.cognition.mcp.recall"),
)
_NODE_ID_RE = re.compile(r"^([A-Z])[0-9_]")


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_plancard(obj: Any) -> tuple[bool, list[str]]:
    """手写校验（与 plancard.schema.json 等价），返回 (ok, errors)。"""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return False, ["root_not_object"]

    card_id = obj.get("id")
    if not isinstance(card_id, str) or not card_id.startswith(ID_PREFIX):
        errors.append(f"id_invalid_prefix:{card_id!r}")

    intent = obj.get("intent")
    if not isinstance(intent, str) or not intent:
        errors.append("intent_required")
    elif len(intent) > INTENT_MAX_CHARS:
        errors.append(f"intent_too_long:{len(intent)}>{INTENT_MAX_CHARS}")

    for key in ("context_refs", "evidence_refs", "risk_flags"):
        if key in obj and not _is_str_list(obj[key]):
            errors.append(f"{key}_not_string_array")

    steps = obj.get("plan_steps")
    if not isinstance(steps, list) or not steps:
        errors.append("plan_steps_empty")
    else:
        for index, raw in enumerate(steps):
            if not isinstance(raw, dict):
                errors.append(f"plan_steps[{index}]_not_object")
                continue
            step = raw.get("step")
            if not isinstance(step, int) or isinstance(step, bool) or step < 1:
                errors.append(f"plan_steps[{index}].step_invalid")
            action = raw.get("action")
            if not isinstance(action, str) or not action:
                errors.append(f"plan_steps[{index}].action_required")
            tool = raw.get("tool")
            if not isinstance(tool, str) or not TOOL_PATTERN.match(tool):
                errors.append(f"plan_steps[{index}].tool_invalid:{tool!r}")
            if "args_hint" in raw and not isinstance(raw["args_hint"], dict):
                errors.append(f"plan_steps[{index}].args_hint_not_object")

    cost = obj.get("cost_estimate")
    if cost is not None:
        if not isinstance(cost, dict):
            errors.append("cost_estimate_not_object")
        else:
            for key in ("tokens", "tool_calls"):
                if key in cost and not _is_non_negative_int(cost[key]):
                    errors.append(f"cost_estimate.{key}_invalid")

    outcome = obj.get("expected_outcome")
    if outcome is not None:
        if not isinstance(outcome, str):
            errors.append("expected_outcome_not_string")
        elif len(outcome) > OUTCOME_MAX_CHARS:
            errors.append(f"expected_outcome_too_long:{len(outcome)}")

    validation = obj.get("validation")
    if not isinstance(validation, dict):
        errors.append("validation_required")
    else:
        refs = validation.get("evaluator_refs")
        if not isinstance(refs, list):
            errors.append("validation.evaluator_refs_not_array")
        else:
            for index, ref in enumerate(refs):
                if not isinstance(ref, str) or not EVALUATOR_PATTERN.match(ref):
                    errors.append(f"validation.evaluator_refs[{index}]_invalid:{ref!r}")
        checks = validation.get("acceptance_checks")
        if checks is not None and not _is_str_list(checks):
            errors.append("validation.acceptance_checks_not_string_array")
        if "outcome" in validation and not isinstance(validation["outcome"], str):
            errors.append("validation.outcome_not_string")

    meta = obj.get("debate_meta")
    if meta is not None:
        if not isinstance(meta, dict):
            errors.append("debate_meta_not_object")
        else:
            if "debate_id" in meta and not isinstance(meta["debate_id"], str):
                errors.append("debate_meta.debate_id_not_string")
            if meta.get("side") is not None and meta["side"] not in ("A", "B"):
                errors.append("debate_meta.side_invalid")
            if meta.get("verdict") is not None and meta["verdict"] not in (
                "WIN",
                "LOSE",
                "INCONCLUSIVE",
            ):
                errors.append("debate_meta.verdict_invalid")

    return (not errors), errors


def new_plancard_id(now: float | None = None) -> str:
    """pc-<base36 毫秒时间戳><10 位随机后缀>（ulid-ish，标准库即可）。"""
    stamp = int((now if now is not None else time.time()) * 1000)
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    millis = stamp
    digits = ""
    while millis:
        millis, rem = divmod(millis, 36)
        digits = alphabet[rem] + digits
    suffix = "".join(random.choice(alphabet) for _ in range(10))
    return f"{ID_PREFIX}{digits or '0'}{suffix}"


def map_node_to_tool(node_id: str) -> str | None:
    """DreamOS 节点 id → L0 工具全名；无确定性映射返回 None。"""
    if not isinstance(node_id, str) or not node_id.strip():
        return None
    node = node_id.strip().upper()
    for keyword, tool in NODE_KEYWORD_MAP:
        if keyword in node:
            return tool
    matched = _NODE_ID_RE.match(node)
    if matched:
        return NODE_TOOL_MAP.get(matched.group(1))
    return None


def _ordered_nodes(nodes: Any) -> list[str]:
    """链字段 → 去重保序节点列表。"""
    values = nodes if isinstance(nodes, list) else [nodes] if isinstance(nodes, str) else []
    ordered: list[str] = []
    for node in values:
        if isinstance(node, str) and node and node not in ordered:
            ordered.append(node)
    return ordered


def chain_for_variant(response: dict[str, Any], variant: int = 0) -> list[str]:
    """variant 0=base+extend；1=仅 base（空则取 extend 子集）；≥2=反转 extend。"""
    base = _ordered_nodes(response.get("base_chain"))
    extend = _ordered_nodes(response.get("extend_nodes"))
    if variant <= 0:
        return base + [node for node in extend if node not in base]
    if variant == 1:
        return base or extend[: max(1, (len(extend) + 1) // 2)]
    reversed_extend = list(reversed(extend))
    chain = base + [node for node in reversed_extend if node not in base]
    return chain or list(reversed(base))


def describe_variant(response: dict[str, Any], variant: int = 0) -> str:
    """变体依据（写入 proposal.selection_basis，便于 trace 审计）。"""
    base = _ordered_nodes(response.get("base_chain"))
    extend = _ordered_nodes(response.get("extend_nodes"))
    if variant <= 0:
        return f"完整链：base_chain({len(base)}) + extend_nodes({len(extend)})"
    if variant == 1:
        if base:
            return f"基链优先：仅 base_chain({len(base)})"
        return f"基链为空：取 extend_nodes({len(extend)}) 前段子集"
    return f"链序扰动：base_chain + 反转 extend_nodes({len(extend)})"


def from_dreamos_intent(
    intent: str,
    intent_response: dict[str, Any],
    allowed_tools: Iterable[str],
    context_refs: Sequence[str] | None = None,
    variant: int = 0,
) -> dict[str, Any]:
    """DreamOS `/api/v1/intent` 响应 → side-B PlanCard（variant 决定链组成）。

    base_chain + extend_nodes 顺序映射为 plan_steps；工具必须真实注册，
    否则回退 `l0.cognition.mcp.recall` 并在 risk_flags 标 `chain_unmapped`。
    """
    allowed = set(allowed_tools)
    response = intent_response if isinstance(intent_response, dict) else {}
    chain: list[str] = chain_for_variant(response, variant)
    if not chain:
        # recommended_chain 可能为 "A->B" / "A,B" 形式的汇总串，仅在主链缺失时兜底
        recommended = response.get("recommended_chain")
        if isinstance(recommended, str):
            chain = _ordered_nodes(
                [n for n in re.split(r"\s*(?:->|>|\||,|\s)\s*", recommended) if n]
            )
        else:
            chain = _ordered_nodes(recommended)

    steps: list[dict[str, Any]] = []
    risk_flags: list[str] = []
    for index, node in enumerate(chain, start=1):
        tool = map_node_to_tool(node)
        if tool is None or tool not in allowed:
            tool = FALLBACK_TOOL
            if CHAIN_UNMAPPED_FLAG not in risk_flags:
                risk_flags.append(CHAIN_UNMAPPED_FLAG)
        steps.append(
            {
                "step": index,
                "action": f"DreamOS 节点 {node} 对应的 L0 只读检索",
                "tool": tool,
                "args_hint": {"node": node},
            }
        )

    if not steps:
        # 空链兜底：至少一步可执行只读检索
        fallback = (
            FALLBACK_TOOL
            if FALLBACK_TOOL in allowed
            else (sorted(allowed)[0] if allowed else FALLBACK_TOOL)
        )
        steps.append(
            {
                "step": 1,
                "action": "意图识别结果为空链，回退认知检索",
                "tool": fallback,
                "args_hint": {"intent": intent},
            }
        )
        risk_flags.append(CHAIN_UNMAPPED_FLAG)

    evidence_refs = [f"dreamos.intent:{response.get('intent_type', 'unknown')}"]
    confidence = response.get("confidence")
    if confidence is not None:
        evidence_refs.append(f"dreamos.confidence:{confidence}")

    expected = (
        f"DreamOS 编排链 {response.get('recommended_chain') or 'base_chain'} "
        f"执行后产出可验证结果"
    )
    card: dict[str, Any] = {
        "id": new_plancard_id(),
        "intent": intent[:INTENT_MAX_CHARS],
        "context_refs": list(context_refs or []),
        "plan_steps": steps,
        "evidence_refs": evidence_refs,
        "risk_flags": risk_flags,
        "cost_estimate": {"tokens": 0, "tool_calls": len(steps)},
        "expected_outcome": expected[:OUTCOME_MAX_CHARS],
        "validation": {
            "evaluator_refs": [DEFAULT_EVALUATOR_REF],
            "acceptance_checks": ["DreamOS 编排链执行结果可复现"],
        },
    }
    return card


def plan_text(card: dict[str, Any]) -> str:
    """拼接 PlanCard 的可检索文本（供触发器 T3 做证据冲突检测）。"""
    parts: list[str] = [str(card.get("intent") or ""), str(card.get("expected_outcome") or "")]
    for step in card.get("plan_steps") or []:
        if isinstance(step, dict):
            parts.append(str(step.get("action") or ""))
            parts.append(str(step.get("tool") or ""))
    parts.extend(str(r) for r in card.get("evidence_refs") or [] if isinstance(r, str))
    return " ".join(p for p in parts if p)
