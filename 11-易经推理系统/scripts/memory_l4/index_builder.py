import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_cases_dir, memory_l4_distills_dir, workbuddy_dir


DEFAULT_WEIGHTS = {"struct": 0.4, "num": 0.4, "strategy": 0.2}


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def list_json_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def load_cases() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in list_json_files(memory_l4_cases_dir()):
        out.append(load_json(p))
    return out


def load_distills() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in list_json_files(memory_l4_distills_dir()):
        out.append(load_json(p))
    return out


def _safe_get(d: Dict[str, Any], keys: List[str]) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


def _extract_episode_ref_path(case: Dict[str, Any]) -> Optional[str]:
    ex = case.get("execution") or {}
    refs = ex.get("episode_refs") or []
    if not refs:
        return None
    p = refs[0].get("path")
    return str(p) if p else None


def _read_episode_by_ref(episode_ref_path: Optional[str]) -> Dict[str, Any]:
    if not episode_ref_path:
        return {}
    p = Path(episode_ref_path)
    if not p.is_absolute():
        p = _ROOT / p
    if not p.exists():
        return {}
    try:
        return load_json(p)
    except Exception:
        return {}


def _extract_thinking_chain_features(case: Dict[str, Any]) -> Dict[str, Any]:
    """从 thinking_chain 提取特征 (v0.2 新增)。"""
    chain = case.get("thinking_chain") or []
    stage_map: Dict[str, Dict[str, Any]] = {}
    for entry in chain:
        s = entry.get("stage")
        if s:
            stage_map[s] = entry
    stages_present = sorted(stage_map.keys())

    # 决策类型统计
    decisions = []
    for s in chain:
        d = s.get("decision")
        if d:
            decisions.append(str(d))

    # 矛盾分析标记
    has_contradiction = "A0" in stage_map and stage_map["A0"].get("contradiction")
    has_theory_verify = "A8" in stage_map

    return {
        "stages_present": stages_present,
        "stages_count": len(stages_present),
        "stage_coverage_pct": round(len(stages_present) / 10.0 * 100, 1),
        "decision_count": len(decisions),
        "has_contradiction_analysis": bool(has_contradiction),
        "has_theory_verification": has_theory_verify,
        "chain_order": stages_present,
    }


def _extract_evidence_chain_features(case: Dict[str, Any]) -> Dict[str, Any]:
    """从 evidence_chain 提取特征 (v0.2 新增)。"""
    ec = case.get("evidence_chain") or {}
    return {
        "market_data_count": len(ec.get("market_data_refs") or []),
        "signal_count": len(ec.get("signal_refs") or []),
        "strategy_count": len(ec.get("strategy_refs") or []),
        "historical_count": len(ec.get("historical_refs") or []),
        "constraint_count": len(ec.get("constraint_refs") or []),
        "total_refs": sum(len(ec.get(k) or []) for k in
                          ("market_data_refs", "signal_refs", "strategy_refs",
                           "historical_refs", "constraint_refs")),
    }


def _extract_decision_outcome_features(case: Dict[str, Any]) -> Dict[str, Any]:
    """从 decision_outcome 提取特征 (v0.2 新增)。"""
    do = case.get("decision_outcome") or {}
    pnl = do.get("pnl_pct")
    return {
        "pnl_pct": pnl,
        "pnl_usdt": do.get("pnl_usdt"),
        "drawdown": do.get("drawdown"),
        "exit_reason": do.get("exit_reason"),
        "goal_achieved": do.get("goal_achieved"),
        "is_profit": bool(pnl and pnl > 0),
    }


def _extract_quadrant_features(case: Dict[str, Any]) -> Dict[str, Any]:
    """从 quadrant 提取特征 (v0.2 新增)。"""
    q = case.get("quadrant") or {}
    ev = q.get("evidence") or {}
    return {
        "x": q.get("x", 0),
        "y": q.get("y", 0),
        "y_perf": ev.get("y_perf", 0),
        "y_consistency": ev.get("y_consistency", 0),
        "y_human": ev.get("y_human", 0),
        "quadrant_label": _quadrant_label(q.get("x", 0), q.get("y", 0)),
    }


def _quadrant_label(x: float, y: float) -> str:
    """象限标签：x=benefit/harm, y=certainty。"""
    x_side = "benefit" if x > 0 else "harm" if x < 0 else "neutral"
    y_level = "high" if y > 0.7 else "low" if y < 0.3 else "medium"
    return f"{x_side}_{y_level}_certainty"


def _case_review_lessons(case: Dict[str, Any], limit: int = 3) -> List[str]:
    """提取 case 复盘经验教训摘要（原始 v0.1 逻辑）。"""
    review = case.get("review") or {}
    lessons = review.get("lessons") or []
    out = [str(x) for x in lessons if str(x)]
    if out:
        return out[:limit]
    summary = str(review.get("summary") or "").strip()
    if not summary:
        return []
    parts = [p.strip() for p in summary.replace("。", ".").split(".") if p.strip()]
    return parts[:limit]


def _case_review_detailed(case: Dict[str, Any]) -> Dict[str, Any]:
    """提取复盘详细特征 (v0.2 新增)。"""
    review = case.get("review") or {}
    mistakes = review.get("mistakes") or []
    successes = review.get("successes") or []
    return {
        "mistakes_count": len(mistakes),
        "successes_count": len(successes),
        "consistency": review.get("theory_practice_consistency"),
        "review_record_id": review.get("review_record_id"),
        "lessons": _case_review_lessons(case),
        "avg_mistake_severity": round(
            sum(m.get("severity") or 0 for m in mistakes) / len(mistakes), 3
        ) if mistakes else None,
    }


def _build_index_summary(
    case_features: Dict[str, Any],
    distills: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """构建索引全局摘要 (v0.2 新增)。"""
    total = len(case_features)
    if total == 0:
        return {"total_cases": 0, "v02_ratio": 0, "stage_coverage": {}, "l4_status": {}, "quadrant_center": {}}

    # v0.2 占比
    v02_count = sum(1 for f in case_features.values() if f.get("version") == "v0.2")

    # A0-A9 阶段覆盖率聚合
    stage_totals = {f"A{i}": 0 for i in range(10)}
    for f in case_features.values():
        tc = f.get("thinking_chain") or {}
        for s in tc.get("stages_present") or []:
            if s in stage_totals:
                stage_totals[s] += 1
    stage_rates = {s: round(v / total, 3) for s, v in stage_totals.items()}

    # L4 状态分布
    status_counts: Dict[str, int] = {}
    for f in case_features.values():
        st = f.get("l4_status") or "UNKNOWN"
        status_counts[st] = status_counts.get(st, 0) + 1

    # 象限重心
    xs = [f.get("quadrant_features", {}).get("x", 0) for f in case_features.values()]
    ys = [f.get("quadrant_features", {}).get("y", 0) for f in case_features.values()]

    return {
        "total_cases": total,
        "v02_count": v02_count,
        "v02_ratio": round(v02_count / total, 3),
        "stage_coverage": {"counts": stage_totals, "rates": stage_rates},
        "l4_status_distribution": status_counts,
        "quadrant_center": {
            "x_mean": round(sum(xs) / total, 3),
            "y_mean": round(sum(ys) / total, 3),
        },
        "distill_count": len(distills),
    }


def build_index_data(
    snapshot_ts: str,
    cases: List[Dict[str, Any]],
    distills: List[Dict[str, Any]],
    episodes_by_path: Dict[str, Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None
) -> Dict[str, Any]:
    w = weights or DEFAULT_WEIGHTS

    case_features: Dict[str, Any] = {}
    for c in cases:
        cid = str(c.get("case_id") or "")
        if not cid:
            continue

        env = c.get("environment_snapshot") or {}
        regime = env.get("regime")

        episode_path = _extract_episode_ref_path(c)
        ep = episodes_by_path.get(episode_path or "", {})

        decision = ep.get("decision")
        reason_codes = ep.get("reason_codes") or []
        edge = ep.get("edge")
        total_score = ep.get("total_score")
        scores = ep.get("scores") or {}

        directive = _safe_get(ep, ["strategy_result", "strategy_directive"]) or {}
        matched_strategy = directive.get("matched_strategy")
        category = directive.get("category")
        directive_bias = directive.get("directive_bias")

        case_features[cid] = {
            "inst_id": c.get("inst_id"),
            "regime": regime,
            "decision": decision,
            "reason_codes": [str(x) for x in reason_codes if str(x)],
            "tags": [str(x) for x in (c.get("tags") or []) if str(x)],
            "scores": scores,
            "total_score": total_score,
            "edge": edge,
            "matched_strategy": matched_strategy,
            "category": category,
            "directive_bias": directive_bias,
            "references": {"case_lessons": _case_review_lessons(c, limit=3)},
            # v0.2 新增特征
            "l4_status": c.get("l4_status"),
            "version": c.get("version"),
            "thinking_chain": _extract_thinking_chain_features(c),
            "evidence_chain": _extract_evidence_chain_features(c),
            "decision_outcome": _extract_decision_outcome_features(c),
            "quadrant_features": _extract_quadrant_features(c),
            "review_detailed": _case_review_detailed(c),
        }

    # v0.2 新增: 全局汇总摘要
    summary = _build_index_summary(case_features, distills)

    distill_features: Dict[str, Any] = {}
    for d in distills:
        did = str(d.get("distill_id") or "")
        if not did:
            continue
        distill_features[did] = {
            "kind": d.get("kind"),
            "claim": str(d.get("claim") or "").strip(),
            "actionable_rules": [str(x) for x in (d.get("actionable_rules") or []) if str(x)],
            "supporting_case_ids": [str(x) for x in (d.get("supporting_case_ids") or []) if str(x)]
        }

    return {
        "metadata": {
            "snapshot_ts": snapshot_ts,
            "feature_version": "v0.2",
            "weights": {"struct": float(w["struct"]), "num": float(w["num"]), "strategy": float(w["strategy"])}
        },
        "summary": summary,
        "case_features": case_features,
        "distill_features": distill_features
    }


def load_episodes_for_cases(cases: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in cases:
        p = _extract_episode_ref_path(c)
        if not p:
            continue
        out[str(p)] = _read_episode_by_ref(p)
    return out


def default_index_path() -> Path:
    return workbuddy_dir() / "memory_l4" / "index" / "latest.json"


def write_index(index_data: Dict[str, Any], out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=False)
    args = parser.parse_args()

    cases = load_cases()
    distills = load_distills()
    episodes = load_episodes_for_cases(cases)
    data = build_index_data(now_iso_local(), cases, distills, episodes_by_path=episodes)

    out_path = Path(args.out) if args.out else default_index_path()
    written = write_index(data, out_path)
    print(str(written))


if __name__ == "__main__":
    main()

