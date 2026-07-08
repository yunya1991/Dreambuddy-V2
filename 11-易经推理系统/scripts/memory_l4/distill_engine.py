"""蒸馏引擎模块 — 11步流程 + 三问逻辑。

从 ReviewRecord 出发，完成完整的蒸馏流程：
意图→调研→理论→假设→测试→结论→落地→监控→复盘→做梦→更新

回答三个核心问题：
- 是什么？(what_is_it)
- 为什么？(why_it_works)
- 怎么做？(how_to_apply)

v0.2 深度实现 — Phase 3 (P2)
"""

import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_distills_dir, memory_l4_cases_dir


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


# ── 蒸馏流程定义 ──

DISTILL_STEPS = [
    "intent",       # 意图: 明确问题
    "investigation", # 调研: 现状调查与矛盾分析
    "theory",        # 理论: 调用知识库、历史事件、联网搜索
    "hypothesis",    # 假设: 基于矛盾分析、现状、理论
    "test",          # 测试与观测: 验证假设，搜集数据
    "conclusion",    # 结论: 根据假设与实际表现推导
    "implementation",# 落地: 实施方案
    "monitoring",    # 监控: 监控结果
    "review",        # 复盘: 理论与实践一致性检验
    "reflection",    # 做梦: 外部反思
    "optimization",  # 更新优化: 最终优化方案
]


# ── 初始化 ──

def init_distill(
    review_record: Dict[str, Any],
    kind: str = "risk_signal",
    distill_id: Optional[str] = None,
) -> Dict[str, Any]:
    """从 ReviewRecord 初始化蒸馏记录。

    Args:
        review_record: ReviewRecord 数据
        kind: 蒸馏类型，自动从 review direction 推断
        distill_id: 蒸馏标识，默认自动生成

    Returns:
        初始 Distill 字典
    """
    did = distill_id or f"D_{now_iso_local()[:19].replace(':', '').replace('-', '')}"

    case_id = review_record.get("case_id", "")
    direction = review_record.get("direction", "mixed")

    # 从 direction 自动推断 kind
    if kind == "risk_signal":
        if direction == "success":
            kind = "benefit_experience"
        elif direction == "failure":
            kind = "risk_signal"

    claim_draft = _draft_claim_from_review(review_record)

    return {
        "distill_id": did,
        "version": "v0.2",
        "kind": kind,
        "what_is_it": {
            "claim": claim_draft,
            "definition": None,
            "classification": [kind],
        },
        "why_it_works": {
            "causal_analysis": "",
            "theory_basis": [],
            "evidence_chain": [],
            "contradiction_resolved": None,
        },
        "how_to_apply": {
            "actionable_rules": [],
            "trigger_conditions": [],
            "step_by_step": [],
            "risk_warnings": [],
        },
        "supporting_case_ids": [case_id] if case_id else [],
        "claim": claim_draft,
        "actionable_rules": [],
        "process_trace": {
            "intent": None,
            "investigation": None,
            "theory_refs": [],
            "hypothesis": None,
            "test_results": None,
            "conclusion": None,
            "implementation": None,
            "monitoring": None,
            "review_result": None,
            "reflection": None,
            "optimization": None,
        },
        "quadrant": {
            "x": 0.0,
            "y": 0.0,
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": 0.0,
                "y_consistency": 0.0,
                "y_human": 0.0,
                "notes": "Auto-generated from distill_engine v0.2",
            },
        },
        "migration_history": [],
    }


def _draft_claim_from_review(review: Dict[str, Any]) -> str:
    """从 ReviewRecord 自动生成初始 claim。"""
    direction = review.get("direction", "mixed")
    case_id = review.get("case_id", "unknown")
    mistakes = review.get("mistakes") or []
    successes = review.get("successes") or []

    if direction == "failure" and mistakes:
        top_mistake = mistakes[0].get("what", "unknown issue")
        return f"Failure pattern in {case_id}: {top_mistake}"
    elif direction == "success" and successes:
        top_success = successes[0].get("what", "unknown benefit")
        return f"Success pattern in {case_id}: {top_success}"
    else:
        return f"Mixed outcome pattern in {case_id}"


def _load_case_by_id(case_id: str) -> Optional[Dict[str, Any]]:
    """从 cases 目录加载 TradeCase。"""
    p = memory_l4_cases_dir() / f"{case_id}.json"
    if not p.exists():
        return None
    try:
        return _load_json(p)
    except Exception:
        return None


def _load_case_review(case: Dict[str, Any]) -> Dict[str, Any]:
    """从 TradeCase 提取 review 信息。"""
    review = case.get("review") or {}
    return {
        "summary": review.get("summary", ""),
        "consistency": review.get("theory_practice_consistency", "partially_consistent"),
        "mistakes": review.get("mistakes", []),
        "successes": review.get("successes", []),
        "review_record_id": review.get("review_record_id"),
    }


# ── 11 步蒸馏流程 ──

def step_intent(distill: Dict[str, Any], review_record: Dict[str, Any]) -> Dict[str, Any]:
    """Step 1: 意图 — 明确问题。

    从 review 的 mistakes/successes 提取核心问题描述，
    结合 case 象限坐标生成结构化 intent。
    """
    pt = distill["process_trace"]
    direction = review_record.get("direction", "unknown")
    case_id = review_record.get("case_id", "")
    mistakes = review_record.get("mistakes") or []
    successes = review_record.get("successes") or []

    # 提取核心问题
    if direction == "failure" and mistakes:
        items = [m.get("what", "") for m in mistakes if m.get("what")]
        problem = f"Failure analysis: {', '.join(items[:3])}"
    elif direction == "success" and successes:
        items = [s.get("what", "") for s in successes if s.get("what")]
        problem = f"Success pattern: {', '.join(items[:3])}"
    else:
        problem = f"Mixed outcome for {case_id}"

    # 加载 case 获取 regime 和 pnl
    case = _load_case_by_id(case_id)
    if case:
        regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")
        do = case.get("decision_outcome") or {}
        pnl = do.get("pnl_pct")
        pnl_str = f"{pnl}%" if pnl is not None else "N/A"
        problem += f" | regime={regime} pnl={pnl_str}"

    pt["intent"] = problem
    return distill


def step_investigation(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 2: 调研 — 现状调查与矛盾分析。

    从 case 的 thinking_chain 中提取各阶段决策，
    识别理论矛盾（A0 contradiction + A7/A8 gap）。
    """
    pt = distill["process_trace"]
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if not case_id:
        pt["investigation"] = "No case found for investigation"
        return distill

    case = _load_case_by_id(case_id)
    if not case:
        pt["investigation"] = f"Case {case_id} not found"
        return distill

    # 收集 thinking_chain 中的关键决策
    chain = case.get("thinking_chain") or []
    decisions_summary = []
    for entry in chain:
        d = entry.get("decision", "")
        if d:
            decisions_summary.append(f"[{entry['stage']}] {d}")

    # 提取 A0 矛盾
    contradictions = []
    for entry in chain:
        if entry.get("stage") == "A0" and entry.get("contradiction"):
            contradictions.append(entry["contradiction"])
        if entry.get("contradiction_analysis"):
            contradictions.append(entry["contradiction_analysis"])

    # 提取 review 中的理论差距
    review = _load_case_review(case)
    theory_gaps = []
    for m in review.get("mistakes", []):
        if m.get("theory_gap"):
            theory_gaps.append(m["theory_gap"])

    parts = []
    if decisions_summary:
        parts.append(f"Decisions: {'; '.join(decisions_summary[:5])}")
    if contradictions:
        parts.append(f"Contradictions: {'; '.join(contradictions[:3])}")
    if theory_gaps:
        parts.append(f"Theory gaps: {'; '.join(theory_gaps[:3])}")

    pt["investigation"] = " | ".join(parts) if parts else "No investigation data available"
    return distill


def step_theory(distill: Dict[str, Any], knowledge_refs: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Step 3: 理论 — 调用知识库、历史事件、联网搜索。

    从 case 的 theory_refs + evidence_chain 中提取理论引用，
    结合外部知识引用（knowledge_refs）。
    """
    pt = distill["process_trace"]
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    theory_sources = []

    if case_id:
        case = _load_case_by_id(case_id)
        if case:
            # 从 theory_refs 提取
            for ref in case.get("theory_refs") or []:
                if ref.get("type") and ref.get("ref"):
                    theory_sources.append(ref)
            # 从 evidence_chain 提取
            ec = case.get("evidence_chain") or {}
            for key in ("strategy_refs", "constraint_refs"):
                for ref in ec.get(key) or []:
                    if ref.get("type") and ref.get("ref"):
                        theory_sources.append(ref)

    # 合并外部知识引用
    if knowledge_refs:
        theory_sources.extend(knowledge_refs)

    # 去重 (按 ref 字符串)
    seen = set()
    deduped = []
    for ref in theory_sources:
        rk = ref.get("ref", "")
        if rk not in seen:
            seen.add(rk)
            deduped.append(ref)

    pt["theory_refs"] = deduped
    return distill


def step_hypothesis(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 4: 假设 — 基于矛盾分析、现状、理论生成假设。

    综合 intent + investigation + theory_refs 推导可验证假设。
    """
    pt = distill["process_trace"]
    claim = distill.get("claim", "")
    investigation = pt.get("investigation") or ""
    theory_count = len(pt.get("theory_refs") or [])

    hypothesis_parts = []
    hypothesis_parts.append(f"Core claim: {claim}")
    if investigation:
        hypothesis_parts.append(f"Context: {investigation[:200]}")
    if theory_count > 0:
        hypothesis_parts.append(f"Supported by {theory_count} theory references")

    pt["hypothesis"] = " | ".join(hypothesis_parts)
    return distill


def step_test(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 5: 测试与观测 — 验证假设，搜集数据。

    从 thinking_chain 的 A3(simulation) / A4(validation) / A6(intelligence)
    阶段提取测试证据。
    """
    pt = distill["process_trace"]
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if not case_id:
        pt["test_results"] = "No case available for testing"
        return distill

    case = _load_case_by_id(case_id)
    if not case:
        pt["test_results"] = f"Case {case_id} not found"
        return distill

    chain = case.get("thinking_chain") or []
    test_evidence = []
    for entry in chain:
        stage = entry.get("stage")
        if stage in ("A3", "A4", "A6"):
            ev = {
                "stage": stage,
                "decision": entry.get("decision"),
                "test_result": entry.get("test_result"),
            }
            test_evidence.append(ev)

    # 从 decision_outcome 提取实际结果
    do = case.get("decision_outcome") or {}
    pnl = do.get("pnl_pct")
    drawdown = do.get("drawdown")
    goal = do.get("goal_achieved")

    parts = []
    if test_evidence:
        for te in test_evidence:
            parts.append(f"[{te['stage']}] result={te.get('test_result', te.get('decision', 'N/A'))}")
    if pnl is not None:
        parts.append(f"pnl={pnl}%")
    if drawdown is not None:
        parts.append(f"drawdown={drawdown}")
    if goal is not None:
        parts.append(f"goal_achieved={goal}")

    pt["test_results"] = " | ".join(parts) if parts else "No test data available"
    return distill


def step_conclusion(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 6: 结论 — 根据假设与实际表现推导正确结果。

    综合 hypothesis + test_results + review lessons 生成结论。
    """
    pt = distill["process_trace"]
    hypothesis = pt.get("hypothesis") or ""
    test_results = pt.get("test_results") or ""

    # 从 case review 提取 lessons
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    lessons = []
    if case_id:
        case = _load_case_by_id(case_id)
        if case:
            review = _load_case_review(case)
            for l in review.get("successes", []):
                if l.get("what"):
                    lessons.append(f"Success: {l['what']}")
            for m in review.get("mistakes", []):
                if m.get("what"):
                    lessons.append(f"Failure: {m['what']}")

    parts = []
    if hypothesis:
        parts.append(f"Hypothesis: {hypothesis[:200]}")
    if test_results:
        parts.append(f"Test results: {test_results}")
    if lessons:
        parts.append(f"Lessons: {'; '.join(lessons[:5])}")

    pt["conclusion"] = " | ".join(parts) if parts else "No conclusion data available"
    return distill


def step_implementation(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 7: 落地 — 实施方案。

    从 successes 和 lessons 中提取可落地的规则。
    """
    pt = distill["process_trace"]
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if not case_id:
        pt["implementation"] = "No case available for implementation"
        return distill

    case = _load_case_by_id(case_id)
    if not case:
        pt["implementation"] = f"Case {case_id} not found"
        return distill

    review = _load_case_review(case)
    rules = []
    for s in review.get("successes", []):
        w = s.get("what", "")
        why = s.get("why", "")
        if w:
            rule = f"Do: {w}"
            if why:
                rule += f" (reason: {why})"
            rules.append(rule)
    for m in review.get("mistakes", []):
        w = m.get("what", "")
        why = m.get("why", "")
        if w:
            rule = f"Avoid: {w}"
            if why:
                rule += f" (cause: {why})"
            rules.append(rule)

    pt["implementation"] = " | ".join(rules[:5]) if rules else "No implementation rules derived"
    return distill


def step_monitoring(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 8: 监控 — 监控结果。

    基于 case 的 regime 和 quadrant 定义监控条件。
    """
    pt = distill["process_trace"]
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if not case_id:
        pt["monitoring"] = "No case available for monitoring"
        return distill

    case = _load_case_by_id(case_id)
    if not case:
        pt["monitoring"] = f"Case {case_id} not found"
        return distill

    regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")
    q = case.get("quadrant") or {}
    x, y = q.get("x", 0), q.get("y", 0)
    do = case.get("decision_outcome") or {}
    pnl = do.get("pnl_pct")

    parts = []
    parts.append(f"Monitor regime={regime}")
    parts.append(f"quadrant x={x} y={y}")
    if pnl is not None:
        parts.append(f"pnl threshold: alert if pnl < {min(0, pnl - 2)}%")

    pt["monitoring"] = " | ".join(parts)
    return distill


def step_review(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 9: 复盘 — 理论与实践一致性检验。

    综合 review 的 theory_practice_consistency + A8 验证结果。
    """
    pt = distill["process_trace"]
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if not case_id:
        pt["review_result"] = "No case available for review"
        return distill

    case = _load_case_by_id(case_id)
    if not case:
        pt["review_result"] = f"Case {case_id} not found"
        return distill

    review = _load_case_review(case)
    consistency = review.get("consistency", "partially_consistent")
    mistakes_count = len(review.get("mistakes", []))
    successes_count = len(review.get("successes", []))

    # 从 thinking_chain A8 提取理论验证
    chain = case.get("thinking_chain") or []
    a8_result = None
    for entry in chain:
        if entry.get("stage") == "A8":
            a8_result = entry.get("decision") or entry.get("test_result")
            break

    parts = []
    parts.append(f"Consistency: {consistency}")
    parts.append(f"Mistakes: {mistakes_count}, Successes: {successes_count}")
    if a8_result:
        parts.append(f"A8 verification: {a8_result}")

    pt["review_result"] = " | ".join(parts)
    return distill


def step_reflection(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 10: 做梦 — 外部反思。

    跨案例模式反思：检查同类 pattern 在其他 case 中的表现。
    """
    pt = distill["process_trace"]
    kind = distill.get("kind", "unknown")

    # 简单跨案例统计
    cases_dir = memory_l4_cases_dir()
    if not cases_dir.exists():
        pt["reflection"] = "No other cases available for cross-case reflection"
        return distill

    same_kind_count = 0
    total_count = 0
    for p in sorted(cases_dir.glob("*.json")):
        try:
            c = _load_json(p)
            total_count += 1
            # 检查是否有类似 pattern
            rev = c.get("review") or {}
            if rev.get("mistakes") and kind == "risk_signal":
                same_kind_count += 1
            elif rev.get("successes") and kind == "benefit_experience":
                same_kind_count += 1
        except Exception:
            continue

    pt["reflection"] = (
        f"Cross-case reflection: {same_kind_count}/{total_count} cases share "
        f"similar {kind} pattern"
    )
    return distill


def step_optimization(distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 11: 更新优化 — 最终优化方案。

    综合前面所有步骤的产出，生成最终优化建议。
    """
    pt = distill["process_trace"]
    conclusion = pt.get("conclusion") or ""
    implementation = pt.get("implementation") or ""
    review_result = pt.get("review_result") or ""

    parts = []
    if conclusion:
        parts.append(f"Conclusion: {conclusion[:200]}")
    if implementation:
        parts.append(f"Implementation: {implementation[:200]}")
    if review_result:
        parts.append(f"Review: {review_result}")

    # 生成 actionable_rules 并同步到顶层
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if case_id:
        case = _load_case_by_id(case_id)
        if case:
            review = _load_case_review(case)
            rules = []
            for s in review.get("successes", []):
                if s.get("what"):
                    rules.append(s["what"])
            distill["actionable_rules"] = rules[:5]
            # 同步到 how_to_apply
            distill["how_to_apply"]["actionable_rules"] = rules[:5]

    pt["optimization"] = " | ".join(parts) if parts else "No optimization data available"
    return distill


# ── 三问逻辑 ──

def answer_what_is_it(distill: Dict[str, Any]) -> Dict[str, Any]:
    """回答"是什么" — 基于 process_trace 生成定义。

    从 intent + investigation 中提取核心定义和分类。
    """
    d = dict(distill)
    wi = d.get("what_is_it") or {}
    pt = d.get("process_trace") or {}

    # claim 已经在 init 时设置
    intent = pt.get("intent") or ""
    investigation = pt.get("investigation") or ""

    # 从 intent 和 investigation 生成定义
    definition_parts = []
    if intent:
        definition_parts.append(f"Problem: {intent[:150]}")
    if investigation:
        definition_parts.append(f"Context: {investigation[:150]}")

    kind = d.get("kind", "unknown")
    classification = [kind]
    # 从 theory_refs 补充分类
    for ref in pt.get("theory_refs") or []:
        if ref.get("type") == "note" and ref.get("ref"):
            classification.append(ref["ref"][:50])

    wi["claim"] = d.get("claim", "")
    wi["definition"] = " | ".join(definition_parts) if definition_parts else None
    wi["classification"] = classification[:5]
    d["what_is_it"] = wi
    return d


def answer_why_it_works(distill: Dict[str, Any]) -> Dict[str, Any]:
    """回答"为什么" — 构建因果分析 + 理论基础 + 证据链。"""
    d = dict(distill)
    ww = d.get("why_it_works") or {}
    pt = d.get("process_trace") or {}
    case_id = d["supporting_case_ids"][0] if d.get("supporting_case_ids") else None

    # 因果分析: hypothesis + test_results → conclusion
    hypothesis = pt.get("hypothesis") or ""
    test_results = pt.get("test_results") or ""
    conclusion = pt.get("conclusion") or ""
    causal_parts = []
    if hypothesis:
        causal_parts.append(f"Based on: {hypothesis[:150]}")
    if test_results:
        causal_parts.append(f"Observed: {test_results[:150]}")
    if conclusion:
        causal_parts.append(f"Inferred: {conclusion[:150]}")
    ww["causal_analysis"] = " | ".join(causal_parts) if causal_parts else ""

    # 理论基础: theory_refs
    theory_refs = pt.get("theory_refs") or []
    ww["theory_basis"] = theory_refs[:10]

    # 证据链: supporting_case_ids + quadrant
    evidence_links = []
    for cid in d.get("supporting_case_ids") or []:
        evidence_links.append({
            "case_id": cid,
            "relevance": "direct_support",
            "weight": 1.0,
        })
    ww["evidence_chain"] = evidence_links

    # 解决的矛盾: 从 investigation 提取
    investigation = pt.get("investigation") or ""
    if "Contradictions" in investigation:
        ww["contradiction_resolved"] = investigation.split("Contradictions: ")[-1].split(" | ")[0]

    d["why_it_works"] = ww
    return d


def answer_how_to_apply(distill: Dict[str, Any]) -> Dict[str, Any]:
    """回答"怎么做" — 生成 actionable_rules + trigger_conditions + step_by_step + risk_warnings。"""
    d = dict(distill)
    ha = d.get("how_to_apply") or {}
    pt = d.get("process_trace") or {}
    case_id = d["supporting_case_ids"][0] if d.get("supporting_case_ids") else None

    # 可操作规则 (已从 step_optimization 同步)
    rules = d.get("actionable_rules", [])
    ha["actionable_rules"] = rules[:10]

    # 触发条件: 从 case regime + monitoring 提取
    trigger_conditions = []
    if case_id:
        case = _load_case_by_id(case_id)
        if case:
            regime = (case.get("environment_snapshot") or {}).get("regime")
            if regime:
                trigger_conditions.append({
                    "condition": f"regime matches '{regime}'",
                    "regime": regime,
                    "severity": None,
                })
            # 从 pnl 提取阈值
            do = case.get("decision_outcome") or {}
            pnl = do.get("pnl_pct")
            if pnl is not None:
                trigger_conditions.append({
                    "condition": f"pnl threshold at {pnl}%",
                    "regime": regime,
                    "severity": min(1.0, abs(pnl) / 10.0),
                })
    ha["trigger_conditions"] = trigger_conditions

    # 逐步操作指南: 从 implementation 提取
    impl = pt.get("implementation") or ""
    if impl:
        steps = [s.strip() for s in impl.split("|") if s.strip()]
        ha["step_by_step"] = steps[:5]

    # 风险警告: 从 mistakes 和 risk_warnings 提取
    risk_warnings = []
    if case_id:
        case = _load_case_by_id(case_id)
        if case:
            review = _load_case_review(case)
            for m in review.get("mistakes", []):
                w = m.get("what", "")
                why = m.get("why", "")
                if w:
                    warning = f"Risk: {w}"
                    if why:
                        warning += f" — caused by: {why}"
                    risk_warnings.append(warning)
    ha["risk_warnings"] = risk_warnings[:5]

    d["how_to_apply"] = ha
    return d


def compute_distill_quadrant(distill: Dict[str, Any], case_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """计算蒸馏象限坐标 (x, y)。

    y_perf: 基于 case pnl 和 review lessons 数量
    y_consistency: 基于 review theory_practice_consistency
    y_human: 基于是否有 review_record_id (人工干预痕迹)
    x: 基于 quadrant x 从 case 继承

    Args:
        distill: 蒸馏记录
        case_data: 可选，直接传入 case 数据（避免从磁盘加载）
    """
    case_id = distill["supporting_case_ids"][0] if distill.get("supporting_case_ids") else None
    if not case_id:
        return distill["quadrant"]

    if case_data is None:
        case_data = _load_case_by_id(case_id)
    if case_data is None:
        return distill["quadrant"]

    q = distill.get("quadrant") or {}
    ev = q.get("evidence") or {}

    # x: 从 case quadrant 继承
    case_q = case_data.get("quadrant") or {}
    x = case_q.get("x", 0.0)

    # y_perf: 基于 pnl 归一化
    do = case_data.get("decision_outcome") or {}
    pnl = do.get("pnl_pct")
    if pnl is not None:
        y_perf = max(0, min(1, (pnl + 5) / 10))  # -5%→0, +5%→1
    else:
        y_perf = 0.5

    # y_consistency: 基于 review consistency
    review = _load_case_review(case_data)
    consistency = review.get("consistency", "partially_consistent")
    y_consistency = (
        0.9 if consistency == "consistent"
        else 0.5 if consistency == "partially_consistent"
        else 0.1
    )

    # y_human: 有 review_record_id → 人工干预 → 高置信
    y_human = 0.8 if review.get("review_record_id") else 0.3

    # 加权 y
    y = 0.4 * y_perf + 0.4 * y_consistency + 0.2 * y_human

    q["x"] = round(max(-1, min(1, x)), 4)
    q["y"] = round(max(0, min(1, y)), 4)
    ev["y_perf"] = round(y_perf, 4)
    ev["y_consistency"] = round(y_consistency, 4)
    ev["y_human"] = round(y_human, 4)
    ev["notes"] = f"Computed by distill_engine v0.2 for {case_id}"
    q["evidence"] = ev
    distill["quadrant"] = q
    return q


# ── 完整流程 ──

def complete_distill(distill: Dict[str, Any], case_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """完成蒸馏 — 触发 11 步 + 三问 + 象限计算。

    这是完整流程的统一入口，按顺序执行所有阶段。

    Args:
        distill: 蒸馏记录
        case_data: 可选，TradeCase 数据（避免磁盘加载）
    """
    d = dict(distill)

    # 三问
    d = answer_what_is_it(d)
    d = answer_why_it_works(d)
    d = answer_how_to_apply(d)

    # 象限计算
    compute_distill_quadrant(d, case_data=case_data)

    return d


def run_full_distill_pipeline(
    review_record: Dict[str, Any],
    kind: str = "risk_signal",
) -> Dict[str, Any]:
    """一键完成从 ReviewRecord 到 DistillRecord 的完整流程。

    Args:
        review_record: ReviewRecord 数据
        kind: 蒸馏类型

    Returns:
        完整的 DistillRecord 字典
    """
    # 0. 尝试加载关联 case
    case_id = review_record.get("case_id")
    case_data = _load_case_by_id(case_id) if case_id else None

    # 1. 初始化
    distill = init_distill(review_record, kind=kind)

    # 2. 执行 11 步
    distill = step_intent(distill, review_record)
    distill = step_investigation(distill)
    distill = step_theory(distill)
    distill = step_hypothesis(distill)
    distill = step_test(distill)
    distill = step_conclusion(distill)
    distill = step_implementation(distill)
    distill = step_monitoring(distill)
    distill = step_review(distill)
    distill = step_reflection(distill)
    distill = step_optimization(distill)

    # 3. 三问 + 象限 (传入 case_data 避免重复加载)
    distill = complete_distill(distill, case_data=case_data)

    return distill


def save_distill(distill: Dict[str, Any], out_path: Optional[Path] = None) -> Path:
    """保存蒸馏记录到文件。"""
    did = distill.get("distill_id", "unknown")
    target = out_path or (memory_l4_distills_dir() / f"{did}.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(distill, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target
