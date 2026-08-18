import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.memory_l4.paths import artifacts_memory_l4_dir


def _clamp(x: float, low: float, high: float) -> float:
    return max(low, min(high, x))


def _extract_pnl_reason(ep: Dict[str, Any]) -> Tuple[Optional[float], str]:
    out = ep.get("outcome") or {}
    for key in ("realized_pnl_pct", "unrealized_pnl_pct", "pnl_pct"):
        value = out.get(key)
        if value is not None:
            reason = str(out.get("exit_reason") or out.get("stop_reason") or out.get("reason") or "unknown")
            return float(value), reason
    return None, str(out.get("exit_reason") or out.get("reason") or "unknown")


def _inst_to_market(inst_id: str) -> str:
    token = (inst_id or "").strip().upper()
    if "-" in token:
        return token.split("-", 1)[0]
    return token or "UNKNOWN"


def _default_output_dir(snapshot_ts: str) -> Path:
    day = snapshot_ts[:10] if len(snapshot_ts) >= 10 else datetime.now().astimezone().strftime("%Y-%m-%d")
    return artifacts_memory_l4_dir() / "cross_market_migration" / day


def _compute_confidence(rows: List[Dict[str, Any]]) -> float:
    support_count = len(rows)
    sample_support = _clamp(float(support_count) / 5.0, 0.0, 1.0)
    pnl_vals = [float(r.get("pnl_pct") or 0.0) for r in rows]
    neg_count = len([x for x in pnl_vals if x < 0.0])
    consistency = _clamp(float(neg_count) / float(support_count), 0.0, 1.0) if support_count > 0 else 0.0

    mean_abs = sum(abs(x) for x in pnl_vals) / len(pnl_vals) if pnl_vals else 0.0
    if pnl_vals:
        variance = sum((abs(x) - mean_abs) ** 2 for x in pnl_vals) / len(pnl_vals)
        std = variance ** 0.5
        stability = _clamp(1.0 - (std / max(mean_abs, 1e-6)), 0.0, 1.0)
    else:
        stability = 0.0

    confidence = 0.5 * sample_support + 0.3 * consistency + 0.2 * stability
    return round(_clamp(confidence, 0.0, 1.0), 4)


def build_cross_market_migration(
    snapshot_ts: str,
    source_market: str,
    target_market: str,
    source_items: List[Dict[str, Any]],
    episodes_by_case_id: Dict[str, Dict[str, Any]],
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    source_market_norm = str(source_market or "").strip().upper()
    target_market_norm = str(target_market or "").strip().upper()
    eligible_rows: List[Dict[str, Any]] = []
    by_key: Dict[str, List[Dict[str, Any]]] = {}

    for item in source_items:
        case_id = str(item.get("case_id") or "")
        if not case_id:
            continue
        inst_id = str(item.get("inst_id") or "")
        market = _inst_to_market(inst_id)
        if market != source_market_norm:
            continue
        ep = episodes_by_case_id.get(case_id) or {}
        pnl_pct, reason = _extract_pnl_reason(ep)
        if pnl_pct is None or pnl_pct >= 0.0:
            continue

        regime = str(((item.get("environment_snapshot") or {}).get("regime")) or "unknown")
        row = {
            "case_id": case_id,
            "inst_id": inst_id,
            "market": market,
            "regime": regime,
            "risk_reason": reason,
            "pnl_pct": float(pnl_pct),
        }
        eligible_rows.append(row)
        key = f"{regime}||{reason}"
        by_key.setdefault(key, []).append(row)

    mappings: List[Dict[str, Any]] = []
    for key, rows in sorted(by_key.items(), key=lambda x: len(x[1]), reverse=True):
        regime, risk_reason = key.split("||", 1)
        confidence = _compute_confidence(rows)
        mappings.append(
            {
                "source": {
                    "market": source_market_norm,
                    "regime": regime,
                    "risk_reason": risk_reason,
                },
                "target": {
                    "market": target_market_norm,
                    "regime": regime,
                    "risk_reason": risk_reason,
                },
                "migration_confidence": confidence,
                "support_count": len(rows),
                "supporting_case_ids": [str(r["case_id"]) for r in rows],
            }
        )

    out_dir = Path(output_dir) if output_dir is not None else _default_output_dir(snapshot_ts)
    out_dir.mkdir(parents=True, exist_ok=True)
    mapping_table_path = out_dir / "mapping_table.json"
    artifact_path = out_dir / "migration_artifact.jsonl"
    summary_path = out_dir / "summary.json"

    mapping_payload = {
        "version": "v0.1",
        "snapshot_ts": snapshot_ts,
        "source_market": source_market_norm,
        "target_market": target_market_norm,
        "mappings": mappings,
    }
    mapping_table_path.write_text(json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with artifact_path.open("w", encoding="utf-8") as f:
        for m in mappings:
            rec = {
                "ts": snapshot_ts,
                "event": "cross_market_migration",
                "source_market": source_market_norm,
                "target_market": target_market_norm,
                "regime": m["source"]["regime"],
                "risk_reason": m["source"]["risk_reason"],
                "migration_confidence": m["migration_confidence"],
                "support_count": m["support_count"],
                "supporting_case_ids": m["supporting_case_ids"],
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    confidences = [float(m["migration_confidence"]) for m in mappings]
    summary = {
        "version": "v0.1",
        "snapshot_ts": snapshot_ts,
        "source_market": source_market_norm,
        "target_market": target_market_norm,
        "total_items": len(source_items),
        "eligible_items": len(eligible_rows),
        "mappings_count": len(mappings),
        "confidence": {
            "min": round(min(confidences), 4) if confidences else None,
            "max": round(max(confidences), 4) if confidences else None,
            "avg": round(sum(confidences) / len(confidences), 4) if confidences else None,
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "mapping_table_path": str(mapping_table_path),
        "artifact_path": str(artifact_path),
        "summary_path": str(summary_path),
        "summary": summary,
    }
