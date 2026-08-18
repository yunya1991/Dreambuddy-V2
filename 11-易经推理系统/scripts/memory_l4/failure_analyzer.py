import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import artifacts_memory_l4_dir, memory_l4_cases_dir


def now_iso_local() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _list_json_files(dir_path: Path) -> List[Path]:
    if not dir_path.exists():
        return []
    return sorted([p for p in dir_path.glob("*.json") if p.is_file()])


def load_cases() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for p in _list_json_files(memory_l4_cases_dir()):
        out.append(load_json(p))
    return out


def _sanitize_token(value: str) -> str:
    text = (value or "").strip().lower()
    parts: List[str] = []
    for ch in text:
        if ch.isalnum():
            parts.append(ch)
        else:
            parts.append("_")
    token = "".join(parts).strip("_")
    while "__" in token:
        token = token.replace("__", "_")
    return token or "unknown"


def _extract_episode_pnl_and_reason(ep: Dict[str, Any]) -> Tuple[Optional[float], str]:
    out = ep.get("outcome") or {}
    # Keep reward-source priority aligned with bandit ingest behavior.
    for key in ("realized_pnl_pct", "unrealized_pnl_pct", "pnl_pct"):
        value = out.get(key)
        if value is not None:
            reason = str(
                out.get("exit_reason")
                or out.get("stop_reason")
                or out.get("reason")
                or "unknown"
            )
            return float(value), reason
    return None, str(out.get("exit_reason") or out.get("reason") or "unknown")


def _extract_episode_path(case: Dict[str, Any]) -> str:
    refs = ((case.get("execution") or {}).get("episode_refs") or [])
    if not refs:
        return ""
    return str((refs[0] or {}).get("path") or "")


def _build_risk_signal(signal_key: str, rows: List[Dict[str, Any]], snapshot_ts: str) -> Dict[str, Any]:
    first = rows[0] if rows else {}
    pnl_values = [float(r["pnl_pct"]) for r in rows]
    case_ids = [str(r["case_id"]) for r in rows]
    inst_ids = sorted({str(r["inst_id"]) for r in rows if str(r["inst_id"])})
    evidence_refs = [r["episode_ref"] for r in rows if r["episode_ref"]]
    avg_pnl = sum(pnl_values) / len(pnl_values) if pnl_values else 0.0
    fail_count = len(rows)
    severity = min(1.0, abs(avg_pnl) / 5.0)
    confidence = min(1.0, fail_count / 3.0)
    return {
        "risk_signal_id": f"RS_{signal_key}",
        "version": "v0.1",
        "kind": "risk_signal",
        "snapshot_ts": snapshot_ts,
        "regime": first.get("regime"),
        "reason": first.get("reason"),
        "inst_ids": inst_ids,
        "fail_count": fail_count,
        "avg_pnl_pct": round(avg_pnl, 4),
        "confidence": round(confidence, 4),
        "supporting_case_ids": case_ids,
        "evidence_refs": evidence_refs,
        "quadrant_hint": {"x": round(-severity, 4), "y": round(confidence, 4)},
    }


def _build_distill_candidate(signal: Dict[str, Any]) -> Dict[str, Any]:
    regime = str(signal.get("regime") or "unknown")
    reason = str(signal.get("reason") or "unknown")
    claim = f"{regime} under {reason} shows recurring downside risk."
    return {
        "distill_id": f"D_AUTO_{signal['risk_signal_id']}",
        "version": "v0.1",
        "kind": "risk_signal",
        "claim": claim,
        "supporting_case_ids": signal.get("supporting_case_ids") or [],
        "actionable_rules": [
            f"When regime={regime} and signal={reason}, tighten risk budget and require additional confirmation."
        ],
        "source_risk_signal_id": signal["risk_signal_id"],
        "quadrant": {
            "x": float((signal.get("quadrant_hint") or {}).get("x") or -0.2),
            "y": float((signal.get("quadrant_hint") or {}).get("y") or 0.3),
            "evidence": {
                "weights": {"perf": 0.4, "consistency": 0.4, "human": 0.2},
                "y_perf": float((signal.get("quadrant_hint") or {}).get("y") or 0.3),
                "y_consistency": float((signal.get("confidence") or 0.0)),
                "y_human": 0.0,
                "notes": "Auto-generated from failure analyzer v0.1",
            },
        },
        "migration_history": [],
    }


def _default_output_dir(snapshot_ts: str) -> Path:
    day = snapshot_ts[:10] if len(snapshot_ts) >= 10 else now_iso_local()[:10]
    return artifacts_memory_l4_dir() / "failure_analysis" / day


def analyze_failure_memory(
    snapshot_ts: str,
    cases: List[Dict[str, Any]],
    episodes_by_case_id: Dict[str, Dict[str, Any]],
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    total_failures = 0
    reason_counts: Dict[str, int] = {}

    for case in cases:
        case_id = str(case.get("case_id") or "")
        if not case_id:
            continue
        episode = episodes_by_case_id.get(case_id) or {}
        pnl_pct, reason = _extract_episode_pnl_and_reason(episode)
        if pnl_pct is None or pnl_pct >= 0.0:
            continue
        total_failures += 1
        reason_key = str(reason or "unknown")
        reason_counts[reason_key] = int(reason_counts.get(reason_key) or 0) + 1
        regime = str(((case.get("environment_snapshot") or {}).get("regime")) or "unknown")
        inst_id = str(case.get("inst_id") or "")
        signal_key = f"{_sanitize_token(regime)}_{_sanitize_token(reason_key)}"
        row = {
            "case_id": case_id,
            "inst_id": inst_id,
            "regime": regime,
            "reason": reason_key,
            "pnl_pct": float(pnl_pct),
            "episode_ref": _extract_episode_path(case),
        }
        groups.setdefault(signal_key, []).append(row)

    risk_signals: List[Dict[str, Any]] = []
    for key, rows in sorted(groups.items(), key=lambda x: len(x[1]), reverse=True):
        risk_signals.append(_build_risk_signal(key, rows, snapshot_ts))

    distill_candidates = [_build_distill_candidate(signal) for signal in risk_signals]

    out_dir = Path(output_dir) if output_dir is not None else _default_output_dir(snapshot_ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    risk_signals_path = out_dir / "risk_signals.jsonl"
    distill_candidates_path = out_dir / "distill_candidates.json"
    summary_path = out_dir / "summary.json"

    with risk_signals_path.open("w", encoding="utf-8") as f:
        for signal in risk_signals:
            f.write(json.dumps(signal, ensure_ascii=False) + "\n")

    distill_candidates_path.write_text(
        json.dumps(distill_candidates, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "version": "v0.1",
        "snapshot_ts": snapshot_ts,
        "total_cases": len(cases),
        "failed_cases": total_failures,
        "risk_signals_count": len(risk_signals),
        "distill_candidates_count": len(distill_candidates),
        "reason_counts": reason_counts,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "risk_signals_path": str(risk_signals_path),
        "distill_candidates_path": str(distill_candidates_path),
        "summary_path": str(summary_path),
        "summary": summary,
    }


def _load_episodes_from_case_refs(cases: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for c in cases:
        case_id = str(c.get("case_id") or "")
        if not case_id:
            continue
        raw = _extract_episode_path(c)
        if not raw:
            out[case_id] = {}
            continue
        p = Path(raw)
        if not p.is_absolute():
            p = _ROOT / p
        try:
            out[case_id] = load_json(p) if p.exists() else {}
        except Exception:
            out[case_id] = {}
    return out


def main() -> None:
    snapshot_ts = now_iso_local()
    cases = load_cases()
    episodes_by_case_id = _load_episodes_from_case_refs(cases)
    out = analyze_failure_memory(
        snapshot_ts=snapshot_ts,
        cases=cases,
        episodes_by_case_id=episodes_by_case_id,
        output_dir=None,
    )
    print(out["summary_path"])


if __name__ == "__main__":
    main()
