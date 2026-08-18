import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _reward_from_episode(episode: Dict[str, Any], unrealized_discount: float) -> float:
    outcome = (episode or {}).get("outcome") or {}
    pnl_pct = float(outcome.get("unrealized_pnl_pct") or 0.0)
    # Map pnl in [-5, 5] roughly to [0, 1], then apply unrealized discount.
    normalized = _clamp01((pnl_pct + 5.0) / 10.0)
    return _clamp01(normalized * float(unrealized_discount))


def update_bandit_scores(
    events: Iterable[Dict[str, Any]],
    state: Dict[str, Dict[str, Any]],
    unrealized_discount: float = 0.7,
    default_reason: str = "",
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    new_state: Dict[str, Dict[str, Any]] = {str(k): dict(v) for k, v in (state or {}).items()}
    updates: List[Dict[str, Any]] = []

    for event in events or []:
        item_id = str(event.get("item_id") or "")
        if not item_id:
            continue
        reward = _reward_from_episode(event.get("episode") or {}, unrealized_discount)
        reason = str(event.get("reason") or default_reason or "")
        item = dict(new_state.get(item_id) or {})
        old_n = int(item.get("n") or 0)
        old_sum = float(item.get("reward_sum") or (float(item.get("reward_mean") or 0.0) * old_n))
        new_n = old_n + 1
        new_sum = old_sum + reward
        new_mean = new_sum / float(new_n)
        item.update({"n": new_n, "reward_sum": round(new_sum, 6), "reward_mean": round(new_mean, 6)})
        new_state[item_id] = item
        updates.append(
            {
                "item_id": item_id,
                "reward": round(reward, 6),
                "old_n": old_n,
                "new_n": new_n,
                "reward_mean": round(new_mean, 6),
                "ts": event.get("ts"),
                "reason": reason,
            }
        )
    return new_state, updates


def score_with_ucb(item_id: str, state: Dict[str, Dict[str, Any]], total_steps: int, c: float = 1.0) -> float:
    item = (state or {}).get(str(item_id)) or {}
    n = max(0, int(item.get("n") or 0))
    mean = float(item.get("reward_mean") or 0.0)
    denom = float(max(1, n))
    bonus = float(c) * math.sqrt(math.log(float(max(2, int(total_steps) + 1))) / denom)
    return max(0.0, mean + bonus)


def write_bandit_audit_artifact(updates: List[Dict[str, Any]], context: Dict[str, Any], audit_dir: Path) -> str:
    audit_root = Path(audit_dir)
    audit_root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    stamp = ts.replace(":", "").replace("-", "")
    trace_id = str((context or {}).get("trace_id") or "no-trace")
    path = audit_root / f"bandit_audit_{trace_id}_{stamp}.json"
    reason_counts: Dict[str, int] = defaultdict(int)
    for u in updates or []:
        r = str((u or {}).get("reason") or (context or {}).get("reason") or "unknown")
        reason_counts[r] += 1

    payload = {
        "audit_schema_version": "v0.1",
        "ts": ts,
        "trace_id": trace_id,
        "reason": (context or {}).get("reason"),
        "updates": updates or [],
        "summary": {
            "updates_count": len(updates or []),
            "reason_counts": dict(reason_counts),
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(path)
