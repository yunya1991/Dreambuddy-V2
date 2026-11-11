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

import domain_eval
from plancard import plan_text, validate_plancard

TRADE_EXEC_DOMAIN = "trade-exec"

# 铁律④的 G4 只做「实盘意图」词法探测；真实执行护栏是 G3（工具域）+ ADR-001 三道门。
# 2026-11-11 实测（77 条 trace / 220 张卡）：15 次 G4 命中全部是风险描述
# （"回测与实盘滑点差异""缺少实盘验证"），0 条是实盘请求；且 live/order 子串会
# 误伤 deliver/liveness/border/reorder。故 G4 改为三档：
#   动作或裸声明 → BLOCK；风险描述/否定语境 → 记 notes 放行；未命中 → 通过。
LIVE_TRADING_ACTION_PATTERNS = (
    re.compile(r"(直接|立即|自动|批量)(下单|委托|交易|执行)"),
    re.compile(r"实盘(下单|委托|开仓|平仓|接入)"),
    re.compile(r"(接入|启用|开启|切换?到?|转到)实盘"),
    re.compile(r"真实(账户|资金)(下|委托|交易)"),
    re.compile(
        r"(?<![a-z])(go[\s_-]*live|live[\s_-]*trading|live[\s_-]*order"
        r"|place[\s_-]*order|submit[\s_-]*order|execute[\s_-]*order)(?![a-z])"
    ),
)
# 纯提及（含实盘/live/order 但非执行动作）：英文按词边界，避免 deliver/reorder 误伤
LIVE_TRADING_MENTION_PATTERNS = (
    re.compile(r"实盘"),
    re.compile(r"下单"),
    re.compile(r"(?<![a-z])live(?![a-z])"),
    re.compile(r"(?<![a-z])order(?![a-z])"),
)
# 裸声明：风险旗标本身即该词，等于显式标注实盘语义 → BLOCK
BARE_LIVE_FLAGS = frozenset(
    {
        "实盘",
        "下单",
        "live",
        "order",
        "live trading",
        "live_trading",
        "livetrading",
        "order execution",
        "place order",
    }
)
# 否定/规避语境：命中即降级为 notes，不 BLOCK（无法判定时仍按描述放行并由 notes 留痕）
NEGATION_MARKERS = (
    "no_",
    "non_",
    "not_",
    "without",
    "avoid",
    "disable",
    "_off",
    "off_",
    "offline",
    "不",
    "非",
    "无",
    "禁止",
    "避免",
    "仅回测",
)
IDENTIFIER_RE = re.compile(r"^[a-z0-9_.\-]+$")

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


def _live_trading_flag_verdict(flag: Any) -> str:
    """G4 单条旗标判定：'block'（执行动作/裸声明）| 'note'（风险描述/否定语境）| ''。"""
    text = str(flag).strip()
    lowered = text.lower()
    if not any(p.search(lowered) for p in LIVE_TRADING_MENTION_PATTERNS):
        return ""
    if any(marker in lowered for marker in NEGATION_MARKERS):
        return "note"
    if any(p.search(lowered) for p in LIVE_TRADING_ACTION_PATTERNS):
        return "block"
    if lowered in BARE_LIVE_FLAGS:
        return "block"
    if IDENTIFIER_RE.match(lowered):
        # 形如 live_trading / order_execution 的显式标识符（无否定前缀）→ 视为声明
        return "block"
    return "note"


def gate(
    card: dict[str, Any],
    allowed_tools: Iterable[str] | Any,
    domains: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """四道确定性门禁，返回 {verdict: PASS|BLOCK, reasons: [...], notes?: [...]}。

    G1 schema 不合规（含 unknown 字段容错）→ BLOCK
    G2 plan_steps[].tool 未注册 → BLOCK
    G3 工具所属壳 domain == trade-exec → BLOCK（铁律④）
    G4 risk_flags 声明实盘执行动作或裸实盘标识 → BLOCK；
       仅作风险描述/否定语境 → 记 notes 放行（真实执行护栏是 G3 + ADR-001）
    """
    reasons: list[str] = []
    notes: list[str] = []

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
        verdict = _live_trading_flag_verdict(flag)
        if verdict == "block":
            reasons.append(f"G4:live_trading_flag:{flag}")
        elif verdict == "note":
            notes.append(f"G4:live_trading_mention:{flag}")

    result: dict[str, Any] = {"verdict": "BLOCK" if reasons else "PASS", "reasons": reasons}
    if notes:
        result["notes"] = notes
    return result


def score(
    card: dict[str, Any],
    *,
    run_id: str | None = None,
    allowed_tools: Any = None,
    evaluators_root: str | None = None,
    discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """确定性规划评分（0-1）：结构分基线 + 45 域评测契约结果。

    base = domain_eval.structural_score（确定性、非退化）
    BLOCK → 0.0 且 verdict=BLOCK；PASS → min(1.0, base+0.05)；
    INCONCLUSIVE → 仅 base（45 不可用/缺产物时绝不编造分数）。
    返回 {score, verdict, breakdown, evaluator_provenance}。
    """
    base, structural_detail = domain_eval.structural_score(card, allowed_tools)
    eval_result = domain_eval.evaluate_plan(
        card,
        run_id=run_id or "unspecified",
        evaluators_root=evaluators_root,
        discovery=discovery,
    )
    verdict = str(eval_result.get("verdict") or domain_eval.VERDICT_INCONCLUSIVE)
    domain_delta = 0.0
    final = base
    if verdict == domain_eval.VERDICT_BLOCK:
        domain_delta = -base
        final = 0.0
    elif verdict == domain_eval.VERDICT_PASS:
        final = min(1.0, base + 0.05)
        domain_delta = round(final - base, 3)

    unavailable = eval_result.get("reason") == "45_unavailable"
    provenance = {
        "source": "structural" if unavailable else "45",
        "evaluator": eval_result.get("evaluator"),
        "verdict": verdict,
        "reason": eval_result.get("reason"),
        "structural_detail": structural_detail,
    }
    breakdown: dict[str, Any] = {
        "structural": base,
        "domain_delta": round(domain_delta, 3),
        "domain": eval_result.get("domain"),
    }
    for item in structural_detail:
        breakdown[item["name"]] = item["contribution"]

    return {
        "score": round(final, 3),
        "verdict": verdict,
        "breakdown": breakdown,
        "evaluator_provenance": provenance,
    }


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

    # T1：**跨侧**最高分差 < 阈值。同侧多 variant 天然只差几分（同一规划器、
    # 同一证据基础），拿全局 Top1/Top2 比较会让 T1 恒命中、永远进不了 dispatch。
    # 两侧都有有效卡时按跨侧最佳比较；只有单侧时退回 Top2。
    by_side: dict[str, float] = {}
    for item in scored:
        side = _side_of(item)
        value = float(item.get("score") or 0.0)
        if value > by_side.get(side, -1.0):
            by_side[side] = value
    if "side_a" in by_side and "side_b" in by_side:
        gap = round(abs(by_side["side_a"] - by_side["side_b"]), 4)
        basis = "cross_side"
    elif len(scores) >= 2:
        gap = round(scores[0] - scores[1], 4)
        basis = "top2"
    else:
        gap = None
        basis = None
    if gap is not None:
        detail["T1"] = {
            "gap": gap,
            "threshold": threshold,
            "fired": gap < threshold,
            "basis": basis,
        }
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
