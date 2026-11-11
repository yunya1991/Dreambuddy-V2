#!/usr/bin/env python3
"""52-LobeHub 协议集成 Phase 4 — 确定性门禁、启发式评分与争议触发器。

设计原则（SPEC §7.7 / 铁律①②④⑤）：
  - 门禁与评分全部确定性（无 LLM 参与），保证可复现、可审计；
  - 铁律④：trade-exec 域工具永不进脑暴/Debate —— G3 直接 BLOCK；
  - 触发器 T1-T4 只做「是否升级 Debate」的信号判定，不执行任何 DreamOS 链路。
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Sequence

from plancard import plan_text, validate_plancard

TRADE_EXEC_DOMAIN = "trade-exec"
# 铁律④：实盘/live/下单/order 语义一律 BLOCK（大小写不敏感，子串匹配）
FORBIDDEN_RISK_KEYWORDS = ("实盘", "live", "下单", "order")

T1_SCORE_GAP_THRESHOLD = 0.1
MAX_SCORE_EVIDENCE_BONUS_THRESHOLD = 5
COST_TOKEN_SOFT_CAP = 20000

# 铁律⑤ fail-closed：模型标识为空/占位一律视为未声明多样性
INVALID_MODEL_VALUES = {"", "unknown", "none", "null"}


def _normalized_model(value: Any) -> str:
    return "" if value is None else str(value).strip().lower()


def _side_of(proposal: Mapping[str, Any]) -> str:
    """推断提案所属侧（side_a / side_b）；未知侧不参与跨侧比较。"""
    raw = str(proposal.get("proposer_id") or proposal.get("side") or "")
    if raw.startswith("side_a") or raw == "A":
        return "side_a"
    if raw.startswith("side_b") or raw == "B":
        return "side_b"
    return raw


def validate_diversity(proposals: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """铁律⑤ fail-closed 校验（Phase 4.5 加固）。

    拒绝：任一卡 model 空/unknown/none/null；跨侧同 model；
    跨侧 evidence_path 相同或任一侧为空。
    返回违规列表（空列表 = 通过）；每条含 rule/reason/same_model/same_evidence_path。
    """
    valid = [p for p in proposals if isinstance(p, Mapping) and isinstance(p.get("card"), dict)]
    violations: list[dict[str, Any]] = []

    for item in valid:
        model = item.get("model")
        if _normalized_model(model) in INVALID_MODEL_VALUES:
            violations.append(
                {
                    "rule": "model_unknown",
                    "pair": [item.get("proposer_id")],
                    "models": [model],
                    "evidence_paths": [item.get("evidence_path")],
                    "same_model": False,
                    "same_evidence_path": False,
                    "reason": "model 为空/unknown/none/null，拒绝开题（铁律⑤）",
                }
            )

    sides = {_side_of(item) for item in valid}
    compare_cross_side = {"side_a", "side_b"} <= sides
    if compare_cross_side:
        for i in range(len(valid)):
            for j in range(i + 1, len(valid)):
                left, right = valid[i], valid[j]
                if _side_of(left) == _side_of(right):
                    continue
                same_model = _normalized_model(left.get("model")) == _normalized_model(
                    right.get("model")
                )
                left_path = str(left.get("evidence_path") or "").strip()
                right_path = str(right.get("evidence_path") or "").strip()
                bad_path = not left_path or not right_path or left_path == right_path
                if not (same_model or bad_path):
                    continue
                violations.append(
                    {
                        "rule": "model_collision" if same_model else "evidence_path_collision",
                        "pair": [left.get("proposer_id"), right.get("proposer_id")],
                        "models": [left.get("model"), right.get("model")],
                        "evidence_paths": [left.get("evidence_path"), right.get("evidence_path")],
                        "same_model": same_model,
                        "same_evidence_path": bad_path,
                        "reason": (
                            "两侧 model 相同，拒绝开题"
                            if same_model
                            else "两侧 evidence_path 相同或为空，拒绝开题"
                        ),
                    }
                )
    return violations


def gate(
    card: dict[str, Any],
    allowed_tools: Iterable[str] | Any,
    domains: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """四道确定性门禁，返回 {verdict: PASS|BLOCK, reasons: [...]}。

    G1 schema 不合规（含 unknown 字段容错）→ BLOCK
    G2 plan_steps[].tool 未注册 → BLOCK
    G3 工具所属壳 domain == trade-exec → BLOCK（铁律④）
    G4 risk_flags 命中 实盘|live|下单|order → BLOCK
    """
    reasons: list[str] = []

    ok, errors = validate_plancard(card)
    if not ok:
        reasons.extend(f"G1:schema_invalid:{err}" for err in errors)

    if isinstance(allowed_tools, set):
        allowed = allowed_tools
    elif hasattr(allowed_tools, "allowed"):
        allowed = allowed_tools.allowed()
    else:
        allowed = set(allowed_tools)
    domain_map = domains if domains is not None else getattr(allowed_tools, "domains", {}) or {}

    steps = card.get("plan_steps") if isinstance(card, dict) else None
    for step in steps if isinstance(steps, list) else []:
        tool = step.get("tool") if isinstance(step, dict) else None
        if not isinstance(tool, str):
            continue
        if tool not in allowed:
            reasons.append(f"G2:unknown_tool:{tool}")
        if domain_map.get(tool) == TRADE_EXEC_DOMAIN:
            reasons.append(f"G3:trade_exec_forbidden:{tool}")

    risk_flags = card.get("risk_flags") if isinstance(card, dict) else None
    for flag in risk_flags if isinstance(risk_flags, list) else []:
        lowered = str(flag).lower()
        for keyword in FORBIDDEN_RISK_KEYWORDS:
            if keyword in lowered:
                reasons.append(f"G4:live_trading_flag:{flag}")
                break

    return {"verdict": "BLOCK" if reasons else "PASS", "reasons": reasons}


def score(card: dict[str, Any]) -> dict[str, Any]:
    """确定性启发式评分（0-1），返回 {score, breakdown}。

    base 0.5
    evidence_refs ≥2 +0.15；≥5 再 +0.05
    plan_steps ≥2 +0.10
    validation.evaluator_refs 非空 +0.10
    validation.acceptance_checks ≥1 +0.10
    expected_outcome 非空 +0.10
    每个 risk_flag -0.10
    cost_estimate.tokens > 20000 -0.05
    clamp[0, 1]
    """
    breakdown: dict[str, float] = {"base": 0.5}
    total = breakdown["base"]

    evidence_refs = card.get("evidence_refs") if isinstance(card, dict) else None
    evidence_count = len(evidence_refs) if isinstance(evidence_refs, list) else 0
    if evidence_count >= 2:
        total += 0.15
        breakdown["evidence_refs>=2"] = 0.15
        if evidence_count >= MAX_SCORE_EVIDENCE_BONUS_THRESHOLD:
            total += 0.05
            breakdown["evidence_refs>=5"] = 0.05

    steps = card.get("plan_steps") if isinstance(card, dict) else None
    if isinstance(steps, list) and len(steps) >= 2:
        total += 0.10
        breakdown["plan_steps>=2"] = 0.10

    validation = card.get("validation") if isinstance(card, dict) else None
    if isinstance(validation, dict):
        refs = validation.get("evaluator_refs")
        if isinstance(refs, list) and refs:
            total += 0.10
            breakdown["evaluator_refs"] = 0.10
        checks = validation.get("acceptance_checks")
        if isinstance(checks, list) and len(checks) >= 1:
            total += 0.10
            breakdown["acceptance_checks"] = 0.10

    outcome = card.get("expected_outcome") if isinstance(card, dict) else None
    if isinstance(outcome, str) and outcome.strip():
        total += 0.10
        breakdown["expected_outcome"] = 0.10

    risk_flags = card.get("risk_flags") if isinstance(card, dict) else None
    if isinstance(risk_flags, list) and risk_flags:
        penalty = -0.10 * len(risk_flags)
        total += penalty
        breakdown["risk_flags"] = penalty

    cost = card.get("cost_estimate") if isinstance(card, dict) else None
    tokens = cost.get("tokens") if isinstance(cost, dict) else None
    if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > COST_TOKEN_SOFT_CAP:
        total -= 0.05
        breakdown["cost_tokens>20000"] = -0.05

    return {"score": max(0.0, min(1.0, round(total, 4))), "breakdown": breakdown}


_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _tokens(text: str) -> set[str]:
    """文本 → 词元集合（拉丁词 + 中文二元组），用于 T3 证据冲突交集判定。"""
    lowered = text.lower()
    tokens = set(_TOKEN_RE.findall(lowered))
    cjk = _CJK_RE.findall(lowered)
    tokens.update("".join(cjk[i : i + 2]) for i in range(len(cjk) - 1))
    tokens.update(cjk)
    return tokens


def triggers(
    cards: Sequence[dict[str, Any]],
    gate_results: Sequence[dict[str, Any]],
    recall_hits: Sequence[dict[str, Any]] | None = None,
    user_requested: bool = False,
    threshold: float = T1_SCORE_GAP_THRESHOLD,
) -> dict[str, Any]:
    """争议触发器 T1-T4 → {escalate, fired, detail}。

    cards: [{"card": PlanCard, "score": float, "side": "A"|"B"}]
    gate_results: [{"card_id": str, "verdict": "PASS"|"BLOCK", "reasons": [...]}]
    recall_hits: cognition recall 记忆列表（{"id","quality_level","content"}）；None=未取证
    """
    fired: list[str] = []
    detail: dict[str, Any] = {}

    scored = [c for c in cards if isinstance(c, dict)]
    scores = sorted((float(c.get("score") or 0.0) for c in scored), reverse=True)

    # T1：Top2 分差 < 阈值
    if len(scores) >= 2:
        gap = round(scores[0] - scores[1], 4)
        detail["T1"] = {"gap": gap, "threshold": threshold, "fired": gap < threshold}
        if gap < threshold:
            fired.append("T1")
    else:
        detail["T1"] = {"fired": False, "reason": "not_enough_cards"}

    # T2：存在被 BLOCK 的卡且其分数 > 可行卡最高分
    verdict_by_id = {
        str(r.get("card_id")): str(r.get("verdict"))
        for r in gate_results
        if isinstance(r, dict) and r.get("card_id") is not None
    }
    blocked_scores: list[float] = []
    pass_scores: list[float] = []
    for item in scored:
        card = item.get("card") if isinstance(item.get("card"), dict) else {}
        verdict = verdict_by_id.get(str(card.get("id")), str(item.get("gate_verdict") or "PASS"))
        if verdict == "BLOCK":
            blocked_scores.append(float(item.get("score") or 0.0))
        else:
            pass_scores.append(float(item.get("score") or 0.0))
    t2_fired = bool(blocked_scores) and (not pass_scores or max(blocked_scores) > max(pass_scores))
    detail["T2"] = {
        "fired": t2_fired,
        "blocked_max": max(blocked_scores) if blocked_scores else None,
        "pass_max": max(pass_scores) if pass_scores else None,
    }
    if t2_fired:
        fired.append("T2")

    # T3：recall 命中 D 级记忆且与任一方 plan 文本有交集；无 recall 数据 → skipped
    if recall_hits is None:
        detail["T3"] = {"fired": False, "status": "skipped", "reason": "recall_disabled"}
    else:
        plan_tokens: set[str] = set()
        for item in scored:
            card = item.get("card") if isinstance(item.get("card"), dict) else {}
            plan_tokens |= _tokens(plan_text(card))
        conflicts: list[str] = []
        for hit in recall_hits:
            if not isinstance(hit, dict):
                continue
            if str(hit.get("quality_level") or "").upper() != "D":
                continue
            overlap = _tokens(str(hit.get("content") or "")) & plan_tokens
            if overlap:
                conflicts.append(f"{hit.get('id') or 'unknown'}:{'/'.join(sorted(overlap)[:3])}")
        detail["T3"] = {"fired": bool(conflicts), "conflicts": conflicts}
        if conflicts:
            fired.append("T3")

    # T4：用户显式要求辩论
    detail["T4"] = {"fired": bool(user_requested)}
    if user_requested:
        fired.append("T4")

    return {"escalate": bool(fired), "fired": fired, "detail": detail}
