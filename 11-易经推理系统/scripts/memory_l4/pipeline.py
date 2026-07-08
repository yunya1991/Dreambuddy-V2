"""L4 记忆全链路串联管道 — P0 端到端流程。

流程: event ingestion → case registration → A0-A9 bridge → review → distill → stats → candidate

入口函数: run_pipeline(episode_path) 从单个 episode 文件触发完整 L4 闭环。

v0.2 新增模块 — Phase P0
"""

import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import (
    memory_l4_cases_dir,
    memory_l4_reviews_dir,
    memory_l4_distills_dir,
    memory_l4_stats_dir,
    workspace_root,
)
from scripts.memory_l4 import case_registry
from scripts.memory_l4 import a0a9_bridge
from scripts.memory_l4 import review_engine
from scripts.memory_l4 import distill_engine
from scripts.memory_l4 import stats_engine
from scripts.memory_l4 import index_builder


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Pipeline steps
# ---------------------------------------------------------------------------

def step_register(episode_path: Path) -> Dict[str, Any]:
    """Step 1: 从 episode 注册 TradeCase (M0_CASE_REGISTERED)。"""
    case = case_registry.create_case_from_episode_file(episode_path)
    data = json.loads(case.read_text(encoding="utf-8"))
    cid = data["case_id"]
    assert data["version"] == "v0.2", f"expected v0.2, got {data['version']}"
    assert data["l4_status"] == "M0_CASE_REGISTERED"
    print(f"[M0] Registered TradeCase {cid}")
    return data


def step_a0a9(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Step 2: 收集 A0-A9 阶段数据并填充 thinking_chain。"""
    cid = case_data["case_id"]
    stage_outputs = a0a9_bridge.collect_stage_outputs(cid)
    if stage_outputs:
        chain = a0a9_bridge.build_thinking_chain_from_stages(stage_outputs)
        case_data["thinking_chain"] = chain
        case_registry.save_json(
            memory_l4_cases_dir() / f"{cid}.json", case_data
        )
        print(f"[A0-A9] Populated {len(chain)} stages: {[s['stage'] for s in chain]}")
    else:
        print(f"[A0-A9] No stage artifacts found for {cid}")
    return case_data


def step_review(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Step 3: 执行复盘，产出 ReviewRecord (M1_REVIEW_COMPLETED)。"""
    cid = case_data["case_id"]
    episode = _read_episode(case_data)

    pnl = (case_data.get("decision_outcome") or {}).get("pnl_pct")
    if pnl is None:
        pnl_val, _ = review_engine._extract_pnl(episode)
    else:
        pnl_val = pnl

    if pnl_val is not None and pnl_val > 0:
        analysis = review_engine.analyze_success(case_data, episode)
    else:
        analysis = review_engine.analyze_failure(case_data, episode)

    record = review_engine.build_review_record(case_data, analysis, snapshot_ts=now_iso_local())
    record["review_record_id"] = record["review_id"]

    # 保存 ReviewRecord
    memory_l4_reviews_dir().mkdir(parents=True, exist_ok=True)
    review_path = memory_l4_reviews_dir() / f"{record['review_id']}.json"
    review_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    # 更新 TradeCase review 字段
    case_data["review"]["summary"] = record.get("direction", "")
    case_data["review"]["mistakes"] = record.get("mistakes", [])
    case_data["review"]["successes"] = record.get("successes", [])
    case_data["review"]["review_record_id"] = record["review_id"]
    case_data["l4_status"] = "M1_REVIEW_COMPLETED"
    case_registry.save_json(memory_l4_cases_dir() / f"{cid}.json", case_data)

    print(f"[M1] Review completed: {record['review_id']} (direction={record['direction']})")
    return record


def step_distill(review_record: Dict[str, Any]) -> Dict[str, Any]:
    """Step 4: 执行蒸馏，产出 DistillRecord (M2_DISTILL_COMPLETED)。"""
    distill = distill_engine.init_distill(review_record)

    # 执行 11 步流程
    distill = distill_engine.step_intent(distill, review_record)
    distill = distill_engine.step_investigation(distill)
    distill = distill_engine.step_theory(distill)
    distill = distill_engine.step_hypothesis(distill)
    distill = distill_engine.step_test(distill)
    distill = distill_engine.step_conclusion(distill)
    distill = distill_engine.step_implementation(distill)
    distill = distill_engine.step_monitoring(distill)
    distill = distill_engine.step_review(distill)
    distill = distill_engine.step_reflection(distill)
    distill = distill_engine.step_optimization(distill)

    # 三问逻辑
    distill = distill_engine.complete_distill(distill)

    # 保存
    saved = distill_engine.save_distill(distill)
    distill_id = distill["distill_id"]

    # 更新关联 case
    cid = review_record.get("case_id", "")
    if cid:
        case_path = memory_l4_cases_dir() / f"{cid}.json"
        if case_path.exists():
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["l4_status"] = "M2_DISTILL_COMPLETED"
            case_registry.save_json(case_path, case)

    print(f"[M2] Distill completed: {distill_id}")
    return distill


def step_stats(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """Step 5: 更新全局统计 (M3_STATS_UPDATED)。"""
    stats = stats_engine.compute_full_stats(snapshot_ts=now_iso_local())
    saved = stats_engine.save_stats(stats)

    # 仅将当前 pipeline 的 case 推进到 M3
    cid = case_data.get("case_id")
    if cid:
        case_path = memory_l4_cases_dir() / f"{cid}.json"
        if case_path.exists():
            case = json.loads(case_path.read_text(encoding="utf-8"))
            if case.get("l4_status") in ("M0_CASE_REGISTERED", "M1_REVIEW_COMPLETED", "M2_DISTILL_COMPLETED"):
                case["l4_status"] = "M3_STATS_UPDATED"
                case_registry.save_json(case_path, case)

    print(f"[M3] Stats updated: {stats['snapshot_id']}")
    return stats


def step_rebuild_index() -> Dict[str, Any]:
    """Step 5.5: 重建 L4 索引 (M3.5_INDEX_REBUILT)。

    在所有 case 和 distill 数据更新后重建检索索引，
    确保 A 系列交易阶段能检索到最新记忆。
    """
    cases = index_builder.load_cases()
    distills = index_builder.load_distills()
    episodes = index_builder.load_episodes_for_cases(cases)

    data = index_builder.build_index_data(
        snapshot_ts=now_iso_local(),
        cases=cases,
        distills=distills,
        episodes_by_path=episodes,
    )
    out_path = index_builder.write_index(data, index_builder.default_index_path())

    print(f"[M3.5] Index rebuilt: {len(data['case_features'])} cases at {out_path}")
    return {"index_path": str(out_path), "case_count": len(data["case_features"])}


def step_emit_candidate(case_data: Dict[str, Any], review: Dict[str, Any], distill: Dict[str, Any]) -> Dict[str, Any]:
    """Step 6: 生成进化候选记录 (M4_CANDIDATE_EMITTED)。"""
    cid = case_data["case_id"]
    candidate = {
        "candidate_id": f"CAND_{cid}_{now_iso_local()[:10]}",
        "version": "v0.2",
        "created_ts": now_iso_local(),
        "case_id": cid,
        "review_record_id": review.get("review_record_id"),
        "distill_id": distill.get("distill_id"),
        "l4_status": "M4_CANDIDATE_EMITTED",
        "quadrant": case_data.get("quadrant"),
        "claim": distill.get("claim"),
        "actionable_rules": distill.get("actionable_rules", []),
        "evolution_status": "C0_COLLECTED",
    }

    # 写入进化候选目录
    artifacts_dir = workspace_root() / "artifacts" / "evolution" / "feedback"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    out = artifacts_dir / f"{candidate['candidate_id']}.json"
    out.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 更新 case 状态
    case_path = memory_l4_cases_dir() / f"{cid}.json"
    case_data["l4_status"] = "M4_CANDIDATE_EMITTED"
    case_registry.save_json(case_path, case_data)

    print(f"[M4] Candidate emitted: {candidate['candidate_id']}")
    return candidate


# ---------------------------------------------------------------------------
# Pipeline orchestrator
# ---------------------------------------------------------------------------

def run_pipeline(
    episode_path: Path,
    steps: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """执行 L4 全链路管道。

    Args:
        episode_path: episode JSON 文件路径
        steps: 要执行的步骤列表，默认全部
               可选: register, a0a9, review, distill, stats, emit

    Returns:
        包含各步骤产出的字典
    """
    all_steps = ["register", "a0a9", "review", "distill", "stats", "rebuild_index", "emit"]
    active_steps = steps or all_steps

    result: Dict[str, Any] = {"episode": str(episode_path), "steps_executed": []}

    if "register" in active_steps:
        case_data = step_register(episode_path)
        result["case"] = case_data
        result["steps_executed"].append("register")

    if "a0a9" in active_steps:
        case_data = step_a0a9(case_data)
        result["case"] = case_data
        result["steps_executed"].append("a0a9")

    if "review" in active_steps:
        review = step_review(case_data)
        result["review"] = review
        result["steps_executed"].append("review")

    if "distill" in active_steps:
        distill = step_distill(review)
        result["distill"] = distill
        result["steps_executed"].append("distill")

    if "stats" in active_steps:
        stats = step_stats(case_data)
        result["stats"] = stats
        result["steps_executed"].append("stats")

    if "rebuild_index" in active_steps:
        index_result = step_rebuild_index()
        result["index"] = index_result
        result["steps_executed"].append("rebuild_index")

    if "emit" in active_steps:
        candidate = step_emit_candidate(case_data, review, distill)
        result["candidate"] = candidate
        result["steps_executed"].append("emit")

    return result


def _read_episode(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """从 case 中读取 episode 数据。"""
    refs = ((case_data.get("execution") or {}).get("episode_refs") or [])
    if not refs:
        return {}
    raw = refs[0].get("path", "")
    if not raw:
        return {}
    p = Path(raw)
    if not p.is_absolute():
        p = _ROOT / p
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="L4 Memory Pipeline")
    parser.add_argument("--episode", required=True, help="Episode JSON file path")
    parser.add_argument(
        "--steps",
        nargs="*",
        default=None,
        help="Steps to run (default: all). Choices: register a0a9 review distill stats rebuild_index emit",
    )
    parser.add_argument("--out", help="Output result JSON file")
    args = parser.parse_args()

    episode = Path(args.episode)
    if not episode.exists():
        print(f"Error: episode file not found: {episode}", file=sys.stderr)
        sys.exit(1)

    result = run_pipeline(episode, steps=args.steps)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"\nResult saved to: {out}")
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
