import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_cases_dir, workspace_root


def _require_nonempty(value: str, field: str) -> str:
    if not value:
        raise ValueError(f"missing required field: {field}")
    return value


def create_case_from_episode_data(episode: Dict[str, Any], case_id: str) -> Dict[str, Any]:
    ts = _require_nonempty(str(episode.get("ts") or ""), "ts")
    inst_id = _require_nonempty(str(episode.get("inst_id") or ""), "inst_id")
    trace_id = _require_nonempty(str(episode.get("trace_id") or ""), "trace_id")

    pnl = episode.get("pnl_pct")
    pnl_usdt = episode.get("pnl_usdt")
    dd = episode.get("drawdown")

    return {
        "case_id": case_id,
        "version": "v0.2",
        "ts_start": ts,
        "ts_end": None,
        "inst_id": inst_id,
        "tags": ["auto_case", "episode_ref"],
        "intent": {"question": "", "goal": "", "constraints": []},
        "investigation": {"summary": "", "sources": []},
        "theory_refs": [],
        "environment_snapshot": {"regime": episode.get("regime", "")},
        "thinking_chain": [],
        "evidence_chain": {
            "market_data_refs": [],
            "signal_refs": [],
            "strategy_refs": [],
            "historical_refs": [],
            "constraint_refs": []
        },
        "decision_outcome": {
            "pnl_pct": float(pnl) if pnl is not None else None,
            "pnl_usdt": float(pnl_usdt) if pnl_usdt is not None else None,
            "drawdown": float(dd) if dd is not None else None,
            "exit_reason": None,
            "goal_achieved": None
        },
        "l4_status": "M0_CASE_REGISTERED",
        "plan": {
            "minimal_change": "",
            "max_future_space": "",
            "steps": ["补全意图/调查/复盘/象限坐标"]
        },
        "execution": {
            "episode_refs": [{"trace_id": trace_id, "path": ""}],
            "result": str(episode.get("status") or episode.get("decision") or "")
        },
        "online_pressure_test": None,
        "rollout_monitoring": None,
        "backtest": None,
        "review": {
            "summary": "",
            "theory_practice_consistency": "partially_consistent",
            "lessons": [],
            "mistakes": [],
            "successes": [],
            "review_record_id": None
        },
        "dream_reflection": None,
        "quadrant": {
            "x": 0.0,
            "y": 0.0,
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": 0.0,
                "y_consistency": 0.0,
                "y_human": 0.0,
                "notes": ""
            }
        }
    }


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def derive_case_id_from_episode_path(episode_path: Path) -> str:
    return f"TC_{episode_path.stem}"


def _to_repo_relative_path(path: Path) -> str:
    root = workspace_root()
    try:
        return str(path.resolve().relative_to(root.resolve()).as_posix())
    except Exception:
        return str(path.as_posix())


def create_case_from_episode_file(episode_path: Path, out_path: Optional[Path] = None) -> Path:
    episode = load_json(episode_path)
    case_id = derive_case_id_from_episode_path(episode_path)
    if out_path is None:
        out_path = memory_l4_cases_dir() / f"{case_id}.json"

    data = create_case_from_episode_data(episode, case_id=case_id)
    data["execution"]["episode_refs"][0]["path"] = _to_repo_relative_path(episode_path)

    save_json(out_path, data)
    return out_path


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--out", required=False)
    args = parser.parse_args()

    episode_path = Path(args.episode)
    out_path = Path(args.out) if args.out else None

    created = create_case_from_episode_file(episode_path, out_path=out_path)
    print(str(created))


# ---------------------------------------------------------------------------
# v0.2 field population helpers
# ---------------------------------------------------------------------------

def populate_thinking_chain(case_data: Dict[str, Any], stage_records: List[Dict[str, Any]]) -> None:
    """将 A0-A9 阶段记录注入 thinking_chain。"""
    chain = []
    for sr in stage_records:
        entry = {
            "stage": sr.get("stage", "A0"),
            "ts": sr.get("ts"),
            "decision": sr.get("decision", ""),
            "rationale": sr.get("rationale"),
            "evidence_refs": sr.get("evidence_refs", []),
        }
        for optional_key in ("contradiction", "contradiction_analysis", "hypothesis",
                             "test_result", "exit_logic", "stage_output_ref"):
            val = sr.get(optional_key)
            if val is not None:
                entry[optional_key] = val
        chain.append(entry)
    case_data["thinking_chain"] = chain


def populate_evidence_chain(case_data: Dict[str, Any], evidence: Dict[str, List[Any]]) -> None:
    """注入证据链，仅覆盖提供的非空列表。"""
    ec = case_data.get("evidence_chain") or {
        "market_data_refs": [], "signal_refs": [],
        "strategy_refs": [], "historical_refs": [], "constraint_refs": []
    }
    for key in ("market_data_refs", "signal_refs", "strategy_refs",
                "historical_refs", "constraint_refs"):
        if key in evidence and evidence[key]:
            ec[key] = evidence[key]
    case_data["evidence_chain"] = ec


def populate_decision_outcome(case_data: Dict[str, Any], episode: Dict[str, Any]) -> None:
    """从 episode 数据填充 decision_outcome。"""
    do = case_data.get("decision_outcome") or {}
    for key in ("pnl_pct", "pnl_usdt", "drawdown"):
        v = episode.get(key)
        if v is not None:
            do[key] = float(v)
    exit_reason = episode.get("exit_reason") or episode.get("exit_signal")
    if exit_reason:
        do["exit_reason"] = str(exit_reason)
    goal = episode.get("goal_achieved")
    if goal is not None:
        do["goal_achieved"] = bool(goal)
    case_data["decision_outcome"] = do


def advance_l4_status(case_data: Dict[str, Any], new_status: str) -> None:
    """推进 L4 状态机。"""
    valid = {"M0_CASE_REGISTERED", "M1_REVIEW_COMPLETED", "M2_DISTILL_COMPLETED",
             "M3_STATS_UPDATED", "M4_CANDIDATE_EMITTED", "M_FAIL"}
    if new_status not in valid:
        raise ValueError(f"invalid l4_status: {new_status}")
    case_data["l4_status"] = new_status


def upgrade_case_to_v02(case_data: Dict[str, Any]) -> Dict[str, Any]:
    """将 v0.1 case 升级为 v0.2 格式（原地修改）。"""
    if case_data.get("version") == "v0.2":
        return case_data
    case_data["version"] = "v0.2"
    if "thinking_chain" not in case_data:
        case_data["thinking_chain"] = []
    if "evidence_chain" not in case_data:
        case_data["evidence_chain"] = {
            "market_data_refs": [], "signal_refs": [],
            "strategy_refs": [], "historical_refs": [], "constraint_refs": []
        }
    if "decision_outcome" not in case_data:
        case_data["decision_outcome"] = {
            "pnl_pct": None, "pnl_usdt": None, "drawdown": None,
            "exit_reason": None, "goal_achieved": None
        }
    if "l4_status" not in case_data:
        case_data["l4_status"] = "M0_CASE_REGISTERED"
    review = case_data.get("review") or {}
    review.setdefault("mistakes", [])
    review.setdefault("successes", [])
    review.setdefault("review_record_id", None)
    case_data["review"] = review
    return case_data


if __name__ == "__main__":
    main()
