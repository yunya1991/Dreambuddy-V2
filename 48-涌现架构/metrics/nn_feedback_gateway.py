"""nn_feedback_gateway.py — 48 → 40 训练/反馈网关（P0）。

仅做“聚合 → 建议 → 输出”，不直接改 40 权重、不下单（SPEC-NN-FEEDBACK-GATEWAY §3/§7）。

输出：`events/nn_feedback/40_feedback.json`
  {gateway_version, generated_at, data_version, source_window,
   factor_priors, contradiction_priors, direction_priors,
   training_suggestions, quality}

开关：`ENABLE_40_VIA_48`（默认关，双读校验通过后才允许 40 切换）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = _REPO_ROOT / "48-涌现架构" / "events" / "nn_feedback" / "40_feedback.json"
FACTOR_PRIOR = _REPO_ROOT / "18-数据获取中心" / "backfill" / "p3c1" / "factor_prior.json"
GATEWAY_VERSION = "nn_feedback_gateway.v0.1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def gate_enabled() -> bool:
    return os.getenv("ENABLE_40_VIA_48", "0").strip().lower() in {"1", "true", "yes", "on"}


def _data_version(events: List[Dict[str, Any]]) -> str:
    seed = "|".join(sorted(str(e.get("event_id", "")) for e in events))
    return "DV-" + hashlib.sha256(seed.encode()).hexdigest()[:12]


def _is_complete(ev: Dict[str, Any]) -> bool:
    execution = ev.get("execution") or {}
    return bool(execution.get("outcome") or execution.get("order_id") or execution.get("fill"))


def load_factor_prior(path: Optional[Path] = None) -> Dict[str, Any]:
    path = Path(path) if path else FACTOR_PRIOR
    try:
        if path.exists():
            obj = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(obj, dict):
                return obj
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("factor_prior 读取失败（降级）: %s", exc)
    return {}


def build_feedback(
    events: Iterable[Dict[str, Any]],
    factor_prior: Optional[Dict[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    evs = [e for e in events if isinstance(e, dict)]
    ts_list = sorted(str(e.get("ts")) for e in evs if e.get("ts"))
    contradiction = Counter(
        str((e.get("decision") or {}).get("primary_contradiction"))
        for e in evs
        if (e.get("decision") or {}).get("primary_contradiction")
    )
    directions: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in evs:
        symbol = str(e.get("symbol", "unknown"))
        action = str((e.get("decision") or {}).get("action", "unknown"))
        directions[symbol][action] += 1

    n_complete = sum(1 for e in evs if _is_complete(e))
    n = len(evs)
    suggestions: List[Dict[str, Any]] = []
    if n:
        suggestions.append(
            {
                "suggestion_id": "S40-" + _data_version(evs)[3:],
                "target": "40",
                "type": "regime_prior_hint",
                "payload": {
                    "direction_priors": {k: dict(v) for k, v in directions.items()},
                    "top_contradiction": (
                        contradiction.most_common(1)[0][0] if contradiction else None
                    ),
                },
                "evidence_count": n,
                "provenance": {"gateway": GATEWAY_VERSION, "advisory_only": True},
            }
        )

    return {
        "gateway_version": GATEWAY_VERSION,
        "generated_at": generated_at or _now_iso(),
        "data_version": _data_version(evs),
        "source_window": {
            "n_events": n,
            "first_ts": ts_list[0] if ts_list else None,
            "last_ts": ts_list[-1] if ts_list else None,
        },
        "factor_priors": factor_prior if factor_prior is not None else {},
        "contradiction_priors": [{"key": k, "count": c} for k, c in contradiction.most_common(20)],
        "direction_priors": {k: dict(v) for k, v in directions.items()},
        "training_suggestions": suggestions,
        "quality": {
            "n_complete": n_complete,
            "n_incomplete": n - n_complete,
            "join_coverage": round(n_complete / n, 4) if n else 0.0,
        },
    }


def write_feedback(feedback: Dict[str, Any], out_path: Optional[Path] = None) -> Dict[str, Any]:
    target = Path(out_path) if out_path else DEFAULT_OUT
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(target)
        return {"status": "written", "path": str(target)}
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("写 40_feedback 失败（降级）: %s", exc)
        return {"status": "error", "path": str(target), "error": str(exc)}


def load_feedback(out_path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    target = Path(out_path) if out_path else DEFAULT_OUT
    try:
        if target.exists():
            obj = json.loads(target.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) else None
    except Exception as exc:  # noqa: BLE001 — FAIL-OPEN
        logger.warning("读 40_feedback 失败（降级）: %s", exc)
    return None


def verify_dual_read(
    direct: Dict[str, Any], via48: Dict[str, Any], tolerance: float = 0.1
) -> Dict[str, Any]:
    """双读校验：数值按容差、字符串按相等；只比较双方共有的 key。"""
    diffs: Dict[str, float] = {}
    mismatches: List[str] = []
    for key in sorted(set(direct) & set(via48)):
        a, b = direct[key], via48[key]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            diffs[key] = abs(float(a) - float(b))
        elif a != b:
            mismatches.append(key)
    consistent = all(v <= tolerance for v in diffs.values()) and not mismatches
    return {"consistent": consistent, "diffs": diffs, "mismatches": mismatches}


def build_and_write(
    events: Iterable[Dict[str, Any]], out_path: Optional[Path] = None
) -> Dict[str, Any]:
    feedback = build_feedback(events, factor_prior=load_factor_prior())
    feedback["write"] = write_feedback(feedback, out_path=out_path)
    return feedback


def main(argv: Optional[List[str]] = None) -> int:
    """一键跑通：50 decisions → TrainingEvent 落盘 → 40_feedback.json。"""
    import argparse

    from training_events import DEFAULT_DIR as EVENTS_DIR
    from training_events import backfill_from_decisions, load_events

    parser = argparse.ArgumentParser(description="48→40 NN feedback gateway")
    parser.add_argument(
        "--decisions",
        default=str(_REPO_ROOT / "50-NN主矛盾评估器" / "runtime" / "decisions.jsonl"),
    )
    parser.add_argument("--events-dir", default=str(EVENTS_DIR))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)

    stats = backfill_from_decisions(Path(args.decisions))
    events = load_events(Path(args.events_dir))
    feedback = build_feedback(events, factor_prior=load_factor_prior())
    feedback["backfill"] = stats
    feedback["write"] = write_feedback(feedback, out_path=Path(args.out))
    print(
        json.dumps(
            {
                "backfill": stats,
                "n_events": feedback["source_window"]["n_events"],
                "join_coverage": feedback["quality"]["join_coverage"],
                "write": feedback["write"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
