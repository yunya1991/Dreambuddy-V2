"""复盘引擎模块 — 对错双向分析。

连接 L1 TradeCase 与 L4 Distill 的桥梁。
消费 TradeCase + Episode + A7/A8 报告，产出 ReviewRecord。

v0.2 新增模块 — Phase 2 (P1)
"""

import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_reviews_dir,
    workspace_root,
)


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def _extract_pnl(episode: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    out = episode.get("outcome") or {}
    pnl_pct = out.get("realized_pnl_pct")
    if pnl_pct is None:
        pnl_pct = out.get("unrealized_pnl_pct")
    pnl_usdt = out.get("realized_pnl_usdt")
    if pnl_usdt is None:
        pnl_usdt = out.get("unrealized_pnl_usdt")
    return (
        float(pnl_pct) if pnl_pct is not None else None,
        float(pnl_usdt) if pnl_usdt is not None else None,
    )


def _extract_episode_path(case: Dict[str, Any]) -> str:
    refs = ((case.get("execution") or {}).get("episode_refs") or [])
    if not refs:
        return ""
    return str((refs[0] or {}).get("path") or "")


def _read_episode(case: Dict[str, Any]) -> Dict[str, Any]:
    raw = _extract_episode_path(case)
    if not raw:
        return {}
    p = Path(raw)
    if not p.is_absolute():
        p = _ROOT / p
    if not p.exists():
        return {}
    try:
        return _load_json(p)
    except Exception:
        return {}


def analyze_success(
    case: Dict[str, Any],
    episode: Dict[str, Any],
) -> Dict[str, Any]:
    """成功案例分析 → 成功经验。

    Args:
        case: TradeCase 数据
        episode: Episode 数据

    Returns:
        成功分析结果
    """
    pnl_pct, pnl_usdt = _extract_pnl(episode)

    # 提取 thinking_chain 中的关键阶段
    thinking_chain = case.get("thinking_chain") or []
    key_decisions = []
    for stage in thinking_chain:
        if stage.get("decision"):
            key_decisions.append({
                "stage": stage["stage"],
                "decision": stage["decision"],
                "rationale": stage.get("rationale"),
            })

    regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")

    return {
        "case_id": case["case_id"],
        "direction": "success",
        "pnl_pct": pnl_pct,
        "pnl_usdt": pnl_usdt,
        "regime": regime,
        "key_decisions": key_decisions,
        "thinking_chain_length": len(thinking_chain),
    }


def analyze_failure(
    case: Dict[str, Any],
    episode: Dict[str, Any],
) -> Dict[str, Any]:
    """失败案例分析 → 风险信号。

    复用 failure_analyzer 的分组逻辑但输出到统一分析格式。

    Args:
        case: TradeCase 数据
        episode: Episode 数据

    Returns:
        失败分析结果
    """
    pnl_pct, pnl_usdt = _extract_pnl(episode)

    # 提取退出原因
    out = episode.get("outcome") or {}
    exit_reason = str(out.get("exit_reason") or out.get("stop_reason") or "unknown")

    regime = (case.get("environment_snapshot") or {}).get("regime", "unknown")

    thinking_chain = case.get("thinking_chain") or []
    stages_covered = [s.get("stage") for s in thinking_chain if s.get("stage")]

    return {
        "case_id": case["case_id"],
        "direction": "failure",
        "pnl_pct": pnl_pct,
        "pnl_usdt": pnl_usdt,
        "regime": regime,
        "exit_reason": exit_reason,
        "stages_covered": stages_covered,
    }


def build_review_record(
    case: Dict[str, Any],
    analysis: Dict[str, Any],
    a7_report: Optional[Dict[str, Any]] = None,
    a8_report: Optional[Dict[str, Any]] = None,
    snapshot_ts: Optional[str] = None,
) -> Dict[str, Any]:
    """构建 ReviewRecord。

    Args:
        case: TradeCase 数据
        analysis: analyze_success/analyze_failure 的返回值
        a7_report: A7 实践理论报告 (可选)
        a8_report: A8 理论验证报告 (可选)
        snapshot_ts: 复盘时间戳

    Returns:
        ReviewRecord 字典
    """
    ts = snapshot_ts or now_iso_local()
    case_id = case.get("case_id", "unknown")
    review_id = f"REV_{ts.replace(':', '').replace('-', '').replace('+', '')[:15]}_{case_id}"

    pnl_pct = analysis.get("pnl_pct")
    direction = analysis.get("direction", "mixed")

    # 构建 mistakes/successes
    mistakes: List[Dict[str, Any]] = []
    successes: List[Dict[str, Any]] = []

    if direction == "failure":
        mistakes.append({
            "what": f"交易亏损 {pnl_pct}%",
            "why": analysis.get("exit_reason", "待分析"),
            "severity": min(1.0, abs(pnl_pct or 0) / 5.0) if pnl_pct is not None else None,
            "stage_ref": None,
            "theory_gap": "待理论与实践验证",
        })
    elif direction == "success":
        successes.append({
            "what": f"交易盈利 {pnl_pct}%",
            "why": "待理论与实践验证",
            "severity": None,
            "stage_ref": None,
            "theory_gap": None,
            "reproducible": None,
        })

    # A8 理论一致性
    review_raw = case.get("review") or {}
    consistency_str = review_raw.get("theory_practice_consistency", "partially_consistent")

    record: Dict[str, Any] = {
        "review_id": review_id,
        "version": "v0.1",
        "snapshot_ts": ts,
        "case_id": case_id,
        "direction": direction,
        "mistakes": mistakes,
        "successes": successes,
        "theory_practice_analysis": {
            "consistency_score": (
                0.9 if consistency_str == "consistent"
                else 0.5 if consistency_str == "partially_consistent"
                else 0.1
            ),
            "confirmed_theories": [],
            "contradicted_theories": [],
            "gap_analysis": None,
        },
        "distill_proposals": [],
        "quadrant": case.get("quadrant", {"x": 0.0, "y": 0.0, "evidence": {}}),
        "a7_report_ref": None,
        "a8_report_ref": None,
    }

    # 合并 A7/A8 报告 (如果有)
    if a7_report:
        record["a7_report_ref"] = "a7_report_pending"
    if a8_report:
        record["a8_report_ref"] = "a8_report_pending"

    return record


def run_review(
    snapshot_ts: Optional[str] = None,
    cases: Optional[List[Dict[str, Any]]] = None,
    episodes_by_case_id: Optional[Dict[str, Dict[str, Any]]] = None,
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """批量复盘。

    Args:
        snapshot_ts: 复盘时间戳
        cases: TradeCase 列表，默认加载全部
        episodes_by_case_id: {case_id: episode} 字典，默认自动加载
        output_dir: 输出目录

    Returns:
        复盘结果摘要
    """
    ts = snapshot_ts or now_iso_local()

    if cases is None:
        cases = [_load_json(p) for p in _list_json(memory_l4_cases_dir())]

    if episodes_by_case_id is None:
        episodes_by_case_id = {}
        for c in cases:
            cid = c.get("case_id", "")
            if cid:
                episodes_by_case_id[cid] = _read_episode(c)

    reviews: List[Dict[str, Any]] = []
    success_count = 0
    failure_count = 0
    mixed_count = 0

    for case in cases:
        cid = case.get("case_id", "")
        episode = episodes_by_case_id.get(cid, {})
        pnl_pct, _ = _extract_pnl(episode)

        if pnl_pct is None:
            continue

        if pnl_pct > 0:
            analysis = analyze_success(case, episode)
            success_count += 1
        else:
            analysis = analyze_failure(case, episode)
            failure_count += 1

        record = build_review_record(case, analysis, snapshot_ts=ts)
        reviews.append(record)

    # 保存
    out_dir = output_dir or memory_l4_reviews_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    for record in reviews:
        path = out_dir / f"{record['review_id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "snapshot_ts": ts,
        "total_reviews": len(reviews),
        "success_count": success_count,
        "failure_count": failure_count,
        "mixed_count": mixed_count,
        "output_dir": str(out_dir),
    }
