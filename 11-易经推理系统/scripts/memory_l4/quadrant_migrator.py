import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import memory_l4_cases_dir, memory_l4_distills_dir

PCT_SCALE = 5.0
USDT_SCALE = 50.0
MAG_PCT_SCALE = 2.0
MAG_USDT_SCALE = 20.0


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def _episode_pnl(ep: Dict[str, Any]) -> Tuple[Optional[float], Optional[float], bool]:
    out = ep.get("outcome") or {}
    pos = ep.get("position") or {}

    pnl_pct = out.get("unrealized_pnl_pct")
    pnl_usdt = out.get("unrealized_pnl_usdt")
    is_unrealized = False

    if pnl_usdt is None and out.get("unrealized_pnl") is not None:
        pnl_usdt = out.get("unrealized_pnl")
        is_unrealized = True
    if pnl_usdt is None and pos.get("upl") is not None:
        pnl_usdt = pos.get("upl")
        is_unrealized = True
    if pnl_usdt is not None and not is_unrealized:
        is_unrealized = True
    if pnl_pct is not None:
        is_unrealized = True

    return (
        float(pnl_usdt) if pnl_usdt is not None else None,
        float(pnl_pct) if pnl_pct is not None else None,
        is_unrealized,
    )


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_json(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def _read_episode_by_case(case: Dict[str, Any]) -> Dict[str, Any]:
    refs = ((case.get("execution") or {}).get("episode_refs") or [])
    if not refs:
        return {}
    p = str((refs[0] or {}).get("path") or "")
    if not p:
        return {}
    ep = Path(p)
    if not ep.is_absolute():
        ep = _ROOT / ep
    if not ep.exists():
        return {}
    try:
        return _load_json(ep)
    except Exception:
        return {}


def _consistency_score(n: int) -> float:
    if n <= 0:
        return 0.0
    if n == 1:
        return 0.2
    if n == 2:
        return 0.35
    if n == 3:
        return 0.5
    if n <= 5:
        return 0.65
    if n <= 8:
        return 0.75
    if n <= 13:
        return 0.85
    if n <= 21:
        return 0.95
    return 1.0


def compute_case_quadrant_update(case: Dict[str, Any], episode: Dict[str, Any]) -> Dict[str, Any]:
    old_q = case.get("quadrant") or {}
    evidence = dict((old_q.get("evidence") or {}))
    y_human = float(evidence.get("y_human") or 0.0)
    y_consistency = float(evidence.get("y_consistency") or 0.0)

    pnl_usdt, pnl_pct, is_unrealized = _episode_pnl(episode)

    if pnl_pct is not None:
        x = _clamp(pnl_pct / PCT_SCALE, -1.0, 1.0)
        magnitude = _clamp(abs(pnl_pct) / MAG_PCT_SCALE, 0.0, 1.0)
    elif pnl_usdt is not None:
        x = _clamp(pnl_usdt / USDT_SCALE, -1.0, 1.0)
        magnitude = _clamp(abs(pnl_usdt) / MAG_USDT_SCALE, 0.0, 1.0)
    else:
        x = float(old_q.get("x") or 0.0)
        magnitude = 0.0

    y_perf = magnitude
    if is_unrealized:
        y_perf = min(y_perf, 0.4)

    y = _clamp(0.4 * y_perf + 0.4 * y_consistency + 0.2 * y_human, 0.0, 1.0)
    evidence.update(
        {
            "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
            "y_perf": round(float(y_perf), 4),
            "y_consistency": round(float(y_consistency), 4),
            "y_human": round(float(y_human), 4),
        }
    )
    return {"x": round(float(x), 4), "y": round(float(y), 4), "evidence": evidence}


def update_distill_with_migration(
    distill: Dict[str, Any],
    episodes_by_case_id: Dict[str, Dict[str, Any]],
    snapshot_ts: str,
    epsilon: float = 0.05,
) -> Dict[str, Any]:
    out = dict(distill)
    old_q = out.get("quadrant") or {}
    old_y = float(old_q.get("y") or 0.0)
    evidence = dict((old_q.get("evidence") or {}))

    pnl_usdts: List[float] = []
    pnl_pcts: List[float] = []
    wins = 0
    valid = 0
    all_unrealized = True
    for cid in (out.get("supporting_case_ids") or []):
        ep = episodes_by_case_id.get(str(cid)) or {}
        pnl_usdt, pnl_pct, is_unrealized = _episode_pnl(ep)
        if pnl_usdt is None and pnl_pct is None:
            continue
        valid += 1
        if not is_unrealized:
            all_unrealized = False
        if pnl_pct is not None:
            pnl_pcts.append(float(pnl_pct))
            if pnl_pct > 0:
                wins += 1
        elif pnl_usdt is not None:
            pnl_usdts.append(float(pnl_usdt))
            if pnl_usdt > 0:
                wins += 1

    win_rate = float(wins) / float(valid) if valid > 0 else 0.0
    if pnl_pcts:
        avg_abs = sum(abs(x) for x in pnl_pcts) / len(pnl_pcts)
        magnitude = _clamp(avg_abs / MAG_PCT_SCALE, 0.0, 1.0)
    elif pnl_usdts:
        avg_abs = sum(abs(x) for x in pnl_usdts) / len(pnl_usdts)
        magnitude = _clamp(avg_abs / MAG_USDT_SCALE, 0.0, 1.0)
    else:
        magnitude = 0.0

    y_perf = _clamp(0.5 * win_rate + 0.5 * magnitude, 0.0, 1.0)
    if valid > 0 and all_unrealized:
        y_perf = min(y_perf, 0.4)

    y_consistency = _consistency_score(len(out.get("supporting_case_ids") or []))
    y_human = float(evidence.get("y_human") or 0.0)
    y_new = _clamp(0.4 * y_perf + 0.4 * y_consistency + 0.2 * y_human, 0.0, 1.0)

    evidence.update(
        {
            "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
            "y_perf": round(float(y_perf), 4),
            "y_consistency": round(float(y_consistency), 4),
            "y_human": round(float(y_human), 4),
        }
    )
    out["quadrant"] = {
        "x": float(old_q.get("x") or 0.0),
        "y": round(float(y_new), 4),
        "evidence": evidence,
    }

    history = list(out.get("migration_history") or [])
    if abs(y_new - old_y) >= float(epsilon):
        history.append(
            {
                "ts": snapshot_ts,
                "y_prev": round(float(old_y), 4),
                "y_new": round(float(y_new), 4),
                "reason": "performance_update",
                "note": f"supporting_cases={len(out.get('supporting_case_ids') or [])}",
            }
        )
    out["migration_history"] = history
    return out


def run_quadrant_migration(snapshot_ts: Optional[str] = None) -> Dict[str, int]:
    ts = snapshot_ts or datetime.now().astimezone().isoformat(timespec="seconds")
    cases = [_load_json(p) for p in _list_json(memory_l4_cases_dir())]
    distills = [_load_json(p) for p in _list_json(memory_l4_distills_dir())]

    episodes_by_case_id: Dict[str, Dict[str, Any]] = {}
    updated_cases = 0
    for case in cases:
        cid = str(case.get("case_id") or "")
        ep = _read_episode_by_case(case)
        if cid:
            episodes_by_case_id[cid] = ep
        new_q = compute_case_quadrant_update(case, ep)
        case["quadrant"] = new_q
        path = memory_l4_cases_dir() / f"{cid}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated_cases += 1

    updated_distills = 0
    for distill in distills:
        did = str(distill.get("distill_id") or "")
        out = update_distill_with_migration(distill, episodes_by_case_id, snapshot_ts=ts)
        path = memory_l4_distills_dir() / f"{did}.json"
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        updated_distills += 1

    return {"cases": updated_cases, "distills": updated_distills}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-ts", required=False)
    args = parser.parse_args()
    out = run_quadrant_migration(snapshot_ts=args.snapshot_ts)
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
